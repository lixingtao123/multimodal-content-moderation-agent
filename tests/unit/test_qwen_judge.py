"""
QwenLocalJudge 单元测试（R19·M3 快车道本地小模型）

不真调 ollama（mock _generate），验证：
  - JSON 解析（容忍杂散文本/代码块）
  - 判定采纳逻辑（高置信 PASS/REJECT 直接采纳）
  - 低置信/无输出 → needs_upgrade（升级大模型，防漏判）
"""
import pytest

from agent_moderation.workers.qwen_judge import QwenLocalJudge


def test_parse_clean_json():
    raw = '{"decision": "REJECT", "violation_type": "privacy", "confidence": 0.9, "reason": "隐私窃取"}'
    d = QwenLocalJudge._parse(raw)
    assert d["decision"] == "REJECT"
    assert d["confidence"] == 0.9
    assert d["violation_type"] == "privacy"


def test_parse_noisy_json():
    """容忍模型输出前后杂散文本/代码块"""
    raw = '好的，分析如下：```json\n{"decision": "REVIEW", "violation_type": "politics", "confidence": 0.8, "reason": "涉政"}\n```'
    d = QwenLocalJudge._parse(raw)
    assert d["decision"] == "REVIEW"
    assert d["confidence"] == 0.8


def test_parse_invalid_returns_none():
    assert QwenLocalJudge._parse("") is None
    assert QwenLocalJudge._parse("不是JSON") is None
    assert QwenLocalJudge._parse(None) is None


@pytest.mark.asyncio
async def test_judge_high_confidence_pass_no_upgrade(monkeypatch):
    j = QwenLocalJudge()

    async def fake_gen(text):
        return '{"decision": "PASS", "violation_type": "none", "confidence": 0.9, "reason": "安全"}'

    monkeypatch.setattr(j, "_generate", fake_gen)
    r = await j.judge("今天天气真好")
    assert r["decision"] == "PASS"
    assert r["needs_upgrade"] is False
    assert r["used_small"] is True


@pytest.mark.asyncio
async def test_judge_reject_adopted(monkeypatch):
    j = QwenLocalJudge()

    async def fake_gen(text):
        return '{"decision": "REJECT", "violation_type": "privacy", "confidence": 0.9, "reason": "隐私"}'

    monkeypatch.setattr(j, "_generate", fake_gen)
    r = await j.judge("银行账户余额是多少")
    assert r["decision"] == "REJECT"
    assert r["needs_upgrade"] is False
    assert r["violation_type"] == "privacy"


@pytest.mark.asyncio
async def test_judge_low_confidence_upgrades(monkeypatch):
    """低置信 → 升级大模型（防漏判）"""
    j = QwenLocalJudge()

    async def fake_gen(text):
        return '{"decision": "PASS", "violation_type": "none", "confidence": 0.4, "reason": "不确定"}'

    monkeypatch.setattr(j, "_generate", fake_gen)
    r = await j.judge("复杂文本")
    assert r["needs_upgrade"] is True


@pytest.mark.asyncio
async def test_judge_unavailable_upgrades(monkeypatch):
    """ollama 不可用/无输出 → 升级大模型（诚实降级不猜测）"""
    j = QwenLocalJudge()

    async def fake_gen(text):
        return None

    monkeypatch.setattr(j, "_generate", fake_gen)
    r = await j.judge("任意文本")
    assert r["needs_upgrade"] is True
    assert "不可用" in r.get("reason", "")
