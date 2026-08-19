---
name: pii_scan
description: 扫描文本中的隐私信息（手机号/身份证/银行卡/邮箱/IP），判定泄露风险
version: 1.0.0
mcp_tools: [pii_detect]
triggers:
  - "隐私"
  - "泄露"
  - "手机号"
  - "身份证"
  - "pii"
tags: [text, privacy]
---

# pii_scan

## Overview
正则匹配隐私信息模式，输出类型、命中片段与风险级别，用于审核前的隐私泄露预检。

## When to Use
- 审核流程中触发 pii_scan 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("pii_detect")
# result = await tool.execute(...)
```
