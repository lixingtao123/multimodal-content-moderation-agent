"""
管理 API — 统计数据、模式管理
"""
import logging
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from db import connection as db_conn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/statistics")
async def get_statistics():
    """获取审核统计数据"""
    try:
        # R19 修复：数据库未初始化时降级返回空统计（不再 500）
        if db_conn.async_session_factory is None:
            return {
                "total_moderated": 0, "by_decision": {}, "by_type": {},
                "avg_risk_score": 0.0, "avg_processing_time_ms": 0.0,
                "degraded": True, "note": "数据库未初始化，统计为空",
            }
        async with db_conn.async_session_factory() as session:
            # 总量统计
            total = await session.execute(text("SELECT COUNT(*) FROM moderation_records"))
            total_count = total.scalar()

            # 按决策统计
            decision_stats = await session.execute(text("""
                SELECT final_decision, COUNT(*) as cnt
                FROM moderation_records
                GROUP BY final_decision
            """))
            decisions = {row.final_decision: row.cnt for row in decision_stats.fetchall()}

            # 平均风险分
            avg_risk = await session.execute(
                text("SELECT AVG(risk_score) FROM moderation_records")
            )
            avg_risk_score = round(avg_risk.scalar() or 0.0, 4)

            # 按类型统计
            type_stats = await session.execute(text("""
                SELECT content_type, COUNT(*) as cnt
                FROM moderation_records
                GROUP BY content_type
            """))
            types = {row.content_type: row.cnt for row in type_stats.fetchall()}

            # 平均处理时间
            avg_time = await session.execute(
                text("SELECT AVG(processing_time_ms) FROM moderation_records")
            )
            avg_processing_ms = round(avg_time.scalar() or 0.0, 2)

            return {
                "total_moderated": total_count,
                "by_decision": decisions,
                "by_type": types,
                "avg_risk_score": avg_risk_score,
                "avg_processing_time_ms": avg_processing_ms,
            }
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/overview")
async def get_stats_overview():
    """
    v4.0: 数据看板概览 — 7天趋势 + 违规分布 + 成本估算
    """
    from datetime import datetime, timedelta

    try:
        # R19 修复：数据库未初始化时降级返回空概览（不再 500）
        if db_conn.async_session_factory is None:
            return {
                "daily_trend": [], "violation_distribution": [],
                "overview": {"total": 0, "active_days": 0, "avg_risk": 0,
                             "avg_time_ms": 0, "pass_rate": 0},
                "token_estimate": {"llm_calls": 0, "total_tokens": 0, "est_cost_cny": 0},
                "degraded": True, "note": "数据库未初始化",
            }
        async with db_conn.async_session_factory() as session:
            # 1. 最近7天每日趋势
            daily_trend = await session.execute(text("""
                SELECT
                    DATE(created_at) as day,
                    COUNT(*) as total,
                    SUM(CASE WHEN final_decision = 'PASS' THEN 1 ELSE 0 END) as pass_count,
                    SUM(CASE WHEN final_decision = 'REVIEW' THEN 1 ELSE 0 END) as review_count,
                    SUM(CASE WHEN final_decision = 'REJECT' THEN 1 ELSE 0 END) as reject_count,
                    ROUND(COALESCE(AVG(risk_score), 0)::numeric, 3) as avg_risk,
                    ROUND(COALESCE(AVG(processing_time_ms), 0)::numeric, 1) as avg_time_ms
                FROM moderation_records
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY DATE(created_at)
                ORDER BY day
            """))
            daily_rows = [dict(zip(row._mapping.keys(), row._mapping.values()))
                          for row in daily_trend.fetchall()]
            # Convert date to string for JSON
            for r in daily_rows:
                if isinstance(r.get('day'), datetime):
                    r['day'] = r['day'].strftime('%Y-%m-%d')

            # 2. 违规类型分布 (最近7天, 展开 JSONB violation_types)
            violation_dist = await session.execute(text("""
                SELECT
                    vt as violation_type,
                    COUNT(*) as cnt
                FROM moderation_records,
                LATERAL jsonb_array_elements_text(violation_types) AS vt
                WHERE created_at >= NOW() - INTERVAL '7 days'
                  AND violation_types IS NOT NULL
                  AND jsonb_array_length(violation_types) > 0
                GROUP BY vt
                ORDER BY cnt DESC
                LIMIT 15
            """))
            violation_rows = [dict(zip(row._mapping.keys(), row._mapping.values()))
                              for row in violation_dist.fetchall()]

            # 3. 总览统计
            overview_row = (await session.execute(text("""
                SELECT
                    COUNT(*) as total,
                    COUNT(DISTINCT DATE(created_at)) as active_days,
                    ROUND(COALESCE(AVG(risk_score), 0)::numeric, 3) as avg_risk,
                    ROUND(COALESCE(AVG(processing_time_ms), 0)::numeric, 1) as avg_time_ms,
                    ROUND(SUM(CASE WHEN final_decision = 'PASS' THEN 1 ELSE 0 END) * 100.0 / GREATEST(COUNT(*), 1), 1) as pass_rate
                FROM moderation_records
                WHERE created_at >= NOW() - INTERVAL '7 days'
            """))).fetchone()
            overview = dict(zip(overview_row._mapping.keys(), overview_row._mapping.values())) if overview_row else {
                "total": 0, "active_days": 0, "avg_risk": 0, "avg_time_ms": 0, "pass_rate": 0
            }

            # 4. Token 消耗估算
            token_row = (await session.execute(text("""
                SELECT
                    COUNT(*) as llm_calls,
                    COALESCE(SUM(processing_time_ms * 0.05), 0)::int as estimated_tokens,
                    ROUND((COALESCE(SUM(processing_time_ms * 0.05 * 0.000001), 0))::numeric, 4) as estimated_cost_usd
                FROM moderation_records
                WHERE created_at >= NOW() - INTERVAL '7 days'
                  AND content_type = 'text'
            """))).fetchone()
            token_info = dict(zip(token_row._mapping.keys(), token_row._mapping.values())) if token_row else {
                "llm_calls": 0, "estimated_tokens": 0, "estimated_cost_usd": 0
            }

            return {
                "daily_trend": daily_rows,
                "violation_distribution": violation_rows,
                "overview": overview,
                "token_estimate": token_info,
            }
    except Exception as e:
        logger.error(f"Failed to get stats overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/dependencies")
