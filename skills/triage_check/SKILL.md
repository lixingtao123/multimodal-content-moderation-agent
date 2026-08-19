---
name: triage_check
description: 三车道分诊（规则快判 low / 标准 med / 复杂 high）
version: 1.0.0
mcp_tools: [triage_router]
triggers:
  - "分诊"
  - "车道"
  - "triage"
  - "快判"
  - "复杂"
tags: [decision, triage]
---

# triage_check

## Overview
根据风险预判与复杂度将内容分派到 low/med/high 三车道，优化成本与延迟。

## When to Use
- 审核流程中触发 triage_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("triage_router")
# result = await tool.execute(...)
```
