---
name: semantic_cache_query
description: 语义缓存查询（相似问题命中缓存结果）
version: 1.0.0
mcp_tools: [semantic_cache_probe]
triggers:
  - "缓存"
  - "语义"
  - "cache"
  - "语义缓存"
tags: [rag, cache]
---

# semantic_cache_query

## Overview
查询语义缓存，相似度≥阈值时返回缓存审核结果，减少重复 LLM 调用。

## When to Use
- 审核流程中触发 semantic_cache_query 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("semantic_cache_probe")
# result = await tool.execute(...)
```
