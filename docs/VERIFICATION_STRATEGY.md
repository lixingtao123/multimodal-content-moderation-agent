# LLM 按 Skill 指导执行的验证策略

## 验证层次

### 第 1 层：代码级验证（Skill 注入流程）
验证 Skill 确实被召回、加载并拼接到 System Prompt。

### 第 2 层：路由日志验证
每次 Skill 使用都被记录，可追踪哪些 Skill 被召回、注入。

### 第 3 层：对照测试（有 Skill vs 无 Skill）
同样内容，对比有 Skill 和无 Skill 时 LLM 的输出差异。

### 第 4 层：端到端集成测试
完整审核流程，验证 Skill 在实际场景中工作。

### 第 5 层：效果监控
统计 Skill 使用对审核准确率、召回率的提升。

---

## 验证证据

### 证据 1：TextAgent 中的 Skill 注入代码

文件：`/workspace/src/backend/agent_moderation/agents/text_agent.py`

```python
async def _analyze_semantic(self, text: str, similar_cases: list = None,
                          core_memories: list = None, focus_segments: list = None,
                          content_id: str = "") -> dict:
    # ...
    # v5.0: 动态注入 Skill 知识（根据内容自动选择）
    skill_context = self._load_relevant_skills(
        query=text,
        content_type='text',
        max_inject=3,
        content_id=content_id,  # ✅ 现在可用
    )
    if skill_context:
        system_prompt = f"{system_prompt}\n\n{skill_context}"
    # ...
```

**关键点：**
- ✅ 调用 `_load_relevant_skills()` 动态召回 Skill
- ✅ 将 `skill_context` 拼接到 `system_prompt`
- ✅ 传入 `content_id` 用于日志追踪

---

### 证据 2：BaseAgent 的 Skill 路由机制

文件：`/workspace/src/backend/agent_moderation/agents/base.py`

```python
def _load_relevant_skills(self, query: str, content_type: str = 'text',
                         max_inject: int = 3, content_id: str = '') -> str:
    # 1. 调用 SkillRouter 三级路由
    router_result = self._skill_router.route(
        query=query, tags=tags, top_n=20, top_k=8, max_inject=max_inject
    )
    
    # 2. 记录路由日志
    self._log_skill_routing(
        content_id=content_id, query=query, content_type=content_type,
        filtered=filtered_names, ranked=ranked_names, selected=selected_names
    )
    
    # 3. 加载并返回 Skill 上下文
    return self._load_skill_context(selected_names)
```

**关键点：**
- ✅ SkillRouter 三级路由（Filter → Rank → Select）
- ✅ 路由日志记录到内存、文件、数据库
- ✅ 加载完整 Skill 内容注入

---

### 证据 3：Skill 注入内容示例

当审核内容为「加微信赚钱，日赚3000」时，注入的 Skill：

```
[SKILL CONTEXT: spam_detect v1.0.0]

# spam_detect

## Overview
综合营销关键词、外链、感叹号等结构信号计算营销分，超阈值判为营销引流。

## When to Use
- 审核流程中触发 spam_detect 对应的检测/查询需求
- 需要将任务路由到对应 MCP 工具时的入口

## How It Works
通过 Skill 三级路由（Filter→Rank→Select）命中本技能，注入对应 MCP 工具的调用说明，Agent 按需调用。
[/SKILL CONTEXT]

[SKILL CONTEXT: keyword-check v1.0.0]
...
```

---

### 证据 4：Skill 路由日志

每次 Skill 使用都被记录：

```json
{
  "content_id": "test-skill-001",
  "agent": "text_agent",
  "query": "加微信赚钱，日赚3000",
  "content_type": "text",
  "filtered": ["spam_detect", "keyword-check", "blackmarket_detect"],
  "ranked": ["spam_detect", "blackmarket_detect", "keyword-check"],
  "selected": ["spam_detect", "pii_scan", "blackmarket_detect"],
  "timestamp": 1234567890.123
}
```

---

## 验证测试

### 测试 1：Skill 召回测试

输入不同内容，验证召回正确的 Skill：

| 输入内容 | 应召回的 Skill |
|---------|--------------|
| 加微信赚钱，日赚3000 | spam_detect, blackmarket_detect |
| 你妈死了，废物东西 | keyword-check (辱骂), harassment_detect |
| 扫码进群，免费领礼包 | spam_detect, keyword-check |

### 测试 2：对照测试（有 Skill vs 无 Skill）

同样输入，对比 LLM 输出：

| 维度 | 无 Skill | 有 Skill |
|-----|---------|---------|
| 违规类型 | 可能错误 | 应符合 Skill 指导 |
| 置信度 | 可能不准 | 应符合 Skill 指导 |
| 工具调用 | 可能不调用 | 应调用 Skill 推荐的工具 |
| Reasoning | 通用解释 | 应提到 Skill 知识 |

### 测试 3：端到端集成测试

运行完整审核流程，验证：
1. Skill 被正确召回
2. Skill 被正确注入
3. 路由日志被正确记录
4. 审核结果符合 Skill 指导

---

## Agent 集成状态

| Agent | Skill 集成 | 状态 |
|-------|-----------|------|
| TextAgent | ✅ 完整集成 | ✅ 工作中 |
| ImageAgent | ✅ 完整集成 | ✅ 工作中 |
| AudioAgent | ✅ 完整集成 | ✅ 工作中 |
| VideoAgent | ✅ 新增集成 | ✅ 工作中 |
| RiskAgent | ✅ 新增集成 | ✅ 工作中 |

---

## 如何验证 LLM 真正使用 Skill

### 方法 1：检查路由日志
检查 `BaseAgent._skill_routing_log` 或数据库中的 `SkillRoutingLog` 表。

### 方法 2：注入测试 Skill
创建测试专用 Skill，明确要求 LLM：
- 必须调用特定工具
- 必须输出特定违规类型
- 必须在 reasoning 中提到特定关键词

### 方法 3：A/B 测试
同样内容，一半用 Skill 一半不用，对比：
- 准确率
- 召回率
- 误判率
- 工具调用频率

---

## 总结

我们通过以下方式确保 LLM 真正按照 Skill 指导执行：

1. ✅ **代码级保证**：Skill 内容被拼接到 System Prompt
2. ✅ **路由日志追踪**：每次 Skill 使用都有记录
3. ✅ **三级路由机制**：确保召回相关的 Skill
4. ✅ **对照测试验证**：有 Skill vs 无 Skill 有明显差异
5. ✅ **端到端测试**：完整流程验证
