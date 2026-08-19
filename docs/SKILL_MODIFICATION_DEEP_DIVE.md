# Skill 文件修改原理深入详解

本文档**100%详细解释**：如何找到位置、如何解析、如何修改、如何拼接回去。

---

## 0️⃣ **前置知识：正则表达式 FRONTMATTER_RE**

```python
FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)
```

### **分解这个正则表达式**

让我们逐个字符拆解：

| 部分 | 含义 |
|------|------|
| `^` | 匹配字符串开头 |
| `---` | 匹配三个短横线（字面） |
| `\s*` | 匹配0个或多个空白字符（空格、制表符等） |
| `\n` | 匹配换行符 |
| `(.*?)` | 匹配任意字符（非贪婪，尽可能少），这是分组 |
| `\n---` | 匹配换行后再三个短横线 |
| `\s*\n` | 匹配可选空白和换行 |
| `re.DOTALL` | 让 `.` 也能匹配换行符（默认 `.` 不匹配换行） |

---

## 1️⃣ **步骤一：定位和分割（找到对应位置）**

### **可视化例子**

假设有这个文件内容：

```
Line 1: ---
Line 2: name: spam_detect
Line 3: description: 检测广告
Line 4: version: 1.0.0
Line 5: tags: ["safety", "text"]
Line 6: triggers:
Line 7:   - 微信
Line 8:   - 加好友
Line 9: ---
Line 10:
Line 11: # spam_detect
Line 12:
Line 13: ## Overview
Line 14: 这里是具体实现...
```

### **正则匹配过程**

```python
FRONTMATTER_RE.match(content)
    ↓
从内容开头开始匹配
    ↓
找到 ^--- (行1)
    ↓
找到中间内容 (.*?) → 行2-8
    ↓
找到最后一个 \n---\s*\n → 行9前后
    ↓
匹配成功！

分组结果：
├─ group(0): 完整匹配（行1-9）
└─ group(1): frontmatter 内容（行2-8）
```

### **代码实现**

```python
# 定位分割
frontmatter_match = FRONTMATTER_RE.match(content)

if not frontmatter_match:
    # 没有 frontmatter → 跳过
    return content

# 提取
frontmatter_str = frontmatter_match.group(1)  # 行2-8
body = content[frontmatter_match.end():]      # 行10开始的内容
```

---

## 2️⃣ **步骤二：解析 frontmatter（字符串→字典）**

### **解析函数**：`_parse_simple_frontmatter(frontmatter_str)`

### **详细解析示例**

**输入** (字符串)：
```
name: spam_detect
description: 检测广告
version: 1.0.0
tags: ["safety", "text"]
triggers:
  - 微信
  - 加好友
```

**处理流程**：

```
逐行遍历：

行 1: "name: spam_detect"
    ├─ 发现有冒号
    ├─ 分割 key="name", val="spam_detect"
    ├─ 存入 frontmatter = {"name": "spam_detect"}
    └─ current_key = "name"

行 2: "description: 检测广告"
    ├─ 发现有冒号
    ├─ 分割 key="description", val="检测广告"
    ├─ 存入 frontmatter = {"name": "spam_detect", "description": "检测广告"}
    └─ current_key = "description"

行 3: "version: 1.0.0"
    ├─ 类似处理
    └─ frontmatter["version"] = "1.0.0"

行 4: "tags: [\"safety\", \"text\"]"
    ├─ 发现有冒号
    ├─ val 以 "[" 开头 → 尝试用 JSON 解析
    ├─ 解析成功！→ tags = ["safety", "text"]
    └─ frontmatter["tags"] = ["safety", "text"]

行 5: "triggers:"
    ├─ 发现有冒号
    ├─ val 为空
    └─ 标记 current_key = "triggers", 开始一个列表

行 6: "  - 微信"
    ├─ 发现以 "- " 开头
    ├─ 有 current_key ("triggers")
    ├─ 取 val = "微信"
    ├─ 追加到列表
    └─ frontmatter["triggers"] = ["微信"]

行 7: "  - 加好友"
    ├─ 同样处理
    └─ frontmatter["triggers"] = ["微信", "加好友"]
```

**最终输出** (字典)：
```python
{
    "name": "spam_detect",
    "description": "检测广告",
    "version": "1.0.0",
    "tags": ["safety", "text"],
    "triggers": ["微信", "加好友"]
}
```

### **解析代码详解**

