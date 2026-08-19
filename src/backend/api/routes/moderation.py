"""
审核 API v2 — 支持 text/image/audio/video 四种模态
集成全链路流水线日志
"""
import uuid
import time
import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from agent_moderation.state import create_initial_state
from agent_moderation.workflows.moderation import get_workflow
from memory.manager import get_memory_manager
from db.connection import get_session
from db import connection as db_conn
from common.logger import start_pipeline, get_pipeline
from common.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["moderation"])

memory = get_memory_manager()


class TextModerationRequest(BaseModel):
    content_type: str = "text"
    text: str
    account_id: Optional[str] = None


class ModerationResponse(BaseModel):
    content_id: str
    content_type: str
    final_decision: str
    risk_score: float
    violation_types: list = []
    violation_details: dict = {}
    suggestions: list = []
    processing_time_ms: float = 0.0
    cached: bool = False
    human_review_required: bool = False
    debate_info: dict | None = None
    agent_reasoning: dict | None = None


async def _run_moderation(content_type: str, content: dict, account_id: Optional[str] = None) -> dict:
    """执行审核工作流 — 同步端点入口 (自动生成 content_id)"""
    content_id = f"mod_{uuid.uuid4().hex[:16]}"
    return await _run_moderation_core(
        content_type=content_type,
        content=content,
        account_id=account_id,
        task_id=content_id,
        progress_callback=None,
    )


