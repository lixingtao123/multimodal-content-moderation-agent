#!/bin/bash

# 内容风控智能治理系统 — 一键构建并推送镜像
# 用法: ./build-and-push.sh [version]
# 默认版本: v1.0

set -e  # 遇到错误立即退出

REGISTRY="registry.cn-hangzhou.aliyuncs.com/moderation-system"
VERSION="${1:-v1.0}"

echo "=========================================="
echo "  内容风控智能治理系统 — 镜像构建与推送"
echo "  仓库: $REGISTRY"
echo "  版本: $VERSION"
echo "=========================================="
echo ""

# 确保在项目根目录
cd "$(dirname "$0")"

# ------------------------------
# 步骤 1: 构建 Backend
# ------------------------------
echo "[1/3] 构建 backend 镜像..."
docker build --no-cache -t ${REGISTRY}/moderation-backend:${VERSION} -f src/backend/Dockerfile src/backend/
echo "✅ backend 镜像构建完成: ${REGISTRY}/moderation-backend:${VERSION}"
echo ""

# ------------------------------
# 步骤 2: 构建 Frontend
# ------------------------------
echo "[2/3] 构建 frontend 镜像..."
docker build --no-cache -t ${REGISTRY}/moderation-frontend:${VERSION} -f src/frontend/Dockerfile src/frontend/
echo "✅ frontend 镜像构建完成: ${REGISTRY}/moderation-frontend:${VERSION}"
echo ""

# ------------------------------
# 步骤 3: 构建 FunASR
# ------------------------------
echo "[3/3] 构建 funasr 镜像..."
docker build --no-cache -t ${REGISTRY}/moderation-funasr:${VERSION} -f src/funasr/Dockerfile src/funasr/
echo "✅ funasr 镜像构建完成: ${REGISTRY}/moderation-funasr:${VERSION}"
echo ""

# ------------------------------
# 步骤 4: 推送镜像
# ------------------------------
read -p "是否现在推送镜像到阿里云容器镜像服务? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "开始推送镜像..."

    docker push ${REGISTRY}/moderation-backend:${VERSION}
    echo "✅ backend 镜像推送完成"

    docker push ${REGISTRY}/moderation-frontend:${VERSION}
    echo "✅ frontend 镜像推送完成"

    docker push ${REGISTRY}/moderation-funasr:${VERSION}
    echo "✅ funasr 镜像推送完成"

    echo ""
    echo "🎉 所有镜像推送完成！"
    echo ""
    echo "用户可以通过以下命令启动:"
    echo "  docker-compose -f docker-compose.delivery.yml up -d"
else
    echo "跳过推送，镜像已保存在本地。"
    echo "手动推送命令:"
    echo "  docker push ${REGISTRY}/moderation-backend:${VERSION}"
    echo "  docker push ${REGISTRY}/moderation-frontend:${VERSION}"
    echo "  docker push ${REGISTRY}/moderation-funasr:${VERSION}"
fi
