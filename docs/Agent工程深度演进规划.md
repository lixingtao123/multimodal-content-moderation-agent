# 多 Agent 动态编排 + MCP/Skill 动态调用 + 大小模型协同 — 工程深度演进规划

> 版本：v1.0 ｜ 日期：2026-08-05
> 定位：面向 **字节跳动 Agent 开发 + 大模型应用** 岗位的项目深度规划。
> 关联文档：[真实数据化与工程深化详细设计.md](真实数据化与工程深化详细设计.md)（评测体系 7 Track 复用为本规划验收基线）。
> 既定约束：**不做模型训练/RL**（12GB 显存限制）；小模型只用现成开源模型量化部署，作为可替换组件设计。
> 指标标注：✅ = 有代码支撑的事实；⚠️ = 预估待实测。

---

## 0. 规划定位

**目标**：把项目从"规则驱动的静态编排"演进为"**认知架构驱动的自适应 Agent 系统**"，在三个方向做出可面试、可落地、有量化指标的技术深度：

1. **多 Agent 动态编排** —— 从静态 DAG 到复杂度自适应的编排 + Orchestrator-Worker 动态任务分配。
2. **MCP / Skill 动态调用** —— 从注册表匹配到语义路由 + 工具可靠性工程 + 安全加固。
3. **大小模型 Agent 协同** —— 从单一 DeepSeek 到「小模型快路径 + 大模型慢路径」的级联与路由（无训练）。

**为什么这三点是字节 Agent 岗的考察核心**：字节（豆包/Coze/火山方舟/飞书）Agent 岗面试高频考察——Agent 认知架构（记忆/工具/规划）、工具调用鲁棒性、多模型策略、上下文工程、评测驱动开发。这三点正好覆盖。评测体系（详设文档 7 Track）作为所有改动的验收基线，体现 **Eval-Driven Development**。

---

## 1. 现状能力盘点

| 能力域 | 已有代码 | 成熟度 | 主要短板 |
|---|---|---|---|
| 静态编排 | `workflows/moderation.py`：11 节点 + 条件路由 | 中 | 链路固定、阈值写死，不随复杂度/风险自适应 |
| 复杂度分级 | `workers/model_router.py` `ModelRouter`(RouteTier) | 低 | 只做规则分级，**未接入编排图**，结果未被消费 |
| ReAct | `agents/react_agent.py` v2.0（MAX_STEPS=5 + 自校准） | 中 | 单 agent 循环，缺任务级工具链编排、失败恢复 |
| Plan-and-Execute | `agents/planner.py` TaskPlanner（REPLAN/DEEP_DIVE） | 中 | 只服务 react，未接入多模态编排 |
| 辩论 | `agents/debate_panel.py` 4 模式 + 专业度加权 | 中 | opinion 无证据链、单轮、权重固定 |
| Reflexion | `workflows` reflexion_node | 中 | 只有"修正置信度"，无跨 agent 元认知 |
| 记忆 | `memory/manager.py` 三层（PG/Redis/Chroma） | 中 | 缓存是精确哈希、写入策略简单、无冲突消解 |
| Agentic RAG | `memory/agentic_rag.py` QueryRewrite + SelfRAG | 中 | 无 CRAG 纠错、无 5 种 RAG 的路由选择 |
| Hybrid RAG | `memory/hybrid_retriever.py` BM25+Dense+RRF+CrossEncoder | 高 | — |
| MCP | `mcp_servers/registry.py` 8 工具 + RBAC | 中 | 无参数 schema 校验、无输出防污染、无工具效果度量 |
| Skill | `skill_registry.py` 3 个 + 三层加载 | 低 | tag 匹配、无语义路由、无注入有效性验证 |
| 输入安全 | `security/input_guard.py` 双层 | 中 | 只护 LLM 输入，未覆盖工具参数/工具输出 |
| 自进化 | FeedbackLoop（阈值 100 → 4 种优化动作） | 中 | 策略层优化，未度量工具质量/路由质量 |
| 评测 | `eval/runners/eval_harness.py` 单流程 | 低 | 未 track 化（详设已规划 harness_v2） |

