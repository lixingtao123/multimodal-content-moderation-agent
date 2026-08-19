"""
单元测试 — RAG 来源加权（G2）与 no_decay（G3）
验证 HybridRetriever 全流程：来源元数据透传 → 时间衰减 → 来源加权。
"""
import time

import pytest

from memory.hybrid_retriever import HybridRetriever, RetrievalResult


class MockChroma:
    """模拟 ChromaService：search_similar 返回预置结果"""
    collection = None  # 避免 ensure_connected 同步

    def __init__(self, results):
        self._results = results

    async def search_similar(self, query, top_k):
        return self._results


def _make_retriever(results):
    return HybridRetriever(chroma_service=MockChroma(results))


def _vec(id_, sim, **meta):
    return {"id": id_, "content": "测试内容", "similarity": sim, "violation_type": "porn",
            "decision": "REJECT", **meta}


class TestSourceWeights:
    def test_weights_order(self):
        """confirmed > out_safe > simulated > model_labeled"""
        w = HybridRetriever.SOURCE_WEIGHTS
        assert w["confirmed"] > w["out_safe"] > w["simulated"] > w["model_labeled"]

    def test_apply_source_weight_direct(self):
        """直接调用 _apply_source_weight：同分不同来源，confirmed 最高"""
        r = [
            RetrievalResult(id="a", content="x", score=1.0, metadata={"source_dataset": "confirmed"}),
            RetrievalResult(id="b", content="x", score=1.0, metadata={"source_dataset": "simulated"}),
        ]
        retriever = HybridRetriever(chroma_service=None)
        retriever._apply_source_weight(r)
        assert r[0].score > r[1].score

    def test_apply_source_weight_fallback(self):
        """未知来源回退默认权重，兼容旧 source 键"""
        r = [
            RetrievalResult(id="a", content="x", score=1.0, metadata={"source": "seed_data"}),
            RetrievalResult(id="b", content="x", score=1.0, metadata={}),
        ]
        retriever = HybridRetriever(chroma_service=None)
        retriever._apply_source_weight(r)
        assert r[0].score == 1.0 * retriever.SOURCE_WEIGHTS["seed_data"]
        assert r[1].score == 1.0 * retriever.SOURCE_WEIGHT_DEFAULT


@pytest.mark.asyncio
class TestSearchIntegration:
    async def test_confirmed_outranks_simulated(self):
        """search 全流程：confirmed 来源排名高于同分 simulated"""
        now = time.time()
        results = [
            _vec("confirmed_1", 0.8, source_dataset="confirmed", timestamp=now),
            _vec("sim_1", 0.8, source_dataset="simulated", timestamp=now),
        ]
        retriever = _make_retriever(results)
        out = await retriever.search("测试查询", top_k=5, use_bm25=False,
                                     use_vector=True, use_rerank=False)
        scores = {r.id: r.score for r in out}
        assert scores["confirmed_1"] > scores["sim_1"]

    async def test_no_decay_skips_time_penalty(self):
        """no_decay=True 的老案例不受时间衰减惩罚，分数高于普通老案例"""
        old_ts = time.time() - 30 * 86400  # 30 天前
        # 两样本同源（权重 1.0），仅区分 no_decay，聚焦时间衰减本身
        results = [
            _vec("seed_no_decay", 0.8, timestamp=old_ts, no_decay=True,
                 source_dataset="confirmed"),
            _vec("normal_old", 0.8, timestamp=old_ts, source_dataset="confirmed"),
        ]
        retriever = _make_retriever(results)
        out = await retriever.search("测试查询", top_k=5, use_bm25=False,
                                     use_vector=True, use_rerank=False)
        scores = {r.id: r.score for r in out}
        # 两样本同分：no_decay 未被衰减（~0.8），普通老案例被衰减（<0.8）
        assert scores["seed_no_decay"] > scores["normal_old"]
        assert scores["seed_no_decay"] == pytest.approx(0.8, abs=1e-6)
