"""
v4.0: 技术实验室 API — RAG调试、Prompt对比等
"""
import time
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tech", tags=["tech-lab"])


class RagDebugRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="待检索文本")
    top_k: int = Field(default=8, ge=1, le=20)


@router.post("/rag-debug")
async def rag_debug(request: RagDebugRequest):
    """
    RAG六层检索调试 — 输入文本, 逐步展示每层检索的中间结果

    六层:
      1. BM25 关键词检索
      2. ChromaDB 向量检索
      3. RRF 融合排序
      4. CrossEncoder 重排
      5. AgenticRAG 查询改写 + Self-RAG评估
      6. GraphRAG 知识图谱扩展
    """
    text = request.text.strip()
    top_k = request.top_k
    layers = []
    total_start = time.time()

    # ── Layer 1: BM25 关键词检索 ──
    t1 = time.time()
    bm25_results = []
    bm25_error = None
    try:
        from memory.chroma_service import get_chroma_service
        from memory.hybrid_retriever import get_hybrid_retriever
        # R21: 显式关联 ChromaService 并同步 BM25 索引（否则 bm25 永不初始化、恒空）
        hr = get_hybrid_retriever(get_chroma_service())
        await hr.ensure_connected()
        if hr.bm25 and hr.bm25._initialized:
            bm25_raw = hr.bm25.search(text, top_k)
            bm25_results = [
                {"doc_id": r.id, "score": round(r.score, 4),
                 "content": (r.content or "")[:200]}
                for r in bm25_raw
            ]
    except Exception as e:
        bm25_error = str(e)[:200]
    layers.append({
        "layer": 1, "name": "BM25 关键词检索",
        "icon": "🔤", "description": "基于中文 bigram+unigram 分词, BM25(k1=1.5, b=0.75) 稀疏检索",
        "duration_ms": round((time.time() - t1) * 1000, 1),
        "result_count": len(bm25_results),
        "top_results": bm25_results[:5],
        "error": bm25_error,
    })

    # ── Layer 2: ChromaDB 向量检索 ──
    t2 = time.time()
    vector_results = []
    vector_error = None
    try:
        from memory.chroma_service import get_chroma_service
        cs = get_chroma_service()
        vector_raw = await cs.search_similar(text, top_k=top_k)
        vector_results = [
            {"doc_id": r.get("id", r.get("doc_id", "")),
             "score": round(r.get("score", r.get("distance", 0)), 4),
             "content": str(r.get("content", r.get("text", "")))[:200]}
            for r in vector_raw
        ]
    except Exception as e:
        vector_error = str(e)[:200]
    layers.append({
        "layer": 2, "name": "ChromaDB 向量检索",
        "icon": "🧬", "description": "bge-small-zh-v1.5 384维 embedding, 余弦相似度检索",
        "duration_ms": round((time.time() - t2) * 1000, 1),
        "result_count": len(vector_results),
        "top_results": vector_results[:5],
        "error": vector_error,
    })

    # ── Layer 3: RRF 融合排序 ──
    t3 = time.time()
    rrf_results = []
    rrf_error = None
    try:
        if bm25_results or vector_results:
            from memory.chroma_service import get_chroma_service
            from memory.hybrid_retriever import get_hybrid_retriever
            hr = get_hybrid_retriever(get_chroma_service())
            fused = await hr.search(text, top_k=top_k) if hr.bm25._initialized else []
            rrf_results = [
                {"doc_id": r.id, "score": round(r.score, 4),
                 "content": (r.content or "")[:200]}
                for r in (fused or [])[:5]
            ]
    except Exception as e:
        rrf_error = str(e)[:200]
    layers.append({
        "layer": 3, "name": "RRF 融合排序",
        "icon": "🔀", "description": "Reciprocal Rank Fusion(k=60) → 去重 → 时间衰减(7天半衰) → 分层采样(每类≥1条)",
        "duration_ms": round((time.time() - t3) * 1000, 1),
        "result_count": len(rrf_results),
        "top_results": rrf_results[:5],
        "error": rrf_error,
    })

    # ── Layer 4: CrossEncoder 重排 ──
    t4 = time.time()
    rerank_results = []
    rerank_error = None
    try:
        if rrf_results:
            from memory.hybrid_retriever import RetrievalResult, get_hybrid_retriever
            rs = get_hybrid_retriever().reranker
            # rerank 期望 RetrievalResult 列表（含 .content/.score），将 RRF dict 转回对象
            docs_for_rerank = [
                RetrievalResult(id=r["doc_id"], content=r["content"], score=r["score"])
                for r in rrf_results[:5]
            ]
            reranked_raw = rs.rerank(text, docs_for_rerank, top_k=min(top_k, len(docs_for_rerank)))
            rerank_results = [
                {"doc_id": r.id, "score": round(r.score, 4),
                 "content": (r.content or "")[:200],
                 "score_formula": "cross_encoder × 0.7 + rrf_score × 0.3"}
                for r in reranked_raw[:5]
            ]
    except Exception as e:
        rerank_error = str(e)[:200]
    layers.append({
        "layer": 4, "name": "CrossEncoder 重排",
        "icon": "🎯", "description": "bge-reranker-v2-m3 Cross-Encoder, 精确语义匹配重排",
        "duration_ms": round((time.time() - t4) * 1000, 1),
        "result_count": len(rerank_results),
        "top_results": rerank_results[:5],
        "error": rerank_error,
    })

    # ── Layer 5: AgenticRAG 查询改写 + Self-RAG评估 ──
    t5 = time.time()
    agentic_result = None
    agentic_error = None
    try:
        from memory.agentic_rag import get_agentic_rag
        ar = get_agentic_rag()
        query_rewrites = {}
        for strategy in ["expand", "compress", "denoise"]:
            rw = ar.query_rewriter.rewrite(text, strategy)
            query_rewrites[strategy] = {
                "rewritten": rw.rewritten,
                "strategy": rw.strategy,
                "reason": rw.reason,
                "changes": [],
            }
        agentic_result = {
            "original_query": text,
            "rewrites": query_rewrites,
        }
    except Exception as e:
        agentic_error = str(e)[:200]
    layers.append({
        "layer": 5, "name": "AgenticRAG 查询改写",
        "icon": "🤖", "description": "expand(扩展) → compress(压缩) → denoise(对抗还原) 三策略 → 自适应路由",
        "duration_ms": round((time.time() - t5) * 1000, 1),
        "result_count": len(agentic_result.get("rewrites", {})) if agentic_result else 0,
        "top_results": [agentic_result] if agentic_result else [],
        "error": agentic_error,
    })

    # ── Layer 6: GraphRAG 知识图谱扩展 ──
    t6 = time.time()
    graph_result = None
    graph_error = None
    try:
        from memory.graph_rag import get_graph_rag
        gr = get_graph_rag()
        # 通过关键词推测可能的违规类型
        inferred_types = _infer_violation_types(text)
        graph_insights = gr.get_insights(inferred_types) if inferred_types else {}
        graph_result = {
            "inferred_types": inferred_types,
            "related_types": graph_insights.get("related_violation_types", []),
            "expansion_query": graph_insights.get("expansion_query", ""),
            "graph_stats": graph_insights.get("stats", {}),
        }
    except Exception as e:
        graph_error = str(e)[:200]
    layers.append({
        "layer": 6, "name": "GraphRAG 知识图谱",
        "icon": "🔗", "description": "违规类型 BFS 关联 → hop衰减 → 多跳遍历 → 账号-内容异构图",
        "duration_ms": round((time.time() - t6) * 1000, 1),
        "result_count": len(graph_result.get("related_types", [])) if graph_result else 0,
        "top_results": [graph_result] if graph_result else [],
        "error": graph_error,
    })

    return {
        "query": text,
        "total_duration_ms": round((time.time() - total_start) * 1000, 1),
        "layers": layers,
    }


class PromptCompareRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    prompt_a: str = Field(..., min_length=1, description="System Prompt 版本 A")
    prompt_b: str = Field(..., min_length=1, description="System Prompt 版本 B")
    model: str = Field(default="deepseek-v4-flash")


@router.post("/prompt-compare")
async def prompt_compare(request: PromptCompareRequest):
    """
    Prompt 版本对比 — 同一条文本用两个 Prompt 分别调用 LLM, 返回对比结果
    """
    import os
    import json

    results = {"text": request.text, "model": request.model}

    async def call_llm(system_prompt: str, label: str) -> dict:
        t0 = time.time()
        try:
            api_key = os.getenv("DEEPSEEK_API_KEY", "")
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            if not api_key:
                # 模拟结果 (无 API Key 时)
                return {
                    "label": label,
                    "decision": "PASS",
                    "violation_type": "none",
                    "confidence": 0.0,
                    "reasoning": f"[模拟] 使用Prompt版本: {label} (未配置API Key, 此为模拟结果)",
                    "token_cost": 0,
                    "duration_ms": 0,
                    "error": None,
                }

            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{base_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": request.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": request.text},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 500,
                    },
                )
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})

                # 解析 LLM 输出
                decision = "PASS"
                confidence = 0.0
                violation_type = "none"
                reasoning = content[:300]
                if "REJECT" in content:
                    decision = "REJECT"
                    confidence = 0.8
                elif "REVIEW" in content:
                    decision = "REVIEW"
                    confidence = 0.5

                return {
                    "label": label,
                    "decision": decision,
                    "violation_type": violation_type,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "token_cost": usage.get("total_tokens", 0),
                    "duration_ms": round((time.time() - t0) * 1000, 0),
                    "error": None,
                }
        except Exception as e:
            return {
                "label": label,
                "decision": "ERROR",
                "violation_type": None,
                "confidence": 0,
                "reasoning": "",
                "token_cost": 0,
                "duration_ms": round((time.time() - t0) * 1000, 0),
                "error": str(e)[:200],
            }

    import asyncio
    result_a, result_b = await asyncio.gather(
        call_llm(request.prompt_a, "A"),
        call_llm(request.prompt_b, "B"),
    )

    results["version_a"] = result_a
    results["version_b"] = result_b
    results["diff"] = {
        "same_decision": result_a.get("decision") == result_b.get("decision"),
        "confidence_diff": round(abs(
            result_a.get("confidence", 0) - result_b.get("confidence", 0)
        ), 2),
        "a_decision": result_a.get("decision"),
        "b_decision": result_b.get("decision"),
    }

    return results


def _infer_violation_types(text: str) -> list:
    """从文本关键词推测可能的违规类型"""
    types = []
    kw_map = {
        "advertisement": ["微信", "加群", "扫码", "赚钱", "代理"],
        "harassment": ["傻逼", "你妈", "废物", "去死", "垃圾"],
        "violence": ["杀", "砍", "死", "打", "揍", "暴力", "刀", "枪", "威胁", "报复"],
        "false_info": ["谣言", "虚假", "中奖", "客服", "造谣"],
        "porn": ["裸", "骚", "色", "约炮", "性"],
        "politics": ["习近平", "台独", "港独"],
        "crime": ["毒品", "偷", "盗", "诈骗", "赌博", "管制刀具", "贩"],
        "privacy": ["隐私", "个人信息", "密码", "银行卡", "窃取", "人肉"],
        "discrimination": ["歧视", "低贱", "劣等"],
    }
    for vtype, keywords in kw_map.items():
        for kw in keywords:
            if kw in text:
                types.append(vtype)
                break
    return types[:5] if types else ["general"]


# ═══════════════════════════════════════════════════════════
# 全流程可视化 API
# ═══════════════════════════════════════════════════════════

