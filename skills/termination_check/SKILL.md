---
name: termination_check
description: 终止双签校验（高危类型/硬阈值/双签规则）
version: 1.0.0
mcp_tools: [termination_double_sign]
triggers:
  - "终止"
  - "双签"
  - "termination"
  - "高危"
  - "硬阈值"
tags: [decision, termination]
---

# termination_check

## Overview
确定性硬校验终止条件：高危类型且风险≥0.65 / 风险≥0.9 / 双签≥0.75。

## When to Use
- 审核流程中触发 termination_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("termination_double_sign")
# result = await tool.execute(...)
```
