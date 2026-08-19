"""
全链路日志系统 v3.0 — 终端ASCII流程图 + 结构化存储 + Web可视化 + 实时追踪

v3.0 新增:
- FlowLogger: 终端 ASCII 流程图输出，面向 0 基础学员，模块级输入输出展示
- 与 PipelineLogger 共存：FlowLogger 管终端展示，PipelineLogger 管持久化存储
- 树形缩进 + 模块边界框 + 数据流连线

三层存储:
1. 内存: PipelineLogger 实例（请求生命周期内，contextvars 隔离）
2. Redis: 最近 1000 条日志（7 天 TTL，快速查询）
3. 文件: JSON Lines 格式持久化（/workspace/logs/pipeline.jsonl）

v2.1 修复:
- PipelineLogger 使用 contextvars 实现请求级隔离，解决并发请求互相覆盖的 bug
- elapsed_ms 使用 time.monotonic() 替代 time.time()，避免 NTP 校时导致负duration
"""
import time
import json
import os
import logging
import contextvars
import sys
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ============================================================
# ANSI 终端颜色 (0基础友好: 不同模块用不同颜色区分)
# ============================================================
COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "bg_blue": "\033[44m",
    "bg_green": "\033[42m",
    "bg_red": "\033[41m",
    "bg_yellow": "\033[43m",
}

# 模块颜色映射
MODULE_COLORS = {
    "GATEWAY": "cyan",
    "FILE_AGENT": "blue",
    "TEXT_AGENT": "green",
    "IMAGE_AGENT": "magenta",
    "AUDIO_AGENT": "yellow",
    "VIDEO_AGENT": "red",
    "BLACKHAT": "yellow",
    "RISK_AGENT": "cyan",
    "RAG": "blue",
    "LLM": "magenta",
    "AGENTIC_RAG": "blue",
    "GRAPH_RAG": "green",
    "MULTIMODAL_RAG": "magenta",
    "DEBATE": "red",
    "REFLEXION": "yellow",
    "SUPERVISOR": "cyan",
}


def _c(color_name: str, text: str) -> str:
    """给文本添加 ANSI 颜色"""
    code = COLORS.get(color_name, "")
    return f"{code}{text}{COLORS['reset']}"


def _box_header(title: str, color: str = "cyan") -> str:
    """生成模块边界框头部"""
    return _c(color, f"┌─ {title} " + "─" * max(5, 60 - len(title)) + "┐")


def _box_footer(color: str = "cyan") -> str:
    """生成模块边界框尾部"""
    return _c(color, "└" + "─" * 62 + "┘")


def _box_line(text: str, color: str = "cyan") -> str:
    """生成模块边界框内的一行"""
    return _c(color, f"│  {text}")


def _flow_arrow(text: str = "") -> str:
    """生成数据流连线"""
    return _c("dim", f"       │  {text}")


def _branch_arrow(text: str = "") -> str:
    """生成分支连线"""
    return _c("dim", f"       ├── {text}")


# ============================================================
# FlowLogger — 终端 ASCII 流程图输出
# ============================================================