@router.get("/pipeline-flow")
async def get_pipeline_flow():
    """
    返回 Multi-Agent 审核管线的完整拓扑结构，供前端可视化渲染。

    覆盖全部模态 (text/image/audio/video/multi-modal) 的完整链路，
    标注每个节点的输入/输出、Agent 类型、处理逻辑。
    """
    pipeline = {
        "name": "Multi-Agent 内容审核管线（三车道）",
        "description": "从内容输入到最终决策的完整审核链路：分诊台三车道分流 → 快车道小模型 / 标准深度分析 / 大脑仲裁 → ReAct 自校准（条件）→ 综合评估 → 人工复核（条件）→ 输出",
        "modalities": {
            "text": {
                "name": "文本审核（三车道）",
                "icon": "📝",
                "description": "纯文本审核：分诊台三车道分流 → low 快车道直判 / high 大脑仲裁 / med 深度分析 → ReAct 自校准（条件）→ 综合评估（含黑灰产聚合）→ 人工复核（条件）→ 输出",
                "pipeline": [
                    {
                        "id": "input",
                        "name": "内容输入",
                        "icon": "📥",
                        "type": "entry",
                        "description": "接收用户提交的文本内容",
                        "input": "text (string)",
                        "output": "ModerationState (content.text)",
                    },
                    {
                        "id": "supervisor",
                        "name": "Supervisor 调度器",
                        "icon": "🧭",
                        "type": "router",
                        "description": "内容分类 + 初始化 state，然后交给分诊台",
                        "input": "ModerationState",
                        "output": "next_node: triage",
                    },
                    {
                        "id": "triage",
                        "name": "分诊台 (TriageEngine)",
                        "icon": "🚦",
                        "type": "router",
                        "description": "ModelRouter 风险×复杂度联合估计 → 三车道分流: low(复杂度<3 且 ≤150字) / med(默认) / high(复杂度≥8 或 ≥800字 或 ≥5中危信号)",
                        "input": "ModerationState (content.text)",
                        "output": "_tier: low / med / high",
                        "condition": "tier=low → fast_lane; tier=high → brain; tier=med → text_agent",
                    },
                    {
                        "id": "fast_lane",
                        "name": "FastLane 快车道 (Qwen2.5:7b)",
                        "icon": "⚡",
                        "type": "agent",
                        "description": "本地小模型判定。小模型采纳则直接出决策省大模型；无信号/低置信(PASS<0.8 或类型矛盾) → 升级 text_agent 防漏判",
                        "input": "_tier=low 的内容",
                        "output": "text_result + final_decision (直接出决策)",
                        "model": "qwen2.5:7b (Ollama 本地) / RuleSmallJudge",
                        "condition": "tier=low。PASS 直接采纳即 END（不经下游）；needs_upgrade → 升级 text_agent",
                    },
                    {
                        "id": "brain",
                        "name": "Brain 大脑仲裁",
                        "icon": "🧠",
                        "type": "decision",
                        "description": "确定性规则版决策（可审计）: 规划 / 仲裁 / 升级(建议人工) / 终止建议(terminate_suggested)",
                        "input": "_triage (risk/complexity)",
                        "output": "_brain_decision: {decisions, terminate_suggested}",
                        "condition": "tier=high。裁决后经类型路由进入 text_agent 深度审核",
                    },
                    {
                        "id": "text_agent",
                        "name": "TextAgent 文本分析",
                        "icon": "🧠",
                        "type": "agent",
                        "description": "关键词 AC 自动机 + DeepSeek LLM 语义分析 → 13 类违规类型/置信度/风险分（med 主路径 / high 深度审核 / low 升级共用）",
                        "input": "ModerationState (content.text)",
                        "output": "text_result: {violation_type, confidence, risk_score, reasoning, tags}",
                        "model": "deepseek-v4-flash",
                        "tools": ["keyword_check (AC自动机)", "similar_case_search (ChromaDB)"],
                    },
                    {
                        "id": "react_agent",
                        "name": "ReAct 自校准",
                        "icon": "🔄",
                        "type": "agent",
                        "description": "低置信/对抗样本的二次深度分析，Phase 2 自校准后进入风险评估（v4.2 起 reflexion 合并于此）",
                        "input": "text_result",
                        "output": "text_result.react_enhanced + 修正后的违规类型/置信度",
                        "condition": "violation_type≠none 且 (conf<0.6 或 is_adversarial) 且未深挖",
                    },
                    {
                        "id": "risk_agent",
                        "name": "RiskAgent 综合评估 + 终止双签",
                        "icon": "📊",
                        "type": "decision",
                        "description": "综合所有风险分量 → 加权总分 → PASS/REVIEW/REJECT；黑灰产信号由各 Agent 内嵌检测后在此聚合（非独立节点）；终止双签 3 条确定性规则强制 REJECT",
                        "input": "text_result + blackhat_result(聚合) + _brain_decision",
                        "output": "final_risk + final_decision + _human_review 标记",
                        "thresholds": "review/reject 阈值动态加载; 终止双签 3 条确定性规则",
                    },
                    {
                        "id": "human_in_loop",
                        "name": "人工审核 (HITL)",
                        "icon": "👤",
                        "type": "decision",
                        "description": "LangGraph interrupt 真挂起 → /review 人工判定 → Command(resume) 恢复，注入 human_decision → risk_agent 复核",
                        "input": "risk_agent 设置的 _human_review.required=PENDING",
                        "output": "human_decision → risk_agent 复核 → END",
                        "condition": "risk_agent 标记 _human_review.required 且状态 PENDING",
                    },
                    {
                        "id": "output",
                        "name": "决策输出",
                        "icon": "📤",
                        "type": "exit",
                        "description": "最终决策: PASS (放行) / REVIEW (人工复核) / REJECT (拒绝)",
                        "input": "final_risk + final_decision",
                        "output": "API 响应 + 入库 (moderation_records + ChromaDB + GraphRAG)",
                    },
                ],
            },
            "image": {
                "name": "图片审核",
                "icon": "🖼️",
                "description": "图片内容审核：VL 视觉分析 + OCR 文字提取 → ReAct 自校准（条件）→ 综合评估（含黑灰产聚合）→ 人工复核（条件）→ 输出",
                "pipeline": [
                    {
                        "id": "input",
                        "name": "内容输入",
                        "icon": "📥",
                        "type": "entry",
                        "description": "接收用户提交的图片文件 (JPEG/PNG/GIF/WebP)",
                        "input": "image (file)",
                        "output": "ModerationState (content.image)",
                    },
                    {
                        "id": "supervisor",
                        "name": "Supervisor 调度器",
                        "icon": "🧭",
                        "type": "router",
                        "description": "content_type=image → 分诊台（非文本直接 med 车道）",
                        "input": "ModerationState",
                        "output": "next_node: triage",
                    },
                    {
                        "id": "triage",
                        "name": "分诊台 (非文本 → med)",
                        "icon": "🚦",
                        "type": "router",
                        "description": "非文本内容不经过文本分诊，直接走 med 标准车道 → 类型路由",
                        "input": "ModerationState",
                        "output": "_tier=med → image_agent",
                    },
                    {
                        "id": "image_agent",
                        "name": "ImageAgent 图片分析",
                        "icon": "👁️",
                        "type": "agent",
                        "description": "VL 模型视觉理解 + OCR 文字提取 + 多图并行 + VL信号卡压缩；黑灰产对抗检测内嵌",
                        "input": "ModerationState (content.image)",
                        "output": "image_result: {violation_type, confidence, risk_score, ocr_text, tags}",
                        "model": "deepseek-v4-flash (VL)",
                        "tools": ["ocr_extract", "multi_image_parallel"],
                    },
                    {
                        "id": "react_agent",
                        "name": "ReAct 自校准",
                        "icon": "🔄",
                        "type": "agent",
                        "description": "低置信/对抗图片二次深度分析",
                        "input": "image_result",
                        "output": "image_result.react_enhanced",
                        "condition": "violation_type≠none 且 (conf<0.6 或 is_adversarial) 且未深挖",
                    },
                    {
                        "id": "risk_agent",
                        "name": "RiskAgent 综合评估",
                        "icon": "📊",
                        "type": "decision",
                        "description": "综合 image_result + 黑灰产信号聚合（内嵌检测，非独立节点）→ 加权评分 → 决策",
                        "input": "image_result + blackhat_result(聚合)",
                        "output": "final_risk: {overall_score, decision}",
                    },
                    {
                        "id": "human_in_loop",
                        "name": "人工审核 (HITL)",
                        "icon": "👤",
                        "type": "decision",
                        "description": "risk_agent 标记模糊边界(0.25~0.70)时真挂起人工复核",
                        "input": "_human_review.required=PENDING",
                        "output": "human_decision → risk_agent 复核 → END",
                        "condition": "risk_agent 标记 _human_review.required 且状态 PENDING",
                    },
                    {
                        "id": "output",
                        "name": "决策输出",
                        "icon": "📤",
                        "type": "exit",
                        "description": "PASS / REVIEW / REJECT → 入库",
                        "input": "final_risk",
                        "output": "API 响应 + DB + ChromaDB",
                    },
                ],
            },
            "audio": {
                "name": "音频审核",
                "icon": "🎤",
                "description": "音频内容审核：ASR 转写 + LLM 语义分析 + 说话人分段 → ReAct 自校准（条件）→ 综合评估（含黑灰产聚合）→ 人工复核（条件）→ 输出",
                "pipeline": [
                    {
                        "id": "input",
                        "name": "内容输入",
                        "icon": "📥",
                        "type": "entry",
                        "description": "接收用户提交的音频文件 (WAV/MP3/M4A)",
                        "input": "audio (file)",
                        "output": "ModerationState (content.audio)",
                    },
                    {
                        "id": "supervisor",
                        "name": "Supervisor 调度器",
                        "icon": "🧭",
                        "type": "router",
                        "description": "content_type=audio → 分诊台（非文本直接 med 车道）",
                        "input": "ModerationState",
                        "output": "next_node: triage",
                    },
                    {
                        "id": "triage",
                        "name": "分诊台 (非文本 → med)",
                        "icon": "🚦",
                        "type": "router",
                        "description": "非文本内容不经过文本分诊，直接走 med 标准车道 → 类型路由",
                        "input": "ModerationState",
                        "output": "_tier=med → audio_agent",
                    },
                    {
                        "id": "audio_agent",
                        "name": "AudioAgent 音频分析",
                        "icon": "🎙️",
                        "type": "agent",
                        "description": "FunASR 语音转文字 → LLM 语义分析 → 说话人分段 → 信号卡压缩 (大文件)；黑灰产对抗检测内嵌",
                        "input": "ModerationState (content.audio)",
                        "output": "audio_result: {violation_type, confidence, risk_score, transcribed_text, speaker_segments}",
                        "model": "deepseek-v4-flash (via transcribed text)",
                        "tools": ["funasr_asr", "speaker_diarization", "signal_card_compress"],
                    },
                    {
                        "id": "react_agent",
                        "name": "ReAct 自校准",
                        "icon": "🔄",
                        "type": "agent",
                        "description": "低置信/对抗音频二次深度分析",
                        "input": "audio_result",
                        "output": "audio_result.react_enhanced",
                        "condition": "violation_type≠none 且 (conf<0.6 或 is_adversarial) 且未深挖",
                    },
                    {
                        "id": "risk_agent",
                        "name": "RiskAgent 综合评估",
                        "icon": "📊",
                        "type": "decision",
                        "description": "audio_result + 黑灰产信号聚合（内嵌检测，非独立节点）→ 加权评分 → 决策",
                        "input": "audio_result + blackhat_result(聚合)",
                        "output": "final_risk: {overall_score, decision}",
                    },
                    {
                        "id": "human_in_loop",
                        "name": "人工审核 (HITL)",
                        "icon": "👤",
                        "type": "decision",
                        "description": "risk_agent 标记模糊边界时真挂起人工复核",
                        "input": "_human_review.required=PENDING",
                        "output": "human_decision → risk_agent 复核 → END",
                        "condition": "risk_agent 标记 _human_review.required 且状态 PENDING",
                    },
                    {
                        "id": "output",
                        "name": "决策输出",
                        "icon": "📤",
                        "type": "exit",
                        "description": "PASS / REVIEW / REJECT → 入库",
                        "input": "final_risk",
                        "output": "API 响应 + DB + ChromaDB",
                    },
                ],
            },
            "video": {
                "name": "视频审核",
                "icon": "🎬",
                "description": "视频审核 = 截帧视觉分析 + 音频轨道转写 + 内部跨模态融合 → ReAct 自校准（条件）→ 综合评估 → 人工复核（条件）→ 输出",
                "pipeline": [
                    {
                        "id": "input",
                        "name": "内容输入",
                        "icon": "📥",
                        "type": "entry",
                        "description": "接收用户提交的视频文件 (MP4/AVI/MOV)",
                        "input": "video (file)",
                        "output": "ModerationState (content.video), _is_multimodal=True",
                    },
                    {
                        "id": "supervisor",
                        "name": "Supervisor 调度器",
                        "icon": "🧭",
                        "type": "router",
                        "description": "content_type=video → 分诊台（非文本直接 med 车道，多模态标记）",
                        "input": "ModerationState",
                        "output": "next_node: triage",
                    },
                    {
                        "id": "triage",
                        "name": "分诊台 (非文本 → med)",
                        "icon": "🚦",
                        "type": "router",
                        "description": "非文本内容不经过文本分诊，直接走 med 标准车道 → 类型路由",
                        "input": "ModerationState",
                        "output": "_tier=med → video_agent",
                    },
                    {
                        "id": "video_agent",
                        "name": "VideoAgent 视频分析（含跨模态融合）",
                        "icon": "🎞️",
                        "type": "agent",
                        "description": "关键帧抽取 → VL 逐帧审核 → 音频轨道 ASR 转写 → 内部跨模态融合 (MMCC → 联合风险评分)",
                        "input": "ModerationState (content.video)",
                        "output": "video_result: {overall_risk_score, frames[], audio_text, fusion_summary}",
                        "model": "deepseek-v4-flash (VL per frame)",
                        "tools": ["frame_extract", "vl_frame_analyze", "audio_track_extract", "cross_modal_fusion"],
                    },
                    {
                        "id": "react_agent",
                        "name": "ReAct 自校准",
                        "icon": "🔄",
                        "type": "agent",
                        "description": "低置信/对抗视频二次深度分析",
                        "input": "video_result",
                        "output": "video_result.react_enhanced",
                        "condition": "violation_type≠none 且 (conf<0.6 或 is_adversarial) 且未深挖",
                    },
                    {
                        "id": "risk_agent",
                        "name": "RiskAgent 综合评估",
                        "icon": "📊",
                        "type": "decision",
                        "description": "video_result (含融合分) + 黑灰产信号聚合（内嵌检测，非独立节点）→ 加权评分 → 决策",
                        "input": "video_result + blackhat_result(聚合)",
                        "output": "final_risk: {overall_score, decision}",
                    },
                    {
                        "id": "human_in_loop",
                        "name": "人工审核 (HITL)",
                        "icon": "👤",
                        "type": "decision",
                        "description": "risk_agent 标记模糊边界时真挂起人工复核",
                        "input": "_human_review.required=PENDING",
                        "output": "human_decision → risk_agent 复核 → END",
                        "condition": "risk_agent 标记 _human_review.required 且状态 PENDING",
                    },
                    {
                        "id": "output",
                        "name": "决策输出",
                        "icon": "📤",
                        "type": "exit",
                        "description": "PASS / REVIEW / REJECT → 入库",
                        "input": "final_risk",
                        "output": "API 响应 + DB + ChromaDB",
                    },
                ],
            },
            "multi_modal": {
                "name": "多模态混合审核",
                "icon": "🔀",
                "description": "同时提交文本+图片+音频等多模态内容：Planner 5-Phase 并行编排 → 文件解析 → 文本增强 → ReAct 自校准（条件）→ 综合评估（含黑灰产聚合）→ 人工复核（条件）→ 输出",
                "pipeline": [
                    {
                        "id": "input",
                        "name": "多模态输入",
                        "icon": "📥",
                        "type": "entry",
                        "description": "同时接收文本 + 多个文件 (图片/音频/视频)",
                        "input": "text + files[]",
                        "output": "ModerationState (content.text + content.files)",
                    },
                    {
                        "id": "supervisor",
                        "name": "Supervisor 并行调度",
                        "icon": "🧭",
                        "type": "router",
                        "description": "content_type=multi_modal → 分诊台（非文本直接 med 车道）",
                        "input": "ModerationState",
                        "output": "next_node: triage",
                    },
                    {
                        "id": "triage",
                        "name": "分诊台 (非文本 → med)",
                        "icon": "🚦",
                        "type": "router",
                        "description": "多模态内容直接走 med 标准车道 → 类型路由 → Planner",
                        "input": "ModerationState",
                        "output": "_tier=med → planner",
                    },
                    {
                        "id": "planner",
                        "name": "Planner 多模态编排 (5-Phase)",
                        "icon": "🧩",
                        "type": "parallel",
                        "description": "Phase1 内容解析 / Phase2 独立模态并行分析 / Phase3 上下文融合(OCR/ASR→文本增强) / Phase4 跨模态关联(图文矛盾/互证/OCR融合) / Phase5 结果输出",
                        "input": "ModerationState",
                        "output": "text_result + image_result + audio_result + video_result + _planner_processed",
                        "parallel_agents": ["text_agent", "image_agent", "audio_agent", "video_agent"],
                    },
                    {
                        "id": "file_agent",
                        "name": "FileAgent 文件解析",
                        "icon": "📁",
                        "type": "agent",
                        "description": "解析 docx/zip 等文件内嵌内容，Planner 后的固定补充节点",
                        "input": "content.files",
                        "output": "解析出的文本/图片列表",
                    },
                    {
                        "id": "text_agent",
                        "name": "TextAgent 文本语义分析",
                        "icon": "🧠",
                        "type": "agent",
                        "description": "对融合后的文本做语义分析 → 违规类型/置信度/风险分",
                        "input": "ModerationState (content.text)",
                        "output": "text_result: {violation_type, confidence, risk_score, reasoning, tags}",
                        "model": "deepseek-v4-flash",
                    },
                    {
                        "id": "react_agent",
                        "name": "ReAct 自校准",
                        "icon": "🔄",
                        "type": "agent",
                        "description": "多模态结果低置信/对抗时二次深度分析",
                        "input": "各模态 result",
                        "output": "react_enhanced 修正",
                        "condition": "violation_type≠none 且 (conf<0.6 或 is_adversarial) 且未深挖",
                    },
                    {
                        "id": "risk_agent",
                        "name": "RiskAgent 综合评估",
                        "icon": "📊",
                        "type": "decision",
                        "description": "多模态分量加权 + 黑灰产信号聚合（内嵌检测，非独立节点）→ 综合决策",
                        "input": "所有 agent 结果 + blackhat_result(聚合)",
                        "output": "final_risk: {overall_score, decision, violation_types}",
                    },
                    {
                        "id": "human_in_loop",
                        "name": "人工审核 (HITL)",
                        "icon": "👤",
                        "type": "decision",
                        "description": "risk_agent 标记模糊边界时真挂起人工复核",
                        "input": "_human_review.required=PENDING",
                        "output": "human_decision → risk_agent 复核 → END",
                        "condition": "risk_agent 标记 _human_review.required 且状态 PENDING",
                    },
                    {
                        "id": "output",
                        "name": "决策输出",
                        "icon": "📤",
                        "type": "exit",
                        "description": "PASS / REVIEW / REJECT → 入库",
                        "input": "final_risk",
                        "output": "API 响应 + DB + ChromaDB + GraphRAG",
                    },
                ],
            },
        },
        "shared_components": {
            "rag_pipeline": {
                "name": "RAG 六层检索增强",
                "icon": "🔍",
                "description": "BM25 → Vector → RRF → CrossEncoder → AgenticRAG → GraphRAG",
                "layers": ["BM25关键词", "ChromaDB向量", "RRF融合", "CrossEncoder重排", "AgenticRAG改写", "GraphRAG图谱"],
            },
            "termination_check": {
                "name": "终止双签 (TerminationChecker)",
                "icon": "🛑",
                "description": "brain 软签(terminate_suggested) + 确定性硬签(3 条规则)，任一命中强制 REJECT",
                "rules": ["高危类型(violence/crime/illegal) 且风险分≥0.65", "风险分≥0.9 硬阈值", "大脑建议终止 且 风险分≥0.75 双签通过"],
            },
            "human_in_loop": {
                "name": "人工审核 (HITL)",
                "icon": "👤",
                "description": "LangGraph interrupt 真挂起，/review 人工判定后 Command(resume) 恢复",
                "trigger": "终判 REVIEW / Agent 不确定 / 大脑升级建议",
                "result": "写入 annotation_records(source=human, weight=3.0) + pipeline HUMAN_RESUME 尾日志",
            },
        },
    }

    # v4.3: 动态注入 Skill 信息 — 从 SkillRegistry 验证并补充
    _enrich_pipeline_with_skills(pipeline)

    return pipeline


