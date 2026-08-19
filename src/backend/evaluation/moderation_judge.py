"""
Moderation Judge v1.0 — LLM-as-Judge 自动效果评估

对标 Google/Meta 的 LLM-as-Judge 方法论:
  - Precision/Recall/F1 量化追踪
  - False Positive/Negative 分析
  - Wrong Type 分类错误分析
  - 评估报告自动生成
  - 评估结果自动反馈到 DSPy 优化器

技术参考:
  - MT-Bench (Zheng et al., 2024): Multi-turn LLM-as-Judge
  - JUDGE-BENCH (2024): LLM评估可靠性基准
  - G-Eval (Liu et al., 2023): Chain-of-Thought LLM评估
"""
import json
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class JudgmentResult:
    """单条评估结果"""
    content_id: str
    predicted_type: str      # AI 判定的违规类型
    ground_truth_type: str    # 标注的真实类型
    predicted_decision: str   # AI 决策 (PASS/REVIEW/REJECT)
    ground_truth_decision: str  # 标注的真实决策
    is_correct: bool          # 是否正确
    error_type: str           # fp (假阳性) / fn (假阴性) / wrong_type (类型错) / correct
    confidence: float
    analysis: str = ""


@dataclass
class EvalReport:
    """评估报告"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    total_samples: int = 0
    correct: int = 0
    accuracy: float = 0.0
    # 分类指标
    precision: Dict[str, float] = field(default_factory=dict)  # 按违规类型
    recall: Dict[str, float] = field(default_factory=dict)
    f1: Dict[str, float] = field(default_factory=dict)
    # 错误分析
    false_positives: List[JudgmentResult] = field(default_factory=list)  # 正常→误判违规
    false_negatives: List[JudgmentResult] = field(default_factory=list)  # 违规→漏判正常
    wrong_types: List[JudgmentResult] = field(default_factory=list)      # 类型A→误判类型B
    # 汇总
    macro_f1: float = 0.0
    micro_f1: float = 0.0
    confusion_matrix: Dict[str, Dict[str, int]] = field(default_factory=dict)


class ModerationJudge:
    """
    LLM-as-Judge 审核效果评估器

    评估维度:
    1. Precision (精确率): 判定为违规的内容中，真正违规的比例
    2. Recall (召回率): 真正违规的内容中，被判定为违规的比例
    3. F1: Precision 和 Recall 的调和平均
    4. False Positive Rate: 正常内容被误判为违规的比例
    5. False Negative Rate: 违规内容被漏判为正常的比例
    6. Wrong Type Rate: 正确识别违规但类型错误的比例
    """

    # 所有违规类型
    ALL_VIOLATION_TYPES = [
        "politics", "porn", "violence", "false_info",
        "harassment", "advertisement", "illegal", "crime", "phishing",
        "terrorism", "bulk_generation", "none"
    ]

    def __init__(self):
        self.results: List[JudgmentResult] = []
        self._llm_client = None
        self._ground_truth: List[Dict] = []

    def set_llm_client(self, client):
        """设置 LLM 客户端用于高级评估分析"""
        self._llm_client = client

    def load_ground_truth(self, samples: List[Dict]):
        """
        加载标注数据集

        每条样本格式:
        {
            "content_id": "...",
            "content": "...",
            "violation_type": "advertisement",  # 真实类型
            "decision": "REVIEW",                # 真实决策
            "confidence": 0.9
        }
        """
        self._ground_truth = samples
        logger.info(f"Loaded {len(samples)} ground truth samples")

    def judge(self, content_id: str, prediction: Dict, ground_truth: Dict) -> JudgmentResult:
        """
        单条结果评估

        Args:
            content_id: 内容ID
            prediction: AI预测 {"violation_type": ..., "decision": ..., "confidence": ...}
            ground_truth: 标注真值 {"violation_type": ..., "decision": ...}

        Returns:
            JudgmentResult
        """
        pred_type = prediction.get("violation_type", "none")
        gt_type = ground_truth.get("violation_type", "none")
        pred_decision = prediction.get("decision", "PASS")
        gt_decision = ground_truth.get("decision", "PASS")

        # 判断正确性
        is_correct = (pred_type == gt_type and pred_decision == gt_decision)

        # 分析错误类型
        if is_correct:
            error_type = "correct"
            analysis = "判定正确"
        elif gt_type == "none" and pred_type != "none":
            error_type = "fp"  # False Positive: 正常内容误判为违规
            analysis = f"假阳性: 正常内容被误判为 {pred_type}"
        elif gt_type != "none" and pred_type == "none":
            error_type = "fn"  # False Negative: 违规内容漏判为正常
            analysis = f"假阴性: {gt_type} 被漏判为正常"
        else:
            error_type = "wrong_type"  # 违规类型判断错误
            analysis = f"类型错误: 真实={gt_type}, 预测={pred_type}"

        result = JudgmentResult(
            content_id=content_id,
            predicted_type=pred_type,
            ground_truth_type=gt_type,
            predicted_decision=pred_decision,
            ground_truth_decision=gt_decision,
            is_correct=is_correct,
            error_type=error_type,
            confidence=prediction.get("confidence", 0.0),
            analysis=analysis,
        )
        self.results.append(result)
        return result

    def evaluate_all(
        self, predictions: List[Dict], ground_truths: List[Dict]
    ) -> EvalReport:
        """
        批量评估，生成完整报告
        """
        self.results = []
        for pred, gt in zip(predictions, ground_truths):
            self.judge(pred.get("content_id", "unknown"), pred, gt)

        return self.generate_report()

    def generate_report(self) -> EvalReport:
        """生成评估报告"""
        if not self.results:
            return EvalReport()

        report = EvalReport()
        report.total_samples = len(self.results)
        report.correct = sum(1 for r in self.results if r.is_correct)
        report.accuracy = round(report.correct / report.total_samples, 4) if report.total_samples > 0 else 0.0

        # 分类错误
        report.false_positives = [r for r in self.results if r.error_type == "fp"]
        report.false_negatives = [r for r in self.results if r.error_type == "fn"]
        report.wrong_types = [r for r in self.results if r.error_type == "wrong_type"]

        # 按违规类型计算 Precision/Recall/F1
        for vt in self.ALL_VIOLATION_TYPES:
            tp = sum(1 for r in self.results
                     if r.predicted_type == vt and r.ground_truth_type == vt)
            fp = sum(1 for r in self.results
                     if r.predicted_type == vt and r.ground_truth_type != vt)
            fn = sum(1 for r in self.results
                     if r.predicted_type != vt and r.ground_truth_type == vt)

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

            report.precision[vt] = round(precision, 4)
            report.recall[vt] = round(recall, 4)
            report.f1[vt] = round(f1, 4)

        # 宏平均和微平均
        non_none_types = [t for t in self.ALL_VIOLATION_TYPES if t != "none"]
        report.macro_f1 = round(
            sum(report.f1.get(t, 0.0) for t in non_none_types) / len(non_none_types), 4
        )

        # 微平均 (按样本数加权)
        total_tp = sum(1 for r in self.results if r.is_correct and r.ground_truth_type != "none")
        total_samples_non_none = sum(1 for r in self.results if r.ground_truth_type != "none")
        report.micro_f1 = round(total_tp / total_samples_non_none, 4) if total_samples_non_none > 0 else 0.0

        # 混淆矩阵
        cm: Dict[str, Dict[str, int]] = {}
        for r in self.results:
            gt = r.ground_truth_type
            pred = r.predicted_type
            if gt not in cm:
                cm[gt] = {}
            cm[gt][pred] = cm[gt].get(pred, 0) + 1
        report.confusion_matrix = cm

        logger.info(
            f"Eval: accuracy={report.accuracy:.2%}, "
            f"macro_f1={report.macro_f1:.2%}, "
            f"FP={len(report.false_positives)}, "
            f"FN={len(report.false_negatives)}, "
            f"WrongType={len(report.wrong_types)}"
        )

        return report

    async def llm_judge_disagreement(
        self, content_id: str, content: str, ai_prediction: Dict, human_label: Dict
    ) -> Dict:
        """
        使用 LLM 分析 AI 和人工标注的分歧

        仅在结果不一致时调用，用于深度分析根因
        """
        if not self._llm_client:
            return {"analysis": "LLM client not available"}

        prompt = f"""你是内容审核质量分析师。请分析以下AI审核结果与人工标注之间的分歧原因。