**结论**：骨架全、深度参差。本规划把"低成熟度、未消费"的能力（ModelRouter 接入编排、Skill 语义路由、工具工程、级联）补成闭环，并强化已有中成熟度能力（辩论证据化、Agentic RAG 纠错、记忆策略）。

---

## 2. 主线 A：多 Agent 动态编排

### A1 风险感知的分层编排（Tiered Orchestration + 编排 Agent）

**现状**：`supervisor_node` 按内容类型分类后走固定链，所有文本都进 TextAgent 全流程（敏感词→RAG→DeepSeek→评分）。`ModelRouter` 规则复杂度分级存在但**未被编排消费**。

**问题（两个设计判断）**：
1. **复杂度分级不值得单独用小模型**——复杂度是低语义价值信号，规则特征足够；且分级目标不是"准"而是"别把高危放快路径"，误判方向不对称（低估是严重错误、高估只是浪费成本）。
2. **编排不该全规则、也不该全 LLM**——需要"编排 Agent"做语义决策层，但不能全权接管（不可控、延迟、token）。

**方案：三层编排架构**：
```
L1 确定性分类（内容类型）        — 现状保留，零 LLM
L2 编排 Agent（Router Agent）    — 新增：理解任务意图 → 输出结构化 plan（JSON schema 约束）
L3 确定性调度器（DAG/worker）    — 现状增强：执行 plan，可并行/重试/降级
```
- **L2 编排 Agent**：复用现有 `agents/planner.py` TaskPlanner（LLM 驱动 Plan-and-Execute）作为内核；输出 `plan`（子任务 + worker + 顺序 + 依赖），**结构化可校验**；失败 → 降级确定性路径（现状）。
- **分档决策**（入口处 `tier`）：`risk×complexity` 联合估计决定走哪条链：
```
tier=low  → 快路径: 敏感词 + 规则 + 小模型粗判（见 C4），PASS 直接出
tier=med  → 标准路径: TextAgent 全流程（现状）
tier=high → 深度路径: TextAgent + AgenticRAG + Debate/Reflexion（现状增强）
```
- **联合估计实现**：规则特征（长度/关键词密度/模态数）粗筛兜底 + **小模型联合输出 `{risk, complexity}`**（一次调用，非单独复杂度分类）+ **单边保守校准**（risk 高估优先，宁多走深度不放过高危）。
- 状态机：`state["_tier"] = low/med/high`，路由按 `_tier` + `risk_hint` 分叉。

**为什么有深度**：三层编排 = 确定性兜底 + Agent 语义决策 + 确定性执行的组合，正是 Anthropic multi-agent / LangGraph supervisor / Coze workflow 的架构形态；可讲"为什么编排 Agent 输出结构化 plan 而非自由文本"（可校验、可回退、可测）。

**验收**：T7 成本——tier=low 延迟 < 500ms、token < 大模型单次调用；T1 精确率不回退；构造"高危但简单"样本断言必走深度路径（风险感知）。

### A2 Orchestrator-Worker 动态任务编排

**现状**：编排是**编译期固定图**（LangGraph StateGraph 静态节点）。`agents/planner.py` TaskPlanner（LLM 驱动的 Plan-and-Execute）已存在但只在 react 场景用。

**问题**：静态图对"运行时才知道的分解"（如一个文档拆成 N 个子任务）不灵活；agent 实例是单例复用，无法按任务规模并行扩容。

**方案**：引入 **Orchestrator-Worker 模式**作为深度任务的执行内核：
- Orchestrator = `TaskPlanner`（已有）：把多模态/复杂任务分解为子任务 DAG（PlanStep 已有 `depends_on/can_parallelize`）。
- Worker = 按子任务类型动态实例化的 agent 池：`WorkerPool(agent_factory, max_concurrency=Semaphore(5))`（Semaphore 复用现有 `planner_node` 并行控制）。
- Orchestrator 观察 Worker 结果 → 决定继续/REPLAN/DEEP_DIVE/DONE（`PlanStatus` 已有）。
- 保留静态图作快速入口，深度任务**下钻到 Orchestrator-Worker**（A1 的 tier=high 路径）。

