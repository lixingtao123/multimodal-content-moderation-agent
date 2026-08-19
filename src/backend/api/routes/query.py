"""
查询 API — GET 端点：查询审核结果、任务状态
"""
import logging
from datetime import timezone
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from db import connection as db_conn
from memory.manager import get_memory_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["query"])
memory = get_memory_manager()


def _utc_iso(value) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


@router.get("/moderate/{content_id}")
async def get_moderation_result(content_id: str):
    """查询审核结果（Redis 短期记忆 + PostgreSQL 补充推理数据）"""
    result = None

    # 1. 查短期记忆（进行中或近期完成的任务）
    short_term = await memory.get_task_status(content_id)
    if short_term:
        result = {
            "content_id": content_id,
            "content_type": short_term.get("content_type", "text"),
            "status": short_term.get("status", "UNKNOWN"),
            "current_step": short_term.get("current_step", ""),
            "final_decision": short_term.get("final_decision", ""),
            "risk_score": short_term.get("risk_score", 0.0),
            "violation_types": short_term.get("violation_types", []),
            "violation_details": short_term.get("violation_details", {}),
            "suggestions": short_term.get("suggestions", []),
            "processing_time_ms": short_term.get("processing_time_ms", 0.0),
            "created_at": short_term.get("created_at", ""),
            "cached": short_term.get("cached", False),
            "human_review_required": short_term.get("human_review_required", False),
            "debate_info": short_term.get("debate_info", None),
            "agent_reasoning": short_term.get("agent_reasoning", None),
            "source": "redis",
        }

    # 2. 从 PostgreSQL 补充所有 Redis 短期记忆缺失的字段
    #    Redis 只存: status/content_type/final_decision/risk_score/agent_reasoning/debate_info
    #    PostgreSQL 有完整数据: violation_types/violation_details/suggestions/processing_time_ms/created_at
    if result is None or result.get("agent_reasoning") is None or result.get("debate_info") is None \
       or not result.get("violation_types") or not result.get("created_at") \
       or not result.get("content_preview"):
        try:
            async with db_conn.async_session_factory() as session:
                row_result = await session.execute(
                    text("""
                        SELECT agent_reasoning, debate_info, final_decision, risk_score,
                               violation_types, violation_details, suggestions,
                               processing_time_ms, content_type, content_preview, created_at
                        FROM moderation_records
                        WHERE content_id = :cid
                    """),
                    {"cid": content_id},
                )
                row = row_result.fetchone()
                if row:
                    if result is None:
                        result = {
                            "content_id": content_id,
                            "content_type": row.content_type,
                            "content_preview": row.content_preview or "",
                            "final_decision": row.final_decision,
                            "risk_score": row.risk_score,
                            "violation_types": row.violation_types or [],
                            "violation_details": row.violation_details or {},
                            "suggestions": row.suggestions or [],
                            "processing_time_ms": row.processing_time_ms or 0.0,
                            "created_at": _utc_iso(row.created_at),
                            "status": "COMPLETED",
                            "current_step": "",
                            "cached": False,
                            "human_review_required": False,
                            "source": "postgres",
                        }
                    else:
                        result["content_type"] = row.content_type
                        result["content_preview"] = row.content_preview or ""
                        result["final_decision"] = row.final_decision
                        result["risk_score"] = row.risk_score
                        result["status"] = "COMPLETED"
                        result["human_review_required"] = row.final_decision == "REVIEW"
                    # 用 PostgreSQL 的数据补充/覆盖所有 Redis 缺失的字段
                    if result.get("agent_reasoning") is None:
                        result["agent_reasoning"] = row.agent_reasoning
                    if result.get("debate_info") is None:
                        result["debate_info"] = row.debate_info
                    if not result.get("content_preview"):
                        result["content_preview"] = row.content_preview or ""
                    # 补充 violation_types / suggestions / created_at 等 Redis 不存的字段
                    if not result.get("violation_types"):
                        result["violation_types"] = row.violation_types or []
                    if not result.get("violation_details"):
                        result["violation_details"] = row.violation_details or {}
                    if not result.get("suggestions"):
                        result["suggestions"] = row.suggestions or []
                    if not result.get("processing_time_ms"):
                        result["processing_time_ms"] = row.processing_time_ms or 0.0
                    if not result.get("created_at"):
                        result["created_at"] = _utc_iso(row.created_at)
                    if result.get("source") == "redis":
                        result["source"] = "redis+postgres"  # 混合来源
        except Exception as e:
            logger.warning(f"Failed to query DB for {content_id}: {e}")

    if result:
        return result

    raise HTTPException(status_code=404, detail="Content not found")


@router.get("/history")
async def list_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    decision: str = Query(None, description="Filter: PASS / REVIEW / REJECT"),
    content_type: str = Query(None, description="Filter: text / image / audio / video"),
):
    """审核历史列表（分页）"""
    try:
        # R19 修复：数据库未初始化时降级返回空列表（不再 500）
        if db_conn.async_session_factory is None:
            return {"total": 0, "items": [], "page": page, "page_size": page_size,
                    "degraded": True, "note": "数据库未初始化"}
        async with db_conn.async_session_factory() as session:
            conditions = []
            params = {}
            if decision and decision.upper() != "ALL":
                conditions.append("final_decision = :decision")
                params["decision"] = decision
            if content_type and content_type.upper() != "ALL":
                conditions.append("content_type = :ctype")
                params["ctype"] = content_type

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            # Count
            count_result = await session.execute(
                text(f"SELECT COUNT(*) FROM moderation_records WHERE {where_clause}"),
                params,
            )
            total = count_result.scalar()

            # Page
            offset = (page - 1) * page_size
            rows = await session.execute(
                text(f"""
                    SELECT content_id, content_type, content_preview, final_decision,
                           risk_score, processing_time_ms, created_at
                    FROM moderation_records
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {**params, "limit": page_size, "offset": offset},
            )

            items = []
            for row in rows.fetchall():
                items.append({
                    "content_id": row.content_id,
                    "content_type": row.content_type,
                    "content_preview": row.content_preview or "",
                    "final_decision": row.final_decision,
                    "risk_score": row.risk_score,
                    "processing_time_ms": row.processing_time_ms,
                    "created_at": _utc_iso(row.created_at),
                })

            return {"total": total, "page": page, "page_size": page_size, "items": items}
    except Exception as e:
        logger.error(f"Failed to list history: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
