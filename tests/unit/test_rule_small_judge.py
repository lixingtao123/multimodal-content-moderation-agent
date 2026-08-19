"""
RuleSmallJudge 单元测试（R19·M2 快车道规则评分器 fallback）

验证：
  - 平凡安全文本 → PASS 高置信（无需升级）
  - 无信号文本 → needs_upgrade（防系统性漏判，关键修复）
  - 高违规信号 → REJECT 直接采纳
  - 中度信号 → REVIEW / 升级
"""
import pytest

from agent_moderation.workers.rule_small_judge import RuleSmallJudge


@pytest.mark.asyncio
async def test_trivial_safe_pass():
    j = RuleSmallJudge()
    r = await j.judge("好的")
    assert r["decision"] == "PASS"
    assert r["needs_upgrade"] is False


@pytest.mark.asyncio
async def test_no_signal_upgrades():
    """无信号 ≠ 安全 → 必须升级大模型（T1 漏判根因的防护）"""
    j = RuleSmallJudge()
    r = await j.judge("陈小姐购买了哪些奢侈品牌的包包和鞋子，她的银行账户余额是多少")
    assert r["needs_upgrade"] is True
    assert r["decision"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_high_violation_signal_reject():
    j = RuleSmallJudge()
    r = await j.judge("博彩下注网站开户")
    assert r["decision"] == "REJECT"
    assert r["needs_upgrade"] is False


@pytest.mark.asyncio
async def test_medium_signals_review_or_upgrade():
    j = RuleSmallJudge()
    # 多个中度信号 → REVIEW（或更强信号 REJECT，均为合理拦截）
    r = await j.judge("加微信 赚钱 点击链接 兼职")
    assert r["decision"] in ("REVIEW", "UNKNOWN", "REJECT")
    if r["decision"] == "REJECT":
        assert r["needs_upgrade"] is False


@pytest.mark.asyncio
async def test_empty_text_pass():
    j = RuleSmallJudge()
    r = await j.judge("")
    assert r["decision"] == "PASS"
