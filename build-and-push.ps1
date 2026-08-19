# 内容风控智能治理系统 — 一键构建并推送镜像 (Windows PowerShell 版)
# 用法: .\build-and-push.ps1 [version]
# 默认版本: v1.0

param(
    [string]$Version = "v1.0"
)

$ErrorActionPreference = "Stop"

$Registry = "registry.cn-hangzhou.aliyuncs.com/moderation-system"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  内容风控智能治理系统 — 镜像构建与推送" -ForegroundColor Cyan
Write-Host "  仓库: $Registry" -ForegroundColor Cyan
Write-Host "  版本: $Version" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 确保在项目根目录
Set-Location $PSScriptRoot

# ------------------------------
# 步骤 1: 构建 Backend
# ------------------------------
Write-Host "[1/3] 构建 backend 镜像..." -ForegroundColor Yellow
docker build --no-cache -t ${Registry}/moderation-backend:${Version} -f src/backend/Dockerfile src/backend/
if ($LASTEXITCODE -ne 0) { throw "backend 镜像构建失败" }
Write-Host "✅ backend 镜像构建完成: ${Registry}/moderation-backend:${Version}" -ForegroundColor Green
Write-Host ""

# ------------------------------
# 步骤 2: 构建 Frontend
# ------------------------------
Write-Host "[2/3] 构建 frontend 镜像..." -ForegroundColor Yellow
docker build --no-cache -t ${Registry}/moderation-frontend:${Version} -f src/frontend/Dockerfile src/frontend/
if ($LASTEXITCODE -ne 0) { throw "frontend 镜像构建失败" }
Write-Host "✅ frontend 镜像构建完成: ${Registry}/moderation-frontend:${Version}" -ForegroundColor Green
Write-Host ""

# ------------------------------
# 步骤 3: 构建 FunASR
# ------------------------------
Write-Host "[3/3] 构建 funasr 镜像..." -ForegroundColor Yellow
docker build --no-cache -t ${Registry}/moderation-funasr:${Version} -f src/funasr/Dockerfile src/funasr/
if ($LASTEXITCODE -ne 0) { throw "funasr 镜像构建失败" }
Write-Host "✅ funasr 镜像构建完成: ${Registry}/moderation-funasr:${Version}" -ForegroundColor Green
Write-Host ""

# ------------------------------
# 步骤 4: 推送镜像
# ------------------------------
$Reply = Read-Host "是否现在推送镜像到阿里云容器镜像服务? (y/n)"
if ($Reply -eq "y" -or $Reply -eq "Y") {
    Write-Host "开始推送镜像..." -ForegroundColor Yellow

    docker push ${Registry}/moderation-backend:${Version}
    if ($LASTEXITCODE -ne 0) { throw "backend 镜像推送失败" }
    Write-Host "✅ backend 镜像推送完成" -ForegroundColor Green

    docker push ${Registry}/moderation-frontend:${Version}
    if ($LASTEXITCODE -ne 0) { throw "frontend 镜像推送失败" }
    Write-Host "✅ frontend 镜像推送完成" -ForegroundColor Green

    docker push ${Registry}/moderation-funasr:${Version}
    if ($LASTEXITCODE -ne 0) { throw "funasr 镜像推送失败" }
    Write-Host "✅ funasr 镜像推送完成" -ForegroundColor Green

    Write-Host ""
    Write-Host "🎉 所有镜像推送完成！" -ForegroundColor Green
    Write-Host ""
    Write-Host "用户可以通过以下命令启动:" -ForegroundColor Cyan
    Write-Host "  docker-compose -f docker-compose.delivery.yml up -d" -ForegroundColor White
} else {
    Write-Host "跳过推送，镜像已保存在本地。" -ForegroundColor Cyan
    Write-Host "手动推送命令:" -ForegroundColor Cyan
    Write-Host "  docker push ${Registry}/moderation-backend:${Version}" -ForegroundColor White
    Write-Host "  docker push ${Registry}/moderation-frontend:${Version}" -ForegroundColor White
    Write-Host "  docker push ${Registry}/moderation-funasr:${Version}" -ForegroundColor White
}
