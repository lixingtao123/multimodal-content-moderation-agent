---
name: media_toxic_probe
description: 媒体违规概率启发式估计（文件名/转写信号）
version: 1.0.0
mcp_tools: [media_toxic_estimate]
triggers:
  - "媒体"
  - "违规"
  - "media"
  - "概率"
  - "估计"
tags: [media, estimate]
---

# media_toxic_probe

## Overview
基于文件名与可用转写文本计算媒体违规概率估计，无转写时如实标注精度有限。

## When to Use
- 审核流程中触发 media_toxic_probe 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("media_toxic_estimate")
# result = await tool.execute(...)
```
