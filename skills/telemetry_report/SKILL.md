---
name: telemetry_report
description: 工具遥测质量报告（成功率/质量分/建议）
version: 1.0.0
mcp_tools: [tool_telemetry_report]
triggers:
  - "遥测"
  - "质量"
  - "telemetry"
  - "监控"
  - "成功率"
tags: [ops, monitoring]
---

# telemetry_report

## Overview
查询工具调用遥测，输出质量分与升级/降级/下线建议。

## When to Use
- 审核流程中触发 telemetry_report 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("tool_telemetry_report")
# result = await tool.execute(...)
```
