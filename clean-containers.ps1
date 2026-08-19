# 内容风控智能治理系统 — 容器清理脚本
# 在 docker commit 前运行，清理垃圾文件减少镜像体积

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  清理容器垃圾文件" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------
# 清理 Backend
# ------------------------------
Write-Host "[1/3] 清理 backend 容器..." -ForegroundColor Yellow
docker exec workspace-backend-1 bash -c @"
rm -rf /tmp/* /var/tmp/*
rm -rf /root/.cache/pip
rm -rf /app/__pycache__ /app/*.pyc 2>/dev/null
find /app -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
find /app -name '*.pyc' -delete 2>/dev/null
rm -rf /app/.pytest_cache /app/.ruff_cache 2>/dev/null
rm -rf /app/logs/* 2>/dev/null
rm -rf /app/models/* 2>/dev/null
rm -rf /app/data/* 2>/dev/null
apt-get clean
rm -rf /var/lib/apt/lists/*
"@
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ backend 容器清理完成" -ForegroundColor Green
} else {
    Write-Host "⚠️ backend 容器清理遇到问题（可能容器没运行），继续..." -ForegroundColor Yellow
}
Write-Host ""

# ------------------------------
# 清理 Frontend
# ------------------------------
Write-Host "[2/3] 清理 frontend 容器..." -ForegroundColor Yellow
docker exec workspace-frontend-1 sh -c @"
rm -rf /tmp/* /var/tmp/*
rm -rf /root/.npm
rm -rf /app/node_modules/.cache 2>/dev/null
"@
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ frontend 容器清理完成" -ForegroundColor Green
} else {
    Write-Host "⚠️ frontend 容器清理遇到问题（可能容器没运行），继续..." -ForegroundColor Yellow
}
Write-Host ""

# ------------------------------
# 清理 FunASR
# ------------------------------
Write-Host "[3/3] 清理 funasr 容器..." -ForegroundColor Yellow
docker exec workspace-funasr-1 bash -c @"
rm -rf /tmp/* /var/tmp/*
rm -rf /root/.cache/pip
rm -rf /models/* 2>/dev/null
apt-get clean
rm -rf /var/lib/apt/lists/*
"@
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ funasr 容器清理完成" -ForegroundColor Green
} else {
    Write-Host "⚠️ funasr 容器清理遇到问题（可能容器没运行），继续..." -ForegroundColor Yellow
}
Write-Host ""

Write-Host "🎉 容器清理完成！" -ForegroundColor Green
Write-Host ""
Write-Host "下一步：" -ForegroundColor Cyan
Write-Host "  1. 停止容器: docker stop workspace-backend-1 workspace-frontend-1 workspace-funasr-1" -ForegroundColor White
Write-Host "  2. 提交镜像: docker commit workspace-backend-1 moderation-backend:v1.0" -ForegroundColor White
Write-Host "  3. 导出镜像: docker save -o moderation-system-v1.0.tar moderation-backend:v1.0 moderation-frontend:v1.0 moderation-funasr:v1.0" -ForegroundColor White
