"""
数据库连接管理 — async SQLAlchemy + asyncpg
"""
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from sqlalchemy import text as sa_text
from common.config import get_settings
from db.models import Base

logger = logging.getLogger(__name__)

engine = None
async_session_factory = None

# schema.sql 相对 src/backend 的路径（运行入口在 src/backend）
_SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "schema.sql"


async def _apply_schema_sql(conn):
    """幂等执行 schema.sql（CREATE TABLE/INDEX IF NOT EXISTS），
    保证 moderation_policies/core_memories/annotation_records/dataset_samples
    等不在 ORM create_all 覆盖范围的表在非 Docker 部署下也被创建。

    R22: 统一 schema 源。先执行 schema.sql，再 create_all（checkfirst 跳过已存在表）。
    """
    if not _SCHEMA_SQL_PATH.exists():
        logger.warning(f"[DB] schema.sql not found at {_SCHEMA_SQL_PATH}, skip")
        return
    sql_text = _SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    # 按分号切分；剥离 `--` 注释（含整行注释），避免注释中的冒号被
    # SQLAlchemy 误解析为 bind 参数（如 "-- keyword: {...}"）
    statements = []
    buf = []
    for line in sql_text.splitlines():
        code = line.split("--", 1)[0].rstrip()
        if not code.strip():
            continue
        buf.append(code)
        if ";" in code:
            statements.append("\n".join(buf))
            buf = []
    if buf:
        statements.append("\n".join(buf))

    executed = 0
    for stmt in statements:
        cleaned = stmt.strip().rstrip(";").strip()
        if not cleaned or cleaned == "--":
            continue
        try:
            await conn.execute(sa_text(stmt))
            executed += 1
        except Exception as e:
            # 幂等：单个语句失败不阻断后续（例如已存在的旧列），记录为 warning
            logger.warning(f"[DB] schema.sql statement failed (skip): {str(e)[:120]}")
    logger.info(f"[DB] schema.sql applied: {executed} statements executed")


async def init_db():
    """初始化数据库连接池 + 自动建表（R3·L3：幂等；R22: 统一执行 schema.sql + create_all）"""
    global engine, async_session_factory
    settings = get_settings()

    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
    )
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    # R22: 先执行 schema.sql（幂等），保证 schema.sql 中定义的表/列全部存在
    async with engine.begin() as conn:
        await _apply_schema_sql(conn)
        # R3·L3 (F4 修复): create_all 默认 checkfirst=True，已有表跳过，幂等。
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def close_db():
    """关闭数据库连接"""
    global engine
    if engine:
        await engine.dispose()


async def get_session() -> AsyncSession:
    """获取数据库会话（用于依赖注入）"""
    if async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with async_session_factory() as session:
        yield session


def get_session_factory():
    """获取当前 session factory（解决 import-time None 问题）"""
    if async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return async_session_factory
