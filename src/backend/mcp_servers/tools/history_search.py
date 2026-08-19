"""
历史案例检索工具 v2.0 — Hybrid RAG 增强版

升级内容:
  - BM25 + Dense Vector 混合检索 (RRF 融合)
  - Cross-Encoder 重排序
  - Agentic RAG 查询改写 + Self-RAG
  - GraphRAG 违规类型扩展查询
"""
from typing import List, Dict
from pydantic import BaseModel
from memory.manager import get_memory_manager


class HistorySearchInput(BaseModel):
    query: str
    top_k: int = 5


class HistorySearchResult(BaseModel):
    cases: List[Dict]
    has_match: bool
    retrieval_info: dict = {}


class HistorySearchTool:
    """历史案例检索工具 v2.0 — Hybrid RAG"""

    name = "history_search"
    description = "检索相似的历史违规案例（BM25+向量混合检索 + CrossEncoder重排序 + GraphRAG增强）"

    def __init__(self):
        self.memory = get_memory_manager()
        self._hybrid_retriever = None
        self._graph_rag = None

    def _get_hybrid(self):
        """延迟加载混合检索器"""
        if self._hybrid_retriever is None:
            from memory.hybrid_retriever import get_hybrid_retriever
            from memory.chroma_service import get_chroma_service
            self._hybrid_retriever = get_hybrid_retriever(get_chroma_service())
        return self._hybrid_retriever

    def _get_graph_rag(self):
        """延迟加载 GraphRAG"""
        if self._graph_rag is None:
            from memory.graph_rag import get_graph_rag
            self._graph_rag = get_graph_rag()
        return self._graph_rag

    async def execute(self, query: str, top_k: int = 5, use_hybrid: bool = True) -> HistorySearchResult:
        """
        执行历史案例检索 (v3.6: 对抗文本归一化 + 双路检索)

        Args:
            query: 检索查询
            top_k: 返回结果数
            use_hybrid: 是否使用混合检索
        """
        # v3.6: 对抗文本归一化预处理
        normalized_query = self._normalize_adversarial(query)

        if use_hybrid:
            result = await self._hybrid_search(query, top_k)
            # 如果归一化查询不同且第一路结果不足，补充归一化检索
            if normalized_query != query and (not result.has_match or len(result.cases) < 2):
                norm_result = await self._hybrid_search(normalized_query, top_k)
                # 合并去重
                seen_ids = {c["id"] for c in result.cases}
                for c in norm_result.cases:
                    if c["id"] not in seen_ids:
                        result.cases.append(c)
                        seen_ids.add(c["id"])
                result.cases.sort(key=lambda x: x.get("similarity", 0), reverse=True)
                result.cases = result.cases[:top_k]
                result.has_match = len([c for c in result.cases if c.get("similarity", 0) > 0.3]) > 0
            return result
        else:
            return await self._legacy_search(query, top_k)

    # 对抗文本归一化映射
    _ADVERSARIAL_MAP = {
        "⬜":"微","👜":"红","🧧":"包","🐎":"码","👗":"群","🤫":"福","💰":"金","💀":"私",
        "🔞":"成人","👀":"视","🍎":"频","👩":"女","💉":"类","🕺":"人","🎰":"博",
        "©":"权","®":"注","™":"商","ℹ":"信","🔪":"杀","🏠":"家","💊":"药",
    }

    @classmethod
    def _normalize_adversarial(cls, text: str) -> str:
        """对抗文本归一化: emoji/特殊符号 → 规范中文"""
        result = text
        for adv, normal in cls._ADVERSARIAL_MAP.items():
            result = result.replace(adv, normal)
        return result

    async def _hybrid_search(self, query: str, top_k: int = 5) -> HistorySearchResult:
        """混合检索: BM25 + Vector + Reranker"""
        try:
            hybrid = self._get_hybrid()
            results = await hybrid.search(query, top_k=top_k)

            cases = []
            for r in results:
                cases.append({
                    "id": r.id,
                    "content": r.content,
                    "similarity": r.score,
                    "bm25_score": r.bm25_score,
                    "vector_score": r.vector_score,
                    "rerank_score": r.rerank_score,
                    "source": r.source,
                    "violation_type": r.metadata.get("violation_type", ""),
                    "decision": r.metadata.get("decision", ""),
                })

            # 筛选相似度 > 0.3 的结果
            relevant = [c for c in cases if c["similarity"] > 0.3]

            return HistorySearchResult(
                cases=relevant,
                has_match=len(relevant) > 0,
                retrieval_info={
                    "method": "hybrid",
                    "total_found": len(cases),
                    "relevant": len(relevant),
                    "sources_used": list(set(c["source"] for c in cases)),
                },
            )
        except Exception as e:
            # 回退到旧版
            import logging
            logging.getLogger(__name__).warning(f"Hybrid search failed, falling back: {e}")
            return await self._legacy_search(query, top_k)

    async def _legacy_search(self, query: str, top_k: int = 5) -> HistorySearchResult:
        """旧版 ChromaDB-only 检索 (向后兼容)"""
        cases = await self.memory.search_similar_cases(query, top_k)
        relevant_cases = [c for c in cases if c.get("similarity", 0) > 0.5]

        return HistorySearchResult(
            cases=relevant_cases,
            has_match=len(relevant_cases) > 0,
            retrieval_info={"method": "chromadb_only"},
        )
