"""
Reflexion Agent v1.0 — 自我反思与迭代改进

Reflexion 模式 (Shinn et al., 2023) 的核心思想:
  - Agent 不仅输出结果，还要自我评估结果质量
  - 发现不足后，主动搜索更多信息
  - 基于新信息修正判断
  - 循环直到达到质量标准或最大迭代次数

三大组件:
  1. Actor: 生成初始判断 (即现有的 TextAgent/ImageAgent 等)
  2. Evaluator: 自评判断质量，识别薄弱点
  3. Self-Reflection: 记录反思经验，指导下一次判断

LangGraph 实现:
  [Agent输出] → [Evaluator评估] → {充分?} → END
                              ↘ {不足} → [Reflection反思]
                                            ↓
                                     [Retrieve搜索] → [Revise修正] → [Evaluator评估]

技术参考:
  - Reflexion (Shinn et al., NeurIPS 2023): Language Agents with Verbal Reinforcement
  - Self-Refine (Madaan et al., 2023): Iterative Refinement with Self-Feedback
  - ReAct (Yao et al., 2023): Reasoning + Acting in Language Models
"""
import json
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from common.api_clients import get_deepseek_model

logger = logging.getLogger(__name__)


@dataclass
class ReflectionMemory:
    """反思记忆 — 记录历史反思经验"""
    content_id: str
    initial_decision: str
    initial_confidence: float
    reflection: str
    revised_decision: str
    revised_confidence: float
    improvement: float  # 改进幅度
    timestamp: str = ""


@dataclass
class ReflexionResult:
    """Reflexion 结果"""
    content_id: str
    initial_decision: str
    initial_confidence: float
    final_decision: str
    final_confidence: float
    reflection_applied: bool
    reflections: List[str] = field(default_factory=list)
    improvements: List[Dict] = field(default_factory=list)
    rounds: int = 0
    summary: str = ""


class ReflexionEvaluator:
    """
    自评估器 — 判定 Agent 输出是否足够可靠

    评估维度:
    1. 置信度是否达到阈值
    2. 证据链是否完整
    3. 是否存在对抗样本信号
    4. 历史案例是否充分匹配
    """

    # 各类违规类型的最低置信度阈值
    CONFIDENCE_THRESHOLDS = {
        "violence": 0.75,
        "porn": 0.70,
        "politics": 0.80,
        "illegal": 0.75,
        "crime": 0.75,  # R20: 官方枚举
        "terrorism": 0.80,
        "phishing": 0.65,
        "advertisement": 0.60,
        "harassment": 0.65,
        "false_info": 0.70,
        "bulk_generation": 0.55,
        "keyword_variant": 0.50,
        "char_noise": 0.50,
        "none": 0.30,
    }

    # 需要人工复核的标志
    REVIEW_FLAGS = [
        "is_adversarial",
        "api_content_filter",
        "hash_similarity_high",
        "low_confidence",
        "conflicting_signals",
    ]

    def evaluate(self, agent_result: dict, content_type: str) -> Dict:
        """
        评估 Agent 结果质量

        Returns:
            {
                "is_sufficient": bool,
                "confidence_gap": float,  # 与阈值的差距
                "issues": List[str],  # 发现的问题
                "suggestions": List[str],  # 改进建议
                "review_flags": List[str],  # 复核标志
            }
        """
        issues = []
        suggestions = []
        review_flags = []

        violation_type = agent_result.get("violation_type", "none")
        confidence = agent_result.get("confidence", 0.0)
        risk_score = agent_result.get("risk_score", 0.0)
        similar_count = agent_result.get("similar_cases_count", 0)
        is_adversarial = agent_result.get("is_adversarial", False)

        # 1. 置信度检查
        threshold = self.CONFIDENCE_THRESHOLDS.get(violation_type, 0.65)
        confidence_gap = threshold - confidence

        if confidence < threshold:
            issues.append(
                f"置信度 {confidence:.2f} 低于阈值 {threshold:.2f}"
            )
            suggestions.append("建议重新审核并收集更多证据")
            review_flags.append("low_confidence")

        # 2. 证据检查
        if violation_type != "none" and similar_count == 0:
            issues.append("无相似历史案例支撑判定")
            suggestions.append("建议扩大历史案例检索范围")

        if violation_type != "none" and risk_score < 0.3:
            issues.append(f"风险分 {risk_score:.2f} 与违规类型 {violation_type} 不匹配")
            suggestions.append("建议复核违规类型是否准确")

        # 3. 对抗样本检查
        if is_adversarial:
            issues.append("检测到对抗样本特征")
            suggestions.append("建议使用深层语义分析对抗样本变体")
            review_flags.append("is_adversarial")

        # 4. 内容过滤触发检查
        if agent_result.get("_content_filtered"):
            review_flags.append("api_content_filter")
            suggestions.append("API内容过滤器触发，建议人工确认")

        is_sufficient = len(issues) == 0

        return {
            "is_sufficient": is_sufficient,
            "confidence_gap": confidence_gap,
            "issues": issues,
            "suggestions": suggestions,
            "review_flags": review_flags,
            "threshold": threshold,
        }

    def should_reflex(self, eval_result: Dict) -> bool:
        """判断是否需要触发 Reflexion 循环"""
        return not eval_result["is_sufficient"]


