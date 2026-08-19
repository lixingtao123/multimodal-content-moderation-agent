"""
评估运行器 — 端到端自动化评估流水线

功能:
  1. 加载评估数据集
  2. 调用审核 API 获取实际结果
  3. 计算评估指标
  4. 使用 LLM-as-Judge 进行质量评估
  5. 生成评估报告
"""
import time
import json
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EvalRunResult:
    """一次评估运行的结果"""
    run_id: str
    timestamp: str
    total_samples: int
    metrics: dict
    judge_results: Optional[dict] = None
    failures: List[dict] = field(default_factory=list)
    duration_seconds: float = 0.0


class EvalHarness:
    """
    评估 Harness — 自动化评估流水线

    使用方式:
        harness = EvalHarness(moderate_func)
        result = await harness.run_full_eval()
        print(harness.report(result))
    """

    def __init__(self, moderate_func=None, judge=None):
        """
        Args:
            moderate_func: async function(content, content_type) -> ModerationResponse
            judge: ModerationJudge instance (optional)
        """
        self.moderate_func = moderate_func
        self.judge = judge

    def set_moderate_func(self, func):
        """设置审核函数"""
        self.moderate_func = func

    def set_judge(self, judge):
        """设置 LLM Judge"""
        self.judge = judge

    async def run_full_eval(self, dataset_categories: List[str] = None) -> EvalRunResult:
        """
        运行完整评估

        Args:
            dataset_categories: 要评估的数据集类别，None = 全部

        Returns:
            EvalRunResult
        """
        from eval.datasets.test_samples import get_all_samples, get_by_category
        from eval.metrics.calculator import MetricsCalculator, EvalSample

        start_time = time.time()

        # 加载数据集
        if dataset_categories:
            samples = []
            for cat in dataset_categories:
                samples.extend(get_by_category(cat))
        else:
            samples = get_all_samples()

        # 运行审核
        eval_samples: List[EvalSample] = []
        failures = []

        for sample in samples:
            try:
                t0 = time.time()
                result = await self.moderate_func(
                    content=sample.content,
                    content_type=sample.content_type,
                )
                elapsed = (time.time() - t0) * 1000

                eval_samples.append(EvalSample(
                    id=sample.id,
                    expected_decision=sample.expected_decision,
                    actual_decision=result.get("final_decision", "UNKNOWN"),
                    expected_types=sample.expected_violation_types,
                    actual_types=result.get("violation_types", []),
                    processing_time_ms=elapsed,
                    risk_score=result.get("risk_score", 0.0),
                ))
            except Exception as e:
                logger.error(f"Eval failed for {sample.id}: {e}")
                failures.append({"sample_id": sample.id, "error": str(e)})

        # 计算指标
        calculator = MetricsCalculator()
        metrics = calculator.compute(eval_samples)

        # LLM-as-Judge 评估
        judge_results = None
        if self.judge:
            # 将失败案例送给 Judge
            incorrect_samples = [
                s for s in eval_samples
                if s.expected_decision != s.actual_decision
            ]
            judge_samples = []
            for s in incorrect_samples[:20]:  # 最多送 20 个失败案例
                orig = next(
                    (o for o in samples if o.id == s.id), None
                )
                if orig:
                    judge_samples.append({
                        "content": orig.content,
                        "decision": s.actual_decision,
                        "violation_types": s.actual_types,
                        "confidence": s.risk_score,
                        "risk_score": s.risk_score,
                        "reason": "",
                        "expected_decision": s.expected_decision,
                        "expected_types": s.expected_types,
                    })

            if judge_samples:
                verdicts = await self.judge.batch_judge(judge_samples)
                judge_results = self.judge.aggregate_scores(verdicts)

        # 汇总
        elapsed = time.time() - start_time
        import uuid
        from datetime import datetime

        return EvalRunResult(
            run_id=f"eval_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now().isoformat(),
            total_samples=len(samples),
            metrics={
                "accuracy": metrics.accuracy,
                "precision": metrics.precision,
                "recall": metrics.recall,
                "f1": metrics.f1,
                "precision_per_class": metrics.precision_per_class,
                "recall_per_class": metrics.recall_per_class,
                "f1_per_class": metrics.f1_per_class,
                "confusion_matrix": metrics.confusion_matrix,
                "correct_count": metrics.correct_count,
                "avg_latency_ms": metrics.avg_latency_ms,
                "avg_risk_score": metrics.avg_risk_score,
            },
            judge_results=judge_results,
            failures=failures,
            duration_seconds=round(elapsed, 2),
        )

    def report(self, result: EvalRunResult) -> str:
        """生成可读报告"""
        from eval.metrics.calculator import MetricsCalculator, MetricResult

        # 重建 MetricResult 以便使用 print_report
        metric_result = MetricResult(**result.metrics)
        calc = MetricsCalculator()
        report = calc.print_report(metric_result)

        # 附加 Judge 结果
        if result.judge_results:
            jr = result.judge_results
            report += f"\n\n  LLM-as-Judge 评估:"
            report += f"\n    Judge 准确率: {jr.get('accuracy', 0):.2%}"
            report += f"\n    错误分布: {jr.get('error_distribution', {})}"
            report += f"\n    改进建议: {jr.get('suggestions', [])[:5]}"

        # 失败案例
        if result.failures:
            report += f"\n\n  执行失败: {len(result.failures)} 条"
            for f in result.failures[:3]:
                report += f"\n    - {f['sample_id']}: {f['error']}"

        report += f"\n\n  总耗时: {result.duration_seconds:.1f}s"
        report += f"\n{'='*70}"

        return report


# === 便捷函数 ===

async def moderate_text_for_eval(content: str, content_type: str = "text") -> dict:
    """用于评估的文本审核函数（R20：返回 lane/违规类型/耗时，支持逐案归因）"""
    import time
    from agent_moderation.state import create_initial_state
    from agent_moderation.workflows.moderation import get_workflow

    state = create_initial_state(
        content_id=f"eval_{hash(content) % 100000:05d}",
        content_type=content_type,
        content={"text": content},
    )
    workflow = get_workflow()
    config = {"configurable": {"thread_id": state["content_id"]}}
    t0 = time.time()
    result = await workflow.ainvoke(state, config)
    duration_ms = round((time.time() - t0) * 1000, 1)

    final_risk = result.get("final_risk") or {}
    text_result = result.get("text_result") or {}
    lane = result.get("_tier", "med")
    # R22: 透出快车道/升级/辩论/终止双签信号（T6/T7 真实评测依赖）
    used_fast_lane = bool(text_result.get("fast_lane", False)) or bool(text_result.get("small_model", False))
    # 快车道车道但小模型未采纳 → 升级完整审核
    upgraded = (lane == "low") and not used_fast_lane
    return {
        "final_decision": result.get("final_decision", "UNKNOWN"),
        "violation_types": final_risk.get("violation_types", []),
        "risk_score": final_risk.get("overall_score", 0.0),
        "lane": lane,
        "violation_type": text_result.get("violation_type", "none"),
        "confidence": text_result.get("confidence", 0.0),
        "duration_ms": duration_ms,
        "used_fast_lane": used_fast_lane,
        "upgraded": upgraded,
        "debate_info": result.get("_debate_result") or {},
        "termination": result.get("_termination") or {},
        "triage": result.get("_triage") or {},
    }


async def quick_eval() -> EvalRunResult:
    """快速评估 — 一键运行"""
    harness = EvalHarness(moderate_text_for_eval)
    result = await harness.run_full_eval()
    logger.info(harness.report(result))
    return result
