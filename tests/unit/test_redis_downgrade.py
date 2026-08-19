"""
RedisService 不可用降级测试（R19·真实评测修复）

验证：无 Redis 环境下（client 未连接/连接失败）所有方法安全短路，
不抛异常，不阻塞主审核流程。
"""
import asyncio

import pytest

from memory.redis_service import RedisService


@pytest.fixture
def svc(monkeypatch) -> RedisService:
    """构造 Redis 连接失败的实例（模拟不可达，进入降级路径）"""
    s = RedisService()
    # 强制未连接状态
    s.client = None
    s._connect_attempted = False

    def _fake_from_url(*args, **kwargs):
        raise ConnectionError("redis unavailable (simulated)")

    monkeypatch.setattr("memory.redis_service.aioredis.from_url", _fake_from_url)
    return s


@pytest.mark.asyncio
async def test_save_short_term_downgrade_no_raise(svc):
    """setter 在 Redis 不可用时静默跳过，不抛异常"""
    await svc.save_short_term("c1", {"status": "STARTED"})
    await svc.update_short_term("c1", {"step": "x"})


@pytest.mark.asyncio
async def test_get_short_term_downgrade_returns_none(svc):
    """getter 在 Redis 不可用时返回 None"""
    assert await svc.get_short_term("c1") is None


@pytest.mark.asyncio
async def test_queue_downgrade(svc):
    """任务队列降级：入队不抛，取出为空"""
    await svc.add_task_queue("c1")
    assert await svc.get_next_tasks() == []
    await svc.remove_task("c1")


@pytest.mark.asyncio
async def test_llm_cache_downgrade(svc):
    """LLM 缓存降级：写不抛，读返回 None（缓存未命中语义）"""
    await svc.cache_llm_response("h1", {"x": 1})
    assert await svc.get_cached_llm_response("h1") is None


@pytest.mark.asyncio
async def test_dedup_downgrade(svc):
    """去重降级：标记不抛，查询返回 None（当作未审核过）"""
    await svc.mark_processed("abc", "c1")
    assert await svc.check_duplicate("abc") is None


@pytest.mark.asyncio
async def test_memory_manager_survives_no_redis(monkeypatch):
    """MemoryManager 在无 Redis 时全部操作不抛异常（真实评测场景）"""
    from memory.manager import MemoryManager

    def _fake_from_url(*args, **kwargs):
        raise ConnectionError("redis unavailable (simulated)")

    monkeypatch.setattr("memory.redis_service.aioredis.from_url", _fake_from_url)

    m = MemoryManager()
    # 注入一个连接必失败的降级实例（全局单例在真实环境可能连上真实 Redis）
    from memory.redis_service import RedisService
    svc = RedisService()
    m.redis = svc
    assert await m.redis._ensure() is False  # 确认确实进入降级

    await m.start_task("c1", "text", "preview")
    await m.update_task_step("c1", "supervisor")
    await m.complete_task("c1", {"final_decision": "PASS", "overall_score": 0.1})
    assert await m.get_task_status("c1") is None
    assert await m.get_cached_llm_result("prompt") is None
    assert await m.check_duplicate_content("content") is None
    await m.enqueue_task("c1")
    assert await m.dequeue_tasks() == []
