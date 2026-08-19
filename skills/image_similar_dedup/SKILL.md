---
name: image_similar_dedup
description: 图像感知哈希相似比对（dHash），相似图去重
version: 1.0.0
mcp_tools: [image_dedup]
triggers:
  - "相似图"
  - "去重"
  - "hash"
  - "重复"
  - "image"
tags: [image, dedup]
---

# image_similar_dedup

## Overview
对两张图像计算 dHash 与汉明距离，超阈值判为相似图，用于图片去重与近似内容治理。

## When to Use
- 审核流程中触发 image_similar_dedup 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("image_dedup")
# result = await tool.execute(...)
```
