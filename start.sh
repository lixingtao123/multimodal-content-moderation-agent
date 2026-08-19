#!/bin/bash
# ============================================================
# 内容风控智能治理系统 — 一键启动脚本
# 用法: bash start.sh [--build] [--stop] [--*-port N]
#   --build  首次运行或需要重新构建前端时使用
#   --stop   停止所有服务
#   端口配置（命令行参数优先级高于同名环境变量，默认值见下）:
#     默认值已选高位端口，降低冲突概率（规则: 原端口前加前缀 1）
#     --backend-port  N  后端 API 端口   (BACKEND_PORT,  默认 18080)
#     --frontend-port N  前端界面端口    (FRONTEND_PORT, 默认 13000)
#     --funasr-port   N  FunASR 语音端口 (FUNASR_PORT,   默认 15001)
#     --pg-port       N  PostgreSQL 端口 (PG_PORT,       默认 15432)
#     --redis-port    N  Redis 端口      (REDIS_PORT,    默认 16379)
#     --chroma-port   N  ChromaDB 端口   (CHROMA_PORT,   默认 18001)
#     --ollama-port   N  Ollama 端口     (OLLAMA_PORT,   默认 11434)
#   快车道小模型: 脚本会自动调用 scripts/ensure_ollama.sh 拉取 qwen2.5:7b
#   示例:
#     bash start.sh --backend-port 19090 --frontend-port 14000
#     FRONTEND_PORT=14000 BACKEND_PORT=19090 bash start.sh
# ============================================================
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/src/backend"
FRONTEND_DIR="$PROJECT_ROOT/src/frontend"
FUNASR_DIR="$PROJECT_ROOT/src/funasr"
DATA_DIR="$PROJECT_ROOT/data"
LOG_DIR="$PROJECT_ROOT/logs"

# 颜色输出
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[FAIL]${NC}  $1"; }

# ============================================================
# 解析参数
# ============================================================
DO_BUILD=false
DO_STOP=false
BACKEND_PORT_ARG=""; FRONTEND_PORT_ARG=""; FUNASR_PORT_ARG=""
PG_PORT_ARG=""; REDIS_PORT_ARG=""; CHROMA_PORT_ARG=""; OLLAMA_PORT_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --build)         DO_BUILD=true; shift ;;
        --stop)          DO_STOP=true;  shift ;;
        --backend-port)  BACKEND_PORT_ARG="$2";  shift 2 ;;
        --frontend-port) FRONTEND_PORT_ARG="$2"; shift 2 ;;
        --funasr-port)   FUNASR_PORT_ARG="$2";   shift 2 ;;
        --pg-port)       PG_PORT_ARG="$2";       shift 2 ;;
        --redis-port)    REDIS_PORT_ARG="$2";    shift 2 ;;
        --chroma-port)   CHROMA_PORT_ARG="$2";   shift 2 ;;
        --ollama-port)   OLLAMA_PORT_ARG="$2";   shift 2 ;;
        *) shift ;;
    esac
done

# ============================================================
# 端口解析：命令行参数 > 环境变量 > 默认值
# ============================================================
BACKEND_PORT="${BACKEND_PORT_ARG:-${BACKEND_PORT:-18080}}"
FRONTEND_PORT="${FRONTEND_PORT_ARG:-${FRONTEND_PORT:-13000}}"
FUNASR_PORT="${FUNASR_PORT_ARG:-${FUNASR_PORT:-15001}}"
PG_PORT="${PG_PORT_ARG:-${PG_PORT:-15432}}"
REDIS_PORT="${REDIS_PORT_ARG:-${REDIS_PORT:-16379}}"
CHROMA_PORT="${CHROMA_PORT_ARG:-${CHROMA_PORT:-18001}}"
OLLAMA_PORT="${OLLAMA_PORT_ARG:-${OLLAMA_PORT:-11434}}"

# 端口合法性校验
for p in BACKEND_PORT FRONTEND_PORT FUNASR_PORT PG_PORT REDIS_PORT CHROMA_PORT OLLAMA_PORT; do
    if ! [[ "${!p}" =~ ^[0-9]+$ ]] || [ "${!p}" -lt 1 ] || [ "${!p}" -gt 65535 ]; then
        err "端口 $p=${!p} 非法，必须是 1-65535 的整数"; exit 1
    fi
