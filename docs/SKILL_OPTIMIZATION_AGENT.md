# SkillOptimizationAgent 完整实现原理详解

## 概述

本文档详细解释 SkillOptimizationAgent 如何工作，从 LLM 建议到修改 Skill 文件的完整流程。

---

## 核心设计原则

### 1. 纯函数设计（Pure Function）

`_modify_skill_content` 是**纯函数**，它：
- 不修改输入参数
- 没有副作用
- 相同输入总是返回相同输出
- 只做字符串处理逻辑与外部状态隔离

```python
def _modify_skill_content(
    self,
    content: str,          # 原始内容（不可变）
    suggestion: SkillOptimizationSuggestion
) -> str:              # 返回新内容
    # 只做纯字符串处理
    # 不修改任何外部文件
    pass
```

---

## 完整流程（分步解析

### 阶段一：数据采集与准备

```python
async def analyze_and_suggest(self, log_dir, min_logs):
```

**步骤1：从数据库加载路由日志

```
数据库表：skill_routing_logs
├─ content_id: "abc123"
├─ agent: "text_agent"
├─ query: "加微信abc123"
├─ filtered: ["spam_detect", "pii_scan"]
├─ ranked: ["spam_detect", "pii_scan", "keyword_check"]
├─ selected: ["spam_detect", "pii_scan"]
└─ timestamp: 123456789
```

**步骤2：获取当前所有 Skills**（通过 SkillRegistry）

```python
skills_list = [
    {
        "name": "spam_detect",
        "description": "检测垃圾广告信息",
        "triggers": ["微信", "加好友"],
        "tags": ["safety", "text"],
        "version": "1.0.0"
    },
    ...
]
```

---

### 阶段二：LLM 分析与建议生成

**核心函数**：`_generate_suggestions_with_llm()`

#### 2.1 构建 LLM 提示词

提示词包含：
1. **Skill 路由原理**（解释 Filter→Rank→Select）
2. **当前所有 Skills 列表**（完整配置）
3. **路由日志摘要**
   - 总日志数
   - Skill使用统计
   - 最近50条日志样本
4. **具体任务**（5类优化机会）
5. **严格的输出格式要求**（JSON Schema）
6. **质量要求**（置信度、理由充分性等）

#### 2.2 调用 LLM

```python
response = await client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.3,      # 低温度，稳定
    max_tokens=3000,
    response_format={"type": "json_object"}
)
```

**LLM 期望的输出格式**：
```json
{
    "analysis_summary": "分析86条路由日志后，发现3个优化机会...",
    "suggestions": [
        {
            "skill_name": "spam_detect",
            "suggestion_type": "trigger_add",
            "current_value": "",
            "suggested_value": "加微信",
            "reason": "在23条含'微信'的日志中，有7条spam_detect未被选中...",
            "confidence": 0.9,
            "supporting_examples": ["加微信abc123", "加v聊"],
            "analysis_detail": "问题影响：垃圾识别率较低，可能漏掉某些变体...",
            "impact": "高"
        }
    ]
}
```

#### 2.3 解析与验证建议（重要的过滤）

**验证步骤**：
```
1. 置信度 ≥ 0.7  → 低质量建议被过滤
2. 字段完整性 → skill_name, suggestion_type 等必填
3. 类型有效性 → 必须是 valid_types 中的一种
4. 建议值非空 → suggested_value 必须有内容
5. 新旧值不同 → description_update 等操作必须真的改变了值
6. 理由充分性 → reason 长度 ≥ 20 字符
7. Skill 存在性 → 除了 new_skill，其他类型必须对应现存 skill
```

---

### 阶段三：保存优化报告（保存到 json 文件）

**报告保存位置**：
```
/workspace/skills_backups/reports/
└─ skill_opt_1786629409.json
```

**报告内容结构**：
```python
{
    "generated_at": 1786629409.0,
    "suggestion_count": 2,
    "suggestions": [...],
    "analysis_summary": "...",
    "voting_required": true,
    "votes": [],
    "approved": false,
    "report_path": "/workspace/skills_backups/reports/skill_opt_xxx.json"
}
```

---

### 阶段四：投票审批（2/3通过机制）

**投票流程**：

