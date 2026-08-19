"""
单元测试 — Benchmark 体系 v2（R5·P1）
Track 注册制 / T1 管道 / T3 接入 / 骨架标注 / baseline 回归检测。
"""
import json
import os
import tempfile

import pytest

from eval.runners.harness_v2 import EvalContext, EvalHarnessV2, Track, TrackResult
from eval.runners.tracks_v2 import (
    T1IntentTrack,
    T2AdversarialTrack,
    T3RagTrack,
    T7CostTrack,
    _binary_metrics,
    build_default_tracks,
)


class TestRegistry:
    def test_register_and_run(self):
        ctx = EvalContext()
        harness = EvalHarnessV2(ctx)

        class FakeTrack(Track):
            name = "fake"
            description = "测试"

            async def run(self, ctx):
                return TrackResult(track=self.name, metrics={"m": 1.0}, samples=3)

        harness.register_track(FakeTrack())
        assert harness.track_names == ["fake"]
        results = pytest_runner(harness)
        assert results["fake"].status == "ok"
        assert results["fake"].metrics["m"] == 1.0

    def test_default_tracks_registered(self):
        harness = EvalHarnessV2()
        harness.register_tracks(build_default_tracks())
        assert set(harness.track_names) == {
            "T1_intent", "T2_adversarial", "T3_rag", "T4_skill",
            "T5_multimodal", "T6_agent", "T7_cost"}

    def test_track_filter(self):
        harness = EvalHarnessV2()
        harness.register_tracks(build_default_tracks())
        results = pytest_runner(harness, track_filter=["T7_cost"])
        assert list(results.keys()) == ["T7_cost"]


class TestTracksReal:
    @pytest.mark.asyncio
    async def test_t2_metrics_with_fake_func(self):
        """T2 用确定性 fake 审核函数跑通管道（对抗样本全拦截）"""
        async def always_reject(content):
            return {"final_decision": "REJECT", "risk_score": 0.9, "lane": "med"}
        ctx = EvalContext(moderate_func=always_reject, config={"t2_variants": 5})
        result = await T2AdversarialTrack().run(ctx)
        assert result.status == "ok"
        assert result.metrics["intercept_recall"] == 1.0
        assert result.samples > 0

    @pytest.mark.asyncio
    async def test_t7_metrics_with_fake_func(self):
        """T7 用确定性 fake 审核函数产出成本指标（真实管道，非骨架 skipped）"""
        async def fake_func(content):
            return {"final_decision": "PASS", "risk_score": 0.1, "lane": "med",
                    "duration_ms": 100.0, "used_fast_lane": False, "upgraded": False}
        ctx = EvalContext(moderate_func=fake_func, sample_per_cat=1, negative_count=2,
                          config={"t7_per_cat": 1})
        result = await T7CostTrack().run(ctx)
        assert result.status == "ok"
        assert result.metrics["avg_latency_ms"] == 100.0
        assert result.metrics["p50_latency_ms"] == 100.0
        assert result.metrics["est_total_tokens"] > 0


class TestT1BinaryMetrics:
    def test_perfect(self):
        m = _binary_metrics(["REJECT", "PASS"], ["REJECT", "PASS"])
        assert m["accuracy"] == 1.0
        assert m["fpr"] == 0.0
        assert m["f1"] == 1.0

    def test_all_reject(self):
        m = _binary_metrics(["REJECT", "PASS"], ["REJECT", "REJECT"])
        assert m["accuracy"] == 0.5
        assert m["fpr"] == 1.0
        assert m["precision"] == 0.5

    def test_empty(self):
        m = _binary_metrics([], [])
        assert m["accuracy"] == 0.0


class TestT1Pipeline:
    async def _always_reject(self, content):
        return {"final_decision": "REJECT", "violation_types": [], "risk_score": 0.9}

    @pytest.mark.asyncio
    async def test_t1_pipeline_with_fake_func(self):
        """T1 用 fake 审核函数跑通管道（确定性指标）"""
        ctx = EvalContext(moderate_func=self._always_reject,
                          sample_per_cat=2, negative_count=1000)
        track = T1IntentTrack()
        result = await track.run(ctx)
        assert result.status == "ok"
        # 正样本 9×2=18，负样本裁剪到 18；全 REJECT → accuracy=0.5, fpr=1.0
        assert result.samples == 36
        assert result.metrics["accuracy"] == pytest.approx(0.5)
        assert result.metrics["fpr"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_t1_skipped_without_func_and_key(self):
        """无审核函数 + 无 key → skipped（诚实标注）"""
        import os
        old = os.environ.get("DEEPSEEK_API_KEY")
        os.environ.pop("DEEPSEEK_API_KEY", None)
        try:
            ctx = EvalContext(moderate_func=None)
            result = await T1IntentTrack().run(ctx)
            assert result.status == "skipped"
        finally:
            if old:
                os.environ["DEEPSEEK_API_KEY"] = old


class TestT3Track:
    @pytest.mark.asyncio
    async def test_t3_runs_small(self):
        """T3 接入真实数据（小规模 BM25 路）出指标"""
        ctx = EvalContext(config={"t3_candidates": 3, "t3_queries": 1,
                                  "t3_dense": False, "t3_k": 3})
        result = await T3RagTrack().run(ctx)
        assert result.status == "ok"
        assert result.samples == 9
        assert 0.0 <= result.metrics["best_ndcg_at_k"] <= 1.0


class TestBaselineCompare:
    def test_compare_no_regression(self):
        harness = EvalHarnessV2()
        results = {
            "T1_intent": TrackResult(track="T1_intent", metrics={"accuracy": 0.9}, samples=10),
        }
        baseline = harness.report(results)  # 自身作为基线
        cmp = harness.compare(results, baseline)
        assert cmp["regressions"] == []

    def test_compare_detects_regression(self):
        harness = EvalHarnessV2()
        results = {
            "T1_intent": TrackResult(track="T1_intent", metrics={"accuracy": 0.7}, samples=10),
        }
        baseline = {"tracks": {"T1_intent": {"status": "ok", "metrics": {"accuracy": 0.9}}}}
        cmp = harness.compare(results, baseline)
        assert len(cmp["regressions"]) == 1
        assert cmp["regressions"][0]["reason"] == "accuracy 回退 0.9 -> 0.7"

    def test_compare_detects_ok_to_skipped(self):
        harness = EvalHarnessV2()
        results = {
            "T1_intent": TrackResult(track="T1_intent", metrics={}, status="skipped", note="x"),
        }
        baseline = {"tracks": {"T1_intent": {"status": "ok", "metrics": {"accuracy": 0.9}}}}
        cmp = harness.compare(results, baseline)
        assert len(cmp["regressions"]) == 1

    def test_save_load_baseline_roundtrip(self):
        harness = EvalHarnessV2()
        results = {"T1_intent": TrackResult(track="T1_intent", metrics={"accuracy": 0.9}, samples=10)}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            harness.save_baseline(results, path)
            loaded = harness.load_baseline(path)
            assert loaded["tracks"]["T1_intent"]["metrics"]["accuracy"] == 0.9
        finally:
            os.unlink(path)


def pytest_runner(harness, track_filter=None):
    import asyncio
    return asyncio.run(harness.run(track_filter))


def pytest_runner_track(track, ctx):
    import asyncio
    return asyncio.run(track.run(ctx))
