"""
Redis 服务 — 短期记忆 + 任务队列 + LLM 缓存

容错设计（R19·真实评测修复）:
  - 惰性连接: 方法调用时才尝试 connect（此前需显式 connect，直调 workflow 时 client 为 None 导致崩溃）
  - 不可用降级: Redis 连不上时所有方法安全短路（getter 返回 None/[]，setter 静默跳过），
    主审核流程不被外部依赖阻塞。语义上 = 缓存未命中 / 去重未命中 / 监控不记录。
"""
import json
import logging
import time
from typing import Optional, Any
from datetime import timedelta
import redis.asyncio as aioredis
from common.config import get_settings

logger = logging.getLogger(__name__)


class RedisService:
    """Redis 短期记忆 & 任务队列服务（带不可用降级）"""

    def __init__(self):
        settings = get_settings()
        self.client: Optional[aioredis.Redis] = None
        self._blocking_client: Optional[aioredis.Redis] = None
        self.url = settings.redis_url
        self._connect_attempted = False

    async def connect(self):
        """显式连接（保持向后兼容），失败时降级为不可用"""
        await self._ensure()

    async def disconnect(self):
        if self.client:
            try:
                await self.client.close()
            except Exception:
                pass
        self.client = None
        self._connect_attempted = False
        if self._blocking_client:
            try:
                await self._blocking_client.close()
            except Exception:
                pass
        self._blocking_client = None

    def get_blocking_client(self) -> Optional[aioredis.Redis]:
        """
        阻塞命令专用连接（无 socket_timeout）。

        BRPOP/BLPOP 是阻塞命令：服务端会等待最长 timeout 秒再返回空。
        若复用全局连接（socket_timeout=2.0），阻塞期间 socket 读超时
        会提前抛 TimeoutError（见 R20 修复：annotation/task worker 高频刷错）。
        此处取消读超时，语义 = 一直等到有数据为止。连接超时仍保留。
        """
        if self._blocking_client is not None:
            return self._blocking_client
        try:
            self._blocking_client = aioredis.from_url(
                self.url, decode_responses=True,
                socket_connect_timeout=1.0,  # 仅连接超时，读超时取消
            )
        except Exception as e:
            logger.warning(f"[RedisService] 阻塞连接创建失败: {e}")
            return None
        return self._blocking_client

    async def _ensure(self) -> bool:
        """惰性连接。返回 True=Redis 可用，False=降级。只尝试连接一次。"""
        if self.client is not None:
            return True
        if self._connect_attempted:
            return False
        self._connect_attempted = True
        try:
            self.client = aioredis.from_url(
                self.url, decode_responses=True,
                socket_connect_timeout=1.0, socket_timeout=2.0,
            )
            await self.client.ping()
            return True
        except Exception as e:
            logger.warning(f"[RedisService] Redis 不可用，降级为内存模式: {e}")
            self.client = None
            return False

    # ========== 短期记忆（TTL 1h）==========
    async def save_short_term(self, content_id: str, data: dict, ttl: int = 3600):
        """保存短期记忆 Hash"""
        if not await self._ensure():
            return
        key = f"short_term:{content_id}"
        await self.client.hset(key, mapping={k: json.dumps(v) for k, v in data.items()})
        await self.client.expire(key, timedelta(seconds=ttl))

    async def get_short_term(self, content_id: str) -> Optional[dict]:
        """获取短期记忆"""
        if not await self._ensure():
            return None
        key = f"short_term:{content_id}"
        data = await self.client.hgetall(key)
        if data:
            return {k: json.loads(v) for k, v in data.items()}
        return None

    async def update_short_term(self, content_id: str, updates: dict):
        """更新短期记忆中的字段"""
        if not await self._ensure():
            return
        key = f"short_term:{content_id}"
        for k, v in updates.items():
            await self.client.hset(key, k, json.dumps(v))

    # ========== 任务队列（TTL 24h）==========
    async def add_task_queue(self, content_id: str, priority: float = 1.0):
        """添加任务到 Sorted Set，按优先级排序"""
        if not await self._ensure():
            return
        score = priority * (time.time() / 1000)
        await self.client.zadd("task_queue", {content_id: score})
        await self.client.expire("task_queue", timedelta(hours=24))

    async def get_next_tasks(self, count: int = 10) -> list:
        """获取下一批任务（优先级从高到低）"""
        if not await self._ensure():
            return []
        tasks = await self.client.zrevrange("task_queue", 0, count - 1)
        return tasks

    async def remove_task(self, content_id: str):
        """从队列中移除已完成的任务"""
        if not await self._ensure():
            return
        await self.client.zrem("task_queue", content_id)

    # ========== LLM 响应缓存 ==========
    async def cache_llm_response(self, prompt_hash: str, response: Any, ttl: int = 3600):
        """缓存 LLM 响应，减少重复 API 调用"""
        if not await self._ensure():
            return
        key = f"cache:llm:{prompt_hash}"
        await self.client.setex(key, ttl, json.dumps(response))

    async def get_cached_llm_response(self, prompt_hash: str) -> Optional[Any]:
        """获取缓存的 LLM 响应"""
        if not await self._ensure():
            return None
        key = f"cache:llm:{prompt_hash}"
        cached = await self.client.get(key)
        return json.loads(cached) if cached else None

    # ========== 内容去重 ==========
    async def check_duplicate(self, content_hash: str) -> Optional[str]:
        """检查内容是否已审核过，返回 content_id 或 None"""
        if not await self._ensure():
            return None
        key = f"dedup:{content_hash}"
        return await self.client.get(key)

    async def mark_processed(self, content_hash: str, content_id: str, ttl: int = 3600):
        """标记内容已处理"""
        if not await self._ensure():
            return
        key = f"dedup:{content_hash}"
        await self.client.setex(key, ttl, content_id)


# 全局单例
_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
