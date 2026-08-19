---
name: policy_query
description: 生效策略查询（策略库检索）
version: 1.0.0
mcp_tools: [policy_lookup]
triggers:
  - "策略"
  - "policy"
  - "配置"
  - "生效"
tags: [ops, policy]
---

# policy_query

## Overview
查询指定类型的生效策略记录，无数据库时如实标注降级。

## When to Use
- 审核流程中触发 policy_query 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("policy_lookup")
# result = await tool.execute(...)
```
