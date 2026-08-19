"""
日志查询 API — 查看历史流水线日志
"""
import json
import os
import logging
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/logs", tags=["logs"])

LOG_FILE = "/workspace/logs/pipeline.jsonl"


# === 固定路由（必须在 /{content_id} 之前） ===

@router.get("/decision-tree/{task_id}")
async def get_decision_tree(task_id: str):
    """
    v3.8: 获取审核决策树 — 从输入到最终结论的完整推理路径

    返回JSON格式的决策路径, 每个节点包含:
    - 输入数据
    - Agent调用的中间结果
    - 路由决策
    - 最终判定及置信度
    """
    from memory.manager import get_memory_manager
    from memory.redis_service import get_redis_service

    try:
        mem = get_memory_manager()
        redis_svc = get_redis_service()

        # 从Redis获取任务详情
        task_data = await redis_svc.get_short_term(f"task:{task_id}") if redis_svc else None

        # 从PostgreSQL查询审核记录
        try:
            from db.connection import get_session_factory
            from sqlalchemy import text
            factory = get_session_factory()
            async with factory() as session:
                result = await session.execute(
                    text("SELECT * FROM moderation_records WHERE content_id = :cid"),
                    {"cid": task_id},
                )
                row = result.fetchone()
                if row:
                    cols = result.keys()
                    record = dict(zip(cols, row))
                else:
                    record = None
        except Exception:
            record = None

        # 构建决策树
        tree = {
            "task_id": task_id,
            "nodes": [],
            "final_decision": record.get("final_decision", "unknown") if record else "unknown",
            "final_risk_score": record.get("risk_score", 0) if record else 0,
            "violation_types": record.get("violation_types", []) if record else [],
        }

        if record:
            details = record.get("violation_details") or {}
            components = details.get("components", {})

            # Node 1: 输入
            tree["nodes"].append({
                "step": 1,
                "agent": "Input",
                "action": "接收内容",
                "input": record.get("content_preview", "")[:200],
                "output": {"content_type": record.get("content_type", "text")},
            })

            # Node 2: 各模态分析
            for idx, (key, score) in enumerate(components.items(), 2):
                agent_name = {"text": "TextAgent", "image": "ImageAgent",
                              "audio": "AudioAgent", "video": "VideoAgent",
                              "blackhat": "BlackhatDetector"}.get(key, key)
                tree["nodes"].append({
                    "step": idx,
                    "agent": agent_name,
                    "action": "内容分析",
                    "input": f"{key} 模态内容",
                    "output": {"risk_score": score},
                })

            # Node N: 综合评估
            tree["nodes"].append({
                "step": len(components) + 2,
                "agent": "RiskAgent",
                "action": "综合评估",
                "input": f"各模态风险分: {components}",
                "output": {
                    "decision": record.get("final_decision", "?"),
                    "risk_score": record.get("risk_score", 0),
                    "types": record.get("violation_types", []),
                },
            })

            # 如果有辩论信息
            debate = record.get("debate_info") or {}
            if debate:
                tree["nodes"].insert(-1, {
                    "step": "D",
                    "agent": "DebatePanel",
                    "action": f"多Agent辩论 ({debate.get('mode', '?')})",
                    "input": str(debate.get("total_opinions", 0)) + " opinions",
                    "output": {"consensus": debate.get("consensus", False),
                               "needs_human": debate.get("needs_human_review", False)},
                })

        return tree

    except Exception as e:
        return {"task_id": task_id, "error": str(e)[:200], "nodes": []}


# === 固定路由（必须在 /{content_id} 之前） ===

@router.get("/dashboard", response_class=HTMLResponse)
async def log_dashboard():
    """日志仪表盘 HTML 页面"""
    return HTMLResponse(content=LOG_DASHBOARD_HTML)


