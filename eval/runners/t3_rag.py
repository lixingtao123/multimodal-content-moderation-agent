"""
T3 RAG 检索评测 v1（R4·G7）— 四路对比

四路检索：
1. BM25        纯词法（本地，无模型依赖）
2. Dense       Chroma PersistentClient + bge 向量
3. Hybrid      BM25 与 Dense 的 RRF 融合
4. Hybrid+Rerank  Hybrid 结果经 Cross-Encoder 重排

指标：Recall@k / MRR / NDCG（eval.metrics.retrieval_metrics）
相关定义：query 所属类别 == 候选文档类别。

运行（需 PYTHONPATH=/workspace:/workspace/src/backend）:
    python eval/runners/t3_rag.py --per-cat-candidates 20 --per-cat-queries 3
"""
import argparse
import asyncio
import logging
import os
import tempfile
from typing import List, Optional

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# 样本划分
# ------------------------------------------------------------
def build_candidate_and_query(loader, per_cat_candidates: int = 20,
                              per_cat_queries: int = 3, lang: str = "zh"):
    """按类别划分候选库与 query（query 排除在候选之外，避免"背答案"）。

    Returns:
        (candidates, queries) — 均为 OutSafeSample 列表
    """
    from collections import defaultdict

    by_cat = defaultdict(list)
    for s in loader.load_text(lang):
        by_cat[s.category].append(s)

    candidates, queries = [], []
    for cat in sorted(by_cat):
        lst = by_cat[cat]
        candidates.extend(lst[:per_cat_candidates])
        queries.extend(lst[per_cat_candidates:per_cat_candidates + per_cat_queries])
    return candidates, queries


def relevant_ids_for(category: str, candidates: list) -> set:
    """相关定义：同类别候选文档 id 集合"""
    return {c.id for c in candidates if c.category == category}


def build_relevant(candidates: list, queries: list) -> list:
    return [relevant_ids_for(q.category, candidates) for q in queries]


# ------------------------------------------------------------
# 四路检索
# ------------------------------------------------------------
def run_route_bm25(candidates: list, queries: list, top_k: int) -> List[List[str]]:
    """纯 BM25（本地，无模型依赖）"""
    from memory.hybrid_retriever import BM25Retriever

    bm25 = BM25Retriever()
    bm25.index([(c.id, c.content) for c in candidates])
    return [[r.id for r in bm25.search(q.content, top_k=top_k)] for q in queries]


def run_route_dense(candidates: list, queries: list, top_k: int,
                    temp_dir: str) -> Optional[List[List[str]]]:
    """Dense 向量检索（Chroma PersistentClient + bge-small）"""
    import chromadb
    from chromadb.utils import embedding_functions

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="BAAI/bge-small-zh-v1.5", device="cpu")
    client = chromadb.PersistentClient(path=temp_dir)
    col = client.get_or_create_collection("t3_eval", embedding_function=ef)
    col.add(ids=[c.id for c in candidates],
            documents=[c.content for c in candidates])

    results = []
    for q in queries:
        out = col.query(query_texts=[q.content], n_results=top_k)
        results.append(list(out["ids"][0]))
    return results


def _rrf_fuse(lists_a: List[List[str]], lists_b: List[List[str]],
              k: int = 60) -> List[List[str]]:
    """逐 query RRF 融合两路排序（排名倒数加权求和）"""
    fused = []
    for a, b in zip(lists_a, lists_b):
        scores: dict = {}
        for rank, rid in enumerate(a, 1):
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
        for rank, rid in enumerate(b, 1):
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
        fused.append(sorted(scores, key=scores.get, reverse=True))
    return fused


def run_route_rerank(hybrid_ids: List[List[str]], candidates_by_id: dict,
                     queries: list, top_k: int) -> List[List[str]]:
    """Hybrid 结果经 Cross-Encoder 重排（模型懒加载，可能较慢）"""
    from memory.hybrid_retriever import RerankerService, RetrievalResult

    reranker = RerankerService()
    results = []
    for q, ids in zip(queries, hybrid_ids):
        docs = [RetrievalResult(id=rid, content=candidates_by_id[rid].content, score=0.0)
                for rid in ids[:top_k * 2]]
        reranked = reranker.rerank(q.content, docs, top_k=top_k)
        results.append([r.id for r in reranked])
    return results


# ------------------------------------------------------------
# 评测入口
# ------------------------------------------------------------
def evaluate(loader, per_cat_candidates: int = 20, per_cat_queries: int = 3,
             lang: str = "zh", k: int = 10, use_dense: bool = True,
             use_rerank: bool = True, temp_dir: str = None) -> dict:
    """四路对比评测。返回 {route: metrics}，失败的路径如实标记 skipped。"""
    from eval.metrics.retrieval_metrics import report_retrieval_metrics

    candidates, queries = build_candidate_and_query(
        loader, per_cat_candidates, per_cat_queries, lang)
    if not candidates or not queries:
        return {"error": "候选库或 query 为空"}

    relevant = build_relevant(candidates, queries)
    cand_by_id = {c.id: c for c in candidates}
    metrics = {}

    # 1. BM25（永远可跑）
    bm25_ids = run_route_bm25(candidates, queries, k)
    metrics["bm25"] = report_retrieval_metrics(
        [q.content for q in queries], bm25_ids, relevant, k=k)

    if use_dense:
        td = temp_dir or tempfile.mkdtemp(prefix="t3_dense_")
        try:
            dense_ids = run_route_dense(candidates, queries, k, td)
            metrics["dense"] = report_retrieval_metrics(
                [q.content for q in queries], dense_ids, relevant, k=k)
            # 2. Hybrid（BM25 + Dense RRF）
            hybrid_ids = _rrf_fuse(bm25_ids, dense_ids)
            metrics["hybrid"] = report_retrieval_metrics(
                [q.content for q in queries], hybrid_ids, relevant, k=k)

            # 3. Hybrid + Rerank
            if use_rerank:
                try:
                    rerank_ids = run_route_rerank(hybrid_ids, cand_by_id, queries, k)
                    metrics["hybrid_rerank"] = report_retrieval_metrics(
                        [q.content for q in queries], rerank_ids, relevant, k=k)
                except Exception as e:
                    logger.warning(f"rerank 路失败，跳过: {e}")
                    metrics["hybrid_rerank"] = {"skipped": str(e)}
        except Exception as e:
            logger.warning(f"dense 路失败，跳过: {e}")
            metrics["dense"] = {"skipped": str(e)}

    return metrics


def main():
    parser = argparse.ArgumentParser(description="T3 RAG 四路对比评测")
    parser.add_argument("--per-cat-candidates", type=int, default=20)
    parser.add_argument("--per-cat-queries", type=int, default=3)
    parser.add_argument("--lang", default="zh")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--no-dense", action="store_true", help="跳过 Dense/Hybrid/Rerank 路")
    parser.add_argument("--no-rerank", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from eval.datasets.out_safe_loader import OutSafeDatasetLoader
    loader = OutSafeDatasetLoader()
    metrics = evaluate(
        loader,
        per_cat_candidates=args.per_cat_candidates,
        per_cat_queries=args.per_cat_queries,
        lang=args.lang,
        k=args.k,
        use_dense=not args.no_dense,
        use_rerank=not args.no_rerank,
    )
    import json
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
