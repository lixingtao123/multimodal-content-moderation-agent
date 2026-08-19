#!/bin/bash
# ================================================================
# Docker 容器一键清理脚本（用于 docker commit 前精简体积）
# 执行方式: docker exec -i <container_id> bash < clean_container.sh
# ================================================================

set -e

echo "=============================================="
echo "  开始清理容器..."
echo "=============================================="

# ------------------- 1. 删除大体积测试数据 -------------------
echo "[1/10] 删除 OutSafe-Bench 数据集..."
if [ -d "/app/data/OutSafe-Bench" ]; then
    rm -rf /app/data/OutSafe-Bench
    echo "  ✓ 已删除 OutSafe-Bench (1.8GB)"
else
    echo "  - 不存在，跳过"
fi

# 清理 chroma 数据（可选，保留的话注释掉）
# echo "[1/10] 删除 Chroma 数据..."
# rm -rf /app/data/chroma

# ------------------- 2. 清理 Python 缓存 -------------------
echo "[2/10] 清理 Python 缓存..."
find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find /app -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
find /app -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
find /app -type f -name "*.pyc" -delete 2>/dev/null || true
find /app -type f -name "*.pyo" -delete 2>/dev/null || true
echo "  ✓ 已清理 Python 缓存"

# ------------------- 3. 删除临时调试脚本 -------------------
echo "[3/10] 删除临时调试脚本..."
rm -f /app/test_*.py 2>/dev/null || true
rm -f /app/debug_*.py 2>/dev/null || true
rm -f /app/demo_*.py 2>/dev/null || true
rm -f /app/check_*.py 2>/dev/null || true
rm -f /app/clear_*.py 2>/dev/null || true
rm -f /app/generate_*.py 2>/dev/null || true
rm -f /app/analyze_*.py 2>/dev/null || true
rm -f /app/create_*.py 2>/dev/null || true
echo "  ✓ 已清理临时脚本"

# ------------------- 4. 删除媒体文件 -------------------
echo "[4/10] 删除媒体文件..."
rm -rf /app/content_images 2>/dev/null || true
rm -rf /app/llm_book_images 2>/dev/null || true
rm -rf /app/llm_book_images_fancy 2>/dev/null || true
rm -rf /app/teaching_images 2>/dev/null || true
rm -f /app/*.png 2>/dev/null || true
rm -f /app/*.jpg 2>/dev/null || true
rm -f /app/*.jpeg 2>/dev/null || true
rm -f /app/*.wav 2>/dev/null || true
rm -f /app/*.mp3 2>/dev/null || true
rm -f /app/*.mp4 2>/dev/null || true
echo "  ✓ 已清理媒体文件"

# ------------------- 5. 清理文档（保留 README） -------------------
echo "[5/10] 清理文档..."
# 可以在这里选择性删除不需要的 md 文件
# rm -f /app/DELIVERY_SUMMARY.md
# rm -f /app/OPTIMIZATION_RESULT.md
echo "  ✓ 文档已保留（可手动删除不需要的）"

# ------------------- 6. 清理日志和临时文件 -------------------
echo "[6/10] 清理日志和临时文件..."
rm -rf /app/logs 2>/dev/null || true
rm -f /app/*.log 2>/dev/null || true
rm -f /app/*.tmp 2>/dev/null || true
rm -f /app/.coverage 2>/dev/null || true
echo "  ✓ 已清理日志"

# ------------------- 7. 清理 Ollama 模型 -------------------
echo "[7/10] 清理 Ollama 模型..."
if [ -d "/root/.ollama/models" ]; then
    rm -rf /root/.ollama/models
    echo "  ✓ 已删除 Ollama 模型 (~4-7GB)"
else
    echo "  - 不存在，跳过"
fi

# ------------------- 8. 清理 pip 缓存 -------------------
echo "[8/10] 清理 pip 缓存..."
rm -rf /root/.cache/pip 2>/dev/null || true
echo "  ✓ 已清理 pip 缓存"

# ------------------- 9. 清理 apt 缓存 -------------------
echo "[9/10] 清理 apt 缓存..."
if command -v apt-get &>/dev/null; then
    apt-get clean 2>/dev/null || true
    rm -rf /var/lib/apt/lists/* 2>/dev/null || true
    echo "  ✓ 已清理 apt 缓存"
else
    echo "  - 不是 Debian/Ubuntu 系统，跳过"
fi

# ------------------- 10. 显示结果 -------------------
echo "[10/10] 检查清理结果..."
echo ""
echo "=============================================="
echo "  清理完成！当前目录大小："
echo "=============================================="

if [ -d "/app" ]; then
    du -sh /app 2>/dev/null || echo "/app: 无法计算"
fi

echo ""
if command -v df &>/dev/null; then
    df -h | head -10
fi

echo ""
echo "=============================================="
echo "  现在可以执行 docker commit 了！"
echo "=============================================="
