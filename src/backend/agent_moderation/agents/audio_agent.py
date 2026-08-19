"""
Audio Agent v3.5 — 语音内容审核 (ASR + 说话人识别)

1. FunASR 语音转文本（STT）→ HTTP 服务端口 5001
2. 3D-Speaker 说话人识别（多人对话场景）→ 本地 ERes2NetV2/CAM++ 模型
3. 复用 TextAgent 文本审核管线（DeepSeek API）
4. 情感/语调分析（可选）

v3.5 升级:
  - 集成 AudioProcessor v3.5 (ERes2NetV2 优先 + VAD + 谱聚类)
  - 输出带说话人标签的转义文本
  - 支持多人对话场景的说话人归属
  - 噪声检测 + 低质量片段标记
  - FunASR 不可用时不静默跳过，返回明确错误

当 FunASR 服务不可用时，返回错误状态（不伪造数据）。
"""
import logging
import time
from agent_moderation.state import ModerationState
from agent_moderation.agents.base import BaseAgent
from common.funasr_client import get_funasr_client
from common.api_clients import get_deepseek_client, get_deepseek_model
from memory.manager import get_memory_manager
from mcp_servers.registry import get_tool_registry

logger = logging.getLogger(__name__)

# 语音审核 System Prompt
AUDIO_MODERATION_PROMPT = """你是语音内容安全审核专家。分析以下语音转写文本是否违反社区规范。

审核维度：
1. 政治敏感：涉政言论、煽动性言论
2. 色情低俗：色情语音、低俗挑逗
3. 暴力恐怖：暴力威胁、恐吓言论
4. 虚假信息：谣言传播、欺诈话术
5. 辱骂骚扰：人身攻击、侮辱性言论、言语霸凌
6. 广告引流：语音广告、诱导联系

请以JSON格式返回分析结果（只返回JSON，不要其他文字）：
{
  "violation_type": "none|politics|porn|violence|false_info|harassment|advertisement",
  "confidence": 0.0-1.0,
  "reason": "简短判断依据",
  "is_adversarial": false,
  "tags": ["标签1","标签2"]
}"""


