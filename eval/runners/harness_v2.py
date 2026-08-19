"""
Benchmark 体系 v2（R5·P1，修复 F6）— Track 注册制

架构：
- Track 接口：async run(context) -> TrackResult；describe() -> str
- EvalHarnessV2：register_track / run(track_filter) / report / compare
- baseline.json：固化基线，后续每次改动跑 diff 做回归检测（T1 不回退、T7 成本下降）

状态约定（诚实标注纪律）：
- status = "ok"（实测出指标）
- status = "skipped" + note（无数据/依赖缺失/待实现——显式标注，不装全实现）
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# 核心数据结构
# ------------------------------------------------------------
@dataclass
class TrackResult:
    track: str
    metrics: dict
    samples: int = 0
    duration: float = 0.0
    status: str = "ok"  # ok / skipped / error
    note: str = ""


class Track:
    """Track 接口：新增评测只写一个 Track 子类 + register_track"""
    name: str = "base"
    description: str = ""

    def describe(self) -> str:
        return f"[{self.name}] {self.description}"

    async def run(self, context: "EvalContext") -> TrackResult:
        raise NotImplementedError


@dataclass
class EvalContext:
    """共享上下文：数据加载器 / 审核函数 / 配置"""
    moderate_func: Optional[Callable] = None
    loader: object = None
    sample_per_cat: int = 20  # T1 每类抽样数
    negative_count: int = 200  # T1 负样本数
    config: dict = field(default_factory=dict)


# ------------------------------------------------------------
# Runner
# ------------------------------------------------------------
class EvalHarnessV2:
    """Track 注册制 Runner"""

    def __init__(self, context: Optional[EvalContext] = None):
        self.context = context or EvalContext()
        self._tracks: Dict[str, Track] = {}

    def register_track(self, track: Track) -> None:
        """注册一个 Track（新增评测只需写一个类 + 此行）"""
        self._tracks[track.name] = track

    def register_tracks(self, tracks: List[Track]) -> None:
        for t in tracks:
            self.register_track(t)

    @property
    def track_names(self) -> List[str]:
        return list(self._tracks.keys())

    async def run(self, track_filter: Optional[List[str]] = None) -> Dict[str, TrackResult]:
        """执行指定 Track（默认全部）。每个 Track 独立数据/指标，失败不阻断其他。"""
        names = [n for n in self.track_names if not track_filter or n in track_filter]
        results: Dict[str, TrackResult] = {}
        for name in names:
            track = self._tracks[name]
            started = time.time()
            try:
                r = await track.run(self.context)
                r.duration = time.time() - started
                if r.status == "ok":
                    logger.info(f"✓ {name}: {r.samples} samples, {r.duration:.1f}s")
                else:
                    logger.warning(f"⚠ {name}: {r.status} — {r.note}")
            except Exception as e:
                r = TrackResult(track=name, metrics={}, status="error",
                                note=str(e), duration=time.time() - started)
                logger.error(f"✗ {name} 执行异常: {e}")
            results[name] = r
        return results

    # ------------------------------------------------------------
    # 报告 / 基线 / 对比
    # ------------------------------------------------------------
    def report(self, results: Dict[str, TrackResult]) -> dict:
        """生成机读报告（含每条状态，绝不隐藏 skipped/error）"""
        return {
            "generated_at": _now(),
            "tracks": {
                name: {
                    "status": r.status,
                    "note": r.note,
                    "samples": r.samples,
                    "duration_sec": round(r.duration, 2),
                    "metrics": r.metrics,
                }
                for name, r in sorted(results.items())
            },
        }

    def report_markdown(self, results: Dict[str, TrackResult]) -> str:
        lines = ["# Benchmark 报告（harness_v2）", ""]
        lines.append("| Track | 状态 | 样本数 | 关键指标 |")
        lines.append("|---|---|---|---|")
        for name in sorted(results):
            r = results[name]
            if r.status == "ok":
                key = next(iter(r.metrics), "")
                val = r.metrics.get(key, "")
                lines.append(f"| {name} | ✅ | {r.samples} | {key}={val:.4f}" if isinstance(val, float) else
                             f"| {name} | ✅ | {r.samples} | {r.metrics} |")
            else:
                lines.append(f"| {name} | ⚠️ {r.status} | 0 | {r.note} |")
        return "\n".join(lines)

    def save_report(self, results: Dict[str, TrackResult], path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.report(results), f, ensure_ascii=False, indent=2)

    # ---- baseline ----
    def save_baseline(self, results: Dict[str, TrackResult], path: str) -> None:
        """固化基线（含状态与指标，作为后续对比基准）"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.report(results), f, ensure_ascii=False, indent=2)

    def load_baseline(self, path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def compare(self, results: Dict[str, TrackResult], baseline: dict) -> dict:
        """与基线对比，回归检测。

        规则：ok 的 Track 必须仍在 baseline 中且关键指标不回退（允许数值误差 1e-6）。
        Returns:
            {"regressions": [...], "summary": {...}}
        """
        regressions = []
        summary = {}
        base_tracks = baseline.get("tracks", {})
        for name, r in results.items():
            b = base_tracks.get(name)
            if r.status != "ok":
                if b and b.get("status") == "ok":
                    regressions.append({"track": name, "reason": "从 ok 变为 skipped/error"})
                summary[name] = "skipped_or_error"
                continue
            if not b or b.get("status") != "ok":
                summary[name] = "new"  # 基线没有的 track
                continue
            reg = _check_regression(name, r.metrics, b.get("metrics", {}))
            if reg:
                regressions.append(reg)
            summary[name] = "ok"
        return {"regressions": regressions, "summary": summary}


def _check_regression(name: str, current: dict, baseline: dict) -> Optional[dict]:
    """对 common 数值指标做回归检测（任一回退即报）"""
    for k, bval in baseline.items():
        if not isinstance(bval, (int, float)):
            continue
        cval = current.get(k)
        if not isinstance(cval, (int, float)):
            continue
        if cval < bval - 1e-6:
            return {"track": name, "metric": k, "baseline": bval, "current": cval,
                    "reason": f"{k} 回退 {bval} -> {cval}"}
    return None


def _now() -> str:
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")
