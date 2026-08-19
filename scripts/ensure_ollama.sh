#!/usr/bin/env bash
# ============================================================
# 幂等初始化 Ollama + 快车道小模型（R20 新增）
#
# 用途：确保 Ollama 服务在运行、qwen2.5:7b 模型已拉取。
#      可被 start.sh 调用，也可单独执行。
# 用法: bash scripts/ensure_ollama.sh [model]
#       默认 model = qwen2.5:7b（可被 OLLAMA_MODEL 环境变量覆盖）
# ============================================================
set -euo pipefail

MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"

info() { echo "ℹ️  $*"; }
err()  { echo "❌ $*" >&2; }

# 1. 检查 ollama 可执行文件
if ! command -v ollama >/dev/null 2>&1; then
    err "未检测到 ollama 命令。请先安装："
    err "  curl -fsSL https://ollama.com/install.sh | sh"
    err "或使用 Docker：docker compose up -d ollama"
    exit 1
fi

# 2. 确保 ollama serve 在运行（幂等）
if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    info "ollama serve 已在运行 ($OLLAMA_URL)"
else
    info "ollama serve 未运行，尝试启动..."
    if pgrep -f "ollama serve" >/dev/null 2>&1; then
        err "存在 ollama 进程但 API 未响应，请检查端口 $OLLAMA_URL 与日志"
        exit 1
    fi
    nohup ollama serve >/tmp/ollama.log 2>&1 &
    READY=0
    for i in $(seq 1 30); do
        sleep 1
        if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
            READY=1
            break
        fi
    done
    if [ "$READY" -ne 1 ]; then
        err "ollama serve 30s 内未就绪，查看 /tmp/ollama.log"
        exit 1
    fi
    info "ollama serve 已启动"
fi

# 3. 确保模型已拉取（幂等）
if curl -sf "$OLLAMA_URL/api/tags" | grep -q "\"$MODEL\""; then
    info "模型 $MODEL 已就绪"
else
    info "拉取模型 $MODEL（约 4.7GB，视网络 5-30 分钟）..."
    ollama pull "$MODEL"
fi

echo "✅ Ollama 就绪：$OLLAMA_URL  model=$MODEL"
