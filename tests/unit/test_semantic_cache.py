"""
单元测试 — 语义缓存（R11·M2）
注入 fake embed 验证语义命中 / 违规不缓存 / TTL / 精确降级。
"""
import numpy as np
import pytest

from memory.semantic_cache import SemanticCache


class FakeEmbed:
    """确定性 embed：含 SIMILAR 的文本编码 [1,0]，否则 [0,1]"""
    def encode(self, texts, normalize_embeddings=True):
        if isinstance(texts, str):
            texts = [texts]
        return np.array([[1.0, 0.0] if "SIMILAR" in t else [0.0, 1.0] for t in texts])


def make_cache(**kw):
    return SemanticCache(embed_fn=FakeEmbed(), **kw)


class TestSemanticHit:
    def test_exact_hit(self):
        c = make_cache()
        c.put("原文", {"r": 1})
        hit, result = c.get("原文")
        assert hit and result == {"r": 1}

    def test_semantic_hit_similar(self):
        """意思相近（SIMILAR 关键词）→ 命中"""
        c = make_cache()
        c.put("SIMILAR 请求内容", {"r": 1})
        hit, result = c.get("SIMILAR 变体表述")
        assert hit is True
        assert result == {"r": 1}

    def test_dissimilar_miss(self):
        c = make_cache()
        c.put("SIMILAR 请求内容", {"r": 1})
        hit, _ = c.get("完全不相关的话题")
        assert hit is False

    def test_threshold_respected(self):
        """相似度低于阈值 → 不命中（threshold=0.5 时 dissimilar sim=0）"""
        c = make_cache(threshold=0.5)
        c.put("SIMILAR 请求", {"r": 1})
        hit, _ = c.get("完全不相关")
        assert hit is False


class TestViolationNotCached:
    def test_violation_put_rejected(self):
        """违规结果不缓存（安全约束）"""
        c = make_cache()
        ok = c.put("敏感内容", {"decision": "REJECT"}, is_violation=True)
        assert ok is False
        assert c.size() == 0

    def test_normal_put_allowed(self):
        c = make_cache()
        ok = c.put("正常内容", {"decision": "PASS"}, is_violation=False)
        assert ok is True
        assert c.size() == 1


class TestTTL:
    def test_expired_not_hit(self):
        c = make_cache(ttl=10)
        c.put("文本A", {"r": 1})
        # 手动过期
        for e in c._entries.values():
            e["ts"] -= 100
        hit, _ = c.get("文本A")
        assert hit is False


class TestDegrade:
    def test_no_embed_precise_only(self):
        """无 embed（embed_fn=None + 加载失败）→ 仅精确匹配"""
        c = SemanticCache(embed_fn=None)
        # 强制嵌入不可用
        c._embed_fn = None
        c._embed_ok = False
        c.put("精确文本", {"r": 1})
        hit, _ = c.get("精确文本")  # 精确命中（dict 精确查找先于嵌入）
        assert hit is True
        hit2, _ = c.get("精确文本 变体")
        assert hit2 is False

    def test_max_entries_evicts(self):
        c = make_cache(max_entries=2)
        c.put("a1", {"r": 1})
        c.put("b2", {"r": 2})
        c.put("c3", {"r": 3})
        assert c.size() <= 2