done

# 统一 export：让子进程（uvicorn/vite/funasr server.py）从环境变量读端口
export BACKEND_PORT FRONTEND_PORT FUNASR_PORT PG_PORT REDIS_PORT CHROMA_PORT OLLAMA_PORT
export PGPORT="$PG_PORT"   # pg_isready/psql 客户端默认端口
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:$PG_PORT/moderation"
export DATABASE_URL_SYNC="postgresql://postgres:postgres@localhost:$PG_PORT/moderation"
export REDIS_URL="redis://localhost:$REDIS_PORT/0"
# R22·D2: 本地模式用嵌入式 PersistentClient（复用 /workspace/data/chroma，保留已有案例库）。
# 不再 export CHROMA_URL 指向本地不存在的 HTTP 服务（18001 仅 Docker 模式由 chromadb 容器占用）。
# Docker 模式（docker-compose.yml）单独 export CHROMA_URL=http://chromadb:8000。
export CHROMA_PERSIST_DIR="$DATA_DIR/chroma"
export FUNASR_URL="http://localhost:$FUNASR_PORT"
export OLLAMA_BASE_URL="http://localhost:$OLLAMA_PORT"
export CORS_ORIGINS="[\"http://localhost:$FRONTEND_PORT\"]"
# vite dev 服务器 / SystemMonitor 展示
export VITE_FRONTEND_PORT="$FRONTEND_PORT"
export VITE_BACKEND_PORT="$BACKEND_PORT"
export VITE_PG_PORT="$PG_PORT" VITE_REDIS_PORT="$REDIS_PORT"
export VITE_CHROMA_PORT="$CHROMA_PORT" VITE_FUNASR_PORT="$FUNASR_PORT"

# ============================================================
# 停止所有服务
# ============================================================
if $DO_STOP; then
    info "停止所有服务..."
    pkill -f "uvicorn main:app" 2>/dev/null || true
    pkill -f "funasr" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
    # Ollama 是外部共享服务（可能被其他项目使用），不在此停止；如需停止:
    #   pkill -f "ollama serve"
    ok "项目服务已停止（Ollama 保留运行，如需停止请手动 pkill -f 'ollama serve'）"
    exit 0
fi

# ============================================================
# 环境检查
# ============================================================
info "========== 环境检查 =========="

# GPU
if nvidia-smi &>/dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1)
    ok "GPU: $GPU_NAME ($GPU_MEM)"
else
    warn "未检测到 GPU，将使用 CPU 模式"
fi

# Python
PYTHON=$(which python3)
PYTHON_VER=$($PYTHON --version 2>&1)
ok "Python: $PYTHON_VER"

# Node.js
if [ -s /root/.nvm/nvm.sh ]; then
    . /root/.nvm/nvm.sh
    nvm use 20 >/dev/null
fi
if command -v node &>/dev/null; then
    ok "Node.js: $(node --version)"
else
    err "Node.js 未安装，前端无法启动"
fi

# ffmpeg
if command -v ffmpeg &>/dev/null; then
    ok "ffmpeg: $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f3)"
else
    warn "ffmpeg 未安装，视频审核将受限"
fi

# sox (3D-Speaker CAM++ 备选策略需要)
if command -v sox &>/dev/null; then
    ok "sox: $(sox --version 2>&1 | head -1)"
else
    warn "sox 未安装，3D-Speaker CAM++ 备选策略将不可用 (apt-get install -y sox libsox-dev)"
fi

# ============================================================
# 创建必要目录
# ============================================================
mkdir -p "$DATA_DIR/chroma" "$LOG_DIR"

# ============================================================
# 1. PostgreSQL
# ============================================================
info "========== 启动 PostgreSQL (端口 $PG_PORT) =========="
if pg_isready -U postgres -h localhost -p "$PG_PORT" &>/dev/null; then
    ok "PostgreSQL 已运行 (端口 $PG_PORT)"
