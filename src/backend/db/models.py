"""
SQLAlchemy ORM 模型
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, JSON, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class ModerationRecord(Base):
    __tablename__ = "moderation_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_id = Column(String(64), unique=True, nullable=False, index=True)
    content_type = Column(String(32), nullable=False)
    content_hash = Column(String(64), nullable=True)
    content_preview = Column(Text, nullable=True)
    account_id = Column(String(64), nullable=True, index=True)
    final_decision = Column(String(16), nullable=False, index=True)  # PASS / REVIEW / REJECT
    risk_score = Column(Float, nullable=False, default=0.0)
    violation_types = Column(JSON, default=[])
    violation_details = Column(JSON, default={})
    suggestions = Column(JSON, default=[])
    processing_time_ms = Column(Float, default=0.0)
    agent_reasoning = Column(JSON, default=None)  # AI 推理过程
    debate_info = Column(JSON, default=None)      # 辩论信息
    # v3.3: 异步任务支持
    status = Column(String(32), default='COMPLETED', index=True)  # QUEUED / PROCESSING / COMPLETED / FAILED
    progress = Column(Float, default=1.0)
    chunk_count = Column(Integer, default=0)
    truncated = Column(Boolean, default=False)
    error_message = Column(Text, default=None)
    # v3.4: 信号卡压缩 + 多模态增强
    compression_used = Column(Boolean, default=False)
    signal_card_count = Column(Integer, default=0)
    speaker_count = Column(Integer, default=0)
    cross_modal_fusion = Column(JSON, default=None)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class BlackhatPattern(Base):
    __tablename__ = "blackhat_patterns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pattern_type = Column(String(64), nullable=False, index=True)
    pattern_name = Column(String(128), nullable=False)
    pattern_data = Column(JSON, nullable=False)
    risk_level = Column(Integer, default=1)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class AccountProfile(Base):
    __tablename__ = "account_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(String(64), unique=True, nullable=False)
    risk_score = Column(Float, default=0.0)
    violation_count = Column(Integer, default=0)
    last_violation_at = Column(DateTime, nullable=True)
    detected_patterns = Column(JSON, default=[])
    behavior_features = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    moderation_id = Column(UUID(as_uuid=True), ForeignKey("moderation_records.id"), nullable=True)
    action_type = Column(String(32), nullable=False)
    action_data = Column(JSON, default={})
    operator_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


class AnnotationRecord(Base):
    """人工/自动标注记录（R3·L3，F4 修复）

    收并集列：对齐现有 4 处硬编码 SQL（hard_case_miner / 人工标注 / 优化 agent）
    的所有引用列，使 ORM 建表后可被现有 SQL 直接使用。
    """
    __tablename__ = "annotation_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_id = Column(String(128), unique=True, nullable=False, index=True)
    content_type = Column(String(32), default="text")
    # —— 模型原始输出 ——
    annotation_input = Column(Text, nullable=True)  # 待标注原文
    model_decision = Column(String(16), nullable=True)
    model_confidence = Column(Float, nullable=True)
    model_violation_types = Column(JSON, default=[])
    model_reason = Column(Text, nullable=True)
    model_risk_score = Column(Float, nullable=True)
    # —— hard_case_miner 专用（ai_* 三件套）——
    ai_violation_type = Column(String(32), nullable=True)
    ai_decision = Column(String(16), nullable=True)
    ai_confidence = Column(Float, nullable=True)
    annotation_status = Column(String(16), default="PENDING", index=True)  # PENDING/REVIEWED
    priority = Column(String(16), nullable=True)
    meta_info = Column(JSON, default={})
    # —— 标注结果 ——
    is_error = Column(Boolean, default=False, index=True)  # 是否标注为误判
    error_type = Column(String(64), nullable=True)
    error_detail = Column(Text, nullable=True)
    # —— 优化 agent 规则/LLM 复核视角 ——
    rule_verdict = Column(String(32), nullable=True)
    rule_detail = Column(Text, nullable=True)
    llm_verdict = Column(String(32), nullable=True)
    llm_reason = Column(Text, nullable=True)
    llm_called = Column(Boolean, default=False)
    contradiction_flag = Column(Boolean, default=False)
    rule_matched_keywords = Column(JSON, default=[])
    rule_matched_rules = Column(JSON, default=[])
    rule_whitelist_hit = Column(Boolean, default=False)
    rule_adversarial_hit = Column(Boolean, default=False)
    # —— 人工标注 ——
    annotated_violation_types = Column(JSON, default=[])
    annotated_confidence = Column(Float, nullable=True)
    source = Column(String(32), default="auto", index=True)  # human/auto/hard_case
    weight = Column(Float, default=1.0)  # human=3.0（权重更大）
    reviewer_id = Column(String(64), nullable=True)
    human_corrected_json = Column(JSON, default=None)
    # —— 优化消费标记（R22: 与 schema.sql/annotation_queue.py 对齐）——
    # FALSE=活跃错误(参与计数), TRUE=已被优化消费(不再计数)
    consumed = Column(Boolean, default=False, index=True)
    optimization_id = Column(String(64), nullable=True)
    # —— 元信息 ——
    processing_time_ms = Column(Float, nullable=True)
    annotated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class DatasetSample(Base):
    """数据集样本登记表（R3·L3，D1 配套）

    OutSafe 真实样本入库后在此登记，供评测系统（T1-T7）读取与抽样，
    与 RAG 案例库（Chroma）解耦。ground_truth 区分标注来源。
    """
    __tablename__ = "dataset_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sample_id = Column(String(128), unique=True, nullable=False, index=True)  # OutSafe 样本 id
    category = Column(String(128), nullable=True)  # OutSafe 目录名
    violation_type = Column(String(32), nullable=True, index=True)  # 13 类枚举
    modality = Column(String(16), nullable=True)  # text/image/video/audio
    language = Column(String(8), nullable=True)  # zh/en
    content_preview = Column(Text, nullable=True)
    path = Column(String(512), nullable=True)  # 模态文件路径
    ground_truth = Column(String(32), default="confirmed")  # confirmed/model_labeled
    source_dataset = Column(String(32), default="out_safe")  # out_safe/simulated/production
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


class ModerationPolicy(Base):
    """审核策略配置表（R22: 补齐 ORM 模型，对齐 schema.sql）

    运营人员可界面化配置审核规则、阈值、违规类型，无需改代码重新部署。
    policy_type: keyword / regex / sensitivity / threshold / model_route
    """
    __tablename__ = "moderation_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), unique=True, nullable=False)
    policy_type = Column(String(32), nullable=False, default="keyword", index=True)
    description = Column(Text, default="")
    rule_config = Column(JSON, nullable=False, default={})
    enabled = Column(Boolean, default=True, index=True)
    priority = Column(Integer, default=5)  # 1(min)~10(max), 高优先级先匹配
    created_by = Column(String(64), default="system")
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class CoreMemory(Base):
    """Agent 核心记忆表（R22: 补齐 ORM 模型，对齐 schema.sql）

    MemGPT 风格三层记忆体系 — Core Memory。
    存储高重要性(>0.7)的审核案例，用于 Agent 长期决策参考。
    """
    __tablename__ = "core_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String(128), unique=True, nullable=False)
    content_id = Column(String(64), nullable=True)
    violation_type = Column(String(32), nullable=False, default="none", index=True)
    decision = Column(String(16), nullable=False, default="PASS")
    risk_score = Column(Float, default=0.0)
    confidence = Column(Float, default=0.0)
    importance = Column(Float, default=0.0, index=True)
    summary = Column(Text, nullable=False)
    # 属性名避开 SQLAlchemy 保留字 metadata，映射到实际列名 "metadata"
    meta_data = Column("metadata", JSON, default={})
    access_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


class SkillRoutingLog(Base):
    """Skill 路由日志表（用于 SkillOptimizer 自优化分析）
    记录每次 Agent 动态选择 Skill 的完整过程：Filter → Rank → Select
    """
    __tablename__ = "skill_routing_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(String(255), nullable=False, index=True)
    agent = Column(String(100), nullable=False, index=True)
    query = Column(Text, nullable=True)
    content_type = Column(String(50), nullable=False)
    filtered_skills = Column(JSON, default=[])  # Filter 阶段结果
    ranked_skills = Column(JSON, default=[])    # Rank 阶段结果
    selected_skills = Column(JSON, default=[])  # Select 阶段结果
    timestamp = Column(DateTime, default=datetime.now(timezone.utc), index=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
