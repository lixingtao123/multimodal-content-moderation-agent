"""
MCP (Model Context Protocol) JSON-RPC 端点 v1.0

提供标准 MCP JSON-RPC 2.0 协议接口，供外部 MCP 客户端调用工具/资源/提示词。

端点:
  POST /api/v1/mcp              — JSON-RPC 2.0 请求入口
  GET  /api/v1/mcp/health       — 健康检查
  GET  /api/v1/mcp/tools        — 便捷: tools/list
  GET  /api/v1/mcp/resources    — 便捷: resources/list
  GET  /api/v1/mcp/prompts      — 便捷: prompts/list
"""
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])
logger = logging.getLogger(__name__)


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 请求"""
    jsonrpc: str = "2.0"
    method: str
    params: Optional[dict] = None
    id: Optional[str] = None


def _parse_jsonrpc(body: dict) -> dict:
    """兼容处理 JSON-RPC 请求格式"""
    return {
        "method": body.get("method", ""),
        "params": body.get("params", {}),
        "id": body.get("id"),
    }


def _get_server():
    """延迟获取 MCP Server 实例"""
    try:
        from mcp_servers.registry import get_tool_registry
        registry = get_tool_registry()
        return registry.get_mcp_server()
    except Exception as e:
        logger.error(f"Failed to get MCP Server: {e}")
        return None


async def _handle_tools_call_via_gateway(raw_request: dict, agent_type: str = "") -> dict:
    """R22: JSON-RPC tools/call 经 Gateway 执行（ACL + 审计 + 执行）。

    返回与 server.handle_request 相同的 JSON-RPC 响应结构，兼容 MCP 客户端。
    agent_type 从请求头 X-Agent-Type 透传，用于 ACL 校验与审计归属（默认空=免 ACL 但记审计）。
    """
    params = raw_request.get("params") or {}
    tool_name = params.get("name", "")
    arguments = params.get("arguments") or {}
    req_id = raw_request.get("id")

    try:
        from mcp_gateway.gateway import get_gateway
        gateway = get_gateway()
        result = await gateway.call_tool(tool_name, arguments, agent_type=agent_type)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, default=str),
                    }
                ]
            },
        }
    except PermissionError as e:
        logger.warning(f"MCP tools/call denied: {tool_name} ({e})")
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32603, "message": str(e)}}
    except Exception as e:
        logger.error(f"MCP tools/call failed: {tool_name} ({e})")
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}


# ===== JSON-RPC 2.0 主端点 =====

@router.post("")
async def mcp_jsonrpc_endpoint(request: Request):
    """
    MCP JSON-RPC 2.0 协议入口

    支持的方法:
      - initialize: 握手，返回服务端信息
      - tools/list: 列出所有可用工具及参数 Schema
      - tools/call: 调用指定工具
      - resources/list: 列出所有资源
      - resources/read: 读取资源
      - prompts/list: 列出所有 Prompt 模板
      - prompts/get: 获取 Prompt 模板

    请求示例:
      POST /api/v1/mcp
      {"jsonrpc":"2.0","method":"tools/list","id":"1"}

    响应:
      {"jsonrpc":"2.0","id":"1","result":{"tools":[...]}}
    """
    server = _get_server()
    if not server:
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32603, "message": "MCP Server not available"},
        }

    try:
        body = await request.json()
        raw_request = _parse_jsonrpc(body)

        # R22: tools/call 走 Gateway 完整流水线（ACL + 参数校验 + 执行 + 审计）。
        # 此前直接 handle_request 会绕过 ACL 与审计，导致 JSON-RPC 入口与
        # Agent 内部调用（gateway.call_tool）行为不一致。
        if raw_request.get("method") == "tools/call":
            agent_type = request.headers.get("X-Agent-Type", "")
            return await _handle_tools_call_via_gateway(raw_request, agent_type=agent_type)

        response = await server.handle_request(raw_request)
        return response
    except json.JSONDecodeError:
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "Parse error: invalid JSON"},
        }
    except Exception as e:
        logger.error(f"MCP endpoint error: {e}")
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
        }


# ===== 便捷端点（供前端 TechLab 直接调用，无需构造 JSON-RPC） =====

@router.get("/health")
async def mcp_health():
    """MCP 服务健康检查"""
    server = _get_server()
    if not server:
        return {"status": "unavailable", "tools": 0}
    return {
        "status": "healthy",
        "name": server.name,
        "version": server.version,
        "tools": len(server._tools),
        "resources": len(server._resources),
        "prompts": len(server._prompts),
    }


@router.get("/tools")
async def mcp_tools_list():
    """便捷端点：列出所有 MCP 工具"""
    server = _get_server()
    if not server:
        raise HTTPException(status_code=503, detail="MCP Server not available")

    result = await server._handle_tools_list({})
    return result


@router.get("/resources")
async def mcp_resources_list():
    """便捷端点：列出所有 MCP 资源"""
    server = _get_server()
    if not server:
        raise HTTPException(status_code=503, detail="MCP Server not available")

    result = await server._handle_resources_list({})
    return result


@router.get("/prompts")
async def mcp_prompts_list():
    """便捷端点：列出所有 MCP Prompt 模板"""
    server = _get_server()
    if not server:
        raise HTTPException(status_code=503, detail="MCP Server not available")

    result = await server._handle_prompts_list({})
    return result


@router.post("/prompts/{prompt_name}")
async def mcp_prompt_get(prompt_name: str, arguments: Optional[dict] = None):
    """便捷端点：获取指定 Prompt 模板"""
    server = _get_server()
    if not server:
        raise HTTPException(status_code=503, detail="MCP Server not available")

    try:
        result = await server._handle_prompts_get({
            "name": prompt_name,
            "arguments": arguments or {},
        })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
