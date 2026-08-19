"""
Image Agent v2.1 — 图片内容审核（VL提取+文本管线分类）
1. Qwen3-VL 多维度提取：OCR文字 + 场景描述 + 违规信号
2. 文本审核管线二次分类（DeepSeek）
3. dHash 相似图片匹配
4. 增强风险评分

设计原理：VL 模型擅长视觉感知（OCR+描述）但不如 LLM 擅长分类
→ 最优策略：VL 提取特征 → LLM 分类 → 结果融合
"""
import os
import json
import logging
import base64
from io import BytesIO
from agent_moderation.state import ModerationState
from agent_moderation.agents.base import BaseAgent
from memory.manager import get_memory_manager
from mcp_servers.registry import get_tool_registry
from common.api_clients import get_deepseek_model
from common.config import get_settings

logger = logging.getLogger(__name__)

# VL 提取 Prompt — 多维度视觉感知
VL_EXTRACTION_PROMPT = """你是专业的视觉内容分析专家。请仔细观察图片，从以下维度提取信息：

1. OCR文字：提取图片中所有可见文字（中文、英文、数字、符号），逐行输出
2. 场景描述：详细描述图片中的场景、物体、人物、动作
3. 可疑元素：识别二维码、微信号/QQ号/手机号、水印、网址链接、广告横幅

请以JSON格式返回（只返回JSON）：
{
  "ocr_text": "图中所有文字内容，逐行提取",
  "scene_description": "详细的场景描述",
  "has_qrcode": false,
  "has_contact": false,
  "has_watermark": false,
  "has_website": false,
  "suspicious_elements": ["可疑元素1", "可疑元素2"],
  "overall_impression": "图片给人的整体印象（如：风景照/广告海报/聊天截图/证件照等）"
}"""

# v3.4: VL 上下文感知 Prompt — 图片 + 周围文本联合分析
VL_CONTEXTUAL_PROMPT = """你是多模态内容安全审核专家。
请结合【周围文本上下文】分析图片，判断图文联合是否存在违规。

## 周围文本上下文 (图片前)
{context_before}

========== [图片位置] ==========

## 周围文本上下文 (图片后)
{context_after}

## 该段文本的审核摘要
{text_signal_summary}

## 分析要求
1. **图片内容描述**: 详细描述图片中的场景、物体、人物、动作
2. **OCR文字提取**: 提取图片中所有可见文字
3. **图文关系判断** (重要):
   - supplement: 图片正常展示/补充文本描述的内容
   - contradict: 图片内容与文本声称不一致 (可疑)
   - cipher: 图片含隐晦信息配合文本暗示违规 (高风险)
   - decoration: 图片与文本无关, 仅为装饰
4. **联合风险评估**: 结合文本上下文, 图片是否强化了违规嫌疑？
5. **可疑元素**: 二维码、联系方式、水印、网址等

请以JSON格式返回（只返回JSON）：
{{
  "ocr_text": "图中所有文字内容",
  "scene_description": "详细的场景描述",
  "text_image_relation": "supplement|contradict|cipher|decoration",
  "relation_detail": "图文关系的详细说明 (50-150字)",
  "joint_risk_assessment": "图文联合风险评估 (50-150字)",
  "has_qrcode": false,
  "has_contact": false,
  "has_watermark": false,
  "has_website": false,
  "suspicious_elements": ["可疑元素"],
  "overall_impression": "整体印象"
}}"""


