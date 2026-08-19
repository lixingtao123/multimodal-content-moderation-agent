---
name: image_quality_audit
description: 图像质量/格式审计（尺寸、格式、分辨率）
version: 1.0.0
mcp_tools: [image_quality_check]
triggers:
  - "清晰度"
  - "尺寸"
  - "格式"
  - "quality"
  - "分辨率"
tags: [image, quality]
---

# image_quality_audit

## Overview
解析图像尺寸与格式，识别低质/异常图像，供画质治理与格式合规检查。

## When to Use
- 审核流程中触发 image_quality_audit 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("image_quality_check")
# result = await tool.execute(...)
```
