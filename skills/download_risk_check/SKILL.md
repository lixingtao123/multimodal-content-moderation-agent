---
name: download_risk_check
description: 下载链接风险检测（可执行/压缩包/脚本）
version: 1.0.0
mcp_tools: [download_risk]
triggers:
  - 下载
  - exe
  - apk
  - download
  - 安装包
  - app
  - APP
tags: [network, download]
---
# download_risk_check

## Overview
识别链接中的高风险文件扩展名（.exe/.apk/.bat/.zip 等），输出下载风险分。

## When to Use
- 审核流程中触发 download_risk_check 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。

## Integration
```python
# Skill 命中后，Agent 调用对应 MCP 工具
# from mcp_servers.registry import get_tool_registry
# tool = get_tool_registry().get("download_risk")
# result = await tool.execute(...)
```