class ImageAgent(BaseAgent):
    """图片审核 Agent v2.1 — VL提取 + LLM分类 + 黑灰产检测"""

    # 类级共享: 黑灰产检测器
    _pattern_detector = None
    _adversarial_detector = None

    @classmethod
    def _get_pattern_detector(cls):
        if cls._pattern_detector is None:
            from agent_moderation.blackhat.pattern_detector import PatternDetector
            cls._pattern_detector = PatternDetector()
        return cls._pattern_detector

    @classmethod
    def _get_adversarial_detector(cls):
        if cls._adversarial_detector is None:
            from agent_moderation.blackhat.adversarial_detector import AdversarialDetector
            cls._adversarial_detector = AdversarialDetector()
        return cls._adversarial_detector

    def __init__(self):
        super().__init__("image_agent")
        self.memory = get_memory_manager()
        self.history_tool = get_tool_registry().get_history_search()
        settings = get_settings()
        self._mock_mode = settings.image_agent_mock
        self._vl_client = None
        self._text_client = None
        if not self._mock_mode:
            try:
                from common.api_clients import get_vl_model_client, get_deepseek_client, get_deepseek_model
                self._vl_client = get_vl_model_client()
                self._text_client = get_deepseek_client()
                logger.info("ImageAgent: VL+LLM clients ready (REAL MODE)")
            except Exception as e:
                # R22: 不静默回退 mock（禁止伪造结果）。
                # VL 不可用时标记 client 缺失，process 阶段返回显式 error 状态。
                logger.error(f"ImageAgent: VL client init failed (NO mock fallback): {e}")
                self._vl_client = None
        else:
            logger.info("ImageAgent: Mock mode (显式配置 IMAGE_AGENT_MOCK=true)")

    async def process(self, state: ModerationState) -> ModerationState:
        """图片审核全流程 v3.5 — 支持上下文感知 VL 分析"""
        import time as _time
        content = state.get("content", {})
        image_data = content.get("image") or content.get("image_data") or b""

        if not image_data:
            state["image_result"] = {"error": "empty image", "risk_score": 0.0}
            return state

        # v3.5: 读取图片上下文 (由 file_agent_node 设置)
        image_context = content.get("image_context") or {}
        context_before = image_context.get("before", "")
        context_after = image_context.get("after", "")
        has_context = bool(context_before or context_after)
        filename = content.get("filename", "unknown")

        ctx_info = f", ctx={len(context_before)}+{len(context_after)} chars" if has_context else ""
        self.log_step(f"Analyzing image: {filename} {len(image_data)} bytes (mock={self._mock_mode}){ctx_info}")
        await self.memory.update_task_step(state["content_id"], "image_agent")

        # 1. 基础图像分析
        basic_info = self._analyze_basic(image_data)

        # 2. VL 提取特征 — v3.5: 有上下文时用上下文感知分析
        # R22: 真实模式下 VL client 缺失 → 显式 error（禁止 mock 伪造）
        if self._mock_mode:
            vl_result = self._mock_analyze(image_data, basic_info)
        elif self._vl_client is None:
            state["image_result"] = {"error": "VL client unavailable (image_agent_mock=false 但 QWEN_VL_API_KEY 未配置)",
                                     "risk_score": 0.0, "mock_mode": False}
            return state
        elif has_context:
            vl_result = await self._vl_extract_with_context(
                image_data,
                context_before=context_before,
                context_after=context_after,
                text_signal_summary="",
            )
        else:
            vl_result = await self._vl_extract(image_data)

        self.log_step(f"VL extracted: {vl_result.get('ocr_text', '')[:80]}..."
                     f"{' (contextual)' if has_context else ''}")

        # P1: VL 模型不可用 → 图片无法分析 → 标记待人工复核, 而非静默判 none (防漏审)
        if vl_result.get("_vl_failed"):
            self.log_step("⚠️ VL 分析不可用, 图片标记为待人工复核 (不静默放行)")
            result = {
                "basic_info": basic_info,
                "ocr_text": "",
                "scene_description": vl_result.get("scene_description", "VL 不可用"),
                "suspicious_elements": [],
                "violation_type": "unknown",
                "confidence": 0.5,
                "reason": f"VL 模型不可用, 图片无法分析, 建议人工复核: {str(vl_result.get('scene_description',''))[:100]}",
                "has_qrcode": False, "has_contact": False, "has_watermark": False,
                "tags": ["vl_unavailable"],
                "similar_cases_count": 0,
                "hash_similarity": 0.0,
                "risk_score": 0.55,   # 中风险 → 保证进入 REVIEW 人工复核, 不 PASS
                "mock_mode": self._mock_mode,
                "filename": filename,
                "has_context": has_context,
                "vl_failed": True,
            }
            state["image_result"] = result
            return state

        # v3.7: 黑灰产检测 — 对 VL 提取的文字做违规模式 + 对抗样本检测
        ocr_text = vl_result.get("ocr_text", "")
        patterns, adversarials, bh_score, is_blackhat = [], [], 0.0, False
        if ocr_text:
            patterns = self._get_pattern_detector().detect_all(ocr_text)
            adversarials = self._get_adversarial_detector().detect_all(ocr_text)
            bh_score = self._calculate_blackhat_score(patterns, adversarials)
            is_blackhat = bh_score >= 0.4
            if patterns or adversarials:
                self.log_step(
                    f"Blackhat: {len(patterns)} patterns + {len(adversarials)} adversarial "
                    f"→ score={bh_score:.2f} {'⚠️' if is_blackhat else '✅'}"
                )

        # 3. 历史相似案例检索 (v3.6: 提前到 LLM 之前，结果注入分类 Prompt)
        similar_cases = []
        rag_start = _time.time()
        try:
            ocr_text = vl_result.get("ocr_text", "")
            if ocr_text:
                history_result = await self._call_mcp_tool("history_search", query=ocr_text, top_k=3)
                # R22: MCP Gateway 返回 SimpleNamespace，统一转 dict 供 .get() 访问
                similar_cases = self._to_dict_list(history_result.cases if history_result.has_match else [])
                self.log_rag(ocr_text, similar_cases, (_time.time() - rag_start) * 1000)
        except Exception:
            similar_cases = []

        # 4. 用提取的文本做文本审核分类 — v3.6: 注入 RAG 案例和上下文
        text_for_classification = self._build_classification_text(vl_result, basic_info)
        if has_context:
            ctx_summary = f"\n[图片周围文本上下文]\n前: {context_before[:200]}\n后: {context_after[:200]}"
            text_for_classification = text_for_classification + ctx_summary
        ocr_text_val = vl_result.get("ocr_text", "")
        scene_desc_val = vl_result.get("scene_description", "")
        classification = await self._classify_text(
            text_for_classification, similar_cases,
            ocr_text=ocr_text_val, scene_description=scene_desc_val,
            content_id=state.get("content_id", "")
        )

        # 5. dHash 相似图片检测
        import base64 as _b64
        hash_result = await self._call_mcp_tool(
            "image_hash",
            image_data=_b64.b64encode(image_data).decode("utf-8"),
            threshold=10,
        )

        # 6. 风险评分 — v3.5: 纳入图文关系信号
        risk_score = self._calculate_risk_score_v2(
            vl_result, classification, basic_info, hash_result, similar_cases
        )

        # API 内容过滤 → 判定为违规
        if vl_result.get("_content_filtered"):
            classification = {"violation_type": "porn", "confidence": 0.95,
                              "reason": "API内容安全过滤 — 图片包含违规内容", "tags": ["api_content_filter"]}

        result = {
            "basic_info": basic_info,
            "ocr_text": vl_result.get("ocr_text", ""),
            "scene_description": vl_result.get("scene_description", ""),
            "suspicious_elements": vl_result.get("suspicious_elements", []),
            "violation_type": classification.get("violation_type", "none"),
            "confidence": classification.get("confidence", 0.0),
            "reason": classification.get("reason", ""),
            "has_qrcode": vl_result.get("has_qrcode", False),
            "has_contact": vl_result.get("has_contact", False),
            "has_watermark": vl_result.get("has_watermark", False),
            "tags": classification.get("tags", []),
            "similar_cases_count": len(similar_cases),
            "hash_similarity": hash_result.similarity if hash_result else 0.0,
            "risk_score": risk_score,
            "mock_mode": self._mock_mode,
            "filename": filename,
            # v3.5: 上下文感知字段
            "has_context": has_context,
            # v3.7: 黑灰产检测结果
            "blackhat_patterns": [
                {"type": p.pattern_type, "name": p.pattern_name, "confidence": p.confidence,
                 "evidence": p.evidence[:3], "risk_score": p.risk_score}
                for p in patterns
            ],
            "adversarial_techniques": [
                {"technique": a.technique, "confidence": a.confidence,
                 "evidence": a.evidence[:3], "risk_score": a.risk_score}
                for a in adversarials
            ],
            "is_blackhat": is_blackhat,
            "blackhat_risk_score": bh_score,
        }

        # v3.5: 附加图文关系分析结果
        if has_context:
            result["text_image_relation"] = vl_result.get("text_image_relation", "unknown")
            result["relation_detail"] = vl_result.get("relation_detail", "")
            result["joint_risk_assessment"] = vl_result.get("joint_risk_assessment", "")

        state["image_result"] = result

        if hash_result and hash_result.hash_hex:
            get_tool_registry().get_image_hash().store_hash(state["content_id"], image_data)

        return state

    def _build_classification_text(self, vl_result: dict, basic_info: dict) -> str:
        """构建用于分类的文本"""
        parts = []
        ocr = vl_result.get("ocr_text", "")
        if ocr:
            parts.append(f"图片中的文字:\n{ocr}")
        desc = vl_result.get("scene_description", "")
        if desc:
            parts.append(f"场景描述:\n{desc}")
        impression = vl_result.get("overall_impression", "")
        if impression:
            parts.append(f"整体印象: {impression}")
        suspicious = vl_result.get("suspicious_elements", [])
        if suspicious:
            parts.append(f"可疑元素: {', '.join(suspicious)}")
        if vl_result.get("has_qrcode"):
            parts.append("图片包含二维码")
        if vl_result.get("has_contact"):
            parts.append("图片包含联系方式")
        if vl_result.get("has_watermark"):
            parts.append("图片包含水印")
        return "\n".join(parts)

    async def _classify_text(self, text: str, similar_cases: list = None,
                               ocr_text: str = '', scene_description: str = '',
                               content_id: str = '') -> dict:
        """用 DeepSeek 对提取的文本进行分类 (v3.6: 注入 RAG 案例, v5.0: 注入 Skill)"""
        import time as _t
        if not text.strip():
            return {"violation_type": "none", "confidence": 0.0, "reason": "无有效内容", "tags": []}

        try:
            t0 = _t.time()
            model = get_deepseek_model()

            # v3.6: 构建 RAG 案例注入
            rag_context = self._build_rag_context(similar_cases or [])
            # v5.0: 动态注入 Skill 知识（根据内容自动选择）
            # 使用 OCR 文本 + 场景描述作为查询
            query_text = f"{ocr_text}\n{scene_description}" if ocr_text else scene_description or ''
            skill_context = self._load_relevant_skills(
                query=query_text,
                content_type='image',
                max_inject=3,
                content_id=content_id,
            )
            system_content = TEXT_MODERATION_PROMPT
            if rag_context:
                system_content = system_content + "\n\n" + rag_context
            if skill_context:
                system_content = system_content + "\n\n" + skill_context

            response = await self._text_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": f"请分析以下图片提取内容是否违规：\n\n{text[:2000]}"},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=500,
            )
            # R22: 裸 json.loads 遇非 JSON 会静默降级 → 违规图被放行。改多级容错解析
            result = self._safe_json_parse(response.choices[0].message.content)
            if result is None:
                logger.warning(
                    f"Text classification JSON 解析失败（已重试兜底仍失败），"
                    f"按高风险降级处理: {str(response.choices[0].message.content)[:120]}")
                return {"violation_type": "unknown", "confidence": 0.5,
                        "reason": "LLM 分类响应无法解析，按需人工复核", "tags": ["parse_failed"]}
            # OpenTelemetry: LLM 调用追踪
            usage = response.usage
            self.trace_llm(model, usage.prompt_tokens if usage else len(text)//4,
                          usage.completion_tokens if usage else 100, (_t.time()-t0)*1000)
            self.log_llm(model, f"ocr={text[:50]}...",
                        f"type={result.get('violation_type','none')} conf={result.get('confidence',0):.2f}",
                        (_t.time()-t0)*1000)
            return result
        except Exception as e:
            logger.error(f"Text classification failed: {e}")
            return {"violation_type": "none", "confidence": 0.0, "reason": f"Classification error: {e}", "tags": []}

    def _build_rag_context(self, similar_cases: list) -> str:
        """将 RAG 检索结果格式化为 LLM Prompt 注入块"""
        if not similar_cases:
            return ""
        lines = ["## 参考案例（知识库检索的相似图片判定）"]
        lines.append("请参考以下历史图片案例的判定逻辑：\n")
        vt_cn = {"advertisement":"广告引流","porn":"色情低俗","violence":"暴力恐怖",
                 "false_info":"虚假信息","harassment":"辱骂骚扰","politics":"政治敏感","none":"正常"}
        for i, case in enumerate(similar_cases[:3], 1):
            sim = case.get("similarity", case.get("score", 0))
            vt = case.get("violation_type", "unknown")
            content = case.get("content", "")[:200]
            lines.append(f"> **案例 {i}** [相似度: {sim:.2f}] [判定: {vt_cn.get(vt, vt)}]")
            lines.append(f"> \"{content}\"")
            lines.append("")
        lines.append("如果当前图片内容与上述案例高度相似，请参照对应案例的判定结果。")
        return "\n".join(lines)

    def _analyze_basic(self, image_data: bytes) -> dict:
        info = {"size_bytes": len(image_data), "format": "unknown", "width": 0, "height": 0}
        try:
            from PIL import Image
            img = Image.open(BytesIO(image_data))
            info["format"] = img.format or "unknown"
            info["width"], info["height"] = img.size
            info["mode"] = img.mode
            info["aspect_ratio"] = round(img.width / max(img.height, 1), 2)
        except Exception as e:
            logger.warning(f"PIL image analysis failed: {e}")
        return info

    def _mock_analyze(self, image_data: bytes, basic_info: dict) -> dict:
        width, height, size_kb = basic_info.get("width", 0), basic_info.get("height", 0), basic_info.get("size_bytes", 0) / 1024
        suspicious = []
        if width > 0 and 0.8 < basic_info.get("aspect_ratio", 0) < 1.2 and width < 400:
            suspicious.append("小尺寸方形图(可能是二维码)")
        if size_kb > 500:
            suspicious.append("高分辨率图片")
        return {
            "ocr_text": "", "scene_description": f"测试图片 {width}x{height}",
            "has_qrcode": width < 400, "has_contact": False, "has_watermark": False,
            "has_website": False, "suspicious_elements": suspicious,
            "overall_impression": "mock分析图片"
        }

    async def _vl_extract(self, image_data: bytes) -> dict:
        """调用 Qwen3-VL 进行多维度特征提取"""
        import time as _t
        settings = get_settings()
        model = settings.qwen_vl_model
        try:
            t0 = _t.time()
            img_b64 = base64.b64encode(image_data).decode("utf-8")
            fmt = "jpeg"
            try:
                from PIL import Image
                img = Image.open(BytesIO(image_data))
                fmt = (img.format or "jpeg").lower()
            except Exception:
                pass

            data_url = f"data:image/{fmt};base64,{img_b64}"

            response = await self._vl_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": VL_EXTRACTION_PROMPT},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": "请提取图片中的文字和可疑元素"},
                    ]},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=800,
            )
            # R22: 多级容错解析 VL 响应
            result = self._safe_json_parse(response.choices[0].message.content)
            if result is None:
                raise ValueError("VL extraction 响应非 JSON，无法解析")
            # OpenTelemetry: VL API 调用追踪
            usage = response.usage
            self.trace_llm(model, usage.prompt_tokens if usage else 0,
                          usage.completion_tokens if usage else 200, (_t.time()-t0)*1000)
            logger.info(f"VL extraction: ocr={result.get('ocr_text','')[:60]}...")
            return result
        except Exception as e:
            error_str = str(e)
            # 阿里云内容安全拦截 → 视为高风险信号
            if "data_inspection_failed" in error_str or "inappropriate content" in error_str:
                logger.warning(f"VL content filter triggered! Treating as high-risk violation.")
                return {
                    "ocr_text": "[API内容安全拦截 — 图片包含违规内容]",
                    "scene_description": "阿里云API内容安全过滤器拒绝了此图片，表明图片内容严重违规",
                    "has_qrcode": False, "has_contact": False,
                    "has_watermark": False, "has_website": False,
                    "suspicious_elements": ["API_CONTENT_FILTER_TRIGGERED"],
                    "overall_impression": "API安全过滤 — 图片内容违规",
                    "_content_filtered": True,
                }
            logger.error(f"VL extraction failed: {e}")
            return {"ocr_text": "", "scene_description": f"Error: {e}", "has_qrcode": False,
                    "has_contact": False, "has_watermark": False, "has_website": False,
                    "suspicious_elements": [], "overall_impression": "error",
                    "_vl_failed": True}

    async def _vl_extract_with_context(
        self, image_data: bytes,
        context_before: str = "",
        context_after: str = "",
        text_signal_summary: str = "",
    ) -> dict:
        """
        v3.4: VL 上下文感知分析 — 图片 + 周围文本联合审核

        与 _vl_extract 的区别:
          - _vl_extract: 只看图片本身 (兼容旧逻辑)
          - _vl_extract_with_context: 看图片 + 周围文本, 判断图文关系

        Args:
            image_data: 图片字节
            context_before: 图片前的文本上下文 (最多500字)
            context_after: 图片后的文本上下文 (最多500字)
            text_signal_summary: 该段文本的信号卡摘要

        Returns:
            VL 分析结果 dict (含 text_image_relation 字段)
        """
        import time as _t
        settings = get_settings()
        model = settings.qwen_vl_model

        try:
            t0 = _t.time()
            img_b64 = base64.b64encode(image_data).decode("utf-8")
            fmt = "jpeg"
            try:
                from PIL import Image
                img = Image.open(BytesIO(image_data))
                fmt = (img.format or "jpeg").lower()
            except Exception:
                pass

            data_url = f"data:image/{fmt};base64,{img_b64}"

            # 构建上下文感知的 VL prompt
            prompt_text = VL_CONTEXTUAL_PROMPT.format(
                context_before=context_before[:500] or "[无上文]",
                context_after=context_after[:500] or "[无下文]",
                text_signal_summary=text_signal_summary or "[无文本摘要]",
            )

            response = await self._vl_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt_text},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": "请结合周围文本上下文分析此图片，判断图文关系及联合风险。"},
                    ]},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=1000,
            )
            # R22: 多级容错解析 VL 响应
            result = self._safe_json_parse(response.choices[0].message.content)
            if result is None:
                raise ValueError("VL contextual extraction 响应非 JSON，无法解析")

            usage = response.usage
            self.trace_llm(model, usage.prompt_tokens if usage else 0,
                          usage.completion_tokens if usage else 300, (_t.time()-t0)*1000)
            logger.info(f"VL contextual extraction: relation={result.get('text_image_relation', 'unknown')}")

            return result

        except Exception as e:
            error_str = str(e)
            if "data_inspection_failed" in error_str or "inappropriate content" in error_str:
                logger.warning(f"VL content filter triggered during contextual analysis")
                return {
                    "ocr_text": "[API内容安全拦截]",
                    "scene_description": "阿里云API内容安全过滤器拒绝了此图片",
                    "text_image_relation": "cipher",
                    "relation_detail": "API安全过滤 — 图片内容违规",
                    "joint_risk_assessment": "图片被API拦截, 联合风险极高",
                    "has_qrcode": False, "has_contact": False,
                    "has_watermark": False, "has_website": False,
                    "suspicious_elements": ["API_CONTENT_FILTER_TRIGGERED"],
                    "overall_impression": "API安全过滤 — 严重违规",
                    "_content_filtered": True,
                }
            logger.error(f"VL contextual extraction failed: {e}")
            return {
                "ocr_text": "", "scene_description": f"Error: {e}",
                "text_image_relation": "unknown",
                "relation_detail": f"VL分析失败: {str(e)[:100]}",
                "joint_risk_assessment": "",
                "has_qrcode": False, "has_contact": False,
                "has_watermark": False, "has_website": False,
                "suspicious_elements": [], "overall_impression": "error",
                "_vl_failed": True,
            }

    def _calculate_risk_score_v2(self, vl_result, classification, basic_info, hash_result, similar_cases) -> float:
        """增强风险评分"""
        # API 内容安全拦截 → 直接高风险
        if vl_result.get("_content_filtered"):
            return 0.85

        score = 0.0
        violation_type = classification.get("violation_type", "none")
        confidence = classification.get("confidence", 0.0)
        suspicious = vl_result.get("suspicious_elements", [])

        # 核心信号: 文本分类结果 (0.55)
        if violation_type != "none":
            type_scores = {"porn": 0.55, "violence": 0.55, "politics": 0.60,
                           "illegal": 0.55, "crime": 0.55, "advertisement": 0.45,
                           "false_info": 0.50, "harassment": 0.50}
            base = type_scores.get(violation_type, 0.45)
            conf_boost = min(confidence / 0.7, 1.3) if confidence > 0 else 0.3
            score += base * min(conf_boost, 1.2)

        # 视觉可疑元素 (0.20)
        score += min(len(suspicious) * 0.06, 0.20)

        # QR/联系方式/水印 (0.15)
        signals = [vl_result.get("has_qrcode"), vl_result.get("has_contact"),
                   vl_result.get("has_watermark"), vl_result.get("has_website")]
        score += min(sum(1 for s in signals if s) * 0.04, 0.15)

        # dHash 匹配 (0.10)
        if hash_result and hash_result.similarity > 0.7:
            score += min(hash_result.similarity * 0.10, 0.10)

        # 历史案例 (0.10)
        if similar_cases:
            sims = [c.get("similarity", 0) for c in similar_cases]
            if sims:
                score += (sum(sims) / len(sims)) * 0.10

        return round(min(score, 1.0), 4)

    @staticmethod
    def _calculate_blackhat_score(patterns: list, adversarials: list, account_risk: dict = None) -> float:
        """计算黑灰产综合风险分"""
        score = 0.0
        if patterns:
            max_pattern_score = max(p.risk_score for p in patterns)
            avg_pattern_score = sum(p.risk_score for p in patterns) / len(patterns)
            score += max_pattern_score * 0.25 + avg_pattern_score * 0.15
        if adversarials:
            max_adv_score = max(a.risk_score for a in adversarials)
            avg_adv_score = sum(a.risk_score for a in adversarials) / len(adversarials)
            score += max_adv_score * 0.2 + avg_adv_score * 0.1
        if account_risk:
            score += account_risk.get("risk_score", 0.0) * 0.3
        return round(min(score, 1.0), 4)