def _enrich_pipeline_with_skills(pipeline: dict):
    """
    从 SkillRegistry 动态加载 Skill 信息，注入到管线节点。

    - 如果节点已有硬编码 skills，以 Registry 实际存在的 Skill 为准做过滤
    - 如果 Registry 不可用，保留硬编码的 skills 不做修改
    """
    try:
        from agent_moderation.skill_registry import get_skill_registry
        registry = get_skill_registry()
        available_skills = {s.name for s in registry.list_skills()}
    except Exception:
        return  # Registry 不可用，保持硬编码数据

    # Agent 节点 ID → 预期 Skill 名称（设计约定，由 Registry 验证）
    NODE_SKILL_MAPPING = {
        "text_agent": ["keyword-check", "history-search"],
        "image_agent": ["image-hash"],
        "audio_agent": ["keyword-check"],
    }

    for modality_name, modality_data in pipeline.get("modalities", {}).items():
        for node in modality_data.get("pipeline", []):
            node_id = node.get("id", "")
            expected = NODE_SKILL_MAPPING.get(node_id, [])
            if expected:
                # 过滤：只保留 Registry 中实际存在的 Skill
                validated = [s for s in expected if s in available_skills]
                node["skills"] = validated if validated else expected
                if validated and len(validated) < len(expected):
                    missing = set(expected) - set(validated)
                    import logging
                    logging.getLogger(__name__).debug(
                        f"Pipeline node '{node_id}': skills {missing} not in Registry"
                    )


