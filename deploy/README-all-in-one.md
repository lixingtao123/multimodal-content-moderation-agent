# 内容风控智能治理系统 — 单容器全栈部署

一键部署，开箱即用！

## 快速开始

### 1. 构建镜像

```bash
docker build -t moderation-system:v1.0 -f Dockerfile.all-in-one .
```

### 2. 运行容器

```bash
docker run -d \
  --name moderation-system \
  -p 13000:13000 \
  -p 18080:18080 \
  -p 15432:15432 \
  -p 16379:16379 \
  -p 18001:18001 \
  -p 15001:15001 \
  -e DEEPSEEK_API_KEY=your_deepseek_key \
  -e QWEN_VL_API_KEY=your_qwen_key \
  -v moderation-data:/data \
  moderation-system:v1.0
```

### 3. 访问

- **前端**: http://localhost:13000
- **后端 API**: http://localhost:18080
- **健康检查**: http://localhost:18080/health

## 环境变量

| 变量 | 说明 | 必填 |
|------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 是 |
| `QWEN_VL_API_KEY` | Qwen VL API Key | 是 |
| `DEEPSEEK_BASE_URL` | DeepSeek 基础 URL | 否 |
| `QWEN_VL_BASE_URL` | Qwen VL 基础 URL | 否 |

## 包含组件

| 组件 | 端口 | 说明 |
|------|------|------|
| PostgreSQL | 15432 | 数据库 |
| Redis | 16379 | 缓存/队列 |
| ChromaDB | 18001 | 向量数据库 |
| FunASR | 15001 | 语音转文本 |
| Backend | 18080 | FastAPI 后端 |
| Frontend (Nginx) | 13000 | React 前端 |

## 数据持久化

数据存储在 `/data` 目录，挂载 volume 可以持久化：

```bash
docker volume create moderation-data
```

## 查看日志

```bash
# 容器日志
docker logs moderation-system

# 各服务日志
docker exec moderation-system tail -f /app/logs/backend.log
docker exec moderation-system tail -f /app/logs/postgres.log
docker exec moderation-system tail -f /app/logs/redis.log
```

## 停止/删除

```bash
docker stop moderation-system
docker rm moderation-system
```

## 导出/导入镜像

```bash
# 导出
docker save moderation-system:v1.0 | gzip > moderation-system-v1.0.tar.gz

# 导入
docker load < moderation-system-v1.0.tar.gz
```
