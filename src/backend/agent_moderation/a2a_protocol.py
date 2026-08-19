"""
A2A Protocol v1.0 — Google Agent-to-Agent 通信协议

实现标准的 A2A (Agent-to-Agent) 协议:
  - Agent Card: 声明 Agent 能力、输入/输出格式
  - Task: 标准化的任务描述
  - Message: Agent 间消息格式
  - 可与外部 Agent 系统互操作

技术参考:
  - Google A2A Protocol (2025): Agent-to-Agent Communication
  - OpenAI Agents SDK (2025): Agent interoperability
  - Anthropic MCP (2024): Protocol-level integration
"""
import json
import uuid
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class TaskState(Enum):
    """A2A 任务状态"""
    PENDING = "pending"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageRole(Enum):
    """消息角色"""
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass
class AgentCard:
    """
    Agent 能力声明卡

    对标 Google A2A AgentCard
    """
    name: str                     # Agent 名称
    description: str              # 功能描述
    version: str = "1.0.0"
    url: str = ""                 # Agent 访问地址
    capabilities: List[str] = field(default_factory=list)  # 能力列表
    input_modes: List[str] = field(default_factory=list)   # text/image/audio/video
    output_modes: List[str] = field(default_factory=list)
    skills: List[Dict] = field(default_factory=list)       # [{name, description, inputSchema}]
    rate_limit: Dict = field(default_factory=dict)          # {max_concurrent, max_per_minute}
    provider: str = ""             # 供应商信息

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "url": self.url,
            "capabilities": self.capabilities,
            "inputModes": self.input_modes,
            "outputModes": self.output_modes,
            "skills": self.skills,
            "rateLimit": self.rate_limit,
            "provider": self.provider,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "AgentCard":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            url=data.get("url", ""),
            capabilities=data.get("capabilities", []),
            input_modes=data.get("inputModes", []),
            output_modes=data.get("outputModes", []),
            skills=data.get("skills", []),
            rate_limit=data.get("rateLimit", {}),
            provider=data.get("provider", ""),
        )


@dataclass
class A2ATask:
    """A2A 标准任务"""
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    state: TaskState = TaskState.PENDING
    assigned_agent: str = ""       # 分配的 Agent 名称
    input_data: Dict = field(default_factory=dict)
    output_data: Dict = field(default_factory=dict)
    context: Dict = field(default_factory=dict)  # 附加上下文
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "taskId": self.task_id,
            "title": self.title,
            "description": self.description,
            "state": self.state.value,
            "assignedAgent": self.assigned_agent,
            "input": self.input_data,
            "output": self.output_data,
            "context": self.context,
            "createdAt": self.created_at,
            "completedAt": self.completed_at,
            "error": self.error,
        }


