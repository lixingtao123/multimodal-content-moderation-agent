"""
异步审核 API 端点 — 全模态异步提交 + 任务状态查询 + 任务列表

用法:
  POST /api/v1/moderate/async          → 异步提交 (multipart, 全模态统一入口)
  GET  /api/v1/moderate/task/{id}      → 任务状态 + 结果
  GET  /api/v1/moderate/tasks           → 任务列表 (分页)
  DELETE /api/v1/moderate/task/{id}     → 取消排队中的任务
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query

from agent_moderation.workers.task_worker import get_task_worker_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["async-moderation"])


# ===== 异步提交 (全模态统一入口) =====

@router.post("/moderate/async")
async def submit_async_task(
    text: str = Form(""),
    account_id: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
):
    """
    异步提交审核任务 (全模态统一入口)

    支持任意组合: 纯文本 / 图片 / 音频 / 视频 / 文档 / 混合

    返回 task_id 后立即返回 (HTTP 202), 后台 Worker Pool 异步执行。
    前端通过 GET /moderate/task/{task_id} 轮询结果。
    """
    content: dict = {}
    content_type = "text"
    content_preview = ""

    # 处理文本
    if text and text.strip():
        content["text"] = text.strip()
        content_preview = text.strip()[:200]
    else:
        text = ""

    # 处理文件
    if files:
        file_list = []
        file_names = []
        has_images = False
        has_audio = False

        for file in files:
            file_bytes = await file.read()
            if not file_bytes:
                continue

            mime = file.content_type or "application/octet-stream"
            file_list.append({
                "filename": file.filename or "unknown",
                "content": file_bytes,
                "mime_type": mime,
            })
            file_names.append(file.filename or "unknown")

            # 判断模态
            if mime.startswith("image/"):
                has_images = True
            elif mime.startswith("audio/") or (file.filename or "").lower().endswith((".mp3", ".wav", ".flac", ".m4a")):
                has_audio = True

        content["files"] = file_list
        content["_multi_modal"] = True

        # 确定内容类型
        if has_images and text:
            content_type = "multi_modal"
        elif has_images:
            content_type = "image"
        elif has_audio:
            content_type = "audio"
        elif file_list:
            content_type = "text"  # 文档类 -> 文本提取

        if not content_preview:
            content_preview = f"[{len(file_list)} 个文件: {', '.join(file_names[:3])}]"

        logger.info(f"[Async] Received {len(file_list)} files, content_type={content_type}")

    if not text.strip() and not files:
        raise HTTPException(status_code=400, detail="请提供文本内容或上传文件")

    # 特殊模态: 单图片/音频提交
    if content_type == "image" and len(files) == 1:
        content["image"] = file_list[0]["content"]
        content["filename"] = file_list[0]["filename"]
        del content["files"]
        content.pop("_multi_modal", None)
    elif content_type == "audio" and len(files) == 1:
        content["audio"] = file_list[0]["content"]
        content["filename"] = file_list[0]["filename"]
        del content["files"]
        content.pop("_multi_modal", None)

    # 提交到 Worker Pool
    pool = get_task_worker_pool()
    task_id = await pool.submit(
        content_type=content_type,
        content=content,
        account_id=account_id,
        content_preview=content_preview,
    )

    return {
        "task_id": task_id,
        "status": "QUEUED",
        "content_type": content_type,
        "created_at": "",  # Worker 填充
        "message": f"任务已提交 ({content_type}), 请通过 GET /moderate/task/{task_id} 查询进度",
    }


# ===== 任务状态查询 =====

@router.get("/moderate/task/{task_id}")
async def get_task_status(task_id: str):
    """查询任务状态和结果"""
    pool = get_task_worker_pool()
    status = await pool.get_status(task_id)

    if not status:
        # 尝试从原有查询端点获取 (兼容 content_id = task_id)
        from api.routes.query import get_moderation_result
        try:
            result = await get_moderation_result(task_id)
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "progress": 1.0,
                "content_type": result.get("content_type", "text"),
                "content_preview": result.get("content_preview", ""),
                "created_at": result.get("created_at", ""),
                "final_decision": result.get("final_decision"),
                "risk_score": result.get("risk_score"),
                "violation_types": result.get("violation_types", []),
                "processing_time_ms": result.get("processing_time_ms"),
                "agent_reasoning": result.get("agent_reasoning"),
                "debate_info": result.get("debate_info"),
                "suggestions": result.get("suggestions"),
            }
        except HTTPException:
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    return status


# ===== 任务列表 =====

@router.get("/moderate/tasks")
async def list_tasks(
    limit: int = Query(50, ge=1, le=200),
    status: str = Query("all", description="Filter: all / QUEUED / PROCESSING / COMPLETED / FAILED"),
):
    """列出最近的任务"""
    pool = get_task_worker_pool()
    result = await pool.list_tasks(limit=limit, status_filter=status)
    return result


# ===== 取消任务 =====

@router.delete("/moderate/task/{task_id}")
async def cancel_task(task_id: str):
    """取消一个排队中的任务"""
    pool = get_task_worker_pool()
    cancelled = await pool.cancel_task(task_id)
    if not cancelled:
        raise HTTPException(status_code=400, detail="只能取消 QUEUED 状态的任务")
    return {"task_id": task_id, "cancelled": True}
