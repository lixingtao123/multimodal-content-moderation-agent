---
name: device_risk_check
description: 设备风险信号评估（越狱/模拟器/多开/IP 共享）
version: 1.0.0
mcp_tools: [account_device_risk]
triggers:
  - "设备"
  - "越狱"
  - "模拟器"
  - "多开"
  - "device"
tags: [account, device]
---

# device_risk_check

## Overview
评估越狱、模拟器、多开、IP 共享等设备风险信号，输出风险分与级别。

## When to Use
- 审核流程中触发 device_risk_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("account_device_risk")
# result = await tool.execute(...)
```
