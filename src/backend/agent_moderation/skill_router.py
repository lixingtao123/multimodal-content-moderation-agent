"""
技能三级路由（R10·T1）— Filter → Rank → Select

规模化的关键：工具/技能很多时，模型不能一次性看到全部说明书（上下文挤爆、选择准确率崩）。

三级筛选：
1. Filter  分桶粗筛（标签/触发词/描述关键词）→ 100 选 20
2. Rank    语义精排（bge 嵌入，query vs 描述相似度）→ 20 选 5
3. Select  裁决（确定性：取 top-k 中前 max_inject 注入）→ 5 选 2-3

Rank 层模型不可用时降级为 Filter 顺序（诚实降级，不崩溃）。
"""
import logging
from typing import List, Optional

from agent_moderation.skill_registry import Skill, SkillMeta, get_skill_registry

logger = logging.getLogger(__name__)


class SkillRouter:
    """三级路由：把全量 skill 收敛为可注入的少数几个"""

    def __init__(self, registry=None, embed_fn=None):
        self.registry = registry or get_skill_registry()
        self._embed_fn = embed_fn  # 可注入（测试用）
        self._embed_loaded = False

    # ------------------------------------------------------------
    # Filter：分桶粗筛
    # ------------------------------------------------------------
    def filter(self, query: str, tags: Optional[set] = None, top_n: int = 20) -> List[SkillMeta]:
        """按标签/触发词/描述关键词打分粗筛，取 top_n。"""
        metas = list(self.registry._meta_cache.values())
        if not metas:
            return []
        scored = []
        ql = query.lower()
        for m in metas:
            s = 0.0
            m_tags = set(m.tags or [])
            if tags and (m_tags & tags):
                s += 3.0
            # triggers 兼容两种格式：str 列表 或 dict 列表（旧 SKILL.md 用 {'tool': ...}）
            for t in (m.triggers or []):
                if isinstance(t, str) and t.lower() in ql:
                    s += 2.0
                elif isinstance(t, dict):
                    for v in t.values():
                        if isinstance(v, str) and v.lower() in ql:
                            s += 2.0
                            break
            desc = (m.description or "").lower()
            # 描述关键词命中（中英文通用：子串匹配）
            for kw in desc.split():
                if len(kw) >= 3 and kw in ql:
                    s += 1.0
            if s > 0:
                scored.append((s, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_n]]

    # ------------------------------------------------------------
    # Rank：语义精排
    # ------------------------------------------------------------
    def _get_embed(self):
        """懒加载 bge-small-zh 嵌入模型"""
        if self._embed_fn is not None:
            return self._embed_fn
        if not self._embed_loaded:
            try:
                from sentence_transformers import SentenceTransformer
                self._embed_fn = SentenceTransformer("BAAI/bge-small-zh-v1.5")
            except Exception as e:
                logger.warning(f"[skill_router] bge 加载失败，语义精排降级为关键词排序: {e}")
                self._embed_fn = None
            self._embed_loaded = True
        return self._embed_fn

    def rank(self, query: str, candidates: List[SkillMeta], top_k: int = 5) -> List[SkillMeta]:
        """语义精排；嵌入不可用 → 保持 Filter 顺序（诚实降级）"""
        if not candidates:
            return []
        embed = self._get_embed()
        if embed is None:
            return candidates[:top_k]
        try:
            query_vec = embed.encode([query], normalize_embeddings=True)[0]
            cand_vecs = embed.encode([m.description for m in candidates], normalize_embeddings=True)
            sims = [float(query_vec @ cv) for cv in cand_vecs]
            order = sorted(range(len(candidates)), key=lambda i: sims[i], reverse=True)
            return [candidates[i] for i in order[:top_k]]
        except Exception as e:
            logger.warning(f"[skill_router] 语义精排异常，降级: {e}")
            return candidates[:top_k]

    # ------------------------------------------------------------
    # Select：裁决注入
    # ------------------------------------------------------------
    def select(self, ranked: List[SkillMeta], max_inject: int = 3) -> List[str]:
        """确定性裁决：取前 max_inject 个 skill 名注入"""
        return [m.name for m in ranked[:max_inject]]

    # ------------------------------------------------------------
    # 路由入口
    # ------------------------------------------------------------
    def route(self, query: str, tags: Optional[set] = None,
              top_n: int = 20, top_k: int = 5, max_inject: int = 3) -> dict:
        """三级路由：返回 {filtered, ranked, selected}"""
        filtered = self.filter(query, tags, top_n)
        ranked = self.rank(query, filtered, top_k)
        selected = self.select(ranked, max_inject)
        return {
            "filtered": [m.name for m in filtered],
            "ranked": [m.name for m in ranked],
            "selected": selected,
        }


# 全局单例
_skill_router = None


def get_skill_router() -> SkillRouter:
    global _skill_router
    if _skill_router is None:
        _skill_router = SkillRouter()
    return _skill_router
