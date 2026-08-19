#!/bin/bash
# ================================================================
# 精简清理脚本：只删 Ollama 模型和 OutSafe-Bench 数据集
# ================================================================

set -e

echo "=============================================="
echo "  开始精简清理..."
echo "=============================================="

# ========== 1. 删除 Ollama qwen2.5 模型 ==========
echo "[1/2] 删除 Ollama 模型..."
if [ -d "/root/.ollama/models" ]; then
    OLLAMA_SIZE=$(du -sh /root/.ollama/models 2>/dev/null | cut -f1)
    rm -rf /root/.ollama/models
    echo "  ✓ 已删除 Ollama 模型 (${OLLAMA_SIZE})"
else
    echo "  - Ollama 模型目录不存在"
fi

# ========== 2. 删除 OutSafe-Bench 数据集 ==========
echo "[2/2] 删除 OutSafe-Bench 数据集..."
if [ -d "/app/data/OutSafe-Bench" ]; then
    DATA_SIZE=$(du -sh /app/data/OutSafe-Bench 2>/dev/null | cut -f1)
    rm -rf /app/data/OutSafe-Bench
    echo "  ✓ 已删除 OutSafe-Bench 数据集 (${DATA_SIZE})"
else
    echo "  - OutSafe-Bench 目录不存在"
fi

# ========== 检查结果 ==========
echo ""
echo "=============================================="
echo "  清理完成！"
echo "=============================================="
echo ""
echo "当前空间使用："
if [ -d "/app/data" ]; then
    echo "- /app/data: $(du -sh /app/data 2>/dev/null | cut -f1)"
fi
if [ -d "/root/.ollama" ]; then
    echo "- /root/.ollama: $(du -sh /root/.ollama 2>/dev/null | cut -f1)"
fi
echo ""
echo "=============================================="
echo "  现在可以执行：docker commit <container_id> <image_name>"
echo "=============================================="