async def health_dependencies():
    """检查所有依赖服务健康状态"""
    from memory.redis_service import get_redis_service
    from memory.chroma_service import get_chroma_service
    import httpx
    from common.config import get_settings

    settings = get_settings()
    status = {"postgres": True, "redis": True, "chromadb": True, "funasr": True}

    try:
        async with db_conn.async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        status["postgres"] = False

    try:
        redis_svc = get_redis_service()
        if redis_svc.client:
            await redis_svc.client.ping()
    except Exception:
        status["redis"] = False

    try:
        chroma_svc = get_chroma_service()
        if chroma_svc.client:
            chroma_svc.client.heartbeat()
    except Exception:
        status["chromadb"] = False

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.funasr_url}/health", timeout=5.0)
            if resp.status_code != 200:
                raise Exception("FunASR unhealthy")
    except Exception:
        status["funasr"] = False

    all_healthy = all(status.values())
    return {
        "all_healthy": all_healthy,
        "dependencies": status,
    }


# === 优化监控 API ===

@router.get("/optimization/feedback-stats")
async def get_feedback_stats():
    """获取标注统计 (v2: 从 Redis 读取 AnnotationAgent 统计)"""
    from optimization.annotation_queue import get_annotation_stats
    return await get_annotation_stats()


@router.get("/optimization/prompt-versions/{prompt_name}")
async def list_prompt_versions(prompt_name: str):
    """获取指定 Prompt 的所有版本历史"""
    from optimization.prompt_optimizer import get_prompt_registry
    registry = get_prompt_registry()
    versions = registry.list_versions(prompt_name)
    active = None
    detail_list = []
    for v in versions:
        pv = registry.get(prompt_name, v)
        if pv:
            detail_list.append({
                "name": pv.name,
                "version": pv.version,
                "model": pv.model,
                "optimizer": pv.optimizer,
                "metrics": pv.metrics,
                "system_prompt_snippet": pv.system_prompt[:100] + "..." if len(pv.system_prompt) > 100 else pv.system_prompt,
                "created_at": pv.created_at,
            })
    # 获取当前活跃版本
    if versions:
        active_pv = registry.get_active(prompt_name)
        if active_pv:
            active = active_pv.version

    return {
        "prompt_name": prompt_name,
        "active_version": active,
        "versions": detail_list,
    }