```python
def _parse_simple_frontmatter(self, frontmatter_str: str) -> Dict:
    lines = frontmatter_str.splitlines()
    frontmatter = {}
    current_key = None
    current_list = []

    for line in lines:
        line = line.strip()

        # 跳过空行和注释
        if not line or line.startswith('#'):
            continue

        # 情形 A: 列表项 "- xxx"
        if line.startswith('- '):
            if current_key:
                # 提取值
                val = line[2:].strip()
                try:
                    # 尝试解析成 JSON
                    parsed = json.loads(val)
                    current_list.append(parsed)
                except Exception:
                    # 不行就当字符串
                    current_list.append(val)
                # 更新回字典
                frontmatter[current_key] = current_list

        # 情形 B: 键值对 "key: value"
        elif ':' in line:
            key, val = line.split(':', 1)
            key = key.strip()
            val = val.strip()
            current_key = key
            current_list = []

            if val.startswith('[') or val.startswith('{'):
                # 值是 JSON 数组或对象
                try:
                    frontmatter[key] = json.loads(val)
                except Exception:
                    frontmatter[key] = val
            elif val:
                # 值是普通字符串
                frontmatter[key] = val
            else:
                # 值为空，开始一个列表
                pass

    return frontmatter
```

---

## 3️⃣ **步骤三：修改字典（各种操作）**

现在我们有了字典，可以做任何修改了！

让我们看**每种优化类型的具体实现**：

---

### **操作 A: trigger_add（添加触发词）**

**输入建议**：
```python
SkillOptimizationSuggestion(
    skill_name="spam_detect",
    suggestion_type="trigger_add",
    current_value="",
    suggested_value="加微信",
    ...
)
```

**修改代码**：
```python
if sug_type == "trigger_add":
    # 1. 确保存在 triggers 列表
    if "triggers" not in frontmatter:
        frontmatter["triggers"] = []

    if isinstance(frontmatter["triggers"], list):
        trigger_val = suggestion.suggested_value

        # 2. 检查是否已存在（避免重复）
        if trigger_val not in frontmatter["triggers"]:
            # 3. 添加！
            frontmatter["triggers"].append(trigger_val)
```

**效果**：
```
修改前
"triggers": ["微信", "加好友"]
                ↓
修改后
"triggers": ["微信", "加好友", "加微信"]
                                      ↑ 新增的！
```

---

### **操作 B: trigger_remove（删除触发词）**

**输入建议**：
```python
SkillOptimizationSuggestion(
    skill_name="spam_detect",
    suggestion_type="trigger_remove",
    current_value="微信",
    suggested_value="",
    ...
)
```

**修改代码**：
```python
if sug_type == "trigger_remove":
    if "triggers" in frontmatter and isinstance(frontmatter["triggers"], list):
        trigger_val = suggestion.current_value

        # 找到并移除
        if trigger_val in frontmatter["triggers"]:
            frontmatter["triggers"].remove(trigger_val)
```

**效果**：
```
修改前
"triggers": ["微信", "加好友", "加微信"]
            ↑ 删除这个
                ↓
修改后
"triggers": ["加好友", "加微信"]
```

---

### **操作 C: description_update（更新描述）**

**输入建议**：
```python
SkillOptimizationSuggestion(
    skill_name="spam_detect",
    suggestion_type="description_update",
    current_value="检测广告",
    suggested_value="检测垃圾广告，包括加联系方式的内容",
    ...
)
```

**修改代码**：
```python
if sug_type == "description_update":
    # 直接替换！
    frontmatter["description"] = suggestion.suggested_value
```

**效果**：
```
修改前
"description": "检测广告"
                ↓ 完全替换
修改后
"description": "检测垃圾广告，包括加联系方式的内容"
```

---

### **操作 D: tag_add（添加标签）**

**输入建议**：
```python
SkillOptimizationSuggestion(
    skill_name="spam_detect",
    suggestion_type="tag_add",
    current_value="",
    suggested_value="spam",
    ...
)
```

**修改代码**：
```python
if sug_type == "tag_add":
    if "tags" not in frontmatter:
        frontmatter["tags"] = []
    if isinstance(frontmatter["tags"], list):
        tag_val = suggestion.suggested_value
        if tag_val not in frontmatter["tags"]:
            frontmatter["tags"].append(tag_val)
```

**效果**：
```
修改前
"tags": ["safety", "text"]
                ↓
修改后
"tags": ["safety", "text", "spam"]
```

---

### **操作 E: tag_remove（删除标签）**

```python
if sug_type == "tag_remove":
    if "tags" in frontmatter and isinstance(frontmatter["tags"], list):
        tag_val = suggestion.current_value
        if tag_val in frontmatter["tags"]:
            frontmatter["tags"].remove(tag_val)
```

---

