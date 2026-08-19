"""
WebSocket 实时推送 — 流式推送审核进度
"""
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agent_moderation.state import create_initial_state
from agent_moderation.workflows.moderation import get_workflow

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/moderation/{content_id}")
async def moderation_websocket(websocket: WebSocket, content_id: str):
    """WebSocket 端点 — 流式推送审核工作流进展"""
    await websocket.accept()
    logger.info(f"WebSocket connected: {content_id}")

    try:
        # 接收初始内容
        data = await websocket.receive_json()
        content_type = data.get("content_type", "text")
        content = data.get("content", {})

        # 创建初始状态
        state = create_initial_state(
            content_id=content_id,
            content_type=content_type,
            content=content,
            account_id=data.get("account_id"),
        )

        # 流式执行工作流
        workflow = get_workflow()
        config = {"configurable": {"thread_id": content_id}}

        async for event in workflow.astream(state, config):
            # 每个节点执行完推送事件
            for node_name, node_output in event.items():
                final_risk = node_output.get("final_risk") or {}
                await websocket.send_json({
                    "type": "NODE_COMPLETED",
                    "node": node_name,
                    "content_id": content_id,
                    "data": {
                        "current_step": node_name,
                        "decision": node_output.get("final_decision", ""),
                        "risk_score": final_risk.get("overall_score", 0.0),
                    },
                })

        # 最终结果推送
        await websocket.send_json({
            "type": "COMPLETED",
            "content_id": content_id,
            "message": "Moderation completed",
        })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {content_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "ERROR",
                "content_id": content_id,
                "error": str(e),
            })
        except Exception:
            pass
