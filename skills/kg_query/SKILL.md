---
name: kg_query
description: 违规类型知识图谱查询（关联类型/扩展检索词）
version: 1.0.0
mcp_tools: [knowledge_graph_query]
triggers:
  - "图谱"
  - "关联"
  - "kg"
  - "违规类型"
  - "扩展"
tags: [rag, graph]
---

# kg_query

## Overview
查询违规类型间的关联关系，生成扩展检索词用于召回增强。

## When to Use
- 审核流程中触发 kg_query 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("knowledge_graph_query")
# result = await tool.execute(...)
```
