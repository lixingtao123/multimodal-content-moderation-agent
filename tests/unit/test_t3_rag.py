"""
单元测试 — T3 RAG 四路对比评测（R4·G7）
纯逻辑快测：样本划分 / RRF / 相关定义；BM25 路小规模跑通。
"""
import pytest

from eval.datasets.out_safe_loader import OutSafeDatasetLoader
from eval.runners.t3_rag import (
    _rrf_fuse,
    build_candidate_and_query,
    build_relevant,
    evaluate,
    relevant_ids_for,
)


@pytest.fixture(scope="module")
def loader():
    return OutSafeDatasetLoader()


class TestSplit:
    def test_candidates_and_queries_disjoint(self, loader):
        """query 与候选不重叠（避免"背答案"）"""
        cand, query = build_candidate_and_query(loader, per_cat_candidates=5, per_cat_queries=2)
        cand_ids = {c.id for c in cand}
        query_ids = {q.id for q in query}
        assert not (cand_ids & query_ids)

    def test_query_not_in_candidates(self, loader):
        cand, query = build_candidate_and_query(loader, per_cat_candidates=3, per_cat_queries=1)
        assert len(query) == 9  # 9 类 × 1

    def test_relevant_ids(self, loader):
        cand, _ = build_candidate_and_query(loader, per_cat_candidates=3, per_cat_queries=1)
        rel = relevant_ids_for("1Privacy_and_Property", cand)
        assert rel == {c.id for c in cand if c.category == "1Privacy_and_Property"}
        assert len(rel) == 3


class TestRRF:
    def test_fuse_reorders(self):
        """两路排序融合后，在两路都靠前的 id 应升到顶部"""
        a = [["x", "y", "z"]]
        b = [["y", "x", "w"]]
        fused = _rrf_fuse(a, b)
        # x/y 在两路都排前二（RRF 得分对称相等），应占据前二
        assert set(fused[0][:2]) == {"x", "y"}
        assert set(fused[0]) >= {"x", "y", "z", "w"}

    def test_fuse_single_route(self):
        a = [["a", "b"]]
        b = [["a", "b"]]
        fused = _rrf_fuse(a, b)
        assert fused[0] == ["a", "b"]


class TestEvaluateBM25:
    def test_bm25_only_route(self, loader):
        """仅 BM25 路：能跑通且出指标"""
        metrics = evaluate(loader, per_cat_candidates=5, per_cat_queries=2,
                           k=5, use_dense=False)
        assert "bm25" in metrics
        m = metrics["bm25"]
        assert m["num_queries"] == 18  # 9 类 × 2
        assert 0.0 <= m["recall_at_k"] <= 1.0
        assert 0.0 <= m["mrr"] <= 1.0
        assert 0.0 <= m["ndcg_at_k"] <= 1.0

    def test_bm25_dense_rerank_full(self, loader):
        """完整四路（小规模）：dense/hybrid/rerank 都能出数字"""
        metrics = evaluate(loader, per_cat_candidates=3, per_cat_queries=1,
                           k=3, use_dense=True, use_rerank=True)
        for route in ("bm25", "dense", "hybrid", "hybrid_rerank"):
            assert route in metrics, f"缺 {route} 路"
            m = metrics[route]
            assert "skipped" not in m, f"{route} 路被跳过: {m}"
            assert "recall_at_k" in m
