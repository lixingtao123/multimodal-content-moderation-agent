---
name: image_sensitive_scan
description: 图像敏感内容启发式扫描（肤色占比）
version: 1.0.0
mcp_tools: [image_sensitive_detect]
triggers:
  - "图片"
  - "图像"
  - "色情"
  - "敏感"
  - "image"
tags: [image, sensitive]
---

# image_sensitive_scan

## Overview
像素级肤色占比启发式评估图像敏感程度，输出占比与置信度，标注为启发式而非精确鉴黄。

## When to Use
- 审核流程中触发 image_sensitive_scan 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("image_sensitive_detect")
# result = await tool.execute(...)
```
