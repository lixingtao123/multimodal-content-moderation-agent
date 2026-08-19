"""
单元测试 — L4 标注/优化 Agent 接入工具与 skill（R12）
monkeypatch 工具层，避免真实 chroma/Redis 依赖。
"""
import pytest

from optimization.annotation_agent import _tool_assisted_review
from optimization.optimization_agent import OptimizationAction, OptimizationAgent


class _FakeKW:
    has_violation = True
    matches = ["加微信"]


class _FakeHS:
    cases = [{"content_id": "c1", "similarity": 0.95}, {"content_id": "c2", "similarity": 0.8}]


class _FakeRouter:
    def route(self, query, top_n=20, top_k=5, max_inject=3):
        return {"filtered": ["kw"], "ranked": ["kw"], "selected": ["keyword-check"]}


class TestToolAssistedReview:
    @pytest.mark.asyncio
    async def test_evidence_filled(self, monkeypatch):
        """工具复核产出证据：路由技能 + keyword + history"""
        async def fake_call(registry, tool_name, args, **kw):
            if tool_name == "keyword_check":
                return _FakeKW()
            return _FakeHS()

        monkeypatch.setattr("agent_moderation.skill_router.get_skill_router",
                            lambda: _FakeRouter())
        monkeypatch.setattr("mcp_servers.tool_reliability.call_with_reliability", fake_call)

        ev = await _tool_assisted_review("加微信返利")
        assert ev["routed_skills"] == ["keyword-check"]
        assert ev["keyword"]["has_violation"] is True
        assert ev["history"][0]["similarity"] == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_tool_failure_degrades(self, monkeypatch):
        """工具异常 → 降级为空证据（不阻断标注）"""
        async def bad_call(registry, tool_name, args, **kw):
            raise RuntimeError("tool down")

        monkeypatch.setattr("mcp_servers.tool_reliability.call_with_reliability", bad_call)
        ev = await _tool_assisted_review("测试内容")
        assert "keyword_error" in ev or "history_error" in ev


class TestRagCaseAddDedup:
    @pytest.mark.asyncio
    async def test_duplicate_skipped(self, monkeypatch):
        """history_search 返回相似≥0.9 → 跳过入库"""
        saved_cases = []

        async def fake_call(registry, tool_name, args, **kw):
            return _FakeHS()  # 最高相似 0.95 ≥ 0.9

        class _FakeMemory:
            async def save_case(self, **kw):
                saved_cases.append(kw)

        monkeypatch.setattr("mcp_servers.tool_reliability.call_with_reliability", fake_call)
        monkeypatch.setattr("memory.manager.get_memory_manager", lambda: _FakeMemory())

        agent = OptimizationAgent()
        action = _mk_action("补充暴力案例")
        buffer = [{"content_id": "dup_1", "error_detail": "漏判了暴力内容", "error_type": "false_negative"}]
        await agent._exec_rag_case_add(action, buffer)
        assert saved_cases == [], f"重复案例不应入库，实际入库 {len(saved_cases)} 条"

    @pytest.mark.asyncio
    async def test_new_case_added(self, monkeypatch):
        """history_search 无相似 → 正常入库"""
        saved_cases = []

        async def fake_call(registry, tool_name, args, **kw):
            return _FakeHS2()  # 相似 < 0.9

        class _FakeMemory:
            async def save_case(self, **kw):
                saved_cases.append(kw)

        monkeypatch.setattr("mcp_servers.tool_reliability.call_with_reliability", fake_call)
        monkeypatch.setattr("memory.manager.get_memory_manager", lambda: _FakeMemory())

        agent = OptimizationAgent()
        action = _mk_action("补充案例")
        buffer = [{"content_id": "new_1", "error_detail": "新案例内容", "error_type": "false_negative"}]
        await agent._exec_rag_case_add(action, buffer)
        assert len(saved_cases) == 1


def _mk_action(desc):
    return OptimizationAction(action_type="rag_case_add", target="violence",
                              description=desc, reason="test")


class _FakeHS2:
    cases = [{"content_id": "other", "similarity": 0.3}]
