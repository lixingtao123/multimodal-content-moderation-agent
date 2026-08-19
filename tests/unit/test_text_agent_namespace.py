"""
text_agent 直调容错测试（R19 修复）

背景：MCP Gateway 的 _dict_to_namespace 递归把 dict 转 SimpleNamespace，
text_agent 直调（绕过 supervisor 分块）时 keyword_result.matches 元素为
SimpleNamespace，原代码按 dict 访问 `m["keyword"]` 会崩。
本测试验证直调 path 不抛异常。

注意：单函数多断言（get_deepseek_client/get_memory_manager 为全局单例，
AsyncOpenAI client 绑定 event loop，跨 loop 复用会报 Event loop is closed）。
"""
from types import SimpleNamespace

import pytest

from agent_moderation.state import create_initial_state


@pytest.mark.asyncio
async def test_process_compat_with_namespace_and_dict_matches(monkeypatch):
    """matches 元素为 SimpleNamespace 与 dict 两种形态均不崩溃且正确产出 text_result"""
    from agent_moderation.agents.text_agent import TextAgent

    class DummyMemory:
        async def update_task_step(self, *a, **k):
            pass

        async def get_cached_llm_result(self, *a, **k):
            return None

        async def cache_llm_result(self, *a, **k):
            pass

    # 避免触碰 loop-bound 全局客户端（全量顺序下跨 loop 复用会崩）
    monkeypatch.setattr("agent_moderation.agents.text_agent.get_deepseek_client", lambda: None)
    monkeypatch.setattr("agent_moderation.agents.text_agent.get_memory_manager", lambda: DummyMemory())

    def _build_state():
        return create_initial_state(
            content_id="eval_ns_test", content_type="text",
            content={"text": "加微信转账，中奖领奖请联系我们"},
        )

    async def _semantic(text, similar_cases=None, core_memories=None):
        return {
            "violation_type": "fraud", "confidence": 0.9, "reason": "test",
            "reasoning": "test", "is_adversarial": False, "tags": ["fraud"],
            "violation_span": [], "ai_generated_prob": 0.0,
        }

    # 场景1: matches 元素为 SimpleNamespace（MCP Gateway 实际形态）
    agent1 = TextAgent()

    async def fake_call_ns(tool_name: str, **kwargs):
        if tool_name == "keyword_check":
            return SimpleNamespace(
                has_violation=True,
                matches=[SimpleNamespace(keyword="中奖", position=3)],
                count=1,
            )
        if tool_name == "history_search":
            return SimpleNamespace(has_match=False, cases=[])
        return SimpleNamespace()

    monkeypatch.setattr(agent1, "_call_mcp_tool", fake_call_ns)
    monkeypatch.setattr(agent1, "_analyze_semantic", _semantic)

    out1 = await agent1.process(_build_state())
    tr1 = out1.get("text_result") or {}
    assert tr1.get("violation_type") == "fraud"
    assert tr1.get("keyword_count") == 1
    chain1 = tr1.get("reasoning_chain") or []
    assert any("关键词检测" in s for s in chain1)

    # 场景2: matches 元素为 dict（旧 tool.execute 直接路径）—— 回归保障
    agent2 = TextAgent()

    async def fake_call_dict(tool_name: str, **kwargs):
        if tool_name == "keyword_check":
            return SimpleNamespace(
                has_violation=True,
                matches=[{"keyword": "中奖", "position": 0}],
                count=1,
            )
        if tool_name == "history_search":
            return SimpleNamespace(has_match=False, cases=[])
        return SimpleNamespace()

    monkeypatch.setattr(agent2, "_call_mcp_tool", fake_call_dict)
    monkeypatch.setattr(agent2, "_analyze_semantic", _semantic)

    out2 = await agent2.process(_build_state())
    tr2 = out2.get("text_result") or {}
    assert tr2.get("violation_type") == "fraud"
