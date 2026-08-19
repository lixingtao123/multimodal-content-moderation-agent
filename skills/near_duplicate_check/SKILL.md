---
name: near_duplicate_check
description: 文本近似重复检测（n-gram 指纹），识别洗稿/重复发布
version: 1.0.0
mcp_tools: [text_fingerprint]
triggers:
  - "重复"
  - "洗稿"
  - "近似"
  - "duplicate"
  - "重复发布"
tags: [text, dedup]
---

# near_duplicate_check

## Overview
对文本计算字符 n-gram 指纹，与参考文本做 Jaccard 相似度比对，超阈值判为近似重复。

## When to Use
- 审核流程中触发 near_duplicate_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("text_fingerprint")
# result = await tool.execute(...)
```
