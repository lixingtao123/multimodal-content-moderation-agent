-- 迁移: 为 moderation_records 添加 agent_reasoning 和 debate_info 列
-- 用于持久化 AI 推理过程和辩论信息

ALTER TABLE moderation_records
    ADD COLUMN IF NOT EXISTS agent_reasoning JSONB;

ALTER TABLE moderation_records
    ADD COLUMN IF NOT EXISTS debate_info JSONB;
