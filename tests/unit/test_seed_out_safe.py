"""
单元测试 — seed_out_safe 增量灌入（R4·G1）
重点断言：真实数据 metadata 标记正确 + 默认保留模拟（绝不清空）。
"""
from eval.datasets.seed_out_safe import build_metadata, collect_text_samples, import_to_chromadb


class TestBuildMetadata:
    def test_metadata_marks_out_safe(self):
        """metadata 必须标记 out_safe / confirmed / no_decay"""
        md = build_metadata("porn")
        assert md["source_dataset"] == "out_safe"
        assert md["ground_truth"] == "confirmed"
        assert md["no_decay"] is True

    def test_metadata_violation_type(self):
        md = build_metadata("privacy")
        assert md["violation_type"] == "privacy"

    def test_metadata_language(self):
        md = build_metadata("crime", language="en")
        assert md["language"] == "en"


class TestCollectTextSamples:
    def test_collect_with_limit(self):
        """limit 生效且结构正确"""
        samples = collect_text_samples(None, limit_per_lang=20)
        assert len(samples) > 0
        s = samples[0]
        assert s["id"] and s["content"] and s["metadata"]
        assert s["metadata"]["source_dataset"] == "out_safe"

    def test_sample_ids_unique(self):
        samples = collect_text_samples(None, limit_per_lang=10)
        ids = [s["id"] for s in samples]
        assert len(set(ids)) == len(ids)

    def test_no_out_safe_prefix_collision(self):
        """真实案例 id 带类别前缀，不与 seed 前缀冲突"""
        samples = collect_text_samples(None, limit_per_lang=5)
        assert all(not s["id"].startswith("seed_") for s in samples)


class TestImportSafety:
    def test_clear_first_defaults_false(self):
        """默认绝不清空模拟数据（用户硬约束）"""
        import inspect
        sig = inspect.signature(import_to_chromadb)
        assert sig.parameters["clear_first"].default is False
