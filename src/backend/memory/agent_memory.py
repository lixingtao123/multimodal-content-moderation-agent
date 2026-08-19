"""
Agent Memory v1.0 — MemGPT 风格三层次记忆管理

核心理念 (参考 MemGPT, Packer et al., 2024):
  - Agent 自主决定什么该记住、什么该遗忘
  - 三层记忆架构: 核心记忆 → 工作记忆 → 归档记忆
  - 重要性评分自动决定存储层级

三层记忆:
  1. Core Memory (核心记忆): 长期保留的关键知识
     - 存储: PostgreSQL
     - 内容: 高频违规特征、典型对抗模式、置信度阈值经验
     - TTL: 永久

  2. Working Memory (工作记忆): 当前审核会话的上下文
     - 存储: Redis (1h TTL)
     - 内容: 当前内容的多Agent判定、中间结果、RAG检索结果
     - TTL: 1小时

  3. Archival Memory (归档记忆): 压缩存储的历史经验
     - 存储: ChromaDB
     - 内容: 向量化的历史审核案例摘要
     - TTL: 永久 (可被检索但权重低)

技术参考:
  - MemGPT (Packer et al., NeurIPS 2024): 操作系统式LLM记忆管理
  - MemTrm (2024): 记忆Transformer用于长序列
  - LangChain Memory: ConversationSummaryMemory
"""
import json
import logging
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


class ImportanceCalculator:
    """
    重要性评分器

    评估记忆事件的重要性 (0.0 ~ 1.0):
    - 违规严重度: violence/porn/politics → 高重要性
    - 置信度: 高置信度 → 高重要性 (确定的经验)
    - 新颖度: 新出现的违规模式 → 高重要性
    - 频率: 反复出现的模式 → 高重要性
    """

    HIGH_IMPORTANCE_TYPES = {"violence", "porn", "politics", "illegal", "crime", "terrorism", "phishing"}
    MEDIUM_IMPORTANCE_TYPES = {"false_info", "harassment", "advertisement", "bulk_generation"}
    LOW_IMPORTANCE_TYPES = {"keyword_variant", "char_noise", "format_spoofing", "none"}

    @classmethod
    def calculate(
        cls,
        violation_type: str,
        confidence: float,
        risk_score: float,
        is_adversarial: bool = False,
        is_first_occurrence: bool = False,
        frequency: int = 0,
    ) -> float:
        """计算综合重要性"""
        score = 0.0

        # 违规类型严重度 (0.0 ~ 0.4)
        if violation_type in cls.HIGH_IMPORTANCE_TYPES:
            score += 0.4
        elif violation_type in cls.MEDIUM_IMPORTANCE_TYPES:
            score += 0.25
        elif violation_type in cls.LOW_IMPORTANCE_TYPES:
            score += 0.1

        # 置信度 (0.0 ~ 0.2)
        score += min(confidence * 0.2, 0.2)

        # 风险分 (0.0 ~ 0.15)
        score += min(risk_score * 0.15, 0.15)

        # 对抗样本加分 (0.15)
        if is_adversarial:
            score += 0.15

        # 首次出现加分 (0.05)
        if is_first_occurrence:
            score += 0.05

        # 频率加分 (0.05)
        if frequency >= 5:
            score += 0.05
        elif frequency >= 3:
            score += 0.03

        return round(min(score, 1.0), 4)


@dataclass
class MemoryEvent:
    """记忆事件"""
    event_id: str
    content_id: str
    event_type: str          # moderation / pattern / adversarial / correction
    violation_type: str
    decision: str
    risk_score: float
    confidence: float
    summary: str             # 压缩后的摘要
    importance: float        # 重要性评分
    metadata: Dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    access_count: int = 0    # 被检索次数


