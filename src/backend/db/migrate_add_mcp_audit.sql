-- MCP 审计日志表
-- 记录所有 MCP 工具调用的完整审计信息
-- 用于故障排查、合规审计、性能分析

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

    -- 索引：
    -- 按工具+时间查询最近的调用
    CONSTRAINT idx_mcp_audit_tool_time UNIQUE (tool_name, created_at, id)
);

-- 加速按工具查询
CREATE INDEX IF NOT EXISTS idx_mcp_audit_tool ON mcp_audit_log (tool_name, created_at DESC);

-- 加速按 Agent 查询
CREATE INDEX IF NOT EXISTS idx_mcp_audit_agent ON mcp_audit_log (caller_agent, created_at DESC);

-- 加速按追踪 ID 查询
CREATE INDEX IF NOT EXISTS idx_mcp_audit_trace ON mcp_audit_log (trace_id);

-- 加速按内容 ID 查询
CREATE INDEX IF NOT EXISTS idx_mcp_audit_content ON mcp_audit_log (content_id);

-- 90 天自动清理策略（可选，根据需要启用）
-- SELECT cron.schedule('cleanup-mcp-audit', '0 3 * * *', $$DELETE FROM mcp_audit_log WHERE created_at < NOW() - INTERVAL '90 days'$$);
