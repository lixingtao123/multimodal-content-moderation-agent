-- 内容风控智能治理系统 — PostgreSQL Schema

-- 内容审核记录表
CREATE TABLE IF NOT EXISTS moderation_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id VARCHAR(64) NOT NULL UNIQUE,
    content_type VARCHAR(32) NOT NULL,          -- text / image / audio / video
    content_hash VARCHAR(64),                    -- MD5 去重
    content_preview TEXT,                        -- 文本摘要 / 文件 URL
    account_id VARCHAR(64),
    final_decision VARCHAR(16) NOT NULL,         -- PASS / REVIEW / REJECT
    risk_score FLOAT NOT NULL DEFAULT 0.0,
    violation_types JSONB DEFAULT '[]',
    violation_details JSONB DEFAULT '{}',
    suggestions JSONB DEFAULT '[]',
    processing_time_ms FLOAT DEFAULT 0.0,
    agent_reasoning JSONB,                          -- AI 推理过程 (各Agent的reasoning_chain等)
    debate_info JSONB,                              -- 辩论信息 (had_debate/opinions/consensus等)
    -- v3.3: 异步任务支持
    status VARCHAR(32) DEFAULT 'COMPLETED',         -- QUEUED / PROCESSING / COMPLETED / FAILED / AWAITING_HUMAN
    progress FLOAT DEFAULT 1.0,                     -- 处理进度 0.0 ~ 1.0
    chunk_count INT DEFAULT 0,                      -- 分块数量 (0=未分块)
    truncated BOOLEAN DEFAULT FALSE,                 -- 是否被截断/取样
    error_message TEXT DEFAULT NULL,                 -- 失败时的错误信息
    -- v3.4: 信号卡压缩 + 多模态增强 (R22: 与 ORM models.ModerationRecord 对齐)
    compression_used BOOLEAN DEFAULT FALSE,         -- 是否使用了信号卡压缩
    signal_card_count INT DEFAULT 0,                -- 信号卡数量
    speaker_count INT DEFAULT 0,                    -- 说话人数
    cross_modal_fusion JSONB,                        -- 跨模态融合分析结果
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_moderation_content_type ON moderation_records(content_type);
CREATE INDEX IF NOT EXISTS idx_moderation_decision ON moderation_records(final_decision);
CREATE INDEX IF NOT EXISTS idx_moderation_account ON moderation_records(account_id);
CREATE INDEX IF NOT EXISTS idx_moderation_created ON moderation_records(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_moderation_content_hash ON moderation_records(content_hash);

-- 黑灰产标签库
CREATE TABLE IF NOT EXISTS blackhat_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_type VARCHAR(64) NOT NULL,           -- BULK_GENERATION / KEYWORD_VARIANT / PHISHING / TRAFFIC_FRAUD
    pattern_name VARCHAR(128) NOT NULL,
    pattern_data JSONB NOT NULL,
    risk_level INT DEFAULT 1,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_blackhat_pattern_type ON blackhat_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_blackhat_enabled ON blackhat_patterns(enabled);

-- 账号风险画像
CREATE TABLE IF NOT EXISTS account_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(64) NOT NULL UNIQUE,
    risk_score FLOAT DEFAULT 0.0,
    violation_count INT DEFAULT 0,
    last_violation_at TIMESTAMP,
    detected_patterns JSONB DEFAULT '[]',
    behavior_features JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_account_profiles_risk ON account_profiles(risk_score DESC);

-- 审核操作日志
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    moderation_id UUID REFERENCES moderation_records(id),
    action_type VARCHAR(32) NOT NULL,
    action_data JSONB,
    operator_id VARCHAR(64),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_moderation ON audit_logs(moderation_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC);

-- === v3.8: Agent 核心记忆表 (MemGPT 风格三层记忆体系 — Core Memory) ===
-- 存储高重要性(>0.7)的审核案例，用于 Agent 长期决策参考
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
);

