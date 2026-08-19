---
name: video_frame_strategy
description: 视频抽帧策略生成（均匀+关键段采样）
version: 1.0.0
mcp_tools: [video_frame_plan]
triggers:
  - "视频"
  - "抽帧"
  - "video"
  - "frame"
  - "关键帧"
tags: [video, sampling]
---

# video_frame_strategy

## Overview
按总时长生成均匀+关键段的抽帧点方案，供视频内容审核抽帧使用。

## When to Use
- 审核流程中触发 video_frame_strategy 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("video_frame_plan")
# result = await tool.execute(...)
```
