---
name: behavior_anomaly_check
description: 账号行为异常评分（高频/夜间/新号突变）
version: 1.0.0
mcp_tools: [account_behavior_anomaly]
triggers:
  - "行为"
  - "异常"
  - "高频"
  - "夜间"
  - "anomaly"
tags: [account, behavior]
---

# behavior_anomaly_check

## Overview
综合发帖频率、夜间活跃、新账号突变等信号计算行为异常分与风险级别。

## When to Use
- 审核流程中触发 behavior_anomaly_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("account_behavior_anomaly")
# result = await tool.execute(...)
```
