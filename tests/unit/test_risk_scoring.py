"""
单元测试 — 风险评估分数计算逻辑 v2
"""
import pytest
from agent_moderation.agents.risk_agent import RiskAssessmentAgent


@pytest.fixture
def risk_agent():
    return RiskAssessmentAgent()


class TestRiskScoring:
    def test_empty_components(self, risk_agent):
        """无风险分量时总分应为 0"""
        score = risk_agent._calculate_overall_v2({}, [], "text")
        assert score == 0.0

    def test_single_component(self, risk_agent):
        """单一风险分量"""
        score = risk_agent._calculate_overall_v2({"text": 0.8}, [], "text")
        # max*0.6 + avg*0.4 = 0.8*0.6 + 0.8*0.4 = 0.8
        assert score > 0.7
        assert score <= 1.0

    def test_max_pooling_dominance(self, risk_agent):
        """高违规分应取 max pooling 主导"""
        score = risk_agent._calculate_overall_v2({"text": 0.9, "image": 0.1}, [], "text")
        # max=0.9, avg=0.5, with 2 components: (0.9*0.6+0.5*0.4)*1.1 = 0.814
        assert score > 0.6

    def test_all_clean(self, risk_agent):
        """所有模态都干净"""
        score = risk_agent._calculate_overall_v2({}, [], "text")
        assert score == 0.0

    def test_decision_pass(self, risk_agent):
        """低风险 → PASS"""
        state = {"text_result": {"risk_score": 0.1}}
        components = risk_agent._collect_components(state)
        score = risk_agent._calculate_overall_v2(components, [], "text")
        # v3.x: REVIEW 阈值改为动态加载（策略缓存 + 回退默认 0.35）
        assert score < risk_agent.review_threshold

    def test_decision_review_threshold(self, risk_agent):
        """中等风险 → REVIEW 区间"""
        state = {"text_result": {"risk_score": 0.55}}
        components = risk_agent._collect_components(state)
        score = risk_agent._calculate_overall_v2(components, [], "text")
        assert score >= risk_agent.review_threshold

    def test_score_bounds(self, risk_agent):
        """分数不应超过 0.0 ~ 1.0"""
        score = risk_agent._calculate_overall_v2(
            {"text": 2.0, "image": 5.0, "audio": 1.5}, [], "text"
        )
        assert 0.0 <= score <= 1.0

    def test_blackhat_component(self, risk_agent):
        """黑灰产风险应被计入"""
        state = {
            "text_result": {"risk_score": 0.3},
            "blackhat_result": {"blackhat_risk_score": 0.9},
        }
        components = risk_agent._collect_components(state)
        assert "blackhat" in components
        assert components["blackhat"] == 0.9

    def test_force_review_for_porn(self, risk_agent):
        """色情内容应强制至少 REVIEW"""
        score = risk_agent._calculate_overall_v2(
            {"image": 0.1}, ["porn"], "image"
        )
        assert score >= risk_agent.review_threshold

    def test_make_decision_reject(self, risk_agent):
        """高风险 → REJECT"""
        decision = risk_agent._make_decision(0.85, ["violence"])
        assert decision == "REJECT"

    def test_make_decision_pass(self, risk_agent):
        """低风险 → PASS"""
        decision = risk_agent._make_decision(0.1, [])
        assert decision == "PASS"

    def test_collect_violation_types_from_image(self, risk_agent):
        """从图片结果收集违规类型"""
        state = {
            "image_result": {"violation_type": "advertisement", "confidence": 0.8, "tags": ["广告"]}
        }
        types = risk_agent._collect_violation_types(state)
        assert "advertisement" in types
