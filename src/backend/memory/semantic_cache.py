"""
语义缓存（R11·M2）— 嵌入相似度 ≥ 阈值命中，意思一样也复用

对比现状（manager.get_cached_llm_result 精确 hash 缓存）：语义缓存能命中
"意思相同但表述不同"的查询。

安全约束（重要）：
- 违规结果不缓存（is_violation=True 拒绝写入）——违规判定绝不能因缓存复用而漏判
- 短 TTL，避免过期判断滞留

存储：内存 dict（无 docker Redis 时的可运行实现；Redis 版后续接 redis_service）。
"""
import logging
import time
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.95
DEFAULT_TTL = 3600  # 1 小时


class SemanticCache:
    """语义缓存：嵌入相似度命中 + 违规结果不缓存 + TTL"""

    def __init__(self, embed_fn: Optional[Any] = None, threshold: float = DEFAULT_THRESHOLD,
                 max_entries: int = 1000, ttl: float = DEFAULT_TTL):
        self._embed_fn = embed_fn
        self._threshold = threshold
        self._max_entries = max_entries
        self._ttl = ttl
        self._entries: dict = {}  # text -> {result, emb, ts}
        self._embed_ok = True

    # ------------------------------------------------------------
    # 嵌入
    # ------------------------------------------------------------
    def _get_embed(self):
        if self._embed_fn is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embed_fn = SentenceTransformer("BAAI/bge-small-zh-v1.5")
            except Exception as e:
                if self._embed_ok:
                    logger.warning(f"[semantic_cache] bge 加载失败，缓存降级为精确匹配: {e}")
                self._embed_ok = False
                self._embed_fn = None
        return self._embed_fn

    def _embed(self, text: str) -> Optional[np.ndarray]:
        embed = self._get_embed()
        if embed is None:
            return None
        try:
            return np.asarray(embed.encode([text], normalize_embeddings=True)[0], dtype=np.float32)
        except Exception:
            return None

    @staticmethod
    def _similarity(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))

    # ------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------
    def get(self, text: str):
        """语义检索命中返回 (True, result)；否则 (False, None)。

        嵌入不可用时退化：仅做精确匹配（文本相等）。
        """
        now = time.time()
        # 先精确命中
        entry = self._entries.get(text)
        if entry and now - entry["ts"] < self._ttl:
            return True, entry["result"]

        emb = self._embed(text)
        if emb is None:
            return False, None  # 无嵌入 → 无法语义匹配

        best = None
        best_sim = self._threshold
        for cached_text, e in self._entries.items():
            if now - e["ts"] >= self._ttl:
                continue
            if e.get("emb") is None:
                continue
            sim = self._similarity(emb, e["emb"])
            if sim >= best_sim:
                best_sim = sim
                best = cached_text
        if best is not None:
            logger.info(f"[semantic_cache] 命中 (sim={best_sim:.3f}): {text[:30]}…")
            return True, self._entries[best]["result"]
        return False, None

    def put(self, text: str, result: Any, is_violation: bool = False) -> bool:
        """写入缓存。违规结果不缓存（安全约束）。返回是否写入。"""
        if is_violation:
            return False  # 违规不缓存（安全：防止缓存复用漏判）
        if len(self._entries) >= self._max_entries:
            # 简单淘汰最旧
            oldest = min(self._entries, key=lambda k: self._entries[k]["ts"])
            del self._entries[oldest]
        emb = self._embed(text)
        self._entries[text] = {"result": result, "emb": emb, "ts": time.time()}
        return True

    def clear(self):
        self._entries.clear()

    def size(self) -> int:
        return len(self._entries)