CREATE INDEX IF NOT EXISTS idx_core_memories_importance ON core_memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_core_memories_violation ON core_memories(violation_type);
CREATE INDEX IF NOT EXISTS idx_core_memories_created ON core_memories(created_at DESC);

-- === v3.8: 审核策略配置表 ===
-- 运营人员可界面化配置审核规则、阈值、违规类型，无需改代码重新部署
CREATE TABLE IF NOT EXISTS moderation_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL UNIQUE,
    policy_type VARCHAR(32) NOT NULL DEFAULT 'keyword',   -- keyword / regex / sensitivity / threshold / model_route
    description TEXT DEFAULT '',
    rule_config JSONB NOT NULL DEFAULT '{}',
    -- keyword:    {"keywords":["微信","QQ"],"action":"flag","violation_type":"advertisement"}
    -- regex:      {"pattern":"加.*微信.*赚","action":"reject","violation_type":"advertisement"}
    -- sensitivity:{"violation_type":"politics","min_confidence":0.8}
    -- threshold:  {"review_threshold":0.35,"reject_threshold":0.75}
    -- model_route:{"tier":"tier1_pass","pattern":"^[好的嗯哦]+$"}
    enabled BOOLEAN DEFAULT TRUE,
    priority INT DEFAULT 5,           -- 1(min)~10(max), 高优先级先匹配
    created_by VARCHAR(64) DEFAULT 'system',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_policies_type ON moderation_policies(policy_type);
CREATE INDEX IF NOT EXISTS idx_policies_enabled ON moderation_policies(enabled);

-- === R22: 标注记录表 (与 ORM AnnotationRecord / annotation_queue.py 对齐) ===
-- 收并集: 人工标注 / hard_case_miner / 优化 agent 的全部引用列
CREATE TABLE IF NOT EXISTS annotation_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id VARCHAR(128) NOT NULL UNIQUE,
    content_type VARCHAR(32) DEFAULT 'text',
    -- 模型原始输出
    annotation_input TEXT,
    model_decision VARCHAR(16),
    model_confidence FLOAT DEFAULT 0,
    model_violation_types JSONB DEFAULT '[]',
    model_reason TEXT,
    model_risk_score FLOAT DEFAULT 0,
    -- hard_case_miner 专用 (ai_* 三件套)
    ai_violation_type VARCHAR(32),
    ai_decision VARCHAR(16),
    ai_confidence FLOAT,
    annotation_status VARCHAR(16) DEFAULT 'PENDING',
    priority VARCHAR(16),
    meta_info JSONB DEFAULT '{}',
    -- 标注结果
    is_error BOOLEAN DEFAULT FALSE,
    error_type VARCHAR(64),
    error_detail TEXT,
    -- 优化 agent 规则/LLM 复核视角
    rule_verdict VARCHAR(32),
    rule_detail TEXT,
    llm_verdict VARCHAR(32),
    llm_reason TEXT,
    llm_called BOOLEAN DEFAULT FALSE,
    contradiction_flag BOOLEAN DEFAULT FALSE,
    rule_matched_keywords JSONB DEFAULT '[]',
    rule_matched_rules JSONB DEFAULT '[]',
    rule_whitelist_hit BOOLEAN DEFAULT FALSE,
    rule_adversarial_hit BOOLEAN DEFAULT FALSE,
    -- 人工标注
    annotated_violation_types JSONB DEFAULT '[]',
    annotated_confidence FLOAT,
    source VARCHAR(32) DEFAULT 'auto',            -- human/auto/hard_case
    weight FLOAT DEFAULT 1.0,                     -- human=3.0 (权重更大)
    reviewer_id VARCHAR(64),
    human_corrected_json JSONB,
    -- 优化消费标记: FALSE=活跃错误(参与计数), TRUE=已被优化消费
    consumed BOOLEAN DEFAULT FALSE,
    optimization_id VARCHAR(64),
    -- 元信息
    processing_time_ms FLOAT,
    annotated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_annotation_content_id ON annotation_records(content_id);
