---
name: sensitive_expand
description: 敏感词变体生成（谐音/拆字/间隔），用于对抗样本库构建
version: 1.0.0
mcp_tools: [sensitive_word_expand]
triggers:
  - "变体"
  - "同音"
  - "谐音"
  - "对抗"
  - "expand"
tags: [text, adversarial]
---

# sensitive_expand

## Overview
为输入敏感词批量生成同音/拆字/间隔变体，供对抗样本构建与关键词库扩充。

## When to Use
- 审核流程中触发 sensitive_expand 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("sensitive_word_expand")
# result = await tool.execute(...)
```
