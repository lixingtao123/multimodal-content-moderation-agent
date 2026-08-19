"""
单元测试 — ModelRouter TIER4_ESCALATE（R20 打通 HIGH 车道）

背景：此前 route() 永不返回 TIER4_ESCALATE → triage 的 HIGH 车道是死代码，
brain_node 端到端不可达、终止双签规则3永不触发。R20 修复后验证：
  - 超长文本（≥800字）→ TIER4_ESCALATE → triage HIGH lane
  - >150 字无信号文本不再直接 Tier1 PASS（长文本零信号是异常信号）
  - 强信号堆叠（≥5）→ TIER4_ESCALATE
  - get_stats 含 tier4 计数
"""
from agent_moderation.workers.model_router import ModelRouter, RouteTier
from agent_moderation.workers.triage import LaneTier, TriageEngine


class TestModelRouterTier4:
    def test_very_long_text_escalates(self):
        """超长文本（1200字）→ TIER4_ESCALATE"""
        r = ModelRouter()
        d = r.route("这是一段用于测试审核路由的超长文本内容。" * 100)  # ~1200 字
        assert d.tier == RouteTier.TIER4_ESCALATE

    def test_long_no_signal_not_tier1_pass(self):
        """200 字无信号文本不再直接 PASS（长文本零信号=异常，需 LLM 确认）"""
        r = ModelRouter()
        d = r.route("这是一个比较长的句子但没有任何违规信号。" * 12)  # ~210 字
        assert d.tier != RouteTier.TIER1_RULES or d.pre_judgment != "PASS"
        assert d.tier in (RouteTier.TIER2_HEURISTIC, RouteTier.TIER3_LLM,
                          RouteTier.TIER4_ESCALATE)

    def test_short_no_signal_still_pass(self):
        """短文本无信号仍走快车道（保持 Tier1 PASS 能力）"""
        r = ModelRouter()
        d = r.route("今天天气很好")
        assert d.tier == RouteTier.TIER1_RULES
        assert d.pre_judgment == "PASS"
        assert d.cost_saved is True

    def test_many_signals_escalate(self):
        """中度信号堆叠≥5 → TIER4_ESCALATE"""
        r = ModelRouter()
        d = r.route("加微信赚钱扫码兼职，诈骗转账银行卡密码验证码泄露")
        assert d.tier == RouteTier.TIER4_ESCALATE

    def test_stats_include_tier4(self):
        """get_stats 暴露 tier4 计数（能力报告可读）"""
        r = ModelRouter()
        r.route("这是一段用于测试审核路由的超长文本内容。" * 100)
        stats = r.get_stats()
        assert stats["tier4"] == 1
        assert "tier4_rate" in stats

    def test_800_boundary_escalates(self):
        """恰好 ≥800 字 → TIER4（边界）"""
        r = ModelRouter()
        text = "字" * 800
        d = r.route(text)
        assert d.tier == RouteTier.TIER4_ESCALATE


class TestTriageHighLane:
    def test_tier4_maps_to_high(self):
        """TIER4_ESCALATE → HIGH lane（brain_node 可达前提）"""
        d = TriageEngine().triage("这是一段用于测试审核路由的超长文本内容。" * 100)
        assert d.tier == LaneTier.HIGH
        assert d.complexity >= 8

    def test_trivial_still_low(self):
        """平凡文本仍映射 LOW（不回归）"""
        d = TriageEngine().triage("今天天气不错")
        assert d.tier == LaneTier.LOW
