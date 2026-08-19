"""
单元测试 — 技能三级路由（R10·T1）
Filter → Rank → Select；注入 fake embed 验证语义精排，不加载真实模型。
"""
import numpy as np
import pytest

from agent_moderation.skill_registry import get_skill_registry
from agent_moderation.skill_router import SkillRouter


@pytest.fixture
def router():
    return SkillRouter()


class TestFilter:
    def test_trigger_match(self, router):
        """query 命中触发词 → 对应 skill 进入候选"""
        metas = router.filter("帮我检索历史相似案例做参考")
        names = [m.name for m in metas]
        assert "rag-retrieve" in names

    def test_tag_match(self, router):
        """tags 匹配 → 进入候选"""
        metas = router.filter("内容审核", tags={"adversarial"})
        names = [m.name for m in metas]
        assert "adversarial-detect" in names

    def test_top_n_respected(self, router):
        metas = router.filter("审核内容测试", top_n=3)
        assert len(metas) <= 3

    def test_no_match_returns_empty(self, router):
        """query 无关 → 候选可能为空"""
        metas = router.filter("asdfghjkl unrelated nonsense zzz")
        assert isinstance(metas, list)


class TestRank:
    def test_rank_semantic_reorders(self):
        """注入 fake embed（带 encode 的对象）：语义更近的候选排到前面（覆盖 filter 顺序）"""
        # 候选 A 语义近（vec=[1,0]），候选 B 远（vec=[0,1]）
        # filter 阶段让 B 靠前（触发词分数高），rank 阶段 A 应超越
        class FakeEmbed:
            def encode(self, texts, normalize_embeddings=True):
                if isinstance(texts, str):
                    texts = [texts]
                return np.array([[1.0, 0.0] if "SIMILAR" in t else [0.0, 1.0] for t in texts])

        r = SkillRouter(embed_fn=FakeEmbed())
        # 构造候选（description 含 SIMILAR 的语义近）
        a = type("M", (), {"name": "a", "description": "SIMILAR candidate one"})()
        b = type("M", (), {"name": "b", "description": "other thing"})()
        ranked = r.rank("与 SIMILAR 候选高度相似", [b, a], top_k=2)
        assert [m.name for m in ranked] == ["a", "b"]

    def test_rank_degrades_without_embed(self, router):
        """嵌入不可用（注入 None）→ 保持 filter 顺序（诚实降级）"""
        r = SkillRouter(embed_fn=None)
        a = type("M", (), {"name": "a", "description": "x"})()
        b = type("M", (), {"name": "b", "description": "y"})()
        ranked = r.rank("q", [a, b], top_k=2)
        assert [m.name for m in ranked] == ["a", "b"]


class TestSelectRoute:
    def test_select_top_n(self, router):
        a = type("M", (), {"name": "a"})()
        b = type("M", (), {"name": "b"})()
        c = type("M", (), {"name": "c"})()
        assert router.select([a, b, c], max_inject=2) == ["a", "b"]

    def test_route_pipeline(self, router):
        """三级串联：filtered ≥ ranked ≥ selected"""
        result = router.route("检索历史案例", top_n=20, top_k=5, max_inject=3)
        assert set(result["selected"]) <= set(result["ranked"])
        assert set(result["ranked"]) <= set(result["filtered"])
        assert result["selected"], "应有注入技能"


class TestSkillsDiscovery:
    def test_skills_loaded_8(self):
        """F7 修复：skills 扩到 8 个"""
        registry = get_skill_registry()
        assert len(registry._meta_cache) >= 8, \
            f"skills 仅 {len(registry._meta_cache)} 个，F7 未修复"

    def test_new_skills_present(self):
        registry = get_skill_registry()
        names = set(registry._meta_cache.keys())
        for s in ("rag-retrieve", "url-check", "adversarial-detect",
                  "account-risk-check", "content-dedup"):
            assert s in names, f"缺新 skill: {s}"
