"""
单元测试 — R16（M1 级联 + R1/R3 训练数据准备）
"""
import json
import os
import tempfile

import pytest

from agent_moderation.workers.model_cascade import CascadeRouter
from training.prepare_sft_data import (
    export_jsonl,
    from_out_safe,
    sample_with_negatives,
    to_sft_samples,
)


async def _small_high(text):
    return {"decision": "PASS", "confidence": 0.9}


async def _small_low(text):
    return {"decision": "UNKNOWN", "confidence": 0.3}


async def _small_needs_upgrade(text):
    return {"decision": "UNKNOWN", "confidence": 0.8, "needs_upgrade": True}


async def _large(text):
    return {"decision": "REJECT", "confidence": 0.85}


class TestCascadeRouter:
    @pytest.mark.asyncio
    async def test_small_confident_no_upgrade(self):
        r = CascadeRouter(small_client=_small_high, large_client=_large)
        result = await r.route("正常内容")
        assert result["upgraded"] is False
        assert result["used_small"] is True
        assert result["decision"] == "PASS"

    @pytest.mark.asyncio
    async def test_low_confidence_upgrades(self):
        r = CascadeRouter(small_client=_small_low, large_client=_large)
        result = await r.route("模糊内容")
        assert result["upgraded"] is True
        assert result["decision"] == "REJECT"
        assert result["small_confidence"] == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_needs_upgrade_flag(self):
        """显式 needs_upgrade 也升级（即使置信度高）"""
        r = CascadeRouter(small_client=_small_needs_upgrade, large_client=_large)
        result = await r.route("高危")
        assert result["upgraded"] is True

    @pytest.mark.asyncio
    async def test_small_exception_upgrades(self):
        async def bad_small(text):
            raise RuntimeError("down")

        r = CascadeRouter(small_client=bad_small, large_client=_large)
        result = await r.route("x")
        assert result["upgraded"] is True
        assert result["reason"]  # 有升级原因

    @pytest.mark.asyncio
    async def test_no_small_large_only(self):
        r = CascadeRouter(small_client=None, large_client=_large)
        result = await r.route("x")
        assert result["upgraded"] is True

    @pytest.mark.asyncio
    async def test_no_models_error(self):
        r = CascadeRouter(small_client=None, large_client=None)
        result = await r.route("x")
        assert result["error"]

    def test_stats_tracking(self):
        r = CascadeRouter(small_client=_small_high, large_client=_large)
        import asyncio
        asyncio.run(r.route("a"))
        assert r.stats()["small"] == 1


class TestSFTData:
    def test_to_sft_samples_standardize(self):
        samples = to_sft_samples([
            {"instruction": "i", "input": "in", "output": "out"},
            {"prompt": "p", "response": "r"},
        ])
        assert samples[0] == {"instruction": "i", "input": "in", "output": "out"}
        assert samples[1]["input"] == "p" and samples[1]["output"] == "r"

    def test_from_out_safe(self):
        from eval.datasets.out_safe_loader import OutSafeDatasetLoader
        samples = from_out_safe(OutSafeDatasetLoader(), per_cat=2)
        assert len(samples) == 18  # 9 类 × 2
        out = json.loads(samples[0]["output"])
        assert "violation_type" in out and "is_harmful" in out

    def test_export_jsonl(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            n = export_jsonl([{"instruction": "i", "input": "in", "output": "out"}], path)
            assert n == 1
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    def test_sample_with_negatives(self):
        pos = [{"instruction": "i", "input": f"x{n}", "output": "{}"} for n in range(10)]
        negs = [f"安全内容{n}" for n in range(100)]
        combined = sample_with_negatives(pos, negs, negative_ratio=0.5)
        assert len(combined) == 15  # 10 正 + 5 负
        neg_outputs = [json.loads(s["output"])["is_harmful"] for s in combined
                       if s["input"].startswith("安全内容")]
        assert all(o is False for o in neg_outputs)
