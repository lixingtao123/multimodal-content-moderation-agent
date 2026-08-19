---
name: reputation_check
description: 用户信誉分计算（历史违规/活跃/人工反馈）
version: 1.0.0
mcp_tools: [user_reputation]
triggers:
  - "信誉"
  - "历史违规"
  - "reputation"
  - "评分"
tags: [account, reputation]
---

# reputation_check

## Overview
综合历史违规、内容活跃、人工确认结果计算用户信誉分与级别。

## When to Use
- 审核流程中触发 reputation_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("user_reputation")
# result = await tool.execute(...)
```
