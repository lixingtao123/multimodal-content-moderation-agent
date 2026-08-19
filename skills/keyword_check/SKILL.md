---
name: keyword-check
description: Detects sensitive keywords in text using local Aho-Corasick automaton. Use when checking content for prohibited terms, variant spellings, and evasion patterns. No external API calls required.
---

# Keyword Check

## Overview
Local sensitive keyword detection based on Aho-Corasick (AC) automaton for O(n) multi-pattern matching.

## When to Use
- First-pass content screening before LLM analysis
- Real-time chat/message filtering
- Detecting keyword variants (homophones, character splitting)

## How It Works
1. Loads keyword dictionary from `references/keyword_dict.txt`
2. Builds AC automaton (double-array trie)
3. Scans input text and returns all matches with positions

## Performance
- Time complexity: O(n + m) where n = text length, m = total matches
- Memory: ~500KB for 10,000 keywords
- Throughput: ~100MB/s on single CPU core

## Integration
```python
from mcp_servers.tools.keyword_check import KeywordCheckTool
tool = KeywordCheckTool()
result = await tool.execute("待检测文本")
# result.has_violation, result.matches, result.count
```