# 图文分类 Prompt — v2: 强化暴力/色情检测
TEXT_MODERATION_PROMPT = """你是严格的内容安全审核专家。分析从图片中提取的文字内容，判断是否违规。

审核标准（优先级从高到低）：
1. 暴力恐怖(violence)：杀戮、威胁杀人、武器制作、恐怖袭击、殴打 → 有则 confidence≥0.85
2. 色情低俗(porn)：裸聊、私密视频、成人内容、性暗示文字 → 有则 confidence≥0.85
3. 政治敏感(politics)：反动言论、分裂主张、敏感事件 → 有则 confidence≥0.85
4. 广告引流(advertisement)：微信/QQ/手机号引流、扫码诱导、赚钱广告 → 有则 confidence≥0.75
5. 虚假信息(false_info)：中奖诈骗、银行卡要求、谣言传播 → 有则 confidence≥0.80
6. 辱骂骚扰(harassment)：人身攻击、侮辱、网络暴力 → 有则 confidence≥0.80

关键原则：
- 只要文字中包含上述任何违规内容，violation_type 必须设为对应类型
- "杀人了""砍死你""炸弹制作" → violence, confidence ≥ 0.85
- "裸聊""私密视频""成人内容" → porn, confidence ≥ 0.85
- 如果内容安全，violation_type="none", confidence=0.0

请以JSON格式返回（只返回JSON）：
{
  "violation_type": "none|politics|porn|violence|false_info|harassment|advertisement",
  "confidence": 0.0-1.0,
  "reason": "简短判断依据",
  "is_adversarial": false,
  "tags": ["标签1","标签2"]
}"""
