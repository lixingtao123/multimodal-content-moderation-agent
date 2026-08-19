"""
终止双签校验（R7·E3）— 确定性规则硬终止

双签语义：
- 软签：大脑（brain_node）给出 terminate_suggested 建议
- 硬签：确定性规则校验（高危类型 / 硬阈值 / 双签确认）

规则（任一命中即强制 REJECT）：
1. 高危类型（violence/illegal）且风险分 ≥ 0.65 → 硬终止
2. 风险分 ≥ 0.9 → 硬终止（不依赖大脑）
3. 大脑建议终止 且 风险分 ≥ 0.75 → 双签通过 → 终止

可审计：reasons 逐条记录触发原因。
"""
from typing import Any

from agent_moderation.violation_types import FORCE_REJECT_TYPES


class TerminationChecker:
    HARD_REJECT_SCORE = 0.9
    DOUBLE_SIGN_SCORE = 0.75
    # R20: 统一引用 violation_types.py（含 crime）
    FORCE_REJECT_TYPES = FORCE_REJECT_TYPES

    def check(self, state: dict) -> dict:
        """对状态做确定性终止校验。返回 {hard_reject, reasons, brain_suggested, score}"""
        final_risk = state.get("final_risk") or {}
        score = float(final_risk.get("overall_score", 0.0))
        vts = set(final_risk.get("violation_types", []) or [])
        brain = state.get("_brain_decision") or {}
        brain_suggest = bool(brain.get("terminate_suggested"))

        reasons: list = []
        hard = False

        # 硬规则 1：高危类型 + 中等以上风险
        hit = vts & self.FORCE_REJECT_TYPES
        if hit and score >= 0.65:
            hard = True
            reasons.append(f"高危类型 {sorted(hit)} 且风险分 {score:.2f}≥0.65")

        # 硬规则 2：风险分超硬阈值（不依赖大脑）
        if score >= self.HARD_REJECT_SCORE:
            hard = True
            reasons.append(f"风险分 {score:.2f}≥0.9 硬阈值")

        # 硬规则 3：双签（大脑建议 + 确定性确认）
        if brain_suggest and score >= self.DOUBLE_SIGN_SCORE:
            hard = True
            reasons.append(f"大脑建议终止 + 风险分 {score:.2f}≥0.75（双签通过）")

        return {
            "hard_reject": hard,
            "reasons": reasons,
            "brain_suggested": brain_suggest,
            "score": score,
        }


def apply_termination_check(state: dict, checker: TerminationChecker = None) -> dict:
    """在 risk_agent 决策后调用：命中硬终止 → 覆盖为 REJECT 并记录 _termination。

    返回是否发生了硬终止。
    """
    checker = checker or TerminationChecker()
    verdict = checker.check(state)
    if verdict["hard_reject"]:
        state["final_decision"] = "REJECT"
        state["_termination"] = {
            "hard_reject": True,
            "reasons": verdict["reasons"],
            "brain_suggested": verdict["brain_suggested"],
            "score": verdict["score"],
            "checker": "TerminationChecker",
        }
        return True
    return False
