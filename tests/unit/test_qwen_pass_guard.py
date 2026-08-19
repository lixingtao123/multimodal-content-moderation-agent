"""
单元测试 — qwen2.5 小模型 PASS 防漏（R20）

背景：此前 needs_upgrade = confidence < 0.6，7B 模型对弱信号违规可能
高置信误判 PASS 直接放行。R20 新增：
  - PASS 需置信 ≥0.8 且 violation_type=none 才直接放行
  - PASS 但标了违规类型（矛盾信号）→ 升级大模型
  - REJECT/REVIEW 低置信（<0.6）→ 升级（避免以不可靠结论直接拦截）
"""
import pytest

from agent_moderation.workers.qwen_judge import QwenLocalJudge


@pytest.mark.asyncio
async def test_pass_with_type_upgrades(monkeypatch):
    """判 PASS 但标了违规类型（矛盾信号）→ 升级"""
    j = QwenLocalJudge()

    async def fake_gen(text):
        return '{"decision": "PASS", "violation_type": "privacy", "confidence": 0.9, "reason": "x"}'

    monkeypatch.setattr(j, "_generate", fake_gen)
    r = await j.judge("x")
    assert r["decision"] == "PASS"
    assert r["needs_upgrade"] is True


@pytest.mark.asyncio
async def test_pass_mid_confidence_upgrades(monkeypatch):
    """PASS 置信 0.7（<0.8）→ 升级"""
    j = QwenLocalJudge()

    async def fake_gen(text):
        return '{"decision": "PASS", "violation_type": "none", "confidence": 0.7, "reason": "x"}'

    monkeypatch.setattr(j, "_generate", fake_gen)
    r = await j.judge("x")
    assert r["needs_upgrade"] is True


@pytest.mark.asyncio
async def test_pass_high_confidence_none_accepted(monkeypatch):
    """PASS 高置信且无类型 → 直接放行（快车道省成本）"""
    j = QwenLocalJudge()

    async def fake_gen(text):
        return '{"decision": "PASS", "violation_type": "none", "confidence": 0.9, "reason": "安全"}'

    monkeypatch.setattr(j, "_generate", fake_gen)
    r = await j.judge("今天天气真好")
    assert r["needs_upgrade"] is False
    assert r["used_small"] is True


@pytest.mark.asyncio
async def test_reject_low_confidence_upgrades(monkeypatch):
    """REJECT 置信不足 0.6 → 升级（避免不可靠拦截）"""
    j = QwenLocalJudge()

    async def fake_gen(text):
        return '{"decision": "REJECT", "violation_type": "crime", "confidence": 0.5, "reason": "x"}'

    monkeypatch.setattr(j, "_generate", fake_gen)
    r = await j.judge("x")
    assert r["needs_upgrade"] is True


@pytest.mark.asyncio
async def test_reject_high_confidence_adopted(monkeypatch):
    """REJECT 高置信 → 采纳且透传类型"""
    j = QwenLocalJudge()

    async def fake_gen(text):
        return '{"decision": "REJECT", "violation_type": "crime", "confidence": 0.9, "reason": "涉罪"}'

    monkeypatch.setattr(j, "_generate", fake_gen)
    r = await j.judge("x")
    assert r["needs_upgrade"] is False
    assert r["violation_type"] == "crime"
