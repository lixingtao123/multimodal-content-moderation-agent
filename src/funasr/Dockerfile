# 内容风控智能治理系统 — FunASR 语音转文本服务 (精简版)
# 不在构建时预下载模型，避免镜像过大

FROM python:3.11-slim

WORKDIR /app

# 系统依赖（ffmpeg 用于音频解码）
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Python 依赖
RUN pip install --no-cache-dir funasr modelscope fastapi uvicorn python-multipart

# 设置模型缓存目录（可选外部挂载）
ENV MODELSCOPE_CACHE=/models

COPY server.py .

# 不在构建时预下载模型，首次运行时自动下载
# 如需预下载，请在 docker-compose 中配置 volume 挂载

# 启动（容器内固定用 5001，宿主端口通过映射调整）
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port 5001"]
