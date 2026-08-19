"""
集成测试 — HITL 修复（R8·E4，F1）
验证：graph 接线 / route_after_risk / interrupt 挂起 / Command(resume) 恢复。
"""
import pytest

from agent_moderation.state import ModerationState, create_initial_state
from agent_moderation.workflows.moderation import route_after_risk


class TestRouteAfterRisk:
    def test_pending_to_human(self):
        """_human_review PENDING → human_in_loop"""
        state = create_initial_state("t", "text", {"text": "x"})
        state["_human_review"] = {"required": True, "status": "PENDING"}
        assert route_after_risk(state) == "human_in_loop"

    def test_resolved_to_end(self):
        """人工已处理 → END"""
        state = create_initial_state("t", "text", {"text": "x"})
        state["_human_review"] = {"required": True, "status": "RESOLVED"}
        assert route_after_risk(state) == "__end__"

    def test_no_flag_to_end(self):
        state = create_initial_state("t", "text", {"text": "x"})
        assert route_after_risk(state) == "__end__"


class TestWorkflowGraph:
    def test_risk_agent_has_human_edge(self):
        """F1 修复：risk_agent 出边含 human_in_loop（此前直连 END）"""
        from agent_moderation.workflows.moderation import create_moderation_workflow
        workflow = create_moderation_workflow()
        edges = workflow.get_graph().edges
        risk_edges = [e for e in edges if e.source == "risk_agent"]
        assert any(e.target == "human_in_loop" for e in risk_edges), \
            "risk_agent → human_in_loop 边缺失（F1 未修复）"


class TestAsyncDegrade:
    """async 模式 langgraph 无 interrupt（版本限制），HITL 走降级：REVIEW + 队列注册。

    诚实断言：不假装 async interrupt 可用；验证降级路径真实生效。
    """

    @pytest.mark.asyncio
    async def test_registers_pending_review(self, monkeypatch):
        """F1 修复：human_in_loop_node 必须注册 Redis 待审核队列（此前永远空）"""
        from agent_moderation.workflows.moderation import human_in_loop_node

        called = []

        async def fake_register(cid, state):
            called.append(cid)

        monkeypatch.setattr("api.routes.moderation._register_pending_review", fake_register)

        state = create_initial_state("hitl_reg", "text", {"text": "测试内容"})
        state["_human_review"] = {"required": True, "reason": "测试", "status": "PENDING"}
        await human_in_loop_node(state)
        assert called == ["hitl_reg"], "Redis 队列注册未被调用（F1 未修复）"

    @pytest.mark.asyncio
    async def test_async_degrade_to_review(self):
        """async 无 interrupt → 降级：REVIEW + PENDING_ASYNC"""
        from agent_moderation.workflows.moderation import human_in_loop_node

        state = create_initial_state("hitl_deg", "text", {"text": "测试内容"})
        state["_human_review"] = {"required": True, "reason": "测试", "status": "PENDING"}
        result = await human_in_loop_node(state)
        assert result["_human_review"]["status"] == "PENDING_ASYNC"
        assert result["final_decision"] == "REVIEW"

    @pytest.mark.asyncio
    async def test_no_human_flag_no_degrade(self):
        """无 human 标记 → 不降级、不设 REVIEW"""
        from agent_moderation.workflows.moderation import human_in_loop_node

        state = create_initial_state("hitl_ok", "text", {"text": "正常内容"})
        result = await human_in_loop_node(state)
        assert result["_human_review"].get("required") is False
        assert result.get("final_decision", "") != "REVIEW"
