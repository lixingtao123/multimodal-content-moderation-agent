# 🚀 Docker 镜像瘦身步骤

## 步骤 1：查看当前运行的容器

```bash
docker ps
```

找到你的容器 ID 或名称（比如 `backend`）。

---

## 步骤 2：进入容器并清理

```bash
# 方式 A：用准备好的脚本（推荐）
docker exec -i <container_id_or_name> bash < /workspace/scripts/clean_slim.sh

# 方式 B：手动执行命令
docker exec -it <container_id_or_name> bash

# 然后在容器内运行：
rm -rf /root/.ollama/models
rm -rf /app/data/OutSafe-Bench
exit
```

---

## 步骤 3：提交为新镜像

```bash
docker commit <container_id_or_name> moderation-slim:v1.0
```

---

## 步骤 4：查看镜像大小

```bash
docker images | grep moderation-slim
```

---

## 步骤 5：测试运行新镜像（可选）

```bash
# 用新镜像启动一个测试容器，验证功能正常
docker run -d --name test-slim moderation-slim:v1.0
```

---

## 预计瘦身效果

| 项目 | 大小 |
|------|------|
| Ollama qwen2.5 模型 | 4-7 GB |
| OutSafe-Bench 数据集 | 1.8 GB |
| **总计** | **6-9 GB** |

对方 30GB 空间完全够用！

---

## 清理后功能验证

| 功能 | 状态 |
|------|------|
| 文本审核 | ✅ 正常，快车道降级为规则评分 |
| 图片审核 | ✅ 正常 |
| 音频审核 | ✅ 正常 |
| 视频审核 | ✅ 正常 |
| RAG 检索 | ✅ 正常（bge 模型还在） |
| 评测功能 | ❌ 不可用（不影响核心） |
