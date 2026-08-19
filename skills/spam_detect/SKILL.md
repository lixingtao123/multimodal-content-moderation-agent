---
name: spam_detect
description: 识别垃圾营销广告与引流信息，包括诱导联系方式、红包福利、赚钱项目、下载注册等内容
version: 1.0.0
mcp_tools: [email_spam_detect]
triggers:
  - 营销
  - 广告
  - 引流
  - spam
  - 垃圾
  - 微
tags: [text, spam]
---
# spam_detect

## Overview
综合营销关键词、外链、感叹号等结构信号计算营销分，超阈值判为营销引流。

## When to Use
- 审核流程中触发 spam_detect 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("email_spam_detect")
# result = await tool.execute(...)
```
