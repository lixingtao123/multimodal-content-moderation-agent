"""
账号风险查询工具 v1.0 — 查询账号历史违规记录和风险画像

本地执行，查询 PostgreSQL account_profiles 表
"""
import logging
from typing import List, Dict, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AccountRiskResult(BaseModel):
    account_id: str
    total_violations: int = 0
    recent_violations: int = 0      # 最近7天违规次数
    violation_types: List[str] = []
    risk_level: str = "low"         # low / medium / high / critical
    risk_score: float = 0.0         # 0.0 ~ 1.0
    is_new_account: bool = True
    summary: str = ""


class AccountRiskTool:
    """账号风险查询工具 — 查 PostgreSQL account_profiles"""

    name = "account_risk_check"
    description = "查询账号的历史违规记录和风险画像（查PostgreSQL）"

    def __init__(self):
        self._db_available = False
        self._check_db()

    def _check_db(self):
        """检查数据库是否可用"""
        try:
            from db.connection import async_session_factory
            self._db_available = True
        except Exception:
            logger.warning("PostgreSQL not available for account_risk_check")

    async def execute(self, account_id: str) -> AccountRiskResult:
        """查询账号风险"""
        if not account_id or account_id == "unknown":
            return AccountRiskResult(
                account_id=account_id or "unknown",
                risk_level="low",
                summary="无有效账号ID",
            )

        if not self._db_available:
            return AccountRiskResult(
                account_id=account_id,
                risk_level="low",
                summary="数据库不可用，跳过账号查询",
            )

        try:
            from sqlalchemy import text
            from db.connection import async_session_factory

            async with async_session_factory() as session:
                # 查询最近违规记录
                result = await session.execute(text("""
                    SELECT
                        COUNT(*) as total_violations,
                        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') as recent_violations,
                        COALESCE(MAX(created_at), NOW()) as last_violation_at
                    FROM moderation_records
                    WHERE account_id = :aid
                      AND final_decision IN ('REJECT', 'REVIEW')
                """), {"aid": account_id})
                row = result.fetchone()

                if not row or row.total_violations == 0:
                    return AccountRiskResult(
                        account_id=account_id,
                        risk_level="low",
                        summary=f"账号 {account_id} 无违规记录",
                    )

                total = row.total_violations
                recent = row.recent_violations or 0

                # 计算风险等级
                if total >= 10 or recent >= 5:
                    risk_level = "critical"
                    risk_score = min(0.9, 0.5 + recent * 0.1 + total * 0.02)
                elif total >= 5 or recent >= 3:
                    risk_level = "high"
                    risk_score = min(0.75, 0.4 + recent * 0.08 + total * 0.03)
                elif total >= 2 or recent >= 1:
                    risk_level = "medium"
                    risk_score = min(0.5, 0.2 + recent * 0.1 + total * 0.05)
                else:
                    risk_level = "low"
                    risk_score = 0.1

                return AccountRiskResult(
                    account_id=account_id,
                    total_violations=total,
                    recent_violations=recent,
                    risk_level=risk_level,
                    risk_score=round(risk_score, 3),
                    is_new_account=False,
                    summary=f"账号 {account_id}: {total}次违规, 近7天{recent}次",
                )
        except Exception as e:
            logger.warning(f"Account risk query failed: {e}")
            return AccountRiskResult(
                account_id=account_id,
                risk_level="low",
                summary=f"查询失败: {str(e)[:80]}",
            )
