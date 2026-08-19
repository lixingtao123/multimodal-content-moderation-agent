---
name: rag_hybrid_query
description: 混合检索（BM25+向量+RRF+重排序），查相似案例
version: 1.0.0
mcp_tools: [rag_hybrid_search]
triggers:
  - "检索"
  - "RAG"
  - "相似案例"
  - "retrieve"
  - "hybrid"
tags: [rag, retrieval]
---

# rag_hybrid_query

## Overview
调用混合检索器查询与输入最相似的历史审核案例，供判定参考。

## When to Use
- 审核流程中触发 rag_hybrid_query 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("rag_hybrid_search")
# result = await tool.execute(...)
```
