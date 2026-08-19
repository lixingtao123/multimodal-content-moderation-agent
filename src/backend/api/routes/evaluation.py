"""
Evaluation API Routes v1.0 — LLM-as-Judge 评估端点

提供:
  - POST /api/v1/eval/judge — 单条结果评估
  - POST /api/v1/eval/batch — 批量评估 + 报告
  - GET /api/v1/eval/report — 获取最新评估报告
  - POST /api/v1/eval/red-team — 红队对抗测试
  - GET /api/v1/eval/a2a/agents — A2A Agent 列表
  - GET /api/v1/eval/a2a/tasks — A2A 任务列表
  - GET /api/v1/eval/benchmark — R17: Benchmark 报告（baseline + latest）
"""
import json
import os
import sys
import time
import functools
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional

router = APIRouter(prefix="/api/v1/eval", tags=["evaluation"])

# eval/baselines/ 位于项目根（/workspace/eval/baselines）
# evaluation.py 位于 src/backend/api/routes/，需 5 层 dirname 回到项目根
_BASELINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
    "eval", "baselines")

# eval/ 包与 src/backend 同级（项目根）。注意：绝不能把 _EVAL_ROOT 加入 sys.path ——
# 那会让 /workspace/eval/datasets shadow 掉 HuggingFace 的 `datasets` 库，
# 导致 sentence_transformers 等依赖 `from datasets import Dataset` 全部失败。
# 改用 importlib 按文件路径加载 OutSafeDatasetLoader。
_EVAL_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
    "eval")


