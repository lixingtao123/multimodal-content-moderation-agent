# 内容风控智能治理系统 — Backend Dockerfile (生产优化版)
# 多阶段构建，精简体积

# ------------------- 阶段 1: 构建 -------------------
FROM python:3.11-slim AS builder

WORKDIR /app

# 系统依赖（ffmpeg 用于视频抽帧/音频提取）
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg gcc && \
    rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements-prod.txt .
RUN pip install --user --no-cache-dir -r requirements-prod.txt

# ------------------- 阶段 2: 生产镜像 -------------------
FROM python:3.11-slim AS production

WORKDIR /app

# 系统依赖（只保留运行时必需的）
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 从 builder 复制已安装的依赖
COPY --from=builder /root/.local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /root/.local/bin /usr/local/bin

# 应用代码（.dockerignore 过滤不需要的文件）
COPY . .

# 默认禁用 Reranker，避免 GPU OOM
ENV ENABLE_RERANKER=false

# 启动（容器内固定用 8000，宿主端口通过映射调整）
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000"]