### **操作 F: new_skill（创建新 Skill）**

这是特殊情况，不是修改现有文件，而是创建全新的：

```python
async def _create_new_skill(self, suggestion):
    # 1. 规范化名称
    skill_name = suggestion.skill_name
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

    # 4. 保存
    skill_file = skill_dir / "SKILL.md"
    with open(skill_file, 'w', encoding='utf-8') as f:
        f.write(skill_content)
```

---

## 4️⃣ **步骤四：生成新 frontmatter（字典→字符串）**

### **生成函数**：`_generate_frontmatter(frontmatter)`

### **详细生成示例**

**输入** (字典)：
```python
{
    "name": "spam_detect",
    "description": "检测垃圾广告，包括加联系方式的内容",
    "version": "1.0.0",
    "tags": ["safety", "text", "spam"],
    "triggers": ["微信", "加好友", "加微信"]
}
```

**输出** (字符串)：
```
name: spam_detect
description: 检测垃圾广告，包括加联系方式的内容
version: 1.0.0
tags: ["safety", "text", "spam"]
triggers:
  - 微信
  - 加好友
  - 加微信
```

### **生成代码详解**

让我补充这个函数（之前代码可能不完整）：

```python
def _generate_frontmatter(self, frontmatter: Dict) -> str:
    """从字典生成 frontmatter 字符串"""
    lines = []

    for key, value in frontmatter.items():
        # 情形 A: 值是列表
        if isinstance(value, list):
            # 检查是否是空列表？
            if len(value) > 0 and isinstance(value[0], str):
                # 字符串列表，用多行形式
                lines.append(f"{key}:")
                for item in value:
                    # 转义特殊字符？或者直接 JSON 化？
                    # 简单处理：如果不包含特殊字符，直接写
                    if '"' in str(item) or ':' in str(item):
                        lines.append(f'  - {json.dumps(item, ensure_ascii=False)}')
                    else:
                        lines.append(f'  - {item}')
            else:
                # 其他列表，JSON 化
                lines.append(f'{key}: {json.dumps(value, ensure_ascii=False)}')

        # 情形 B: 值是字典
        elif isinstance(value, dict):
            lines.append(f'{key}: {json.dumps(value, ensure_ascii=False)}')

        # 情形 C: 值是字符串（包含特殊字符的话用引号）
        elif isinstance(value, str):
            if ':' in value or '#' in value or '"' in value:
                lines.append(f'{key}: {json.dumps(value, ensure_ascii=False)}')
            else:
                lines.append(f'{key}: {value}')

        # 情形 D: 其他类型（数字、布尔）
        else:
            lines.append(f'{key}: {value}')

    # 拼接成最终字符串
    content = '\n'.join(lines)

    # 包裹在 --- 之间
    return f'---\n{content}\n---'
```

---

## 5️⃣ **步骤五：拼接回去（生成最终内容）**

### **拼接操作**

```python
# 新的 frontmatter 字符串
new_frontmatter = self._generate_frontmatter(frontmatter)

# 拼接 = 新 frontmatter + 原来的 body
return f"{new_frontmatter}\n{body}"
```

### **完整拼接可视化**

```
┌─────────────────────────────────┐
│  新 frontmatter                  │
│  ---                            │
│  name: spam_detect              │
│  description: 新版...            │
│  ...                            │
│  ---                            │
└─────────────────────────────────┘
            ↓ 拼接
┌─────────────────────────────────┐
│  原来的 body (不变!)            │
│                                  │
│  # spam_detect                  │
│                                  │
│  ## Overview                    │
│  这里是具体实现...              │
└─────────────────────────────────┘
            ↓
┌─────────────────────────────────┐
│  最终完整文件                    │
│  ---                            │
│  name: spam_detect              │
│  description: 新版...            │
│  ...                            │
│  ---                            │
│                                  │
│  # spam_detect                  │
│  ...                            │
└─────────────────────────────────┘
```

---

## 6️⃣ **完整流程图解（一个示例）**

### **目标**：给 spam_detect 添加一个触发词 "加微信"

