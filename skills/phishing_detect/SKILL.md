---
name: phishing_detect
description: 钓鱼模式综合检测（仿官方品牌+诱导操作+紧急话术）
version: 1.0.0
mcp_tools: [phishing_pattern]
triggers:
  - "钓鱼"
  - "诈骗"
  - "phishing"
  - "冒充"
  - "验证码"
tags: [network, phishing]
---

# phishing_detect

## Overview
综合品牌冒充、紧急诱导、索取敏感操作三类信号计算钓鱼分。

## When to Use
- 审核流程中触发 phishing_detect 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("phishing_pattern")
# result = await tool.execute(...)
```