else
    info "启动 PostgreSQL (端口 $PG_PORT)..."
    # 若 cluster 已在旧端口运行，先停再以新端口启动（保留同一数据目录）
    pg_ctlcluster 14 main stop 2>/dev/null || true
    pg_ctlcluster 16 main stop 2>/dev/null || true
    pg_ctlcluster 14 main start -o "-p $PG_PORT" 2>/dev/null || \
    pg_ctlcluster 16 main start -o "-p $PG_PORT" 2>/dev/null || {
        warn "PostgreSQL 启动失败，请手动启动"
    }
    sleep 2
    if pg_isready -U postgres -h localhost -p "$PG_PORT" &>/dev/null; then
        ok "PostgreSQL 启动成功 (端口 $PG_PORT)"
    else
        err "PostgreSQL 不可用 (端口 $PG_PORT)"
    fi
fi

# 确保数据库存在（su - postgres 是登录 shell 会清空环境变量，需内联 PGPORT）
su - postgres -c "PGPORT=$PG_PORT psql -c \"CREATE DATABASE moderation;\"" 2>/dev/null || true
# 确保 schema 已导入
su - postgres -c "PGPORT=$PG_PORT psql -d moderation -f $BACKEND_DIR/db/schema.sql" 2>/dev/null || true

# ============================================================
# 2. Redis
# ============================================================
info "========== 启动 Redis (端口 $REDIS_PORT) =========="
if redis-cli -p "$REDIS_PORT" ping &>/dev/null; then
    ok "Redis 已运行 (端口 $REDIS_PORT)"
else
    info "启动 Redis (端口 $REDIS_PORT)..."
    redis-server --daemonize yes --port "$REDIS_PORT" 2>/dev/null || {
        err "Redis 启动失败"
    }
    sleep 1
    if redis-cli -p "$REDIS_PORT" ping &>/dev/null; then
        ok "Redis 启动成功 (端口 $REDIS_PORT)"
    else
        err "Redis 不可用 (端口 $REDIS_PORT)"
    fi
fi

# ============================================================
# 3. Ollama 快车道小模型（R20 新增）
# ============================================================
info "========== 启动 Ollama 快车道小模型 (端口 $OLLAMA_PORT) =========="
if [ -f "$PROJECT_ROOT/scripts/ensure_ollama.sh" ]; then
    # ensure_ollama.sh 幂等：serve 已跑则跳过，模型已拉取则跳过。
    # 失败（未安装 ollama）只告警不阻断 —— 快车道自动降级规则评分器。
    if ! bash "$PROJECT_ROOT/scripts/ensure_ollama.sh" 2>&1 | sed 's/^/  /'; then
        warn "Ollama 初始化失败，快车道将降级为规则评分器（可稍后手动: bash scripts/ensure_ollama.sh）"
    fi
else
    warn "scripts/ensure_ollama.sh 不存在，跳过 Ollama 初始化"
fi

# ============================================================
# 4. FunASR 服务
# ============================================================
info "========== 启动 FunASR (端口 $FUNASR_PORT) =========="
FUNASR_PID=""
FUNASR_HEALTH="http://localhost:$FUNASR_PORT/health"
if curl -s "$FUNASR_HEALTH" &>/dev/null; then
    ok "FunASR 已运行 (端口 $FUNASR_PORT)"
else
    if [ -f "$FUNASR_DIR/server.py" ]; then
        info "启动 FunASR 语音识别服务 (端口 $FUNASR_PORT)..."
        cd "$FUNASR_DIR"
        FUNASR_PORT="$FUNASR_PORT" nohup $PYTHON server.py > "$LOG_DIR/funasr.log" 2>&1 &
        FUNASR_PID=$!
        echo $FUNASR_PID > "$LOG_DIR/funasr.pid"
        cd "$PROJECT_ROOT"
        # 等待 FunASR 模型加载（首次需要下载，最多等 2 分钟）
        info "等待 FunASR 模型加载（首次启动可能需要下载模型）..."
        for i in $(seq 1 24); do
            if curl -s "$FUNASR_HEALTH" &>/dev/null; then
                ok "FunASR 启动成功 (PID: $FUNASR_PID)"
                break
            fi
            sleep 5
            echo -n "."
        done
        if ! curl -s "$FUNASR_HEALTH" &>/dev/null; then
            warn "FunASR 启动超时（检查日志: $LOG_DIR/funasr.log）"
        fi
    else
        warn "FunASR 服务文件不存在，跳过"
    fi
