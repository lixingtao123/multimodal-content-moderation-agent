---
name: regression_guard
description: 优化回归守卫（指标变差建议回滚）
version: 1.0.0
mcp_tools: [regression_guard_check]
triggers:
  - "回归"
  - "回滚"
  - "优化"
  - "regression"
  - "rollback"
tags: [ops, optimization]
---

# regression_guard

## Overview
对比优化前后关键指标，变差超容差时建议回滚并标记。

## When to Use
- 审核流程中触发 regression_guard 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("regression_guard_check")
# result = await tool.execute(...)
```
