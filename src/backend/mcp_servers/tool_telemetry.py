"""
工具质量分（R11·T3）— 每次调用记录正贡献 → 质量分 → 降权/灰度/下线建议

质量分 = 成功率 × (0.5 + 0.5 × 正贡献率)
- 正贡献：工具结果对最终判定有正向作用（调用方上报）
- 建议：score ≥ 0.7 正常 / 0.5-0.7 降权 / < 0.5 下线候选

存储：内存 dict（进程内）。持久化到 PG/Redis 属后续（与 T3 完整评测同期）。
"""
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

DEGRADE_THRESHOLD = 0.7
OFFLINE_THRESHOLD = 0.5


class ToolTelemetry:
    def __init__(self):
        self._stats: dict = defaultdict(
            lambda: {"calls": 0, "success": 0, "positive": 0, "last": 0.0})

    def record(self, tool_name: str, success: bool = True,
               positive_contribution: bool = False) -> None:
        """记录一次工具调用。positive_contribution：结果对判定有正贡献。"""
        st = self._stats[tool_name]
        st["calls"] += 1
        if success:
            st["success"] += 1
        if positive_contribution:
            st["positive"] += 1

    def quality_score(self, tool_name: str) -> float:
        """质量分：成功率 × (0.5 + 0.5 × 正贡献率)；无调用返回 0"""
        st = self._stats.get(tool_name)
        if not st or st["calls"] == 0:
            return 0.0
        success_rate = st["success"] / st["calls"]
        positive_rate = st["positive"] / st["calls"]
        return success_rate * (0.5 + 0.5 * positive_rate)

    def suggest(self, tool_name: str) -> str:
        """治理建议：normal / downgrade / offline"""
        score = self.quality_score(tool_name)
        if score >= DEGRADE_THRESHOLD:
            return "normal"
        if score >= OFFLINE_THRESHOLD:
            return "downgrade"
        return "offline"

    def snapshot(self) -> dict:
        """全量统计（含质量分与建议）"""
        return {
            name: {"calls": st["calls"], "success": st["success"],
                   "positive": st["positive"], "quality": self.quality_score(name),
                   "suggest": self.suggest(name)}
            for name, st in sorted(self._stats.items())
        }

    def top_positive(self, n: int = 5) -> list:
        """正贡献率最高的工具（用于灰度放量）"""
        ranked = sorted(self._stats.items(),
                        key=lambda kv: kv[1]["positive"] / max(kv[1]["calls"], 1),
                        reverse=True)
        return [name for name, _ in ranked[:n]]


# 全局单例
_telemetry = None


def get_tool_telemetry() -> ToolTelemetry:
    global _telemetry
    if _telemetry is None:
        _telemetry = ToolTelemetry()
    return _telemetry
