---
name: audio_metadata_audit
description: 音频元数据解析（时长/采样率/格式）
version: 1.0.0
mcp_tools: [audio_metadata_check]
triggers:
  - "音频"
  - "audio"
  - "时长"
  - "采样率"
  - "元数据"
tags: [audio, metadata]
---

# audio_metadata_audit

## Overview
解析音频时长/采样率/格式，无 mutagen 时按文件大小粗估并标注降级。

## When to Use
- 审核流程中触发 audio_metadata_audit 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("audio_metadata_check")
# result = await tool.execute(...)
```