class AudioAgent(BaseAgent):
    """语音审核 Agent — FunASR STT + 文本审核管线 + 黑灰产检测"""

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
        super().__init__("audio_agent")
        self.funasr = get_funasr_client()
        self.llm_client = get_deepseek_client()
        self.memory = get_memory_manager()
        self.keyword_tool = get_tool_registry().get_keyword_check()
        self.history_tool = get_tool_registry().get_history_search()

    async def process(self, state: ModerationState) -> ModerationState:
        """语音审核全流程 v3.5 (ASR + 说话人识别 + 语义分析)"""
        t_start = time.time()
        content = state.get("content", {})
        audio_data = content.get("audio") or content.get("audio_data") or b""

        if not audio_data:
            state["audio_result"] = {"error": "empty audio", "risk_score": 0.0}
            logger.warning(f"[AudioAgent] Empty audio data for {state.get('content_id', 'unknown')}")
            return state

        content_id = state.get("content_id", "unknown")
        self.log_step(f"Analyzing audio: {len(audio_data)} bytes")
        await self.memory.update_task_step(content_id, "audio_agent")

        # 1. ASR + 说话人识别 (AudioProcessor v3.5)
        from agent_moderation.workers.audio_processor import get_audio_processor_sync
        audio_processor = get_audio_processor_sync()

        transcript = await audio_processor.process(
            audio_data,
            audio_id=content_id,
        )

        if not transcript.success:
            err_msg = transcript.error or "STT failed"
            logger.error(f"[AudioAgent] ASR failed for {content_id}: {err_msg}")
            state["audio_result"] = {
                "error": err_msg,
                "transcribed_text": "",
                "risk_score": 0.0,
                "stt_success": False,
            }
            return state

        # 使用带说话人标签的格式化文本
        transcribed_text = transcript.formatted_text or transcript.raw_text
        asr_elapsed = (time.time() - t_start) * 1000
        self.log_step(f"Transcribed text ({len(transcribed_text)} chars, "
                     f"{transcript.speaker_count} speakers, "
                     f"diarization={'on' if transcript.diarization_used else 'off'}, "
                     f"{asr_elapsed:.0f}ms): '{transcribed_text[:100]}...'")

        if not transcribed_text.strip():
            logger.info(f"[AudioAgent] No valid speech content for {content_id}")
            state["audio_result"] = {
                "transcribed_text": "",
                "violation_type": "none",
                "confidence": 0.0,
                "reason": "音频无有效语音内容",
                "risk_score": 0.0,
                "stt_success": True,
                "speaker_count": transcript.speaker_count,
            }
            return state

        # 2. 敏感词检测
        keyword_result = await self._call_mcp_tool("keyword_check", text=transcribed_text)

        # 2.5. v3.7: 黑灰产检测 — 对转写文字做违规模式 + 对抗样本检测
        patterns = self._get_pattern_detector().detect_all(transcribed_text)
        adversarials = self._get_adversarial_detector().detect_all(transcribed_text)
        bh_score = self._calculate_blackhat_score(patterns, adversarials)
        is_blackhat = bh_score >= 0.4
        if patterns or adversarials:
            self.log_step(
                f"Blackhat: {len(patterns)} patterns + {len(adversarials)} adversarial "
                f"→ score={bh_score:.2f} {'⚠️' if is_blackhat else '✅'}"
            )

        # 3. 历史相似案例检索 (v3.6: 提前到 LLM 之前，结果注入 Prompt)
        similar_cases = []
        rag_start = time.time()
        try:
            history_result = await self._call_mcp_tool(
                "history_search", query=transcript.raw_text, top_k=3
            )
            # R22: MCP Gateway 返回 SimpleNamespace，统一转 dict 供 .get() 访问
            similar_cases = self._to_dict_list(history_result.cases if history_result.has_match else [])
            self.log_rag(transcribed_text, similar_cases, (time.time() - rag_start) * 1000)
        except Exception:
            similar_cases = []

        # 4. 语义违规分析（DeepSeek API + RAG 案例注入）
        try:
            semantic_result = await self._analyze_semantic(
                transcribed_text, similar_cases,
                transcribed_text=transcribed_text,
                content_id=content_id
            )
        except Exception as e:
            logger.error(f"DeepSeek API call failed for audio text: {e}")
            semantic_result = {
                "violation_type": "none",
                "confidence": 0.0,
                "reason": f"API error: {str(e)}",
                "is_adversarial": False,
                "tags": [],
            }

        # 5. 综合风险评分
        risk_score = self._calculate_risk_score(keyword_result, semantic_result, similar_cases)

        # v3.4: 构建说话人维度的风险归属
        speaker_attribution = {}
        if transcript.speaker_count > 1 and transcript.speaker_segments:
            for seg in transcript.speaker_segments:
                sid = seg.speaker_id if hasattr(seg, 'speaker_id') else seg.get('speaker_id', 'unknown')
                if sid not in speaker_attribution:
                    speaker_attribution[sid] = {
                        "text_snippet": "",
                        "risk_score": 0.0,
                    }
                text = seg.text if hasattr(seg, 'text') else seg.get('text', '')
                speaker_attribution[sid]["text_snippet"] += text[:200]

        state["audio_result"] = {
            "transcribed_text": transcribed_text,
            "raw_transcript": transcript.raw_text,
            "stt_success": True,
            "has_keyword_violation": keyword_result.has_violation,
            "keyword_matches": keyword_result.matches,
            "keyword_count": keyword_result.count,
            "violation_type": semantic_result.get("violation_type", "none"),
            "confidence": semantic_result.get("confidence", 0.0),
            "reason": semantic_result.get("reason", ""),
            "is_adversarial": semantic_result.get("is_adversarial", False),
            "tags": semantic_result.get("tags", []),
            "similar_cases_count": len(similar_cases),
            "risk_score": risk_score,
            # v3.4: 说话人信息
            "speaker_count": transcript.speaker_count,
            "speaker_segments": [
                {
                    "speaker_id": s.speaker_id if hasattr(s, 'speaker_id') else s.get('speaker_id', '?'),
                    "start_ms": s.start_ms if hasattr(s, 'start_ms') else s.get('start_ms', 0),
                    "end_ms": s.end_ms if hasattr(s, 'end_ms') else s.get('end_ms', 0),
                    "text": s.text if hasattr(s, 'text') else s.get('text', ''),
                }
                for s in transcript.speaker_segments
            ] if transcript.speaker_segments else [],
            "has_background_noise": transcript.has_background_noise,
            "diarization_used": transcript.diarization_used,
            "speaker_attribution": speaker_attribution,
            "processing_time_ms": round((time.time() - t_start) * 1000),
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

        logger.info(
            f"[AudioAgent] {content_id}: risk={risk_score}, "
            f"type={semantic_result.get('violation_type', 'none')}, "
            f"speakers={transcript.speaker_count}, "
            f"{round((time.time() - t_start) * 1000)}ms"
        )
        return state

    async def _analyze_semantic(self, text: str, similar_cases: list = None,
                                 transcribed_text: str = '', content_id: str = '') -> dict:
        """调用 DeepSeek API 进行语义分析 (v3.6: 注入 RAG 案例, v5.0: 注入 Skill)"""
        import json as _json
        import time as _t
        t0 = _t.time()
        model = get_deepseek_model()

        # v3.6: 构建 RAG 案例注入
        rag_context = self._build_rag_context(similar_cases or [])
        # v5.0: 动态注入 Skill 知识（根据内容自动选择）
        query_text = transcribed_text or text
        skill_context = self._load_relevant_skills(
            query=query_text,
            content_type='audio',
            max_inject=3,
            content_id=content_id,
        )
        system_content = AUDIO_MODERATION_PROMPT
        if rag_context:
            system_content = system_content + "\n\n" + rag_context
        if skill_context:
            system_content = system_content + "\n\n" + skill_context

        response = await self.llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"请分析以下语音转写文本：\n\n{text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=500,
        )
        # R22: 多级容错解析，避免非 JSON 响应静默降级为 none
        result = self._safe_json_parse(response.choices[0].message.content)
        if result is None:
            logger.warning(
                f"Audio semantic JSON 解析失败，按高风险降级处理: "
                f"{str(response.choices[0].message.content)[:120]}")
            return {"violation_type": "unknown", "confidence": 0.5,
                    "reason": "LLM 分类响应无法解析，按需人工复核", "tags": ["parse_failed"]}
        usage = response.usage
        self.trace_llm(model, usage.prompt_tokens if usage else len(text)//4,
                      usage.completion_tokens if usage else 100, (_t.time()-t0)*1000)
        self.log_llm(model, f"audio_text={text[:50]}...",
                    f"type={result.get('violation_type','none')} conf={result.get('confidence',0):.2f}",
                    (_t.time()-t0)*1000)
        return result

    def _build_rag_context(self, similar_cases: list) -> str:
        """将 RAG 检索结果格式化为 LLM Prompt 注入块"""
        if not similar_cases:
            return ""
        lines = ["## 参考案例（知识库检索的相似语音违规案例）"]
        lines.append("请参考以下历史语音审核案例的判定逻辑：\n")
        vt_cn = {"advertisement":"广告引流","porn":"色情低俗","violence":"暴力恐怖",
                 "false_info":"虚假信息","harassment":"辱骂骚扰","politics":"政治敏感","none":"正常"}
        for i, case in enumerate(similar_cases[:3], 1):
            sim = case.get("similarity", case.get("score", 0))
            vt = case.get("violation_type", "unknown")
            content = case.get("content", "")[:200]
            lines.append(f"> **案例 {i}** [相似度: {sim:.2f}] [判定: {vt_cn.get(vt, vt)}]")
            lines.append(f"> \"{content}\"")
            lines.append("")
        lines.append("如果当前语音转写内容与上述案例高度相似，请参照对应案例的判定结果。")
        return "\n".join(lines)

    def _calculate_risk_score(self, keyword_result, semantic_result, similar_cases) -> float:
        """计算综合风险分数"""
        score = 0.0

        if keyword_result.has_violation:
            keyword_weight = min(keyword_result.count / 10.0, 1.0)
            score += 0.4 * keyword_weight

        if semantic_result:
            confidence = semantic_result.get("confidence", 0.0)
            if semantic_result.get("violation_type", "none") != "none":
                score += 0.5 * confidence
            if semantic_result.get("is_adversarial", False):
                score += 0.1

        if similar_cases:
            similarities = [c.get("similarity", 0) for c in similar_cases]
            if similarities:
                score += 0.2 * (sum(similarities) / len(similarities))

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
