"""
集成测试 — 分诊台三车道（R6·E1/E2/E3）
验证：workflow 图编译 + 三车道路由 + 快车道小模型判定 + 大脑决策。
"""
import pytest

from agent_moderation.state import create_initial_state
from agent_moderation.workflows.moderation import (
    brain_node,
    fast_lane_node,
    route_after_triage,
    triage_node,
)


class TestWorkflowGraph:
    def test_workflow_compiles_with_triage_nodes(self):
        """图可编译，且包含 v5.0 新节点"""
        from agent_moderation.workflows.moderation import create_moderation_workflow
        workflow = create_moderation_workflow()
        nodes = set(workflow.get_graph().nodes.keys())
        for n in ("triage", "fast_lane", "brain"):
            assert n in nodes, f"缺 {n} 节点"


class TestTriageNode:
    def test_simple_text_to_low(self):
        state = create_initial_state("t1", "text", {"text": "今天天气不错"})
        state = triage_node(state)
        assert state["_tier"] == "low"
        assert state["_triage"]["cost_saved"] is True

    def test_non_text_to_med(self):
        state = create_initial_state("t2", "image", {"image": b"xx"})
        state = triage_node(state)
        assert state["_tier"] == "med"


class TestRouteAfterTriage:
    def test_low_to_fast_lane(self):
        state = create_initial_state("t1", "text", {"text": "hi"})
        state["_tier"] = "low"
        assert route_after_triage(state) == "fast_lane"

    def test_high_to_brain(self):
        state = create_initial_state("t1", "text", {"text": "x"})
        state["_tier"] = "high"
        assert route_after_triage(state) == "brain"

    def test_med_to_existing_route(self):
        """med 复用现状路由：文本 → text_agent"""
        state = create_initial_state("t1", "text", {"text": "x"})
        state["_tier"] = "med"
        assert route_after_triage(state) == "text_agent"

    def test_med_multimodal_to_planner(self):
        state = create_initial_state("t1", "multi_modal", {"text": "x"})
        state["_tier"] = "med"
        state["_is_multimodal"] = True
        assert route_after_triage(state) == "planner"


class TestFastLane:
    @pytest.mark.asyncio
    async def test_fast_lane_pass(self, monkeypatch):
        """R19 快车道 = 小模型判定（qwen 本地模型），高置信 PASS 直接采纳"""
        state = create_initial_state("t1", "text", {"text": "hi"})

        async def fake_qwen(text):
            return {"decision": "PASS", "confidence": 0.9, "needs_upgrade": False,
                    "violation_type": "none", "reason": "平凡文本", "used_small": True}

        # fast_lane_node 内是局部 import，需 mock 源头类
        from agent_moderation.workers.qwen_judge import QwenLocalJudge
        monkeypatch.setattr(QwenLocalJudge, "judge", fake_qwen)

        out = await fast_lane_node(state)
        assert out["final_decision"] == "PASS"
        assert out["text_result"]["fast_lane"] is True
        assert out["text_result"]["small_model"] is True


class TestBrain:
    def test_brain_decisions_4_types(self):
        """大脑产出 4 类决策（规划/仲裁/升级/终止建议）"""
        state = create_initial_state("t1", "text", {"text": "x"})
        state["_tier"] = "high"
        state["_triage"] = {"risk": 0.95, "complexity": 8, "pre_judgment": "VIOLATION"}
        state = brain_node(state)
        bd = state["_brain_decision"]
        types = {d["type"] for d in bd["decisions"]}
        assert {"plan", "arbitrate", "escalate", "terminate_suggest"} <= types

    def test_brain_terminate_suggest_high_risk(self):
        state = create_initial_state("t1", "text", {"text": "x"})
        state["_triage"] = {"risk": 0.95}
        state = brain_node(state)
        assert state["_brain_decision"]["terminate_suggested"] is True

    def test_brain_no_terminate_low_risk(self):
        state = create_initial_state("t1", "text", {"text": "x"})
        state["_triage"] = {"risk": 0.5}
        state = brain_node(state)
        assert state["_brain_decision"]["terminate_suggested"] is False

    def test_brain_escalate_sets_human_review_signal(self):
        # R20 修复: 大脑 escalate 是软建议（suggested），不得设置 required=True，
        # 否则 risk_agent_node 阶段1 会提前 return，跳过风险评估/终止双签，
        # final_decision 为空（HIGH lane 打通后暴露）。真正的人工介入由
        # risk_agent 的确定性规则触发（见 risk_agent_node 辩论升级分支）。
        state = create_initial_state("t1", "text", {"text": "x"})
        state["_triage"] = {"risk": 0.8}
        state = brain_node(state)
        hr = state.get("_human_review", {})
        assert hr.get("status") == "suggested"
        assert hr.get("required") is False
        # 但大脑仍给出 escalate 决策 + terminate 建议
        decisions = state["_brain_decision"]["decisions"]
        assert any(d["type"] == "escalate" for d in decisions)
        assert state["_brain_decision"]["terminate_suggested"] is False  # 0.8 < 0.9
