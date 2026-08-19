"""
评估指标计算 — Precision / Recall / F1 / Confusion Matrix

指标:
  - Accuracy: (TP + TN) / Total
  - Precision: TP / (TP + FP)
  - Recall: TP / (TP + FN)
  - F1: 2 * P * R / (P + R)
  - Macro/Micro averaging
  - Per-class metrics
"""
import logging
from typing import List, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MetricResult:
    """评估指标结果"""
    accuracy: float
    precision: float
    recall: float
    f1: float
    precision_per_class: Dict[str, float] = field(default_factory=dict)
    recall_per_class: Dict[str, float] = field(default_factory=dict)
    f1_per_class: Dict[str, float] = field(default_factory=dict)
    confusion_matrix: Dict[str, Dict[str, int]] = field(default_factory=dict)
    total_samples: int = 0
    correct_count: int = 0
    avg_latency_ms: float = 0.0
    avg_risk_score: float = 0.0


@dataclass
class EvalSample:
    """评估样本"""
    id: str
    expected_decision: str
    actual_decision: str
    expected_types: List[str] = field(default_factory=list)
    actual_types: List[str] = field(default_factory=list)
    processing_time_ms: float = 0.0
    risk_score: float = 0.0


class MetricsCalculator:
    """评估指标计算器"""

    DECISION_CLASSES = ["PASS", "REVIEW", "REJECT", "UNKNOWN"]

    def compute(self, samples: List[EvalSample]) -> MetricResult:
        """
        计算完整评估指标

        Args:
            samples: 评估样本列表

        Returns:
            MetricResult
        """
        if not samples:
            return MetricResult(
                accuracy=0, precision=0, recall=0, f1=0,
            )

        # 正确计数
        correct = sum(1 for s in samples if s.expected_decision == s.actual_decision)
        accuracy = correct / len(samples)

        # Per-class metrics
        precision_per_class = {}
        recall_per_class = {}
        f1_per_class = {}

        confusion = self._build_confusion_matrix(samples)

        for cls in self.DECISION_CLASSES:
            tp = confusion.get(cls, {}).get(cls, 0)
            fp = sum(confusion.get(c, {}).get(cls, 0) for c in self.DECISION_CLASSES if c != cls)
            fn = sum(confusion.get(cls, {}).get(c, 0) for c in self.DECISION_CLASSES if c != cls)

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

            precision_per_class[cls] = round(precision, 4)
            recall_per_class[cls] = round(recall, 4)
            f1_per_class[cls] = round(f1, 4)

        # Macro average
        macro_precision = sum(precision_per_class.values()) / len(self.DECISION_CLASSES)
        macro_recall = sum(recall_per_class.values()) / len(self.DECISION_CLASSES)
        macro_f1 = 2 * macro_precision * macro_recall / (macro_precision + macro_recall) if (macro_precision + macro_recall) > 0 else 0.0

        # 平均延迟和风险分
        avg_latency = sum(s.processing_time_ms for s in samples) / len(samples)
        avg_risk = sum(s.risk_score for s in samples) / len(samples)

        return MetricResult(
            accuracy=round(accuracy, 4),
            precision=round(macro_precision, 4),
            recall=round(macro_recall, 4),
            f1=round(macro_f1, 4),
            precision_per_class=precision_per_class,
            recall_per_class=recall_per_class,
            f1_per_class=f1_per_class,
            confusion_matrix=confusion,
            total_samples=len(samples),
            correct_count=correct,
            avg_latency_ms=round(avg_latency, 2),
            avg_risk_score=round(avg_risk, 4),
        )

    def _build_confusion_matrix(self, samples: List[EvalSample]) -> Dict[str, Dict[str, int]]:
        """构建混淆矩阵"""
        matrix = {c: {d: 0 for d in self.DECISION_CLASSES} for c in self.DECISION_CLASSES}
        for s in samples:
            exp = s.expected_decision if s.expected_decision in self.DECISION_CLASSES else "UNKNOWN"
            act = s.actual_decision if s.actual_decision in self.DECISION_CLASSES else "UNKNOWN"
            matrix[exp][act] += 1
        return matrix

    def print_report(self, result: MetricResult) -> str:
        """生成可读的评估报告"""
        lines = []
        lines.append("=" * 70)
        lines.append("  内容审核系统评估报告")
        lines.append("=" * 70)
        lines.append(f"  总样本数: {result.total_samples}")
        lines.append(f"  正确数:   {result.correct_count}")
        lines.append(f"  准确率:   {result.accuracy:.2%}")
        lines.append(f"  Macro-P:  {result.precision:.4f}")
        lines.append(f"  Macro-R:  {result.recall:.4f}")
        lines.append(f"  Macro-F1: {result.f1:.4f}")
        lines.append(f"  平均延迟: {result.avg_latency_ms:.0f}ms")
        lines.append("")
        lines.append("  Per-Class Metrics:")
        lines.append(f"  {'Class':<12} {'Precision':<12} {'Recall':<12} {'F1':<12}")
        lines.append("  " + "-" * 48)
        for cls in self.DECISION_CLASSES:
            lines.append(
                f"  {cls:<12} {result.precision_per_class.get(cls, 0):<12.4f} "
                f"{result.recall_per_class.get(cls, 0):<12.4f} "
                f"{result.f1_per_class.get(cls, 0):<12.4f}"
            )
        lines.append("")
        lines.append("  混淆矩阵 (行=期望, 列=实际):")
        lines.append(f"  {'':<12} " + " ".join(f"{c:<8}" for c in self.DECISION_CLASSES))
        for cls_exp in self.DECISION_CLASSES:
            row = " ".join(
                f"{result.confusion_matrix.get(cls_exp, {}).get(cls_act, 0):<8}"
                for cls_act in self.DECISION_CLASSES
            )
            lines.append(f"  {cls_exp:<12} {row}")
        lines.append("=" * 70)
        return "\n".join(lines)