# ═══════════════════════════════════════════════════════════
# Agent 提示词查询 API
# ═══════════════════════════════════════════════════════════

@router.get("/prompts")
async def list_agent_prompts():
    """
    返回所有 Agent 当前使用的提示词，供 Prompt 调试工坊展示和对照实验。

    包含:
      - 提示词名称、版本、模型
      - 完整 system_prompt 文本
      - 适用的 Agent 和模态
    """
    prompts = []

    # 从 PromptRegistry 加载所有已注册提示词
    try:
        from optimization.prompt_optimizer import get_prompt_registry
        registry = get_prompt_registry()
        for name in sorted(registry._prompts.keys()):
            active_pv = registry.get_active(name)
            if active_pv:
                prompts.append({
                    "name": active_pv.name,
                    "version": active_pv.version,
                    "model": active_pv.model,
                    "system_prompt": active_pv.system_prompt,
                    "optimizer": active_pv.optimizer,
                    "metrics": active_pv.metrics,
                    "created_at": active_pv.created_at,
                })
    except Exception as e:
        logger.warning(f"Failed to load prompts from registry: {e}")

    # 回退: 从 JSON 文件加载
    if not prompts:
        prompts = _load_prompts_from_files()

    return {"prompts": prompts, "total": len(prompts)}


