-- 标注记录持久化表 (历史迁移脚本)
-- 解决 Redis 重启后统计数据清零的问题
-- 错误案例积累从 PostgreSQL 读取，仅优化消费后标记 consumed=TRUE

-- ⚠️ 注意 (R22 统一): 权威 schema 源为 db/schema.sql (含完整列定义, id 为 UUID)。
-- 此文件仅为历史迁移记录，新部署无需执行 —— init_db() 会幂等执行 schema.sql。
-- 本脚本保留供已有 SERIAL 表升级参考，新表请勿使用 (id 类型与 ORM 的 UUID 不一致)。

CREATE TABLE IF NOT EXISTS annotation_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id VARCHAR(128) UNIQUE NOT NULL,
    content_type VARCHAR(32) DEFAULT 'text',
    annotation_input TEXT DEFAULT '',
    model_decision VARCHAR(32) DEFAULT '',
    model_confidence FLOAT DEFAULT 0,
    model_violation_types JSONB DEFAULT '[]',
    model_reason TEXT DEFAULT '',
    model_risk_score FLOAT DEFAULT 0,
    is_error BOOLEAN DEFAULT FALSE,
    error_type VARCHAR(32) DEFAULT 'correct',
    error_detail TEXT DEFAULT '',
    rule_verdict VARCHAR(32) DEFAULT '',
    rule_detail TEXT DEFAULT '',
    llm_verdict VARCHAR(32) DEFAULT '',
    llm_reason TEXT DEFAULT '',
    llm_called BOOLEAN DEFAULT FALSE,
    contradiction_flag BOOLEAN DEFAULT FALSE,
    annotated_violation_types JSONB DEFAULT '[]',
    annotated_confidence FLOAT DEFAULT 0,
    rule_matched_keywords JSONB DEFAULT '[]',
    rule_matched_rules JSONB DEFAULT '[]',
    rule_whitelist_hit BOOLEAN DEFAULT FALSE,
    rule_adversarial_hit BOOLEAN DEFAULT FALSE,
    processing_time_ms FLOAT DEFAULT 0,
    annotated_at TIMESTAMP DEFAULT NOW(),
    -- 优化消费标记: FALSE=活跃错误(参与计数), TRUE=已被优化消费(不再计数)
    consumed BOOLEAN DEFAULT FALSE,
    optimization_id VARCHAR(64),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_annotation_content_id ON annotation_records(content_id);
CREATE INDEX IF NOT EXISTS idx_annotation_is_error ON annotation_records(is_error);
CREATE INDEX IF NOT EXISTS idx_annotation_consumed ON annotation_records(consumed);
CREATE INDEX IF NOT EXISTS idx_annotation_error_type ON annotation_records(error_type);