@router.get("/optimization/prompts")
async def list_all_prompts():
    """列出所有已注册的 Prompt 名称"""
    from optimization.prompt_optimizer import get_prompt_registry
    registry = get_prompt_registry()
    names = []
    for name in registry._prompts:
        active_pv = registry.get_active(name)
        names.append({
            "name": name,
            "active_version": active_pv.version if active_pv else None,
            "total_versions": len(registry._prompts.get(name, {})),
        })
    return {"prompts": names}


@router.post("/optimization/trigger")
async def trigger_optimization(source: str = "all"):
    """手动触发一次优化 (v3.2: 支持 source 过滤: all/auto/human)"""
    from optimization.annotation_queue import trigger_manual_optimization
    return await trigger_manual_optimization(source_filter=source)


# === 标注结果查询 API ===

@router.get("/optimization/annotation-buffer")
async def get_annotation_buffer(limit: int = 50, offset: int = 0):
    """获取当前标注错误积累列表 (分页)"""
    from optimization.annotation_queue import get_annotation_buffer
    items = await get_annotation_buffer(limit=limit, offset=offset)
    return {"total": len(items), "items": items}


@router.get("/optimization/annotation-all")
async def get_all_annotation_results(limit: int = 50, offset: int = 0, error_type: str = ""):
    """获取全量标注结果 (含正确和错误, 支持筛选)"""
    from optimization.annotation_queue import get_all_annotation_results
    items = await get_all_annotation_results(limit=limit, offset=offset, error_type=error_type)
    return {"total": len(items), "items": items}


@router.get("/optimization/annotation-results/{content_id}")
async def get_annotation_result(content_id: str):
    """查询特定内容的标注结果"""
    from optimization.annotation_queue import get_annotation_result
    result = await get_annotation_result(content_id)
    if result:
        return result
    raise HTTPException(status_code=404, detail=f"No annotation result found for {content_id}")


@router.get("/optimization/reports")
async def list_optimization_reports(limit: int = 10):
    """获取优化报告列表"""
    from optimization.annotation_queue import get_optimization_reports
    reports = await get_optimization_reports(limit=limit)
    return {"total": len(reports), "reports": reports}


@router.get("/optimization/annotation-stats")
async def get_annotation_statistics():
    """获取标注统计 (v2: 完整版, 包含错误分类)"""
    from optimization.annotation_queue import get_annotation_stats
    return await get_annotation_stats()


# === v3.2: 人工标注端点 ===

from pydantic import BaseModel

class HumanAnnotationRequest(BaseModel):
    """人工标注请求 — 标注人员可直接修改 AI 的 JSON 输出"""
    reviewer_id: str = "human_annotator"
    violation_type: str = ""       # 人工修正后的违规类型
    confidence: float = 1.0        # 人工标注置信度(默认1.0)
    reason: str = ""              # 人工判定理由
    tags: list[str] = []           # 人工修正后的标签
    is_adversarial: bool = False
    decision: str = "REVIEW"       # PASS / REVIEW / REJECT


