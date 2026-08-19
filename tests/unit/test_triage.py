"""
单元测试 — 分诊台（R6·E2）+ state 新字段
"""
from agent_moderation.state import create_initial_state
from agent_moderation.workers.triage import LaneTier, TriageEngine, TriageDecision


def make_engine():
    return TriageEngine()


class TestTriageMapping:
    def test_trivial_pass_to_low(self):
        """简单正常文本 → 快车道 low"""
        d = make_engine().triage("今天天气不错，适合去公园散步")
        assert d.tier == LaneTier.LOW
        assert d.cost_saved is True
        assert isinstance(d, TriageDecision)

    def test_empty_to_low(self):
        d = make_engine().triage("")
        assert d.tier == LaneTier.LOW

    def test_unknown_returns_valid(self):
        """任何输入都能返回合法车道（不抛异常）"""
        d = make_engine().triage("加微信转账汇款，中奖了请联系我们")
        assert d.tier in (LaneTier.LOW, LaneTier.MED, LaneTier.HIGH)
        assert 0.0 <= d.risk <= 1.0
        assert 0 <= d.complexity <= 10

    def test_risk_bounds(self):
        for text in ["你好", "加微信返利", "这是一段" * 200]:
            d = make_engine().triage(text)
            assert 0.0 <= d.risk <= 1.0


class TestStateFields:
    def test_tier_default_none(self):
        state = create_initial_state("t1", "text", {"text": "你好"})
        assert state["_tier"] is None
        assert state["_triage"] is None
        assert state["_brain_decision"] is None
