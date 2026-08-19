"""
标注队列 — Redis 异步队列 + 后台消费者 + PostgreSQL 持久化

生产者:
  - moderation.py: _run_moderation() 完成后 asyncio.create_task(enqueue(...))

消费者:
  - AnnotationConsumer: FastAPI lifespan 中启动的后台协程
  - BRPOP 阻塞消费 annotation:queue
  - 每个 item 调 AnnotationAgent.annotate()
  - 结果写入 PostgreSQL (持久化) + Redis buffer
  - 更新 Redis 统计计数器

触发:
  - 自动: PostgreSQL 中未消费错误 >= BUFFER_THRESHOLD → 触发 OptimizationAgent
  - 手动: POST /api/v1/admin/optimization/trigger
  - 优化完成后标记 consumed=TRUE (数据不删除, 仅不再计数)

持久化设计:
  - PostgreSQL annotation_records 表 = 数据源 (持久化, 不丢失)
  - Redis = 实时队列 + 缓存
  - 重启后从 PostgreSQL 恢复统计数据
"""
import json
import asyncio
import logging
import time
from typing import Optional
from dataclasses import asdict

from sqlalchemy import text as sa_text
from memory.redis_service import get_redis_service
from db import connection as db_conn
from .annotation_agent import get_annotation_agent, AnnotationResult

logger = logging.getLogger(__name__)

# Redis Key 常量
QUEUE_KEY = "moderation:annotation:queue"       # 待标注队列 (List, LPUSH/BRPOP)
BUFFER_KEY = "moderation:annotation:buffer"     # 错误积累缓冲区 (List, LPUSH/LRANGE)
RESULTS_KEY = "moderation:annotation:results"   # 全量标注结果 (List, LPUSH/LTRIM, 保留最近500条)
STATS_KEY = "moderation:annotation:stats"       # 统计计数器 (Hash)
LOCK_KEY = "moderation:annotation:lock"         # 消费者分布式锁
OPT_LOCK_KEY = "moderation:annotation:optimizing"  # 优化执行锁
REPORTS_KEY = "moderation:annotation:reports"   # 优化报告列表 (List)

# 优化触发阈值
BUFFER_THRESHOLD = 100
# 最小优化间隔 (秒)
MIN_OPTIMIZE_INTERVAL = 600  # 10 分钟