class FlowLogger:
    """
    面向 0 基础学员的终端日志输出器

    功能:
    - 打印模块边界框 (box_start / box_end)
    - 打印模块内部步骤 (step)
    - 打印数据流连线 (flow)
    - 打印任务启动/完成横幅 (banner)
    - 所有输出直接到 stdout，终端实时可见
    """

    def __init__(self, content_id: str = "", content_type: str = ""):
        self.content_id = content_id
        self.content_type = content_type
        self._indent = 0
        self._step_count = 0
        self._rag_count = 0
        self._llm_count = 0

    def _print(self, text: str):
        """直接输出到 stdout"""
        print(text, flush=True)

    def banner_start(self):
        """任务启动横幅"""
        self._print("")
        self._print(_c("bg_blue", "╔══════════════════════════════════════════════════════════════╗"))
        self._print(_c("bg_blue", f"║  📋 审核任务启动: {self.content_id[:20]} | 类型: {self.content_type:<20} ║"))
        self._print(_c("bg_blue", f"║  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<54}║"))
        self._print(_c("bg_blue", "╚══════════════════════════════════════════════════════════════╝"))
        self._print("")

    def banner_end(self, total_ms: float, decision: str = "?", risk: float = 0):
        """任务完成横幅"""
        self._print("")
        self._print(_c("bg_green", "╔══════════════════════════════════════════════════════════════╗"))
        self._print(_c("bg_green", f"║  ✅ 审核完成 | 总耗时: {total_ms/1000:.1f}s".ljust(63) + "║"))
        self._print(_c("bg_green", f"║  📊 决策: {decision} | 风险分: {risk:.2f}"))
        self._print(_c("bg_green", f"║  🔍 RAG调用: {self._rag_count}次 | 🧠 LLM调用: {self._llm_count}次"))
        self._print(_c("bg_green", "╚══════════════════════════════════════════════════════════════╝"))
        self._print("")

    def box_start(self, module_name: str, subtitle: str = ""):
        """模块开始 — 打印边界框头部"""
        color = MODULE_COLORS.get(module_name.upper(), "cyan")
        title = f"{module_name}"
        if subtitle:
            title += f" | {subtitle}"
        self._print(_box_header(title, color))

    def box_step(self, icon: str, label: str, detail: str, color: str = None):
        """模块内部步骤 — 带icon缩进"""
        if color is None:
            color = "white"
        icon_str = f"{icon} {label}:"
        self._print(_c(color, f"│  {icon_str} {detail}"))

        if "RAG" in icon:
            self._rag_count += 1
        if "LLM" in icon or "VL" in icon or "ASR" in icon:
            self._llm_count += 1

    def box_rag_result(self, results: list, color: str = "blue"):
        """RAG 检索结果详情"""
        if not results:
            self._print(_c("dim", "│     (无匹配案例)"))
            return
        for i, r in enumerate(results[:3]):
            sim = r.get("similarity", r.get("score", 0))
            vt = r.get("violation_type", "?")
            content = r.get("content", "")[:60]
            self._print(_c(color, f"│     [{i+1}] 相似度{sim:.2f} | {vt} | \"{content}...\""))

    def box_end(self, module_name: str = "", summary: str = ""):
        """模块结束 — 打印边界框尾部"""
        color = MODULE_COLORS.get(module_name.upper(), "cyan")
        if summary:
            self._print(_c(color, f"│  → {summary}"))
        self._print(_box_footer(color))

    def flow(self, description: str):
        """数据流连线"""
        self._print(_flow_arrow(description))

    def branch(self, description: str):
        """分支连线"""
        self._print(_branch_arrow(description))

    def step(self, node: str, action: str,
             input_data: dict = None, output_data: dict = None,
             duration_ms: float = 0, level: str = "INFO"):
        """兼容 PipelineLogger.step() 的通用日志方法 — 终端输出"""
        color = MODULE_COLORS.get(node.upper().replace(" ", "_"), "white")
        icon_map = {
            "GATEWAY": "🌐", "FILE_AGENT": "📁", "TEXT_AGENT": "📝",
            "IMAGE_AGENT": "🖼️", "AUDIO_AGENT": "🎤", "VIDEO_AGENT": "🎬",
            "BLACKHAT": "🕵️", "RISK_AGENT": "⚖️", "RAG": "🔍",
            "LLM": "🧠", "AGENTIC_RAG": "🔍", "GRAPH_RAG": "🔗",
            "MULTIMODAL_RAG": "🔍", "DEBATE": "⚖️", "REFLEXION": "🔄",
        }
        icon = icon_map.get(node.upper().replace(" ", "_"), "→")

        detail_parts = []
        if output_data:
            for k, v in list(output_data.items())[:4]:
                if isinstance(v, float):
                    detail_parts.append(f"{k}={v:.2f}")
                elif isinstance(v, (str, int)):
                    detail_parts.append(f"{k}={v}")
                elif isinstance(v, list):
                    detail_parts.append(f"{k}={len(v)}项")
            if duration_ms > 0:
                detail_parts.append(f"{duration_ms:.0f}ms")

        detail = " | ".join(detail_parts) if detail_parts else ""
        self.box_step(icon, action[:50], detail, color)


# ============================================================
# PipelineLogger (保持向后兼容)
# ============================================================

LOG_FILE = "/workspace/logs/pipeline.jsonl"
MAX_REDIS_LOGS = 1000
LOG_TTL = 7 * 24 * 3600  # 7 天


def _ensure_log_dir():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


def _append_file(record: dict):
    """追加到 JSON Lines 文件"""
    try:
        _ensure_log_dir()
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _save_redis(content_id: str, record: dict):
    """保存到 Redis 列表（最近 N 条）"""
    try:
        from memory.redis_service import get_redis_service
        svc = get_redis_service()
        if svc.client:
            import asyncio
            async def _save():
                key = f"pipeline_log:{content_id}"
                await svc.client.set(key, json.dumps(record, ensure_ascii=False), ex=LOG_TTL)
                # 加入最近列表
                await svc.client.lpush("pipeline_logs:recent", content_id)
                await svc.client.ltrim("pipeline_logs:recent", 0, MAX_REDIS_LOGS - 1)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(_save())
                else:
                    loop.run_until_complete(_save())
            except RuntimeError:
                asyncio.run(_save())
    except Exception:
        pass


