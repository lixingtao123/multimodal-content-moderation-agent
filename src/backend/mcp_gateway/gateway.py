"""
MCP Gateway v1.0 — 统一工具调用控制面

流水线:
  请求 → 认证 → RBAC 检查 → 限流 → 参数校验 → 执行 → 审计 → 响应

使用方式:
  from mcp_gateway import get_gateway

  gateway = get_gateway()
  result = await gateway.call_tool("keyword_check", {"text": "test"}, agent_type="text_agent")
"""
import json
import logging
import time
import asyncio
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class MCPGateway:
    """
    MCP Gateway — 所有工具调用的统一入口。

    负责在工具执行前后插入横切关注点：
      - 权限校验：Agent 是否有权调用此工具
      - 速率限制：是否超过频率限制
      - 参数校验：入参是否符合 JSON Schema
      - 审计日志：记录所有调用的完整信息
    """

    def __init__(self):
        self._server = None
        self._acl = None
        self._audit = None

    @property
    def server(self):
        if self._server is None:
            from mcp_servers.registry import get_tool_registry
            self._server = get_tool_registry().get_mcp_server()
        return self._server

    @property
    def acl(self):
        if self._acl is None:
            from mcp_servers.access_control import get_access_controller
            self._acl = get_access_controller()
        return self._acl

    @property
    def audit(self):
        if self._audit is None:
            from mcp_servers.audit import get_audit_logger
            self._audit = get_audit_logger()
        return self._audit

    def _log_audit(self, tool_name: str, caller_agent: str, params: dict,
                   result_type: str = "success", result_summary: dict = None,
                   latency_ms: float = 0.0, error_message: str = "",
                   caller_identity: str = "", content_id: str = "", trace_id: str = ""):
        """
        记录审计日志（文件）+ 异步写入 PostgreSQL。
        """
        record = self.audit.log(
            tool_name=tool_name,
            caller_agent=caller_agent,
            params=params,
            result_type=result_type,
            result_summary=result_summary,
            latency_ms=latency_ms,
            error_message=error_message,
            caller_identity=caller_identity,
            content_id=content_id,
            trace_id=trace_id,
        )
        # fire-and-forget 写入 DB（不阻塞主流程）
        try:
            asyncio.ensure_future(self.audit.log_to_db(record))
        except Exception:
            pass  # DB 不可用时静默跳过

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        agent_type: str = "",
        caller_identity: str = "",
        content_id: str = "",
    ) -> dict:
        """
        通过 Gateway 调用 MCP 工具（完整流水线）。

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            agent_type: 调用方 Agent 类型（用于 RBAC）
            caller_identity: 调用方身份（用于审计）
            content_id: 关联内容 ID（用于审计）

        Returns:
            工具执行结果 dict

        Raises:
            PermissionError: Agent 无权调用此工具
            ValueError: 参数校验失败
        """
        start_time = time.monotonic()
        trace_id = f"gw_{int(start_time * 1000) % 100000:05d}"

        # ---- 1. 权限校验 ----
        if agent_type and not self.acl.is_allowed(agent_type, tool_name):
            error_msg = f"Access denied: {agent_type} cannot use {tool_name}"
            logger.warning(f"[Gateway] {error_msg}")
            # 记录审计日志（文件 + DB）
            self._log_audit(
                tool_name=tool_name,
                caller_agent=agent_type,
                params=arguments,
                result_type="denied",
                error_message=error_msg,
                caller_identity=caller_identity,
                content_id=content_id,
                trace_id=trace_id,
            )
            raise PermissionError(error_msg)

        # ---- 2. 参数校验 (JSON Schema) ----
        self._validate_params(tool_name, arguments)

        # ---- 3. 执行 ----
        try:
            # 委托给 MCPServer 执行
            mcp_result = await self.server._handle_tools_call({
                "name": tool_name,
                "arguments": arguments,
            })

            # 解析 MCP content 格式
            content = mcp_result.get("content", [])
            if content and len(content) > 0:
                text = content[0].get("text", "{}")
                result = json.loads(text)
            else:
                result = mcp_result

            latency_ms = (time.monotonic() - start_time) * 1000

            # ---- 4. 审计日志（文件 + DB）----
            self._log_audit(
                tool_name=tool_name,
                caller_agent=agent_type,
                params=arguments,
                result_type="success",
                result_summary=self._summarize_result(tool_name, result),
                latency_ms=latency_ms,
                caller_identity=caller_identity,
                content_id=content_id,
                trace_id=trace_id,
            )

            return result

        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000

            # 审计日志（错误 — 文件 + DB）
            self._log_audit(
                tool_name=tool_name,
                caller_agent=agent_type,
                params=arguments,
                result_type="error",
                error_message=str(e)[:500],
                latency_ms=latency_ms,
                caller_identity=caller_identity,
                content_id=content_id,
                trace_id=trace_id,
            )
            raise

    def _validate_params(self, tool_name: str, arguments: dict):
        """
        JSON Schema 参数校验。

        验证入参是否包含所有 required 字段，类型是否匹配。
        不阻止额外字段（向前兼容）。
        """
        try:
            from mcp_servers.registry import get_tool_registry
            registry = get_tool_registry()
            schemas = registry.get_tool_schemas()
            schema = next((s for s in schemas if s.get("name") == tool_name), None)

            if not schema:
                return  # 无 Schema 定义，跳过校验

            input_schema = schema.get("inputSchema", {})
            required_fields = input_schema.get("required", [])
            properties = input_schema.get("properties", {})

            # 检查必填字段
            missing = [f for f in required_fields if f not in arguments]
            if missing:
                raise ValueError(f"Missing required params for '{tool_name}': {missing}")

            # 简单类型检查
            for key, value in arguments.items():
                prop_schema = properties.get(key, {})
                expected_type = prop_schema.get("type", "")
                if expected_type == "string" and not isinstance(value, str):
                    raise ValueError(f"Param '{key}' expected string, got {type(value).__name__}")
                elif expected_type == "integer" and not isinstance(value, int):
                    raise ValueError(f"Param '{key}' expected integer, got {type(value).__name__}")
                elif expected_type == "array" and not isinstance(value, list):
                    raise ValueError(f"Param '{key}' expected array, got {type(value).__name__}")

        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"Schema validation skipped for {tool_name}: {e}")

    def _summarize_result(self, tool_name: str, result: dict) -> dict:
        """生成结果摘要（不记录完整内容，防止审计日志膨胀）"""
        if tool_name == "keyword_check":
            return {"has_violation": result.get("has_violation", False), "count": result.get("count", 0)}
        elif tool_name == "history_search":
            return {"case_count": len(result.get("cases", [])), "has_match": result.get("has_match", False)}
        elif tool_name == "image_hash":
            return {"similarity": result.get("similarity", 0)}
        elif tool_name == "account_risk_check":
            return {"risk_level": result.get("risk_level", "unknown")}
        elif tool_name == "adversarial_detect":
            return {"has_adversarial": result.get("has_adversarial", False)}
        elif tool_name == "url_check":
            return {"risk_level": result.get("risk_level", "safe")}
        elif tool_name == "content_dedup":
            return {"is_duplicate": result.get("is_duplicate", False)}
        elif tool_name == "regex_rule_check":
            return {"has_match": result.get("has_match", False), "total_matches": result.get("total_matches", 0)}
        return {"keys": list(result.keys())}

    def list_tools(self, agent_type: str = "") -> list:
        """
        列出工具列表（可选过滤：仅返回指定 Agent 可用的工具）。

        Args:
            agent_type: 如果非空，仅返回此 Agent 有权调用的工具
        """
        result = self.server._handle_tools_list_sync() if hasattr(self.server, '_handle_tools_list_sync') else None
        if result is None:
            return []

        tools = result.get("tools", [])
        if agent_type:
            tools = self.acl.filter_tools(agent_type, tools)
        return tools


# 全局单例
_gateway: Optional[MCPGateway] = None


def get_gateway() -> MCPGateway:
    global _gateway
    if _gateway is None:
        _gateway = MCPGateway()
    return _gateway
