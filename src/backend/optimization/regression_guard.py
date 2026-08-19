"""
优化回归守卫（R15·L2）— 优化后跑回归，变差自动回滚

解决现状问题：优化 Agent 执行动作后无验证，可能越改越差。

流程：
1. 优化前评估基线（before）
2. 执行优化动作
3. 优化后评估（after）
4. 关键指标变差超过容差 → 自动回滚 + 标记 rolled_back

evaluate_func 可注入（测试用 fake；生产接 T1 评测）。无评测能力时如实标记 unverified（不假装已验证）。
"""
import logging

logger = logging.getLogger(__name__)

DEFAULT_KEY = "f1"
DEFAULT_TOLERANCE = 0.02


def regressed(before: dict, after: dict, key: str = DEFAULT_KEY,
              tolerance: float = DEFAULT_TOLERANCE) -> bool:
    """判定是否回归：优化后指标低于优化前超过容差"""
    b = before.get(key)
    a = after.get(key)
    if b is None or a is None:
        return False  # 无指标可对比 → 不判定回归
    return b > a + tolerance


class RegressionGuard:
    """优化动作的回归守卫"""

    def __init__(self, evaluate_func=None, key: str = DEFAULT_KEY,
                 tolerance: float = DEFAULT_TOLERANCE):
        self.evaluate_func = evaluate_func
        self.key = key
        self.tolerance = tolerance

    async def _evaluate(self):
        if self.evaluate_func is None:
            return None
        return await self.evaluate_func()

    async def guard(self, apply_func, rollback_func, evaluate_func=None):
        """执行优化 → 回归检测 → 变差回滚。

        Args:
            apply_func: async，执行优化动作
            rollback_func: async，回滚优化动作
            evaluate_func: async -> dict（覆盖实例默认，None 时用实例的）

        Returns:
            {applied, rolled_back, verified, before, after}
        """
        ef = evaluate_func or self.evaluate_func
        before = await ef() if ef else None
        result = {"applied": False, "rolled_back": False, "verified": before is not None,
                  "before": before, "after": None}

        await apply_func()

        after = await ef() if ef else None
        result["after"] = after
        result["applied"] = True

        if after is None:
            logger.warning("[regression_guard] 无评测能力，优化结果未验证（unverified）")
            return result

        if regressed(before, after, self.key, self.tolerance):
            logger.warning(f"[regression_guard] 优化导致 {self.key} 回退 "
                           f"{before.get(self.key)} → {after.get(self.key)}，自动回滚")
            await rollback_func()
            result["rolled_back"] = True
            result["applied"] = False
        else:
            logger.info(f"[regression_guard] 优化通过回归（{self.key}: "
                        f"{before.get(self.key)} → {after.get(self.key)}）")
        return result
