"""
账号风险画像 — 累积账号历史违规记录，生成风险评分

账号风险从以下几个维度评估：
1. 历史违规次数和频率
2. 违规类型分布
3. 检测到的黑灰产模式
4. 最近违规时间
"""
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class AccountRiskProfile:
    account_id: str
    risk_score: float = 0.0
    violation_count: int = 0
    last_violation_at: Optional[str] = None
    violation_types: list = field(default_factory=list)
    detected_patterns: list = field(default_factory=list)
    behavior_features: dict = field(default_factory=dict)
    risk_level: str = "LOW"

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "risk_score": self.risk_score,
            "violation_count": self.violation_count,
            "last_violation_at": self.last_violation_at,
            "violation_types": self.violation_types,
            "detected_patterns": self.detected_patterns,
            "behavior_features": self.behavior_features,
            "risk_level": self.risk_level,
        }


class AccountRiskProfiler:
    """账号风险画像管理器"""

    def __init__(self):
        self._profiles: dict = {}  # 内存缓存

    def get_profile(self, account_id: str) -> AccountRiskProfile:
        """获取账号画像（不存在则创建）"""
        if account_id not in self._profiles:
            self._profiles[account_id] = AccountRiskProfile(account_id=account_id)
        return self._profiles[account_id]

    def record_violation(
        self,
        account_id: str,
        violation_type: str,
        risk_score: float,
        patterns: list = None,
        features: dict = None,
    ):
        """记录一次违规"""
        profile = self.get_profile(account_id)

        profile.violation_count += 1
        profile.last_violation_at = datetime.now().isoformat()

        if violation_type and violation_type != "none":
            if violation_type not in profile.violation_types:
                profile.violation_types.append(violation_type)

        if patterns:
            for p in patterns:
                if p not in profile.detected_patterns:
                    profile.detected_patterns.append(p)

        if features:
            profile.behavior_features.update(features)

        # 重新计算风险分
        profile.risk_score = self._calculate_risk_score(profile)

        # 风险等级
        if profile.risk_score >= 0.7:
            profile.risk_level = "HIGH"
        elif profile.risk_score >= 0.4:
            profile.risk_level = "MEDIUM"
        else:
            profile.risk_level = "LOW"

        logger.info(
            f"Account {account_id}: violations={profile.violation_count}, "
            f"score={profile.risk_score:.3f}, level={profile.risk_level}"
        )

    def _calculate_risk_score(self, profile: AccountRiskProfile) -> float:
        """计算账号累积风险分"""
        score = 0.0

        # 违规次数（阶梯增长）
        if profile.violation_count == 1:
            score += 0.2
        elif profile.violation_count == 2:
            score += 0.4
        elif profile.violation_count >= 3:
            score += 0.6 + min((profile.violation_count - 3) * 0.1, 0.3)

        # 违规类型多样性
        unique_types = len(set(profile.violation_types))
        score += min(unique_types * 0.1, 0.2)

        # 最近违规时间（1小时内额外加分）
        if profile.last_violation_at:
            try:
                last_time = datetime.fromisoformat(profile.last_violation_at)
                hours_since = (datetime.now() - last_time).total_seconds() / 3600
                if hours_since < 1:
                    score += 0.2
                elif hours_since < 24:
                    score += 0.1
            except Exception:
                pass

        # 检测到的模式
        high_risk_patterns = {"PHISHING", "KEYWORD_VARIANT"}
        pattern_types = {p for p in profile.detected_patterns if p in high_risk_patterns}
        score += len(pattern_types) * 0.15

        return round(min(score, 1.0), 4)

    def should_auto_review(self, account_id: str) -> bool:
        """判断该账号是否应自动送审"""
        profile = self.get_profile(account_id)
        return profile.risk_score >= 0.3

    def should_auto_reject(self, account_id: str) -> bool:
        """判断该账号是否应自动封禁"""
        profile = self.get_profile(account_id)
        return (
            profile.risk_score >= 0.8
            and profile.violation_count >= 3
        )

    def get_all_profiles(self) -> list:
        """获取所有画像"""
        return [p.to_dict() for p in self._profiles.values()]

    def get_high_risk_accounts(self) -> list:
        """获取高风险账号"""
        return [
            p.to_dict()
            for p in self._profiles.values()
            if p.risk_level in ("HIGH", "MEDIUM")
        ]


# 全局单例
_account_profiler: Optional[AccountRiskProfiler] = None


def get_account_profiler() -> AccountRiskProfiler:
    global _account_profiler
    if _account_profiler is None:
        _account_profiler = AccountRiskProfiler()
    return _account_profiler
