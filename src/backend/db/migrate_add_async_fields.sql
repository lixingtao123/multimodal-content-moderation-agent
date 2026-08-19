-- 异步审核任务状态字段迁移
-- 为 moderation_records 表添加异步任务支持

ALTER TABLE moderation_records ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'COMPLETED';
-- 状态值: QUEUED / PROCESSING / COMPLETED / FAILED / AWAITING_HUMAN

ALTER TABLE moderation_records ADD COLUMN IF NOT EXISTS progress FLOAT DEFAULT 1.0;
-- 进度: 0.0 ~ 1.0

ALTER TABLE moderation_records ADD COLUMN IF NOT EXISTS chunk_count INT DEFAULT 0;
-- 分块数量: 0=未分块, >0=文本被分块处理

ALTER TABLE moderation_records ADD COLUMN IF NOT EXISTS truncated BOOLEAN DEFAULT FALSE;
-- 是否因超长被截断/取样

ALTER TABLE moderation_records ADD COLUMN IF NOT EXISTS error_message TEXT DEFAULT NULL;
-- 失败时的错误信息

CREATE INDEX IF NOT EXISTS idx_moderation_status ON moderation_records(status);
