"""
Debate Panel v1.0 — 多 Agent 辩论协作机制

当多个 Agent 对同一内容产生不一致判定时，触发辩论流程:
  1. 各 Agent 提交自己的判定 + 证据 + 置信度
  2. Debate Panel 识别分歧点
  3. 每个 Agent 被要求回应其他 Agent 的论点
  4. 综合所有论点做出最终判定 (投票/协商)

辩论模式:
  - Majority Vote: 简单多数投票
  - Weighted Vote: 按 Agent 专业度和置信度加权
  - Consensus: 需要达成共识 (高置信场景)
  - Escalation: 僵局时升级到 Human-in-the-Loop

技术参考:
  - Multi-Agent Debate (Du et al., 2024): 多 LLM 辩论提升推理准确性
  - ChatDev (Qian et al., 2023): Agent 角色扮演协商
  - LM vs LM (Cohen et al., 2023): 对抗性检测
"""
import copy
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class DebateMode(Enum):
    MAJORITY_VOTE = "majority_vote"
    WEIGHTED_VOTE = "weighted_vote"
    CONSENSUS = "consensus"
    ESCALATE = "escalate"


@dataclass
class AgentOpinion:
    """单个 Agent 的意见"""
    agent_name: str
    violation_type: str
    confidence: float
    risk_score: float
    evidence: List[str] = field(default_factory=list)
    reasoning: str = ""
    modality: str = "text"  # text / image / audio / video
    expertise_weight: float = 1.0  # Agent 在该模态的专业权重


@dataclass
class DebateResult:
    """辩论结果"""
    final_violation_type: str
    final_confidence: float
    final_risk_score: float
    debate_mode: DebateMode
    opinions: List[AgentOpinion]
    majority_opinion: Optional[AgentOpinion] = None
    minority_opinions: List[AgentOpinion] = field(default_factory=list)
    is_consensus: bool = False
    needs_human_review: bool = False
    debate_summary: str = ""


