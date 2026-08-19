---
name: shortlink_check
description: 短链识别与还原风险核验（t.cn/bit.ly 等）
version: 1.0.0
mcp_tools: [shortlink_expand]
triggers:
  - "短链"
  - "短链接"
  - "t.cn"
  - "shortlink"
  - "bit.ly"
tags: [network, url]
---

# shortlink_check

## Overview
识别主流短链域名并标注还原风险，提示需二次校验目的地。

## When to Use
- 审核流程中触发 shortlink_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("shortlink_expand")
# result = await tool.execute(...)
```
