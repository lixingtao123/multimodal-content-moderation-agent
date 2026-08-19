"""
ReAct Agent v2.0 — Reasoning + Acting + Self-Calibration

Phase 1 — 主动搜索 (原 ReAct):
  Thought → Action → Observation 循环, 最多 5 步
  主动调用工具收集证据, 修正判定

Phase 2 — 保守校准 (原 Reflexion, v2.0 合并):
  Phase 1 结束后自动评估结果质量:
    - 置信度是否达到该违规类型的阈值?
    - 是否有历史案例支撑?
    - 风险分与违规类型匹配吗?
    - 有对抗信号吗?
  → 通过: 结束
  → 不通过: 保守校准 (confidence × 0.85, risk_score × 1.2 for adversarial)

触发条件 (任意模态):
  violation_type != "none" AND (confidence < 0.6 OR is_adversarial) AND NOT react_enhanced

技术参考:
  - ReAct (Yao et al., ICLR 2023)
  - Reflexion (Shinn et al., NeurIPS 2023)
"""
import json
import logging
from typing import List, Dict, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from common.api_clients import get_deepseek_model
from agent_moderation.agents.reflexion import ReflexionEvaluator

logger = logging.getLogger(__name__)


class ReActAction(Enum):
    """ReAct 可用的动作"""
    KEYWORD_CHECK = "keyword_check"        # 敏感词检测
    HISTORY_SEARCH = "history_search"      # 历史案例检索
    DEEP_ANALYSIS = "deep_analysis"        # 深层语义分析 (调用 LLM)
    IMAGE_HASH = "image_hash"             # 图片相似度检测
    RAG_RETRIEVE = "rag_retrieve"         # RAG 检索
    ACCOUNT_CHECK = "account_check"       # 账号风险查询
    ESCALATE = "escalate"                  # 升级到人工
    FINALIZE = "finalize"                  # 输出最终判定


@dataclass
class ReActStep:
    """ReAct 循环中的单步"""
    step_num: int
    thought: str         # Agent 的思考过程
    action: ReActAction  # 决定采取的动作
    action_input: Dict   # 动作参数
    observation: str     # 动作执行后的观察结果
    confidence: float = 0.0


@dataclass
class ReActResult:
    """ReAct 循环的最终结果"""
    final_decision: str        # 最终判定
    violation_type: str        # 违规类型
    confidence: float          # 置信度
    risk_score: float          # 风险分
    steps: List[ReActStep]     # 完整的推理步骤
    total_steps: int
    tools_called: List[str]
    reasoning_trace: str       # 完整推理链


