"""
Supervisor Agent — 总控调度，识别内容类型并分发到对应 Agent
"""
import time
from agent_moderation.state import ModerationState
from agent_moderation.agents.base import BaseAgent
from memory.manager import get_memory_manager


class SupervisorAgent(BaseAgent):
    """总控调度 Agent"""

    def __init__(self):
        super().__init__("supervisor")
        self.memory = get_memory_manager()

    async def process(self, state: ModerationState) -> ModerationState:
        """
        1. 识别内容类型
        2. 记录任务开始
        3. 分发到下游 Agent
        """
        content = state.get("content", {})
        content_type = state.get("content_type", "")

        # 自动识别内容类型（如果未指定）
        if not content_type:
            content_type = self._identify_content_type(content)
            state["content_type"] = content_type

        self.log_step(f"Processing {content_type} content, content_id={state['content_id']}")

        # 记录到短期记忆
        content_preview = self._get_preview(content, content_type)
        await self.memory.start_task(
            state["content_id"],
            content_type,
            content_preview,
        )

        state["start_time"] = time.time()
        return state

    def _identify_content_type(self, content: dict) -> str:
        """智能识别内容类型"""
        # 全模态 (文件 + 文本)
        if content.get("files") or content.get("_multi_modal"):
            return "multi_modal"
        if "text" in content:
            return "text"
        elif "image" in content or "image_data" in content:
            return "image"
        elif "audio" in content or "audio_data" in content:
            return "audio"
        elif "video" in content or "video_data" in content:
            return "video"
        return "unknown"

    def _get_preview(self, content: dict, content_type: str) -> str:
        """获取内容摘要"""
        if content_type == "text":
            text = content.get("text", "")
            return text[:200] + "..." if len(text) > 200 else text
        elif content_type == "image":
            return f"[image: {len(content.get('image', b''))} bytes]"
        elif content_type == "audio":
            return f"[audio: {len(content.get('audio', b''))} bytes]"
        elif content_type == "video":
            return f"[video: {len(content.get('video', b''))} bytes]"
        return "[unknown]"