async def _save_annotation_to_pg(result: AnnotationResult):
    """将标注结果写入 PostgreSQL (持久化数据源)"""
    try:
        import json as _json
        from datetime import datetime, timezone

        # 解析 annotated_at 字符串为 datetime 对象 (asyncpg 不支持字符串传 TIMESTAMP)
        # 注意: 去掉时区信息, PostgreSQL TIMESTAMP WITHOUT TIME ZONE 不接受 aware datetime
        annotated_at = None
        if result.annotated_at:
            try:
                ts_str = result.annotated_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_str)
                annotated_at = dt.replace(tzinfo=None)  # 转为 naive datetime
            except (ValueError, TypeError):
                annotated_at = None

        result_dict = asdict(result)
        async with db_conn.async_session_factory() as session:
            await session.execute(sa_text("""
                INSERT INTO annotation_records
                (content_id, content_type, annotation_input, model_decision,
                 model_confidence, model_violation_types, model_reason, model_risk_score,
                 is_error, error_type, error_detail,
                 rule_verdict, rule_detail, llm_verdict, llm_reason, llm_called,
                 contradiction_flag, annotated_violation_types, annotated_confidence,
                 rule_matched_keywords, rule_matched_rules,
                 rule_whitelist_hit, rule_adversarial_hit,
                 processing_time_ms, annotated_at,
                 source, weight, reviewer_id, human_corrected_json)
                VALUES (:cid, :ctype, :ainput, :mdec,
                        :mconf, :mvtypes, :mreason, :mrisk,
                        :iserr, :etype, :edetail,
                        :rverdict, :rdetail, :lverdict, :lreason, :llm_called,
                        :contra, :avtypes, :aconf,
                        :rmkeywords, :rmrules,
                        :rwhitelist, :radv,
                        :ptime, :aat,
                        :source, :weight, :reviewer_id, :hcorrected)
                ON CONFLICT (content_id) DO UPDATE SET
                    is_error = EXCLUDED.is_error,
                    error_type = EXCLUDED.error_type,
                    error_detail = EXCLUDED.error_detail,
                    rule_verdict = EXCLUDED.rule_verdict,
                    llm_verdict = EXCLUDED.llm_verdict,
                    annotated_at = EXCLUDED.annotated_at,
                    -- v3.2: 自动标注不覆盖人工标注的 source/weight
                    source = CASE WHEN annotation_records.source = 'human' THEN 'human' ELSE EXCLUDED.source END,
                    weight = CASE WHEN annotation_records.source = 'human' THEN annotation_records.weight ELSE EXCLUDED.weight END,
                    reviewer_id = CASE WHEN annotation_records.source = 'human' THEN annotation_records.reviewer_id ELSE EXCLUDED.reviewer_id END
            """), {
                "cid": result.content_id, "ctype": result_dict.get("content_type", "text"),
                "ainput": result_dict.get("annotation_input", ""),
                "mdec": result_dict.get("model_decision", ""),
                "mconf": result_dict.get("model_confidence", 0.0),
                "mvtypes": _json.dumps(result_dict.get("model_violation_types", []), ensure_ascii=False),
                "mreason": result_dict.get("model_reason", ""),
                "mrisk": result_dict.get("model_risk_score", 0.0),
                "iserr": result.is_error,
                "etype": result.error_type,
                "edetail": result.error_detail,
                "rverdict": result.rule_verdict,
                "rdetail": result.rule_detail,
                "lverdict": result.llm_verdict,
                "lreason": result.llm_reason,
                "llm_called": result_dict.get("llm_called", False),
                "contra": result.contradiction_flag,
                "avtypes": _json.dumps(result_dict.get("annotated_violation_types", []), ensure_ascii=False),
                "aconf": result_dict.get("annotated_confidence", 0.0),
                "rmkeywords": _json.dumps(result_dict.get("rule_matched_keywords", []), ensure_ascii=False),
                "rmrules": _json.dumps(result_dict.get("rule_matched_rules", []), ensure_ascii=False),
                "rwhitelist": result_dict.get("rule_whitelist_hit", False),
                "radv": result_dict.get("rule_adversarial_hit", False),
                "ptime": result_dict.get("processing_time_ms", 0.0),
                "aat": annotated_at,
                "source": result_dict.get("source", "auto"),
                "weight": result_dict.get("weight", 1.0),
                "reviewer_id": result_dict.get("reviewer_id", ""),
                "hcorrected": _json.dumps(result_dict.get("human_corrected_json"), ensure_ascii=False) if result_dict.get("human_corrected_json") else None,
            })
            await session.commit()
            logger.debug(f"[Annotation] Saved to PG: {result.content_id}")
    except Exception as e:
        logger.warning(f"[Annotation] Failed to save to PG (non-blocking): {e}")


async def enqueue_annotation(item: dict):
    """审核完成时将结果异步入队 (生产者端, 非阻塞)"""
    try:
        svc = get_redis_service()
        if svc.client:
            payload = json.dumps(item, ensure_ascii=False)
            await svc.client.lpush(QUEUE_KEY, payload)
            logger.debug(f"[AnnotationQueue] Enqueued: {item.get('content_id')}")
    except Exception as e:
        logger.warning(f"[AnnotationQueue] Enqueue failed (non-blocking): {e}")