@router.get("/recent/all")
async def list_recent_logs(limit: int = Query(20, ge=1, le=100)):
    """列出最近的审核日志摘要"""
    logs = []
    try:
        from memory.redis_service import get_redis_service
        svc = get_redis_service()
        if svc.client:
            ids = await svc.client.lrange("pipeline_logs:recent", 0, limit - 1)
            for cid in ids:
                cid_str = cid.decode() if isinstance(cid, bytes) else cid
                data = await svc.client.get(f"pipeline_log:{cid_str}")
                if data:
                    record = json.loads(data)
                    logs.append({
                        "content_id": record["content_id"],
                        "content_type": record["content_type"],
                        "total_duration_ms": record["total_duration_ms"],
                        "step_count": record["step_count"],
                        "start_time": record.get("start_time", ""),
                    })
    except Exception:
        pass
    if not logs and os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                for line in f.readlines()[-limit:]:
                    record = json.loads(line.strip())
                    logs.append({
                        "content_id": record["content_id"],
                        "content_type": record["content_type"],
                        "total_duration_ms": record["total_duration_ms"],
                        "step_count": record["step_count"],
                        "start_time": record.get("start_time", ""),
                    })
        except Exception:
            pass
    return {"total": len(logs), "items": logs}


# === 动态路由（/{content_id} 必须放在最后） ===


@router.get("/{content_id}")
async def get_pipeline_log(content_id: str):
    """获取单条审核的完整流水线日志（优先 Redis，其次文件）"""
    # 1. 尝试从 Redis 读取
    try:
        from memory.redis_service import get_redis_service
        svc = get_redis_service()
        if svc.client:
            data = await svc.client.get(f"pipeline_log:{content_id}")
            if data:
                return JSONResponse(content=json.loads(data))
    except Exception:
        pass

    # 2. 从文件读取
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                for line in f:
                    record = json.loads(line.strip())
                    if record.get("content_id") == content_id:
                        return JSONResponse(content=record)
        except Exception:
            pass

    raise HTTPException(status_code=404, detail=f"Log not found: {content_id}")


@router.get("/{content_id}/html", response_class=HTMLResponse)
async def get_pipeline_log_html(content_id: str):
    """获取单条审核的流水线日志（HTML 可视化）"""
    record = None

    # 尝试 Redis
    try:
        from memory.redis_service import get_redis_service
        svc = get_redis_service()
        if svc.client:
            data = await svc.client.get(f"pipeline_log:{content_id}")
            if data:
                record = json.loads(data)
    except Exception:
        pass

    # 尝试文件
    if not record and os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                for line in f:
                    r = json.loads(line.strip())
                    if r.get("content_id") == content_id:
                        record = r
                        break
        except Exception:
            pass

    if not record:
        return HTMLResponse(content=f"<h1>Log not found: {content_id}</h1>", status_code=404)

    return HTMLResponse(content=_render_html(record))


