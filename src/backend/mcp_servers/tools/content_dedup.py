"""
内容去重工具 v1.0 — MD5 hash 查重

本地执行，通过 Redis 查询是否已有相同内容的审核记录。
用于:
  - 避免重复审核相同内容
  - 快速返回已知结果
  - 降低 API 调用成本
"""
import hashlib
import logging
from typing import Optional, Dict
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DedupResult(BaseModel):
    is_duplicate: bool
    content_hash: str
    original_content_id: Optional[str] = None
    original_decision: Optional[str] = None
    original_risk_score: Optional[float] = None
    cached: bool = False
    summary: str


class ContentDedupTool:
    """内容去重工具 — MD5 hash + Redis查重"""

    name = "content_dedup"
    description = "检查内容是否已审核过（MD5 hash → Redis查重，避免重复审核）"

    def __init__(self):
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            try:
                from memory.redis_service import get_redis_service
                self._redis = get_redis_service()
                await self._redis.connect()
            except Exception:
                logger.warning("Redis not available for content_dedup")
        return self._redis

    @staticmethod
    def hash_text(text: str) -> str:
        """计算文本 MD5 hash（标准化后）"""
        # 标准化: 去除多余空白，小写化
        normalized = " ".join(text.lower().split())
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    async def execute(self, text: str) -> DedupResult:
        """检查内容是否重复"""
        if not text:
            return DedupResult(is_duplicate=False, content_hash="", summary="空文本")

        content_hash = self.hash_text(text)

        try:
            redis = await self._get_redis()
            if redis:
                dup_id = await redis.check_duplicate(content_hash)
                if dup_id:
                    # 尝试获取原始审核结果
                    task_status = await redis.get_short_term(dup_id)
                    decision = task_status.get("final_decision") if task_status else None
                    risk_score = task_status.get("risk_score") if task_status else None

                    return DedupResult(
                        is_duplicate=True,
                        content_hash=content_hash,
                        original_content_id=dup_id,
                        original_decision=decision,
                        original_risk_score=risk_score,
                        cached=True,
                        summary=f"重复内容: 原始审核ID={dup_id}, 判定={decision}",
                    )
        except Exception as e:
            logger.warning(f"Redis dedup check failed: {e}")

        return DedupResult(
            is_duplicate=False,
            content_hash=content_hash,
            summary=f"新内容 (hash={content_hash[:12]}...)",
        )