**为什么有深度**：这是 Agent 系统从"预编排"到"运行时编排"的关键演进；对齐 LangGraph `Send` API 的动态 fan-out、MetaGPT 的协作式编排等思想，且能讲"为什么固定图 + 动态 worker 结合"。

**验收**：多图文档任务并行 Worker 数、REPLAN 触发次数（pipeline 日志可统计）；T6 多轮完成率。

### A3 动态重规划（Plan-and-Execute 增强）

**现状**：TaskPlanner 有 REPLAN 枚举但触发简单；`react_agent` 是单 agent 循环。

**方案**：
- Orchestrator 每轮执行后**评估进度信号**（Worker 结果置信度、是否出现新风险维度），满足条件触发 REPLAN（新增子任务、调整优先级）。
- ReAct 循环加**最大重试 + 降级**：工具失败 N 次后跳过该步继续（而不是整体失败）。
- Reflexion 从"改置信度"升级为"跨 agent 反馈"：把高置信错误样本的教训写成 agent 级记忆，供下个任务的 Orchestrator 参考（`state["_plan_context"]` 已有雏形）。

**为什么有深度**：可讲 ReAct 的局限（无法规划多步、无全局视角）与 Plan-and-Execute 的取舍（多一步 LLM 开销换全局一致性），以及"何时重规划"的触发设计。

**验收**：构造一个"初始计划错误、观察后需重规划"的用例，断言触发 REPLAN 且最终结果正确；完成率提升（⚠️）。

### A4 证据驱动的多轮辩论

**现状**：`debate_panel.py` 有 4 模式 + `expertise_weight`（固定），但 opinion 只有 `{agent, violation_type, confidence}`，单轮投票。

**方案**：
- **opinion 加证据链**：每个 agent 的判定附带 `evidence`（命中的关键词、检索案例 id、RAG 置信度），投票按"证据强度"加权而非仅专业度。
- **多轮辩论**：首轮不一致 → 第二轮互相引用对方论点反驳（round 上限 2）；仍不一致且置信度 < 阈值 → `needs_human_review`（已有）。
- **专业度权重动态估计**：不再固定 `expertise_weight`，按该 agent 历史准确率（自进化反馈）动态调整。

**为什么有深度**：多 agent 协作的两种范式对比（多数投票 vs 协商共识）及其适用条件；对齐 Chain-of-Verification / Debate (ICLR 2023) 思路。

**验收**：T1 争议子集（类型不一致样本）最终准确率；辩论轮次分布；升级 human 率。

### A5 A2A 结构化消息协议

**现状**：`_send_a2a_message` + a2a_protocol 传字符串内容。

**方案**：Agent 间消息结构化：`{sender, receiver, payload_type, confidence, evidence_refs, timestamp}`；消息进入 Working Memory（Redis）可被后续 agent 查询，形成**可审计的 agent 协作轨迹**（trace 可回溯）。

**为什么有深度**：Agent 通信协议设计（对齐 Google A2A / Anthropic Agent SDK 思路）；面试可讲"为什么结构化消息比裸字符串更利于审计与记忆"。

---

## 3. 主线 B：MCP / Skill 动态调用与工具工程

### B1 三级检索式技能路由（Filter → Rank → Select）

**现状**：`skill_registry` 按 tag/content_type 匹配，8 工具——两级"标签→内容"匹配无法支撑上百技能。

**为什么三级**：OpenAI function calling 官方建议工具 ≤20 个（多了精度崩），而目标"成百上千精准调用"必须先把候选集缩小、再排序、再裁决，同时避免一次性把上百 schema 塞进 context（溢出）。

