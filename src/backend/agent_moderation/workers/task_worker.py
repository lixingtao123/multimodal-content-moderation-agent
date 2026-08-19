"""
异步任务 Worker 池 — 后台消费审核任务队列

架构参考 AnnotationConsumer (BRPOP + asyncio.Task)：
  - Redis List 作为任务队列 (moderation:task:queue)
  - Redis Hash 存储任务状态 (task:status:{task_id})
  - asyncio.Semaphore 控制并发数 (默认 3, 受 LLM API 限流约束)

生命周期：
  在 main.py lifespan 中启动/停止, 与 AnnotationConsumer 共存
"""
import asyncio
import json
import logging
import time
from typing import Optional

from memory.redis_service import get_redis_service
from db import connection as db_conn

logger = logging.getLogger(__name__)

# Redis Key 常量
TASK_QUEUE_KEY = "moderation:task:queue"       # List (RPUSH/LPOP)
TASK_STATUS_PREFIX = "task:status:"             # Hash: {task_id}
TASK_RESULT_PREFIX = "task:result:"             # Hash: {task_id}
TASK_LIST_KEY = "moderation:task:list"          # Sorted Set (按时间排序)
TASK_STATUS_TTL = 86400                         # 24h


class TaskWorkerPool:
    """异步审核任务工作池"""

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running = False
        self._workers: list[asyncio.Task] = []

    async def start(self):
        """启动 Worker Pool — 创建 max_concurrent 个并发 worker"""
        if self._running:
            return
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker_loop(i))
            for i in range(self.max_concurrent)
        ]
        logger.info(f"[TaskWorkerPool] Started with {self.max_concurrent} workers")

    async def stop(self):
        """停止所有 workers"""
        self._running = False
        for w in self._workers:
            if not w.done():
                w.cancel()
        # 等待所有 worker 优雅退出
        results = await asyncio.gather(*self._workers, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
                logger.warning(f"[TaskWorkerPool] Worker error during shutdown: {r}")
        self._workers.clear()
        logger.info("[TaskWorkerPool] Stopped")

    async def _worker_loop(self, worker_id: int):
        """单个 worker 的主循环"""
        svc = get_redis_service()
        logger.info(f"[TaskWorkerPool] Worker-{worker_id} ready")

        while self._running:
            try:
                # 阻塞命令用专用长连接（无 socket_timeout），避免 BLPOP 阻塞期间
                # 触发全局连接 socket_timeout=2.0 的读超时（R20 修复）
                client = svc.get_blocking_client()
                if client is None:
                    await asyncio.sleep(1)
                    continue

                # LPOP 非阻塞取任务, 超时 2s 后检查 _running
                result = await client.blpop(TASK_QUEUE_KEY, timeout=2)
                if result is None:
                    continue

                _, task_data = result
                task = json.loads(task_data) if isinstance(task_data, (str, bytes)) else task_data
                task_id = task.get("task_id", "unknown")

                # 使用信号量控制并发
                async with self._semaphore:
                    await self._execute_task(task, task_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TaskWorkerPool] Worker-{worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(0.5)

    async def _execute_task(self, task: dict, task_id: str):
        """执行单个审核任务"""
        svc = get_redis_service()
        start_time = time.time()

        try:
            # 更新状态 → PROCESSING
            await self._update_status(task_id, {
                "status": "PROCESSING",
                "progress": "0.0",
                "current_step": "initializing",
            })

            # 导入审核核心逻辑 (延迟导入避免循环依赖)
            from api.routes.moderation import _run_moderation_core

            content_type = task.get("content_type", "text")
            content = task.get("content", {})
            account_id = task.get("account_id")

            # 处理文件内容 (bytes → 保持原样)
            if "files" in content:
                for f in content["files"]:
                    if isinstance(f.get("content"), str):
                        # base64 编码的文件内容需要解码
                        import base64
                        try:
                            f["content"] = base64.b64decode(f["content"])
                        except Exception:
                            pass  # 可能不是 base64, 保持原样

            logger.info(f"[TaskWorkerPool] Executing task {task_id} ({content_type})")

            # 执行审核工作流
            result = await _run_moderation_core(
                content_type=content_type,
                content=content,
                account_id=account_id,
                task_id=task_id,
                progress_callback=lambda step, pct: self._update_status(task_id, {
                    "current_step": step,
                    "progress": str(round(pct, 2)),
                }),
            )

            elapsed = (time.time() - start_time) * 1000

            # v3.6: 保存 Pipeline 日志 + 打印完成横幅
            try:
                from common.logger import save_all, get_pipeline
                save_all()
            except Exception:
                pass

            # 存储结果到 Redis
            result_data = {
                "status": "COMPLETED",
                "progress": "1.0",
                "final_decision": result.get("final_decision", "UNKNOWN"),
                "risk_score": str(result.get("risk_score", 0.0)),
                "violation_types": json.dumps(result.get("violation_types", []), ensure_ascii=False),
                "processing_time_ms": str(round(elapsed, 1)),
                "content_preview": str(task.get("content_preview", ""))[:200],
            }

            # 存储 agent_reasoning (如有)
            if result.get("agent_reasoning"):
                result_data["agent_reasoning"] = json.dumps(result["agent_reasoning"], ensure_ascii=False)
            if result.get("debate_info"):
                result_data["debate_info"] = json.dumps(result["debate_info"], ensure_ascii=False)

            await self._update_status(task_id, result_data)

            # 同步写入 task:result:{task_id}
            if svc.client:
                await svc.client.hset(f"{TASK_RESULT_PREFIX}{task_id}", mapping=result_data)
                await svc.client.expire(f"{TASK_RESULT_PREFIX}{task_id}", TASK_STATUS_TTL)

            # 添加到任务列表 Sorted Set (按时间排序)
            if svc.client:
                await svc.client.zadd(TASK_LIST_KEY, {task_id: time.time()})
                await svc.client.expire(TASK_LIST_KEY, TASK_STATUS_TTL)

            logger.info(f"[TaskWorkerPool] Task {task_id} completed: "
                        f"{result.get('final_decision')} (risk={result.get('risk_score', 0):.2f}, "
                        f"{elapsed:.0f}ms)")

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            error_msg = f"{type(e).__name__}: {str(e)[:500]}"
            logger.error(f"[TaskWorkerPool] Task {task_id} FAILED after {elapsed:.0f}ms: {error_msg}")

            # v3.6: 失败时也保存 Pipeline 日志
            try:
                from common.logger import save_all
                save_all()
            except Exception:
                pass

            await self._update_status(task_id, {
                "status": "FAILED",
                "progress": "1.0",
                "error_message": error_msg,
                "processing_time_ms": str(round(elapsed, 1)),
            })

            # 同时写入 PostgreSQL (标记失败)
            try:
                from sqlalchemy import text
                async with db_conn.async_session_factory() as session:
                    await session.execute(text("""
                        UPDATE moderation_records
                        SET status = 'FAILED', error_message = :err, progress = 1.0,
                            processing_time_ms = :ptime, updated_at = NOW()
                        WHERE content_id = :cid
                    """), {"err": error_msg[:500], "ptime": elapsed, "cid": task_id})
                    await session.commit()
            except Exception as db_err:
                logger.warning(f"[TaskWorkerPool] Failed to save error to PG: {db_err}")

    # ========== 公开 API ==========

    @staticmethod
    async def submit(content_type: str, content: dict, account_id: Optional[str] = None,
                     content_preview: str = "") -> str:
        """
        提交异步审核任务
        返回 task_id, 任务立即入队, 不阻塞
        """
        import uuid

        task_id = f"task_{uuid.uuid4().hex[:16]}"
        svc = get_redis_service()

        # 构建任务数据
        task_data = {
            "task_id": task_id,
            "content_type": content_type,
            "content": content,
            "account_id": account_id,
            "content_preview": content_preview,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        # 序列化文件内容 (bytes → base64)
        if "files" in content:
            import base64
            serialized_files = []
            for f in content.get("files", []):
                sf = dict(f)
                if isinstance(sf.get("content"), bytes):
                    sf["content"] = base64.b64encode(sf["content"]).decode("ascii")
                serialized_files.append(sf)
            task_data["content"] = {**content, "files": serialized_files}

        # 写入状态 → QUEUED
        status_data = {
            "status": "QUEUED",
            "progress": "0.0",
            "current_step": "",
            "content_type": content_type,
            "content_preview": content_preview[:200],
            "created_at": task_data["created_at"],
        }
        if svc.client:
            await svc.client.hset(f"{TASK_STATUS_PREFIX}{task_id}", mapping=status_data)
            await svc.client.expire(f"{TASK_STATUS_PREFIX}{task_id}", TASK_STATUS_TTL)

        # 入队 (RPUSH)
        if svc.client:
            await svc.client.rpush(TASK_QUEUE_KEY, json.dumps(task_data, ensure_ascii=False))

        logger.info(f"[TaskWorkerPool] Task {task_id} submitted ({content_type}), queue depth ~{await svc.client.llen(TASK_QUEUE_KEY) if svc.client else '?'}")
        return task_id

    @staticmethod
    async def get_status(task_id: str) -> Optional[dict]:
        """查询任务状态 (Redis 优先)"""
        svc = get_redis_service()
        if not svc.client:
            return None

        status_key = f"{TASK_STATUS_PREFIX}{task_id}"
        data = await svc.client.hgetall(status_key)
        if not data:
            # 尝试从 result key 获取
            result_key = f"{TASK_RESULT_PREFIX}{task_id}"
            data = await svc.client.hgetall(result_key)

        if not data:
            # PostgreSQL 兜底
            try:
                from sqlalchemy import text
                async with db_conn.async_session_factory() as session:
                    row = await session.execute(text("""
                        SELECT content_id, status, progress, final_decision, risk_score,
                               violation_types, processing_time_ms, content_type, content_preview,
                               created_at, error_message
                        FROM moderation_records
                        WHERE content_id = :cid
                    """), {"cid": task_id})
                    r = row.fetchone()
                    if r:
                        import json as _json
                        return {
                            "task_id": r.content_id,
                            "status": r.status or "COMPLETED",
                            "progress": r.progress or 1.0,
                            "content_type": r.content_type,
                            "content_preview": r.content_preview or "",
                            "created_at": r.created_at.isoformat() if r.created_at else "",
                            "final_decision": r.final_decision,
                            "risk_score": r.risk_score,
                            "violation_types": r.violation_types if isinstance(r.violation_types, list) else [],
                            "processing_time_ms": r.processing_time_ms,
                            "error_message": r.error_message,
                        }
            except Exception as e:
                logger.warning(f"[TaskWorkerPool] PG fallback failed for {task_id}: {e}")
            return None

        # 反序列化 Redis 数据
        result = {"task_id": task_id}
        for k, v in data.items():
            k_str = k.decode() if isinstance(k, bytes) else k
            v_str = v.decode() if isinstance(v, bytes) else v
            if k_str in ("violation_types", "suggestions"):
                try:
                    result[k_str] = json.loads(v_str)
                except (json.JSONDecodeError, TypeError):
                    result[k_str] = v_str
            elif k_str in ("risk_score", "progress", "processing_time_ms"):
                try:
                    result[k_str] = float(v_str)
                except (ValueError, TypeError):
                    result[k_str] = v_str
            elif k_str in ("agent_reasoning", "debate_info", "violation_details"):
                try:
                    result[k_str] = json.loads(v_str)
                except (json.JSONDecodeError, TypeError):
                    result[k_str] = v_str
            else:
                result[k_str] = v_str
        return result

    @staticmethod
    async def list_tasks(limit: int = 50, status_filter: str = "all") -> dict:
        """列出最近的任务 (Redis 优先, PostgreSQL 补充)"""
        svc = get_redis_service()
        tasks = {}
        now = time.time()

        # 1. 从 Redis Sorted Set 获取最近的 task_id
        if svc.client:
            try:
                task_ids = await svc.client.zrevrangebyscore(
                    TASK_LIST_KEY, now + 86400, 0,
                    start=0, num=limit
                )
            except Exception:
                task_ids = []

            # 获取每个任务的状态
            for tid in task_ids:
                tid_str = tid.decode() if isinstance(tid, bytes) else tid
                status = await TaskWorkerPool.get_status(tid_str)
                if status:
                    if status_filter == "all" or status.get("status") == status_filter:
                        tasks[tid_str] = status

        # 2. 从 PostgreSQL 补充
        if len(tasks) < limit:
            try:
                from sqlalchemy import text
                async with db_conn.async_session_factory() as session:
                    where = ""
                    params = {"limit": limit - len(tasks)}
                    if status_filter != "all":
                        where = "WHERE status = :status_filter"
                        params["status_filter"] = status_filter

                    rows = await session.execute(text(f"""
                        SELECT content_id, status, progress, final_decision, risk_score,
                               violation_types, processing_time_ms, content_type, content_preview,
                               created_at, error_message
                        FROM moderation_records
                        {where}
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """), params)

                    for row in rows.fetchall():
                        cid = row.content_id
                        if cid not in tasks:
                            tasks[cid] = {
                                "task_id": cid,
                                "status": row.status or "COMPLETED",
                                "progress": row.progress or 1.0,
                                "content_type": row.content_type,
                                "content_preview": row.content_preview or "",
                                "created_at": row.created_at.isoformat() if row.created_at else "",
                                "final_decision": row.final_decision,
                                "risk_score": row.risk_score,
                                "violation_types": row.violation_types if isinstance(row.violation_types, list) else [],
                                "processing_time_ms": row.processing_time_ms,
                                "error_message": row.error_message,
                            }
            except Exception as e:
                logger.warning(f"[TaskWorkerPool] PG list fallback failed: {e}")

        items = sorted(tasks.values(), key=lambda x: x.get("created_at", ""), reverse=True)
        return {"total": len(items), "items": items[:limit]}

    @staticmethod
    async def cancel_task(task_id: str) -> bool:
        """取消一个排队中的任务"""
        svc = get_redis_service()
        if not svc.client:
            return False

        status = await TaskWorkerPool.get_status(task_id)
        if status and status.get("status") == "QUEUED":
            # 从队列中移除 (需要扫描 Redis List, 成本较高, 用状态标记代替)
            await svc.client.hset(f"{TASK_STATUS_PREFIX}{task_id}", "status", "CANCELLED")
            logger.info(f"[TaskWorkerPool] Task {task_id} cancelled")
            return True
        return False

    # ========== 内部方法 ==========

    @staticmethod
    async def _update_status(task_id: str, updates: dict):
        """更新 Redis 任务状态"""
        svc = get_redis_service()
        if svc.client:
            key = f"{TASK_STATUS_PREFIX}{task_id}"
            await svc.client.hset(key, mapping=updates)
            await svc.client.expire(key, TASK_STATUS_TTL)


# 全局单例
_pool: Optional[TaskWorkerPool] = None


def get_task_worker_pool(max_concurrent: int = 3) -> TaskWorkerPool:
    global _pool
    if _pool is None:
        _pool = TaskWorkerPool(max_concurrent=max_concurrent)
    return _pool
