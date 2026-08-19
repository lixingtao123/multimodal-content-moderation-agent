"""
检索指标（R4·G7）：Recall@k / MRR / NDCG

T3 RAG 评测专用。相关性定义：query 的 ground truth 类别 == 检索结果的类别。
纯函数，可单测。
"""
import math
from typing import List, Sequence


def recall_at_k(relevant_ids: set, retrieved_ids: Sequence[str], k: int) -> float:
    """Recall@k = |相关 ∩ 检索top-k| / |相关|；无相关样本返回 0.0"""
    if not relevant_ids:
        return 0.0
    topk = retrieved_ids[:k]
    hit = sum(1 for rid in topk if rid in relevant_ids)
    return hit / len(relevant_ids)


def mrr(retrieved_by_query: Sequence[Sequence[str]], relevant_by_query: Sequence[set]) -> float:
    """MRR：首个相关文档倒数排名的均值"""
    if not retrieved_by_query:
        return 0.0
    total = 0.0
    for retrieved, relevant in zip(retrieved_by_query, relevant_by_query):
        for rank, rid in enumerate(retrieved, 1):
            if rid in relevant:
                total += 1.0 / rank
                break
    return total / len(retrieved_by_query)


def _dcg(rels: Sequence[float]) -> float:
    return sum(rel / math.log2(idx + 2) for idx, rel in enumerate(rels))


def ndcg_at_k(retrieved_ids: Sequence[str], relevant_ids: set, k: int) -> float:
    """NDCG@k：折损累积增益归一化"""
    topk = retrieved_ids[:k]
    if not topk:
        return 0.0
    rels = [1.0 if rid in relevant_ids else 0.0 for rid in topk]
    dcg = _dcg(rels)
    # IDCG：理想排序下 rels 全部相关
    ideal_rels = [1.0] * min(len(rels), len(relevant_ids)) + [0.0] * max(0, len(rels) - len(relevant_ids))
    idcg = _dcg(ideal_rels)
    if idcg <= 0.0:
        return 0.0
    return dcg / idcg


def average_metric(values: List[float]) -> float:
    """均值（空列表返回 0）"""
    return sum(values) / len(values) if values else 0.0


def report_retrieval_metrics(
    queries: List[str],
    retrieved_per_query: List[List[str]],
    relevant_per_query: List[set],
    k: int = 10,
) -> dict:
    """批量计算检索指标汇总。

    Args:
        queries: query 文本列表（用于行数校验）
        retrieved_per_query: 每个 query 的检索 id 列表
        relevant_per_query: 每个 query 的相关 id 集合

    Returns:
        {recall_at_k, mrr, ndcg_at_k, num_queries}
    """
    assert len(retrieved_per_query) == len(relevant_per_query) == len(queries)
    recall_vals = [recall_at_k(rel, ret, k) for ret, rel in zip(retrieved_per_query, relevant_per_query)]
    ndcg_vals = [ndcg_at_k(ret, rel, k) for ret, rel in zip(retrieved_per_query, relevant_per_query)]
    return {
        "recall_at_k": average_metric(recall_vals),
        "mrr": mrr(retrieved_per_query, relevant_per_query),
        "ndcg_at_k": average_metric(ndcg_vals),
        "num_queries": len(queries),
    }
