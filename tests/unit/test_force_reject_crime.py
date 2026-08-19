"""
单元测试 — crime 类型进入强制 REJECT 集合（R20 类型统一）

背景：官方枚举用 crime（violation_types.py），但 risk_agent / termination_check
的 FORCE_REJECT_TYPES 硬编码为 {"violence","illegal"}，导致 text_agent 产出的
crime（违法犯罪）走不到强制 REJECT 路径（T1 的 crime 类样本系统性漏放）。
R20 统一常量后验证：
  - risk_agent：crime 且高风险 → overall 抬升到 REJECT 阈值
  - termination_check：crime + 中高风险 → 硬终止
"""
import pytest

from agent_moderation.agents.risk_agent import RiskAssessmentAgent
from agent_moderation.state import create_initial_state
from agent_moderation.violation_types import (
    FORCE_REJECT_TYPES,
    FORCE_REVIEW_TYPES,
    HIGH_RISK_TYPES,
)
from agent_moderation.workers.termination_check import TerminationChecker


class TestCrimeInForceSets:
    def test_crime_in_force_reject(self):
        """crime 进入统一 FORCE_REJECT_TYPES"""
        assert "crime" in FORCE_REJECT_TYPES

    def test_crime_in_force_review(self):
        assert "crime" in FORCE_REVIEW_TYPES

    def test_crime_in_high_risk(self):
        assert "crime" in HIGH_RISK_TYPES

    def test_illegal_kept_for_backward_compat(self):
        """illegal 保留兼容历史数据/旧链路输出"""
        assert "illegal" in FORCE_REJECT_TYPES


class TestRiskAgentCrime:
    def test_crime_force_reject_score(self):
        """crime + 高风险分量 → overall 抬升到 ≥REJECT 阈值"""
        agent = RiskAssessmentAgent()
        score = agent._calculate_overall_v2({"text": 0.6}, ["crime"], "text")
        assert score >= agent.reject_threshold  # 0.75

    def test_crime_decision_reject(self):
        agent = RiskAssessmentAgent()
        score = agent._calculate_overall_v2({"text": 0.6}, ["crime"], "text")
        assert agent._make_decision(score, ["crime"]) == "REJECT"


class TestTerminationCrime:
    def test_crime_high_risk_terminates(self):
        """crime + 风险分 0.7 → 硬终止（FORCE_REJECT_TYPES 生效）"""
        st = create_initial_state("t", "text", {"text": "x"})
        st["final_risk"] = {"overall_score": 0.7, "violation_types": ["crime"]}
        v = TerminationChecker().check(st)
        assert v["hard_reject"] is True
        assert any("高危类型" in r for r in v["reasons"])

    def test_crime_low_score_no_terminate(self):
        """crime 但风险分低（<0.65）→ 不终止（0.65 门槛）"""
        st = create_initial_state("t", "text", {"text": "x"})
        st["final_risk"] = {"overall_score": 0.3, "violation_types": ["crime"]}
        v = TerminationChecker().check(st)
        assert v["hard_reject"] is False
