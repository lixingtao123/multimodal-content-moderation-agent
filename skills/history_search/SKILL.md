---
name: history-search
description: Searches similar historical moderation cases using hybrid retrieval (BM25 + Dense Vector + Reranker). Use when analyzing content that may have precedents, or when confidence from LLM analysis alone is insufficient.
---

# History Search (Hybrid RAG)

## Overview
Hybrid retrieval system combining BM25 keyword search, ChromaDB dense vector search, and Cross-Encoder reranking for finding similar historical moderation cases.

## Architecture
```
Query → QueryRewriter → [BM25 ‖ ChromaDB] → RRF Fusion → CrossEncoder Rerank → Results
```

## When to Use
- Before making a final decision on borderline content
- When LLM confidence is below threshold (need historical evidence)
- For adversarial content detection (check if similar evasion patterns exist)

## Retrieval Strategies
| Query Type | Strategy | BM25 Weight | Vector Weight |
|-----------|----------|-------------|---------------|
| Short (<10 chars) | BM25 Dominant | 0.7 | 0.3 |
| Long (>100 chars) | Vector Dominant | 0.3 | 0.7 |
| Medium | Balanced Hybrid | 0.5 | 0.5 |

## Integration
```python
from memory.hybrid_retriever import get_hybrid_retriever
retriever = get_hybrid_retriever(chroma_service)
results = await retriever.search("query", top_k=5)
```
