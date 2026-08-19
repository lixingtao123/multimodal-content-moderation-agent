"""
分层记忆管理器 — 协调 3 层记忆（Redis 短期 + Redis 工作队列 + ChromaDB 长期）
"""
import hashlib
import time
from typing import Optional, Any
from .redis_service import get_redis_service
from .chroma_service import get_chroma_service


class MemoryManager:
    """分层记忆管理器"""

    def __init__(self):
        self.redis = get_redis_service()
        self.chroma = get_chroma_service()

    async def connect_all(self):
        """连接所有记忆层"""
        await self.redis.connect()
        await self.chroma.connect()

    async def disconnect_all(self):
        """断开所有记忆层"""
        await self.redis.disconnect()

    # ========== 短期记忆 ==========
    async def start_task(self, content_id: str, content_type: str, content_preview: str = ""):
        """记录任务开始"""
        await self.redis.save_short_term(content_id, {
            "status": "STARTED",
            "content_type": content_type,
            "content_preview": content_preview,
            "start_time": time.time(),
        })

    async def update_task_step(self, content_id: str, step: str):
        """更新当前执行步骤"""
        await self.redis.update_short_term(content_id, {
            "current_step": step,
            "step_time": time.time(),
        })

    async def complete_task(self, content_id: str, result: dict):
        """标记任务完成"""
        await self.redis.update_short_term(content_id, {
            "status": "COMPLETED",
            "final_decision": result.get("final_decision", ""),
            "risk_score": result.get("overall_score", 0.0),
            "end_time": time.time(),
        })

    async def get_task_status(self, content_id: str) -> Optional[dict]:
        """查询任务状态"""
        return await self.redis.get_short_term(content_id)

    # ========== LLM 缓存 ==========
    @staticmethod
    def hash_prompt(prompt: str) -> str:
        """生成 prompt 的 MD5 hash"""
        return hashlib.md5(prompt.encode("utf-8")).hexdigest()

    async def get_cached_llm_result(self, prompt: str) -> Optional[Any]:
        """获取缓存的 LLM 结果"""
        prompt_hash = self.hash_prompt(prompt)
        return await self.redis.get_cached_llm_response(prompt_hash)

    async def cache_llm_result(self, prompt: str, result: Any):
        """缓存 LLM 结果"""
        prompt_hash = self.hash_prompt(prompt)
        await self.redis.cache_llm_response(prompt_hash, result)

    # ========== 内容去重 ==========
    @staticmethod
    def hash_content(content: str) -> str:
        """生成内容的 MD5 hash"""
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    async def check_duplicate_content(self, content: str) -> Optional[str]:
        """检查是否已审核过相同内容"""
        content_hash = self.hash_content(content)
        return await self.redis.check_duplicate(content_hash)

    async def mark_content_processed(self, content: str, content_id: str):
        """标记内容已审核"""
        content_hash = self.hash_content(content)
        await self.redis.mark_processed(content_hash, content_id)

    # ========== 长期记忆 ==========
    async def save_case(self, case_id: str, content: str, violation_type: str, decision: str,
                       confidence: float = 0.0, risk_score: float = 0.0,
                       is_adversarial: bool = False, frequency: int = 0):
        """
        保存审核案例到 ChromaDB (v3.1 增强: 重要性评分分层存储)

        基于 AgentMemory 的 ImportanceCalculator:
        - 高重要性 (>0.7) → core_memory collection (长期保留)
        - 低重要性 (≤0.7) → moderation_cases collection (常规存储)
        """
        from memory.agent_memory import ImportanceCalculator

        importance = ImportanceCalculator.calculate(
            violation_type=violation_type,
            confidence=confidence,
            risk_score=risk_score,
            is_adversarial=is_adversarial,
            frequency=frequency,
        )

        # 根据重要性路由到不同 collection
        if importance > 0.7:
            await self.chroma.add_core_case(case_id, content, violation_type, decision, importance)
        else:
            await self.chroma.add_case(case_id, content, violation_type, decision)

        return importance

    async def search_similar_cases(self, query: str, top_k: int = 5):
        """检索相似历史案例 (优先 core_memory)"""
        return await self.chroma.search_similar(query, top_k)

    # ========== 任务队列 ==========
    async def enqueue_task(self, content_id: str, priority: float = 1.0):
        """任务入队"""
        await self.redis.add_task_queue(content_id, priority)

    async def dequeue_tasks(self, count: int = 10) -> list:
        """取出下一批任务"""
        return await self.redis.get_next_tasks(count)

    async def remove_task(self, content_id: str):
        """移除已完成任务"""
        await self.redis.remove_task(content_id)


# 全局单例
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
