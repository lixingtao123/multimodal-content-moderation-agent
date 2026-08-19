"""
Hybrid Retriever v2.0 — BM25 + Dense Vector + RRF Fusion + Cross-Encoder Reranker

三层检索架构:
  Layer 1: BM25 (sparse keyword) — PostgreSQL Full-Text Search / rank_bm25
  Layer 2: Dense Vector (semantic) — ChromaDB + bge-small-zh-v1.5
  Layer 3: RRF Fusion — Reciprocal Rank Fusion 合并两个检索结果
  Layer 4: Cross-Encoder Reranker — bge-reranker-v2-m3 精准重排序

参考:
  - Pinecone Hybrid Search Best Practices (2025)
  - Cohere Rerank v3 Architecture
  - LangChain EnsembleRetriever 设计
"""
import time
import math
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """检索结果"""
    id: str
    content: str
    score: float  # 融合后的最终分数 0.0-1.0
    bm25_score: float = 0.0
    vector_score: float = 0.0
    rerank_score: Optional[float] = None
    metadata: dict = field(default_factory=dict)
    source: str = "hybrid"  # bm25 / vector / hybrid


class BM25Retriever:
    """
    BM25 关键词检索器 (sparse retrieval)

    使用 rank_bm25 库实现标准 BM25 算法:
    - k1: 词频饱和度参数 (默认 1.5)
    - b: 文档长度归一化参数 (默认 0.75)

    作为 PostgreSQL Full-Text Search 的轻量替代方案，
    当 PostgreSQL 不可用时使用内存 BM25。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._corpus: List[str] = []
        self._tokenized_corpus: List[List[str]] = []
        self._doc_ids: List[str] = []
        self._avg_doc_len: float = 0.0
        self._df: Dict[str, int] = {}  # document frequency
        self._idf: Dict[str, float] = {}
        self._initialized = False

    def _tokenize(self, text: str) -> List[str]:
        """中文分词: 简单字符级 bigram + 单字"""
        text = text.strip().lower()
        # Bigram 分词 (适用于中文)
        bigrams = [text[i:i+2] for i in range(len(text)-1)]
        # 也加入单字
        unigrams = list(text)
        return bigrams + unigrams

    def index(self, documents: List[Tuple[str, str]]):
        """
        索引文档
        documents: [(doc_id, content), ...]
        """
        self._doc_ids = []
        self._corpus = []
        self._tokenized_corpus = []
        self._df = {}

        for doc_id, content in documents:
            self._doc_ids.append(doc_id)
            self._corpus.append(content)
            tokens = self._tokenize(content)
            self._tokenized_corpus.append(tokens)

            # 统计文档频率
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self._df[token] = self._df.get(token, 0) + 1

        # 计算平均文档长度
        total_len = sum(len(t) for t in self._tokenized_corpus)
        N = max(len(self._tokenized_corpus), 1)
        self._avg_doc_len = total_len / N

        # 计算 IDF
        self._idf = {}
        for token, df in self._df.items():
            self._idf[token] = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

        self._initialized = True
        logger.info(f"BM25 index built: {N} docs, {len(self._df)} unique tokens")

    def search(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """BM25 检索"""
        if not self._initialized:
            return []

        query_tokens = self._tokenize(query)
        N = len(self._tokenized_corpus)

        scores = []
        for i, doc_tokens in enumerate(self._tokenized_corpus):
            doc_len = len(doc_tokens)
            score = 0.0

            # 计算词频
            tf = {}
            for t in doc_tokens:
                tf[t] = tf.get(t, 0) + 1

            for token in query_tokens:
                if token not in self._idf:
                    continue
                idf = self._idf[token]
                token_tf = tf.get(token, 0)

                # BM25 公式
                numerator = token_tf * (self.k1 + 1)
                denominator = token_tf + self.k1 * (1 - self.b + self.b * doc_len / max(self._avg_doc_len, 1))
                score += idf * numerator / max(denominator, 0.001)

            if score > 0:
                scores.append((i, score))

        # 按分数排序
        scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        max_score = max((s[1] for s in scores), default=1.0)
        for idx, score in scores[:top_k]:
            results.append(RetrievalResult(
                id=self._doc_ids[idx],
                content=self._corpus[idx],
                score=score / max_score,  # normalize
                bm25_score=score / max_score,
                source="bm25",
            ))

        return results

    def add_document(self, doc_id: str, content: str):
        """增量添加文档 (重建索引)"""
        # 简化实现: 追加后重建
        self._doc_ids.append(doc_id)
        self._corpus.append(content)
        tokens = self._tokenize(content)
        self._tokenized_corpus.append(tokens)

        unique_tokens = set(tokens)
        for token in unique_tokens:
            self._df[token] = self._df.get(token, 0) + 1

        # 重新计算
        N = len(self._tokenized_corpus)
        total_len = sum(len(t) for t in self._tokenized_corpus)
        self._avg_doc_len = total_len / max(N, 1)
        for token, df in self._df.items():
            self._idf[token] = math.log((N - df + 0.5) / (df + 0.5) + 1.0)


class RerankerService:
    """
    Cross-Encoder 重排序器

    使用 bge-reranker-v2-m3 对初步检索结果进行精准重排序。
    Cross-Encoder 同时编码 query 和 document，精度远高于 Bi-Encoder。

    回退策略: bge-reranker → sentence-transformers cross-encoder → score-based fallback

    低内存配置: 默认禁用 Reranker 或使用极小模型，避免 GPU OOM。
    """

    def __init__(self):
        self._model = None
        self._model_name = None
        self._disabled = True  # 默认禁用，避免 GPU OOM
        self._init_model()

    def _init_model(self):
        """初始化重排序模型（默认禁用，避免 GPU OOM）"""
        # 检查环境变量是否启用
        import os
        enabled = os.environ.get("ENABLE_RERANKER", "false").lower() == "true"
        if not enabled:
            logger.info("Reranker disabled by default (set ENABLE_RERANKER=true to enable)")
            self._disabled = True
            self._model = None
            return

        # 低内存配置：先尝试最小的模型，使用 CPU
        candidates = [
            "BAAI/bge-reranker-v2-mini",
            "BAAI/bge-reranker-base",
            "BAAI/bge-reranker-v2-m3",
        ]

        for name in candidates:
            try:
                from sentence_transformers import CrossEncoder
                # 优先使用 CPU，避免 GPU OOM
                device = "cpu"
                logger.info(f"Loading reranker on {device}...")

                self._model = CrossEncoder(name, device=device)
                self._model_name = name
                self._disabled = False
                logger.info(f"Reranker loaded: {name} (device={device})")
                return
            except Exception as e:
                logger.debug(f"Failed to load {name}: {e}")
                continue

        logger.warning("No Cross-Encoder available, reranker will use score-based fallback")
        self._disabled = True
        self._model = None

    def rerank(
        self,
        query: str,
        documents: List[RetrievalResult],
        top_k: int = 5,
    ) -> List[RetrievalResult]:
        """
        重排序文档列表

        Args:
            query: 查询文本
            documents: 初步检索结果
            top_k: 返回的文档数

        Returns:
            重排序后的结果
        """
        if not documents:
            return []

        if not self._disabled and self._model and len(documents) > 1:
            return self._cross_encoder_rerank(query, documents, top_k)
        else:
            return self._score_fallback(documents, top_k)

    def _cross_encoder_rerank(
        self, query: str, documents: List[RetrievalResult], top_k: int
    ) -> List[RetrievalResult]:
        """Cross-Encoder 精确重排序（小 batch size 避免 OOM）"""
        max_doc_len = 256  # 缩短文档长度节省内存
        max_batch_size = 8  # 小 batch size

        pairs = [(query, doc.content[:max_doc_len]) for doc in documents]

        try:
            scores = self._model.predict(pairs, show_progress_bar=False, batch_size=max_batch_size)

            for doc, score in zip(documents, scores):
                doc.rerank_score = float(score)
                # 融合原始分数和重排序分数
                doc.score = float(score) * 0.7 + doc.score * 0.3

            documents.sort(key=lambda x: x.score, reverse=True)
        except Exception as e:
            logger.warning(f"Reranker prediction failed: {e} (fallback to score-based)")

        return documents[:top_k]

    def _score_fallback(
        self, documents: List[RetrievalResult], top_k: int
    ) -> List[RetrievalResult]:
        """无模型时的分数回落"""
        documents.sort(key=lambda x: x.score, reverse=True)
        return documents[:top_k]


class HybridRetriever:
    """
    混合检索器 v2.0

    完整检索流水线:
    1. 并行执行 BM25 + Dense Vector 检索
    2. RRF (Reciprocal Rank Fusion) 融合两路结果
    3. Cross-Encoder 重排序
    4. 返回 top_k 结果

    使用示例:
        retriever = HybridRetriever(chroma_service)
    """

    # RRF 参数
    RRF_K = 60  # RRF 常数，控制排名的影响力

    # R3·G2: 检索来源权重（confirmed > out_safe > simulated > model_labeled）
    # 真实/人工确认的数据优先于模拟/模型标注数据，防止模拟种子污染真实检索。
    SOURCE_WEIGHTS = {
        "confirmed": 1.0,
        "out_safe": 0.9,
        "simulated": 0.7,
        "model_labeled": 0.5,
        "seed_data": 0.7,  # 历史 seed_rag_data 的 source 值，兼容旧数据
    }
    SOURCE_WEIGHT_DEFAULT = 0.7

    def __init__(self, chroma_service=None):
        self.bm25 = BM25Retriever()
        self.reranker = RerankerService()
        self.chroma = chroma_service
        self._doc_store: Dict[str, str] = {}  # id -> content 缓存
        self._synced = False

    async def ensure_connected(self):
        """确保 ChromaService 已连接，并同步 BM25 索引"""
        if self.chroma is not None and self.chroma.collection is None:
            try:
                await self.chroma.connect()
                logger.info("HybridRetriever: ChromaService auto-connected")
            except Exception as e:
                logger.warning(f"HybridRetriever: Failed to connect ChromaService: {e}")

        # 从 ChromaDB 同步文档到 BM25 索引
        if not self._synced and self.chroma is not None and self.chroma.collection is not None:
            try:
                await self._sync_from_chroma()
            except Exception as e:
                logger.warning(f"HybridRetriever: Failed to sync BM25 index: {e}")

    async def _sync_from_chroma(self):
        """从 ChromaDB 同步已有文档到 BM25 索引"""
        try:
            count = self.chroma.collection.count()
            if count > 0:
                # 分批获取所有文档
                batch_size = 100
                all_docs = []
                for offset in range(0, count, batch_size):
                    results = self.chroma.collection.get(
                        limit=batch_size,
                        offset=offset,
                        include=["documents"],
                    )
                    if results["ids"]:
                        for i, doc_id in enumerate(results["ids"]):
                            content = results["documents"][i] if results["documents"] else ""
                            all_docs.append((doc_id, content))
                            self._doc_store[doc_id] = content

                if all_docs:
                    self.bm25.index(all_docs)
                    logger.info(f"BM25 index synced from ChromaDB: {len(all_docs)} documents")
        except Exception as e:
            logger.warning(f"BM25 sync failed: {e}")
        self._synced = True

    def index_documents(self, documents: List[Tuple[str, str]]):
        """
        批量索引文档用于 BM25 检索

        Args:
            documents: [(doc_id, content), ...]
        """
        self.bm25.index(documents)
        for doc_id, content in documents:
            self._doc_store[doc_id] = content
        logger.info(f"HybridRetriever indexed {len(documents)} documents")

    def add_document(self, doc_id: str, content: str):
        """增量添加文档"""
        self.bm25.add_document(doc_id, content)
        self._doc_store[doc_id] = content

    async def search(
        self,
        query: str,
        top_k: int = 5,
        use_bm25: bool = True,
        use_vector: bool = True,
        use_rerank: bool = True,
    ) -> List[RetrievalResult]:
        """
        混合检索

        Args:
            query: 查询文本
            top_k: 返回结果数
            use_bm25: 是否启用 BM25 关键词检索
            use_vector: 是否启用向量语义检索
            use_rerank: 是否启用 Cross-Encoder 重排序

        Returns:
            融合后的检索结果
        """
        # 确保 ChromaService 连接 + BM25 索引同步
        await self.ensure_connected()

        bm25_results = []
        vector_results = []

        # 并行执行两路检索
        if use_bm25:
            bm25_results = self.bm25.search(query, top_k=top_k * 2)
            logger.debug(f"BM25 retrieved {len(bm25_results)} results")

        if use_vector and self.chroma:
            try:
                vector_raw = await self.chroma.search_similar(query, top_k=top_k * 2)
                for r in vector_raw:
                    # R19 修复：优先用 chroma 完整透传的 metadata（source/来源加权/no_decay）
                    # 兼容两种返回形态：chroma 的 metadata 子字段 / 旧 MockChroma 顶层字段
                    _meta = dict(r.get("metadata") or {}) if isinstance(r.get("metadata"), dict) else {}
                    for _k in ("source", "source_dataset", "timestamp", "no_decay", "ground_truth"):
                        if _k in r and _k not in _meta:
                            _meta[_k] = r[_k]
                    vector_results.append(RetrievalResult(
                        id=r.get("id", ""),
                        content=r.get("content", ""),
                        score=r.get("similarity", 0.0),
                        vector_score=r.get("similarity", 0.0),
                        metadata={
                            "violation_type": r.get("violation_type", ""),
                            "decision": r.get("decision", ""),
                            **_meta,
                        },
                        source="vector",
                    ))
                logger.debug(f"Vector retrieved {len(vector_results)} results")
            except Exception as e:
                logger.warning(f"Vector search failed: {e}")

        # RRF 融合
        if bm25_results and vector_results:
            fused = self._rrf_fusion(bm25_results, vector_results, top_k * 2)
        elif bm25_results:
            fused = bm25_results
        elif vector_results:
            fused = vector_results
        else:
            return []

        # 去重 (同一 id 取最高分)
        seen = {}
        for r in fused:
            if r.id not in seen or r.score > seen[r.id].score:
                seen[r.id] = r
        fused = list(seen.values())
        fused.sort(key=lambda x: x.score, reverse=True)

        # v3.6: 时间衰减加权 (新案例优先, 7天半衰期)
        # R3·G3: metadata.no_decay=True 的种子/离线案例跳过时间衰减
        now = time.time()
        HALF_LIFE = 7 * 24 * 3600  # 7天
        for r in fused:
            if r.metadata and r.metadata.get("no_decay"):
                continue
            ts = r.metadata.get("timestamp", now) if r.metadata else now
            age_days = (now - ts) / 86400
            decay = math.exp(-0.693 * age_days / 7)  # 指数衰减, 7天半衰期
            r.score = r.score * (0.85 + 0.15 * decay)  # 时间权重占15%

        # R3·G2: 来源加权（真实/确认数据优先，模拟数据降权）
        fused = self._apply_source_weight(fused)

        # v3.6: 违规类型分层采样 (避免热门类型淹没罕见类型)
        fused = self._stratified_sample(fused, top_k)

        # Cross-Encoder 重排序
        if use_rerank and len(fused) > 1:
            fused = self.reranker.rerank(query, fused, top_k)
        else:
            fused = fused[:top_k]

        # 补充 content (如果 ChromaDB 返回的 content 为空)
        for r in fused:
            if not r.content and r.id in self._doc_store:
                r.content = self._doc_store[r.id]

        logger.info(
            f"Hybrid search: query='{query[:50]}...' → "
            f"bm25={len(bm25_results)}, vector={len(vector_results)}, "
            f"final={len(fused)}"
        )

        return fused[:top_k]

    def _apply_source_weight(self, results: List[RetrievalResult]) -> List[RetrievalResult]:
        """R3·G2: 按数据来源加权（confirmed > out_safe > simulated > model_labeled）。

        metadata 优先取 source_dataset，回退到旧的 source 键；未知来源用默认权重。
        """
        for r in results:
            md = r.metadata or {}
            src = md.get("source_dataset") or md.get("source") or "unknown"
            weight = self.SOURCE_WEIGHTS.get(src, self.SOURCE_WEIGHT_DEFAULT)
            r.score = r.score * weight
        return results

    def _stratified_sample(self, results: List[RetrievalResult], top_k: int) -> List[RetrievalResult]:
        """分层采样: 每种违规类型至少保留1条，避免热门类型淹没罕见类型"""
        by_type = {}
        for r in results:
            vt = r.metadata.get("violation_type", "other") if r.metadata else "other"
            if vt not in by_type:
                by_type[vt] = []
            by_type[vt].append(r)

        sampled = []
        # 轮询每种类型取 top-1
        while len(sampled) < top_k * 2 and by_type:
            for vt in list(by_type.keys()):
                if by_type[vt]:
                    sampled.append(by_type[vt].pop(0))
                else:
                    del by_type[vt]
                if len(sampled) >= top_k * 2:
                    break

        sampled.sort(key=lambda x: x.score, reverse=True)
        return sampled

    def _rrf_fusion(
        self,
        results_a: List[RetrievalResult],
        results_b: List[RetrievalResult],
        top_k: int,
    ) -> List[RetrievalResult]:
        """
        Reciprocal Rank Fusion (RRF)

        RRF 公式: score(d) = Σ 1/(k + rank_i(d))
        其中 k 是常数 (默认 60), rank_i 是文档在第 i 个检索器中的排名
        """
        rrf_scores: Dict[str, Tuple[float, RetrievalResult]] = {}

        # 第一路 BM25 排名
        for rank, doc in enumerate(results_a, start=1):
            rrf = 1.0 / (self.RRF_K + rank)
            rrf_scores[doc.id] = (rrf, doc)
            doc.score = rrf  # 初始 RRF 分数

        # 第二路 Vector 排名
        for rank, doc in enumerate(results_b, start=1):
            rrf = 1.0 / (self.RRF_K + rank)
            if doc.id in rrf_scores:
                existing_rrf, existing_doc = rrf_scores[doc.id]
                new_rrf = existing_rrf + rrf
                rrf_scores[doc.id] = (new_rrf, existing_doc)
                # 融合来源标记
                existing_doc.source = "hybrid"
                existing_doc.score = new_rrf
                if doc.vector_score > 0:
                    existing_doc.vector_score = doc.vector_score
                existing_doc.metadata.update(doc.metadata)
            else:
                doc.score = rrf
                rrf_scores[doc.id] = (rrf, doc)

        # 按 RRF 分数排序
        sorted_items = sorted(rrf_scores.values(), key=lambda x: x[0], reverse=True)
        return [doc for _, doc in sorted_items[:top_k]]


# 全局服务单例
_hybrid_retriever: Optional[HybridRetriever] = None


def get_hybrid_retriever(chroma_service=None) -> HybridRetriever:
    """获取混合检索器实例"""
    global _hybrid_retriever
    if _hybrid_retriever is None:
        _hybrid_retriever = HybridRetriever(chroma_service)
    elif chroma_service and _hybrid_retriever.chroma is None:
        _hybrid_retriever.chroma = chroma_service
    return _hybrid_retriever
