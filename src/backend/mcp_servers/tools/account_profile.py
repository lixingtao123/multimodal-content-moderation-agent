"""
账号风控域扩展工具（R19·MCP 扩展批 5）

确定性规则实现（本地计算，不依赖外部风控服务）：
  - account_behavior_anomaly   行为异常评分（频率/时段/突变）
  - account_device_risk        设备风险（越狱/模拟器/多开信号）
  - user_reputation            用户信誉分（历史违规/活跃/反馈综合）
"""
from typing import List, Optional
from pydantic import BaseModel


class BehaviorAnomalyResult(BaseModel):
    score: float
    level: str   # normal / suspicious / high_risk
    signals: List[str]
    summary: str


class AccountBehaviorAnomalyTool:
    name = "account_behavior_anomaly"
    description = "账号行为异常评分（发帖频率/夜间活跃/新账号突变）"

    async def execute(self, posts_last_hour: int = 0, posts_per_day_avg: float = 0.0,
                      night_ratio: float = 0.0, account_age_days: int = 0,
                      daily_posts: float = 0.0) -> BehaviorAnomalyResult:
        signals, score = [], 0.0
        # 高频发帖
        if posts_last_hour >= 20:
            score += 0.4
            signals.append(f"1小时内 {posts_last_hour} 帖（远超常人）")
        elif posts_last_hour >= 10:
            score += 0.2
            signals.append(f"1小时内 {posts_last_hour} 帖")
        # 夜间活跃
        if night_ratio > 0.7:
            score += 0.2
            signals.append(f"夜间活跃占比 {night_ratio:.0%}")
        # 新账号突变
        if account_age_days < 7 and daily_posts > posts_per_day_avg * 3 + 10:
            score += 0.3
            signals.append("新账号且发帖量异常")
        score = min(score, 1.0)
        level = "high_risk" if score >= 0.6 else ("suspicious" if score >= 0.3 else "normal")
        return BehaviorAnomalyResult(
            score=round(score, 3), level=level, signals=signals,
            summary=f"行为异常分 {score:.2f}（{level}）",
        )


class DeviceRiskResult(BaseModel):
    risk_score: float
    level: str
    flags: List[str]
    summary: str


class AccountDeviceRiskTool:
    name = "account_device_risk"
    description = "设备风险信号评估（越狱/模拟器/多开/IP 池化特征）"

    async def execute(self, is_jailbroken: bool = False, is_emulator: bool = False,
                      multi_open: bool = False, ip_shared_count: int = 1,
                      new_device: bool = False) -> DeviceRiskResult:
        flags, score = [], 0.0
        if is_jailbroken:
            score += 0.4
            flags.append("越狱/ROOT")
        if is_emulator:
            score += 0.35
            flags.append("模拟器")
        if multi_open:
            score += 0.25
            flags.append("多开")
        if ip_shared_count > 50:
            score += 0.3
            flags.append(f"IP 共享 {ip_shared_count} 账号")
        elif ip_shared_count > 10:
            score += 0.15
            flags.append(f"IP 共享 {ip_shared_count} 账号")
        if new_device:
            score += 0.1
            flags.append("新设备")
        score = min(score, 1.0)
        level = "high" if score >= 0.6 else ("medium" if score >= 0.3 else "low")
        return DeviceRiskResult(
            risk_score=round(score, 3), level=level, flags=flags,
            summary=f"设备风险 {score:.2f}（{level}）",
        )


class UserReputationResult(BaseModel):
    reputation: float
    level: str   # good / neutral / poor
    reasons: List[str]
    summary: str


class UserReputationTool:
    name = "user_reputation"
    description = "用户信誉分（历史违规/活跃度/人工反馈综合）"

    async def execute(self, violation_count: int = 0, content_count: int = 1,
                      manual_confirm_bad: int = 0, manual_confirm_good: int = 0,
                      account_age_days: int = 0) -> UserReputationResult:
        reasons = []
        base = 0.5
        base += min(content_count / 500.0, 0.15)           # 活跃加分
        base -= min(violation_count * 0.08, 0.35)          # 违规扣分
        base -= min(manual_confirm_bad * 0.15, 0.3)        # 人工确认违规
        base += min(manual_confirm_good * 0.05, 0.15)      # 人工确认正常
        if account_age_days > 365:
            base += 0.05
        rep = round(max(0.0, min(base, 1.0)), 3)
        if violation_count > 0:
            reasons.append(f"{violation_count} 次历史违规")
        if manual_confirm_bad > 0:
            reasons.append(f"{manual_confirm_bad} 次人工确认违规")
        level = "poor" if rep < 0.4 else ("good" if rep >= 0.65 else "neutral")
        return UserReputationResult(
            reputation=rep, level=level, reasons=reasons,
            summary=f"信誉分 {rep:.2f}（{level}）",
        )
