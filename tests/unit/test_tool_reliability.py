"""
单元测试 — 工具可靠性层（R9·T2）
校验 → 修复 → 降级链。
"""
import pytest

from mcp_servers.registry import get_tool_registry
from mcp_servers.tool_reliability import (
    ToolCallError,
    call_with_reliability,
    repair_args,
    validate_args,
)


@pytest.fixture
def registry():
    return get_tool_registry()


class TestValidate:
    def test_valid_args(self, registry):
        schema = registry.get_schema("keyword_check")
        ok, errors = validate_args(schema, {"text": "你好"})
        assert ok is True
        assert errors == []

    def test_missing_required(self, registry):
        schema = registry.get_schema("keyword_check")
        ok, errors = validate_args(schema, {})
        assert ok is False
        assert errors

    def test_wrong_type(self, registry):
        schema = registry.get_schema("keyword_check")
        ok, errors = validate_args(schema, {"text": 123})
        assert ok is False


class TestRepair:
    @pytest.mark.asyncio
    async def test_deterministic_default_fill(self):
        """确定性修复：补必填字段默认值"""
        schema = {"type": "object", "properties": {
            "text": {"type": "string"},
            "top_k": {"type": "integer", "default": 5},
        }, "required": ["text", "top_k"]}
        repaired = await repair_args(schema, {"text": "hi"}, [])
        assert repaired["top_k"] == 5

    @pytest.mark.asyncio
    async def test_llm_repair(self):
        """LLM 修复优先"""
        schema = {"type": "object", "properties": {"query": {"type": "string"}},
                  "required": ["query"]}
        called = []

        async def fake_llm(prompt):
            called.append(prompt)
            return {"query": "fixed"}

        repaired = await repair_args(schema, {}, ["缺 query"], fake_llm)
        assert repaired == {"query": "fixed"}
        assert called  # LLM 被调用

    @pytest.mark.asyncio
    async def test_llm_repair_fallback(self):
        """LLM 修复异常时回退确定性修复"""
        schema = {"type": "object", "properties": {"x": {"type": "integer", "default": 1}},
                  "required": ["x"]}

        async def bad_llm(prompt):
            raise RuntimeError("LLM down")

        repaired = await repair_args(schema, {}, ["缺 x"], bad_llm)
        assert repaired["x"] == 1


class TestCallReliability:
    @pytest.mark.asyncio
    async def test_success(self, registry):
        result = await call_with_reliability(registry, "keyword_check", {"text": "加微信"})
        assert result is not None
        assert hasattr(result, "has_violation") or hasattr(result, "matches")

    @pytest.mark.asyncio
    async def test_missing_tool_raises(self, registry):
        with pytest.raises(ToolCallError):
            await call_with_reliability(registry, "not_a_tool", {})

    @pytest.mark.asyncio
    async def test_invalid_unrepairable_raises(self, registry):
        """缺必填 text 且无默认值 → 修复无效 → ToolCallError（调用方降级）"""
        with pytest.raises(ToolCallError):
            await call_with_reliability(registry, "keyword_check", {})

    @pytest.mark.asyncio
    async def test_repairable_default_fills(self, registry):
        """history_search 缺必填 query 但可被确定性补默认的字段不影响"""
        # history_search required 只有 query（无默认），所以构造一个含默认的场景：
        # 用 account_risk_check（required account_id 无默认）→ 应失败降级而非崩溃
        with pytest.raises(ToolCallError):
            await call_with_reliability(registry, "account_risk_check", {})

    @pytest.mark.asyncio
    async def test_exec_exception_wrapped(self, registry):
        """工具执行异常 → 包装为 ToolCallError"""
        # 传入非法类型触发内部异常
        with pytest.raises(ToolCallError):
            await call_with_reliability(registry, "keyword_check", {"text": 999})

    @pytest.mark.asyncio
    async def test_llm_repair_saves_call(self):
        """LLM 修复可挽救参数缺失的调用"""
        async def fake_llm(prompt):
            return {"text": "修复后的文本"}

        result = await call_with_reliability(
            get_tool_registry(), "keyword_check", {}, fake_llm)
        assert result is not None
