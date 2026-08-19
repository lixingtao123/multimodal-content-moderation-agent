"""
RAG/记忆域扩展工具（R19·MCP 扩展批 6）

薄封装已有引擎组件（HybridRetriever / SemanticCache / ViolationKnowledgeGraph）：
  - rag_hybrid_search      混合检索（BM25+向量+RRF+重排序）
  - source_weighted_search 来源加权检索（confirmed>out_safe>simulated>model_labeled）
  - semantic_cache_probe   语义缓存查询（≥阈值命中，缓存未命中返回 miss）
  - knowledge_graph_query  违规类型知识图谱关联查询
  - case_history_stats     案例库统计

外部依赖不可用时返回 degraded 标注（诚实降级，不编造检索结果）。
"""
from typing import List, Optional
from pydantic import BaseModel


class RetrievedItem(BaseModel):
    id: str
    content: str
    score: float
    source: str
    metadata: dict = {}


class HybridSearchResult(BaseModel):
    items: List[RetrievedItem]
    degraded: bool
    note: str


def _to_items(results) -> List[RetrievedItem]:
    items = []
    for r in results:
        items.append(RetrievedItem(
            id=getattr(r, "id", ""), content=getattr(r, "content", ""),
            score=round(float(getattr(r, "score", 0.0)), 4),
            source=getattr(r, "source", ""),
            metadata=getattr(r, "metadata", {}) or {},
        ))
    return items


class RagHybridSearchTool:
    name = "rag_hybrid_search"
    description = "混合检索（BM25 + 向量 + RRF 融合 + 重排序）"

    async def execute(self, query: str, top_k: int = 5, use_rerank: bool = True) -> HybridSearchResult:
        try:
            from memory.hybrid_retriever import HybridRetriever
            from memory.chroma_service import get_chroma_service

            retriever = HybridRetriever(get_chroma_service())
            results = await retriever.search(query, top_k=top_k, use_rerank=use_rerank)
            return HybridSearchResult(items=_to_items(results), degraded=False, note=f"{len(results)} 条结果")
        except Exception as e:
            return HybridSearchResult(items=[], degraded=True, note=f"检索降级: {e}")


class SourceWeightedSearchTool:
    name = "source_weighted_search"
    description = "来源加权检索（confirmed>out_safe>simulated>model_labeled 优先）"

    async def execute(self, query: str, top_k: int = 5) -> HybridSearchResult:
        try:
            from memory.hybrid_retriever import HybridRetriever
            from memory.chroma_service import get_chroma_service

            retriever = HybridRetriever(get_chroma_service())
            results = await retriever.search(query, top_k=top_k * 2, use_rerank=False)
            # 来源加权：权重叠加到 score 后取 top_k
            w = retriever.SOURCE_WEIGHTS
            for r in results:
                src = (getattr(r, "metadata", {}) or {}).get("source", "")
                r.score = r.score * w.get(src, retriever.SOURCE_WEIGHT_DEFAULT)
            results.sort(key=lambda r: r.score, reverse=True)
            return HybridSearchResult(
                items=_to_items(results[:top_k]), degraded=False,
                note="按来源权重加权排序",
            )
        except Exception as e:
            return HybridSearchResult(items=[], degraded=True, note=f"检索降级: {e}")


class SemanticCacheProbeResult(BaseModel):
    hit: bool
    result: dict
    similarity: float
    degraded: bool


class SemanticCacheProbeTool:
    name = "semantic_cache_probe"
    description = "语义缓存查询（相似度≥阈值命中返回缓存结果）"

    async def execute(self, text: str) -> SemanticCacheProbeResult:
        try:
            from memory.semantic_cache import get_semantic_cache
            cache = get_semantic_cache()
            res = await cache.get(text) if hasattr(cache.get, "__await__") else cache.get(text)
            if isinstance(res, tuple) and len(res) == 2:
                result, sim = res
                return SemanticCacheProbeResult(
                    hit=result is not None, result=result or {},
                    similarity=round(float(sim), 4), degraded=False,
                )
            return SemanticCacheProbeResult(hit=res is not None, result=res or {}, similarity=0.0, degraded=False)
        except Exception as e:
            return SemanticCacheProbeResult(hit=False, result={}, similarity=0.0, degraded=True)


class KnowledgeGraphQueryResult(BaseModel):
    related: List[dict]
    expansion_query: str
    degraded: bool


class KnowledgeGraphQueryTool:
    name = "knowledge_graph_query"
    description = "查询违规类型知识图谱的关联类型与扩展检索词"

    async def execute(self, violation_types: List[str]) -> KnowledgeGraphQueryResult:
        try:
            from memory.graph_rag import get_knowledge_graph

            kg = get_knowledge_graph()
            related = kg.get_related_violation_types(violation_types)
            expansion = kg.get_expansion_query(violation_types)
            return KnowledgeGraphQueryResult(
                related=[{"type": t, "relation": rel} for t, rel in related],
                expansion_query=expansion, degraded=False,
            )
        except Exception as e:
            return KnowledgeGraphQueryResult(related=[], expansion_query="", degraded=True)


class CaseHistoryStatsResult(BaseModel):
    total: Optional[int]
    degraded: bool
    note: str


class CaseHistoryStatsTool:
    name = "case_history_stats"
    description = "案例库统计（ChromaDB 案例总数/集合状态）"

    async def execute(self) -> CaseHistoryStatsResult:
        try:
            from memory.chroma_service import get_chroma_service
            svc = get_chroma_service()
            await svc.connect()
            if svc.collection is None:
                return CaseHistoryStatsResult(total=None, degraded=True, note="Chroma 集合未初始化")
            count = svc.collection.count()
            return CaseHistoryStatsResult(total=count, degraded=False, note=f"{count} 条案例")
        except Exception as e:
            return CaseHistoryStatsResult(total=None, degraded=True, note=f"统计降级: {e}")