CREATE INDEX IF NOT EXISTS idx_annotation_is_error ON annotation_records(is_error);
CREATE INDEX IF NOT EXISTS idx_annotation_consumed ON annotation_records(consumed);
CREATE INDEX IF NOT EXISTS idx_annotation_error_type ON annotation_records(error_type);
CREATE INDEX IF NOT EXISTS idx_annotation_source ON annotation_records(source);

-- === R22: 数据集样本登记表 (与 ORM DatasetSample 对齐) ===
CREATE TABLE IF NOT EXISTS dataset_samples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id VARCHAR(128) NOT NULL UNIQUE,
    category VARCHAR(128),
    violation_type VARCHAR(32),
    modality VARCHAR(16),                          -- text/image/video/audio
    language VARCHAR(8),                           -- zh/en
    content_preview TEXT,
    path VARCHAR(512),
    ground_truth VARCHAR(32) DEFAULT 'confirmed',  -- confirmed/model_labeled
    source_dataset VARCHAR(32) DEFAULT 'out_safe', -- out_safe/simulated/production
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dataset_violation_type ON dataset_samples(violation_type);
CREATE INDEX IF NOT EXISTS idx_dataset_modality ON dataset_samples(modality);
CREATE INDEX IF NOT EXISTS idx_dataset_source ON dataset_samples(source_dataset);

-- === MCP 审计日志表 (R22: 并入 schema.sql，与 mcp_servers/audit.py 对齐) ===
-- 记录所有 MCP 工具调用的完整审计信息，用于故障排查、合规审计、性能分析
CREATE TABLE IF NOT EXISTS mcp_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    trace_id        VARCHAR(16) NOT NULL,            -- 追踪 ID (短 UUID)
    tool_name       VARCHAR(64) NOT NULL,            -- 工具名称
    caller_agent    VARCHAR(64) NOT NULL,            -- 调用方 Agent
    caller_identity VARCHAR(128) DEFAULT '',         -- 调用方身份
    params_hash     VARCHAR(64) DEFAULT '',          -- 参数 MD5 哈希 (去重用)
    result_type     VARCHAR(16) NOT NULL DEFAULT 'success',  -- success / error / denied
    result_summary  JSONB DEFAULT '{}',              -- 结果摘要
    latency_ms      DOUBLE PRECISION DEFAULT 0,      -- 调用耗时 (毫秒)
    error_message   TEXT DEFAULT '',                 -- 错误信息
    content_id      VARCHAR(64) DEFAULT '',          -- 关联审核内容 ID
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT idx_mcp_audit_tool_time UNIQUE (tool_name, created_at, id)
);

CREATE INDEX IF NOT EXISTS idx_mcp_audit_tool ON mcp_audit_log (tool_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_audit_agent ON mcp_audit_log (caller_agent, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_audit_trace ON mcp_audit_log (trace_id);
CREATE INDEX IF NOT EXISTS idx_mcp_audit_content ON mcp_audit_log (content_id);

-- === Skill 路由日志表 ===
-- 记录每次 Agent 动态选择 Skill 的完整过程，用于 SkillOptimizer 分析优化
CREATE TABLE IF NOT EXISTS skill_routing_logs (
    id BIGSERIAL PRIMARY KEY,
    content_id VARCHAR(255) NOT NULL,
    agent VARCHAR(100) NOT NULL,
    query TEXT,
    content_type VARCHAR(50) NOT NULL,
    filtered_skills TEXT[],      -- Filter 阶段结果
    ranked_skills TEXT[],        -- Rank 阶段结果
    selected_skills TEXT[],      -- Select 阶段结果（最终注入）
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skill_routing_content_id ON skill_routing_logs(content_id);
CREATE INDEX IF NOT EXISTS idx_skill_routing_agent ON skill_routing_logs(agent);
CREATE INDEX IF NOT EXISTS idx_skill_routing_timestamp ON skill_routing_logs(timestamp DESC);
