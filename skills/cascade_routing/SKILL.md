---
name: cascade_routing
description: 模型级联路由（小模型优先，低置信升级）
version: 1.0.0
mcp_tools: [model_cascade_route]
triggers:
  - "级联"
  - "模型"
  - "cascade"
  - "升级"
  - "成本"
tags: [decision, cost]
---

# cascade_routing

## Overview
根据小模型置信度决定是否升级大模型复核，平衡成本与准确率。

## When to Use
- 审核流程中触发 cascade_routing 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("model_cascade_route")
# result = await tool.execute(...)
```
