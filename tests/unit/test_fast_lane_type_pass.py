"""
单元测试 — fast_lane 透传小模型违规类型（R20）

背景：此前 fast_lane_node 小模型 REJECT/REVIEW 时 violation_type 写死 "none"，
REJECT 记录无违规类型，下游按类型分析/强制终止全部失效。
R20 修复后验证：小模型 REJECT(violation_type=crime) → final_risk 含 ["crime"]。
"""
import pytest

from agent_moderation.state import create_initial_state
from agent_moderation.workflows.moderation import fast_lane_node


@pytest.mark.asyncio
async def test_fast_lane_reject_passes_type(monkeypatch):
    """小模型 REJECT + 违规类型 → 类型透传到 text_result/final_risk"""

    class FakeQwen:
        async def judge(self, text):
            return {"decision": "REJECT", "confidence": 0.9,
                    "violation_type": "crime", "reason": "涉罪", "used_small": True}

    monkeypatch.setattr("agent_moderation.workers.qwen_judge.QwenLocalJudge", FakeQwen)

    state = create_initial_state("t", "text", {"text": "制作枪支出售教程"})
    out = await fast_lane_node(state)

    assert out["final_decision"] == "REJECT"
    assert out["final_risk"]["violation_types"] == ["crime"]
    assert out["text_result"]["violation_type"] == "crime"
    assert out["text_result"]["small_model"] is True


@pytest.mark.asyncio
async def test_fast_lane_review_passes_type(monkeypatch):
    """小模型 REVIEW + 类型 → 透传（REVIEW 也是拦截）"""

    class FakeQwen:
        async def judge(self, text):
            return {"decision": "REVIEW", "confidence": 0.7,
                    "violation_type": "privacy", "reason": "疑似隐私", "used_small": True}

    monkeypatch.setattr("agent_moderation.workers.qwen_judge.QwenLocalJudge", FakeQwen)

    state = create_initial_state("t", "text", {"text": "查询你的住址信息"})
    out = await fast_lane_node(state)

    assert out["final_decision"] == "REVIEW"
    assert out["final_risk"]["violation_types"] == ["privacy"]


@pytest.mark.asyncio
async def test_fast_lane_pass_no_type(monkeypatch):
    """小模型 PASS + none → 保持无类型（不误标）"""

    class FakeQwen:
        async def judge(self, text):
            return {"decision": "PASS", "confidence": 0.9,
                    "violation_type": "none", "reason": "安全", "used_small": True}

    monkeypatch.setattr("agent_moderation.workers.qwen_judge.QwenLocalJudge", FakeQwen)

    state = create_initial_state("t", "text", {"text": "今天天气真好"})
    out = await fast_lane_node(state)

    assert out["final_decision"] == "PASS"
    assert out["final_risk"]["violation_types"] == []
    assert out["text_result"]["violation_type"] == "none"
