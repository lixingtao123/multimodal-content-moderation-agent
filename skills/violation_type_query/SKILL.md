---
name: violation_type_query
description: 违规类型字典查询（13 类枚举与中文名）
version: 1.0.0
mcp_tools: [violation_type_lookup]
triggers:
  - "违规类型"
  - "枚举"
  - "violation"
  - "字典"
  - "查询"
tags: [ops, reference]
---

# violation_type_query

## Overview
查询违规类型枚举与中文名映射，供审核链与标注使用。

## When to Use
- 审核流程中触发 violation_type_query 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("violation_type_lookup")
# result = await tool.execute(...)
```
