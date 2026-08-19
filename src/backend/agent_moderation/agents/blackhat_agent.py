"""
Blackhat Agent — 黑灰产识别
串联 PatternDetector + AdversarialDetector + AccountRiskProfiler
检测批量操作模式、对抗样本、账号风险
"""
import logging
from agent_moderation.state import ModerationState
from agent_moderation.agents.base import BaseAgent
from agent_moderation.blackhat.pattern_detector import PatternDetector
from agent_moderation.blackhat.adversarial_detector import AdversarialDetector
from agent_moderation.blackhat.account_risk import get_account_profiler
from memory.manager import get_memory_manager

logger = logging.getLogger(__name__)


class BlackhatAgent(BaseAgent):
    """黑灰产识别 Agent"""

    def __init__(self):
        super().__init__("blackhat_agent")
        self.pattern_detector = PatternDetector()
        self.adversarial_detector = AdversarialDetector()
        self.account_profiler = get_account_profiler()
        self.memory = get_memory_manager()

    async def process(self, state: ModerationState) -> ModerationState:
        """黑灰产识别全流程"""
        await self.memory.update_task_step(state["content_id"], "blackhat_agent")

        # 获取审核文本（多模态来源）
        text = self._extract_text(state)
        account_id = state.get("account_id")

        if not text:
            state["blackhat_result"] = {
                "pattern_detected": [],
                "adversarial_detected": [],
                "account_risk": None,
                "blackhat_risk_score": 0.0,
            }
            return state

        self.log_step(f"Analyzing for blackhat patterns in text ({len(text)} chars)")

        # 1. 违规模式检测
        patterns = self.pattern_detector.detect_all(text)
        self.log_step(f"Patterns detected: {len(patterns)}")

        # 2. 对抗样本检测
        adversarial = self.adversarial_detector.detect_all(text)
        self.log_step(f"Adversarial techniques: {len(adversarial)}")

        # 3. 账号风险画像更新
        account_risk = None
        if account_id:
            # 收集违规信息
            violation_type = self._get_violation_type(state)
            risk_score = self._get_risk_score(state)

            pattern_types = [p.pattern_type for p in patterns]
            adv_techniques = [a.technique for a in adversarial]

            self.account_profiler.record_violation(
                account_id=account_id,
                violation_type=violation_type,
                risk_score=risk_score,
                patterns=list(set(pattern_types + adv_techniques)),
            )
            account_risk = self.account_profiler.get_profile(account_id).to_dict()

        # 4. 计算黑灰产综合风险分
        blackhat_score = self._calculate_blackhat_score(patterns, adversarial, account_risk)

        state["blackhat_result"] = {
            "pattern_detected": [
                {
                    "type": p.pattern_type,
                    "name": p.pattern_name,
                    "confidence": p.confidence,
                    "evidence": p.evidence[:3],
                    "risk_score": p.risk_score,
                }
                for p in patterns
            ],
            "adversarial_detected": [
                {
                    "technique": a.technique,
                    "confidence": a.confidence,
                    "evidence": a.evidence[:3],
                    "risk_score": a.risk_score,
                }
                for a in adversarial
            ],
            "account_risk": account_risk,
            "blackhat_risk_score": blackhat_score,
            "is_blackhat": blackhat_score >= 0.4,
        }

        return state

    def _extract_text(self, state: ModerationState) -> str:
        """从不同模态提取文本"""
        content = state.get("content", {})
        content_type = state.get("content_type", "text")

        if content_type == "text":
            return content.get("text", "")

        # 从审核结果中提取文字
        if content_type == "image" and state.get("image_result"):
            ocr = state["image_result"].get("ocr_text", "")
            return ocr if ocr else ""

        if content_type == "audio" and state.get("audio_result"):
            return state["audio_result"].get("transcribed_text", "")

        if content_type == "video":
            # 视频：合并音频转写文字 + 帧OCR
            texts = []
            if state.get("video_result"):
                audio_text = state["video_result"].get("audio_text", "")
                if audio_text:
                    texts.append(audio_text)
            if state.get("audio_result"):
                texts.append(state["audio_result"].get("transcribed_text", ""))
            return " ".join(texts)

        return ""

    def _get_violation_type(self, state: ModerationState) -> str:
        """获取审核判定的违规类型"""
        final_risk = state.get("final_risk") or {}
        types = final_risk.get("violation_types", [])
        return types[0] if types else "none"

    def _get_risk_score(self, state: ModerationState) -> float:
        """获取审核的综合风险分"""
        final_risk = state.get("final_risk") or {}
        return final_risk.get("overall_score", 0.0)

    def _calculate_blackhat_score(
        self, patterns: list, adversarial: list, account_risk: dict
    ) -> float:
        """计算黑灰产综合风险分"""
        score = 0.0

        # 模式检测贡献 (max 0.4)
        if patterns:
            max_pattern_score = max(p.risk_score for p in patterns)
            avg_pattern_score = sum(p.risk_score for p in patterns) / len(patterns)
            score += max_pattern_score * 0.25 + avg_pattern_score * 0.15

        # 对抗检测贡献 (max 0.3)
        if adversarial:
            max_adv_score = max(a.risk_score for a in adversarial)
            avg_adv_score = sum(a.risk_score for a in adversarial) / len(adversarial)
            score += max_adv_score * 0.2 + avg_adv_score * 0.1

        # 账号风险贡献 (max 0.3)
        if account_risk:
            score += account_risk.get("risk_score", 0.0) * 0.3

        return round(min(score, 1.0), 4)
