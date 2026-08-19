"""
单元测试 — 终止双签硬校验（R7·E3）
"""
from agent_moderation.state import create_initial_state
from agent_moderation.workers.termination_check import (
    TerminationChecker,
    apply_termination_check,
)


def _state(score=0.1, vts=None, brain_terminate=False):
    st = create_initial_state("t", "text", {"text": "x"})
    st["final_risk"] = {"overall_score": score, "violation_types": vts or []}
    st["_brain_decision"] = {"terminate_suggested": brain_terminate, "decisions": []}
    return st


class TestTerminationChecker:
    def test_low_risk_no_reject(self):
        v = TerminationChecker().check(_state(score=0.1))
        assert v["hard_reject"] is False
        assert v["reasons"] == []

    def test_high_risk_type_force_reject(self):
        """高危类型 + 中高风险 → 硬终止"""
        v = TerminationChecker().check(_state(score=0.7, vts=["violence"]))
        assert v["hard_reject"] is True

    def test_high_risk_type_low_score_no(self):
        """高危类型但分低 → 不终止（0.65 门槛）"""
        v = TerminationChecker().check(_state(score=0.3, vts=["violence"]))
        assert v["hard_reject"] is False

    def test_score_hard_threshold(self):
        """风险分 ≥0.9 → 硬终止（不依赖大脑）"""
        v = TerminationChecker().check(_state(score=0.95))
        assert v["hard_reject"] is True

    def test_double_sign_passes(self):
        """大脑建议 + 风险分≥0.75 → 双签通过"""
        v = TerminationChecker().check(_state(score=0.8, brain_terminate=True))
        assert v["hard_reject"] is True
        assert any("双签" in r for r in v["reasons"])

    def test_double_sign_fails_low_score(self):
        """大脑建议但分低 → 双签不通过"""
        v = TerminationChecker().check(_state(score=0.5, brain_terminate=True))
        assert v["hard_reject"] is False

    def test_brain_suggested_flag(self):
        v = TerminationChecker().check(_state(score=0.5, brain_terminate=True))
        assert v["brain_suggested"] is True


class TestApplyTerminationCheck:
    def test_applies_reject_and_records(self):
        state = _state(score=0.95)
        assert apply_termination_check(state) is True
        assert state["final_decision"] == "REJECT"
        assert state["_termination"]["hard_reject"] is True
        assert state["_termination"]["checker"] == "TerminationChecker"

    def test_no_change_when_not_hard(self):
        state = _state(score=0.1)
        assert apply_termination_check(state) is False
        assert state["final_decision"] == ""
        assert state.get("_termination") is None

    def test_state_default_termination_none(self):
        st = create_initial_state("t", "text", {"text": "x"})
        assert st["_termination"] is None