async def _run_moderation_core(
    content_type: str,
    content: dict,
    account_id: Optional[str] = None,
    task_id: Optional[str] = None,
    progress_callback: Optional[callable] = None,
) -> dict:
    """
    执行审核工作流 — 核心逻辑 (同步和异步端点共用)

    Args:
        content_type: text / image / audio / video / multi_modal
        content: 原始内容 dict
        account_id: 账号 ID (可选)
        task_id: 任务 ID (同步端点自动生成 mod_xxx, 异步使用给定 task_id)
        progress_callback: 进度回调 async def cb(step: str, progress: float)

    Returns:
        审核结果 dict
    """
    content_id = task_id or f"mod_{uuid.uuid4().hex[:16]}"

    # === 开始流水线日志 ===
    pipeline = start_pipeline(content_id, content_type)

    # 重复内容检查
    if content_type == "text" and "text" in content:
        text = content.get("text", "")
        dup_id = await memory.check_duplicate_content(text)
        if dup_id:
            logger.info(f"Duplicate content detected: {dup_id}")
            pipeline.step("GATEWAY", "重复内容命中缓存", output_data={"duplicate_id": dup_id})
            cached_status = await memory.get_task_status(dup_id)
            if cached_status:
                cached_decision = str(cached_status.get("final_decision", "PASS")).upper()
                return {
                    "content_id": dup_id, "content_type": content_type,
                    "final_decision": cached_decision,
                    "risk_score": cached_status.get("risk_score", 0.0),
                    "violation_types": cached_status.get("violation_types", []),
                    "violation_details": cached_status.get("violation_details", {}),
                    "suggestions": cached_status.get("suggestions", []),
                    "processing_time_ms": 0.0, "cached": True,
                    "human_review_required": bool(cached_status.get("human_review_required"))
                    or cached_decision in ("REVIEW", "PENDING_HUMAN_REVIEW"),
                }

    # 创建初始状态
    state = create_initial_state(
        content_id=content_id, content_type=content_type,
        content=content, account_id=account_id,
    )
    pipeline.step("GATEWAY", "状态初始化", input_data={"content_type": content_type,
        "size": content.get("text", "")[:50] if "text" in content else len(content.get("image", content.get("audio", content.get("video", b"")))),
    })

    if progress_callback:
        await progress_callback("initialized", 0.05)

    # v4.0: 多模态标记 — 让 LangGraph Planner 统一调度
    # 不再在 API 层预调用 Coordinator
    is_multi_modal = (
        content_type in ("multi_modal",) or
        content.get("_multi_modal") or
        bool(content.get("files"))
    )
    has_multiple_modalities = is_multi_modal and (
        (content.get("text") and content.get("files")) or
        (len(content.get("files", [])) > 1)
    )
    if has_multiple_modalities:
        state["_is_multimodal"] = True

    # 执行工作流
    workflow = get_workflow()
    config = {"configurable": {"thread_id": content_id}}

    try:
        if progress_callback:
            await progress_callback("workflow_started", 0.1)
        start = time.time()
        result = await workflow.ainvoke(state, config)
        elapsed = (time.time() - start) * 1000
    except Exception as e:
        import traceback
        logger.error(f"Workflow failed with traceback:\n{traceback.format_exc()}")
        # 检查是否为 Human-in-the-Loop 中断
        if "GraphInterrupt" in type(e).__name__ or "interrupt" in str(e).lower():
            pipeline.step("👤 HUMAN_REVIEW", "⏸️ 工作流暂停,等待人工审核",
                          output_data={"content_id": content_id, "status": "AWAITING_HUMAN"})
            pipeline.save()
            await _register_pending_review(content_id, state)
            if progress_callback:
                await progress_callback("awaiting_human", 1.0)
            logger.info(f"Workflow {content_id} interrupted for human review")
            return {
                "content_id": content_id, "content_type": content_type,
                "final_decision": "PENDING_HUMAN_REVIEW",
                "risk_score": 0.0,
                "violation_types": [],
                "violation_details": {"status": "awaiting_human_review"},
                "suggestions": [{"action": "MANUAL_REVIEW",
                                 "reason": "内容需要人工审核,请通过 POST /api/v1/moderate/{content_id}/review 提交判定",
                                 "priority": "HIGH"}],
                "processing_time_ms": (time.time() - start) * 1000,
                "human_review_required": True,
            }
        pipeline.step("ERROR", f"工作流执行失败: {e}")
        logger.error(f"Workflow execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"Moderation workflow failed: {str(e)}")

    if progress_callback:
        await progress_callback("workflow_completed", 0.9)

    # 去重标记
    if content_type == "text" and "text" in content:
        await memory.mark_content_processed(content.get("text", ""), content_id)

    # 持久化流水线日志
    pipeline.save()

    final_risk = result.get("final_risk") or {}

    human_review_state = result.get("_human_review") or {}
    final_decision = str(result.get("final_decision", "")).upper()
    human_review_required = bool(
        final_decision in ("REVIEW", "PENDING_HUMAN_REVIEW")
        or (
            human_review_state.get("required")
            and human_review_state.get("status") == "PENDING"
        )
    )
    if human_review_required:
        pending_state = dict(result)
        pending_state["content"] = result.get("content") or state.get("content") or content
        pending_state["content_type"] = result.get("content_type") or state.get("content_type") or content_type
        pending_state["final_risk"] = final_risk
        pending_state["_human_review"] = {
            **human_review_state,
            "required": True,
            "status": "PENDING",
            "reason": human_review_state.get("reason") or "审核结果为 REVIEW，等待人工确认",
        }
        await _register_pending_review(content_id, pending_state)
        logger.info(
            f"Workflow {content_id} registered for human review: "
            f"{pending_state['_human_review']['reason']}"
        )
        pipeline.step("👤 HUMAN_REVIEW", "标记为待人工审核 (模糊边界)",
                      output_data={"reason": pending_state["_human_review"]["reason"], "status": "PENDING"})

    # === 构建辩论信息 ===
    debate_result = state.get("_debate_result") or result.get("_debate_result")
    debate_info = None
    if debate_result and debate_result.get("debated"):
        debate_info = {
            "had_debate": True,
            "debate_mode": debate_result.get("mode", "unknown"),
            "opinion_count": debate_result.get("opinion_count", 0),
            "final_confidence": debate_result.get("final_confidence", 0),
            "is_consensus": debate_result.get("is_consensus", False),
            "needs_human_review": debate_result.get("needs_human_review", False),
            "agent_opinions": [],
        }

    # === 收集各 Agent 的推理过程 ===
    agent_reasoning = {}
    for key in ["text_result", "image_result", "audio_result", "video_result"]:
        agent_result = state.get(key) or result.get(key)
        if agent_result and isinstance(agent_result, dict):
            chain = agent_result.get("reasoning_chain", [])
            detail = agent_result.get("reasoning", "") or agent_result.get("reason", "")
            raw_matches = agent_result.get("keyword_matches", [])
            if raw_matches and isinstance(raw_matches, list) and len(raw_matches) > 0 and isinstance(raw_matches[0], dict):
                keyword_matches = [m["keyword"] if isinstance(m, dict) else str(m) for m in raw_matches]
            else:
                keyword_matches = raw_matches if raw_matches else []
            if chain or detail:
                agent_reasoning[key.replace("_result", "")] = {
                    "violation_type": agent_result.get("violation_type", "none"),
                    "confidence": agent_result.get("confidence", 0),
                    "reason": agent_result.get("reason", ""),
                    "reasoning": detail,
                    "reasoning_chain": chain,
                    "keyword_matches": keyword_matches,
                }

    result["agent_reasoning"] = agent_reasoning if agent_reasoning else None
    result["debate_info"] = debate_info

    # 更新 Redis 短期记忆
    # R22: 静默吞错 → 记录降级日志（可观测，不中断主流程）
    try:
        await memory.redis.update_short_term(content_id, {
            "status": "COMPLETED",
            "final_decision": result.get("final_decision", "UNKNOWN"),
            "risk_score": final_risk.get("overall_score", 0.0),
            "human_review_required": human_review_required,
            "agent_reasoning": agent_reasoning,
            "debate_info": debate_info,
            "violation_types": final_risk.get("violation_types", []),
            "violation_details": final_risk,
            "suggestions": final_risk.get("suggestions", []),
            "processing_time_ms": elapsed,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    except Exception as e:
        logger.warning(f"[Moderation] Redis short-term memory update failed "
                       f"(content_id={content_id}, degraded): {e}")
        result["_redis_degraded"] = True

    # 入库
    await _save_to_db(content_id, content_type, content, result, elapsed)

    pipeline.step("GATEWAY", "审核完成",
        output_data={"decision": result.get("final_decision"),
                     "score": final_risk.get("overall_score"),
                     "types": final_risk.get("violation_types", []),
                     "total_ms": elapsed})

    response = {
        "content_id": content_id, "content_type": content_type,
        "final_decision": result.get("final_decision", "UNKNOWN"),
        "risk_score": final_risk.get("overall_score", 0.0),
        "violation_types": final_risk.get("violation_types", []),
        "violation_details": final_risk,
        "suggestions": final_risk.get("suggestions", []),
        "processing_time_ms": elapsed,
        "debate_info": debate_info,
        "agent_reasoning": agent_reasoning if agent_reasoning else None,
        "human_review_required": human_review_required,
    }

    if progress_callback:
        await progress_callback("completed", 1.0)

    # v2: 异步入队给 AnnotationAgent 做独立校验
    # 注意: 不用 asyncio.create_task — 异步 worker 上下文中可能不被调度, 直接 await
    # Redis LPUSH 是 O(1) 操作, 不影响响应延迟
    await _enqueue_annotation(content_id, content_type, state, result)

    # 打印完整流水线
    print(f"\n{'='*70}")
    print(f"流水线完成: {pipeline.to_json()[:3000]}")
    print(f"{'='*70}\n")

    return response


async def _save_to_db(content_id, content_type, content, result, elapsed_ms):
    try:
        from sqlalchemy import text
        async with db_conn.async_session_factory() as session:
            if content_type == "text":
                content_preview = content.get("text", "")[:2000]
            elif content_type == "multi_modal":
                parts = []
                submitted_text = (content.get("text") or "").strip()
                if submitted_text:
                    parts.append(f"文本: {submitted_text[:1000]}")
                for file_info in content.get("files") or []:
                    filename = file_info.get("filename") or "未命名文件"
                    file_data = file_info.get("content")
                    file_size = len(file_data) if isinstance(file_data, bytes) else 0
                    parts.append(f"文件: {filename} ({file_size} bytes)")
                content_preview = "\n".join(parts)[:2000] or "[multi_modal: 无可用摘要]"
            else:
                size = 0
                for k in ["image", "audio", "video", "image_data", "audio_data", "video_data"]:
                    data = content.get(k)
                    if isinstance(data, bytes): size = len(data); break
                filename = content.get("filename") or "未命名文件"
                content_preview = f"[{content_type}] 文件: {filename} · {size} bytes"

            final_risk = result.get("final_risk") or {}
            import json as _json
            # v3.3: 提取分块/截断信息
            text_result = result.get("text_result") or {}
            is_chunked = text_result.get("is_chunked", False) or text_result.get("chunk_count", 0) > 0
            chunk_count = text_result.get("chunk_count", 0)
            is_truncated = (result.get("_fusion_result") or {}).get("is_truncated", False) or is_chunked

            # v3.4/R22: 信号卡压缩 + 多模态增强实义字段（真实取值，非 mock）
            fusion = result.get("_fusion_result") or {}
            compression_used = result.get("compression_used", False) or fusion.get("compression_used", False)
            signal_card_count = int(fusion.get("signal_card_count", 0) or 0)
            speaker_count = int((result.get("audio_result") or {}).get("speaker_count", 0) or 0)
            cross_modal = result.get("_cross_modal_analysis") or {}
            cross_modal_fusion = _json.dumps(cross_modal, ensure_ascii=False) if cross_modal else None

            await session.execute(text("""
                INSERT INTO moderation_records
                (content_id, content_type, content_preview, account_id,
                 final_decision, risk_score, violation_types, violation_details,
                 suggestions, processing_time_ms, agent_reasoning, debate_info,
                 status, progress, chunk_count, truncated,
                 compression_used, signal_card_count, speaker_count, cross_modal_fusion)
                VALUES (:cid, :ctype, :cpreview, :aid,
                        :decision, :risk, :vtypes, :vdetails,
                        :suggestions, :ptime, :reasoning, :debate,
                        'COMPLETED', 1.0, :chunk_count, :truncated,
                        :compression_used, :signal_card_count, :speaker_count, :cross_modal_fusion)
            """), {
                "cid": content_id, "ctype": content_type,
                "cpreview": content_preview, "aid": None,
                "decision": result.get("final_decision", "UNKNOWN"),
                "risk": final_risk.get("overall_score", 0.0),
                "vtypes": _json.dumps(final_risk.get("violation_types", []), ensure_ascii=False),
                "vdetails": _json.dumps(final_risk, ensure_ascii=False),
                "suggestions": _json.dumps(final_risk.get("suggestions", []), ensure_ascii=False),
                "ptime": elapsed_ms,
                "reasoning": _json.dumps(result.get("agent_reasoning"), ensure_ascii=False) if result.get("agent_reasoning") else None,
                "debate": _json.dumps(result.get("debate_info"), ensure_ascii=False) if result.get("debate_info") else None,
                "chunk_count": chunk_count,
                "truncated": is_truncated,
                "compression_used": compression_used,
                "signal_card_count": signal_card_count,
                "speaker_count": speaker_count,
                "cross_modal_fusion": cross_modal_fusion,
            })
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to save moderation record: {e}")


# === 端点 ===
@router.post("/moderate/text", response_model=ModerationResponse)
async def moderate_text(request: TextModerationRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text content is empty")
    result = await _run_moderation("text", {"text": request.text}, request.account_id)
    return ModerationResponse(**result)


@router.post("/moderate/image", response_model=ModerationResponse)
async def moderate_image(file: UploadFile = File(...), account_id: Optional[str] = Form(None)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    image_data = await file.read()
    if not image_data:
        raise HTTPException(status_code=400, detail="Image file is empty")
    result = await _run_moderation("image", {"image": image_data, "filename": file.filename}, account_id)
    return ModerationResponse(**result)


@router.post("/moderate/audio", response_model=ModerationResponse)
async def moderate_audio(file: UploadFile = File(...), account_id: Optional[str] = Form(None)):
    audio_data = await file.read()
    if not audio_data:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    result = await _run_moderation("audio", {"audio": audio_data, "filename": file.filename}, account_id)
    return ModerationResponse(**result)


@router.post("/moderate/video", response_model=ModerationResponse)
async def moderate_video(file: UploadFile = File(...), account_id: Optional[str] = Form(None)):
    video_data = await file.read()
    if not video_data:
        raise HTTPException(status_code=400, detail="Video file is empty")
    if len(video_data) > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Video file too large (max 100MB)")
    result = await _run_moderation("video", {"video": video_data, "filename": file.filename}, account_id)
    return ModerationResponse(**result)


# === 全模态审核 (文本 + 多文件) ===

@router.post("/moderate/multi-modal", response_model=ModerationResponse)
async def moderate_multi_modal(
    text: str = Form(""),
    account_id: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
):
    """
    全模态审核: 支持文本 + 多文件 (PDF/Word/TXT/图片)
    """
    from agent_moderation.parsers import extract_text_from_pdf, extract_text_from_docx, extract_text_from_txt

    content: dict = {
        "text": text.strip() if text else "",
        "files": [],
        "_multi_modal": True,
    }

    for file in files:
        file_bytes = await file.read()
        if not file_bytes:
            continue

        mime = file.content_type or "application/octet-stream"
        content["files"].append({
            "filename": file.filename or "unknown",
            "content": file_bytes,
            "mime_type": mime,
        })
        logger.info(f"Multi-modal: received file {file.filename}, type={mime}, size={len(file_bytes)}")

    if not text.strip() and not content["files"]:
        raise HTTPException(status_code=400, detail="请提供文本内容或上传文件")

    logger.info(f"Multi-modal moderation: text={len(text)} chars, {len(content['files'])} files")
    result = await _run_moderation("multi_modal", content, account_id)
    return ModerationResponse(**result)


# === Human-in-the-Loop Resume ===

class HumanReviewRequest(BaseModel):
    decision: str       # "PASS" / "REJECT" / "REVIEW"
    reason: str = ""    # 人工判定理由
    reviewer_id: str = "human_reviewer"
    violation_type: str = ""  # 人工判定的违规类型（可选）


@router.post("/moderate/{content_id}/review")
async def resume_after_human_review(content_id: str, review: HumanReviewRequest):
    """
    恢复被 Human-in-the-Loop 中断的工作流

    当工作流在 human_in_loop 节点被 interrupt() 暂停后,
    人工审核员通过此端点提交判定结果,工作流继续执行到 Risk → END
    """
    from langgraph.types import Command

    workflow = get_workflow()
    config = {"configurable": {"thread_id": content_id}}

    # 尝试获取当前工作流状态确认是否在等待人工审核
    waiting_for_human = False
    try:
        current_state = workflow.get_state(config)
        waiting_for_human = bool(current_state.next) and "human_in_loop" in current_state.next
        if not waiting_for_human and current_state.next:
            logger.warning(f"Workflow {content_id} is not waiting for human review (next: {current_state.next})")
    except Exception as e:
        logger.warning(f"Could not check workflow state for {content_id}: {e}")

    # 构建人工判定
    human_decision = {
        "decision": review.decision,
        "reason": review.reason,
        "reviewer_id": review.reviewer_id,
        "violation_type": review.violation_type,
    }

    logger.info(f"Resuming workflow {content_id} with human decision: {review.decision}")

    try:
        if waiting_for_human:
            result = await workflow.ainvoke(
                Command(resume=human_decision),
                config,
            )
        else:
            # R8·E4 降级：async 模式 langgraph 无 interrupt（版本限制），工作流已 REVIEW 结束。
            # 直接落地人工结果，保证人工提交始终有响应、annotation 入库。
            logger.info(f"[HITL] 工作流已结束（async 无 interrupt），人工结果直接落地: {review.decision}")
            result = {
                "content_id": content_id,
                "final_decision": review.decision,
                "final_risk": {
                    "overall_score": 0.0,
                    "violation_types": [review.violation_type] if review.violation_type else [],
                    "decision": review.decision,
                },
            }

        final_risk = result.get("final_risk") or {}
        response_data = {
            "content_id": content_id,
            "final_decision": result.get("final_decision", "UNKNOWN"),
            "risk_score": final_risk.get("overall_score", 0.0),
            "violation_types": final_risk.get("violation_types", []),
            "violation_details": final_risk,
            "suggestions": final_risk.get("suggestions", []),
            "human_decision": human_decision,
        }

        # LLM-as-Judge: 自动比较 AI 判定 vs 人工判定
        try:
            from evaluation.moderation_judge import get_judge
            judge = get_judge()
            ai_prediction = {
                "violation_type": (final_risk.get("violation_types") or ["none"])[0],
                "decision": final_risk.get("decision") or result.get("final_decision", "PASS"),
                "confidence": final_risk.get("overall_score", 0),
            }
            ground_truth = {
                "violation_type": review.violation_type or "none",
                "decision": review.decision,
            }
            judge_result = judge.judge(content_id, ai_prediction, ground_truth)
            response_data["llm_judge"] = {
                "is_correct": judge_result.is_correct,
                "error_type": judge_result.error_type,
                "analysis": judge_result.analysis,
            }
            # 将评估结果也反馈到 FeedbackLoop
            if not judge_result.is_correct:
                from optimization.prompt_optimizer import get_feedback_loop
                fb = get_feedback_loop()
                fb.collect_feedback({
                    "prompt_name": "text_moderation",
                    "content": content_id,
                    "actual_decision": ai_prediction["decision"],
                    "expected_decision": review.decision,
                    "error_type": judge_result.error_type,
                })
                logger.info(f"LLM-as-Judge: AI vs Human mismatch → {judge_result.error_type}")
        except Exception as e:
            logger.warning(f"LLM-as-Judge auto-eval failed (non-blocking): {e}")

        # v3.2: 将人工标注写入 annotation_records (统一存储, source=human, weight=3.0)
        asyncio.create_task(_save_human_annotation(content_id, review, result))

        # R21: HITL 恢复尾日志 — 在原有 pipeline 日志上追加人工判定步骤（保证可归因可分析）
        await _append_human_resume_log(content_id, review, response_data)

        # 从待审核队列移除
        await _remove_pending_review(content_id)

        return response_data
    except Exception as e:
        logger.error(f"Failed to resume workflow {content_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume workflow: {str(e)}")


async def _append_human_resume_log(content_id: str, review: HumanReviewRequest, response_data: dict):
    """R21: HITL 恢复尾日志 — 在原 pipeline 日志末尾追加人工判定步骤。

    复用 common.logger.append_pipeline_tail（读取原记录 → 追加步骤 → 写回 Redis，
    不覆盖原始链路）。保证同一 content_id 的日志完整可归因。
    """
    from common.logger import append_pipeline_tail
    ok = await append_pipeline_tail(
        content_id, "👤 HUMAN_RESUME",
        f"人工恢复工作流: decision={review.decision}, reviewer={review.reviewer_id}",
        output_data={
            "human_decision": review.decision,
            "reviewer_id": review.reviewer_id,
            "reason": (review.reason or "")[:200],
            "violation_type": review.violation_type,
            "final_decision": response_data.get("final_decision"),
            "llm_judge_is_correct": (response_data.get("llm_judge") or {}).get("is_correct"),
        },
    )
    if ok:
        logger.info(f"[HITL] 恢复日志已追加: {content_id} → {review.decision}")


# === Human Review Queue ===

@router.get("/moderate/pending-reviews")
async def list_pending_reviews():
    """
    列出所有等待人工审核的内容 (v3.2 增强: 包含 AI 推理数据)

    返回每个待审核项的:
    - 基本信息: content_id, content_type, text_preview, risk_score
    - AI推理: agent_reasoning (各Agent的完整推理链), debate_info
    - 触发原因: reason
    - 审核状态: 是否已被标注
    """
    pending = []
    try:
        import json as _json
        from memory.redis_service import get_redis_service
        from sqlalchemy import text
        from db import connection as db_conn

        svc = get_redis_service()
        if svc.client:
            # 获取所有 pending review keys
            keys = await svc.client.keys("pending_review:*")
            content_ids = []
            for key in keys:
                data = await svc.client.hgetall(key)
                if data:
                    item = {}
                    for k, v in data.items():
                        k_str = k.decode() if isinstance(k, bytes) else k
                        v_str = v.decode() if isinstance(v, bytes) else v
                        if k_str in ("violation_types",):
                            try:
                                item[k_str] = _json.loads(v_str)
                            except Exception:
                                item[k_str] = [v_str]
                        elif k_str == "risk_score":
                            item[k_str] = float(v_str)
                        else:
                            item[k_str] = v_str
                    cid = key.decode().split(":", 1)[1] if isinstance(key, bytes) else key.split(":", 1)[1]
                    item["content_id"] = cid
                    content_ids.append(cid)
                    pending.append(item)

        # v3.2: 从 PostgreSQL 补充 AI 推理数据
        if content_ids:
            try:
                async with db_conn.async_session_factory() as session:
                    result = await session.execute(text("""
                        SELECT content_id, agent_reasoning, debate_info, violation_types
                        FROM moderation_records WHERE content_id = ANY(:cids)
                    """), {"cids": content_ids})
                    rows = {row.content_id: row for row in result.fetchall()}

                for item in pending:
                    cid = item.get("content_id")
                    if cid and cid in rows:
                        row = rows[cid]
                        # 补充 agent_reasoning
                        if row.agent_reasoning:
                            item["agent_reasoning"] = row.agent_reasoning if isinstance(row.agent_reasoning, dict) else {}
                        # 补充 debate_info
                        if row.debate_info:
                            item["debate_info"] = row.debate_info if isinstance(row.debate_info, dict) else {}
                        # AI 原始违规类型
                        if row.violation_types:
                            item["ai_violation_types"] = row.violation_types if isinstance(row.violation_types, list) else []

                # 查询是否已被人工标注过
                async with db_conn.async_session_factory() as session2:
                    ann_result = await session2.execute(text("""
                        SELECT content_id, source FROM annotation_records
                        WHERE content_id = ANY(:cids) AND source = 'human'
                    """), {"cids": content_ids})
                    annotated = {row.content_id: row.source for row in ann_result.fetchall()}
                    for item in pending:
                        cid = item.get("content_id")
                        if cid in annotated:
                            item["annotation_status"] = "reviewed"
                            item["annotation_source"] = annotated[cid]
                        else:
                            item["annotation_status"] = "pending"
            except Exception as e:
                logger.warning(f"Failed to enrich pending reviews with reasoning: {e}")
    except Exception as e:
        logger.warning(f"Failed to list pending reviews: {e}")

    return {"total": len(pending), "items": pending}


async def _register_pending_review(content_id: str, state: dict):
    """在 Redis 中注册待人工审核项"""
    try:
        from memory.redis_service import get_redis_service
        import json as _json
        svc = get_redis_service()
        if svc.client:
            content = state.get("content") or {}
            final_risk = state.get("final_risk") or {}
            review_data = {
                "content_type": state.get("content_type", "text"),
                "text_preview": content.get("text", "")[:200],
                "risk_score": str(final_risk.get("overall_score", 0)),
                "violation_types": _json.dumps(final_risk.get("violation_types", [])),
                "reason": (state.get("_human_review") or {}).get("reason", "需要人工审核"),
                "created_at": str(int(__import__("time").time())),
            }
            await svc.client.hset(f"pending_review:{content_id}", mapping=review_data)
            await svc.client.expire(f"pending_review:{content_id}", 86400)  # 24h TTL
    except Exception as e:
        logger.warning(f"Failed to register pending review: {e}")


async def _remove_pending_review(content_id: str):
    """人工审核完成后从队列中移除"""
    try:
        from memory.redis_service import get_redis_service
        svc = get_redis_service()
        if svc.client:
            await svc.client.delete(f"pending_review:{content_id}")
    except Exception as e:
        logger.warning(f"Failed to remove pending review: {e}")


async def _save_human_annotation(content_id: str, review, ai_result: dict):
    """
    v3.2: 将人工审核结果写入 annotation_records (与自动标注统一存储)
    source='human', weight=3.0
    """
    try:
        import json as _json
        from sqlalchemy import text
        from db import connection as db_conn

        final_risk = ai_result.get("final_risk") or {}
        # AI 原始判定 (人工审核前)
        ai_decision = ai_result.get("final_decision", "PASS")
        ai_vtypes = final_risk.get("violation_types", [])
        # 人工判定
        human_decision = review.decision
        human_vtype = review.violation_type or "none"

        # 判断 AI 是否错误
        is_error = False
        error_type = "correct"
        if human_decision != ai_decision:
            is_error = True
            if human_decision in ("REJECT", "REVIEW") and ai_decision == "PASS":
                error_type = "false_negative"
            elif human_decision == "PASS" and ai_decision in ("REJECT", "REVIEW"):
                error_type = "false_positive"
            else:
                error_type = "wrong_violation_type"
        elif human_vtype not in ai_vtypes and human_vtype != "none":
            error_type = "wrong_violation_type"
            is_error = True

        # 构建人工修正后的 JSON 输出
        human_corrected = {
            "violation_type": human_vtype,
            "confidence": 1.0,
            "reason": review.reason,
            "decision": human_decision,
        }

        async with db_conn.async_session_factory() as session:
            await session.execute(text("""
                INSERT INTO annotation_records
                (content_id, content_type, model_decision, model_confidence,
                 model_violation_types, model_reason, model_risk_score,
                 is_error, error_type, error_detail,
                 annotated_violation_types, annotated_confidence,
                 source, weight, reviewer_id, human_corrected_json)
                VALUES (:cid, 'text', :mdec, :mconf,
                        :mvtypes, :mreason, :mrisk,
                        :iserr, :etype, :edetail,
                        :avtypes, :aconf,
                        'human', 3.0, :rid, :hcorrected)
                ON CONFLICT (content_id) DO UPDATE SET
                    is_error = EXCLUDED.is_error,
                    error_type = EXCLUDED.error_type,
                    error_detail = EXCLUDED.error_detail,
                    annotated_violation_types = EXCLUDED.annotated_violation_types,
                    annotated_confidence = EXCLUDED.annotated_confidence,
                    -- 人工标注不覆盖
                    source = 'human',
                    weight = 3.0,
                    reviewer_id = EXCLUDED.reviewer_id,
                    human_corrected_json = EXCLUDED.human_corrected_json,
                    annotated_at = NOW()
            """), {
                "cid": content_id,
                "mdec": ai_decision,
                "mconf": final_risk.get("overall_score", 0.0),
                "mvtypes": _json.dumps(ai_vtypes, ensure_ascii=False),
                "mreason": "",
                "mrisk": final_risk.get("overall_score", 0.0),
                "iserr": is_error,
                "etype": error_type,
                "edetail": f"人工判定: {human_decision}/{human_vtype}, AI原判定: {ai_decision}/{ai_vtypes}",
                "avtypes": _json.dumps([human_vtype] if human_vtype != "none" else [], ensure_ascii=False),
                "aconf": 1.0,
                "rid": review.reviewer_id,
                "hcorrected": _json.dumps(human_corrected, ensure_ascii=False),
            })
            await session.commit()
            logger.info(f"[HumanAnnotation] Saved for {content_id}: source=human, error={error_type}")

        # 同时更新 moderation_records 中的人工判定
        async with db_conn.async_session_factory() as session:
            await session.execute(text("""
                UPDATE moderation_records
                SET final_decision = :dec,
                    violation_types = :vtypes,
                    updated_at = NOW()
                WHERE content_id = :cid
            """), {
                "dec": human_decision,
                "vtypes": _json.dumps([human_vtype] if human_vtype != "none" else [], ensure_ascii=False),
                "cid": content_id,
            })
            await session.commit()

    except Exception as e:
        logger.warning(f"[HumanAnnotation] Failed to save for {content_id} (non-blocking): {e}")


# === AnnotationAgent 异步入队 ===

def _clean_markup_text(text: str) -> str:
    """去除 FileAgent 生成的标记头: [用户输入文本], [文件: xxx] 等"""
    import re
    # 去除行首的标记: [用户输入文本], [文件: xxx], [音频文件], [图片文件]
    cleaned = re.sub(r'^\[(用户输入文本|文件:[^\]]+|音频文件|图片文件|视频文件)\][\n\r]*', '', text, flags=re.MULTILINE)
    return cleaned.strip()


def _extract_annotation_input(state: dict, content_type: str) -> str:
    """从审核状态中提取可供 AnnotationAgent 独立判断的文本

    覆盖所有 content_type, 确保异步全模态提交也能被标注:
      - text/image/audio/video: 单一模态
      - multi_modal: 全模态混合 (异步提交的文档+图片+音频+文本)
    """
    parts = []

    # 1. 提取文本内容 (text 类型 + multi_modal 类型的文本部分)
    content = state.get("content") or {}
    text = content.get("text", "")
    if text and text.strip():
        cleaned = _clean_markup_text(text)
        if cleaned:
            parts.append(cleaned[:2000])  # 取前 2000 字符

    # 2. 提取文件解析结果 (docx/pdf 中提取的文本)
    if content_type in ("multi_modal",) or content.get("files"):
        file_results = state.get("file_results") or {}
        extracted_text = file_results.get("extracted_text", "")
        if extracted_text and extracted_text.strip():
            cleaned = _clean_markup_text(extracted_text)
            if cleaned:
                parts.append(cleaned[:2000])

    # 3. 纯文本类型返回 (可能来自 FileAgent 处理后的注入文本)
    if content_type == "text":
        if parts:
            return " | ".join(parts)
        return ""

    # 4. 图片
    elif content_type == "image":
        image_result = state.get("image_result") or {}
        description = image_result.get("description", "")
        ocr_text = image_result.get("ocr_text", "")
        caption = image_result.get("caption", "")
        img_parts = [p for p in [description, ocr_text, caption] if p]
        if img_parts:
            parts.extend(img_parts)
        return " | ".join(parts) if parts else ""

    # 5. 音频
    elif content_type == "audio":
        audio_result = state.get("audio_result") or {}
        asr_text = audio_result.get("asr_text", "") or audio_result.get("transcribed_text", "")
        if asr_text and asr_text.strip():
            parts.append(asr_text.strip()[:2000])
        return " | ".join(parts) if parts else ""

    # 6. 视频
    elif content_type == "video":
        video_result = state.get("video_result") or {}
        frame_descs = video_result.get("frame_descriptions", [])
        asr_text = video_result.get("asr_text", "")
        if frame_descs:
            parts.extend(frame_descs[:3])  # 最多 3 个关键帧描述
        if asr_text and asr_text.strip():
            parts.append(asr_text.strip()[:1000])
        return " | ".join(parts) if parts else ""

    # 7. multi_modal — 全模态混合 (异步提交典型路径)
    elif content_type == "multi_modal":
        # 补充图片描述
        image_result = state.get("image_result") or {}
        if image_result:
            desc = image_result.get("description") or image_result.get("ocr_text", "")
            if desc and desc.strip():
                parts.append(f"[图片分析: {desc[:500]}]")

        # 补充音频转义
        audio_result = state.get("audio_result") or {}
        if audio_result:
            asr = audio_result.get("asr_text", "") or audio_result.get("transcribed_text", "")
            if asr and asr.strip():
                parts.append(f"[音频转义: {asr[:500]}]")

        # 补充融合结果中的跨模态分析
        fusion = state.get("_fusion_result") or {}
        if fusion:
            summary = fusion.get("summary", "")
            if summary and summary.strip():
                parts.append(f"[跨模态分析摘要: {summary[:500]}]")

        return " | ".join(parts) if parts else ""

    return ""


async def _enqueue_annotation(content_id: str, content_type: str, state: dict, result: dict):
    """审核完成后, 异步将结果入队给 AnnotationAgent (非阻塞)"""
    try:
        from optimization.annotation_queue import enqueue_annotation

        final_risk = result.get("final_risk") or {}
        annotation_input = _extract_annotation_input(state, content_type)

        # 跳过空输入或全占位符 (如整段只有 [图片内容] 或 [音频内容])
        if not annotation_input:
            logger.debug(f"[Annotation] Skip {content_id}: empty annotation_input for {content_type}")
            return
        if annotation_input in ("[图片内容]", "[音频内容]", "[视频内容]"):
            logger.debug(f"[Annotation] Skip {content_id}: placeholder-only input for {content_type}")
            return

        item = {
            "content_id": content_id,
            "content_type": content_type,
            "annotation_input": annotation_input,
            "model_decision": result.get("final_decision", "UNKNOWN"),
            "model_confidence": final_risk.get("overall_score", 0),
            "model_violation_types": final_risk.get("violation_types", []),
            "model_reason": result.get("violation_details", {}).get("reason", ""),
            "model_risk_score": final_risk.get("overall_score", 0),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        await enqueue_annotation(item)
        logger.info(f"[Annotation] Enqueued {content_id} ({content_type})")
    except Exception as e:
        logger.warning(f"[Annotation] Enqueue failed for {content_id} (non-blocking): {e}")