def _load_out_safe_loader():
    """按文件路径加载 OutSafeDatasetLoader，不污染 sys.path。"""
    import importlib.util
    loader_path = os.path.join(_EVAL_ROOT, "datasets", "out_safe_loader.py")
    spec = importlib.util.spec_from_file_location("out_safe_loader", loader_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.OutSafeDatasetLoader


@router.get("/benchmark")
async def get_benchmark_report():
    """R17: 返回 harness_v2 基线 + 最近报告（Benchmark 前端页数据源）。

    文件不存在时返回空结构（诚实标注：未运行评测）。
    """
    result = {"baseline": None, "latest": None, "tracks": []}
    for key in ("baseline", "latest"):
        path = os.path.join(_BASELINE_DIR, f"{key}.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    result[key] = json.load(f)
            except Exception as e:
                result[key] = {"error": str(e)}
    # 汇总 track 清单（含状态）
    src = result.get("baseline") or result.get("latest")
    if src and src.get("tracks"):
        result["tracks"] = [
            {"name": name, "status": t.get("status"), "note": t.get("note", "")}
            for name, t in src["tracks"].items()
        ]
    return result


@functools.lru_cache(maxsize=1)
def _load_out_safe_stats() -> dict:
    """懒加载 OutSafe 数据集统计（进程级缓存，避免每次读盘）。"""
    OutSafeDatasetLoader = _load_out_safe_loader()
    loader = OutSafeDatasetLoader()
    per_cat = []
    for cat in loader.categories():
        row = {"category": cat}
        row["text_zh"] = sum(1 for s in loader.load_text("zh") if s.category == cat)
        row["text_en"] = sum(1 for s in loader.load_text("en") if s.category == cat)
        row["image"] = sum(1 for s in loader.load_images() if s.category == cat)
        row["video"] = sum(1 for s in loader.load_video() if s.category == cat)
        row["audio"] = sum(1 for s in loader.load_audio() if s.category == cat)
        per_cat.append(row)
    return {"stats": loader.stats(), "per_category": per_cat}


async def _sync_dataset_samples() -> dict:
    """R22: 把 OutSafe-Bench 真实样本登记进 dataset_samples 表（幂等 upsert）。

    此前 dataset_samples 只有 schema/ORM 定义却无写入路径（半成品）。
    这里在 dataset/stats 被调用时懒登记一次：读 OutSafe 各模态样本，
    以 sample_id 为唯一键 upsert（PG ON CONFLICT DO NOTHING），DB 失败仅告警不阻断。
    """
    try:
        from db.connection import get_session_factory
        from sqlalchemy import text
        OutSafeDatasetLoader = _load_out_safe_loader()
        loader = OutSafeDatasetLoader()
        if not os.path.isdir(loader.root_dir):
            return {"registered": 0, "skipped": "out_safe_dir_missing"}
        rows = []
        for s in loader.load_text("zh"):
            rows.append((f"{s.id}:zh", s.category, s.violation_type, "text", "zh", s.content, s.path, "confirmed", "out_safe"))
        for s in loader.load_text("en"):
            rows.append((f"{s.id}:en", s.category, s.violation_type, "text", "en", s.content, s.path, "confirmed", "out_safe"))
        for s in loader.load_images():
            rows.append((s.id, s.category, s.violation_type, "image", "", "", s.path, "confirmed", "out_safe"))
        for s in loader.load_video():
            rows.append((s.id, s.category, s.violation_type, "video", "", "", s.path, "confirmed", "out_safe"))
        for s in loader.load_audio():
            rows.append((s.id, s.category, s.violation_type, "audio", "", "", s.path, "confirmed", "out_safe"))

        factory = get_session_factory()
        async with factory() as session:
            # 分块执行，避免单条超长 SQL
            for i in range(0, len(rows), 200):
                chunk = rows[i:i + 200]
                await session.execute(
                    text("""
                        INSERT INTO dataset_samples
                            (id, sample_id, category, violation_type, modality,
                             language, content_preview, path, ground_truth, source_dataset)
                        VALUES (gen_random_uuid(), :sample_id, :category, :violation_type, :modality,
                                :language, :content_preview, :path, :ground_truth, :source_dataset)
                        ON CONFLICT (sample_id) DO NOTHING
                    """),
                    [{"sample_id": r[0], "category": r[1], "violation_type": r[2],
                      "modality": r[3], "language": r[4], "content_preview": r[5],
                      "path": r[6], "ground_truth": r[7], "source_dataset": r[8]}
                     for r in chunk],
                )
            await session.commit()
        return {"registered": len(rows), "skipped": "already_synced"}
    except Exception as e:
        return {"registered": 0, "error": str(e)[:120]}


@router.get("/dataset/stats")
async def get_dataset_stats():
    """R22·C5: OutSafe-Bench 数据集统计（真实读盘，懒加载缓存）。

    数据源：/workspace/data/OutSafe-Bench（9 类风险目录）。
    目录缺失时诚实返回 available=false，不伪造。
    """
    OutSafeDatasetLoader = _load_out_safe_loader()
    root_dir = OutSafeDatasetLoader().root_dir
    if not os.path.isdir(root_dir):
        return {"available": False, "root_dir": root_dir,
                "stats": None, "per_category": [], "error": "OutSafe-Bench 目录不存在"}
    data = _load_out_safe_stats()
    # R22: 懒登记样本入库（幂等；DB 失败不阻断统计返回）
    try:
        await _sync_dataset_samples()
    except Exception:
        pass
    return {"available": True, "root_dir": root_dir, **data}


class JudgeRequest(BaseModel):
    content_id: str
    prediction: Dict   # {"violation_type": ..., "decision": ..., "confidence": ...}
    ground_truth: Dict  # {"violation_type": ..., "decision": ...}


class BatchJudgeRequest(BaseModel):
    predictions: List[Dict]
    ground_truths: List[Dict]


class RedTeamRequest(BaseModel):
    sample_count: int = 20
    run_moderation: bool = True  # 是否实际调用审核系统


# ===== LLM-as-Judge =====

@router.post("/judge")
async def judge_single(req: JudgeRequest):
    """单条结果评估"""
    from evaluation.moderation_judge import get_judge
    judge = get_judge()
    result = judge.judge(req.content_id, req.prediction, req.ground_truth)
    return {
        "content_id": result.content_id,
        "is_correct": result.is_correct,
        "error_type": result.error_type,
        "analysis": result.analysis,
    }


@router.post("/batch")
async def judge_batch(req: BatchJudgeRequest):
    """批量评估"""
    from evaluation.moderation_judge import get_judge
    judge = get_judge()
    report = judge.evaluate_all(req.predictions, req.ground_truths)

    return {
        "accuracy": report.accuracy,
        "macro_f1": report.macro_f1,
        "micro_f1": report.micro_f1,
        "total": report.total_samples,
        "correct": report.correct,
        "false_positives": len(report.false_positives),
        "false_negatives": len(report.false_negatives),
        "wrong_types": len(report.wrong_types),
        "per_class_f1": {
            k: v for k, v in report.f1.items() if v > 0
        },
    }


@router.get("/report")
async def get_report():
    """获取最新评估报告（含完整指标）"""
    from evaluation.moderation_judge import get_judge
    judge = get_judge()

    if not judge.results:
        return {
            "status": "no_data",
            "message": "尚未运行评测。请先 POST /api/v1/eval/run"
        }

    summary = judge.get_summary()

    # 如果有评估结果，生成完整报告
    report = judge.generate_report()
    return {
        "summary": summary,
        "accuracy": report.accuracy,
        "macro_f1": report.macro_f1,
        "micro_f1": report.micro_f1,
        "per_class_f1": {
            k: v for k, v in report.f1.items() if v > 0
        },
        "per_class_precision": {
            k: v for k, v in report.precision.items() if v > 0
        },
        "per_class_recall": {
            k: v for k, v in report.recall.items() if v > 0
        },
        "error_distribution": {
            "false_positives": len(report.false_positives),
            "false_negatives": len(report.false_negatives),
            "wrong_types": len(report.wrong_types),
        },
    }


# ===== 红队测试 =====

@router.post("/red-team")
async def run_red_team(req: RedTeamRequest):
    """运行红队对抗测试"""
    from tests.red_team import get_red_team
    red_team = get_red_team()

    # 生成样本
    samples = red_team.generate_samples(count=req.sample_count)

    if not req.run_moderation:
        return {
            "samples_generated": len(samples),
            "attack_types": list(set(s.attack_type for s in samples)),
            "samples": [
                {
                    "id": s.sample_id,
                    "attack_type": s.attack_type,
                    "original": s.original_text[:80],
                    "adversarial": s.adversarial_text[:80],
                    "expected": s.expected_type,
                    "risk_level": s.risk_level,
                }
                for s in samples[:10]
            ],
        }

    # 实际运行审核
    async def moderate_func(content):
        from agent_moderation.state import create_initial_state
        from agent_moderation.workflows.moderation import get_workflow
        from common.logger import start_pipeline, save_all
        import uuid

        cid = f"redteam_{uuid.uuid4().hex[:8]}"
        # R21: 红队样本独立 pipeline 埋点
        _pl_rt = start_pipeline(cid, "text")
        state = create_initial_state(
            content_id=cid,
            content_type="text",
            content=content,
        )
        workflow = get_workflow()
        result = await workflow.ainvoke(state)
        text_result = result.get("text_result", {})
        _pl_rt.step("🧪 RED_TEAM", "红队对抗样本审核",
                    output_data={"content_id": cid,
                                 "final_decision": result.get("final_decision"),
                                 "violation_type": text_result.get("violation_type"),
                                 "expected": content.get("expected_type", "") if isinstance(content, dict) else ""})
        save_all()
        return {
            "violation_type": text_result.get("violation_type", "none"),
            "decision": result.get("final_decision", "PASS"),
            "confidence": text_result.get("confidence", 0),
        }

    report = await red_team.evaluate(samples, moderate_func)
    bypass_rates = red_team.get_bypass_rate_by_attack(report)

    return {
        "detection_rate": report.detection_rate,
        "total": report.total_samples,
        "detected": report.detected,
        "bypassed": report.bypassed,
        "risk_assessment": report.risk_assessment,
        "bypass_by_attack": bypass_rates,
        "bypass_by_violation": {
            vt: round(1 - stats["detected"] / stats["total"], 4) if stats["total"] > 0 else 0
            for vt, stats in report.by_violation_type.items()
        },
        "bypassed_top5": report.bypassed_samples[:5],
    }


# ===== 全量评测运行 =====

@router.post("/run")
async def run_full_evaluation():
    """
    运行全量评测: 加载标注数据集 → 逐条运行审核 → 生成完整评估报告

    评测数据集: data/eval_dataset.json (由 scripts/build_eval_dataset.py 生成)
    """
    import os
    import json
    import time
    import asyncio

    dataset_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data", "eval_dataset.json"
    )

    if not os.path.exists(dataset_path):
        raise HTTPException(
            status_code=404,
            detail=f"评测数据集不存在: {dataset_path}。请先运行: python3 scripts/build_eval_dataset.py --count 200"
        )

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    from evaluation.moderation_judge import get_judge
    from agent_moderation.state import create_initial_state
    from agent_moderation.workflows.moderation import get_workflow
    import uuid

    judge = get_judge()
    judge.load_ground_truth(dataset)

    predictions = []
    ground_truths = []
    total_start = time.time()

    # 逐条运行审核（每条创建新的 workflow 实例）
    for i, entry in enumerate(dataset):
        try:
            # R21: 评测样本独立 pipeline 埋点（此前直接 ainvoke 无日志）
            from common.logger import start_pipeline, save_all
            _pl_eval = start_pipeline(entry["content_id"], "text")
            state = create_initial_state(
                content_id=entry["content_id"],
                content_type="text",
                content={"text": entry["content"]},
            )
            workflow = get_workflow()
            result = await workflow.ainvoke(state)
            _pl_eval.step("🧪 EVAL_RUN", f"评测样本 {i + 1}/{len(dataset)}",
                          output_data={"content_id": entry["content_id"],
                                       "final_decision": result.get("final_decision"),
                                       "expected": entry.get("expected_decision") or entry.get("decision"),
                                       "violation_type": (result.get("text_result") or {}).get("violation_type")})
            save_all()

            text_result = result.get("text_result", {})
            final_decision = result.get("final_decision", "PASS")

            predictions.append({
                "content_id": entry["content_id"],
                "violation_type": text_result.get("violation_type", "none"),
                "decision": final_decision,
                "confidence": text_result.get("confidence", 0.0),
            })
            ground_truths.append({
                "content_id": entry["content_id"],
                "violation_type": entry["violation_type"],
                "decision": entry["decision"],
            })
        except Exception as e:
            # 单条失败不中断整体评测
            predictions.append({
                "content_id": entry["content_id"],
                "violation_type": "none",
                "decision": "PASS",
                "confidence": 0.0,
            })
            ground_truths.append({
                "content_id": entry["content_id"],
                "violation_type": entry["violation_type"],
                "decision": entry["decision"],
            })

    # 生成完整评估报告
    report = judge.evaluate_all(predictions, ground_truths)
    total_elapsed = round((time.time() - total_start), 1)

    # 构建响应
    return {
        "evaluation": {
            "dataset_size": len(dataset),
            "total_time_seconds": total_elapsed,
            "accuracy": report.accuracy,
            "macro_f1": report.macro_f1,
            "micro_f1": report.micro_f1,
            "correct": report.correct,
            "total": report.total_samples,
            "false_positives_count": len(report.false_positives),
            "false_negatives_count": len(report.false_negatives),
            "wrong_types_count": len(report.wrong_types),
        },
        "per_class": {
            vt: {
                "precision": report.precision.get(vt, 0),
                "recall": report.recall.get(vt, 0),
                "f1": report.f1.get(vt, 0),
            }
            for vt in ["advertisement", "false_info", "porn", "violence", "harassment", "politics", "none"]
            if report.f1.get(vt, 0) > 0 or vt in report.precision or vt in report.recall
        },
        "error_analysis": {
            "false_positives": [
                {
                    "content_id": r.content_id,
                    "predicted": r.predicted_type,
                    "ground_truth": r.ground_truth_type,
                    "analysis": r.analysis,
                }
                for r in report.false_positives[:10]
            ],
            "false_negatives": [
                {
                    "content_id": r.content_id,
                    "predicted": r.predicted_type,
                    "ground_truth": r.ground_truth_type,
                    "analysis": r.analysis,
                }
                for r in report.false_negatives[:10]
            ],
            "wrong_types": [
                {
                    "content_id": r.content_id,
                    "predicted": r.predicted_type,
                    "ground_truth": r.ground_truth_type,
                    "analysis": r.analysis,
                }
                for r in report.wrong_types[:10]
            ],
        },
        "confusion_matrix": report.confusion_matrix,
    }


# ===== A2A Protocol =====

@router.get("/a2a/agents")
async def list_a2a_agents():
    """列出所有 A2A 注册的 Agent"""
    from agent_moderation.a2a_protocol import get_a2a_registry
    registry = get_a2a_registry()
    return {"agents": registry.list_agents(), "stats": registry.get_stats()}


@router.get("/a2a/tasks")
async def list_a2a_tasks():
    """列出 A2A 任务"""
    from agent_moderation.a2a_protocol import get_a2a_registry
    registry = get_a2a_registry()
    tasks = [t.to_dict() for t in registry._tasks.values()]
    return {"tasks": tasks[-50:], "stats": registry.get_stats()}


# ===== 系统能力总览 =====

@router.get("/capabilities")
async def system_capabilities():
    """系统能力总览 (v3.1 优化后 — 每项都真实生效)"""
    from common.config import get_settings
    from mcp_servers.registry import get_tool_registry
    tools = get_tool_registry().list_tools()
    _settings = get_settings()

    return {
        "agents": {
            "text": "DeepSeek V4 Flash — 6维度文本审核",
            "image": "Qwen3-VL + DeepSeek — VL提取+文本分类",
            "audio": "FunASR STT + Text Pipeline",
            "video": "ffmpeg多帧 + VL + ASR + 时间轴融合",
            "blackhat": "Pattern + Adversarial + Account Risk (规则引擎, 无LLM调用)",
            "react": "ReAct Agent — 低置信度/对抗样本时自动触发多步推理 (v3.1生效)",
            "debate": "4模式多Agent辩论 (规则驱动, 多数/加权/共识/升级)",
            "reflexion": "Actor→Evaluator→Self-Reflection 2轮循环 (LLM+规则回退)",
            "risk": "模态感知加权 + 强制升级规则",
        },
        "rag": {
            "layers": "BM25 + Dense Vector + RRF Fusion + CrossEncoder Rerank",
            "agentic": "QueryRewriter + RetrievalRouter + SelfRAG + LLM改写",
            "graph": "违规知识图谱 BFS (触发路径: risk_agent → graph_rag.get_insights)",
            "multimodal": "CLIP视觉检索 + 多模态RRF融合 (v3.1生效: image_agent_node自动触发)",
        },
        "optimization": {
            "prompt": "PromptRegistry版本化 + 自动反馈驱动优化",
            "feedback_loop": "FeedbackLoop: 工作流自动收集反馈, 阈值=20触发优化 (v3.1生效)",
            "evaluation": "LLM-as-Judge: 人工审核恢复时自动比较AI vs 人工判定 (v3.1生效)",
            "red_team": "5种对抗攻击向量 (POST /api/v1/eval/red-team 手动触发)",
        },
        "protocols": {
            "mcp": f"JSON-RPC 2.0 + {len(tools)}个工具 (真实本地执行)",
            "mcp_tools": list(tools.keys()),
            "a2a": "A2A任务追踪: 每个工作流运行为一个Task, 节点间发送Message (v3.1生效)",
            "websocket": "workflow.astream() 流式推送节点事件",
        },
        "memory": {
            "short_term": "Redis (1h TTL) — 任务状态 + LLM缓存",
            "long_term": "ChromaDB — moderation_cases + core_memory 双collection (v3.1: 重要性分层)",
            "relational": "PostgreSQL (asyncpg) — moderation_records表",
            "importance": "ImportanceCalculator (6维度评分) → 高重要性案例进入core_memory",
        },
        "human_in_loop": {
            "interrupt": "LangGraph interrupt() — 真正暂停工作流 (v3.1生效)",
            "resume": "POST /api/v1/moderate/{content_id}/review — 提交人工判定后恢复",
        },
        "telemetry": {
            "tracing": "OpenTelemetry/LocalTracer — 所有Agent的LLM调用已接入trace (v3.1生效)",
            "output": "/workspace/logs/traces.jsonl (本地JSON Lines)",
        },
        "models": {
            "text": "deepseek-v4-flash",
            "vision": "qwen3.6-plus (阿里百炼)",
            "embedding": "bge-small-zh-v1.5 (384维)",
            "reranker": "bge-reranker-v2-m3 (Cross-Encoder)",
            "stt": "FunASR SenseVoiceSmall (本地)",
        },
        "ports": {
            "backend": _settings.backend_port,
            "frontend": _settings.frontend_port,
            "pg": _settings.pg_port,
            "redis": _settings.redis_port,
            "chroma": _settings.chroma_port,
            "funasr": _settings.funasr_port,
        },
        "no_rlhf": "本项目不包含RLHF训练 — 反馈优化为Prompt级别文字调整, 非模型参数更新",
    }
