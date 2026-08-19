"""
Text Agent — 文本内容审核
1. 敏感词检测（本地 AC 自动机）
2. 语义违规分析（DeepSeek API）
3. 历史相似案例检索（ChromaDB）
4. 综合风险评分
"""
import asyncio
import json
import logging
from agent_moderation.state import ModerationState
from agent_moderation.agents.base import BaseAgent
from agent_moderation.violation_types import VIOLATION_CN
from common.api_clients import get_deepseek_client, get_deepseek_model
from memory.manager import get_memory_manager
from mcp_servers.registry import get_tool_registry

logger = logging.getLogger(__name__)

# v4.4: 长文本分段审核阈值 — 超过此长度文本可能藏违规被 LLM 注意力稀释, 触发分段逐块审核
# 注意: 必须 ≥ TextChunker.CHUNK_THRESHOLD (3000), 否则进入分段路径但切不出多块 (回退单次, 无意义)
SEGMENT_REVIEW_THRESHOLD = 3000   # 文本字符数阈值 (3000字 ≈ 2100+ tokens, 超过后单次 LLM 易漏审)
SEGMENT_CONCURRENCY = 5           # 分段审核并发数 (与图片并行一致, 受 DeepSeek API 限流约束)

# 文本审核 System Prompt
TEXT_MODERATION_PROMPT = """你是内容安全审核专家。请按照以下两步流程分析文本是否违反社区规范。

## 审核维度
1. 政治敏感：涉政、敏感事件、分裂言论
2. 色情低俗：色情描写、低俗色情暗示
3. 暴力恐怖：暴力威胁、恐怖主义宣传
4. 虚假信息：谣言、虚假欺诈信息
5. 辱骂骚扰：人身攻击、侮辱性言论、网络暴力、粗口脏话
   - 包括但不限于"你妈""他妈""废物""傻逼""去死""脑残""滚"等
   - 注意"你妈"在中日韩语境中通常是辱骂，不是字面意思
   - 短文本只要包含侮辱词就应判定为 harassment
6. 广告引流：垃圾广告、诱导加好友、引流推广
7. 隐私窃取：索取/泄露他人隐私、个人身份、账户、财产信息
8. 歧视偏见：基于种族、性别、地域、宗教等的歧视性、贬损性言论
9. 违法犯罪：诱导、教授盗窃/诈骗/赌博等违法活动（区别于暴力威胁）
10. 道德伦理：明显违背公序良俗、伦理失范的言论或行为引导
11. 身心健康：自残、自杀、厌世引导，或传播危害健康的方法
12. 知识产权侵权：诱导盗版、抄袭剽窃、破解他人版权内容

## 推理要求（重要）
reasoning 字段必须是你完整的内部推理过程（200-500字），按以下结构展开：
1. **关键信号识别**：列出文本中你观察到的所有可疑/敏感词汇、句式、语义特征
2. **逐维度分析**：对每个审核维度，逐一判断是否存在违规并说明理由
3. **上下文判断**：考虑文本整体语境，判断是否存在误报可能（如：引用新闻、正常讨论、讽刺表达等）
4. **最终结论**：基于以上分析，给出是否违规的判断及置信度

## 输出格式
请先写出你的详细推理分析过程（200-500字，按以下4部分展开），然后在最后输出 JSON：

【推理过程】
1.关键信号识别：列出文本中所有可疑/敏感词汇、句式、语义特征；
2.逐维度分析：对12个审核维度逐一判断是否存在违规并说明理由；
3.上下文判断：考虑文本整体语境，判断是否存在误报可能（如引用新闻、正常讨论、讽刺表达等）；
4.最终结论：基于以上分析给出是否违规的判断及置信度。

【JSON结果】
{
  "violation_type": "none|politics|porn|violence|false_info|harassment|advertisement|privacy|discrimination|crime|ethics|health|copyright",
  "confidence": 0.0-1.0,
  "reason": "简短判断依据(50字以内)",
  "reasoning": "将上面的【推理过程】完整复制到这里(200-500字)",
  "is_adversarial": false,
  "tags": ["标签1","标签2"]
}

重要：reasoning 字段不得省略、不得缩写。这是审核可解释性的核心依据。"""