**方案：Filter → Rank → Select 三级路由**（对标数据库查询优化器：分桶 / 索引扫描 / 查询优化）：
```
Skill/Tool Registry（上百个）
  → ① 分桶粗筛 (Filter)   : 任务描述 → 元数据过滤（domain_tags/modality/cost/rbac）
                           元数据即"标签分类"，命中候选集 100 → 20
  → ② 语义精排 (Rank)     : bge 嵌入相似度 + 规则权重(0.6/0.4) → 20 → 5
                           覆盖"标签没覆盖的说法"
  → ③ 裁决选择 (Select)   : 编排 Agent（A1 的 L2）从 top-5 选最终工具集 + 参数
                           处理多工具能力重叠（RBAC∩成本∩准确率加权）
  → 动态注入               : 只注入被选中的 2-3 个 skill 内容（防溢出）
```
- **元数据驱动**：每个 skill/tool 登记 `{name, description, domain_tags, modality, cost, rbac_level, version}`——新增技能**只加元数据不改代码**，registry 自动注册，支撑"成百上千可扩展"。
- 向量索引：`skill_index`（ChromaDB 新 collection，复用 bge-small-zh-v1.5）。
- **标签分桶是关键的第①步**：解决候选集缩小；但必须配②③处理标签覆盖不全与多工具重叠（回答"仅标签判断不够"的边界）。

**为什么有深度**：检索式工具路由是 Gorilla / ToolLLM / MCP 生态 / Coze 插件市场的通用解法，且"元数据自动注册 + 三级检索"直接解决上下文溢出与工具数量上限两个真问题；可类比数据库查询优化器讲设计。

**验收**：T4——Skill Hit@3 ≥ 0.85（⚠️）；分桶命中率（候选集覆盖 gold 工具的比例 ≥ 0.98，⚠️）；动态注入 token 节省量化；新增 1 个工具只加元数据不改代码可被路由命中。

### B2 工具调用可靠性工程

**现状**：工具调用路径无统一容错（registry call_tool 直接执行）。

**问题**：真实运行中 LLM 生成的工具参数非法/缺失 → 调用失败，ReAct 步就断了。

**方案**：
- **参数 schema 校验**：call_tool 入口 jsonschema 校验 `inputSchema`，失败返回结构化错误而非异常。
- **自动重试 + 修复**：校验失败时让 LLM 修复参数（1 次重试），仍失败则跳过该工具（不中断 agent）。
- **降级链**：工具不可用（如外部服务挂）→ 记录 + 走 fallback（如 history_search 挂 → 用 rule-based 检索替代），保证 agent 存活。

**为什么有深度**：工具调用是 Agent 落地最大的可靠性坑；可讲"校验→修复→降级"三级容错的工程取舍与错误注入测试。

**验收**：T4 工具调用成功率（目标 ≥ 95%，⚠️）；构造 30 个非法参数用例全部被拦截不崩溃。

### B3 多工具编排（工具链）

**现状**：ReAct 每步选一个工具，无工具间依赖关系。

**方案**：引入**工具依赖 DAG**（如 `adversarial_detect` 命中 → 才需 `input_sanitize` → 再 `keyword_check`）：Orchestrator 或 ReAct 的 action 支持"工具链"声明，worker 按依赖并行/串行执行。

**为什么有深度**：从"单工具调用"到"工具编排"是 Agent 能力上限的质变；可讲工具链与 RAG 多跳检索的类比。

### B4 MCP 安全加固

**现状**：RBAC（`access_control.py`）有，审计靠日志。

**方案**：
- **工具输出防污染**：工具返回内容在进入 system prompt 前过 `InputGuard.detect_injection`（防工具返回的恶意文本注入 agent）。
- **工具参数防护**：参数中检测注入（复用 `input_guard`）。
- **调用审计结构化**：`{agent, tool, args_hash, result_summary, cost, timestamp}` 进审计表。

**为什么有深度**：Agent 系统的"工具攻击面"——工具既是能力也是注入入口；可讲 LLM 供应链安全 / OWASP LLM Top 10。

### B5 工具效果度量与自进化

**现状**：无工具级质量度量。

**方案**：每次工具调用记录"对最终判定是否有贡献"（判定正确且用了该工具 = 正贡献），聚合出**工具质量分**，反馈给 `SkillRouter`（低质量工具降权）+ 自进化闭环（低质量工具触发优化/下线）。

**为什么有深度**：把工具变成可进化的资产（Gorilla/ToolLLM 的"工具评估"思想的产品化）。

---

## 4. 主线 C：大小模型 Agent 协同（无训练版）

### C1 级联推理（Cascade）

**现状**：所有语义判断都走 DeepSeek。