fi

# ============================================================
# 5. 前端构建
# ============================================================
info "========== 构建前端 =========="
if [ -d "$FRONTEND_DIR" ]; then
    cd "$FRONTEND_DIR"
    if $DO_BUILD || [ ! -d "node_modules" ]; then
        info "安装前端依赖..."
        npm install --silent 2>&1 | tail -1
    fi
    if $DO_BUILD || [ ! -d "dist" ]; then
        info "构建前端..."
        npx vite build --logLevel warn 2>&1
        ok "前端构建完成"
    else
        ok "前端已构建，使用 --build 强制重建"
    fi
    cd "$PROJECT_ROOT"
fi

# ============================================================
# 6. 启动后端
# ============================================================
info "========== 启动后端 =========="
# 先停掉旧的后端进程
pkill -f "uvicorn main:app" 2>/dev/null || true
sleep 1

cd "$BACKEND_DIR"
nohup $PYTHON -m uvicorn main:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    --reload \
    --log-level info \
    > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > "$LOG_DIR/backend.pid"
cd "$PROJECT_ROOT"

# 等待后端就绪
info "等待后端启动..."
for i in $(seq 1 10); do
    if curl -s "http://localhost:$BACKEND_PORT/health" &>/dev/null; then
        ok "后端启动成功 (PID: $BACKEND_PID, 端口: $BACKEND_PORT)"
        break
    fi
    sleep 2
    echo -n "."
done
echo ""

# ============================================================
# 7. 前端开发服务器
# ============================================================
info "========== 启动前端 =========="
pkill -f "vite" 2>/dev/null || true
sleep 1

cd "$FRONTEND_DIR"
nohup npx vite --host 0.0.0.0 --port "$FRONTEND_PORT" > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > "$LOG_DIR/frontend.pid"
cd "$PROJECT_ROOT"

sleep 3
if curl -s "http://localhost:$FRONTEND_PORT" &>/dev/null; then
    ok "前端启动成功 (PID: $FRONTEND_PID, 端口: $FRONTEND_PORT)"
else
    warn "前端可能仍在启动中（PID: $FRONTEND_PID）"
fi

# ============================================================
# 8. 最终状态报告
# ============================================================
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║     内容风控智能治理系统 — 启动完成               ║"
echo "╠══════════════════════════════════════════════════╣"
print_box() { printf "║  %-48s ║\n" "$1"; }
print_box "后端 API:  http://localhost:$BACKEND_PORT"
print_box "API 文档:  http://localhost:$BACKEND_PORT/docs"
print_box "健康检查:  http://localhost:$BACKEND_PORT/health"
print_box "前端界面:  http://localhost:$FRONTEND_PORT"
print_box "FunASR:    http://localhost:$FUNASR_PORT (语音识别)"
echo "╠══════════════════════════════════════════════════╣"

# 服务状态
echo -n "║  PostgreSQL: "
pg_isready -U postgres -h localhost -p "$PG_PORT" &>/dev/null && echo -n "✅" || echo -n "❌"
echo -n "  Redis: "
redis-cli -p "$REDIS_PORT" ping &>/dev/null && echo -n "✅" || echo -n "❌"
echo -n "  FunASR: "
curl -s "http://localhost:$FUNASR_PORT/health" &>/dev/null && echo -n "✅" || echo -n "❌"
echo -n "  后端: "
curl -s "http://localhost:$BACKEND_PORT/health" &>/dev/null && echo -n "✅" || echo -n "❌"
echo -n "  前端: "
curl -s "http://localhost:$FRONTEND_PORT" &>/dev/null && echo -n "✅" || echo -n "❌"
echo ""
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "日志文件:"
echo "  后端:   $LOG_DIR/backend.log"
echo "  前端:   $LOG_DIR/frontend.log"
echo "  FunASR: $LOG_DIR/funasr.log"
echo ""
echo "停止所有服务: bash start.sh --stop"
echo ""
echo "════════ 实时日志（Ctrl+C 退出） ════════"
echo ""
# 前台模式：持续打印后端日志，终端保持存活
tail -f "$LOG_DIR/backend.log"