class TextAgent(BaseAgent):
    """文本审核 Agent — DeepSeek API 驱动 + 黑灰产检测"""

    # 类级共享: 黑灰产检测器 (无状态, 所有实例共享)
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

    @staticmethod
    def _to_dict_list(items) -> list:
        """将元素统一转为 dict（兼容 dict / SimpleNamespace / 其他对象）。"""
        out = []
        for it in items or []:
            if isinstance(it, dict):
                out.append(dict(it))
            elif hasattr(it, "__dict__"):
                out.append(dict(it.__dict__))
            else:
                out.append({"content": str(it)})
        return out

    @staticmethod
    def _serializable_matches(matches) -> list:
        """将 keyword matches 统一转为可 msgpack 序列化的 dict 列表。

        MCP Gateway 返回 SimpleNamespace（递归 _dict_to_namespace），LangGraph
        MemorySaver 用 msgpack 保存 state，SimpleNamespace 不可序列化会抛
        "Type is not msgpack serializable"。此处兜底转换。
        """
        out = []
        for m in matches or []:
            if isinstance(m, dict):
                out.append(dict(m))
            elif hasattr(m, "__dict__"):
                out.append(dict(m.__dict__))
            else:
                out.append({"value": str(m)})
        return out

    def __init__(self):
        super().__init__("text_agent")
        self.llm_client = get_deepseek_client()
        self.memory = get_memory_manager()
        # v4.3: 保留直接工具引用作为 fallback，优先走 MCP Gateway
        self.keyword_tool = get_tool_registry().get_keyword_check()
        self.history_tool = get_tool_registry().get_history_search()

    async def process(self, state: ModerationState) -> ModerationState:
        """文本审核全流程"""
        text = state["content"].get("text", "")
        content_id = state.get("content_id", "unknown")
        content_type = state.get("content_type", "text")

        if not text:
            state["text_result"] = {"error": "empty text", "risk_score": 0.0}
            return state

        self.log_step(f"Analyzing text: {text[:50]}...")
        await self.memory.update_task_step(state["content_id"], "text_agent")

        # OpenTelemetry: 追踪 Agent 执行
        with self.trace(content_id, content_type):
            result = await self._process_impl(state, text, content_id)
        return result

    async def _process_impl(self, state: ModerationState, text: str, content_id: str) -> ModerationState:
        """文本审核核心逻辑 (trace 包装内执行)"""
        import time

        self.log_box_start(f"输入: \"{text[:80]}...\"")

        # v3.3: 如果协调器已经做了分块处理, 跳过重复的 LLM 调用
        existing = state.get("text_result")
        if existing and existing.get("is_chunked"):
            self.log_step(f"Using coordinator chunked result ({existing.get('chunk_count', '?')} chunks)")
            keyword_result = await self._call_mcp_tool("keyword_check", text=text)
            self.log_step(f"Keywords found (full text): {keyword_result.count}")
            if keyword_result.matches and existing.get("keyword_matches"):
                existing_matches = existing.get("keyword_matches", [])
                new_matches = [m["keyword"] if isinstance(m, dict) else str(m) for m in keyword_result.matches]
                existing["keyword_matches"] = list(set(existing_matches + new_matches))
            elif keyword_result.matches:
                existing["keyword_matches"] = [m["keyword"] if isinstance(m, dict) else str(m) for m in keyword_result.matches]
            state["text_result"] = existing
            self.log_box_end(f"复用分块结果, 风险分={existing.get('risk_score', 0):.2f}")
            return state

        # 1. 敏感词检测
        tool_start = time.time()
        keyword_result = await self._call_mcp_tool("keyword_check", text=text)
        self.log_step(f"Keywords found: {keyword_result.count}")
        self.trace_llm("local_ac_automaton", 0, 0, (time.time() - tool_start) * 1000)


        # 1.5. v3.7: 黑灰产检测 — 违规模式 + 对抗样本 (纯规则, 无 LLM 调用)
        patterns = self._get_pattern_detector().detect_all(text)
        adversarials = self._get_adversarial_detector().detect_all(text)
        blackhat_score = self._calculate_blackhat_score(patterns, adversarials, None)
        is_blackhat = blackhat_score >= 0.4
        if patterns or adversarials:
            self.log_step(
                f"Blackhat: {len(patterns)} patterns + {len(adversarials)} adversarial "
                f"→ score={blackhat_score:.2f} {'⚠️' if is_blackhat else '✅'}"
            )

        # 2. 历史相似案例检索 (v3.6: 提前到 LLM 调用之前，结果注入 Prompt)
        similar_cases = []
        rag_start = time.time()
        try:
            history_result = await self._call_mcp_tool("history_search", query=text, top_k=3)
            # R19 修复：MCP Gateway 返回 SimpleNamespace 列表，统一转 dict 供后续 .get() 使用
            similar_cases = self._to_dict_list(history_result.cases) if history_result.has_match else []
            self.log_rag(text, similar_cases, (time.time() - rag_start) * 1000)
        except Exception:
            similar_cases = []

        # 2.5. v3.8: Agent核心记忆召回 — 检索高重要性历史案例补充 RAG
        core_memories = []
        try:
            from memory.agent_memory import get_agent_memory
            agent_mem = get_agent_memory()
            mem_results = await agent_mem.recall("any", top_k=3)
            core_memories = [m for m in mem_results if m.get("source") == "core"]
            if core_memories:
                self.log_step(f"CoreMemory recall: {len(core_memories)} high-importance cases")
        except Exception:
            pass

        # 3. LLM 缓存检查
        prompt = self._build_prompt(text, similar_cases)
        semantic_result = await self.memory.get_cached_llm_result(prompt)

        if semantic_result:
            self.log_step("Using cached LLM result")
        elif len(text) > SEGMENT_REVIEW_THRESHOLD:
            # v4.4: 长文本分段审核 — 防违规藏进大量文本被 LLM 注意力稀释漏审。
            #       每块独立 LLM 分析 + 规则命中段注入, ChunkResultMerger 合并取保守风险。
            llm_start = time.time()
            semantic_result = await self._segment_review(
                text, similar_cases, core_memories, content_id=content_id)
            llm_ms = (time.time() - llm_start) * 1000
            from common.api_clients import get_deepseek_model
            self.trace_llm(get_deepseek_model(), len(text), 300, llm_ms)
            self.log_llm(get_deepseek_model(),
                        f"text={text[:50]}... ({semantic_result.get('chunk_count','?')} chunks)",
                        f"type={semantic_result.get('violation_type','none')} conf={semantic_result.get('confidence',0):.2f}",
                        llm_ms)
            await self.memory.cache_llm_result(prompt, semantic_result)
        else:
            # 4. 语义违规分析（DeepSeek API + RAG 案例注入 + 核心记忆）
            try:
                llm_start = time.time()
                # P3: 提取规则命中片段（敏感词+黑灰产模式+对抗），注入语义分析 —
                #     防"明显违规藏进大量文本"时被 LLM 注意力稀释漏审
                rule_hits = []
                for m in (keyword_result.matches or [])[:8]:
                    if isinstance(m, dict):
                        rule_hits.append(m.get("keyword", str(m)))
                    else:
                        rule_hits.append(getattr(m, "keyword", str(m)))
                rule_hits += [p.pattern_name for p in patterns[:5]]
                rule_hits += [f"{a.technique}:{a.evidence[:30]}" for a in adversarials[:5]]
                focus_segments = self._extract_focus_segments(
                    text, [k for k in rule_hits if isinstance(k, str) and k])
                semantic_result = await self._analyze_semantic(
                    text, similar_cases, core_memories,
                    focus_segments=focus_segments, content_id=content_id)
                llm_ms = (time.time() - llm_start) * 1000
                from common.api_clients import get_deepseek_model
                self.trace_llm(get_deepseek_model(), len(text), 300, llm_ms)
                self.log_llm(get_deepseek_model(),
                            f"text={text[:50]}...",
                            f"type={semantic_result.get('violation_type','none')} conf={semantic_result.get('confidence',0):.2f}",
                            llm_ms)
                await self.memory.cache_llm_result(prompt, semantic_result)
            except Exception as e:
                logger.error(f"DeepSeek API call failed: {e}")
                semantic_result = {
                    "violation_type": "none",
                    "confidence": 0.0,
                    "reason": f"API error: {str(e)}",
                    "reasoning": "",
                    "is_adversarial": False,
                    "tags": [],
                }

        # 5. 综合风险评分
        if semantic_result.get("is_chunked"):
            # v4.4: 分段审核已在 ChunkResultMerger 中取各块 max, 避免重复计算
            risk_score = semantic_result.get("risk_score", 0.0)
        else:
            risk_score = self._calculate_risk_score(keyword_result, semantic_result, similar_cases)

        # 构建推理链
        reasoning_steps = []
        if semantic_result.get("is_chunked"):
            reasoning_steps.append(
                f"[分段审核] 文本{len(text)}字 → {semantic_result.get('chunk_count', '?')}块并行逐块分析"
            )
        if keyword_result.matches:
            # MCP Gateway 返回递归 SimpleNamespace（BaseAgent._dict_to_namespace），
            # 兼容 dict 与 namespace 两种元素形态（v3.8 直调修复）
            matched_keywords = []
            for m in keyword_result.matches[:5]:
                if isinstance(m, dict):
                    matched_keywords.append(m.get("keyword", str(m)))
                else:
                    matched_keywords.append(getattr(m, "keyword", str(m)))
            reasoning_steps.append(f"[关键词检测] 命中 {keyword_result.count} 个敏感词: {', '.join(matched_keywords)}")
        else:
            reasoning_steps.append("[关键词检测] 未命中敏感词")
        reasoning_steps.append(f"[语义分析] {semantic_result.get('reason', '无')}")
        if similar_cases:
            reasoning_steps.append(f"[RAG检索] 找到 {len(similar_cases)} 个相似案例")
        reasoning_steps.append(f"[风险计算] keyword=0.4|semantic=0.5|history=0.2 → {risk_score}")

        state["text_result"] = {
            "has_keyword_violation": keyword_result.has_violation,
            # R19 修复：MCP Gateway 返回 SimpleNamespace，LangGraph MemorySaver 走 msgpack
            # 序列化会失败 → 统一转为可序列化 dict 列表
            "keyword_matches": self._serializable_matches(keyword_result.matches),
            "keyword_count": keyword_result.count,
            "violation_type": semantic_result.get("violation_type", "none"),
            "confidence": semantic_result.get("confidence", 0.0),
            "reason": semantic_result.get("reason", ""),
            "reasoning": semantic_result.get("reasoning", ""),
            "reasoning_chain": reasoning_steps,
            "is_adversarial": semantic_result.get("is_adversarial", False),
            "tags": semantic_result.get("tags", []),
            "violation_span": semantic_result.get("violation_span", []),
            "ai_generated_prob": semantic_result.get("ai_generated_prob", 0.0),
            "similar_cases_count": len(similar_cases) if similar_cases else 0,
            "risk_score": risk_score,
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
            "blackhat_risk_score": blackhat_score,
        }

        # v3.7: 同时设置 blackhat_result (兼容下游消费者)
        state["blackhat_result"] = {
            "pattern_detected": state["text_result"]["blackhat_patterns"],
            "adversarial_detected": state["text_result"]["adversarial_techniques"],
            "account_risk": None,
            "blackhat_risk_score": blackhat_score,
            "is_blackhat": is_blackhat,
        }

        return state

    async def _segment_review(self, text: str, similar_cases: list = None,
                              core_memories: list = None, content_id: str = '') -> dict:
        """v4.4: 长文本分段审核 — 防"违规藏进大量文本"被 LLM 注意力稀释漏审。

        对超过 SEGMENT_REVIEW_THRESHOLD 的长文本, 切块后每块独立做
        [关键词检测 + 黑灰产检测 + 规则命中段注入 + DeepSeek 语义分析 + 风险评分],
        块间并行 (Semaphore 限流), 最后 ChunkResultMerger 合并:
          - violation_type: 取置信度最高的非 none 类型
          - risk_score: max(所有块) — 保守策略
          - keyword_matches / reasoning: 各块合并

        Returns:
            dict: 合并后的语义分析结果 (含 is_chunked=True, chunk_count)
        """
        import time
        from agent_moderation.workers.chunking import TextChunker, ChunkResultMerger

        similar_cases = similar_cases or []
        core_memories = core_memories or []

        # 1. 切块 (段落边界优先, 2000字/块, 200重叠)
        chunks = TextChunker.chunk(text)
        if len(chunks) <= 1:
            # 文本虽超阈值但切不出多块 (边界极端), 回退单次语义分析
            return await self._analyze_semantic(text, similar_cases, core_memories, content_id=content_id)

        self.log_step(f"⚡ 分段审核: {len(text)}字 → {len(chunks)}块 (并行 {SEGMENT_CONCURRENCY})")
        sem = asyncio.Semaphore(SEGMENT_CONCURRENCY)

        async def _review_chunk(chunk_meta: dict) -> dict:
            """单块独立审核: 关键词 → 黑灰产 → 规则命中段 → DeepSeek → 评分"""
            async with sem:
                ctext = chunk_meta["text"]
                # 块级敏感词检测
                c_kw = await self._call_mcp_tool("keyword_check", text=ctext)
                # 块级黑灰产检测
                c_patterns = self._get_pattern_detector().detect_all(ctext)
                c_adversarials = self._get_adversarial_detector().detect_all(ctext)
                # 块内规则命中段提取 (P3 复用)
                rule_hits = []
                for m in (c_kw.matches or [])[:8]:
                    if isinstance(m, dict):
                        rule_hits.append(m.get("keyword", str(m)))
                    else:
                        rule_hits.append(getattr(m, "keyword", str(m)))
                rule_hits += [p.pattern_name for p in c_patterns[:5]]
                rule_hits += [f"{a.technique}:{a.evidence[:30]}" for a in c_adversarials[:5]]
                focus_segments = self._extract_focus_segments(
                    ctext, [k for k in rule_hits if isinstance(k, str) and k])
                # 块级语义分析
                c_semantic = await self._analyze_semantic(
                    ctext, similar_cases, core_memories,
                    focus_segments=focus_segments, content_id=content_id)
                # 块级风险评分
                c_risk = self._calculate_risk_score(c_kw, c_semantic, similar_cases)
                c_semantic["risk_score"] = c_risk
                c_semantic["keyword_matches"] = self._serializable_matches(c_kw.matches)
                c_semantic["keyword_count"] = c_kw.count
                c_semantic["_chunk_index"] = chunk_meta.get("index", 0)
                return c_semantic

        # 2. 并行审核所有块
        chunk_results = await asyncio.gather(
            *[_review_chunk(c) for c in chunks],
            return_exceptions=True,
        )

        # 3. 整理各块结果 (异常块标记 error)
        per_chunk = []
        for i, cr in enumerate(chunk_results):
            if isinstance(cr, Exception):
                logger.warning(f"Chunk {i} review failed: {cr}")
                per_chunk.append({"error": str(cr), "risk_score": 0.0})
            elif isinstance(cr, dict):
                per_chunk.append(cr)
            else:
                per_chunk.append({"error": "unknown", "risk_score": 0.0})

        # 4. 合并
        merged = ChunkResultMerger.merge(per_chunk, chunks)

        # 补充与单次路径对齐的字段 (text_result 消费者依赖)
        merged.setdefault("ai_generated_prob",
                          max((c.get("ai_generated_prob", 0.0) for c in per_chunk
                               if isinstance(c, dict)), default=0.0))
        merged.setdefault("violation_span",
                          [s for c in per_chunk if isinstance(c, dict)
                           for s in c.get("violation_span", [])])
        merged.setdefault("keyword_count",
                          sum((c.get("keyword_count", 0) for c in per_chunk
                               if isinstance(c, dict)), 0))

        self.log_step(f"合并完成: vt={merged.get('violation_type')} "
                     f"conf={merged.get('confidence', 0):.2f} risk={merged.get('risk_score', 0):.2f} "
                     f"({len(per_chunk)}块)")
        return merged

    async def _analyze_semantic(self, text: str, similar_cases: list = None,
                                core_memories: list = None,
                                focus_segments: list = None,
                                content_id: str = '') -> dict:
        """
        调用 DeepSeek API 进行语义违规分析

        v4.0 重构: 移除 json_object 强制格式 → LLM 先推理再输出JSON
        - 使用 system role 传递审核指令
        - LLM 自由输出推理过程 + JSON, 由 _parse_semantic_response 提取
        - RAG案例作为 few-shot 注入 user message
        - P3: focus_segments 注入规则命中片段, 防长文本中违规被稀释漏审
        - v5.0: 动态注入 Skill 知识
        """
        similar_cases = similar_cases or []
        core_memories = core_memories or []

        # 从 PromptRegistry 获取 System Prompt
        try:
            system_prompt, _ = self.get_prompt("text_moderation", text)
        except Exception:
            system_prompt = TEXT_MODERATION_PROMPT

        # v5.0: 动态注入 Skill 知识（根据内容自动选择）
        skill_context = self._load_relevant_skills(
            query=text,
            content_type='text',
            max_inject=3,
            content_id=content_id,
        )
        if skill_context:
            system_prompt = f"{system_prompt}\n\n{skill_context}"

        # 构建 RAG few-shot 案例
        rag_context = self._build_rag_context(similar_cases)
        memory_context = self._build_memory_context(core_memories)

        # P3: 规则命中片段注入 — 让 LLM 聚焦审查可能藏违规的片段
        focus_block = ""
        if focus_segments:
            lines = "\n".join(f"- \"{seg}\"" for seg in focus_segments[:5])
            focus_block = f"""
## 重点核查信号（以下片段命中了敏感词/违规模式/对抗规则，可能藏有违规内容。
请逐字核查，判断是否构成违规，不要因为混在大量正常文本中就忽略）:
{lines}
"""
        # User message: 待审核文本 + 重点核查信号 + RAG参考 + 输出要求
        user_message = f"""请审核以下文本：

"{text}"
{focus_block}
{rag_context}
{memory_context}
---
## 重要判例参考（必须参照）:
- "你妈死了" → harassment, confidence≥0.85
- "废物东西滚远点" → harassment, confidence≥0.85
- "今天天气真好" → none, confidence≥0.9
- "加微信赚钱" → advertisement, confidence≥0.8
- "网上能查到你的家庭住址和身份证号" → privacy, confidence≥0.8
- "某省的人都是骗子，别信他们" → discrimination, confidence≥0.8
- "转发到5个群就能免费领千元礼包" → false_info, confidence≥0.7
- "教你制作简易爆炸装置" → crime, confidence≥0.85

请先逐维度分析（政治/色情/暴力/虚假信息/辱骂骚扰/广告引流/隐私窃取/
歧视偏见/违法犯罪/道德伦理/身心健康/版权侵权），
然后在最后输出 JSON：

{{
  "violation_type": "none|politics|porn|violence|false_info|harassment|advertisement|privacy|discrimination|crime|ethics|health|copyright",
  "confidence": 0.0-1.0,
  "reason": "判定依据(50字以内)",
  "reasoning": "完整推理过程",
  "is_adversarial": false,
  "tags": [],
  "violation_span": []
}}"""

        # InputGuard
        from security.input_guard import get_input_guard
        input_guard = get_input_guard()
        guard_result = await input_guard.filter(text, user_message[:1000], use_llm_verification=False)
        if not guard_result.is_safe:
            logger.warning(f"InputGuard blocked: {guard_result.attack_type}")

        # v4.0: system role + 无 json_object 限制 → LLM 先推理再输出
        response = await self.llm_client.chat.completions.create(
            model=get_deepseek_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        raw_output = response.choices[0].message.content
        result = self._parse_semantic_response(raw_output)

        # 确保 reasoning 不为空 (API 响应构造需要此字段)
        if not result.get("reasoning") and result.get("reason"):
            result["reasoning"] = result["reason"]
        if not result.get("reasoning"):
            result["reasoning"] = f"判定: {result.get('violation_type','none')}, 置信度: {result.get('confidence',0)}"

        # AIGC检测
        ai_prob = self._detect_ai_generated(text, result)
        result["ai_generated_prob"] = ai_prob

        # OutputGuard
        from security.output_guard import get_output_guard
        output_guard = get_output_guard()
        out_guard_result = output_guard.validate(raw_output, result, content_id=None)
        if not out_guard_result.is_valid and out_guard_result.corrected_output:
            logger.warning(f"OutputGuard corrected: {out_guard_result.anomaly_type}")
            result = out_guard_result.corrected_output

        if len(result.get("reasoning", "")) < 20:
            result["reasoning"] = result.get("reason", "")[:500]

        return result

    def _parse_semantic_response(self, raw_content: str) -> dict:
        """解析 LLM 语义分析输出，支持两种格式:
        1. 纯 JSON (以 { 开头)
        2. 推理文本 + JSON 混合 (提取最后的 JSON 块)
        """
        import re as _re
        text = raw_content.strip()

        # 方式1: 纯 JSON
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # 方式2: 提取最后的 JSON 块 (支持 markdown 代码块和裸 JSON)
        # 先尝试匹配 ```json ... ``` 代码块
        json_match = _re.search(r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```", text, _re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 再尝试匹配最后一个完整的 JSON 对象
        json_matches = list(_re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, _re.DOTALL))
        if json_matches:
            # 取最后一个 (通常是最终结果 JSON)
            try:
                return json.loads(json_matches[-1].group(0))
            except json.JSONDecodeError:
                pass

        # 方式3: 用 json_repair 修复后解析
        try:
            from json_repair import repair_json
            # 尝试找 JSON 起始位置
            brace_idx = text.rfind("{")
            if brace_idx >= 0:
                json_str = text[brace_idx:]
                repaired = repair_json(json_str)
                return json.loads(repaired)
        except Exception:
            pass

        logger.warning(f"Failed to parse LLM semantic response: {text[:200]}")
        return {
            "violation_type": "none",
            "confidence": 0.0,
            "reason": "Failed to parse LLM response",
            "reasoning": "",
            "is_adversarial": False,
            "tags": [],
        }

    def _build_prompt(self, text: str, similar_cases: list = None) -> str:
        """构建用于缓存 hash 的完整 prompt (v3.6: 含 RAG 案例)"""
        base = TEXT_MODERATION_PROMPT + text[:200]
        if similar_cases:
            # 取 top case 的 content 加入 hash key
            top = similar_cases[0].get("content", "")[:100] if similar_cases else ""
            base += top
        return base

    @staticmethod
    def _extract_focus_segments(text: str, keywords: list, span: int = 40,
                                max_segments: int = 5) -> list:
        """P3: 提取规则命中关键词所在的原文片段（关键词±上下文）。

        供语义分析注入，让 DeepSeek 聚焦审查这些可能藏违规的片段，
        避免违规内容混在大量正常文本中时被 LLM 注意力稀释而漏审。
        """
        if not text or not keywords:
            return []
        segments = []
        for kw in keywords:
            if len(segments) >= max_segments:
                break
            idx = text.find(kw)
            if idx >= 0:
                start = max(0, idx - span)
                end = min(len(text), idx + len(kw) + span)
                segments.append(text[start:end].replace("\n", " "))
        return segments

    def _build_rag_context(self, similar_cases: list) -> str:
        """将 RAG 检索结果格式化为 LLM Prompt 注入块"""
        if not similar_cases:
            return ""

        lines = ["## 参考案例（知识库检索的相似历史判定）"]
        lines.append("请参考以下历史案例的判定逻辑来辅助判断当前内容：\n")

        for i, case in enumerate(similar_cases[:3], 1):
            sim = case.get("similarity", case.get("score", 0))
            vt = case.get("violation_type", "unknown")
            decision = case.get("decision", "?")
            content = case.get("content", "")[:200]

            # 翻译违规类型
            vt_cn = VIOLATION_CN.get(vt, vt)

            lines.append(f"> **案例 {i}** [相似度: {sim:.2f}] [判定: {decision} / {vt_cn}]")
            lines.append(f"> \"{content}\"")
            lines.append("")

        lines.append("请严格参考以上案例的判定标准和逻辑，对当前待审核内容给出判定。")
        lines.append("如果当前内容与某个案例高度相似，应该参考该案例的判定结果。")
        return "\n".join(lines)

    def _build_memory_context(self, core_memories: list) -> str:
        """v3.8: 将 Agent 核心记忆格式化为 LLM Prompt 注入块"""
        if not core_memories:
            return ""

        lines = ["## Agent 核心记忆（历史高风险案例，高重要性长期保留）"]
        lines.append("以下是从长期记忆中检索到的高重要性审核案例，请严格参考：\n")

        vt_cn = VIOLATION_CN

        for i, mem in enumerate(core_memories[:3], 1):
            vt = mem.get("violation_type", "unknown")
            importance = mem.get("score", 0)
            content = mem.get("content", "")[:150]
            lines.append(f"> **记忆 {i}** [重要性: {importance:.2f}] [类型: {vt_cn.get(vt, vt)}]")
            lines.append(f"> \"{content}\"")
            lines.append("")

        lines.append("如果当前内容与上述长期记忆中的案例高度相似，应参照对应的判定结果。")
        return "\n".join(lines)

    def _calculate_risk_score(self, keyword_result, semantic_result, similar_cases) -> float:
        """计算综合风险分数（0.0 ~ 1.0）

        v4.0: 引入关键词保底分 — 即使LLM漏判(violation_type=none),
        只要关键词命中就产生有效风险分，防止漏审

        v4.1: 权重从策略配置动态加载，运维可通过 UI 调整无需重启
        """
        # 从策略缓存加载权重配置
        try:
            from api.routes.policies import get_active_threshold_config
            threshold_cfg = get_active_threshold_config()
            kw_weight = float(threshold_cfg.get("keyword_weight", 0.3))
            sem_weight = float(threshold_cfg.get("semantic_weight", 0.5))
            case_weight = float(threshold_cfg.get("case_weight", 0.2))
        except Exception:
            kw_weight = 0.3
            sem_weight = 0.5
            case_weight = 0.2

        score = 0.0

        # 敏感词匹配
        if keyword_result.has_violation:
            keyword_density = min(keyword_result.count / 10.0, 1.0)
            score += kw_weight * keyword_density

        # 语义违规
        llm_violation_detected = False
        if semantic_result:
            confidence = semantic_result.get("confidence", 0.0)
            violation_type = semantic_result.get("violation_type", "none")
            if violation_type != "none":
                llm_violation_detected = True
                score += sem_weight * confidence
            # v4.0: 关键词保底 — LLM漏判但有关键词命中时, 给最低语义分
            elif keyword_result.has_violation and keyword_result.count >= 2:
                score += sem_weight * 0.4  # 关键词≥2个但LLM漏判: 语义分保底0.4
            elif keyword_result.has_violation:
                score += sem_weight * 0.25  # 关键词1个但LLM漏判: 语义分保底0.25
            # 对抗样本额外加分
            if semantic_result.get("is_adversarial", False):
                score += 0.1

        # 历史案例相似度
        if similar_cases:
            similarities = [c.get("similarity", 0) for c in similar_cases]
            if similarities:
                score += case_weight * (sum(similarities) / len(similarities))

        return round(min(score, 1.0), 4)

    def _detect_ai_generated(self, text: str, semantic_result: dict) -> float:
        """
        v3.8: AIGC 文本检测 — 判断文本是否由 AI 生成

        检测维度:
        1. 统计学特征: 熵、重复n-gram、标点分布 (0-0.3分)
        2. 语义特征: LLM 输出的 reasoning 中检查AI生成特征词 (0-0.4分)
        3. 结构特征: 是否有AI典型的"首先/其次/最后"等模板结构 (0-0.3分)

        Returns: 0.0-1.0 表示AI生成概率
        """
        score = 0.0
        signals = []

        # 1. 统计学特征
        if len(text) > 50:
            # 检查文本熵: AI生成文本通常有更均匀的词汇分布
            words = text.replace(" ", "").replace("\n", "")
            if len(words) > 10:
                unique_chars = len(set(words))
                char_ratio = unique_chars / len(words)
                # AI文本: 字符多样性中等 (0.3-0.6), 人类文本: 更分散或更集中
                if 0.25 < char_ratio < 0.55 and len(text) > 100:
                    score += 0.15
                    signals.append(f"字符多样性适中({char_ratio:.2f})")

            # 检查重复模式
            from collections import Counter
            bigrams = [text[i:i+2] for i in range(len(text)-1)]
            if bigrams:
                bigram_counts = Counter(bigrams)
                repeat_rate = sum(1 for c in bigram_counts.values() if c > 3) / len(bigram_counts)
                if repeat_rate > 0.05:
                    score += 0.1
                    signals.append(f"高频重复bigram({repeat_rate:.3f})")

        # 2. 语义特征: 检查reasoning中是否有AI生成标志
        reasoning = semantic_result.get("reasoning", "")
        ai_markers = [
            "总体来说", "总而言之", "综上所述", "基于以上分析",
            "首先", "其次", "最后", "此外", "另外",
            "需要注意的是", "值得关注的是", "不可忽视的是",
        ]
        marker_count = sum(1 for m in ai_markers if m in reasoning)
        if marker_count >= 3:
            score += 0.25
            signals.append(f"AI模板标志词 {marker_count} 个")
        elif marker_count >= 1:
            score += 0.1

        # 3. 结构特征: 检查是否为标准的"背景-分析-结论"结构
        if reasoning.count("。") >= 5 and len(reasoning) > 150:
            sentences = [s.strip() for s in reasoning.split("。") if s.strip()]
            if len(sentences) >= 4:
                avg_sentence_len = sum(len(s) for s in sentences) / len(sentences)
                # AI句子长度通常比较均匀 (标准差小)
                if 15 < avg_sentence_len < 80:
                    score += 0.1
                    signals.append(f"句子结构均匀(avg={avg_sentence_len:.0f}字)")

        if signals and score > 0.3:
            logger.debug(f"AIGC检测信号: {signals} → score={score:.2f}")

        return round(min(score, 1.0), 4)

    @staticmethod
    def _calculate_blackhat_score(patterns: list, adversarials: list, account_risk: dict = None) -> float:
        """计算黑灰产综合风险分 (与 BlackhatAgent 一致)"""
        score = 0.0
        # 模式检测贡献 (max 0.4)
        if patterns:
            max_pattern_score = max(p.risk_score for p in patterns)
            avg_pattern_score = sum(p.risk_score for p in patterns) / len(patterns)
            score += max_pattern_score * 0.25 + avg_pattern_score * 0.15
        # 对抗检测贡献 (max 0.3)
        if adversarials:
            max_adv_score = max(a.risk_score for a in adversarials)
            avg_adv_score = sum(a.risk_score for a in adversarials) / len(adversarials)
            score += max_adv_score * 0.2 + avg_adv_score * 0.1
        # 账号风险贡献 (max 0.3)
        if account_risk:
            score += account_risk.get("risk_score", 0.0) * 0.3
        return round(min(score, 1.0), 4)
