"""
单元测试 — 检索指标（R4·G7）
"""
from eval.metrics.retrieval_metrics import (
    average_metric,
    mrr,
    ndcg_at_k,
    recall_at_k,
    report_retrieval_metrics,
)


class TestRecallAtK:
    def test_perfect_hit(self):
        assert recall_at_k({"a", "b"}, ["a", "b", "c"], k=2) == 1.0

    def test_partial(self):
        assert recall_at_k({"a", "b", "c"}, ["a", "x", "y"], k=3) == 1 / 3

    def test_empty_relevant(self):
        assert recall_at_k(set(), ["a"], k=1) == 0.0

    def test_k_respected(self):
        # top-1 内无相关，但相关在 top-3
        assert recall_at_k({"c"}, ["a", "b", "c"], k=1) == 0.0
        assert recall_at_k({"c"}, ["a", "b", "c"], k=3) == 1.0


class TestMRR:
    def test_first_rank_1(self):
        assert mrr([["a", "b"]], [{"b"}]) == 0.5  # 首个相关在 rank2

    def test_rank1(self):
        assert mrr([["a", "b"]], [{"a"}]) == 1.0

    def test_no_relevant(self):
        assert mrr([["a", "b"]], [{"c"}]) == 0.0

    def test_multi_query_average(self):
        assert mrr([["a"], ["x", "y"]], [{"a"}, {"y"}]) == (1.0 + 0.5) / 2


class TestNDCG:
    def test_perfect(self):
        assert ndcg_at_k(["a", "b"], {"a", "b"}, k=2) == 1.0

    def test_partial_better_than_random(self):
        good = ndcg_at_k(["a", "x", "y"], {"a", "b"}, k=3)
        bad = ndcg_at_k(["x", "y", "a"], {"a", "b"}, k=3)
        assert good > bad > 0.0

    def test_empty(self):
        assert ndcg_at_k([], {"a"}, k=5) == 0.0

    def test_single_relevant_at_rank1(self):
        """唯一相关且在 rank1 → NDCG=1.0（完美排序）"""
        assert ndcg_at_k(["a", "b", "c"], {"a"}, k=3) == 1.0

    def test_single_relevant_at_rank2(self):
        """唯一相关在 rank2 → 部分得分"""
        v = ndcg_at_k(["x", "a", "c"], {"a"}, k=3)
        assert 0.0 < v < 1.0


class TestReport:
    def test_report_structure(self):
        r = report_retrieval_metrics(
            queries=["q1", "q2"],
            retrieved_per_query=[["a", "b"], ["a", "b"]],
            relevant_per_query=[{"a"}, {"b"}],
            k=2,
        )
        assert r["num_queries"] == 2
        assert "recall_at_k" in r and "mrr" in r and "ndcg_at_k" in r
        assert r["mrr"] == (1.0 + 0.5) / 2

    def test_empty_queries(self):
        r = report_retrieval_metrics([], [], [], k=10)
        assert r["num_queries"] == 0
        assert r["recall_at_k"] == 0.0

    def test_average_metric_empty(self):
        assert average_metric([]) == 0.0
