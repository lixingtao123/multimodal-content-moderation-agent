"""
MCP 审计日志 v1.0

记录每条 MCP 工具调用的完整审计信息：
  - 谁调用了什么工具
  - 什么参数（截断脱敏）
  - 什么结果
  - 耗时多少
  - 成功还是失败

日志输出:
  1. JSON Lines 文件: /workspace/logs/mcp_audit.jsonl（始终写入）
  2. PostgreSQL 表: moderation_audit_log（可选，configurable）
  3. 标准 logging（INFO 级别）
"""
import json
import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, Dict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 审计日志文件路径
AUDIT_LOG_PATH = os.environ.get(
    "MCP_AUDIT_LOG_PATH",
    "/workspace/logs/mcp_audit.jsonl",
)

# 参数截断长度（防止日志膨胀）
MAX_PARAM_LENGTH = 200


@dataclass
class AuditRecord:
    """MCP 工具调用审计记录"""
    timestamp: str = ""
    trace_id: str = ""
    tool_name: str = ""
    caller_agent: str = ""
    caller_identity: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    params_hash: str = ""
    result_type: str = "success"  # success / error / denied
    result_summary: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    error_message: str = ""
    content_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AuditLogger:
    """MCP 工具调用审计日志记录器"""

    def __init__(self, log_path: str = None):
        self._log_path = log_path or AUDIT_LOG_PATH
        self._ensure_log_dir()

    def _ensure_log_dir(self):
        """确保日志目录存在"""
        log_dir = os.path.dirname(self._log_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

    def log(
        self,
        tool_name: str,
        caller_agent: str,
        params: dict,
        result_type: str = "success",
        result_summary: dict = None,
        latency_ms: float = 0.0,
        error_message: str = "",
        caller_identity: str = "",
        content_id: str = "",
        trace_id: str = "",
    ) -> AuditRecord:
        """
        记录一条工具调用审计日志。

        Args:
            tool_name: 工具名称
            caller_agent: 调用方 Agent
            params: 调用参数（会自动截断长文本）
            result_type: success / error / denied
            result_summary: 结果摘要
            latency_ms: 调用耗时 (ms)
            error_message: 错误信息
            caller_identity: 调用方身份
            content_id: 关联内容 ID
            trace_id: 追踪 ID

        Returns:
            AuditRecord 对象
        """
        # 脱敏参数（截断长文本）
        safe_params = self._sanitize_params(params)

        # 生成参数哈希（用于去重检测，不记录原始敏感内容）
        params_hash = hashlib.md5(
            json.dumps(params, sort_keys=True, default=str).encode()
        ).hexdigest()

        record = AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=trace_id or str(uuid.uuid4())[:8],
            tool_name=tool_name,
            caller_agent=caller_agent,
            caller_identity=caller_identity,
            params=safe_params,
            params_hash=params_hash,
            result_type=result_type,
            result_summary=result_summary or {},
            latency_ms=round(latency_ms, 3),
            error_message=error_message[:500] if error_message else "",
            content_id=content_id,
        )

        # 写入 JSON Lines 文件
        self._write_to_file(record)

        # 写入标准日志
        log_level = logging.ERROR if result_type == "error" else logging.INFO
        logger.log(
            log_level,
            f"[MCP_AUDIT] tool={tool_name} agent={caller_agent} "
            f"result={result_type} latency={latency_ms:.2f}ms "
            f"content={content_id} trace={record.trace_id}",
        )

        return record

    def _sanitize_params(self, params: dict) -> dict:
        """脱敏参数：截断长文本值"""
        safe = {}
        for k, v in (params or {}).items():
            if isinstance(v, str) and len(v) > MAX_PARAM_LENGTH:
                safe[k] = v[:MAX_PARAM_LENGTH] + f"...[truncated, total {len(v)} chars]"
            elif isinstance(v, bytes):
                safe[k] = f"<bytes:{len(v)}>"
            else:
                safe[k] = v
        return safe

    def _write_to_file(self, record: AuditRecord):
        """写入 JSON Lines 文件"""
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    async def log_to_db(self, record: AuditRecord):
        """
        写入 PostgreSQL 审计表（异步，不阻塞主流程）

        建表 DDL: db/migrations/003_mcp_audit_log.sql
        """
        try:
            from db.connection import get_session_factory
            from sqlalchemy import text

            factory = get_session_factory()
            async with factory() as session:
                await session.execute(
                    text("""
                        INSERT INTO mcp_audit_log
                            (trace_id, tool_name, caller_agent, caller_identity,
                             params_hash, result_type, result_summary,
                             latency_ms, error_message, content_id)
                        VALUES
                            (:trace_id, :tool_name, :caller_agent, :caller_identity,
                             :params_hash, :result_type, :result_summary,
                             :latency_ms, :error_message, :content_id)
                    """),
                    {
                        "trace_id": record.trace_id,
                        "tool_name": record.tool_name,
                        "caller_agent": record.caller_agent,
                        "caller_identity": record.caller_identity or "",
                        "params_hash": record.params_hash,
                        "result_type": record.result_type,
                        "result_summary": json.dumps(record.result_summary, ensure_ascii=False),
                        "latency_ms": record.latency_ms,
                        "error_message": record.error_message,
                        "content_id": record.content_id or "",
                    },
                )
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to write audit log to DB (non-critical): {e}")


# 全局单例
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
