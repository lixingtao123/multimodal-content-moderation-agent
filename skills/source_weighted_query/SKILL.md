---
name: source_weighted_query
description: 来源加权检索（confirmed 数据优先于模拟数据）
version: 1.0.0
mcp_tools: [source_weighted_search]
triggers:
  - "来源"
  - "加权"
  - "simulated"
  - "confirmed"
  - "out_safe"
tags: [rag, retrieval]
---

# source_weighted_query

## Overview
按来源权重（confirmed>out_safe>simulated>model_labeled）加权排序检索结果。

## When to Use
- 审核流程中触发 source_weighted_query 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("source_weighted_search")
# result = await tool.execute(...)
```