class PipelineLogger:
    """审核流水线日志记录器 v2.1 — monotonic时间 + contextvars 隔离"""

    def __init__(self, content_id: str, content_type: str):
        self.content_id = content_id
        self.content_type = content_type
        self.steps: list = []
        self._start_monotonic = time.monotonic()  # 不受 NTP 影响, 用于 duration 计算
        self._start_wall = time.time()             # 墙上时间, 用于显示
        self._saved = False

    @property
    def start_time(self) -> float:
        """兼容旧代码: 返回墙上开始时间"""
        return self._start_wall

    def step(self, node: str, action: str,
             input_data: dict = None, output_data: dict = None,
             duration_ms: float = 0, level: str = "INFO"):
        """记录一个流水线步骤"""
        # 使用 monotonic 计算 elapsed, 避免 NTP 校时导致时间倒退
        elapsed_ms = round((time.monotonic() - self._start_monotonic) * 1000, 2)
        step_record = {
            "seq": len(self.steps) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node": node,
            "action": action,
            "level": level,
            "duration_ms": round(duration_ms, 2),
            "elapsed_ms": elapsed_ms,
        }
        if input_data:
            step_record["input"] = _truncate(input_data, 300)
        if output_data:
            step_record["output"] = _truncate(output_data, 300)

        self.steps.append(step_record)

        # 终端输出（带颜色标记）
        colors = {"ERROR": "❌", "WARN": "⚠️", "INFO": "  "}
        prefix = colors.get(level, "  ")
        print(f"{prefix} [{self.content_id[:12]}] {node:14s} | {action:35s} | "
              f"+{step_record['elapsed_ms']:6.0f}ms")

    def save(self):
        """持久化流水线日志"""
        if self._saved:
            return
        self._saved = True

        total_ms = round((time.monotonic() - self._start_monotonic) * 1000, 2)
        record = {
            "content_id": self.content_id,
            "content_type": self.content_type,
            "start_time": datetime.fromtimestamp(self._start_wall, tz=timezone.utc).isoformat(),
            "total_duration_ms": total_ms,
            "step_count": len(self.steps),
            "steps": self.steps,
        }

        _append_file(record)
        _save_redis(self.content_id, record)

        # 打印总结
        decisions = [s for s in self.steps if s.get("output", {}).get("decision")]
        final = decisions[-1]["output"] if decisions else {}
        print(f"   ═══ 完成 [{self.content_id[:12]}] {total_ms:.0f}ms | "
              f"decision={final.get('decision','?')} | score={final.get('overall_score','?')}")

    def to_json(self) -> str:
        return json.dumps({
            "content_id": self.content_id,
            "content_type": self.content_type,
            "total_duration_ms": round((time.monotonic() - self._start_monotonic) * 1000, 2),
            "step_count": len(self.steps),
            "steps": self.steps,
        }, ensure_ascii=False, indent=2)

    def to_html(self) -> str:
        """生成 HTML 格式的可视化日志"""
        rows = []
        for s in self.steps:
            level_color = {"ERROR": "#e74c3c", "WARN": "#f39c12", "INFO": "#2ecc71"}.get(s.get("level", "INFO"), "#3498db")
            in_data = json.dumps(s.get("input", {}), ensure_ascii=False)[:200] if s.get("input") else "-"
            out_data = json.dumps(s.get("output", {}), ensure_ascii=False)[:200] if s.get("output") else "-"
            rows.append(f"""
            <tr>
                <td>{s['seq']}</td>
                <td style="color:{level_color};font-weight:bold">{s['node']}</td>
                <td>{s['action']}</td>
                <td style="font-family:monospace;font-size:12px;max-width:300px;overflow:hidden">{in_data}</td>
                <td style="font-family:monospace;font-size:12px;max-width:300px;overflow:hidden">{out_data}</td>
                <td style="text-align:right">{s['duration_ms']:.0f}ms</td>
                <td style="text-align:right">+{s['elapsed_ms']:.0f}ms</td>
            </tr>""")

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>Pipeline Log - {self.content_id}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px}}
.header{{background:#16213e;padding:20px;border-radius:8px;margin-bottom:20px}}
.header h1{{color:#e94560;font-size:18px}}
.header .meta{{color:#888;font-size:13px;margin-top:8px}}
table{{width:100%;border-collapse:collapse;background:#16213e;border-radius:8px;overflow:hidden}}
th{{background:#0f3460;padding:10px 12px;text-align:left;font-size:12px;color:#aaa;text-transform:uppercase}}
td{{padding:8px 12px;font-size:13px;border-bottom:1px solid #1a1a2e}}
tr:hover{{background:#1a1a3e}}
.flow-arrow{{color:#e94560;font-weight:bold;text-align:center}}
</style></head>
<body>
<div class="header">
    <h1>🔍 Pipeline Trace: {self.content_id}</h1>
    <div class="meta">Type: {self.content_type} | Steps: {len(self.steps)} | Total: ~{int((time.time()-self.start_time)*1000)}ms</div>
</div>
<table>
<thead><tr>
    <th>#</th><th>Node</th><th>Action</th><th>Input</th><th>Output</th><th>Dur</th><th>Elapsed</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</body></html>"""


def _truncate(obj, max_len: int):
    """智能截断"""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if isinstance(v, str) and len(v) > max_len:
                result[k] = v[:max_len] + f"...[{len(v)}c]"
            elif isinstance(v, bytes):
                result[k] = f"<bytes:{len(v)}>"
            elif isinstance(v, (int, float, bool, type(None))):
                result[k] = v
            elif isinstance(v, list) and len(v) > 5:
                result[k] = v[:5] + [f"...[{len(v)} items]"]
            else:
                result[k] = str(v)[:200]
        return result
    return obj


# 请求级隔离: contextvars 确保并发请求互不干扰
_pipeline: contextvars.ContextVar = contextvars.ContextVar("pipeline_logger", default=None)
_flow_logger: contextvars.ContextVar = contextvars.ContextVar("flow_logger", default=None)


def start_pipeline(content_id: str, content_type: str) -> PipelineLogger:
    """创建请求级 PipelineLogger (contextvars 隔离, 并发安全)"""
    pl = PipelineLogger(content_id, content_type)
    _pipeline.set(pl)

    # 同步创建 FlowLogger
    fl = FlowLogger(content_id, content_type)
    _flow_logger.set(fl)
    fl.banner_start()
    fl.step("🌐 GATEWAY", "HTTP 请求到达", input_data={"content_type": content_type})

    return pl


def get_pipeline() -> Optional[PipelineLogger]:
    """获取当前请求的 PipelineLogger"""
    return _pipeline.get(None)


def get_flow_logger() -> Optional[FlowLogger]:
    """获取当前请求的 FlowLogger (终端 ASCII 流程图)"""
    return _flow_logger.get(None)


def save_all():
    """保存 Pipeline 日志并打印完成横幅"""
    pl = get_pipeline()
    fl = get_flow_logger()
    if pl:
        pl.save()
    if fl and pl:
        total_ms = round((time.monotonic() - pl._start_monotonic) * 1000, 2)
        # 从 steps 中提取最终决策
        decisions = [s for s in pl.steps if s.get("output", {}).get("decision")]
        final = decisions[-1]["output"] if decisions else {}
        fl.banner_end(total_ms, final.get("decision", "?"), final.get("overall_score", 0))


async def append_pipeline_tail(content_id: str, node: str, action: str,
                               output_data: dict = None, level: str = "INFO") -> bool:
    """R21: 追加 pipeline 尾日志（用于无 request-scoped pipeline 的独立请求）。

    适用场景：HITL 人工恢复、人工标注等——它们不经过 _run_moderation_core，
    不处于原工作流的 contextvars 作用域。这里读取已有记录（Redis 优先，文件兜底），
    在 steps 末尾追加一个步骤后写回 Redis（不覆盖原始链路），保证同 content_id
    的日志完整可归因。返回是否成功。
    """
    try:
        from memory.redis_service import get_redis_service
        svc = get_redis_service()

        record = None
        if svc.client:
            data = await svc.client.get(f"pipeline_log:{content_id}")
            if data:
                record = json.loads(data)
        if record is None and os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                for line in f:
                    r = json.loads(line.strip())
                    if r.get("content_id") == content_id:
                        record = r
                        break

        if record is None:
            record = {"content_id": content_id, "content_type": "text",
                      "start_time": "", "total_duration_ms": 0, "steps": []}

        step = {
            "seq": len(record.get("steps", [])) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node": node,
            "action": action,
            "level": level,
            "duration_ms": 0,
            "elapsed_ms": 0,
        }
        if output_data:
            step["output"] = _truncate(output_data, 300)
        record["steps"].append(step)
        record["step_count"] = len(record["steps"])

        if svc.client:
            await svc.client.setex(f"pipeline_log:{content_id}", LOG_TTL,
                                   json.dumps(record, ensure_ascii=False))
            # R21: Redis 可用的同时也落盘文件，保证 pipeline.jsonl 文件分析可覆盖尾日志
            _append_file(record)
        else:
            _append_file(record)
        return True
    except Exception as e:
        logger.warning(f"[append_pipeline_tail] {content_id} 追加失败: {e}")
        return False