@router.post("/annotation/human")
async def submit_human_annotation(content_id: str, annotation: HumanAnnotationRequest):
    """
    v3.2: 提交人工标注 — 独立于工作流恢复流程

    标注人员可以查看 AI 推理后，直接修改 AI 的 JSON 输出，
    提交正确的内容作为 ground truth。

    效果:
    - 写入 annotation_records (source='human', weight=3.0)
    - 更新 moderation_records 中的人工判定
    - 移除待审核队列
    """
    import json as _json
    from sqlalchemy import text
    from db import connection as db_conn
    from optimization.prompt_optimizer import get_feedback_loop

    try:
        # 1. 从 moderation_records 获取 AI 原始判定
        async with db_conn.async_session_factory() as session:
            row_result = await session.execute(text("""
                SELECT final_decision, violation_types, risk_score, agent_reasoning
                FROM moderation_records WHERE content_id = :cid
            """), {"cid": content_id})
            row = row_result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Content {content_id} not found")

            ai_decision = row.final_decision
            ai_vtypes = row.violation_types or []
            ai_score = row.risk_score or 0.0

        # 2. 判断 AI 是否错误
        is_error = False
        error_type = "correct"
        human_decision = annotation.decision
        human_vtype = annotation.violation_type or "none"

        if human_decision != ai_decision:
            is_error = True
            if human_decision in ("REJECT", "REVIEW") and ai_decision == "PASS":
                error_type = "false_negative"
            elif human_decision == "PASS" and ai_decision in ("REJECT", "REVIEW"):
                error_type = "false_positive"
            else:
                error_type = "wrong_violation_type"
        elif human_vtype not in ai_vtypes and human_vtype != "none":
            error_type = "wrong_violation_type"
            is_error = True

        # 3. 构建人工修正后的 JSON
        human_corrected = {
            "violation_type": human_vtype,
            "confidence": annotation.confidence,
            "reason": annotation.reason,
            "tags": annotation.tags,
            "is_adversarial": annotation.is_adversarial,
            "decision": human_decision,
        }

        # 4. 写入 annotation_records
        async with db_conn.async_session_factory() as session:
            await session.execute(text("""
                INSERT INTO annotation_records
                (content_id, content_type, model_decision, model_confidence,
                 model_violation_types, model_risk_score,
                 is_error, error_type, error_detail,
                 annotated_violation_types, annotated_confidence,
                 source, weight, reviewer_id, human_corrected_json)
                VALUES (:cid, 'text', :mdec, :mconf,
                        :mvtypes, :mrisk,
                        :iserr, :etype, :edetail,
                        :avtypes, :aconf,
                        'human', 3.0, :rid, :hcorrected)
                ON CONFLICT (content_id) DO UPDATE SET
                    is_error = EXCLUDED.is_error,
                    error_type = EXCLUDED.error_type,
                    error_detail = EXCLUDED.error_detail,
                    annotated_violation_types = EXCLUDED.annotated_violation_types,
                    annotated_confidence = EXCLUDED.annotated_confidence,
                    source = 'human',
                    weight = 3.0,
                    reviewer_id = EXCLUDED.reviewer_id,
                    human_corrected_json = EXCLUDED.human_corrected_json,
                    annotated_at = NOW()
            """), {
                "cid": content_id, "mdec": ai_decision,
                "mconf": ai_score, "mvtypes": _json.dumps(ai_vtypes, ensure_ascii=False),
                "mrisk": ai_score,
                "iserr": is_error, "etype": error_type,
                "edetail": f"人工标注: {human_decision}/{human_vtype}, AI原判定: {ai_decision}/{ai_vtypes}",
                "avtypes": _json.dumps([human_vtype] if human_vtype != "none" else [], ensure_ascii=False),
                "aconf": annotation.confidence,
                "rid": annotation.reviewer_id,
                "hcorrected": _json.dumps(human_corrected, ensure_ascii=False),
            })
            await session.commit()
            logger.info(f"[HumanAnnotation] {content_id}: source=human, error={error_type}")

        # 5. 更新 moderation_records
        async with db_conn.async_session_factory() as session:
            await session.execute(text("""
                UPDATE moderation_records SET final_decision = :dec,
                violation_types = :vtypes, updated_at = NOW()
                WHERE content_id = :cid
            """), {
                "dec": human_decision,
                "vtypes": _json.dumps([human_vtype] if human_vtype != "none" else [], ensure_ascii=False),
                "cid": content_id,
            })
            await session.commit()

        # 6. 写入 FeedbackLoop (触发可能的优化)
        if is_error:
            try:
                fb = get_feedback_loop()
                fb.collect_feedback({
                    "prompt_name": "text_moderation",
                    "content": content_id,
                    "actual_decision": ai_decision,
                    "expected_decision": human_decision,
                    "error_type": error_type,
                    "source": "human",  # 标记人工反馈
                })
            except Exception:
                pass

        # 7. 从待审核队列移除
        try:
            from memory.redis_service import get_redis_service
            svc = get_redis_service()
            if svc.client:
                await svc.client.delete(f"pending_review:{content_id}")
        except Exception:
            pass

        # R21: 人工标注 pipeline 尾日志（AI 判定 vs 人工修正，可归因可分析）
        try:
            from common.logger import append_pipeline_tail
            await append_pipeline_tail(
                content_id, "👤 HUMAN_ANNOTATE",
                f"人工标注: {human_decision}/{human_vtype} ({error_type})",
                output_data={
                    "ai_decision": ai_decision,
                    "ai_violation_types": ai_vtypes,
                    "human_decision": human_decision,
                    "human_violation_type": human_vtype,
                    "is_error": is_error,
                    "error_type": error_type,
                    "reviewer_id": annotation.reviewer_id,
                    "reason": (annotation.reason or "")[:200],
                },
            )
        except Exception as _ann_err:
            logger.warning(f"[HumanAnnotation] 追加 pipeline 尾日志失败: {_ann_err}")

        return {
            "saved": True,
            "content_id": content_id,
            "source": "human",
            "weight": 3.0,
            "is_error": is_error,
            "error_type": error_type,
            "human_corrected": human_corrected,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HumanAnnotation] Failed for {content_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Annotation failed: {str(e)}")


@router.get("/annotation/human/stats")
async def get_human_annotation_stats():
    """获取人工标注统计 (source='human')"""
    from sqlalchemy import text
    from db import connection as db_conn

    try:
        async with db_conn.async_session_factory() as session:
            result = await session.execute(text("""
                SELECT
                    COUNT(*) as total_human,
                    COUNT(*) FILTER (WHERE is_error = TRUE) as errors_found,
                    COUNT(*) FILTER (WHERE error_type = 'false_positive') as false_positives,
                    COUNT(*) FILTER (WHERE error_type = 'false_negative') as false_negatives,
                    COUNT(*) FILTER (WHERE error_type = 'wrong_violation_type') as wrong_types,
                    COUNT(*) FILTER (WHERE error_type = 'correct') as correct,
                    COALESCE(AVG(weight), 0) as avg_weight
                FROM annotation_records
                WHERE source = 'human'
            """))
            row = result.fetchone()
            if not row:
                return {"total_human": 0, "errors_found": 0}

            # 对比自动标注
            auto_result = await session.execute(text("""
                SELECT
                    COUNT(*) as total_auto,
                    COUNT(*) FILTER (WHERE is_error = TRUE) as errors_found
                FROM annotation_records
                WHERE source = 'auto'
            """))
            auto_row = auto_result.fetchone()

            return {
                "human": {
                    "total": row.total_human or 0,
                    "errors_found": row.errors_found or 0,
                    "false_positives": row.false_positives or 0,
                    "false_negatives": row.false_negatives or 0,
                    "wrong_types": row.wrong_types or 0,
                    "correct": row.correct or 0,
                    "avg_weight": round(row.avg_weight or 0, 2),
                },
                "auto": {
                    "total": auto_row.total_auto if auto_row else 0,
                    "errors_found": auto_row.errors_found if auto_row else 0,
                },
            }
    except Exception as e:
        logger.error(f"Failed to get human annotation stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
