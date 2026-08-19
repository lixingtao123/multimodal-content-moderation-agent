---
name: image_violence_scan
description: 图像暴力血腥启发式扫描（红色高饱和占比）
version: 1.0.0
mcp_tools: [image_violence_detect]
triggers:
  - "暴力"
  - "血腥"
  - "恐怖"
  - "红色"
  - "image"
tags: [image, violence]
---

# image_violence_scan

## Overview
统计高红色饱和度像素占比，启发式评估暴力血腥嫌疑，供图像审核预检。

## When to Use
- 审核流程中触发 image_violence_scan 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("image_violence_detect")
# result = await tool.execute(...)
```