内容: {content[:500]}

AI判定:
- 违规类型: {ai_prediction.get('violation_type', 'unknown')}
- 决策: {ai_prediction.get('decision', 'unknown')}
- 置信度: {ai_prediction.get('confidence', 0):.2f}

人工标注:
- 违规类型: {human_label.get('violation_type', 'unknown')}
- 决策: {human_label.get('decision', 'unknown')}

请分析:
1. 分歧的根本原因是什么? (AI过于严格/AI不够敏感/标注模糊/边界case)
2. AI的 Prompt 或逻辑需要如何改进?

只返回JSON: {{"root_cause": "...", "severity": "minor|moderate|major", "improvement": "..."}}"""

        try:
            from common.api_clients import get_deepseek_model
            response = await self._llm_client.chat.completions.create(
                model=get_deepseek_model(),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=300,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.warning(f"LLM judge analysis failed: {e}")
            return {"root_cause": f"Analysis error: {e}", "severity": "unknown", "improvement": ""}

    def auto_feedback_to_dspy(self, report: EvalReport, min_errors: int = 10):
        """
        自动将评估结果反馈到 DSPy 优化器

        触发条件: 错误总数 >= min_errors
        """
        total_errors = len(report.false_positives) + len(report.false_negatives) + len(report.wrong_types)
        if total_errors < min_errors:
            logger.info(f"Errors ({total_errors}) below threshold ({min_errors}), skipping DSPy feedback")
            return None

        # 构建反馈数据
        feedback = {
            "report": {
                "accuracy": report.accuracy,
                "macro_f1": report.macro_f1,
                "total_errors": total_errors,
            },
            "failure_cases": [],
        }

        # 收集失败案例
        for r in report.false_positives[:10]:
            feedback["failure_cases"].append({
                "content_id": r.content_id,
                "error_type": "false_positive",
                "predicted": r.predicted_type,
                "ground_truth": r.ground_truth_type,
            })
        for r in report.false_negatives[:10]:
            feedback["failure_cases"].append({
                "content_id": r.content_id,
                "error_type": "false_negative",
                "predicted": r.predicted_type,
                "ground_truth": r.ground_truth_type,
            })
        for r in report.wrong_types[:10]:
            feedback["failure_cases"].append({
                "content_id": r.content_id,
                "error_type": "wrong_type",
                "predicted": r.predicted_type,
                "ground_truth": r.ground_truth_type,
            })

        # 触发 DSPy 优化
        try:
            from optimization.prompt_optimizer import get_feedback_loop
            loop = get_feedback_loop()
            for case in feedback["failure_cases"]:
                loop.collect_feedback(case)
            result = loop.maybe_optimize()
            logger.info(f"DSPy auto-optimization triggered: {result}")
            return result
        except Exception as e:
            logger.warning(f"DSPy feedback failed: {e}")
            return None

    def get_summary(self) -> Dict:
        """获取简单的评估摘要"""
        if not self.results:
            return {"status": "no_data"}
        correct = sum(1 for r in self.results if r.is_correct)
        return {
            "total": len(self.results),
            "correct": correct,
            "accuracy": round(correct / len(self.results), 4),
            "fp": len([r for r in self.results if r.error_type == "fp"]),
            "fn": len([r for r in self.results if r.error_type == "fn"]),
            "wrong_type": len([r for r in self.results if r.error_type == "wrong_type"]),
        }


# 全局单例
_judge: Optional[ModerationJudge] = None


def get_judge() -> ModerationJudge:
    global _judge
    if _judge is None:
        _judge = ModerationJudge()
    return _judge
