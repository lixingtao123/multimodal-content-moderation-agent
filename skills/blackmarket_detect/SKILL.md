---
name: blackmarket_detect
description: 黑灰产黑话/谐音隐语检测（杀猪盘/跑分/加V等）
version: 1.0.0
mcp_tools: [blackmarket_slang]
triggers:
  - 黑话
  - 黑产
  - 隐语
  - 杀猪盘
  - 跑分
  - 脑残
tags: [text, blackhat]
---
# blackmarket_detect

## Overview
匹配黑灰产直接词、同音变体与拆字变体，输出命中黑话与风险分，辅助黑灰产判定。

## When to Use
- 审核流程中触发 blackmarket_detect 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("blackmarket_slang")
# result = await tool.execute(...)
```
