"""
分诊台（R6·E2）— 风险×复杂度联合估计，消费 F3 的 ModelRouter

将 ModelRouter 的 tier1-4 分级映射到三车道（low/med/high）：
- low  快车道：小模型判定（qwen2.5 本地 / 规则评分器），无信号升级大模型
- med  标准车道：现有完整流程（LLM 审核）
- high 专家车道：超复杂/超长/强信号堆叠（ModelRouter TIER4_ESCALATE，大脑接管）

保守校准：命中敏感词（tier1 VIOLATION）即使规则可判，也走 med 让 LLM 确认类型；
超长/超复杂（tier4）直接 high。
"""
from dataclasses import dataclass
from enum import Enum

from agent_moderation.workers.model_router import ModelRouter, RouteTier


class LaneTier(str, Enum):
    LOW = "low"  # 快车道
    MED = "med"  # 标准车道
    HIGH = "high"  # 专家车道


@dataclass
class TriageDecision:
    tier: LaneTier
    risk: float  # 0-1 风险估计
    complexity: int  # 0-10 复杂度估计
    pre_judgment: str  # PASS / VIOLATION / UNCERTAIN
    reason: str
    cost_saved: bool = False  # 是否走快车道省掉 LLM


# tier1-4 → 复杂度近似（0-10）
_TIER_COMPLEXITY = {
    RouteTier.TIER1_RULES: 1,
    RouteTier.TIER2_HEURISTIC: 4,
    RouteTier.TIER3_LLM: 7,
    RouteTier.TIER4_ESCALATE: 10,
}


class TriageEngine:
    """分诊台：输入文本 → 三车道决策"""

    def __init__(self, model_router: ModelRouter = None):
        self.router = model_router or ModelRouter()

    def triage(self, text: str, content_type: str = "text") -> TriageDecision:
        rd = self.router.route(text, content_type)

        complexity = _TIER_COMPLEXITY.get(rd.tier, 5)
        risk = _estimate_risk(rd.tier, rd.pre_judgment)

        # —— 车道映射（保守校准）——
        if rd.tier == RouteTier.TIER4_ESCALATE:
            lane = LaneTier.HIGH
        elif rd.tier == RouteTier.TIER1_RULES and rd.pre_judgment == "PASS":
            lane = LaneTier.LOW  # 规则直接判正常，省 LLM
        elif rd.tier == RouteTier.TIER1_RULES and rd.pre_judgment == "VIOLATION":
            lane = LaneTier.MED  # 命中敏感词，需 LLM 确认类型，不直接快车道
        else:
            lane = LaneTier.MED

        return TriageDecision(
            tier=lane,
            risk=risk,
            complexity=complexity,
            pre_judgment=rd.pre_judgment,
            reason=rd.reason,
            cost_saved=(lane == LaneTier.LOW),
        )


def _estimate_risk(tier: RouteTier, pre_judgment: str) -> float:
    """风险估计（0-1）"""
    if pre_judgment == "VIOLATION":
        return 0.8
    if tier == RouteTier.TIER4_ESCALATE:
        return 0.9
    if pre_judgment == "UNCERTAIN":
        return 0.4
    return 0.1  # PASS
