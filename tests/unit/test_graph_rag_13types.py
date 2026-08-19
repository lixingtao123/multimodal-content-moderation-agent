"""
单元测试 — GraphRAG 图重建对齐 13 类（R14·G4/G5）
"""
from agent_moderation.violation_types import VIOLATION_TYPES
from memory.graph_rag import ViolationKnowledgeGraph


class TestGraph13Types:
    def test_all_13_enum_nodes_exist(self):
        """13 类枚举节点全部存在（G4：图对齐 v5.0 枚举）"""
        g = ViolationKnowledgeGraph()
        missing = [v for v in VIOLATION_TYPES if v != "none" and v not in g.nodes]
        assert not missing, f"图缺枚举节点: {missing}"

    def test_new_types_accessible(self):
        """新增 6 类可查询关联（不报错）"""
        g = ViolationKnowledgeGraph()
        for vt in ("privacy", "discrimination", "crime", "ethics", "health", "copyright"):
            related = g.get_related_violation_types(vt, max_hops=1)
            assert isinstance(related, list)

    def test_privacy_related_to_false_info(self):
        """新增类型关联边生效：privacy ↔ false_info"""
        g = ViolationKnowledgeGraph()
        related = {r[0] for r in g.get_related_violation_types("privacy", max_hops=1)}
        assert "false_info" in related

    def test_crime_related_to_violence(self):
        g = ViolationKnowledgeGraph()
        related = {r[0] for r in g.get_related_violation_types("crime", max_hops=1)}
        assert "violence" in related

    def test_expansion_query_handles_new_types(self):
        """get_expansion_query 对新增类型生成扩展查询"""
        g = ViolationKnowledgeGraph()
        q = g.get_expansion_query(["privacy"], max_related=3)
        assert "privacy" in q
        assert "false_info" in q