```
1. 用户在前端点击「👍 通过」或「👎 拒绝」
   ↓
2. 前端调用 API: POST /tech/skill-optimization/suggestions/{suggestion_id}/vote
   Body: {"voter": "user1", "vote": true, "comment": "同意"}
   ↓
3. 后端: optimizer.add_vote(report_path, voter, vote, comment)
   ↓
4. 加载报告，追加投票记录
   ↓
5. 检查是否达到批准条件：
   ├─ 总票数 ≥ 3
   └─ 赞成票 ≥ 2
   ↓
6. 如果条件满足 → report.approved = true
   ↓
7. 保存更新后的报告
```

**投票数据结构**：
```python
{
    "voter": "user1",
    "vote": true,
    "comment": "同意，这个优化合理",
    "timestamp": 1786629500.0
}
```

---

### 阶段五：应用优化（最关键的部分）

**这是实际修改 Skill 文件的过程**

#### 5.1 入口函数
```python
async def apply_suggestions(self, report: SkillOptimizationReport) -> Dict
```

#### 5.2 逐条应用建议

```python
for suggestion in report.suggestions:
    if suggestion.suggestion_type == "new_skill":
        await self._create_new_skill(suggestion)
    else:
        await self._update_existing_skill(suggestion)
```

---

### 阶段六：更新现有 Skill（核心实现）

**函数**：`_update_existing_skill()`

**详细流程（分步）**：

#### 步骤1：定位 Skill 文件
```python
skill_dir = SKILLS_DIR / skill_name
# 如果不存在，尝试下划线命名
skill_dir = SKILLS_DIR / skill_name.replace('-', '_')
# 仍不存在 → 报错
```

#### 步骤2：读取原文件内容
```python
skill_file = skill_dir / "SKILL.md"
with open(skill_file, 'r', encoding='utf-8') as f:
    content = f.read()
```

**示例原文件**：
```markdown
---
name: spam_detect
description: 检测垃圾广告信息
version: 1.0.0
tags: ["safety", "text"]
triggers: ["微信", "加好友"]
---

# spam_detect

## Overview
识别垃圾广告，特别是加联系方式的内容
```

#### 步骤3：备份原文件（安全机制）
```python
backup_path = self._backup_skill(skill_name, skill_file)
# 保存到: /workspace/skills_backups/spam_detect_v1786629500.md
```

#### 步骤4：修改内容（纯函数！！）
```python
new_content = self._modify_skill_content(content, suggestion)
```

**纯函数 _modify_skill_content 的实现**：

这个函数是**完全纯的**，它：
- 不修改任何外部状态
- 只做字符串操作
- 返回新字符串

**分步处理**：

1. **解析 frontmatter**（用正则分割）
   ```python
   frontmatter_match = FRONTMATTER_RE.match(content)
   frontmatter_str = frontmatter_match.group(1)
   body = content[frontmatter_match.end():]
   ```

2. **将 frontmatter 转为字典**
   ```python
   frontmatter = self._parse_simple_frontmatter(frontmatter_str)
   # 结果:
   # {
   #   "name": "spam_detect",
   #   "description": "检测垃圾广告信息",
   #   ...
   # }
   ```

3. **根据建议类型做不同修改**

   **3.1 trigger_add**:
   ```python
   if sug_type == "trigger_add":
       if "triggers" not in frontmatter:
           frontmatter["triggers"] = []
       if isinstance(frontmatter["triggers"], list):
           # 检查是否已存在，避免重复添加
           if trigger_val not in frontmatter["triggers"]:
               frontmatter["triggers"].append(trigger_val)
   ```

   **3.2 description_update**:
   ```python
   if sug_type == "description_update":
       frontmatter["description"] = suggestion.suggested_value
   ```

   **3.3 tag_add**:
   ```python
   if sug_type == "tag_add":
       if "tags" not in frontmatter:
           frontmatter["tags"] = []
       if tag_val not in frontmatter["tags"]:
           frontmatter["tags"].append(tag_val)
   ```

4. **重新生成 frontmatter 字符串**
   ```python
   new_frontmatter = self._generate_frontmatter(frontmatter)
   ```

5. **拼接返回新内容**
   ```python
   return f"{new_frontmatter}\n{body}"
   ```

#### 步骤5：写回文件
```python
with open(skill_file, 'w', encoding='utf-8') as f:
    f.write(new_content)
```

**修改后的文件示例**：
```markdown
---
name: spam_detect
description: 检测垃圾广告信息（优化版）
version: 1.0.0
tags: ["safety", "text", "spam"]
triggers: ["微信", "加好友", "加微信"]
---

# spam_detect

## Overview
识别垃圾广告，特别是加联系方式的内容
```

---

### 阶段七：创建新 Skill（可选）

**函数**：`_create_new_skill()`

