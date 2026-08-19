#!/bin/bash
# ============================================================
# 内容风控智能治理系统 — 交付前清理脚本
# ============================================================
# 用途：在打包交付给客户前，清理敏感信息和临时文件
# ============================================================

set -e

echo "============================================="
echo "  内容风控智能治理系统 — 交付前清理"
echo "============================================="

# 项目根目录
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$PROJECT_ROOT"

echo ""
echo "[1/6] 检查并清理 .env 文件..."
if [ -f "src/backend/.env" ]; then
    echo "⚠️  发现 src/backend/.env — 将其重命名为 .env.your-key"
    mv src/backend/.env src/backend/.env.your-key
    echo "✅ 已重命名为 .env.your-key（不要交付给客户）"
else
    echo "✅ .env 不存在，无需清理"
fi

echo ""
echo "[2/6] 清理数据/日志/缓存目录..."
dirs_to_clean=(
    "data"
    "logs"
    "chroma_data"
    "postgres_data"
    "redis_data"
    "funasr_models"
    "src/frontend/node_modules"
    "src/frontend/dist"
    "__pycache__"
    "src/backend/__pycache__"
    ".pytest_cache"
    ".ruff_cache"
    ".coverage"
)

for dir in "${dirs_to_clean[@]}"; do
    if [ -d "$dir" ] || [ -f "$dir" ]; then
        echo "   删除: $dir"
        rm -rf "$dir"
    fi
done

echo ""
echo "[3/6] 检查 Git 状态..."
if [ -d ".git" ]; then
    echo "⚠️  发现 Git 仓库！"
    echo "   建议：删除 .git 目录，或者清理历史中的敏感信息"
    read -p "是否删除 .git 目录？(y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf .git
        echo "✅ .git 目录已删除"
    else
        echo "⚠️  注意：保留 .git 目录，请确保历史中无密钥"
    fi
fi

echo ""
echo "[4/6] 检查是否还有其他敏感文件..."
sensitive_keywords=(
    "DEEPSEEK_API_KEY"
    "QWEN_VL_API_KEY"
    "sk-"
)

found_sensitive=false
for keyword in "${sensitive_keywords[@]}"; do
    if grep -r "$keyword" --include="*.py" --include="*.txt" --include="*.md" --exclude="DEPLOY.md" --exclude="README.md" --exclude-dir=".git" --exclude-dir="node_modules" --exclude="*.log" --exclude="*.jsonl" --exclude-dir="__pycache__" ./ 2>/dev/null | head -5; then
        found_sensitive=true
        echo ""
        echo "⚠️  发现可能的敏感关键字: $keyword"
        echo "   请检查以上文件"
    fi
done

echo ""
echo "[5/6] 确认环境变量模板是否存在..."
if [ -f "src/backend/.env.example" ]; then
    echo "✅ .env.example 存在，模板正常"
else
    echo "❌ .env.example 缺失！请确保模板文件存在"
    exit 1
fi

echo ""
echo "[6/6] 清理完成！"
echo ""
echo "============================================="
echo "  ✅ 清理完成！现在可以打包了"
echo "============================================="
echo ""
echo "📋 建议在交付前检查以下文件是否包含:"
echo "   ✅ DEPLOY.md (本部署文档)"
echo "   ✅ 三个 docx 文档"
echo "   ✅ src/backend/.env.example (模板)"
echo ""
echo "❌ 确保不包含:"
echo "   ❌ src/backend/.env (您的密钥)"
echo "   ❌ .git 目录（如包含历史）"
echo "   ❌ data/、logs/ 等数据目录"
echo ""

read -p "按回车确认完成..."