class ReActModerationAgent:
    """
    ReAct 审核 Agent

    Thought: "文本包含加微信和日赚千元，可能是广告引流，但需要确认"
    Action: keyword_check("加微信xxx，日赚千元，无需押金")
    Observation: "检测到 3 个敏感词: 微信, 日赚千元, 押金"
    Thought: "确实有引流特征，再查一下历史案例确认"
    Action: history_search("微信引流广告", top_k=3)
    Observation: "找到 2 个相似案例，均判定为 advertisement"
    Thought: "证据充分，确认为广告引流"
    Action: finalize(violation_type="advertisement", confidence=0.85)

    最大步数: MAX_STEPS = 5
    """

    MAX_STEPS = 5
    _evaluator = None  # 类级共享 ReflexionEvaluator

    @classmethod
    def _get_evaluator(cls):
        if cls._evaluator is None:
            cls._evaluator = ReflexionEvaluator()
        return cls._evaluator

    @staticmethod
    def _calibrate(result: "ReActResult", content_type: str) -> "ReActResult":
        """
        Phase 2 — 保守校准 (v2.0: 原 Reflexion 逻辑合并)

        Phase 1 结束后自动评估结果质量。如果发现不足, 不重新搜索,
        而是保守地降低置信度或提高风险分标记。

        Returns: 校准后的 ReActResult (可能是原结果, 也可能是修改后的)
        """
        evaluator = ReActModerationAgent._get_evaluator()

        # 构造 agent_result dict 供 evaluator 使用
        agent_result = {
            "violation_type": result.violation_type,
            "confidence": result.confidence,
            "risk_score": result.risk_score,
            "similar_cases_count": len([t for t in result.tools_called if t == "history_search"]),
            "is_adversarial": False,
        }

        eval_result = evaluator.evaluate(agent_result, content_type)

        if eval_result["is_sufficient"]:
            return result  # 一切OK, 不需要校准

        # 有不足 → 保守校准
        calibrated = ReActResult(
            final_decision=result.final_decision,
            violation_type=result.violation_type,
            confidence=result.confidence,
            risk_score=result.risk_score,
            steps=result.steps,
            total_steps=result.total_steps,
            tools_called=result.tools_called,
            reasoning_trace=result.reasoning_trace,
        )

        if "low_confidence" in eval_result.get("review_flags", []):
            # 置信度不足: 保守下调, cap at 0.5
            calibrated.confidence = min(result.confidence * 0.85, 0.5)
            calibrated.reasoning_trace += (
                f"\n[Phase2校准] 置信度{result.confidence:.2f}→{calibrated.confidence:.2f} "
                f"(不足阈值{eval_result['threshold']:.2f})"
            )
            logger.info(
                f"ReAct Phase2: confidence calibrated {result.confidence:.2f}"
                f"→{calibrated.confidence:.2f}"
            )

        if "is_adversarial" in eval_result.get("review_flags", []):
            # 对抗样本: 提高风险分
            calibrated.risk_score = min(result.risk_score * 1.2, 0.95)

        return calibrated

    # 可用工具和它们的描述
    TOOL_DESCRIPTIONS = {
        "keyword_check": "检测文本中的敏感词和违规关键词，返回匹配列表和数量",
        "history_search": "搜索历史相似案例，返回判定结果和相似度",
        "deep_analysis": "使用 LLM 进行深层语义分析，适合对抗样本和边界case",
        "image_hash": "计算图片感知哈希，搜索视觉相似图片",
        "rag_retrieve": "使用混合RAG检索相关知识 (BM25+Vector+RRF+Rerank)",
        "account_check": "查询账号的历史违规记录和风险画像",
        "escalate": "证据不足时升级到人工审核",
        "finalize": "输出最终判定结果",
    }

    def __init__(self):
        self._llm_client = None
        self._tool_registry = None
        self._memory = None

    def set_llm_client(self, client):
        self._llm_client = client

    def set_tool_registry(self, registry):
        self._tool_registry = registry

    def set_memory(self, memory):
        self._memory = memory

    async def run(self, content: Dict, content_type: str = "text") -> ReActResult:
        """
        执行 ReAct 循环

        Args:
            content: 待审核内容 {"text": "...", "image": b"...", ...}
            content_type: 内容类型

        Returns:
            ReActResult 包含最终判定和完整推理链
        """
        steps = []
        tools_called = []
        text = content.get("text", "") if content_type == "text" else ""

        # 从外部预填充上下文 (如 TextAgent 结果)
        prefill = getattr(self, 'context_prefill', {}) or {}

        # 初始上下文 — 优先使用预填充数据
        context = {
            "content": content,
            "content_type": content_type,
            "known_violations": prefill.get("known_violations", []),
            "known_keywords": prefill.get("known_keywords", []),
            "known_similar_cases": prefill.get("known_similar_cases", []),
            "account_risk": prefill.get("account_risk"),
        }

        for step_num in range(1, self.MAX_STEPS + 1):
            # Step 1: Thought — LLM 分析当前状态，决定下一步
            thought_result = await self._think(context, steps)
            action = thought_result["action"]
            action_input = thought_result.get("action_input", {})

            # Step 2: Action — 执行选定的动作
            observation = await self._act(action, action_input, context)

            # 记录这一步
            step = ReActStep(
                step_num=step_num,
                thought=thought_result.get("reasoning", ""),
                action=action,
                action_input=action_input,
                observation=observation,
                confidence=thought_result.get("confidence", 0.0),
            )
            steps.append(step)
            tools_called.append(action.value)

            logger.info(f"ReAct step {step_num}: {action.value} → {observation[:100]}")

            # 更新上下文
            self._update_context(context, action, observation)

            # Step 3: 判断是否结束
            if action == ReActAction.FINALIZE:
                raw = ReActResult(
                    final_decision=action_input.get("decision", "REVIEW"),
                    violation_type=action_input.get("violation_type", "none"),
                    confidence=action_input.get("confidence", 0.0),
                    risk_score=action_input.get("risk_score", 0.0),
                    steps=steps,
                    total_steps=step_num,
                    tools_called=tools_called,
                    reasoning_trace=self._build_trace(steps),
                )
                return self._calibrate(raw, content_type)
            elif action == ReActAction.ESCALATE:
                raw = ReActResult(
                    final_decision="REVIEW",
                    violation_type="unknown",
                    confidence=0.3,
                    risk_score=0.7,
                    steps=steps,
                    total_steps=step_num,
                    tools_called=tools_called,
                    reasoning_trace=self._build_trace(steps),
                )
                return self._calibrate(raw, content_type)

        # 达到最大步数，强制输出
        raw = ReActResult(
            final_decision="REVIEW",
            violation_type="|".join(context["known_violations"]) if context["known_violations"] else "unknown",
            confidence=0.4,
            risk_score=0.5,
            steps=steps,
            total_steps=self.MAX_STEPS,
            tools_called=tools_called,
            reasoning_trace=self._build_trace(steps),
        )
        return self._calibrate(raw, content_type)

    async def _think(self, context: Dict, previous_steps: List[ReActStep]) -> Dict:
        """
        LLM 推理: 分析当前状态，决定下一步动作

        Returns:
            {"action": ReActAction, "action_input": {...}, "reasoning": "...", "confidence": 0.0}
        """
        # 构建工具描述
        tools_desc = "\n".join(
            f"- {name}: {desc}"
            for name, desc in self.TOOL_DESCRIPTIONS.items()
        )

        # 构建历史步骤描述
        history = ""
        for s in previous_steps:
            history += f"\nStep {s.step_num}: Action={s.action.value}, Observation={s.observation[:150]}"

        prompt = f"""你是内容审核 ReAct Agent。你需要通过工具调用来收集证据，最终做出审核判定。

可用工具:
{tools_desc}

已收集的信息:
- 已知违规类型: {context.get('known_violations', [])}
- 已知关键词: {context.get('known_keywords', [])[:5]}
- 相似案例数: {len(context.get('known_similar_cases', []))}
- 账号风险: {context.get('account_risk')}

已执行步骤:{history if history else ' (尚无)'}

内容类型: {context.get('content_type', 'text')}

请决定下一步。规则:
1. 如果还没做关键词检测 → keyword_check
2. 如果还没查历史案例 → history_search
3. 如果关键词或历史案例有信号但不确定 → deep_analysis 或 rag_retrieve
4. 如果证据充分 → finalize (给出violation_type, decision, confidence, risk_score)
5. 如果证据不足且所有工具都已用过 → escalate
6. 最多调用5次工具，尽量3步内完成

只返回JSON:
{{"action": "工具名", "action_input": {{...}}, "reasoning": "思考过程", "confidence": 0.0}}"""

        try:
            response = await self._llm_client.chat.completions.create(
                model=get_deepseek_model(),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=400,
            )
            result = json.loads(response.choices[0].message.content)
            # 转换 action 字符串为枚举
            action_str = result.get("action", "finalize")
            try:
                result["action"] = ReActAction(action_str)
            except ValueError:
                result["action"] = ReActAction.FINALIZE
            return result
        except Exception as e:
            logger.error(f"ReAct think failed: {e}")
            return {
                "action": ReActAction.FINALIZE,
                "action_input": {"decision": "REVIEW", "violation_type": "unknown",
                                 "confidence": 0.3, "risk_score": 0.5},
                "reasoning": f"Think error: {e}",
                "confidence": 0.3,
            }

    async def _act(self, action: ReActAction, action_input: Dict, context: Dict) -> str:
        """执行动作，返回观察结果"""
        try:
            if action == ReActAction.KEYWORD_CHECK:
                text = context.get("content", {}).get("text", "")
                if self._tool_registry:
                    tool = self._tool_registry.get_keyword_check()
                    result = await tool.execute(text)
                    keyword_names = [m["keyword"] for m in result.matches[:5]]
                    return f"检测到 {result.count} 个敏感词: {keyword_names}"
                return "工具不可用"

            elif action == ReActAction.HISTORY_SEARCH:
                query = action_input.get("query", context.get("content", {}).get("text", "")[:200])
                if self._tool_registry:
                    tool = self._tool_registry.get_history_search()
                    result = await tool.execute(query, top_k=action_input.get("top_k", 5))
                    if result.has_match:
                        cases_desc = [f"{c.get('violation_type', '?')}(sim={c.get('similarity', 0):.2f})"
                                      for c in result.cases[:3]]
                        return f"找到 {len(result.cases)} 个相似案例: {cases_desc}"
                    return "未找到相似案例"
                return "工具不可用"

            elif action == ReActAction.DEEP_ANALYSIS:
                text = context.get("content", {}).get("text", "")
                prompt = f"请深度分析以下文本的违规风险和对抗特征:\n{text[:500]}"
                response = await self._llm_client.chat.completions.create(
                    model="deepseek-v4-flash",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300, temperature=0.1,
                )
                return response.choices[0].message.content[:200]

            elif action == ReActAction.RAG_RETRIEVE:
                text = context.get("content", {}).get("text", "")
                try:
                    from memory.agentic_rag import get_agentic_rag
                    from memory.hybrid_retriever import get_hybrid_retriever
                    from memory.chroma_service import get_chroma_service
                    from memory.graph_rag import get_graph_rag
                    hybrid = get_hybrid_retriever(get_chroma_service())
                    graph = get_graph_rag()
                    agentic = get_agentic_rag(hybrid, graph)
                    from common.api_clients import get_deepseek_client
                    agentic.set_llm_client(get_deepseek_client())
                    result = await agentic.retrieve(text[:500], top_k=5, auto_refine=True)
                    n_results = len(result.get("results", []))
                    return f"RAG检索到 {n_results} 条结果, 置信度={result.get('self_rag', {}).get('confidence', 0):.2f}"
                except Exception as e:
                    return f"RAG检索失败: {str(e)[:80]}"

            elif action == ReActAction.ACCOUNT_CHECK:
                try:
                    from memory.manager import get_memory_manager
                    mem = get_memory_manager()
                    account_id = context.get("content", {}).get("account_id", "unknown")
                    if account_id and account_id != "unknown":
                        task_status = await mem.get_task_status(account_id)
                        return f"账号查询: {task_status}"
                    return "无账号ID，跳过账号查询"
                except Exception as e:
                    return f"账号查询失败: {str(e)[:80]}"

            elif action == ReActAction.FINALIZE:
                return f"最终判定: {action_input}"

            elif action == ReActAction.ESCALATE:
                return "证据不足，升级到人工审核"

            else:
                return f"未知动作: {action.value}"

        except Exception as e:
            return f"动作执行失败: {str(e)[:100]}"

    def _update_context(self, context: Dict, action: ReActAction, observation: str):
        """根据动作结果更新上下文"""
        if action == ReActAction.KEYWORD_CHECK and "敏感词" in observation:
            # 提取关键词
            context["known_keywords"].extend(
                observation.split(": ")[-1].strip("[]").split(", ")
            )

        elif action == ReActAction.HISTORY_SEARCH and "找到" in observation:
            context["known_similar_cases"].append(observation)

        elif action == ReActAction.ACCOUNT_CHECK:
            context["account_risk"] = observation

    def _build_trace(self, steps: List[ReActStep]) -> str:
        """构建推理链文本"""
        trace = []
        for s in steps:
            trace.append(
                f"[Step {s.step_num}] "
                f"Thought: {s.thought} | "
                f"Action: {s.action.value} | "
                f"Obs: {s.observation[:80]}"
            )
        return "\n".join(trace)


# 全局单例
_react_agent: Optional[ReActModerationAgent] = None


def get_react_agent() -> ReActModerationAgent:
    global _react_agent
    if _react_agent is None:
        _react_agent = ReActModerationAgent()
    return _react_agent
