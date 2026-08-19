---
name: ip_check
description: IP 信誉核验（私网/保留段识别）
version: 1.0.0
mcp_tools: [ip_reputation]
triggers:
  - "IP"
  - "地址"
  - "私网"
  - "ip"
tags: [network, ip]
---

# ip_check

## Overview
提取文本中的 IP 并标记私网/保留段，辅助风控与溯源。

## When to Use
- 审核流程中触发 ip_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("ip_reputation")
# result = await tool.execute(...)
```
