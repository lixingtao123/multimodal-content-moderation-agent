"""
内容风控智能治理系统 — FastAPI 主入口
"""
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.config import get_settings
from api.routes import moderation, query, admin, logs, evaluation, async_moderation
from api.websocket import router as ws_router
from db.connection import init_db, close_db
from memory.manager import get_memory_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    settings = get_settings()
    logger.info(f"Starting Content Moderation System (env={settings.environment})")
    await init_db()

    # 初始化分层记忆（Redis + ChromaDB）
    memory = get_memory_manager()
    await memory.connect_all()
    logger.info("Memory manager initialized (Redis + ChromaDB)")

    # v3.6: 恢复 GraphRAG 图谱状态
    try:
        from memory.graph_rag import get_graph_rag
        graph_rag = get_graph_rag()
        await graph_rag.load()
        logger.info("GraphRAG state restored")
    except Exception as e:
        logger.warning(f"GraphRAG load failed (non-blocking): {e}")

    # v3.6: 自动导入种子数据 (如果 ChromaDB 为空)
    try:
        import chromadb
        c = chromadb.PersistentClient(path="/workspace/data/chroma")
        try:
            coll = c.get_collection("moderation_cases_v2")
            if coll.count() == 0:
                logger.info("ChromaDB is empty, auto-importing seed data...")
                from scripts.seed_rag_data import import_to_chromadb
                import_to_chromadb(clear_first=False)
                logger.info("Seed data auto-import complete")
        except Exception:
            logger.info("ChromaDB collection not found, will be created on first use")
    except Exception as e:
        logger.warning(f"Seed data check failed (non-blocking): {e}")

    # v2: 启动 AnnotationAgent 后台消费者
    try:
        from optimization.annotation_queue import get_annotation_consumer
        consumer = get_annotation_consumer()
        await consumer.start()
        logger.info("AnnotationConsumer started")
    except Exception as e:
        logger.warning(f"AnnotationConsumer start failed (non-blocking): {e}")

    # v3.3: 启动异步审核 TaskWorkerPool
    try:
        from agent_moderation.workers.task_worker import get_task_worker_pool
        pool = get_task_worker_pool(max_concurrent=3)
        await pool.start()
        logger.info("TaskWorkerPool started (max_concurrent=3)")
    except Exception as e:
        logger.warning(f"TaskWorkerPool start failed (non-blocking): {e}")

    yield

    # v3.3: 停止 TaskWorkerPool
    try:
        from agent_moderation.workers.task_worker import get_task_worker_pool
        pool = get_task_worker_pool()
        await pool.stop()
        logger.info("TaskWorkerPool stopped")
    except Exception:
        pass

    # v2: 停止消费者
    try:
        from optimization.annotation_queue import get_annotation_consumer
        consumer = get_annotation_consumer()
        await consumer.stop()
        logger.info("AnnotationConsumer stopped")
    except Exception:
        pass

    await memory.disconnect_all()
    await close_db()
    logger.info("Shutting down Content Moderation System")


app = FastAPI(
    title="内容风控智能治理系统",
    description="Multi-Agent 多模态内容审核平台",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由 (注意: 异步路由必须在 query 之前注册, 避免 /moderate/tasks 被 /moderate/{content_id} 拦截)
app.include_router(moderation.router)
app.include_router(async_moderation.router)
app.include_router(query.router)
app.include_router(admin.router)
app.include_router(logs.router)
app.include_router(evaluation.router)
from api.routes import policies
app.include_router(policies.router)
from api.routes import tech
app.include_router(tech.router)
from api.routes import mcp as mcp_routes
app.include_router(mcp_routes.router)
app.include_router(ws_router)


@app.get("/health")
async def health_check():
    """健康检查 — 验证所有依赖服务连通性"""
    import redis.asyncio as aioredis
    import chromadb
    import httpx

    status = {
        "status": "ok",
        "dependencies": {
            "postgres": True,
            "redis": True,
            "chromadb": True,
            "funasr": True,
        },
    }

    # Redis
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.close()
    except Exception as e:
        status["dependencies"]["redis"] = False
        status["status"] = "degraded"
        logger.warning(f"Redis health check failed: {e}")

    # ChromaDB（内嵌模式）
    try:
        c = chromadb.PersistentClient(path="/workspace/data/chroma")
        c.heartbeat()
    except Exception as e:
        status["dependencies"]["chromadb"] = False
        status["status"] = "degraded"
        logger.warning(f"ChromaDB health check failed: {e}")

    # FunASR
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.funasr_url}/health", timeout=5.0)
            if resp.status_code != 200:
                raise Exception(f"FunASR returned {resp.status_code}")
    except Exception as e:
        status["dependencies"]["funasr"] = False
        status["status"] = "degraded"
        logger.warning(f"FunASR health check failed: {e}")

    return status


if __name__ == "__main__":
    import os

    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0",
                port=int(os.environ.get("BACKEND_PORT", "18080")), reload=True)
