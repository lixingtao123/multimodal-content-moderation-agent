"""
决策/编排域扩展工具（R19·MCP 扩展批 7）

薄封装引擎决策组件（TriageEngine / TerminationChecker / SkillRouter /
CascadeRouter / evidence_fusion）：
  - triage_router          三车道分诊（low/med/high）
  - risk_grade_evaluate    风险定级（综合风险分→级别）
  - termination_double_sign 终止双签校验（确定性硬校验）
  - evidence_fusion        多模态证据融合
  - skill_router_route     技能三级路由
  - model_cascade_route    模型级联路由

组件不可用时返回 degraded 标注（诚实降级）。
"""
from typing import List, Optional
from pydantic import BaseModel


class TriageRouterResult(BaseModel):
    lane: str            # low / med / high
    risk_score: float
    pre_judgment: str
    degraded: bool
    note: str


class TriageRouterTool:
    name = "triage_router"
    description = "三车道分诊（规则快判 low / 标准 med / 复杂 high）"

    async def execute(self, text: str, content_type: str = "text") -> TriageRouterResult:
        try:
            from agent_moderation.workers.triage import TriageEngine

            engine = TriageEngine()
            d = engine.triage(text, content_type)
            return TriageRouterResult(
                lane=d.lane.value, risk_score=round(d.risk_score, 3),
                pre_judgment=d.pre_judgment, degraded=False, note="",
            )
        except Exception as e:
            return TriageRouterResult(lane="med", risk_score=0.0, pre_judgment="UNCERTAIN",
                                      degraded=True, note=f"分诊降级: {e}")


class RiskGradeResult(BaseModel):
    level: str     # low / medium / high / critical
    score: float
    note: str


class RiskGradeEvaluateTool:
    name = "risk_grade_evaluate"
    description = "风险定级（综合风险分 → 级别映射）"

    async def execute(self, risk_score: float = 0.0) -> RiskGradeResult:
        score = max(0.0, min(float(risk_score), 1.0))
        level = "critical" if score >= 0.8 else ("high" if score >= 0.6 else ("medium" if score >= 0.35 else "low"))
        return RiskGradeResult(level=level, score=round(score, 3), note=f"风险分 {score:.2f} → {level}")


class TerminationDoubleSignResult(BaseModel):
    should_terminate: bool
    reasons: List[str]
    degraded: bool
    note: str


class TerminationDoubleSignTool:
    name = "termination_double_sign"
    description = "终止双签校验（高危类型≥0.65 / 硬阈值 0.9 / 双签≥0.75）"

    async def execute(self, risk_score: float = 0.0, violation_types: List[str] = None,
                      agent_agree: bool = False, risk_agent_score: float = 0.0) -> TerminationDoubleSignResult:
        violation_types = violation_types or []
        reasons = []
        # 规则：高危类型 + 高置信
        high_risk_types = {"politics", "adult", "violence", "terror", "drug", "weapon", "gambling", "fraud"}
        hits = [t for t in violation_types if t in high_risk_types]
        if hits and risk_score >= 0.65:
            reasons.append(f"高危类型 {hits} 且风险分 {risk_score:.2f}≥0.65")
        if risk_score >= 0.9:
            reasons.append(f"硬阈值 0.9 命中")
        if agent_agree and risk_agent_score >= 0.75:
            reasons.append(f"双签（Agent+Risk）≥0.75")
        return TerminationDoubleSignResult(
            should_terminate=bool(reasons), reasons=reasons, degraded=False,
            note=f"{len(reasons)} 条终止依据" if reasons else "不满足终止条件",
        )


class EvidenceFusionResult(BaseModel):
    fused_decision: str
    overall_score: float
    modality_weights: dict
    degraded: bool
    note: str


class EvidenceFusionTool:
    name = "evidence_fusion"
    description = "多模态证据融合（非文本中心，按置信度加权）"

    async def execute(self, opinions: List[dict]) -> EvidenceFusionResult:
        try:
            from agent_moderation.workers.evidence_fusion import fuse_modal_opinions

            fused = fuse_modal_opinions(opinions)
            return EvidenceFusionResult(
                fused_decision=fused.get("fused_decision", "UNKNOWN"),
                overall_score=round(float(fused.get("overall_score", 0.0)), 3),
                modality_weights=fused.get("modality_weights", {}),
                degraded=False, note="",
            )
        except Exception as e:
            return EvidenceFusionResult(fused_decision="UNKNOWN", overall_score=0.0,
                                        modality_weights={}, degraded=True, note=f"融合降级: {e}")


class SkillRouteResult(BaseModel):
    selected: List[str]
    degraded: bool
    note: str


class SkillRouterRouteTool:
    name = "skill_router_route"
    description = "技能三级路由（Filter→Rank→Select，返回 Top-N 技能）"

    async def execute(self, task_description: str, top_n: int = 3) -> SkillRouteResult:
        try:
            from agent_moderation.skill_router import SkillRouter

            router = SkillRouter()
            selected = await router.select(task_description, top_n=top_n)
            names = [getattr(s, "name", str(s)) for s in selected]
            return SkillRouteResult(selected=names, degraded=False, note=f"选中 {len(names)} 个技能")
        except Exception as e:
            return SkillRouteResult(selected=[], degraded=True, note=f"路由降级: {e}")


class CascadeRouteResult(BaseModel):
    used_model: str
    reason: str
    confidence: float
    degraded: bool


class ModelCascadeRouteTool:
    name = "model_cascade_route"
    description = "模型级联路由（小模型优先，低置信升级大模型）"

    async def execute(self, text: str, small_confidence: float = 0.9) -> CascadeRouteResult:
        try:
            from agent_moderation.workers.model_cascade import CascadeRouter

            router = CascadeRouter()
            # 只做路由决策（不真正调 API），检查置信度阈值
            if small_confidence >= 0.85:
                return CascadeRouteResult(used_model="small", reason="小模型置信充足", confidence=small_confidence, degraded=False)
            reason = "置信不足，建议升级大模型复核"
            return CascadeRouteResult(used_model="large", reason=reason, confidence=small_confidence, degraded=False)
        except Exception as e:
            return CascadeRouteResult(used_model="small", reason=f"路由降级: {e}", confidence=small_confidence, degraded=True)