@dataclass
class A2AMessage:
    """A2A 标准消息"""
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    role: MessageRole = MessageRole.AGENT
    content: str = ""
    task_id: Optional[str] = None
    sender_agent: str = ""         # 发送方 Agent 名称
    receiver_agent: str = ""       # 接收方 Agent 名称
    metadata: Dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return {
            "messageId": self.message_id,
            "role": self.role.value,
            "content": self.content,
            "taskId": self.task_id,
            "senderAgent": self.sender_agent,
            "receiverAgent": self.receiver_agent,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class A2ARegistry:
    """
    A2A Agent 注册中心

    管理所有可用的 Agent 及其能力声明
    """

    def __init__(self):
        self._agents: Dict[str, AgentCard] = {}
        self._tasks: Dict[str, A2ATask] = {}
        self._messages: List[A2AMessage] = []

    def register_agent(self, card: AgentCard):
        """注册 Agent"""
        self._agents[card.name] = card
        logger.info(f"A2A: registered agent '{card.name}' with {len(card.skills)} skills")

    def get_agent_card(self, name: str) -> Optional[AgentCard]:
        """获取 Agent 能力声明"""
        return self._agents.get(name)

    def list_agents(self) -> List[Dict]:
        """列出所有注册的 Agent"""
        return [card.to_dict() for card in self._agents.values()]

    def create_task(self, title: str, description: str,
                    assigned_agent: str, input_data: Dict = None,
                    context: Dict = None) -> A2ATask:
        """创建任务并分配 Agent"""
        task = A2ATask(
            title=title,
            description=description,
            assigned_agent=assigned_agent,
            input_data=input_data or {},
            context=context or {},
        )
        self._tasks[task.task_id] = task
        logger.info(f"A2A: created task '{task.task_id}' → {assigned_agent}")
        return task

    def update_task(self, task_id: str, state: TaskState = None,
                    output_data: Dict = None, error: str = None):
        """更新任务状态"""
        task = self._tasks.get(task_id)
        if task:
            if state:
                task.state = state
            if output_data:
                task.output_data = output_data
            if error:
                task.error = error
            if state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                task.completed_at = datetime.now().isoformat()

    def get_task(self, task_id: str) -> Optional[A2ATask]:
        return self._tasks.get(task_id)

    def send_message(self, content: str, sender: str, receiver: str,
                     task_id: str = None, metadata: Dict = None) -> A2AMessage:
        """Agent 间发送消息"""
        msg = A2AMessage(
            content=content,
            sender_agent=sender,
            receiver_agent=receiver,
            task_id=task_id,
            metadata=metadata or {},
        )
        self._messages.append(msg)
        logger.info(f"A2A: message {sender} → {receiver}: {content[:80]}")
        return msg

    def get_messages(self, task_id: str = None, agent_name: str = None) -> List[Dict]:
        """查询消息历史"""
        msgs = self._messages
        if task_id:
            msgs = [m for m in msgs if m.task_id == task_id]
        if agent_name:
            msgs = [m for m in msgs if m.sender_agent == agent_name or m.receiver_agent == agent_name]
        return [m.to_dict() for m in msgs[-100:]]  # 最近100条

    def get_stats(self) -> Dict:
        return {
            "registered_agents": len(self._agents),
            "active_tasks": sum(1 for t in self._tasks.values() if t.state in (TaskState.PENDING, TaskState.WORKING)),
            "completed_tasks": sum(1 for t in self._tasks.values() if t.state == TaskState.COMPLETED),
            "total_messages": len(self._messages),
        }


def create_default_agent_cards() -> List[AgentCard]:
    """创建默认的 Agent 能力声明卡"""
    return [
        AgentCard(
            name="text-moderation-agent",
            description="文本内容审核 — DeepSeek V4 Flash 驱动",
            version="3.1.0",
            capabilities=["text_moderation", "semantic_analysis", "adversarial_detection"],
            input_modes=["text"],
            output_modes=["text"],
            skills=[
                {"name": "keyword_check", "description": "AC自动机敏感词检测"},
                {"name": "deep_analysis", "description": "DeepSeek API深层语义分析"},
                {"name": "history_search", "description": "ChromaDB历史案例检索"},
            ],
            rate_limit={"max_concurrent": 10, "max_per_minute": 100},
            provider="internal",
        ),
        AgentCard(
            name="image-moderation-agent",
            description="图片内容审核 — Qwen3-VL 视觉 + DeepSeek 分类",
            version="2.1.0",
            capabilities=["image_moderation", "ocr_extraction", "visual_analysis", "dhash_dedup"],
            input_modes=["image"],
            output_modes=["text"],
            skills=[
                {"name": "vl_extract", "description": "Qwen3-VL多维度视觉特征提取"},
                {"name": "image_hash", "description": "dHash感知哈希相似图检测"},
                {"name": "text_classify", "description": "OCR+描述→DeepSeek文本分类"},
            ],
            rate_limit={"max_concurrent": 5, "max_per_minute": 50},
            provider="internal",
        ),
        AgentCard(
            name="risk-assessment-agent",
            description="综合风险评估 — 多模态融合评分",
            version="2.0.0",
            capabilities=["risk_scoring", "decision_making", "force_escalation"],
            input_modes=["text"],
            output_modes=["text"],
            skills=[
                {"name": "multi_modal_fusion", "description": "多模态风险分量加权融合"},
                {"name": "force_escalation", "description": "违规类型强制升级规则"},
                {"name": "suggestion_gen", "description": "修复建议生成"},
            ],
            rate_limit={"max_concurrent": 20, "max_per_minute": 200},
            provider="internal",
        ),
        AgentCard(
            name="debate-panel",
            description="多Agent辩论协作 — 4种辩论模式",
            version="1.0.0",
            capabilities=["multi_agent_debate", "consensus_seeking", "escalation"],
            input_modes=["text"],
            output_modes=["text"],
            skills=[
                {"name": "majority_vote", "description": "多数投票模式"},
                {"name": "weighted_vote", "description": "加权投票(模态权重+违规严重度)"},
                {"name": "consensus", "description": "共识模式(80%共识阈值)"},
                {"name": "escalate", "description": "升级人工(≥3种分歧)"},
            ],
            rate_limit={"max_concurrent": 10, "max_per_minute": 100},
            provider="internal",
        ),
    ]


# 全局单例
_a2a_registry: Optional[A2ARegistry] = None


def get_a2a_registry() -> A2ARegistry:
    global _a2a_registry
    if _a2a_registry is None:
        _a2a_registry = A2ARegistry()
        # 注册默认 Agent
        for card in create_default_agent_cards():
            _a2a_registry.register_agent(card)
    return _a2a_registry
