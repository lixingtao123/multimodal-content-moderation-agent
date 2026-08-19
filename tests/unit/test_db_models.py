"""
单元测试 — 数据库模型定义（R3·L3，F4 修复）
不连库，用 SQLAlchemy metadata 反射检查表结构与列（ORM 契约断言）。
"""
from db.models import Base


class TestAnnotationRecordModel:
    def test_table_exists(self):
        assert "annotation_records" in Base.metadata.tables

    def test_core_columns_present(self):
        """现有 4 处硬编码 SQL 引用的核心列全部存在"""
        cols = set(Base.metadata.tables["annotation_records"].columns.keys())
        required = {
            # hard_case_miner（moderation.py:283）
            "content_id", "ai_violation_type", "ai_decision", "ai_confidence",
            "annotation_status", "priority", "meta_info",
            # 人工标注（admin.py / moderation.py）
            "content_type", "model_decision", "model_confidence",
            "model_violation_types", "model_risk_score", "is_error",
            "error_type", "error_detail", "annotated_violation_types",
            "annotated_confidence", "source", "weight", "reviewer_id",
            "human_corrected_json", "model_reason",
            # 优化 agent（annotation_queue.py）
            "annotation_input", "rule_verdict", "rule_detail", "llm_verdict",
            "llm_reason", "llm_called", "contradiction_flag",
            "rule_matched_keywords", "rule_matched_rules",
            "rule_whitelist_hit", "rule_adversarial_hit",
            "processing_time_ms", "annotated_at",
        }
        missing = required - cols
        assert not missing, f"annotation_records 缺列: {missing}"

    def test_content_id_unique_index(self):
        table = Base.metadata.tables["annotation_records"]
        cols = table.columns
        assert cols["content_id"].unique

    def test_source_default(self):
        table = Base.metadata.tables["annotation_records"]
        assert table.columns["source"].default is not None

    def test_is_error_indexed(self):
        table = Base.metadata.tables["annotation_records"]
        idx_cols = {c.name for idx in table.indexes for c in idx.columns}
        assert "is_error" in idx_cols


class TestDatasetSampleModel:
    def test_table_exists(self):
        assert "dataset_samples" in Base.metadata.tables

    def test_core_columns(self):
        cols = set(Base.metadata.tables["dataset_samples"].columns.keys())
        required = {"sample_id", "category", "violation_type", "modality",
                    "language", "content_preview", "path",
                    "ground_truth", "source_dataset"}
        missing = required - cols
        assert not missing, f"dataset_samples 缺列: {missing}"

    def test_sample_id_unique(self):
        cols = Base.metadata.tables["dataset_samples"].columns
        assert cols["sample_id"].unique
