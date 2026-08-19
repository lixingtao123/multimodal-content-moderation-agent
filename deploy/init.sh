#!/bin/bash
# ==============================================================================
# 内容风控智能治理系统 — 单容器初始化脚本
# ==============================================================================

set -e

echo "=========================================="
echo "  内容风控智能治理系统"
echo "  正在初始化..."
echo "=========================================="
echo ""

# 0. 创建必要目录
mkdir -p /data/postgres /data/redis /data/chroma /app/logs /app/tmp
chmod -R 755 /data

# 1. 初始化 PostgreSQL（如果需要）
if [ ! -d /data/postgres/base ]; then
    echo "[1/6] 初始化 PostgreSQL..."
    chown -R postgres:postgres /data/postgres
    sudo -u postgres /usr/lib/postgresql/14/bin/initdb -D /data/postgres

    # 修改配置
    echo "host all all 0.0.0.0/0 md5" >> /data/postgres/pg_hba.conf
    echo "listen_addresses = '*'" >> /data/postgres/postgresql.conf
fi

# 2. 启动 PostgreSQL（临时）
echo "[2/6] 启动 PostgreSQL..."
sudo -u postgres /usr/lib/postgresql/14/bin/pg_ctl -D /data/postgres -o "-c listen_addresses='localhost'" -w start

# 等待 PostgreSQL 启动
sleep 3

# 3. 创建数据库和用户（如果需要）
echo "[3/6] 配置数据库..."
sudo -u postgres psql << SQL || true
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_user WHERE usename = 'postgres') THEN
        CREATE USER postgres WITH PASSWORD 'postgres';
    END IF;
END
\$\$;
CREATE DATABASE IF NOT EXISTS moderation;
GRANT ALL PRIVILEGES ON DATABASE moderation TO postgres;
SQL

# 4. 初始化数据库 schema
echo "[4/6] 初始化数据库 schema..."
if [ -f /app/backend/db/schema.sql ]; then
    sudo -u postgres psql -d moderation -f /app/backend/db/schema.sql || true
fi

# 5. 停止临时 PostgreSQL
echo "[5/6] 停止临时 PostgreSQL..."
sudo -u postgres /usr/lib/postgresql/14/bin/pg_ctl -D /data/postgres stop

# 6. 启动 supervisord 管理所有服务
echo "[6/6] 启动所有服务..."
echo ""
echo "=========================================="
echo "  系统准备就绪！"
echo "  访问:"
echo "  - Frontend: http://localhost:13000"
echo "  - Backend:  http://localhost:18080"
echo "=========================================="
echo ""

# 启动 supervisord
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/all-in-one.conf
