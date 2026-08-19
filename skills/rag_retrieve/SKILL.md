---
name: rag-retrieve
description: 从历史案例库检索相似审核案例，作为判定依据。需要参考历史时使用。
tags: [rag, retrieve, history, case, similarity]
triggers: [历史案例, 相似案例, 检索, 参考, rag]
mcp_tools: [history_search]
---
# RAG Retrieve
从 Chroma 案例库检索相似历史审核案例，提供判定参考。调用 `history_search` 工具。