def _load_prompts_from_files() -> list:
    """从 prompts/ 目录加载 JSON 提示词文件 (PromptRegistry 不可用时的回退)"""
    import os as _os
    import json as _json
    prompts = []
    prompts_dir = _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "prompts")
    prompts_dir = _os.path.abspath(prompts_dir)
    if _os.path.isdir(prompts_dir):
        for fname in sorted(_os.listdir(prompts_dir)):
            if fname.endswith(".json"):
                fpath = _os.path.join(prompts_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = _json.load(f)
                    prompts.append({
                        "name": data.get("name", fname),
                        "version": data.get("version", "0.0.0"),
                        "model": data.get("model", ""),
                        "system_prompt": data.get("system_prompt", ""),
                        "optimizer": data.get("optimizer", ""),
                        "metrics": data.get("metrics", {}),
                        "created_at": data.get("created_at", ""),
                    })
                except Exception as e:
                    logger.warning(f"Failed to load prompt file {fname}: {e}")
    return prompts


# ===== v4.1: MCP 工具 + Skill 知识库 API =====


@router.get("/tools")
async def list_mcp_tools():
    """
    列出所有注册的 MCP 工具（含 JSON Schema 参数定义）。

    从 MCPToolRegistry 动态获取，不再硬编码。
    """
    try:
        from mcp_servers.registry import get_tool_registry
        registry = get_tool_registry()
        schemas = registry.get_tool_schemas()

        # 附加访问控制信息
        from mcp_servers.access_control import get_access_controller
        acl = get_access_controller()

        tools = []
        for s in schemas:
            tool_name = s.get("name", "")
            tools.append({
                "name": tool_name,
                "description": s.get("description", ""),
                "inputSchema": s.get("inputSchema", {}),
                "allowed_agents": acl.get_tool_agents(tool_name),
            })

        return {"tools": tools, "total": len(tools)}
    except Exception as e:
        logger.warning(f"Failed to list MCP tools: {e}")
        return {"tools": [], "total": 0, "error": str(e)[:200]}


@router.get("/skills")
async def list_skills():
    """
    列出所有 Skill 元数据（L1 渐进加载）。

    从 SkillRegistry 动态获取，含激活统计。
    """
    try:
        from agent_moderation.skill_registry import get_skill_registry
        registry = get_skill_registry()
        metas = registry.list_skills()
        metrics = registry.get_metrics()

        skills = []
        for meta in metas:
            skills.append({
                "name": meta.name,
                "description": meta.description,
                "version": meta.version,
                "invocation_mode": meta.invocation_mode,
                "mcp_tools": meta.mcp_tools,
                "triggers": meta.triggers,
                "tags": meta.tags,
                "activations": metrics.get(meta.name, {}).get("activations", 0),
            })

        return {
            "skills": skills,
            "total": len(skills),
            "l1_token_cost": registry.l1_token_cost,
        }
    except Exception as e:
        logger.warning(f"Failed to list skills: {e}")
        return {"skills": [], "total": 0, "error": str(e)[:200]}


@router.get("/skills/{skill_name}")
async def get_skill_detail(skill_name: str):
    """
    获取单个 Skill 的完整内容（L1 + L2 + L3），带激活计数和相关路由日志。
    """
    try:
        from agent_moderation.skill_registry import get_skill_registry
        registry = get_skill_registry()
        skill = registry.get_skill(skill_name)

        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

        # 获取相关的路由日志
        related_logs = []
        try:
            from sqlalchemy import select, desc, or_
            from db.connection import get_session_factory
            from db.models import SkillRoutingLog

            session_factory = get_session_factory()
            async with session_factory() as session:
                # 查找该 Skill 出现在 filtered/ranked/selected 中的日志
                query = select(SkillRoutingLog)
                query = query.order_by(desc(SkillRoutingLog.timestamp))
                query = query.limit(20)
                result = await session.execute(query)
                logs = result.scalars().all()

                # 过滤出与该 Skill 相关的日志
                for log in logs:
                    if (skill_name in log.selected_skills or
                        skill_name in log.ranked_skills or
                        skill_name in log.filtered_skills):
                        related_logs.append({
                            "id": log.id,
                            "content_id": log.content_id,
                            "agent": log.agent,
                            "query": log.query,
                            "content_type": log.content_type,
                            "filtered_skills": log.filtered_skills,
                            "ranked_skills": log.ranked_skills,
                            "selected_skills": log.selected_skills,
                            "timestamp": log.timestamp,
                            "was_selected": skill_name in log.selected_skills,
                            "was_ranked": skill_name in log.ranked_skills,
                            "was_filtered": skill_name in log.filtered_skills,
                        })
        except Exception as e:
            logger.warning(f"Failed to load related logs for {skill_name}: {e}")

        return {
            "meta": {
                "name": skill.meta.name,
                "description": skill.meta.description,
                "version": skill.meta.version,
                "invocation_mode": skill.meta.invocation_mode,
                "mcp_tools": skill.meta.mcp_tools,
                "triggers": skill.meta.triggers,
                "tags": skill.meta.tags,
            },
            "instructions": skill.instructions,
            "references": list(skill.references.keys()),
            "scripts": list(skill.scripts.keys()),
            "activation_count": registry.get_metrics().get(skill_name, {}).get("activations", 0),
            "related_logs": related_logs,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.get("/skill-tool-map")
async def get_skill_tool_map():
    """获取 MCP 工具 ↔ Skill 关联映射表"""
    try:
        from agent_moderation.skill_registry import get_skill_registry
        registry = get_skill_registry()
        return {
            "mcp_tool_to_skills": registry.get_mcp_tool_skills_map(),
            "skill_count": registry.skill_count,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ============== Skill 自优化 API ==============

@router.get("/skill-routing-logs")
async def get_skill_routing_logs(limit: int = 100, offset: int = 0, agent: str = None):
    """获取 Skill 路由日志

    Args:
        limit: 返回条数（最大 500）
        offset: 偏移量
        agent: 按 Agent 过滤
    """
    try:
        from sqlalchemy import select, desc
        from db.connection import get_session_factory
        from db.models import SkillRoutingLog

        session_factory = get_session_factory()
        async with session_factory() as session:
            query = select(SkillRoutingLog)
            if agent:
                query = query.where(SkillRoutingLog.agent == agent)
            query = query.order_by(desc(SkillRoutingLog.timestamp))
            query = query.offset(offset).limit(min(limit, 500))

            result = await session.execute(query)
            logs = result.scalars().all()

            # 统计每个 Skill 的使用次数
            skill_stats = {}
            for log in logs:
                for skill in log.selected_skills:
                    skill_stats[skill] = skill_stats.get(skill, 0) + 1

            return {
                "logs": [
                    {
                        "id": log.id,
                        "content_id": log.content_id,
                        "agent": log.agent,
                        "query": log.query,
                        "content_type": log.content_type,
                        "filtered_skills": log.filtered_skills,
                        "ranked_skills": log.ranked_skills,
                        "selected_skills": log.selected_skills,
                        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                    }
                    for log in logs
                ],
                "total": len(logs),
                "skill_stats": skill_stats,
            }
    except Exception as e:
        logger.error(f"Failed to get skill routing logs: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/skill-optimization/analyze")
async def analyze_skill_routing(min_logs: int = 10):
    """触发 Skill 路由分析并生成优化建议（使用 LLM-driven SkillOptimizationAgent）

    Args:
        min_logs: 最小日志数（低于此数不分析）
    """
    try:
        from optimization.skill_optimization_agent import get_skill_optimization_agent
        optimizer = get_skill_optimization_agent()

        report = await optimizer.analyze_and_suggest(min_logs=min_logs)

        if report is None:
            return {
                "status": "skipped",
                "reason": f"Insufficient logs (needs at least {min_logs})"
            }

        return {
            "status": "success",
            "report": {
                "generated_at": report.generated_at,
                "suggestion_count": report.suggestion_count,
                "analysis_summary": report.analysis_summary,
                "suggestions": [
                    {
                        "skill_name": s.skill_name,
                        "suggestion_type": s.suggestion_type,
                        "current_value": s.current_value,
                        "suggested_value": s.suggested_value,
                        "reason": s.reason,
                        "confidence": s.confidence,
                        "supporting_examples": s.supporting_examples,
                        "analysis_detail": getattr(s, "analysis_detail", ""),
                        "impact": getattr(s, "impact", ""),
                    }
                    for s in report.suggestions
                ],
                "voting_required": report.voting_required,
                "votes": report.votes,
                "approved": report.approved,
            }
        }
    except Exception as e:
        logger.error(f"Failed to analyze skill routing: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.get("/skill-optimization/suggestions")
async def get_optimization_suggestions():
    """获取待审批的优化建议"""
    try:
        # 从备份目录读取报告
        import json
        from pathlib import Path
        reports_dir = Path("/workspace/skills_backups/reports")
        suggestions = []

        if reports_dir.exists():
            for report_file in sorted(reports_dir.glob("*.json"), reverse=True):
                try:
                    with open(report_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    suggestions.append(data)
                except Exception as e:
                    logger.warning(f"Failed to read report {report_file}: {e}")

        return {
            "suggestions": suggestions[:20],  # 最近 20 份
            "total": len(suggestions),
        }
    except Exception as e:
        logger.error(f"Failed to get optimization suggestions: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


class VoteRequest(BaseModel):
    voter: str
    vote: bool
    comment: str = ""


class ApplyRequest(BaseModel):
    suggestion_id: str


class SuggestionVoteRequest(BaseModel):
    voter: str
    vote: bool
    comment: str = ""


class ApplySelectedRequest(BaseModel):
    report_path: str
    suggestion_ids: List[int]


@router.post("/skill-optimization/suggestions/{suggestion_id}/vote")
async def vote_optimization(suggestion_id: str, request: VoteRequest):
    """对优化建议投票

    Args:
        suggestion_id: 建议 ID（生成时的时间戳或报告路径）
        request: 投票请求
    """
    try:
        from optimization.skill_optimization_agent import get_skill_optimization_agent
        optimizer = get_skill_optimization_agent()

        # suggestion_id 实际上是报告文件路径
        result = await optimizer.add_vote(suggestion_id, request.voter, request.vote, request.comment)

        return result
    except Exception as e:
        logger.error(f"Failed to vote on optimization: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/skill-optimization/apply")
async def apply_optimization(request: ApplyRequest):
    """应用已批准的优化建议

    Args:
        request: 包含 suggestion_id 的请求
    """
    try:
        from optimization.skill_optimization_agent import get_skill_optimization_agent
        optimizer = get_skill_optimization_agent()

        # 先加载报告
        report = optimizer._load_report(request.suggestion_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found")

        if not report.approved:
            raise HTTPException(status_code=400, detail="Report not approved")

        result = await optimizer.apply_suggestions(report)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to apply optimization: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.get("/skill-optimization/reports")
async def get_optimization_reports(limit: int = 20):
    """获取历史优化报告"""
    try:
        import json
        from pathlib import Path
        reports_dir = Path("/workspace/skills_backups/reports")
        reports = []

        if reports_dir.exists():
            for report_file in sorted(reports_dir.glob("*.json"), reverse=True):
                try:
                    with open(report_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    reports.append(data)
                except Exception as e:
                    logger.warning(f"Failed to read report {report_file}: {e}")

        return {
            "reports": reports[:limit],
            "total": len(reports),
        }
    except Exception as e:
        logger.error(f"Failed to get optimization reports: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


# ===== 增强版本的 Skill 优化 API =====


@router.post("/skill-optimization/suggestions/{report_path}/{suggestion_id}/vote")
async def vote_single_suggestion(
    report_path: str, suggestion_id: int, request: SuggestionVoteRequest
):
    """对单个建议投票"""
    try:
        from optimization.skill_optimization_agent import get_skill_optimization_agent
        optimizer = get_skill_optimization_agent()

        result = await optimizer.vote_suggestion(
            report_path,
            suggestion_id,
            request.voter,
            request.vote,
            request.comment
        )

        return result
    except Exception as e:
        logger.error(f"Failed to vote on suggestion: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/skill-optimization/apply-selected")
async def apply_selected_suggestions(request: ApplySelectedRequest):
    """应用选中的建议"""
    try:
        from optimization.skill_optimization_agent import get_skill_optimization_agent
        optimizer = get_skill_optimization_agent()

        result = await optimizer.apply_selected(
            request.report_path,
            request.suggestion_ids
        )

        return result
    except Exception as e:
        logger.error(f"Failed to apply selected suggestions: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.get("/skill-optimization/suggestions/{report_path}/{suggestion_id}/preview")
async def get_suggestion_preview(report_path: str, suggestion_id: int):
    """获取单个建议的预览效果"""
    try:
        from optimization.skill_optimization_agent import get_skill_optimization_agent
        optimizer = get_skill_optimization_agent()

        preview = optimizer.get_preview_diff(report_path, suggestion_id)

        if preview is None:
            raise HTTPException(status_code=404, detail="Preview not found")

        return preview
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get suggestion preview: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])