class ReflexionLoop:
    """
    Reflexion 自反思循环

    工作流:
    1. 接收 Agent 初始输出
    2. Evaluator 自评质量
    3. 如果不充分:
       a. 生成反思 (Reflection): 分析为什么不够好
       b. 生成改进计划 (Action Plan): 需要做什么来改进
       c. 执行改进 (Retrieve more evidence)
       d. 修正判断 (Revise)
    4. 循环直到充分或达到最大轮次
    """

    MAX_REFLEXION_ROUNDS = 2  # 最多 2 轮反思
    MIN_IMPROVEMENT = 0.05   # 最小置信度改善幅度，低于此值停止

    def __init__(self):
        self.evaluator = ReflexionEvaluator()
        self.reflection_memory: List[ReflectionMemory] = []
        self._llm_client = None

    def set_llm_client(self, client):
        """设置 LLM 客户端"""
        self._llm_client = client

    async def run(
        self,
        content_id: str,
        agent_result: dict,
        content_type: str,
        context: dict = None,
    ) -> ReflexionResult:
        """
        执行 Reflexion 自反思循环

        Args:
            content_id: 内容 ID
            agent_result: Agent 初始输出
            content_type: 内容类型
            context: 额外上下文 (原始内容、历史案例等)

        Returns:
            ReflexionResult
        """
        reflections = []
        improvements = []
        current_result = dict(agent_result)
        initial_decision = agent_result.get("violation_type", "none")
        initial_confidence = agent_result.get("confidence", 0.0)

        for round_idx in range(1, self.MAX_REFLEXION_ROUNDS + 1):
            # Step 1: 自评
            eval_result = self.evaluator.evaluate(current_result, content_type)

            if eval_result["is_sufficient"]:
                logger.info(f"Reflexion round {round_idx}: 结果充分，停止反思")
                break

            # Step 2: 生成反思
            reflection = await self._generate_reflection(
                current_result, eval_result, content_type, context
            )
            reflections.append(reflection)

            # Step 3: 生成改进计划 → 修正判断
            revised = await self._revise_judgment(
                current_result, reflection, eval_result, content_type
            )

            if revised:
                old_conf = current_result.get("confidence", 0.0)
                new_conf = revised.get("confidence", 0.0)
                improvement = new_conf - old_conf

                improvements.append({
                    "round": round_idx,
                    "old_confidence": old_conf,
                    "new_confidence": new_conf,
                    "improvement": improvement,
                    "reflection": reflection,
                })

                current_result.update(revised)

                # 检查改进幅度
                if improvement < self.MIN_IMPROVEMENT:
                    logger.info(f"Reflexion round {round_idx}: 改进幅度 {improvement:.3f} < {self.MIN_IMPROVEMENT}，停止")
                    break
            else:
                logger.warning(f"Reflexion round {round_idx}: 修正失败")
                break

        # 记录反思记忆
        memory = ReflectionMemory(
            content_id=content_id,
            initial_decision=initial_decision,
            initial_confidence=initial_confidence,
            reflection="; ".join(reflections),
            revised_decision=current_result.get("violation_type", initial_decision),
            revised_confidence=current_result.get("confidence", initial_confidence),
            improvement=current_result.get("confidence", 0.0) - initial_confidence,
        )
        self.reflection_memory.append(memory)

        return ReflexionResult(
            content_id=content_id,
            initial_decision=initial_decision,
            initial_confidence=initial_confidence,
            final_decision=current_result.get("violation_type", initial_decision),
            final_confidence=current_result.get("confidence", initial_confidence),
            reflection_applied=len(reflections) > 0,
            reflections=reflections,
            improvements=improvements,
            rounds=len(reflections),
            summary=self._build_summary(memory),
        )

    async def _generate_reflection(
        self, result: dict, eval_result: dict, content_type: str, context: dict = None
    ) -> str:
        """生成反思: 分析当前判定的不足之处"""
        if not self._llm_client:
            return self._rule_based_reflection(result, eval_result)

        issues_text = "\n".join(f"- {i}" for i in eval_result.get("issues", []))
        suggestions_text = "\n".join(f"- {s}" for s in eval_result.get("suggestions", []))

        prompt = f"""你是内容审核质量分析师。请分析以下审核结果的问题并提出改进方向。

当前判定:
- 违规类型: {result.get('violation_type', 'unknown')}
- 置信度: {result.get('confidence', 0):.2f}
- 风险分: {result.get('risk_score', 0):.2f}
- 内容类型: {content_type}

发现的问题:
{issues_text}

改进建议:
{suggestions_text}

请分析:
1. 当前判定最大的不确定性是什么?
2. 需要补充什么信息来提高判定准确度?
3. 一句话改进建议。

只返回JSON: {{"uncertainty": "...", "missing_info": "...", "improvement_action": "..."}}
"""
        try:
            response = await self._llm_client.chat.completions.create(
                model=get_deepseek_model(),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=300,
            )
            result = json.loads(response.choices[0].message.content)
            return f"不确定性: {result.get('uncertainty', '')}; 缺失信息: {result.get('missing_info', '')}; 改进建议: {result.get('improvement_action', '')}"
        except Exception as e:
            logger.warning(f"LLM reflection failed: {e}")
            return self._rule_based_reflection(result, eval_result)

    def _rule_based_reflection(self, result: dict, eval_result: dict) -> str:
        """基于规则的反思 (无 LLM 时的回退)"""
        parts = []
        for issue in eval_result.get("issues", []):
            if "置信度" in issue:
                parts.append("置信度不足，需更多证据支撑")
            if "相似" in issue:
                parts.append("缺乏历史案例佐证，需扩大检索")
            if "对抗" in issue:
                parts.append("疑似对抗样本，需深层语义分析")
        return "; ".join(parts) if parts else "无明确问题"

    async def _revise_judgment(
        self, result: dict, reflection: str, eval_result: dict, content_type: str
    ) -> Optional[dict]:
        """基于反思修正判断"""
        # 核心策略: 根据反思降低或调整置信度

        revised = dict(result)
        confidence_gap = eval_result.get("confidence_gap", 0)

        # 如果置信度不足，根据问题标记调整
        if eval_result.get("review_flags"):
            if "low_confidence" in eval_result["review_flags"]:
                # 保留原判定但降低置信度为更保守的估计
                revised["confidence"] = min(result.get("confidence", 0) * 0.85, 0.5)

            if "is_adversarial" in eval_result["review_flags"]:
                # 对抗样本: 提高风险分但在reason中标记
                revised["risk_score"] = min(result.get("risk_score", 0) * 1.2, 0.95)
                revised["tags"] = result.get("tags", []) + ["reflexion_adversarial"]

        # 标记此结果经过反思
        revised["reflexion_applied"] = True
        revised["reflexion_note"] = reflection

        return revised

    def _build_summary(self, memory: ReflectionMemory) -> str:
        """构建反思总结"""
        if memory.improvement > 0.05:
            return (
                f"Reflexion: {memory.initial_decision}→{memory.revised_decision}, "
                f"置信度 {memory.initial_confidence:.2f}→{memory.revised_confidence:.2f} "
                f"(+{memory.improvement:.2f})"
            )
        elif memory.improvement > 0:
            return (
                f"Reflexion: 轻微改善 {memory.initial_confidence:.2f}→"
                f"{memory.revised_confidence:.2f}"
            )
        else:
            return "Reflexion: 维持原判定"


# 全局单例
_reflexion_loop: Optional[ReflexionLoop] = None


def get_reflexion_loop() -> ReflexionLoop:
    global _reflexion_loop
    if _reflexion_loop is None:
        _reflexion_loop = ReflexionLoop()
    return _reflexion_loop