```python
# 1. 规范化名称（避免非法字符）
skill_name = re.sub(r'[^\w\-]', '_', skill_name).lower()

# 2. 创建目录
skill_dir = SKILLS_DIR / skill_name
skill_dir.mkdir(exist_ok=True)

# 3. 生成内容
skill_content = f"""---
name: {skill_name}
description: {suggestion.suggested_value}
version: 1.0.0
tags: ["new"]
triggers: []
---

# {skill_name}

## Overview
{suggestion.reason}

## When to Use
待补充...
"""

# 4. 保存文件
skill_file = skill_dir / "SKILL.md"
with open(skill_file, 'w', encoding='utf-8') as f:
    f.write(skill_content)
```

---

## 安全机制

### 1. 备份机制

**每次修改前都备份**
```
修改前
/workspace/skills/spam_detect/SKILL.md → 备份到
/workspace/skills_backups/spam_detect_v1786629500.md
```

### 2. 投票机制

**2/3通过才允许应用**
```
用户1: 👍 通过
用户2: 👎 拒绝
用户3: 👍 通过
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
总票数: 3, 赞成: 2 → 达到2/3, 批准应用
```

### 3. 建议验证过滤

**只保留高质量建议**
- 置信度 <0.7 → 自动过滤
- 理由太短 → 自动过滤
- 新旧值相同 → 自动过滤
- Skill 不存在 → 自动过滤

---

## 文件目录结构

```
/workspace/
├─ skills/                          # Skills 目录（实际生效）
│  ├─ spam_detect/
│  │  └─ SKILL.md
│  ├─ pii_scan/
│  │  └─ SKILL.md
│  └─ violation_type_query/
│     └─ SKILL.md
│
├─ skills_backups/                  # 备份目录（安全保障）
│  ├─ reports/
│  │  ├─ skill_opt_1786629409.json  # 优化报告
│  │  └─ skill_opt_1786629500.json
│  ├─ spam_detect_v1786629500.md     # 被修改前的备份
│  └─ pii_scan_v1786629600.md
│
└─ src/backend/
   └─ optimization/
      └─ skill_optimization_agent.py  # 本Agent实现
```

---

## API 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/tech/skill-optimization/analyze` | POST | 触发分析，生成建议 |
| `/tech/skill-optimization/suggestions` | GET | 获取待审批建议 |
| `/tech/skill-optimization/suggestions/{id}/vote` | POST | 投票 |
| `/tech/skill-optimization/apply` | POST | 应用优化 |
| `/tech/skill-optimization/reports` | GET | 获取历史报告 |

---

## 数据流向图

```
用户点击「分析并优化」
        ↓
    [API]
        ↓
    [SkillOptimizationAgent]
        ↓
    [从DB加载路由日志] ← skill_routing_logs表
        ↓
    [构建提示词] ─┬─ 当前Skills
                    ├─ 日志统计
                    └─ 日志样本
        ↓
    [调用LLM] ← DeepSeek API
        ↓
    [解析JSON]
        ↓
    [验证过滤] ─┬─ 置信度≥0.7?
                    ├─ 字段完整?
                    ├─ 类型有效?
                    ├─ 理由充分?
                    └─ Skill存在?
        ↓
    [保存报告] → /workspace/skills_backups/reports/xxx.json
        ↓
    [返回前端]
        ↓
    [用户投票]
        ↓
    [达到2/3]?
        ├─ 是 → [应用优化]
        └─ 否 → [等待更多投票]
        ↓
    [应用优化] ─┬─ 备份原文件 → /workspace/skills_backups/xxx_v12345.md
                 ├─ 修改frontmatter(纯函数)
                 └─ 写回文件 → /workspace/skills/xxx/SKILL.md
        ↓
    [完成]
```

---

## 总结

### 核心要点

1. **纯函数设计**：`_modify_skill_content` 不改变状态
2. **安全机制**：备份、投票、验证
3. **三步修改**：解析 → 修改 → 重新生成
4. **frontmatter 只修改**：保持 body 内容不变
5. **验证严格**：只保留高质量建议

### 为什么这样设计?

| 设计决策 | 原因 |
|----------|------|
| 纯函数修改 | 安全、可测试、副作用隔离 |
| frontmatter 只改 | body 可能很长，改配置就行 |
| 先备份再修改 | 可以随时回滚，不丢失 |
| 2/3 通过才应用 | 多人审批，避免错误优化 |
| LLM建议+人工 | LLM分析，人类把关 |