**方案**：**小模型初判 → 低置信度升级大模型**：
```
小模型（本地 Qwen2.5-3B 量化, vLLM）: 意图分类/粗判
  |_ 置信度 ≥ 0.9 且非高危 → 直接采用（快路径）
  |_ 置信度 < 0.9 或 risk_hint=high → 升级 DeepSeek 复审
```
- 挂点：L2 意图预筛（详设子任务 3）已设计为"小模型为主、API fallback"，此即 C1 落地。
- 置信度阈值用 ECE 校准后确定（详设 T1 的 ECE 指标驱动阈值选择）。

**为什么有深度**：级联是"用成本换质量"的经典模型策略（对应 Cascade RAG / 预算感知推理思路）；可讲阈值选择如何由校准曲线决定而非拍脑袋。

**验收**：T1——升级率（去大模型的样本占比）、成本下降（token）、F1 差距（⚠️ 目标差距 <2pp）。

### C2 模型路由接入编排

**现状**：`ModelRouter` 规则分级未接编排（A1 会消费其 tier）。

**方案**：两级路由——`tier`（复杂度）→ `model_path`（local_small / deepseek_brain）：tier=low 全走小模型，tier=high 全走大模型，tier=med 走级联（C1）。
- 实现：`common/api_clients.py` 增加 `get_local_model_client()`，`workers/model_router.py` 扩展 `route(task, tier) -> model_path`。

**为什么有深度**：模型路由是 MOE/混合模型的工程版；可讲"为什么复杂度分级先于语义分级"（确定性优先）。

### C3 语义缓存

**现状**：`MemoryManager.cache_llm_result` 是**精确哈希**（`hash_prompt`），改写过的同义查询缓存不命中。

**方案**：升级为**语义缓存**——查询嵌入（bge）与缓存键相似度 ≥ 阈值（如 0.95）即命中；缓存带风险结果（违规样本结果不缓存或短 TTL）。

**为什么有深度**：语义缓存是 Agent 系统降本的核心工程；可讲缓存粒度（决策级 vs 检索级）与安全约束（不缓存可逆敏感结果）。

**验收**：缓存命中率、API 调用下降比例（⚠️）。

### C4 小模型快路径职责（无训练，可替换设计）

**现状**：无本地模型。

**方案**：用**现成开源模型量化部署**（Qwen2.5-1.5B/3B-Instruct，AWQ/GGUF）承担三个快路径任务：意图预筛（C1）、工具路由（B1 的 router 可用小模型）、粗判（A1 tier=low）。接口抽象成 `get_intent_model()/get_router_model()`，**未来微调/蒸馏可无缝替换**（详设子任务 5 的接口设计保留，仅去掉训练步骤）。

**诚实边界**：不微调的通用模型在意图分类精度上会低于 DeepSeek，**必须靠级联（C1）兜底**；这正是"快路径降本 + 慢路径保质量"的工程权衡本身。

### C5 自洽性增强（Self-Consistency）

**方案**：小模型快路径对低置信样本做 3-5 次采样投票（小模型便宜，代价可控），提升粗判稳定性；与级联联合——采样仍不一致则升级大模型。

**为什么有深度**：可讲大模型推理中 self-consistency 的适用边界（分类任务比生成任务更适合投票）。

---

## 5. 配套工程

### 5.1 可观测性（Trace + 成本归因）

- 现状：`pipeline.jsonl` 步骤日志（211 条真实请求可统计）。
- 增强：**span 树**（supervisor→agent→tool→RAG 层级）、每步 token/成本归因、失败归因（哪一步导致 REJECT 误判）。
- 价值：面试可展示"用 trace 定位自进化闭环误判来源"的案例。

### 5.2 评测驱动验收（复用详设 7 Track）

| 主线改动 | 验收 Track |
|---|---|
| A1-A5 编排 | T1（准确率）、T6（多轮完成率）、T7（成本延迟） |
| B1-B5 工具 | T4（工具选择/Hit@k/注入 Δ）、T3（RAG） |
| C1-C5 模型协同 | T1（级联 F1 差距）、T7（成本）、新 Track：模型路由统计（升级率/命中率） |

### 5.3 Prompt 版本管理

- 自进化闭环已有版本 + A/B + 回滚；补 prompt 差异 diff 与效果归因表。

---

