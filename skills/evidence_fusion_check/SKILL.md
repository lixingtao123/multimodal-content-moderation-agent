---
name: evidence_fusion_check
description: 多模态证据融合（非文本中心加权）
version: 1.0.0
mcp_tools: [evidence_fusion]
triggers:
  - "融合"
  - "证据"
  - "多模态"
  - "fusion"
  - "opinion"
tags: [decision, fusion]
---

# evidence_fusion_check

## Overview
融合各模态 agent 判定意见，按置信度加权产出最终决策。

## When to Use
- 审核流程中触发 evidence_fusion_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("evidence_fusion")
# result = await tool.execute(...)
```
