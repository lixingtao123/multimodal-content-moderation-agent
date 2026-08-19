# 内容风控智能治理系统 — 上线部署文档

## 📋 目录

- [⚠️ 重要说明：出售前检查](#️-重要说明出售前检查)
- [🔑 API Key 配置指南](#-api-key-配置指南)
- [🚀 两种部署方式](#-两种部署方式)
- [📦 项目文件清单](#-项目文件清单)

---

## ⚠️ 重要说明：出售前检查

### ❌ 绝对不能交付给客户的文件

| 文件名/目录 | 原因 |
|-------------|------|
| `src/backend/.env` | 包含您的真实 API Key |
| `.git` 目录 | Git历史可能残留密钥 |
| `data/` 目录 | 可能含您的测试数据 |
| `logs/` 目录 | 运行日志可能含敏感信息 |
| `chroma_data/` | 向量数据库数据 |
| `postgres_data/` | PostgreSQL 数据 |
| `redis_data/` | Redis 数据 |
| `funasr_models/` | 本地模型缓存 |

### ✅ 需要确保已经处理好的文件

| 文件 | 状态 | 说明 |
|------|------|
| `.gitignore` | ✅ 已配置 | 已包含所有敏感文件 |
| `src/backend/.env.example` | ✅ 已配置 | 模板文件，无真实密钥 |

---

## 🔑 API Key 配置指南

### 1️⃣ 客户需要申请的服务

| 服务 | 用途 | 申请地址 |
|------|------|---------|
| **DeepSeek API** | 文本理解、Agent 推理 | https://platform.deepseek.com |
| **阿里云 MaaS Qwen-VL** | 图像理解、OCR、视频分析 | https://pai.console.aliyun.com/maas |

### 2️⃣ 客户配置步骤

**步骤 1：复制环境变量模板**
```bash
cd /workspace/src/backend
cp .env.example .env
```

**步骤 2：填写真实的 API Key**

编辑 `src/backend/.env` 文件，填写以下内容：

```ini
# ============================================================
# LLM 密钥（必填）
# ============================================================

# DeepSeek API（文本理解 / Agent 推理）
DEEPSEEK_API_KEY=sk-deepseek-your-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com

# Qwen3-VL API（阿里云 MaaS 多模态：图像 / 视频帧 / OCR）
QWEN_VL_API_KEY=sk-qwen-vl-your-key-here
QWEN_VL_BASE_URL=https://your-workspace-id.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
QWEN_VL_MODEL=qwen3.6-plus

# ============================================================
# 连接地址（本地模式）
# ============================================================

DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:15432/moderation
DATABASE_URL_SYNC=postgresql://postgres:postgres@localhost:15432/moderation
REDIS_URL=redis://localhost:16379/0
CHROMA_URL=http://localhost:18001

# ============================================================
# 多模态 Agent 模式控制（false=真实 VL API；仅调试用 true 走 mock）
# ============================================================
IMAGE_AGENT_MOCK=false

# ============================================================
# FunASR（本地进程）
# ============================================================
FUNASR_URL=http://localhost:15001
```

### 3️⃣ 获取 API Key 详细教程

#### DeepSeek API Key 获取

1. 访问 https://platform.deepseek.com
2. 注册/登录账号
3. 进入「API Keys」页面
4. 点击「Create new key」
5. 复制生成的 key（格式：`sk-` 开头）
6. 填入 `.env` 的 `DEEPSEEK_API_KEY`

#### 阿里云 MaaS Qwen-VL API Key 获取

1. 访问 https://pai.console.aliyun.com/maas
2. 开通「PAI-EAS」服务（免费额度可用）
3. 进入「Workspace」→ 「API Keys」
4. 创建新 API Key（`sk-` 开头）
5. 查看您的 workspace ID（在 URL 或控制台）
6. 填入 `.env` 的：
   - `QWEN_VL_API_KEY`（您的 API Key）
   - `QWEN_VL_BASE_URL`（替换 workpace ID）

---

## 🚀 两种部署方式

### 方式一：Docker 一键部署（推荐）

**优点：
- 一键启动所有服务
- 环境隔离，不影响本地环境
- 包含 PostgreSQL、Redis、ChromaDB 等依赖

**步骤：**

```bash
# 1. 进入项目目录
cd /workspace

# 2. 配置 API Key
cp src/backend/.env.example .env
# 编辑 .env，填入真实密钥

# 3. 启动所有服务
docker-compose up -d

# 4. 首次运行：下载快车道模型（可选，约 2-3 GB）
docker-compose exec ollama ollama pull qwen2.5:7b

# 5. 检查服务状态
docker-compose ps

# 访问：浏览器打开 http://localhost:13000
```

**服务端口：**

| 服务 | 端口 | 访问地址 |
|-----|------|--------|
| 前端 | 13000 | http://localhost:13000 |
| 后端 API | 18080 | http://localhost:18080 |
| API 文档（Swagger） | 18080 | http://localhost:18080/docs |

---

### 方式二：本地手动部署（技术）

**前置要求：**
- Python 3.10+
- Node.js 18+
- PostgreSQL 15+
- Redis 7+

**步骤：**

```bash
# 1. 配置 API Key
cd /workspace/src/backend
cp .env.example .env
# 编辑 .env，填入真实密钥

# 2. 一键启动（本地模式）
cd /workspace
bash start.sh
```

---

## 📦 项目文件清单

### 核心功能

| 目录/文件 | 说明 |
|-----------|------|
| `🎓 智能风控引擎零基础入门.docx` | 使用文档 |
| `🧠 智能风控引擎操作指南.docx` | 操作手册 |
| `⚡ 智能风控引擎技术文档.docx` | 技术文档 |
| `DEPLOY.md` | 本部署文档 |
| `README.md` | 项目简介 |
| `src/backend/` | 后端代码（Python） |
| `src/frontend/` | 前端代码（React） |
| `skills/` | 44个 Skills 知识库 |
| `docker-compose.yml` | Docker 配置 |

### 配置模板文件

| 文件 | 说明 |
|------|------|
| `src/backend/.env.example` | ⭐ 环境变量模板（无密钥） |
| **⚠️ `src/backend/.env` | ❌ 不要交付（含真实密钥） |

---

## 📞 技术支持

如有问题，请参考：

1. 阅读 `🎓 智能风控引擎零基础入门.docx`
2. 查看 `🧠 智能风控引擎操作指南.docx`
3. 访问 Swagger API 文档：http://localhost:18080/docs

---

## ⚠️ 安全提醒

1. **切勿** 将 `.env` 文件提交到 Git
2. **务必** 修改 PostgreSQL 生产环境密码
3. **定期** 轮换 API Key
4. **建议** 使用 Docker 模式部署，更安全隔离

---

最后更新：2026-08-10
