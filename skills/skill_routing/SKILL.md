---
name: skill_routing
description: 技能三级路由（Filter→Rank→Select 注入）
version: 1.0.0
mcp_tools: [skill_router_route]
triggers:
  - "技能"
  - "路由"
  - "skill"
  - "注入"
  - "route"
tags: [decision, skill]
---

# skill_routing

## Overview
将任务描述路由到最相关技能，控制注入上下文规模。

## When to Use
- 审核流程中触发 skill_routing 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("skill_router_route")
# result = await tool.execute(...)
```
