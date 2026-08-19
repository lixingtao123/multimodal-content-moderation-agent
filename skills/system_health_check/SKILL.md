---
name: system_health_check
description: 系统组件健康状态（Redis/Chroma/DB 探测）
version: 1.0.0
mcp_tools: [system_health]
triggers:
  - "健康"
  - "health"
  - "系统"
  - "探测"
  - "redis"
tags: [ops, monitoring]
---

# system_health_check

## Overview
探测 Redis/Chroma/DB 连通性，输出各组件状态与总体健康度。

## When to Use
- 审核流程中触发 system_health_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("system_health")
# result = await tool.execute(...)
```
