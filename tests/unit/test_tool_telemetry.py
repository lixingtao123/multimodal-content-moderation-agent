"""
单元测试 — 工具质量分（R11·T3）
质量分计算 / 治理建议 / 接入 reliability 层自动记录。
"""
import pytest

from mcp_servers.registry import get_tool_registry
from mcp_servers.tool_telemetry import ToolTelemetry, get_tool_telemetry
from mcp_servers.tool_reliability import ToolCallError, call_with_reliability


@pytest.fixture
def telemetry():
    return ToolTelemetry()


class TestQualityScore:
    def test_no_calls_zero(self, telemetry):
        assert telemetry.quality_score("none") == 0.0

    def test_all_success_all_positive(self, telemetry):
        telemetry.record("kw", success=True, positive_contribution=True)
        telemetry.record("kw", success=True, positive_contribution=True)
        assert telemetry.quality_score("kw") == pytest.approx(1.0)

    def test_half_success(self, telemetry):
        telemetry.record("kw", success=True)
        telemetry.record("kw", success=False)
        # 0.5 * (0.5 + 0) = 0.25
        assert telemetry.quality_score("kw") == pytest.approx(0.25)

    def test_success_with_positive_boosts(self, telemetry):
        telemetry.record("kw", success=True, positive_contribution=True)
        telemetry.record("kw", success=True, positive_contribution=False)
        # 1.0 * (0.5 + 0.5*0.5) = 0.75
        assert telemetry.quality_score("kw") == pytest.approx(0.75)


class TestSuggest:
    def test_normal(self, telemetry):
        for _ in range(5):
            telemetry.record("kw", success=True, positive_contribution=True)
        assert telemetry.suggest("kw") == "normal"

    def test_downgrade(self, telemetry):
        for _ in range(4):
            telemetry.record("kw", success=True, positive_contribution=False)
        # 1.0 * (0.5+0) = 0.5 → downgrade
        assert telemetry.suggest("kw") == "downgrade"

    def test_offline(self, telemetry):
        telemetry.record("kw", success=True)
        telemetry.record("kw", success=False)
        telemetry.record("kw", success=False)
        # 0.33 * (0.5) ≈ 0.166 → offline
        assert telemetry.suggest("kw") == "offline"

    def test_snapshot_and_top(self, telemetry):
        telemetry.record("a", success=True, positive_contribution=True)
        telemetry.record("b", success=True, positive_contribution=False)
        snap = telemetry.snapshot()
        assert "quality" in snap["a"]
        assert telemetry.top_positive(n=1) == ["a"]


class TestReliabilityIntegration:
    @pytest.mark.asyncio
    async def test_success_records(self):
        """reliability 成功调用自动记录（质量分上升）"""
        t = ToolTelemetry()
        # 临时替换全局 telemetry 难，直接验证 call_with_reliability 调用后全局有记录
        global_t = get_tool_telemetry()
        before = global_t.snapshot().get("keyword_check", {}).get("calls", 0)
        await call_with_reliability(get_tool_registry(), "keyword_check", {"text": "加微信"})
        after = global_t.snapshot().get("keyword_check", {}).get("calls", 0)
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_failure_records(self):
        global_t = get_tool_telemetry()
        before = global_t.snapshot().get("keyword_check", {}).get("calls", 0)
        with pytest.raises(ToolCallError):
            await call_with_reliability(get_tool_registry(), "keyword_check", {})
        after = global_t.snapshot().get("keyword_check", {}).get("calls", 0)
        assert after == before + 1