```
┌───────────────────────────────────────────────────────────────┐
│ 步骤1: 读取原文件                                              │
└───────────────────────────────────────────────────────────────┘
   ↓
   文件内容 = """
---
name: spam_detect
description: 检测广告
version: 1.0.0
tags: ["safety", "text"]
triggers:
  - 微信
  - 加好友
---

# spam_detect

## Overview
这里是具体实现...
"""

┌───────────────────────────────────────────────────────────────┐
│ 步骤2: 正则分割 (FRONTMATTER_RE)                              │
└───────────────────────────────────────────────────────────────┘
   ↓
   frontmatter_str = """name: spam_detect
description: 检测广告
version: 1.0.0
tags: ["safety", "text"]
triggers:
  - 微信
  - 加好友"""
   ↓
   body = """
# spam_detect

## Overview
这里是具体实现...
"""

┌───────────────────────────────────────────────────────────────┐
│ 步骤3: 解析成字典                                              │
└───────────────────────────────────────────────────────────────┘
   ↓
   frontmatter = {
       "name": "spam_detect",
       "description": "检测广告",
       "version": "1.0.0",
       "tags": ["safety", "text"],
       "triggers": ["微信", "加好友"]
   }

┌───────────────────────────────────────────────────────────────┐
│ 步骤4: 修改字典 (trigger_add)                                 │
└───────────────────────────────────────────────────────────────┘
   ↓
   frontmatter["triggers"].append("加微信")
   ↓
   frontmatter = {
       "name": "spam_detect",
       "description": "检测广告",
       "version": "1.0.0",
       "tags": ["safety", "text"],
       "triggers": ["微信", "加好友", "加微信"]  # ← 新增!
   }

┌───────────────────────────────────────────────────────────────┐
│ 步骤5: 生成新 frontmatter                                      │
└───────────────────────────────────────────────────────────────┘
   ↓
   new_frontmatter = """
---
name: spam_detect
description: 检测广告
version: 1.0.0
tags: ["safety", "text"]
triggers:
  - 微信
  - 加好友
  - 加微信
---"""

┌───────────────────────────────────────────────────────────────┐
│ 步骤6: 拼接 new_frontmatter + body                             │
└───────────────────────────────────────────────────────────────┘
   ↓
   final_content = """
---
name: spam_detect
description: 检测广告
version: 1.0.0
tags: ["safety", "text"]
triggers:
  - 微信
  - 加好友
  - 加微信
---

# spam_detect

## Overview
这里是具体实现...
"""

┌───────────────────────────────────────────────────────────────┐
│ 步骤7: 写回文件                                                │
└───────────────────────────────────────────────────────────────┘
   ↓
   完成！✓
```

---

## 7️⃣ **边界情况与限制**

### **可以处理的**

| 操作 | 是否支持 |
|------|---------|
| 修改简单字段 (name, description) | ✅ 支持 |
| 给列表添加元素 (trigger_add, tag_add) | ✅ 支持 |
| 从列表删除元素 (trigger_remove, tag_remove) | ✅ 支持 |
| 保持原 body 内容不变 | ✅ 支持 |

### **暂不支持的**

| 操作 | 原因 |
|------|------|
| 修改 body 内容 | 设计只修改 frontmatter |
| 复杂的嵌套字典列表 | 简单 frontmatter 不需要 |
| YAML 的高级特性 | 只用简单子集 |

---

## 8️⃣ **为什么这样设计？**

### **设计决策对比**

| 方案 | 优点 | 缺点 |
|------|------|------|
| **方案A: 用完整 YAML 库** | 能处理所有 YAML | 增加依赖，可能过度设计 |
| **方案B: 简单解析器（当前）** | 无依赖，快速，可控 | 只处理简单子集 |
| **方案C: 直接字符串替换** | 实现简单 | 容易出错，不健壮 |

### **为什么选择方案B？**

因为 frontmatter 的格式是**固定且简单的**：
- 只有简单 key: value
- 只有单层列表
- 没有复杂嵌套

不需要完整 YAML 库！

---

## 总结

### **任何优化动作都可以执行吗？**

**回答：目前支持6种操作**

| 操作类型 | 能否处理 |
|----------|---------|
| `description_update` | ✅ |
| `trigger_add` | ✅ |
| `trigger_remove` | ✅ |
| `tag_add` | ✅ |
| `tag_remove` | ✅ |
| `new_skill` | ✅ |

---

### **如何找到对应位置？**

**回答：通过正则表达式 FRONTMATTER_RE**

```
^---\s*\n(.*?)\n---\s*\n
│   │       │
│   │       └─ 匹配中间内容
│   └─ 匹配开始标记
└─ 从字符串开头开始
```

---

### **如何做各种操作？**

**回答：通过「字符串→字典→修改→字符串」四步**

1. **字符串→字典**：`_parse_simple_frontmatter()`
2. **修改字典**：直接 `dict[key] = value` 或 `list.append()`
3. **字典→字符串**：`_generate_frontmatter()`
4. **拼接回去**：`new_frontmatter + "\n" + body`

---

希望这个超详细的解释解决了你的问题！🎯