class DebatePanel:
    """
    多 Agent 辩论面板

    使用场景:
    1. 文本 + 图片同时检测 → 结果不一致时触发
    2. 多模态审核 → 一个模态说违规、另一个说正常
    3. 低置信度判定 → 需多方验证
    """

    # 模态专业权重: 每种 Agent 在特定内容类型上的权重
    MODALITY_WEIGHTS = {
        ("text_agent", "text"): 1.2,
        ("image_agent", "image"): 1.2,
        ("audio_agent", "audio"): 1.0,
        ("video_agent", "video"): 1.1,
        ("blackhat_agent", "text"): 0.9,
        ("blackhat_agent", "image"): 0.7,
    }

    # 违规类型严重度权重 (用于加权投票)
    VIOLATION_SEVERITY = {
        "violence": 1.5,
        "porn": 1.3,
        "politics": 1.4,
        "illegal": 1.5,
        "crime": 1.5,  # R20: 官方枚举，与 illegal 同权
        "terrorism": 1.5,
        "phishing": 1.2,
        "advertisement": 0.8,
        "harassment": 1.0,
        "false_info": 1.1,
        "none": 0.0,
    }

    def __init__(self):
        self.debate_history: List[DebateResult] = []

    def collect_opinions(self, state: dict) -> List[AgentOpinion]:
        """从 ModerationState 收集各 Agent 的审核意见"""
        opinions = []
        content_type = state.get("content_type", "text")

        # 文本 Agent 结果 — v3.2: 收集低置信度 none 作为 "uncertain" 意见
        text_result = state.get("text_result")
        if text_result:
            vt = text_result.get("violation_type", "none")
            conf = text_result.get("confidence", 0.0)
            if vt != "none" or (vt == "none" and conf > 0.3 and conf < 0.7):
                # 低置信度 none → Agent 不确定, 标记为 "uncertain"
                effective_vt = vt if vt != "none" else "uncertain"
                effective_conf = conf if vt != "none" else (1.0 - conf)  # 不确定性越高 conf 越低
                opinions.append(AgentOpinion(
                    agent_name="text_agent",
                    violation_type=effective_vt,
                    confidence=effective_conf,
                    risk_score=text_result.get("risk_score", 0.0),
                    evidence=self._extract_evidence(text_result),
                    reasoning=text_result.get("reason", ""),
                    modality=content_type,
                    expertise_weight=self._get_weight("text_agent", content_type),
                ))

        # 图片 Agent 结果 — v3.2: 收集低置信度 none 作为 "uncertain" 意见
        image_result = state.get("image_result")
        if image_result:
            vt = image_result.get("violation_type", "none")
            conf = image_result.get("confidence", 0.0)
            if vt != "none" or (vt == "none" and conf > 0.3 and conf < 0.7):
                effective_vt = vt if vt != "none" else "uncertain"
                effective_conf = conf if vt != "none" else (1.0 - conf)
                opinions.append(AgentOpinion(
                    agent_name="image_agent",
                    violation_type=effective_vt,
                    confidence=effective_conf,
                    risk_score=image_result.get("risk_score", 0.0),
                    evidence=self._extract_evidence(image_result),
                    reasoning=image_result.get("reason", ""),
                    modality="image",
                    expertise_weight=self._get_weight("image_agent", "image"),
                ))

        # 音频 Agent 结果 — v3.2: 收集低置信度 none 作为 "uncertain" 意见
        audio_result = state.get("audio_result")
        if audio_result:
            vt = audio_result.get("violation_type", "none")
            conf = audio_result.get("confidence", 0.0)
            if vt != "none" or (vt == "none" and conf > 0.3 and conf < 0.7):
                effective_vt = vt if vt != "none" else "uncertain"
                effective_conf = conf if vt != "none" else (1.0 - conf)
                opinions.append(AgentOpinion(
                    agent_name="audio_agent",
                    violation_type=effective_vt,
                    confidence=effective_conf,
                    risk_score=audio_result.get("risk_score", 0.0),
                    evidence=self._extract_evidence(audio_result),
                    reasoning=audio_result.get("reason", ""),
                    modality="audio",
                    expertise_weight=self._get_weight("audio_agent", "audio"),
                ))

        # 视频 Agent 结果
        video_result = state.get("video_result")
        if video_result and not video_result.get("error"):
            opinions.extend(self._extract_video_opinions(video_result))

        # 黑灰产 Agent 结果 — 仅计入真正的违规类型，排除检测方法类模式
        NON_VIOLATION_PATTERNS = {"BULK_GENERATION", "KEYWORD_VARIANT", "FORMAT_SPOOFING"}
        blackhat_result = state.get("blackhat_result")
        if blackhat_result:
            patterns = blackhat_result.get("pattern_detected", [])
            for p in patterns:
                ptype = p.get("type", "")
                if ptype and ptype != "none" and ptype not in NON_VIOLATION_PATTERNS:
                    opinions.append(AgentOpinion(
                        agent_name="blackhat_agent",
                        violation_type=ptype,
                        confidence=p.get("confidence", 0.0),
                        risk_score=p.get("risk_score", 0.0),
                        evidence=[p.get("name", "")],
                        reasoning=f"模式检测: {p.get('name', '')}",
                        modality=content_type,
                        expertise_weight=self._get_weight("blackhat_agent", content_type),
                    ))

        return opinions

    def _extract_evidence(self, result: dict) -> List[str]:
        """提取审核证据"""
        evidence = []
        if result.get("keyword_matches"):
            evidence.append(f"敏感词: {len(result['keyword_matches'])} 个")
        if result.get("similar_cases_count", 0) > 0:
            evidence.append(f"相似案例: {result['similar_cases_count']} 个")
        if result.get("tags"):
            evidence.append(f"标签: {result['tags']}")
        if result.get("suspicious_elements"):
            evidence.append(f"可疑元素: {result['suspicious_elements'][:3]}")
        if result.get("is_adversarial"):
            evidence.append("检测到对抗样本")
        return evidence

    def _extract_video_opinions(self, video_result: dict) -> List[AgentOpinion]:
        """从视频结果提取多个意见 (每个高风险帧一个意见)"""
        opinions = []
        frame_results = video_result.get("frame_results", [])
        for f in frame_results:
            vt = f.get("violation_type", "none")
            if vt != "none" and f.get("confidence", 0) > 0.3:
                opinions.append(AgentOpinion(
                    agent_name="video_agent",
                    violation_type=vt,
                    confidence=f.get("confidence", 0.0),
                    risk_score=f.get("confidence", 0.0) * 0.7,
                    evidence=[f"帧@{f.get('timestamp', 0):.1f}s: {f.get('reason', '')}"],
                    reasoning=f.get("reason", ""),
                    modality="video",
                    expertise_weight=self._get_weight("video_agent", "video"),
                ))
        return opinions

    def _get_weight(self, agent_name: str, modality: str) -> float:
        """获取 Agent 权重"""
        return self.MODALITY_WEIGHTS.get((agent_name, modality), 1.0)

    def debate(self, opinions: List[AgentOpinion], mode: Optional[DebateMode] = None) -> DebateResult:
        """
        执行辩论流程

        Args:
            opinions: 各 Agent 的意见
            mode: 辩论模式 (None = 自动选择)

        Returns:
            辩论结果
        """
        if not opinions:
            return DebateResult(
                final_violation_type="none",
                final_confidence=0.0,
                final_risk_score=0.0,
                debate_mode=DebateMode.MAJORITY_VOTE,
                opinions=[],
                debate_summary="无 Agent 提交意见，默认为正常内容",
            )

        # 检查是否需要辩论
        unique_types = set(o.violation_type for o in opinions)
        if len(unique_types) == 1:
            # 所有 Agent 意见一致 → 快速共识
            return self._fast_consensus(opinions, list(unique_types)[0])

        # 选择辩论模式
        if mode is None:
            mode = self._select_mode(opinions)
        logger.info(f"Debate triggered: {len(opinions)} opinions, {len(unique_types)} unique types, mode={mode.value}")

        if mode == DebateMode.MAJORITY_VOTE:
            result = self._majority_vote(opinions)
        elif mode == DebateMode.WEIGHTED_VOTE:
            result = self._weighted_vote(opinions)
        elif mode == DebateMode.CONSENSUS:
            result = self._seek_consensus(opinions)
        else:
            result = self._escalate(opinions)

        self.debate_history.append(result)
        return result

    # ============================================================
    # R13·Q2: 多轮辩论 + 动态权重（升级单轮投票 → 证据化多轮互相反驳）
    # ============================================================
    def debate_multi_round(self, opinions: List[AgentOpinion],
                           max_rounds: int = 2) -> DebateResult:
        """多轮辩论：分歧未消时，minority 补充证据后互相反驳再投，上限 max_rounds 轮。

        Round 1: 正常投票
        Round 2+: 有证据的 minority 提升话语权、majority 置信度微降 → 再投
        """
        result = self.debate(opinions)
        rounds = 1
        while rounds < max_rounds and not result.is_consensus:
            rebutted = self._rebut(opinions, result)
            result = self.debate(rebutted)
            rounds += 1
            result.debate_summary = f"{result.debate_summary}（第{rounds}轮反驳）"
        result.debate_summary = f"共{rounds}轮辩论 | {result.debate_summary}"
        return result

    def _rebut(self, opinions: List[AgentOpinion], result: DebateResult) -> List[AgentOpinion]:
        """第二轮反驳：minority 有证据则话语权↑；majority 受反驳置信度微降"""
        majority_type = result.majority_opinion.violation_type if result.majority_opinion else None
        minority_types = {o.violation_type for o in result.minority_opinions}
        rebutted: List[AgentOpinion] = []
        for o in opinions:
            no = copy.deepcopy(o)
            if o.violation_type in minority_types and o.evidence:
                # 有证据支撑的 minority 提升话语权
                no.confidence = min(1.0, o.confidence * 1.15)
                no.expertise_weight = o.expertise_weight * 1.1
                no.reasoning = (o.reasoning + " [反驳: 我有证据支撑]").strip()
            elif majority_type and o.violation_type == majority_type:
                # majority 受到反驳 → 置信度微降（不盲目坚持）
                no.confidence = max(0.1, o.confidence * 0.95)
                no.reasoning = (o.reasoning + " [被反驳质疑]").strip()
            rebutted.append(no)
        return rebutted

    def update_weight(self, agent_name: str, modality: str, weight: float) -> None:
        """R13·Q2: 权重动态化 — 基于历史准确率更新某 Agent 的专业权重"""
        self.MODALITY_WEIGHTS[(agent_name, modality)] = max(0.1, min(3.0, weight))

    def get_weights(self) -> dict:
        """当前全部权重快照"""
        return dict(self.MODALITY_WEIGHTS)

    def _select_mode(self, opinions: List[AgentOpinion]) -> DebateMode:
        """自动选择辩论模式"""
        max_confidence = max(o.confidence for o in opinions)
        avg_confidence = sum(o.confidence for o in opinions) / len(opinions)
        unique_types = set(o.violation_type for o in opinions)

        # v3.2: "uncertain" 类型一律升级人工 (Agent 不确定的模糊case)
        if "uncertain" in unique_types:
            return DebateMode.ESCALATE

        # 低置信度 + 多分歧 → 升级人工
        if avg_confidence < 0.5 and len(unique_types) >= 3:
            return DebateMode.ESCALATE

        # 高置信度 → 要求共识
        if max_confidence > 0.85:
            return DebateMode.CONSENSUS

        # 有专业 Agent (权重 != 1.0) → 加权投票
        if any(o.expertise_weight != 1.0 for o in opinions):
            return DebateMode.WEIGHTED_VOTE

        return DebateMode.MAJORITY_VOTE

    def _majority_vote(self, opinions: List[AgentOpinion]) -> DebateResult:
        """简单多数投票"""
        # 按违规类型分组
        type_votes: Dict[str, List[AgentOpinion]] = {}
        for o in opinions:
            if o.violation_type not in type_votes:
                type_votes[o.violation_type] = []
            type_votes[o.violation_type].append(o)

        # 找票数最多
        sorted_types = sorted(type_votes.items(), key=lambda x: len(x[1]), reverse=True)
        winner_type, winner_opinions = sorted_types[0]

        # 计算最终分数
        avg_confidence = sum(o.confidence for o in winner_opinions) / len(winner_opinions)
        avg_risk = sum(o.risk_score for o in winner_opinions) / len(winner_opinions)

        return DebateResult(
            final_violation_type=winner_type,
            final_confidence=round(avg_confidence, 4),
            final_risk_score=round(avg_risk, 4),
            debate_mode=DebateMode.MAJORITY_VOTE,
            opinions=opinions,
            majority_opinion=winner_opinions[0],
            minority_opinions=[o for o in opinions if o.violation_type != winner_type],
            is_consensus=(len(sorted_types) == 1),
            needs_human_review=(avg_confidence < 0.5),
            debate_summary=f"多数投票: {winner_type} ({len(winner_opinions)}/{len(opinions)} 票)",
        )

    def _weighted_vote(self, opinions: List[AgentOpinion]) -> DebateResult:
        """加权投票: 考虑 Agent 专业度和违规严重度"""
        type_scores: Dict[str, float] = {}
        type_opinions: Dict[str, List[AgentOpinion]] = {}

        for o in opinions:
            if o.violation_type not in type_scores:
                type_scores[o.violation_type] = 0.0
                type_opinions[o.violation_type] = []

            severity = self.VIOLATION_SEVERITY.get(o.violation_type, 1.0)
            # R13·Q2: 证据加权 — 有证据链的 opinion 话语权提升（证据充分者更可信）
            evidence_bonus = 1.0 + 0.2 * min(len(o.evidence or []), 3)
            weight = o.expertise_weight * severity * o.confidence * evidence_bonus
            type_scores[o.violation_type] += weight
            type_opinions[o.violation_type].append(o)

        # 找得分最高
        winner_type = max(type_scores, key=type_scores.get)
        winner_opinions = type_opinions[winner_type]

        avg_confidence = sum(o.confidence for o in winner_opinions) / len(winner_opinions)
        avg_risk = sum(o.risk_score for o in winner_opinions) / len(winner_opinions)

        return DebateResult(
            final_violation_type=winner_type,
            final_confidence=round(avg_confidence, 4),
            final_risk_score=round(avg_risk, 4),
            debate_mode=DebateMode.WEIGHTED_VOTE,
            opinions=opinions,
            majority_opinion=winner_opinions[0],
            minority_opinions=[o for o in opinions if o.violation_type != winner_type],
            is_consensus=(len(type_scores) == 1),
            needs_human_review=(avg_confidence < 0.45),
            debate_summary=f"加权投票: {winner_type} (得分 {type_scores[winner_type]:.2f})",
        )

    def _seek_consensus(self, opinions: List[AgentOpinion]) -> DebateResult:
        """寻求共识: 高置信度时要求 Agent 间互相验证"""
        # 检查 Agent 意见是否可以调和
        type_groups: Dict[str, List[AgentOpinion]] = {}
        for o in opinions:
            if o.violation_type not in type_groups:
                type_groups[o.violation_type] = []
            type_groups[o.violation_type].append(o)

        # 取最高平均置信度的类型
        best_type = None
        best_score = 0.0
        for vt, ops in type_groups.items():
            avg_conf = sum(o.confidence for o in ops) / len(ops)
            avg_risk = sum(o.risk_score for o in ops) / len(ops)
            score = avg_conf * 0.6 + avg_risk * 0.4
            if score > best_score:
                best_score = score
                best_type = vt

        if best_type is None:
            return self._majority_vote(opinions)

        best_opinions = type_groups[best_type]
        avg_conf = sum(o.confidence for o in best_opinions) / len(best_opinions)
        avg_risk = sum(o.risk_score for o in best_opinions) / len(best_opinions)

        # 共识度: 支持此类型的 Agent 占比
        consensus_ratio = len(best_opinions) / len(opinions)

        return DebateResult(
            final_violation_type=best_type,
            final_confidence=round(avg_conf, 4),
            final_risk_score=round(avg_risk, 4),
            debate_mode=DebateMode.CONSENSUS,
            opinions=opinions,
            majority_opinion=best_opinions[0],
            minority_opinions=[o for o in opinions if o.violation_type != best_type],
            is_consensus=(consensus_ratio >= 0.8),
            needs_human_review=(consensus_ratio < 0.6),
            debate_summary=f"共识判定: {best_type} (共识度 {consensus_ratio:.0%})",
        )

    def _escalate(self, opinions: List[AgentOpinion]) -> DebateResult:
        """升级到人工审核"""
        # 标记所有违规类型
        all_types = list(set(o.violation_type for o in opinions))
        avg_risk = sum(o.risk_score for o in opinions) / len(opinions)

        return DebateResult(
            final_violation_type="|".join(all_types),
            final_confidence=0.3,
            final_risk_score=round(avg_risk, 4),
            debate_mode=DebateMode.ESCALATE,
            opinions=opinions,
            is_consensus=False,
            needs_human_review=True,
            debate_summary=f"升级人工: {len(all_types)} 种违规类型分歧 ({', '.join(all_types)})",
        )

    def _fast_consensus(self, opinions: List[AgentOpinion], violation_type: str) -> DebateResult:
        """快速共识 (所有 Agent 意见一致)"""
        avg_conf = sum(o.confidence for o in opinions) / len(opinions)
        avg_risk = sum(o.risk_score for o in opinions) / len(opinions)

        return DebateResult(
            final_violation_type=violation_type,
            final_confidence=round(avg_conf, 4),
            final_risk_score=round(avg_risk, 4),
            debate_mode=DebateMode.CONSENSUS,
            opinions=opinions,
            majority_opinion=opinions[0],
            minority_opinions=[],
            is_consensus=True,
            needs_human_review=False,
            debate_summary=f"快速共识: 所有 Agent 一致判定为 {violation_type}",
        )
