"""
单元测试 — risk_agent 新增 6 类支持（R1 B3）
"""
import pytest

from agent_moderation.agents.risk_agent import RiskAssessmentAgent
from agent_moderation.violation_types import VIOLATION_TYPES


@pytest.fixture
def risk_agent():
    return RiskAssessmentAgent()


class TestRiskAgentNewTypes:
    def test_force_review_covers_all_12_violations(self, risk_agent):
        """原有强制集合不丢失 + 新增 6 类全部纳入强制 REVIEW"""
        base = {"porn", "violence", "politics", "illegal", "phishing", "false_info"}
        assert base <= set(risk_agent.FORCE_REVIEW_TYPES), "原有强制类型丢失"
        new_6 = ["privacy", "discrimination", "crime", "ethics", "health", "copyright"]
        missing = [v for v in new_6 if v not in risk_agent.FORCE_REVIEW_TYPES]
        assert not missing, f"新增类型未纳入强制 REVIEW: {missing}"
        # 注意：harassment/advertisement 是轻度违规，走分数自然判定，不强制升级（设计约定）

    def test_new_types_force_at_least_review(self):
        """新增类型低风险分也至少到 REVIEW 阈值"""
        agent = RiskAssessmentAgent()
        for vt in ["privacy", "discrimination", "crime", "ethics", "health", "copyright"]:
            score = agent._calculate_overall_v2({"text": 0.05}, [vt], "text")
            assert score >= agent.review_threshold, f"{vt} 未被强制 REVIEW"

    def test_decision_review_for_new_type(self):
        """中风险新增类型 → REVIEW"""
        agent = RiskAssessmentAgent()
        assert agent._make_decision(0.5, ["privacy"]) == "REVIEW"

    def test_decision_reject_high_score(self):
        """新增类型高分 → REJECT"""
        agent = RiskAssessmentAgent()
        assert agent._make_decision(0.9, ["crime"]) == "REJECT"

    def test_suggestions_cover_new_6_types(self):
        """类型特化建议覆盖新增 6 类"""
        agent = RiskAssessmentAgent()
        state = {"text_result": {"risk_score": 0.8, "violation_type": "crime"}}
        suggestions = agent._generate_suggestions(state, "REJECT", ["crime"])
        reason_text = " ".join(s.get("reason", "") for s in suggestions)
        assert "违法犯罪" in reason_text or "违法" in reason_text

        # 每个新增类型都能产出类型特化建议（非空 action）
        for vt in ["privacy", "discrimination", "crime", "ethics", "health", "copyright"]:
            sugg = agent._generate_suggestions(state, "REVIEW", [vt])
            type_sugg = [s for s in sugg if vt in s.get("reason", "")]
            # 至少有一条包含该类型的中文 reason
            assert type_sugg, f"{vt} 缺少类型特化建议"
