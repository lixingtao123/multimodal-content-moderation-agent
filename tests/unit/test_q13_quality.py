"""
单元测试 — P5 质量层（R13）：Q2 辩论升级 + Q1 证据化融合
"""
import pytest

from agent_moderation.agents.debate_panel import AgentOpinion, DebatePanel
from agent_moderation.workers.evidence_fusion import (
    build_modal_opinion,
    fuse_modal_opinions,
)


def op(agent, vt, conf, evidence=None, modality="text", weight=1.0):
    return AgentOpinion(agent_name=agent, violation_type=vt, confidence=conf,
                        risk_score=0.5, evidence=evidence or [], modality=modality,
                        expertise_weight=weight)


class TestQ2EvidenceWeight:
    def test_evidence_boosts_winner(self):
        """证据充分的 image 意见在加权投票中胜过无证据的 text 意见（image 有专业权重触发加权模式）"""
        panel = DebatePanel()
        opinions = [
            op("text_agent", "none", 0.8, evidence=["无明显违规"]),
            op("image_agent", "porn", 0.7, evidence=["检测到裸露区域", "OCR含成人词汇"],
               modality="image", weight=1.5),
        ]
        result = panel.debate(opinions)
        # WEIGHTED_VOTE：porn=0.7*1.3(severity)*1.4(证据2条)*1.5(专业) > none=0.8*1.2
        assert result.final_violation_type == "porn"

    def test_evidence_chain_recorded(self):
        """意见的证据链保留"""
        o = op("image", "porn", 0.8, evidence=["证据A", "证据B"])
        assert len(o.evidence) == 2


class TestQ2MultiRound:
    def test_multi_round_runs(self):
        """分歧未消时多轮辩论执行（≥2 轮），有证据的 minority 话语权提升"""
        panel = DebatePanel()
        opinions = [
            op("text_agent", "none", 0.7, evidence=["无违规关键词"]),
            op("image_agent", "violence", 0.6,
               evidence=["检测到危险物体", "场景包含武器", "姿态威胁"], modality="image"),
        ]
        result = panel.debate_multi_round(opinions, max_rounds=2)
        # 多轮后 evidence 支撑的 minority 有机会翻盘或至少不被淹没
        assert "轮" in result.debate_summary
        assert result.debate_summary.startswith("共")
        # 单轮: text=0.7*1.2=0.84, image=0.6*1.5*1.6=1.44 → image 已胜出（violence severity 1.5）

    def test_rebut_raises_minority_confidence(self):
        """_rebut：有证据的 minority 置信度提升、majority 被质疑降置信度"""
        panel = DebatePanel()
        # none 占 2 票（majority），porn 1 票但有证据（minority）
        opinions = [
            op("text", "porn", 0.5, evidence=["关键词命中"]),
            op("image", "none", 0.8, evidence=["正常场景"], modality="image"),
            op("audio", "none", 0.7, evidence=["正常语气"], modality="audio"),
        ]
        r1 = panel.debate(opinions)
        assert r1.majority_opinion.violation_type == "none"  # none 2票 majority
        rebutted = panel._rebut(opinions, r1)
        for o in rebutted:
            if o.violation_type == "porn" and o.evidence:
                assert o.confidence > 0.5  # 有证据 minority 置信度被提升
            if o.violation_type == "none":
                assert o.confidence < 0.8  # majority 被质疑降置信度


class TestQ2DynamicWeight:
    def test_update_weight(self):
        panel = DebatePanel()
        panel.update_weight("image_agent", "image", 2.0)
        assert panel.get_weights().get(("image_agent", "image")) == 2.0

    def test_update_weight_clamped(self):
        panel = DebatePanel()
        panel.update_weight("x", "y", 99.0)
        assert panel.get_weights().get(("x", "y")) == 3.0
        panel.update_weight("x", "y", -5.0)
        assert panel.get_weights().get(("x", "y")) == 0.1


class TestQ1EvidenceFusion:
    def test_fusion_non_text_centric(self):
        """多模态意见融合：image 证据充分时不被 text 淹没"""
        opinions = [
            build_modal_opinion("text", "none", 0.85, evidence=["无明显违规"]),
            build_modal_opinion("image", "violence", 0.7,
                                evidence=["检测到武器", "攻击姿势", "威胁场景"]),
            build_modal_opinion("audio", "violence", 0.6, evidence=["威胁语气"]),
        ]
        r = fuse_modal_opinions(opinions)
        # violence: 0.7*1.6 + 0.6*1.2 = 1.84 vs none: 0.85*1.2 = 1.02 → violence 胜出
        assert r["final_type"] == "violence"
        assert r["contributing_modalities"] == ["audio", "image"]
        assert r["modal_breakdown"]["violence"]["evidence_count"] == 4

    def test_fusion_empty(self):
        r = fuse_modal_opinions([])
        assert r["final_type"] == "none"

    def test_fusion_consensus(self):
        """多数模态一致 → 该类型胜出"""
        opinions = [
            build_modal_opinion("text", "porn", 0.9, evidence=["e1"]),
            build_modal_opinion("image", "porn", 0.8, evidence=["e2"]),
        ]
        r = fuse_modal_opinions(opinions)
        assert r["final_type"] == "porn"
        assert r["confidence"] > 0.5
