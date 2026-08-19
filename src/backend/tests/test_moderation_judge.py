"""
测试: ModerationJudge 评测指标计算
验证 Precision/Recall/F1/Confusion Matrix
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.moderation_judge import ModerationJudge, EvalReport


class TestModerationJudge:
    """测试评测指标计算"""

    @classmethod
    def setup_class(cls):
        cls.judge = ModerationJudge()

    def test_single_correct_judgment(self):
        """单条正确判定"""
        result = self.judge.judge(
            content_id="test_1",
            prediction={"violation_type": "advertisement", "decision": "REJECT", "confidence": 0.9},
            ground_truth={"violation_type": "advertisement", "decision": "REJECT"},
        )
        assert result.is_correct
        assert result.error_type == "correct"

    def test_single_false_positive(self):
        """正常内容误判为违规 (假阳性)"""
        result = self.judge.judge(
            content_id="test_2",
            prediction={"violation_type": "advertisement", "decision": "REVIEW", "confidence": 0.6},
            ground_truth={"violation_type": "none", "decision": "PASS"},
        )
        assert not result.is_correct
        assert result.error_type == "fp"

    def test_single_false_negative(self):
        """违规内容漏判为正常 (假阴性)"""
        result = self.judge.judge(
            content_id="test_3",
            prediction={"violation_type": "none", "decision": "PASS", "confidence": 0.1},
            ground_truth={"violation_type": "violence", "decision": "REJECT"},
        )
        assert not result.is_correct
        assert result.error_type == "fn"

    def test_single_wrong_type(self):
        """违规类型判断错误"""
        result = self.judge.judge(
            content_id="test_4",
            prediction={"violation_type": "advertisement", "decision": "REJECT", "confidence": 0.85},
            ground_truth={"violation_type": "false_info", "decision": "REJECT"},
        )
        assert not result.is_correct
        assert result.error_type == "wrong_type"

    def test_batch_evaluation_perfect(self):
        """完美预测的批量评估"""
        predictions = [
            {"content_id": "p1", "violation_type": "advertisement", "decision": "REJECT", "confidence": 0.9},
            {"content_id": "p2", "violation_type": "none", "decision": "PASS", "confidence": 0.05},
            {"content_id": "p3", "violation_type": "violence", "decision": "REJECT", "confidence": 0.95},
        ]
        ground_truths = [
            {"content_id": "p1", "violation_type": "advertisement", "decision": "REJECT"},
            {"content_id": "p2", "violation_type": "none", "decision": "PASS"},
            {"content_id": "p3", "violation_type": "violence", "decision": "REJECT"},
        ]
        report = self.judge.evaluate_all(predictions, ground_truths)

        assert report.accuracy == 1.0
        assert report.correct == 3
        assert len(report.false_positives) == 0
        assert len(report.false_negatives) == 0

    def test_batch_evaluation_with_errors(self):
        """含错误的批量评估"""
        predictions = [
            {"content_id": "e1", "violation_type": "advertisement", "decision": "REJECT", "confidence": 0.85},
            {"content_id": "e2", "violation_type": "none", "decision": "PASS", "confidence": 0.1},
            {"content_id": "e3", "violation_type": "porn", "decision": "REVIEW", "confidence": 0.5},
        ]
        ground_truths = [
            {"content_id": "e1", "violation_type": "advertisement", "decision": "REJECT"},  # correct
            {"content_id": "e2", "violation_type": "harassment", "decision": "REVIEW"},    # fn
            {"content_id": "e3", "violation_type": "porn", "decision": "REVIEW"},           # correct
        ]
        report = self.judge.evaluate_all(predictions, ground_truths)

        assert report.accuracy == pytest.approx(2/3, abs=0.001)
        assert len(report.false_negatives) == 1

    def test_confusion_matrix(self):
        """混淆矩阵生成"""
        predictions = [
            {"content_id": "c1", "violation_type": "advertisement", "decision": "REJECT", "confidence": 0.9},
            {"content_id": "c2", "violation_type": "advertisement", "decision": "REJECT", "confidence": 0.8},
            {"content_id": "c3", "violation_type": "none", "decision": "PASS", "confidence": 0.1},
        ]
        ground_truths = [
            {"content_id": "c1", "violation_type": "advertisement", "decision": "REJECT"},
            {"content_id": "c2", "violation_type": "violence", "decision": "REJECT"},  # wrong type
            {"content_id": "c3", "violation_type": "none", "decision": "PASS"},
        ]
        report = self.judge.evaluate_all(predictions, ground_truths)

        assert report.confusion_matrix is not None
        assert len(report.confusion_matrix) > 0

    def test_empty_evaluation(self):
        """空评测返回空报告"""
        report = self.judge.evaluate_all([], [])
        assert report.total_samples == 0
        assert report.accuracy == 0.0

    def test_judge_load_ground_truth(self):
        """加载标注数据集"""
        samples = [
            {"content_id": "gt1", "violation_type": "advertisement", "decision": "REJECT"},
            {"content_id": "gt2", "violation_type": "none", "decision": "PASS"},
        ]
        self.judge.load_ground_truth(samples)
        assert len(self.judge._ground_truth) == 2

    def test_get_summary_no_data(self):
        """无评测数据时的摘要"""
        empty_judge = ModerationJudge()
        summary = empty_judge.get_summary()
        assert summary["status"] == "no_data"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