def _render_html(record: dict) -> str:
    """将单条日志渲染为 HTML"""
    rows = []
    for s in record.get("steps", []):
        level_color = {"ERROR": "#e74c3c", "WARN": "#f39c12", "INFO": "#2ecc71"}.get(
            s.get("level", "INFO"), "#3498db")
        in_data = json.dumps(s.get("input", {}), ensure_ascii=False)[:250] if s.get("input") else "-"
        out_data = json.dumps(s.get("output", {}), ensure_ascii=False)[:250] if s.get("output") else "-"
        rows.append(f"""
        <tr>
            <td>{s['seq']}</td>
            <td style="color:{level_color};font-weight:bold">{s['node']}</td>
            <td>{s['action']}</td>
            <td style="font-size:11px;max-width:250px;overflow:hidden">{in_data}</td>
            <td style="font-size:11px;max-width:250px;overflow:hidden">{out_data}</td>
            <td style="text-align:right">{s['duration_ms']:.0f}ms</td>
            <td style="text-align:right">+{s['elapsed_ms']:.0f}ms</td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>Pipeline: {record['content_id']}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:24px}}
.header{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;margin-bottom:20px}}
.header h1{{color:#58a6ff;font-size:18px}}
.meta{{color:#8b949e;font-size:13px;margin-top:8px;display:flex;gap:24px}}
.meta span{{display:flex;align-items:center;gap:6px}}
table{{width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden}}
th{{background:#21262d;padding:10px 14px;text-align:left;font-size:11px;color:#8b949e;text-transform:uppercase;border-bottom:1px solid #30363d}}
td{{padding:8px 14px;font-size:13px;border-bottom:1px solid #21262d}}
tr:hover{{background:#1c2128}}
</style></head>
<body>
<div class="header">
    <h1>🔍 Pipeline Trace: {record['content_id']}</h1>
    <div class="meta">
        <span>📦 {record.get('content_type','?')}</span>
        <span>📊 {record.get('step_count',0)} 步骤</span>
        <span>⏱ {record.get('total_duration_ms',0):.0f}ms</span>
        <span>🕐 {record.get('start_time','')[:19]}</span>
    </div>
</div>
<table>
<thead><tr><th>#</th><th>Node</th><th>Action</th><th>Input</th><th>Output</th><th>Dur</th><th>+Elapsed</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<script>setTimeout(()=>location.reload(),5000)</script>
</body></html>"""


LOG_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>Pipeline Log Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:24px}
h1{color:#58a6ff;font-size:20px;margin-bottom:20px}
.controls{display:flex;gap:12px;margin-bottom:20px;align-items:center}
.controls input,.controls button{padding:8px 16px;border-radius:6px;border:1px solid #30363d;background:#161b22;color:#c9d1d9;font-size:14px}
.controls button{background:#238636;border-color:#238636;color:white;cursor:pointer}
.controls button:hover{background:#2ea043}
table{width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden}
th{background:#21262d;padding:10px 14px;text-align:left;font-size:11px;color:#8b949e;text-transform:uppercase;border-bottom:1px solid #30363d}
td{padding:8px 14px;font-size:13px;border-bottom:1px solid #21262d}
tr:hover{background:#1c2128}
a{color:#58a6ff;text-decoration:none}
a:hover{text-decoration:underline}
.status-ok{color:#3fb950}
.status-warn{color:#d29922}
.status-err{color:#f85149}
</style></head>
<body>
<h1>📊 Pipeline Log Dashboard</h1>
<div class="controls">
    <input type="text" id="cid" placeholder="Content ID (如 mod_xxx)..." style="width:300px">
    <button onclick="viewLog()">查看日志</button>
    <button onclick="viewHtml()">HTML 视图</button>
    <button onclick="loadRecent()">刷新最近</button>
    <span style="color:#8b949e;font-size:12px;margin-left:12px" id="status"></span>
</div>
<table><thead><tr>
    <th>Content ID</th><th>Type</th><th>Steps</th><th>Duration</th><th>Time</th><th>Actions</th>
</tr></thead><tbody id="tbody"><tr><td colspan="6" style="text-align:center;color:#8b949e">Loading...</td></tr></tbody></table>
<script>
async function loadRecent() {
    document.getElementById('status').textContent = 'Loading...';
    try {
        const r = await fetch('/api/v1/logs/recent/all?limit=50');
        const data = await r.json();
        const tbody = document.getElementById('tbody');
        if (!data.items || data.items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8b949e">暂无日志。提交审核后自动记录。</td></tr>';
            document.getElementById('status').textContent = '0 records';
            return;
        }
        tbody.innerHTML = data.items.map(item => `
            <tr>
                <td><code>${item.content_id}</code></td>
                <td><span style="background:#21262d;padding:2px 8px;border-radius:4px;font-size:12px">${item.content_type}</span></td>
                <td>${item.step_count}</td>
                <td>${item.total_duration_ms.toFixed(0)}ms</td>
                <td style="font-size:12px;color:#8b949e">${(item.start_time||'').substring(11,19)}</td>
                <td>
                    <a href="/api/v1/logs/${item.content_id}" target="_blank">JSON</a> |
                    <a href="/api/v1/logs/${item.content_id}/html" target="_blank">HTML</a>
                </td>
            </tr>`).join('');
        document.getElementById('status').textContent = `${data.items.length} records`;
    } catch(e) {
        document.getElementById('status').textContent = 'Error: ' + e.message;
    }
}
function viewLog() {
    const cid = document.getElementById('cid').value.trim();
    if (cid) window.open('/api/v1/logs/' + cid, '_blank');
}
function viewHtml() {
    const cid = document.getElementById('cid').value.trim();
    if (cid) window.open('/api/v1/logs/' + cid + '/html', '_blank');
}
loadRecent();
setInterval(loadRecent, 10000);
</script></body></html>"""
