# Multimodal Content Moderation Agent

A full-stack content-governance platform built with **LangGraph**, **FastAPI**,
**React**, and multimodal large language models. It coordinates specialised
agents to analyse text, images, audio, and video, then routes each case through
rule-based checks, local models, LLM review, or human escalation according to
risk and complexity.

## Highlights

- Multimodal ingestion with OCR, ASR, visual understanding, and cross-modal
  consistency checks.
- A LangGraph state graph for triage, specialist review, debate, reflection,
  final arbitration, and human-in-the-loop recovery.
- An Aho-Corasick keyword engine plus normalization for homophones, split
  characters, Unicode confusables, and other evasive patterns.
- Long-document chunking and rule-hit context injection to reduce missed
  violations hidden in otherwise benign content.
- Feedback-driven evaluation and optimisation with annotation, error analysis,
  prompt versioning, threshold tuning, and RAG case injection.
- Docker-based local deployment with PostgreSQL, Redis, ChromaDB, FunASR, and
  an optional Ollama fast lane.

> API credentials and runtime data are intentionally excluded from the
> repository. See [Security](SECURITY.md) before running the project.

---

# 内容风控智能治理系统

面向多模态内容（文本 / 图片 / 视频 / 音频）的智能风控治理平台。基于 **LangGraph 多 Agent 编排** 与 **DeepSeek + Qwen3-VL 大模型**，实现三车道路由、Agent 辩论仲裁、人工复核闭环、对抗攻击检测与持续评测优化。

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                       前端 (React + Vite :13000)              │
│  数据看板 │ 内容审核 │ 异步审核 │ 人工审核 │ 评测报告 │ 技术实验室  │
└───────────────┬─────────────────────────────────────────────┘
                │ HTTP / WS (/api/v1)
┌───────────────▼─────────────────────────────────────────────┐
│                      FastAPI 网关 (:18080)                    │
│   moderation │ query │ admin │ logs │ evaluation │ tech      │
└───────────────┬─────────────────────────────────────────────┘
                │ LangGraph StateGraph 审核工作流
┌───────────────▼─────────────────────────────────────────────┐
│  7 大 Agent（text/image/video/audio/planner/react_agent/…）  │
│  三车道路由: fast_lane(qwen2.5:7b) → med → brain 仲裁 + 辩论  │
│  终止双签: 3 个确定性规则                                     │
└───────────────┬─────────────────────────────────────────────┘
    ┌──────────┬┴─────────┬──────────────┬──────────┐
    │ PostgreSQL │ Redis   │ ChromaDB     │ FunASR   │ Ollama
    │ 审核持久化  │ 记忆/缓存 │ 案例向量检索  │ 语音转写  │ 快车道小模型
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI + LangGraph StateGraph + SQLAlchemy 2.0 async ORM |
| LLM | DeepSeek（文本/推理）+ Qwen3-VL（多模态视觉，阿里云 MaaS） |
| 快车道 | Ollama 本地 qwen2.5:7b（低危文本免 API 成本） |
| 数据库 | PostgreSQL（主存储）+ Redis（短期记忆/缓存/任务队列） |
| 向量 | ChromaDB + bge-m3（历史案例检索 + RAG + GraphRAG） |
| 语音 | FunASR SenseVoiceSmall |
| 前端 | React 18 + Vite + TypeScript + recharts |

## 端口一览

| 服务 | 端口 | 说明 |
|---|---|---|
| 后端 API | **18080** | FastAPI，`/docs` Swagger |
| 前端 | **13000** | Vite 构建产物（dev 亦用 13000） |
| PostgreSQL | **15432** | 数据卷持久化 |
| Redis | **16379** | |
| FunASR | **15001** | 语音转写 |
| Ollama | **11434** | 快车道小模型 |
| ChromaDB | 本地嵌入式 | 无独立端口，见 `data/chroma` |

## 快速启动

### 本地模式（推荐）

前置依赖：Python 3.10+、Node.js、PostgreSQL 16、Redis、Ollama（快车道可选）。

```bash
# 1. 配置密钥（真实 key 仅放 .env，不进入代码/commit）
cp src/backend/.env.example src/backend/.env   # 若存在示例文件
# 编辑 src/backend/.env 填入 DEEPSEEK_API_KEY、QWEN_VL_API_KEY

# 2. 一键启动（PG/Redis/FunASR/前端构建/后端）
bash start.sh

# 3. 访问
#   前端   http://localhost:13000
#   API    http://localhost:18080/docs
```

### Docker 模式

```bash
# 先在根目录 .env 填 DEEPSEEK_API_KEY / QWEN_VL_API_KEY
docker compose up -d --build
# 首次拉取快车道模型
docker compose exec ollama ollama pull qwen2.5:7b
```

## 核心功能

- **多模态审核**：文本/图片/视频/音频 单模态 + 图文矛盾对（安全文本 + 有害图片）。
- **三车道路由**：triage 分流 → 低危 fast_lane（本地小模型）→ 中危全 Agent → 高危 brain 仲裁。
- **Agent 辩论仲裁**：Agent 严重分歧时触发辩论，多意见收敛后终审双签。
- **人工复核闭环**：低置信度内容进入待审核队列，人工标注后恢复工作流。
- **对抗检测**：同音字/字符噪声/关键词变体/图像对抗，AdversarialDetector 全链路拦截。
- **持续评测**：7 个 Benchmark Track（意图/对抗/RAG/技能路由/多模态/Agent链路/成本）跑真实指标。
- **优化闭环**：标注缓冲 → 自动错误分析 → 提示词版本迭代 → 策略生效。

## 目录结构

```
├── src/backend/           # FastAPI 后端
│   ├── agent_moderation/  # 7 个 Agent + LangGraph 工作流
│   ├── api/routes/        # REST API（moderation/admin/eval/tech/logs）
│   ├── db/                # SQLAlchemy ORM + schema.sql
│   ├── memory/            # ChromaDB 案例库 + Redis 记忆 + GraphRAG
│   ├── optimization/      # 标注队列 + 提示词优化
│   └── mcp_gateway/       # MCP 工具网关（44+ 技能注册）
├── src/frontend/          # React 前端
├── src/funasr/            # 语音识别服务
├── eval/                  # Benchmark（T1-T7）+ OutSafe 数据集加载
├── tests/                 # 单元 + 集成测试
├── docs/                  # 文档
├── scripts/               # 运维/数据脚本
├── start.sh               # 本地一键启动
└── docker-compose.yml     # Docker 部署
```

## 测试与评测

```bash
# 单元测试
make test                      # 或: cd src/backend && python -m pytest /workspace/tests/

# 前端类型检查
cd src/frontend && npx tsc --noEmit

# 全量 Benchmark（真实模型调用，约 15-30 分钟）
python eval/run_benchmark.py --all

# 单 Track
python eval/run_benchmark.py --tracks T2_adversarial
```

## 文档

- [零基础入门指南](docs/零基础入门指南.md)
- [用户操作指南与测试要点](docs/用户操作指南与测试要点.md)

## 安全说明

- API 密钥仅存放于 `src/backend/.env`（已 gitignore），**绝不进入代码、文档或 commit**。
- 冒用/滥用、色情、政治敏感等内容拦截由审核链路保证；本项目用于内容风控治理。
