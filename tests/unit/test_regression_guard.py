"""
单元测试 — 优化回归守卫（R15·L2）
变差自动回滚 / 变好保留 / 无评测标记未验证 / 判定边界。
"""
import pytest

from optimization.optimization_agent import OptimizationAction, OptimizationAgent
from optimization.regression_guard import RegressionGuard, regressed


class TestRegressed:
    def test_worse_flagged(self):
        assert regressed({"f1": 0.9}, {"f1": 0.8}) is True

    def test_improved_not(self):
        assert regressed({"f1": 0.8}, {"f1": 0.9}) is False

    def test_same_within_tolerance(self):
        assert regressed({"f1": 0.9}, {"f1": 0.885}) is False  # 差 0.015 < 0.02

    def test_missing_metric_not(self):
        assert regressed({"f1": 0.9}, {"accuracy": 0.8}) is False


class TestGuard:
    @pytest.mark.asyncio
    async def test_regression_rolls_back(self):
        """优化变差 → 自动回滚（同一评测函数评估优化前后，apply 改变系统状态）"""
        applied, rolled_back = [], []
        state = {"f1": 0.8}

        async def ev():
            return dict(state)

        async def apply():
            state["f1"] = 0.7  # 优化使指标变差

        result = await RegressionGuard(evaluate_func=ev).guard(apply, lambda: _record(rolled_back))
        assert result["rolled_back"] is True
        assert result["applied"] is False  # 回滚后视为未生效
        assert rolled_back

    @pytest.mark.asyncio
    async def test_improved_not_rolled_back(self):
        """优化变好 → 不回滚"""
        rolled_back = []
        state = {"f1": 0.8}

        async def ev():
            return dict(state)

        async def apply():
            state["f1"] = 0.85  # 优化使指标变好

        result = await RegressionGuard(evaluate_func=ev).guard(apply, lambda: _record(rolled_back))
        assert result["rolled_back"] is False
        assert rolled_back == []

    @pytest.mark.asyncio
    async def test_unverified_without_eval(self):
        """无评测能力 → 标记未验证（诚实，不假装已验证）"""
        guard = RegressionGuard(evaluate_func=None)

        async def apply():
            return None

        result = await guard.guard(apply, apply)
        assert result["verified"] is False
        assert result["rolled_back"] is False


class TestAgentIntegration:
    @pytest.mark.asyncio
    async def test_with_guard_rolls_back(self):
        """优化 agent 接入：动作变差 → guard 触发回滚"""
        agent = OptimizationAgent()
        rolled_back = []
        action = OptimizationAction(action_type="keyword_update", target="violence",
                                    description="更新", reason="t")

        # monkeypatch _execute_action 返回 True，且动作使 evaluate 变差
        async def fake_exec(action, buffer_data):
            state["f1"] = 0.7
            return True

        state = {"f1": 0.8}

        async def fake_ev():
            return dict(state)

        original = agent._execute_action
        agent._execute_action = fake_exec
        snapshot = {"restore": lambda: _record(rolled_back)}
        try:
            result = await agent._execute_action_with_guard(
                action, [], evaluate_func=fake_ev, snapshot=snapshot)
        finally:
            agent._execute_action = original

        assert result["rolled_back"] is True
        assert rolled_back  # 回滚回调被调用


async def _ev(metrics):
    return metrics


async def _record(lst):
    lst.append(1)
