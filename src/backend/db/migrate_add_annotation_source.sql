-- 人工标注增强迁移
-- 新增 source (标注来源: auto/human), weight (标注权重), reviewer_id (标注人员ID), human_corrected_json (人工修改后的JSON结果)
-- 使得人工标注和自动标注统一存储在同一张表 annotation_records 中
-- 优化 Agent 可按 source 过滤和按 weight 加权

ALTER TABLE annotation_records ADD COLUMN IF NOT EXISTS source VARCHAR(16) DEFAULT 'auto';
ALTER TABLE annotation_records ADD COLUMN IF NOT EXISTS weight FLOAT DEFAULT 1.0;
ALTER TABLE annotation_records ADD COLUMN IF NOT EXISTS reviewer_id VARCHAR(64) DEFAULT '';
ALTER TABLE annotation_records ADD COLUMN IF NOT EXISTS human_corrected_json JSONB DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_annotation_source ON annotation_records(source);
CREATE INDEX IF NOT EXISTS idx_annotation_reviewer_id ON annotation_records(reviewer_id);
