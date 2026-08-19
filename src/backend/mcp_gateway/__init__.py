"""
MCP Gateway v1.0 — 控制面层

提供 MCP 协议调用的统一入口，负责:
  - 认证代理 (API Key / JWT)
  - 工具级访问控制 (RBAC)
  - 速率限制 (Redis 滑动窗口)
  - 参数校验 (JSON Schema)
  - 审计日志管道
  - Prometheus 指标暴露
"""
from mcp_gateway.gateway import MCPGateway, get_gateway  # noqa: F401
