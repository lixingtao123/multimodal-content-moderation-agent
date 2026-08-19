# 内容风控智能治理系统 — Makefile

.PHONY: up down build logs test test-cov lint format clean seed help ollama-up ollama-pull

help:
	@echo "内容风控智能治理系统"
	@echo ""
	@echo "Usage:"
	@echo "  make up        启动所有服务 (docker compose up -d)"
	@echo "  make down      停止所有服务"
	@echo "  make build     构建所有镜像"
	@echo "  make logs      查看所有服务日志"
	@echo "  make ollama-up 本地启动 Ollama + 拉取 qwen2.5:7b (快车道小模型)"
	@echo "  make ollama-pull 仅拉取 qwen2.5:7b 模型"
	@echo "  make test      运行测试"
	@echo "  make test-cov  运行测试 + 覆盖率报告"
	@echo "  make lint      代码检查"
	@echo "  make format    代码格式化"
	@echo "  make clean     清理临时文件"
	@echo "  make seed      生成测试数据"

# ====== Docker ======
up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

restart: down up

# ====== Ollama（快车道本地小模型，R20 新增） ======
ollama-up:
	bash scripts/ensure_ollama.sh

ollama-pull:
	ollama pull qwen2.5:7b

# ====== 开发 ======
dev:
	cd src/backend && uvicorn main:app --reload --host 0.0.0.0 --port $${BACKEND_PORT:-18080}

install:
	cd src/backend && pip install -r requirements.txt

# ====== 测试 ======
# 注意：tests 用绝对路径 $(CURDIR)/tests，避免 rootdir 变化导致相对路径解析失败
test:
	cd src/backend && python -m pytest $(CURDIR)/tests/ -v

test-cov:
	cd src/backend && python -m pytest $(CURDIR)/tests/ -v --cov=. --cov-report=html --cov-report=term

test-unit:
	cd src/backend && python -m pytest $(CURDIR)/tests/unit/ -v

test-integration:
	cd src/backend && python -m pytest $(CURDIR)/tests/integration/ -v

# ====== 代码质量 ======
lint:
	cd src/backend && ruff check .

format:
	cd src/backend && ruff format .

# ====== 数据 ======
seed:
	cd scripts && python generate_test_data.py

# ====== 清理 ======
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.sqlite3" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage
