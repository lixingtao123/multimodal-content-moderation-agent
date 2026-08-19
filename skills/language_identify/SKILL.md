---
name: language_identify
description: 识别文本语种（中/英/日/韩/俄/阿拉伯），用于多语种路由
version: 1.0.0
mcp_tools: [language_detect]
triggers:
  - "语种"
  - "语言"
  - "language"
  - "多语言"
tags: [text, language]
---

# language_identify

## Overview
基于 Unicode 字符统计的启发式语种判定，返回语种与置信度，供分诊/路由决定后续处理链路。

## When to Use
- 审核流程中触发 language_identify 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("language_detect")
# result = await tool.execute(...)
```
