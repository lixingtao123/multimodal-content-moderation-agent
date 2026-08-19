"""
运维/优化域扩展工具（R19·MCP 扩展批 8）

封装或确定性实现：
  - regression_guard_check  优化回归守卫（变差自动回滚判定）
  - tool_telemetry_report   工具遥测质量分
  - violation_type_lookup   违规类型字典查询
  - policy_lookup           生效策略查询
  - system_health           系统组件健康状态
"""
from typing import List, Optional
from pydantic import BaseModel


class RegressionGuardResult(BaseModel):
    should_rollback: bool
    reason: str
    delta: float
    degraded: bool


class RegressionGuardCheckTool:
    name = "regression_guard_check"
    description = "回归守卫判定（关键指标变差 → 建议回滚）"

    async def execute(self, before_score: float = 0.0, after_score: float = 0.0,
                      threshold: float = 0.01) -> RegressionGuardResult:
        try:
            from optimization.regression_guard import regressed

            is_reg = regressed({"f1": before_score}, {"f1": after_score})
            delta = after_score - before_score
            return RegressionGuardResult(
                should_rollback=is_reg,
                reason=f"指标 {before_score:.4f} → {after_score:.4f}（Δ{delta:+.4f}）" + ("，建议回滚" if is_reg else ""),
                delta=round(delta, 4), degraded=False,
            )
        except Exception as e:
            return RegressionGuardResult(should_rollback=False, reason=f"判定降级: {e}", delta=0.0, degraded=True)


class TelemetryReportResult(BaseModel):
    quality_score: float
    suggestion: str
    snapshot: dict
    degraded: bool


class ToolTelemetryReportTool:
    name = "tool_telemetry_report"
    description = "工具遥测质量报告（成功率/质量分/使用建议）"

    async def execute(self, tool_name: str = "") -> TelemetryReportResult:
        try:
            from mcp_servers.tool_telemetry import get_tool_telemetry

            tele = get_tool_telemetry()
            snap = tele.snapshot()
            if tool_name:
                score = tele.quality_score(tool_name)
                return TelemetryReportResult(
                    quality_score=round(score, 3),
                    suggestion=tele.suggest(tool_name),
                    snapshot={tool_name: snap.get(tool_name, {})}, degraded=False,
                )
            return TelemetryReportResult(
                quality_score=0.0, suggestion="", snapshot=snap, degraded=False,
            )
        except Exception as e:
            return TelemetryReportResult(quality_score=0.0, suggestion="", snapshot={}, degraded=True)


class ViolationTypeLookupResult(BaseModel):
    types: List[dict]
    count: int
    degraded: bool


class ViolationTypeLookupTool:
    name = "violation_type_lookup"
    description = "查询违规类型字典（13 类枚举 + 中文名 + 描述）"

    async def execute(self, category: str = "") -> ViolationTypeLookupResult:
        try:
            from agent_moderation.violation_types import VIOLATION_TYPES, VIOLATION_CN

            items = []
            for vt in VIOLATION_TYPES:
                if category and category != vt:
                    continue
                items.append({
                    "type": vt,
                    "cn": VIOLATION_CN.get(vt, vt),
                })
            return ViolationTypeLookupResult(types=items, count=len(items), degraded=False)
        except Exception as e:
            return ViolationTypeLookupResult(types=[], count=0, degraded=True)


class PolicyLookupResult(BaseModel):
    policy_id: str
    type: str
    enabled: bool
    degraded: bool


class PolicyLookupTool:
    name = "policy_lookup"
    description = "查询生效策略（数据库查询，失败降级返回默认）"

    async def execute(self, policy_type: str = "moderation") -> PolicyLookupResult:
        try:
            from db.connection import get_session_factory, get_sync_engine
            from db.models import Policy
            from sqlalchemy import select

            engine = get_sync_engine()
            from sqlalchemy.orm import Session
            with Session(engine) as session:
                row = session.execute(
                    select(Policy).where(Policy.policy_type == policy_type, Policy.is_active == True)  # noqa: E712
                ).scalars().first()
                if row:
                    return PolicyLookupResult(policy_id=str(getattr(row, "id", "")), type=policy_type,
                                              enabled=True, degraded=False)
            return PolicyLookupResult(policy_id="", type=policy_type, enabled=False, degraded=True)
        except Exception as e:
            return PolicyLookupResult(policy_id="", type=policy_type, enabled=False, degraded=True)


class SystemHealthResult(BaseModel):
    components: dict
    overall: str   # ok / degraded / unavailable
    degraded: bool


class SystemHealthTool:
    name = "system_health"
    description = "系统组件健康状态（Redis/Chroma/DB 探测）"

    async def execute(self) -> SystemHealthResult:
        components = {}
        # Redis 探测
        try:
            from memory.redis_service import get_redis_service
            svc = get_redis_service()
            components["redis"] = "ok" if await svc._ensure() else "unavailable"
        except Exception:
            components["redis"] = "error"
        # Chroma 探测
        try:
            from memory.chroma_service import get_chroma_service
            svc = get_chroma_service()
            await svc.connect()
            components["chroma"] = "ok" if svc.collection is not None else "unavailable"
        except Exception:
            components["chroma"] = "unavailable"
        # DB 探测
        try:
            from db.connection import get_sync_engine
            from sqlalchemy import text
            get_sync_engine().connect().execute(text("SELECT 1"))
            components["db"] = "ok"
        except Exception:
            components["db"] = "unavailable"
        bad = [k for k, v in components.items() if v != "ok"]
        overall = "ok" if not bad else ("degraded" if len(bad) < len(components) else "unavailable")
        return SystemHealthResult(components=components, overall=overall, degraded=bool(bad))