class CoreMemory:
    """
    核心记忆 — PostgreSQL 持久化存储

    存储内容:
    - 高重要性 (>0.7) 的审核决策
    - 屡次出现的违规模式 (>3次)
    - 对抗样本特征

    v3.8: 从内存 dict 改为 PostgreSQL 持久化存储, 进程重启数据不丢失
    """

    MAX_EVENTS = 100  # 核心记忆容量上限

    def __init__(self):
        self._events: Dict[str, MemoryEvent] = {}  # 本地缓存 (加速高频访问)
        self._db_initialized = False

    async def _ensure_db(self):
        """确保数据库表已创建"""
        if self._db_initialized:
            return True
        try:
            from db.connection import get_session_factory
            session_factory = get_session_factory()
            async with session_factory() as session:
                # 确保 core_memories 表存在（幂等 CREATE IF NOT EXISTS）
                await session.execute(
                    __import__('sqlalchemy').text("""
                        CREATE TABLE IF NOT EXISTS core_memories (
                            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                            event_id VARCHAR(128) NOT NULL UNIQUE,
                            content_id VARCHAR(64),
                            violation_type VARCHAR(32) NOT NULL DEFAULT 'none',
                            decision VARCHAR(16) NOT NULL DEFAULT 'PASS',
                            risk_score FLOAT DEFAULT 0.0,
                            confidence FLOAT DEFAULT 0.0,
                            importance FLOAT DEFAULT 0.0,
                            summary TEXT NOT NULL,
                            metadata JSONB DEFAULT '{}',
                            access_count INT DEFAULT 0,
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                )
                await session.commit()
            self._db_initialized = True
            return True
        except Exception as e:
            logger.warning(f"CoreMemory DB init failed, falling back to in-memory: {e}")
            return False

    async def store(self, event: MemoryEvent):
        """存储到核心记忆 (PostgreSQL + 本地缓存)"""
        if event.importance < 0.7:
            return  # 重要性不足，不进入核心记忆

        # 本地缓存
        self._events[event.event_id] = event
        # 精简 — 只保留最重要的 MAX_EVENTS 条
        if len(self._events) > self.MAX_EVENTS:
            sorted_events = sorted(
                self._events.values(),
                key=lambda e: (e.importance, e.access_count),
                reverse=True,
            )
            self._events = {e.event_id: e for e in sorted_events[:self.MAX_EVENTS]}

        # PostgreSQL 持久化
        if await self._ensure_db():
            try:
                from db.connection import get_session_factory
                import json as _json
                session_factory = get_session_factory()
                async with session_factory() as session:
                    await session.execute(
                        __import__('sqlalchemy').text("""
                            INSERT INTO core_memories (event_id, content_id, violation_type,
                                decision, risk_score, confidence, importance, summary, metadata)
                            VALUES (:event_id, :content_id, :violation_type, :decision,
                                :risk_score, :confidence, :importance, :summary, :metadata)
                            ON CONFLICT (event_id) DO UPDATE SET
                                importance = EXCLUDED.importance,
                                access_count = core_memories.access_count + 1,
                                metadata = EXCLUDED.metadata
                        """),
                        {
                            "event_id": event.event_id,
                            "content_id": event.content_id,
                            "violation_type": event.violation_type,
                            "decision": event.decision,
                            "risk_score": event.risk_score,
                            "confidence": event.confidence,
                            "importance": event.importance,
                            "summary": event.summary[:500],
                            "metadata": _json.dumps(event.metadata, ensure_ascii=False),
                        },
                    )
                    await session.commit()
            except Exception as e:
                logger.warning(f"CoreMemory PostgreSQL store failed: {e}")

        logger.info(f"CoreMemory: stored {event.event_id} (importance={event.importance:.2f})")

    async def recall(self, query_type: str, top_k: int = 5) -> List[MemoryEvent]:
        """从核心记忆检索相关事件 (本地缓存 + PostgreSQL)"""
        # 先从本地缓存查询
        results = []
        for event in self._events.values():
            if event.violation_type == query_type or query_type == "any":
                results.append(event)
                event.access_count += 1

        # 如果本地缓存不足，从 PostgreSQL 查询
        if len(results) < top_k and await self._ensure_db():
            try:
                from db.connection import get_session_factory
                import json as _json
                session_factory = get_session_factory()
                async with session_factory() as session:
                    if query_type == "any":
                        db_results = await session.execute(
                            __import__('sqlalchemy').text("""
                                SELECT event_id, content_id, violation_type, decision,
                                    risk_score, confidence, importance, summary, metadata
                                FROM core_memories
                                ORDER BY importance DESC, created_at DESC
                                LIMIT :top_k
                            """),
                            {"top_k": top_k},
                        )
                    else:
                        db_results = await session.execute(
                            __import__('sqlalchemy').text("""
                                SELECT event_id, content_id, violation_type, decision,
                                    risk_score, confidence, importance, summary, metadata
                                FROM core_memories
                                WHERE violation_type = :query_type
                                ORDER BY importance DESC, created_at DESC
                                LIMIT :top_k
                            """),
                            {"query_type": query_type, "top_k": top_k},
                        )
                    rows = db_results.fetchall()
                    for row in rows:
                        existing_ids = {e.event_id for e in results}
                        if row[0] not in existing_ids:
                            metadata = _json.loads(row[8]) if row[8] else {}
                            event = MemoryEvent(
                                event_id=row[0],
                                content_id=row[1] or "",
                                event_type="moderation",
                                violation_type=row[2],
                                decision=row[3],
                                risk_score=row[4] or 0.0,
                                confidence=row[5] or 0.0,
                                summary=row[7] or "",
                                importance=row[6] or 0.0,
                                metadata=metadata,
                            )
                            results.append(event)
                            # 同步到本地缓存
                            if len(self._events) < self.MAX_EVENTS:
                                self._events[event.event_id] = event
            except Exception as e:
                logger.warning(f"CoreMemory PostgreSQL recall failed: {e}")

        results.sort(key=lambda e: (e.importance, e.timestamp), reverse=True)
        return results[:top_k]

    def get_stats(self) -> Dict:
        return {
            "total_events": len(self._events),
            "high_importance": sum(1 for e in self._events.values() if e.importance >= 0.8),
            "avg_importance": round(
                sum(e.importance for e in self._events.values()) / max(len(self._events), 1), 4
            ),
            "persisted": self._db_initialized,
        }


class WorkingMemory:
    """
    工作记忆 — Redis 短期存储 (1h TTL)

    存储内容:
    - 当前审核会话的上下文
    - 多Agent中间结果
    - RAG检索结果
    - Debate/Reflexion 结论
    """

    def __init__(self, redis_service=None):
        self._redis = redis_service
        self._local: Dict[str, Dict] = {}

    async def store(self, key: str, value: Dict, ttl: int = 3600):
        """存储到工作记忆"""
        self._local[key] = {
            "value": value,
            "expires_at": time.time() + ttl,
        }
        if self._redis:
            try:
                await self._redis.save_short_term(key, value)
            except Exception as e:
                logger.warning(f"WorkingMemory Redis store failed: {e}")

    async def recall(self, key: str) -> Optional[Dict]:
        """从工作记忆读取"""
        # 先查本地
        if key in self._local:
            entry = self._local[key]
            if entry["expires_at"] > time.time():
                return entry["value"]
            del self._local[key]
        # 再查 Redis
        if self._redis:
            try:
                return await self._redis.get_short_term(key)
            except Exception:
                pass
        return None

    async def clear_expired(self):
        """清理过期条目"""
        now = time.time()
        expired = [k for k, v in self._local.items() if v["expires_at"] <= now]
        for k in expired:
            del self._local[k]


class ArchivalMemory:
    """
    归档记忆 — ChromaDB 向量存储

    存储内容:
    - 低重要性 (<0.7) 的审核记录
    - 压缩摘要 (max 200 chars)
    - 用于长期相似案例检索 (补充 RAG)
    """

    def __init__(self, chroma_service=None):
        self._chroma = chroma_service
        self._buffer: List[tuple] = []  # 批量写入缓冲

    async def store(self, event: MemoryEvent):
        """归档到 ChromaDB"""
        # 压缩摘要
        compressed_summary = self._compress(event.summary)
        self._buffer.append((
            event.event_id,
            compressed_summary,
            event.metadata,
        ))

        # 批量写入 (每10条或按需)
        if len(self._buffer) >= 10:
            await self._flush()

    async def _flush(self):
        """批量写入 ChromaDB"""
        if not self._buffer or not self._chroma:
            self._buffer = []
            return
        try:
            ids = [b[0] for b in self._buffer]
            docs = [b[1] for b in self._buffer]
            metadatas = [b[2] for b in self._buffer]

            self._chroma.collection.add(
                ids=ids,
                documents=docs,
                metadatas=metadatas,
            )
            logger.info(f"ArchivalMemory: flushed {len(self._buffer)} events")
            self._buffer = []
        except Exception as e:
            logger.warning(f"ArchivalMemory flush failed: {e}")

    async def recall(self, query: str, top_k: int = 5) -> List[Dict]:
        """从归档记忆搜索"""
        await self._flush()
        if self._chroma and self._chroma.collection:
            try:
                results = self._chroma.collection.query(
                    query_texts=[query],
                    n_results=top_k,
                )
                return [
                    {"id": rid, "content": rdoc, "score": 1.0 - rdist}
                    for rid, rdoc, rdist in zip(
                        results["ids"][0],
                        results["documents"][0],
                        results["distances"][0],
                    )
                ]
            except Exception as e:
                logger.warning(f"ArchivalMemory recall failed: {e}")
        return []

    def _compress(self, text: str, max_chars: int = 200) -> str:
        """压缩记忆文本"""
        if len(text) <= max_chars:
            return text
        # 简单截断 + 关键信息提取
        return text[:max_chars - 3] + "..."


class AgentMemory:
    """
    MemGPT 风格三层次记忆管理器

    Agent 自主决策:
    - importance > 0.7 → CoreMemory (长期)
    - 0.3 < importance <= 0.7 → WorkingMemory (短期)
    - importance <= 0.3 → ArchivalMemory (归档)

    recall(query) 按优先级: Core → Working → Archival
    """

    def __init__(self, redis_service=None, chroma_service=None):
        self.core = CoreMemory()
        self.working = WorkingMemory(redis_service)
        self.archival = ArchivalMemory(chroma_service)

    async def store(self, event: MemoryEvent):
        """自主决定存储层级"""
        if event.importance > 0.7:
            await self.core.store(event)
        elif event.importance > 0.3:
            await self.working.store(
                f"memory:{event.event_id}",
                {
                    "violation_type": event.violation_type,
                    "decision": event.decision,
                    "risk_score": event.risk_score,
                    "confidence": event.confidence,
                    "summary": event.summary,
                    "importance": event.importance,
                },
            )
        else:
            await self.archival.store(event)

    async def recall(self, query: str, top_k: int = 5) -> List[Dict]:
        """三层次回忆"""
        all_results = []

        # 1. Core Memory (优先)
        core_results = await self.core.recall("any", top_k=3)
        for e in core_results:
            all_results.append({
                "source": "core",
                "id": e.event_id,
                "content": e.summary,
                "score": e.importance,
                "violation_type": e.violation_type,
            })

        # 2. Working Memory — 遍历所有本地缓存条目, 匹配前缀
        if self.working:
            for stored_key, entry in list(self.working._local.items()):
                # 检查 TTL
                if entry["expires_at"] <= time.time():
                    del self.working._local[stored_key]
                    continue
                # 匹配 violation_type 或通用召回
                if query == "any" or query in str(entry.get("value", {}).get("violation_type", "")):
                    val = entry["value"]
                    all_results.append({
                        "source": "working",
                        "id": stored_key,
                        "content": val.get("summary", "")[:200],
                        "score": val.get("importance", 0.5),
                        "violation_type": val.get("violation_type", ""),
                    })

        # 3. Archival Memory
        archival_results = await self.archival.recall(query, top_k=5)
        for r in archival_results:
            all_results.append({
                "source": "archival",
                "id": r["id"],
                "content": r["content"],
                "score": r["score"] * 0.5,  # 归档权重减半
                "violation_type": r.get("violation_type", ""),
            })

        # 按 scores 排序
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:top_k]

    def get_stats(self) -> Dict:
        return {
            "core": self.core.get_stats(),
            "archival_buffer_size": len(self.archival._buffer),
        }

    async def flush(self):
        """确保所有缓冲数据写入"""
        await self.archival._flush()


# 全局单例
_agent_memory: Optional[AgentMemory] = None


def get_agent_memory(redis_service=None, chroma_service=None) -> AgentMemory:
    global _agent_memory
    if _agent_memory is None:
        _agent_memory = AgentMemory(redis_service, chroma_service)
    return _agent_memory