class AnnotationConsumer:
    """
    后台标注消费者 (并发模式)

    使用 BRPOP 阻塞等待队列消息, 零 polling 延迟。
    asyncio.Semaphore 控制并发标注数, 多个 worker 协程并行 BRPOP + 标注。
    在 FastAPI lifespan 中启动/停止。
    """

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running = False
        self._workers: list[asyncio.Task] = []

    async def start(self):
        """启动消费者池 — 创建 max_concurrent 个并发 worker"""
        if self._running:
            return
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker_loop(i))
            for i in range(self.max_concurrent)
        ]
        logger.info(f"[AnnotationConsumer] Started with {self.max_concurrent} workers "
                     f"(BRPOP mode, threshold={BUFFER_THRESHOLD})")

    async def stop(self):
        """停止所有 worker"""
        self._running = False
        for w in self._workers:
            if not w.done():
                w.cancel()
        results = await asyncio.gather(*self._workers, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
                logger.warning(f"[AnnotationConsumer] Worker error during shutdown: {r}")
        self._workers.clear()
        logger.info("[AnnotationConsumer] Stopped")

    async def _worker_loop(self, worker_id: int):
        """单个 worker 的主循环 — BRPOP 阻塞取任务 + 信号量限流"""
        agent = get_annotation_agent()
        svc = get_redis_service()

        while self._running:
            try:
                # 阻塞命令用专用长连接（无 socket_timeout），避免 BRPOP 阻塞期间
                # 触发全局连接 socket_timeout=2.0 的读超时（R20 修复）
                client = svc.get_blocking_client()
                if client is None:
                    await asyncio.sleep(1)
                    continue

                # BRPOP 阻塞等待, 超时 2s 后检查 _running 状态
                result = await client.brpop(QUEUE_KEY, timeout=2)
                if result is None:
                    continue

                _, data = result
                item = json.loads(data)
                content_id = item.get("content_id", "unknown")

                # 信号量控制并发数
                async with self._semaphore:
                    await self._process_item(agent, svc, item, content_id, worker_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[AnnotationConsumer] Worker-{worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(0.5)

    async def _process_item(self, agent, svc, item: dict, content_id: str, worker_id: int):
        """处理单个标注项 — 从 BRPOP 取到到写入 PostgreSQL 的完整流程"""
        # 消费锁 (防多实例竞争)
        item_lock_key = f"{LOCK_KEY}:{content_id}"
        acquired = await svc.client.setnx(item_lock_key, "1")
        if not acquired:
            return
        await svc.client.expire(item_lock_key, 30)

        try:
            # 调用 AnnotationAgent 标注
            annotation_result: AnnotationResult = await agent.annotate(item)

            # 写入 PostgreSQL (持久化, 数据源)
            await _save_annotation_to_pg(annotation_result)

            # 更新统计
            await self._update_stats(svc, annotation_result)

            # 全量写入 results (保留最近 500 条，正确和错误都有)
            result_json = json.dumps(asdict(annotation_result), ensure_ascii=False)
            await svc.client.lpush(RESULTS_KEY, result_json)
            await svc.client.ltrim(RESULTS_KEY, 0, 499)

            # 只有模型错误才写入 buffer
            if annotation_result.is_error:
                await svc.client.lpush(BUFFER_KEY, result_json)
                logger.info(
                    f"[AnnotationConsumer] Worker-{worker_id} error accumulated: "
                    f"{content_id} ({annotation_result.error_type})"
                )

            # 检查是否需要自动触发优化
            await self._check_auto_optimize(svc)

        finally:
            await svc.client.delete(item_lock_key)

    async def _update_stats(self, svc, result: AnnotationResult):
        """更新统计计数器"""
        try:
            await svc.client.hincrby(STATS_KEY, "total_processed", 1)
            if result.is_error:
                await svc.client.hincrby(STATS_KEY, "total_errors", 1)
                await svc.client.hincrby(STATS_KEY, result.error_type + "s", 1)
            else:
                await svc.client.hincrby(STATS_KEY, "correct", 1)
            await svc.client.hset(STATS_KEY, "last_annotation_time", str(int(time.time())))
        except Exception as e:
            logger.warning(f"[AnnotationConsumer] Stats update failed: {e}")

    async def _check_auto_optimize(self, svc):
        """检查是否达到自动优化阈值 (从 PostgreSQL 读取未消费错误数)"""
        try:
            # 检查是否正在优化
            optimizing = await svc.client.get(OPT_LOCK_KEY)
            if optimizing:
                return

            # 从 PostgreSQL 查询未消费的错误数
            async with db_conn.async_session_factory() as session:
                result = await session.execute(sa_text("""
                    SELECT COUNT(*) FROM annotation_records
                    WHERE is_error = TRUE AND consumed = FALSE
                """))
                buffer_size = result.scalar() or 0

            if buffer_size >= BUFFER_THRESHOLD:
                logger.info(
                    f"[AnnotationConsumer] Buffer threshold reached ({buffer_size}/{BUFFER_THRESHOLD}), "
                    "triggering auto-optimization..."
                )
                from .optimization_agent import get_optimization_agent
                opt_agent = get_optimization_agent()
                report = await opt_agent.optimize(trigger="auto")
                if report:
                    logger.info(f"[AnnotationConsumer] Auto-optimization completed: {len(report.get('actions', []))} actions")
        except Exception as e:
            logger.warning(f"[AnnotationConsumer] Auto-optimize check failed: {e}")


async def get_annotation_stats() -> dict:
    """获取标注统计 (从 PostgreSQL 查询, 持久化数据不丢失)"""
    try:
        async with db_conn.async_session_factory() as session:
            result = await session.execute(sa_text("""
                SELECT
                    COUNT(*) as total_processed,
                    COUNT(*) FILTER (WHERE is_error = TRUE AND consumed = FALSE) as total_errors,
                    COUNT(*) FILTER (WHERE error_type = 'false_positive' AND consumed = FALSE) as false_positives,
                    COUNT(*) FILTER (WHERE error_type = 'false_negative' AND consumed = FALSE) as false_negatives,
                    COUNT(*) FILTER (WHERE error_type = 'wrong_type' AND consumed = FALSE) as wrong_types,
                    COUNT(*) FILTER (WHERE error_type = 'correct') as correct,
                    COALESCE(MAX(annotated_at)::text, '') as last_annotation_time
                FROM annotation_records
            """))
            row = result.fetchone()
            if not row:
                return _empty_stats()

            total_errors = row.total_errors or 0
            return {
                "total_processed": row.total_processed or 0,
                "total_errors": total_errors,
                "false_positives": row.false_positives or 0,
                "false_negatives": row.false_negatives or 0,
                "wrong_types": row.wrong_types or 0,
                "correct": row.correct or 0,
                "last_annotation_time": str(row.last_annotation_time) if row.last_annotation_time else "",
                "last_optimization_time": "",  # 从 Redis 或优化报告表读取
                "threshold": BUFFER_THRESHOLD,
                "buffer_threshold": BUFFER_THRESHOLD,
                "last_optimization": 0,
                "buffer_size": total_errors,       # 未消费错误数 = buffer 大小
                "queue_size": 0,                    # Redis 队列大小 (瞬态的, 不关键)
                "ready_to_optimize": total_errors >= BUFFER_THRESHOLD,
            }
    except Exception as e:
        logger.warning(f"Failed to get annotation stats from PG: {e}")
        return _empty_stats()


async def get_annotation_buffer(limit: int = 50, offset: int = 0) -> list:
    """获取当前未消费的错误标注列表 (分页, 从 PostgreSQL)"""
    try:
        async with db_conn.async_session_factory() as session:
            result = await session.execute(sa_text("""
                SELECT * FROM annotation_records
                WHERE is_error = TRUE AND consumed = FALSE
                ORDER BY annotated_at DESC
                LIMIT :limit OFFSET :offset
            """), {"limit": limit, "offset": offset})
            rows = result.fetchall()
            return [_row_to_dict(row) for row in rows]
    except Exception as e:
        logger.warning(f"Failed to get annotation buffer from PG: {e}")
        return []


async def get_all_annotation_results(limit: int = 50, offset: int = 0,
                                     error_type: str = "") -> list:
    """获取全量标注结果列表 (分页+筛选, 从 PostgreSQL)"""
    try:
        async with db_conn.async_session_factory() as session:
            if error_type:
                result = await session.execute(sa_text("""
                    SELECT * FROM annotation_records
                    WHERE error_type = :etype
                    ORDER BY annotated_at DESC
                    LIMIT :limit OFFSET :offset
                """), {"etype": error_type, "limit": limit, "offset": offset})
            else:
                result = await session.execute(sa_text("""
                    SELECT * FROM annotation_records
                    ORDER BY annotated_at DESC
                    LIMIT :limit OFFSET :offset
                """), {"limit": limit, "offset": offset})
            rows = result.fetchall()
            return [_row_to_dict(row) for row in rows]
    except Exception as e:
        logger.warning(f"Failed to get all annotation results from PG: {e}")
        return []


async def get_annotation_result(content_id: str) -> Optional[dict]:
    """查询特定 content_id 的标注结果 (从 PostgreSQL)"""
    try:
        async with db_conn.async_session_factory() as session:
            result = await session.execute(sa_text("""
                SELECT * FROM annotation_records
                WHERE content_id = :cid
            """), {"cid": content_id})
            row = result.fetchone()
            if row:
                return _row_to_dict(row)
        return None
    except Exception as e:
        logger.warning(f"Failed to get annotation result from PG: {e}")
        return None


def _row_to_dict(row) -> dict:
    """将 SQLAlchemy Row 转为普通 dict, 处理 JSONB 字段"""
    import json as _json
    mapping = dict(row._mapping)
    # JSONB 字段在 asyncpg 中已经是 Python 对象, 无需额外处理
    # 但需要处理日期时间字段
    for key in ("annotated_at", "created_at"):
        val = mapping.get(key)
        if hasattr(val, "isoformat"):
            mapping[key] = val.isoformat()
    return mapping


async def trigger_manual_optimization(source_filter: str = "all") -> dict:
    """手动触发优化 (v3.2: 支持 source 过滤)"""
    try:
        from .optimization_agent import get_optimization_agent
        opt_agent = get_optimization_agent()
        report = await opt_agent.optimize(trigger="manual", source_filter=source_filter)
        if report:
            return {"optimized": True, "source_filter": source_filter, "report": report}
        else:
            stats = await get_annotation_stats()
            return {
                "optimized": False,
                "source_filter": source_filter,
                "reason": "优化未执行：无未消费的错误案例，或 LLM 分析不可用（详见后端日志）",
                "stats": stats,
            }
    except Exception as e:
        logger.error(f"Manual optimization failed: {e}")
        return {"optimized": False, "reason": str(e)}


async def get_optimization_reports(limit: int = 10) -> list:
    """获取优化报告列表"""
    try:
        svc = get_redis_service()
        if not svc.client:
            return []
        items = await svc.client.lrange(REPORTS_KEY, 0, limit - 1)
        return [json.loads(item) for item in items]
    except Exception as e:
        logger.warning(f"Failed to get optimization reports: {e}")
        return []


def _empty_stats() -> dict:
    return {
        "total_processed": 0,
        "total_errors": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "wrong_types": 0,
        "correct": 0,
        "last_annotation_time": "",
        "last_optimization_time": "",
        "buffer_size": 0,
        "threshold": BUFFER_THRESHOLD,       # 前端兼容字段
        "buffer_threshold": BUFFER_THRESHOLD,
        "last_optimization": 0,               # 前端兼容字段
        "queue_size": 0,
        "ready_to_optimize": False,
    }


# 全局单例
_consumer: Optional[AnnotationConsumer] = None


def get_annotation_consumer() -> AnnotationConsumer:
    global _consumer
    if _consumer is None:
        _consumer = AnnotationConsumer()
    return _consumer