## 6. 里程碑

| 阶段 | 内容 | 依赖 | 验证 |
|---|---|---|---|
| P1 | harness_v2 + T1/T3/T4/T7 基线 | 详设 M1/M2 | 基线报告（改动前） |
| P2 | A1 分层链路 + C2 模型路由接入 | P1 | tier 分布 + 成本下降 |
| P3 | B2 工具容错 + B4 安全加固 | P1 | 工具成功率/注入拦截 |
| P4 | B1 SkillRouter + C3 语义缓存 | P1 | Hit@3 + 缓存命中率 |
| P5 | A2/A3 Orchestrator-Worker + 重规划 | P2 | 多轮完成率 + REPLAN 统计 |
| P6 | A4 证据辩论 + B5 工具质量闭环 | P2/P3 | 争议子集准确率 |
| P7 | C1/C4 小模型级联接入 + C5 自洽 | P2 | 升级率 + F1 差距 |
| P8 | 全量回归 + 报告归档 + 简历数字固化 | 全部 | 7 Track 全绿 |

---

## 7. 面试故事线 & 简历亮点（提炼）

**故事主线**：从"规则驱动的固定编排"演进为"**认知架构驱动的自适应 Agent 系统**"——复杂度分层编排 + 证据驱动协作 + 语义路由工具层 + 大小模型级联。

**可提炼的简历点（每点都挂真实/待实测指标）**：
1. **分层路由架构**：构建三层编排——确定性分类 + 编排 Agent 动态规划（结构化 plan）+ 确定性调度器；复杂任务多 Agent 协作、简单任务直通，延迟/成本分层可控（对标 Anthropic multi-agent / LangGraph supervisor / Coze workflow）。
2. **检索式技能路由**：设计 Filter→Rank→Select 三级路由（元数据分桶 + 语义精排 + Agent 裁决），支撑**上百** skill/MCP 精准调用，上下文按需注入避免溢出；新增技能只加元数据不改代码（对标 Gorilla / ToolLLM / MCP 生态，**最有区分度**）。
3. **风险感知编排**：构建风险×复杂度联合估计驱动自适应编排，规则粗筛 + 小模型联合估计 + 单边保守校准，高危不放快路径。
4. **工具可靠性工程**：35+ MCP 工具，调用"schema 校验→LLM 修复→降级链"三级容错 + 工具输出防注入 + 工具质量分反馈自进化。
5. **大小模型协同**：Qwen 小模型快路径（路由/意图/粗判）+ DeepSeek 大模型级联，升级阈值由 ECE 校准曲线决定，成本下降 X%（⚠️）。
6. **评测驱动**：7 Track benchmark（识别/对抗/检索/工具/多模态/自进化/成本），ECE 校准驱动阈值，Eval-Driven 开发。

### 7.1 大厂做法对标表（面试可用）

| 本项目设计 | 大厂/业界对标 |
|---|---|
| 三层编排（分类/编排 Agent/调度器） | Anthropic multi-agent（LLM router→worker）、LangGraph supervisor、Coze 工作流 |
| 编排 Agent 输出结构化 plan | HuggingGPT 任务规划、LangGraph Plan-and-Execute |
| Filter→Rank→Select 技能路由 | Gorilla / ToolLLM 检索式工具、MCP 工具发现、Coze 插件市场 |
| 规则粗筛→小模型联合估计→LLM 兜底 | 大厂风控分层（规则→GBDT→深度模型）、预算感知推理 |
| 级联（小模型初判→大模型复审） | Cascade RAG / Cascade Rerank 思路 |
| 元数据自动注册工具 | MCP 注册中心、Coze 插件 manifest |

---

## 8. 风险与诚实边界

| 项 | 说明 |
|---|---|
| 小模型未微调精度有限 | 靠级联兜底；对外只报"级联后"指标，不虚报小模型单独能力 |
| 动态编排复杂度 | A2 Orchestrator 引入后需 T6 完成率回归，回退线 = 静态图（保留） |
| 全量 LLM 评测成本 | 复用详设抽样/缓存策略 |
| 指标真实性 | 全部 ⚠️ 在对应 P 阶段实测后转 ✅，禁止虚构 |
