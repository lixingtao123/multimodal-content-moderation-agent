"""
MCP Client v1.0 — Agent 调用 MCP 工具的客户端

提供与 MCPServer 对等的 JSON-RPC 客户端接口。
Agent 通过此客户端调用工具，而非直接 import tool.execute()。

使用方式:
  from mcp_servers.mcp_client import get_mcp_client

  client = get_mcp_client()
  result = await client.call_tool("keyword_check", {"text": "待检测文本"})

特点:
  - 同进程直接调用（零序列化开销）
  - 未来可切换为 HTTP/SSE 远程调用
  - 自动参数校验
  - 统一的错误处理
"""
import json
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class MCPClient:
    """
    MCP 协议客户端 — Agent 与 MCP Server 之间的通信桥梁。

    当前实现: 同进程直接调用（零网络开销）
    预留接口: HTTP/SSE 远程调用（传 server_url 参数即可切换）
    """

    def __init__(self, server_url: str = None):
        """
        Args:
            server_url: 远程 MCP Server URL（可选，默认使用本地 in-process server）
        """
        self._server_url = server_url
        self._server = None  # 延迟加载

    @property
    def server(self):
        """延迟加载 MCPServer 实例"""
        if self._server is None:
            try:
                from mcp_servers.registry import get_tool_registry
                registry = get_tool_registry()
                self._server = registry.get_mcp_server()
            except Exception as e:
                logger.error(f"Failed to get MCP Server: {e}")
                raise RuntimeError("MCP Server not available") from e
        return self._server

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """
        调用 MCP 工具（Agent 主要入口）

        Args:
            name: 工具名称 (如 "keyword_check")
            arguments: 工具参数 (如 {"text": "待检测文本"})

        Returns:
            工具执行结果 dict

        Raises:
            ValueError: 工具不存在或参数无效
            RuntimeError: MCP Server 不可用
        """
        if self._server_url:
            return await self._call_remote(name, arguments)
        return await self._call_local(name, arguments)

    async def _call_local(self, name: str, arguments: dict) -> dict:
        """同进程直接调用（零序列化开销）"""
        result = await self.server._handle_tools_call({
            "name": name,
            "arguments": arguments,
        })

        # 解析 MCP content 格式
        content = result.get("content", [])
        if content and len(content) > 0:
            text = content[0].get("text", "{}")
            return json.loads(text)
        return result

    async def _call_remote(self, name: str, arguments: dict) -> dict:
        """HTTP 远程调用（预留接口）"""
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._server_url}/api/v1/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                    "id": "1",
                },
            )
            response.raise_for_status()
            return response.json()

    async def list_tools(self) -> List[dict]:
        """列出所有可用工具"""
        result = await self.server._handle_tools_list({})
        return result.get("tools", [])

    async def list_resources(self) -> List[dict]:
        """列出所有可用资源"""
        result = await self.server._handle_resources_list({})
        return result.get("resources", [])

    async def read_resource(self, uri: str) -> dict:
        """读取指定资源"""
        result = await self.server._handle_resources_read({"uri": uri})
        return result

    async def list_prompts(self) -> List[dict]:
        """列出所有 Prompt 模板"""
        result = await self.server._handle_prompts_list({})
        return result.get("prompts", [])

    async def get_prompt(self, name: str, arguments: dict = None) -> dict:
        """获取指定 Prompt 模板"""
        result = await self.server._handle_prompts_get({
            "name": name,
            "arguments": arguments or {},
        })
        return result

    async def initialize(self) -> dict:
        """MCP 握手"""
        result = await self.server._handle_initialize({})
        return result


# 全局单例
_mcp_client: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    """获取 MCP Client 全局单例"""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client
