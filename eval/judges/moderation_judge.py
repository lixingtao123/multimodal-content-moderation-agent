"""
LLM-as-Judge — 使用 LLM 自动评估审核质量

评估维度:
  1. Decision Accuracy: 判定是否正确
  2. Type Accuracy: 违规类型是否正确
  3. Confidence Calibration: 置信度是否合理
  4. Evidence Quality: 提供的证据是否充分

技术参考:
  - Judge-Bench (2025): Standardized LLM-as-Judge Evaluation
  - MT-Bench (Zheng et al., 2024): Multi-turn conversation evaluation
"""
import json
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class JudgeVerdict:
    """LLM Judge 的判定"""
    is_correct: bool
    confidence_score: float
    reasoning: str
    error_type: Optional[str] = None  # false_positive / false_negative / wrong_type / none
    suggestions: List[str] = None


class ModerationJudge:
    """
    审核结果评判器

    使用 LLM 评估审核输出的质量，提供:
    - 判定正确性
    - 错误分析
    - 改进建议
    """

    JUDGE_PROMPT = """你是内容审核质量评估专家。评估以下审核结果是否合理。

=== 原始内容 ===
{content}

=== 审核结果 ===
- 判定: {decision}
- 违规类型: {violation_types}
- 置信度: {confidence:.2f}
- 风险分: {risk_score:.2f}
- 判定依据: {reason}

=== 期望结果 ===
- 期望判定: {expected_decision}
- 期望违规类型: {expected_types}

请评估:
1. 判定是否正确?
2. 如果不正确，是什么类型的错误 (false_positive/false_negative/wrong_type)?
3. 置信度是否与内容严重度匹配?
4. 给出改进建议。

只返回JSON:
{{
  "is_correct": true/false,
  "error_type": "none|false_positive|false_negative|wrong_type",
  "confidence_calibration": "well_calibrated|overconfident|underconfident",
  "reasoning": "评估依据",
  "suggestions": ["建议1", "建议2"]
}}
"""

    def __init__(self):
        self._llm_client = None

    def set_llm_client(self, client):
        self._llm_client = client

    async def judge(
        self,
        content: str,
        decision: str,
        violation_types: List[str],
        confidence: float,
        risk_score: float,
        reason: str,
        expected_decision: str,
        expected_types: List[str],
    ) -> JudgeVerdict:
        """评估单个审核结果"""
        if not self._llm_client:
            return self._heuristic_judge(
                decision, expected_decision, violation_types, expected_types
            )

        prompt = self.JUDGE_PROMPT.format(
            content=content[:500],
            decision=decision,
            violation_types=", ".join(violation_types) if violation_types else "none",
            confidence=confidence,
            risk_score=risk_score,
            reason=reason[:300],
            expected_decision=expected_decision,
            expected_types=", ".join(expected_types) if expected_types else "none",
        )

        try:
            response = await self._llm_client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=400,
            )
            result = json.loads(response.choices[0].message.content)
            return JudgeVerdict(
                is_correct=result.get("is_correct", False),
                confidence_score=1.0 if result.get("is_correct") else 0.3,
                reasoning=result.get("reasoning", ""),
                error_type=result.get("error_type", "none"),
                suggestions=result.get("suggestions", []),
            )
        except Exception as e:
            logger.warning(f"LLM judge failed: {e}")
            return self._heuristic_judge(
                decision, expected_decision, violation_types, expected_types
            )

    def _heuristic_judge(
        self, decision: str, expected: str,
        violation_types: List[str], expected_types: List[str],
    ) -> JudgeVerdict:
        """基于规则的评判 (无 LLM 时的回退)"""
        # 决策匹配
        decision_correct = (decision == expected)
        # 允许 REVIEW 在 PASS/REJECT 之间有一定容差
        if not decision_correct:
            if expected == "REVIEW" and decision in ("PASS", "REJECT"):
                decision_correct = False
            elif expected == "PASS" and decision == "REVIEW":
                decision_correct = False  # 正常内容标 REVIEW 算部分错

        # 类型匹配
        type_overlap = len(set(violation_types) & set(expected_types)) if expected_types else 0
        type_expected = len(expected_types) if expected_types else 1
        type_match = type_overlap / type_expected > 0.5 if expected_types else True

        is_correct = decision_correct and type_match

        if not decision_correct:
            error_type = "false_positive" if decision in ("REVIEW", "REJECT") else "false_negative"
        elif not type_match:
            error_type = "wrong_type"
        else:
            error_type = "none"

        return JudgeVerdict(
            is_correct=is_correct,
            confidence_score=0.8 if is_correct else 0.2,
            reasoning=f"Decision match: {decision_correct}, Type match: {type_match}",
            error_type=error_type,
            suggestions=[] if is_correct else ["建议复核审核标准"],
        )

    async def batch_judge(self, samples: List[Dict]) -> List[JudgeVerdict]:
        """批量评估"""
        verdicts = []
        for s in samples:
            verdict = await self.judge(**s)
            verdicts.append(verdict)
        return verdicts

    def aggregate_scores(self, verdicts: List[JudgeVerdict]) -> Dict:
        """汇总评估结果"""
        total = len(verdicts)
        correct = sum(1 for v in verdicts if v.is_correct)
        errors = {}
        for v in verdicts:
            if v.error_type and v.error_type != "none":
                errors[v.error_type] = errors.get(v.error_type, 0) + 1

        return {
            "total": total,
            "correct": correct,
            "accuracy": correct / max(total, 1),
            "error_distribution": errors,
            "avg_confidence": sum(v.confidence_score for v in verdicts) / max(total, 1),
            "suggestions": sum((v.suggestions or [] for v in verdicts), []),
        }
