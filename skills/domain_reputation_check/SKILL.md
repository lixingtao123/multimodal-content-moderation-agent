---
name: domain_reputation_check
description: 域名信誉评估（免费 TLD/钓鱼关键词）
version: 1.0.0
mcp_tools: [domain_reputation]
triggers:
  - "域名"
  - "domain"
  - "钓鱼"
  - "TLD"
  - "信誉"
tags: [network, domain]
---

# domain_reputation_check

## Overview
从文本提取域名，匹配高风险免费 TLD 与钓鱼诱导关键词，输出可疑域名清单。

## When to Use
- 审核流程中触发 domain_reputation_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("domain_reputation")
# result = await tool.execute(...)
```
