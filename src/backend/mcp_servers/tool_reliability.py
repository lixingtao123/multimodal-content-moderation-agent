"""
工具可靠性层（R9·T2）— 校验 → 修复 → 降级链

目标：工具参数非法被拦截、工具挂了 Agent 不中断。

流程：
1. validate_args：jsonschema 校验工具参数
2. repair_args：确定性修复（补必填字段默认值）+ 可选 LLM 修复（1 次）
3. call_with_reliability：校验→修复→调用；修复无效抛 ToolCallError（调用方降级/跳过）

所有 agent 统一走此层（T4 工具调用分层的基础设施）。
"""
import logging
from typing import Awaitable, Callable, Optional

import jsonschema

logger = logging.getLogger(__name__)


class ToolCallError(Exception):
    """工具调用失败（参数非法且修复无效 / 工具不存在 / 执行异常）"""


def _input_schema(schema: dict) -> dict:
    """兼容 {inputSchema: {...}} 与裸 JSON Schema 两种格式"""
    return schema.get("inputSchema", schema) if schema else {}


def validate_args(schema: dict, args: dict) -> tuple:
    """jsonschema 校验工具参数。返回 (ok: bool, errors: list[str])"""
    input_schema = _input_schema(schema)
    if not input_schema:
        return True, []
    validator = jsonschema.Draft202012Validator(input_schema)
    errors = sorted(validator.iter_errors(args), key=lambda e: list(e.path))
    if not errors:
        return True, []
    return False, [e.message for e in errors]


def _deterministic_repair(schema: dict, args: dict) -> dict:
    """确定性修复：为缺失的必填字段补默认值"""
    input_schema = _input_schema(schema)
    repaired = dict(args)
    if not input_schema:
        return repaired
    props = input_schema.get("properties", {})
    for req in input_schema.get("required", []):
        if req not in repaired and req in props:
            default = props[req].get("default")
            if default is not None:
                repaired[req] = default
    return repaired


async def repair_args(
    schema: dict,
    args: dict,
    errors: list,
    llm_func: Optional[Callable[[str], Awaitable[dict]]] = None,
) -> dict:
    """修复参数：先确定性补默认值，再用 LLM 修复（1 次，可选）。"""
    repaired = _deterministic_repair(schema, args)
    if llm_func is not None and errors:
        try:
            prompt = (
                f"修复工具调用参数，使其通过 JSON Schema 校验。\n"
                f"Schema 错误: {errors[:3]}\n原始参数: {args}\n"
                f"返回修复后的 JSON 对象。"
            )
            result = await llm_func(prompt)
            if isinstance(result, dict):
                repaired = result
        except Exception as e:
            logger.warning(f"[tool_reliability] LLM 修复失败，用确定性修复结果: {e}")
    return repaired


async def call_with_reliability(
    registry,
    tool_name: str,
    args: dict,
    llm_func: Optional[Callable[[str], Awaitable[dict]]] = None,
    positive_contribution: bool = False,
) -> object:
    """校验→修复→调用。修复无效或执行异常抛 ToolCallError（调用方降级/跳过）。

    Args:
        registry: MCPToolRegistry（get / get_schema）
        tool_name: 工具名
        args: 工具参数
        llm_func: 可选 LLM 修复函数（接收 prompt 返回 dict）
        positive_contribution: 结果是否对判定有正贡献（T3 质量分上报，由调用方决定）
    """
    from mcp_servers.tool_telemetry import get_tool_telemetry

    tool = registry.get(tool_name)
    if tool is None:
        raise ToolCallError(f"工具不存在: {tool_name}")

    schema = registry.get_schema(tool_name) or {}

    ok, errors = validate_args(schema, args)
    if not ok:
        repaired = await repair_args(schema, args, errors, llm_func)
        ok2, errors2 = validate_args(schema, repaired)
        if not ok2:
            # R11·T3: 记录失败（质量分下降）
            get_tool_telemetry().record(tool_name, success=False)
            raise ToolCallError(
                f"工具参数校验失败且修复无效: {tool_name} ({errors2[:2]})")
        logger.info(f"[tool_reliability] {tool_name} 参数已修复: {args} -> {repaired}")
        args = repaired

    try:
        result = await tool.execute(**args)
        # R11·T3: 记录成功调用
        get_tool_telemetry().record(tool_name, success=True,
                                    positive_contribution=positive_contribution)
        return result
    except ToolCallError:
        get_tool_telemetry().record(tool_name, success=False)
        raise
    except Exception as e:
        get_tool_telemetry().record(tool_name, success=False)
        raise ToolCallError(f"工具执行异常: {tool_name}: {e}") from e
