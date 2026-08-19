"""
LangGraph 主工作流 v3.7 — 深度多 Agent 协作审核

升级内容 (v3.6 → v3.7):
  1. 黑灰产检测内嵌: PatternDetector + AdversarialDetector 融入各 Agent, 移除独立 BlackhatAgent 节点
  2. FileAgent 并行化: 音频处理与图片处理并行执行 (asyncio.gather)
  3. blackhat_result 聚合: 从各 Agent 结果汇总黑灰产信号, 保持下游兼容

全链路 (v3.7):
  Supervisor → [FileAgent(图片‖音频并行)] → TextAgent(含黑灰产)
    → Agentic RAG → [ReAct?] → Debate Panel
    → [Reflexion?] → Human-in-Loop? → Risk → END

技术栈:
  - LangGraph StateGraph + Conditional Routing
  - FileAgent 内部 asyncio.gather 并行
  - MemorySaver Checkpoint (状态持久化)
"""
import asyncio
import logging
import time
from typing import Literal, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from agent_moderation.state import ModerationState
from agent_moderation.agents.supervisor import SupervisorAgent
from agent_moderation.agents.text_agent import TextAgent
from agent_moderation.agents.image_agent import ImageAgent
from agent_moderation.agents.audio_agent import AudioAgent
from agent_moderation.agents.video_agent import VideoAgent
from agent_moderation.agents.risk_agent import RiskAssessmentAgent

logger = logging.getLogger(__name__)

# === Agent 单例 (延迟初始化) ===
_supervisor = None
_text_agent = None
_image_agent = None
_audio_agent = None
_video_agent = None
_risk_agent = None
_debate_panel = None
_reflexion_loop = None

# === v4.1: Agent 结果缓存 (绕过 LangGraph TypedDict channel 传递bug) ===
# LangGraph total=False TypedDict 在 Optional[dict] 类型的 channel merge 时存在丢失更新的bug。
# 此缓存作为可靠的结果传递通道：text_agent_node 写入 → risk_agent_node 读取。
_agent_result_cache: dict = {}
_agentic_rag = None
_graph_rag = None
_react_agent = None
_multimodal_rag = None
_file_agent = None


def _get_supervisor():
    global _supervisor
    if _supervisor is None:
        _supervisor = SupervisorAgent()
    return _supervisor

def _get_text_agent():
    global _text_agent
    if _text_agent is None:
        _text_agent = TextAgent()
    return _text_agent

def _get_image_agent():
    global _image_agent
    if _image_agent is None:
        _image_agent = ImageAgent()
    return _image_agent

def _get_audio_agent():
    global _audio_agent
    if _audio_agent is None:
        _audio_agent = AudioAgent()
    return _audio_agent

def _get_video_agent():
    global _video_agent
    if _video_agent is None:
        _video_agent = VideoAgent()
    return _video_agent

def _get_file_agent():
    """获取 FileAgent — 全模态文件解析"""
    global _file_agent
    if _file_agent is None:
        from agent_moderation.agents.file_agent import FileAgent
        _file_agent = FileAgent()
    return _file_agent

def _get_risk_agent():
    global _risk_agent
    if _risk_agent is None:
        _risk_agent = RiskAssessmentAgent()
    return _risk_agent

def _get_debate_panel():
    global _debate_panel
    if _debate_panel is None:
        from agent_moderation.agents.debate_panel import DebatePanel
        _debate_panel = DebatePanel()
    return _debate_panel

def _get_reflexion_loop():
    global _reflexion_loop
    if _reflexion_loop is None:
        from agent_moderation.agents.reflexion import get_reflexion_loop
        from common.api_clients import get_deepseek_client
        _reflexion_loop = get_reflexion_loop()
        _reflexion_loop.set_llm_client(get_deepseek_client())  # v3.1: LLM增强反思
    return _reflexion_loop

def _get_agentic_rag():
    global _agentic_rag
    if _agentic_rag is None:
        from memory.agentic_rag import get_agentic_rag
        from memory.hybrid_retriever import get_hybrid_retriever
        from memory.graph_rag import get_graph_rag
        from memory.chroma_service import get_chroma_service
        from common.api_clients import get_deepseek_client
        hybrid = get_hybrid_retriever(get_chroma_service())
        graph = get_graph_rag()
        _agentic_rag = get_agentic_rag(hybrid, graph)
        _agentic_rag.set_llm_client(get_deepseek_client())  # v3.1: LLM增强查询改写
    return _agentic_rag

def _get_graph_rag():
    global _graph_rag
    if _graph_rag is None:
        from memory.graph_rag import get_graph_rag
        _graph_rag = get_graph_rag()
    return _graph_rag

def _get_react_agent():
    """获取 ReAct Agent — 用于复杂case的多步推理"""
    global _react_agent
    if _react_agent is None:
        from agent_moderation.agents.react_agent import get_react_agent
        from mcp_servers.registry import get_tool_registry
        from common.api_clients import get_deepseek_client
        _react_agent = get_react_agent()
        _react_agent.set_llm_client(get_deepseek_client())
        _react_agent.set_tool_registry(get_tool_registry())
        from memory.manager import get_memory_manager
        _react_agent.set_memory(get_memory_manager())
    return _react_agent

def _get_multimodal_rag():
    """获取 Multi-Modal RAG — 图片视觉相似案例检索"""
    global _multimodal_rag
    if _multimodal_rag is None:
        from memory.multimodal_rag import get_multimodal_rag as _get_mm_rag
        from memory.hybrid_retriever import get_hybrid_retriever
        from memory.chroma_service import get_chroma_service
        from common.api_clients import get_deepseek_client
        hybrid = get_hybrid_retriever(get_chroma_service())
        _multimodal_rag = _get_mm_rag(hybrid, get_chroma_service())
        _multimodal_rag.set_vl_client(get_deepseek_client())
    return _multimodal_rag

def _send_a2a_message(state: ModerationState, sender: str, receiver: str, content: str):
    """A2A Protocol: 发送 Agent 间消息 (用于任务追踪)"""
    try:
        from agent_moderation.a2a_protocol import get_a2a_registry
        a2a = get_a2a_registry()
        task_id = state.get("_a2a_task_id")
        if task_id:
            a2a.send_message(content=content[:200], sender=sender, receiver=receiver, task_id=task_id)
    except Exception:
        pass  # A2A 追踪失败不影响主流程


def _schedule_feedback_collection(state: ModerationState):
    """
    v2.1: Fire-and-forget FeedbackLoop 收集, 不阻塞审核响应

    将 collect_feedback 和 maybe_optimize 从关键路径移出,
    通过 asyncio.create_task 在后台执行.
    """
    async def _collect():
        try:
            from optimization.prompt_optimizer import get_feedback_loop
            feedback_loop = get_feedback_loop()
            final_risk = state.get("final_risk") or {}
            decision = state.get("final_decision", "PASS")
            overall_score = final_risk.get("overall_score", 0)

            # 1. 低置信度 REJECT → 潜在误判
            if decision == "REJECT" and overall_score < 0.8:
                text_result = state.get("text_result") or {}
                feedback_loop.collect_feedback({
                    "prompt_name": "text_moderation",
                    "content": (state.get("content") or {}).get("text", "")[:200],
                    "actual_decision": decision,
                    "expected_decision": "REVIEW",
                    "error_type": "possible_false_positive",
                    "confidence": overall_score,
                    "violation_type": text_result.get("violation_type", "unknown"),
                })
            # 2. 高风险但最终 PASS → 潜在漏判
            if decision == "PASS" and overall_score > 0.3:
                feedback_loop.collect_feedback({
                    "prompt_name": "text_moderation",
                    "content": (state.get("content") or {}).get("text", "")[:200],
                    "actual_decision": decision,
                    "expected_decision": "REVIEW",
                    "error_type": "possible_false_negative",
                    "confidence": overall_score,
                    "violation_type": "unknown",
                })
            # 3. 对抗样本
            if (state.get("text_result") or {}).get("is_adversarial"):
                feedback_loop.collect_feedback({
                    "prompt_name": "text_moderation",
                    "content": (state.get("content") or {}).get("text", "")[:200],
                    "actual_decision": decision,
                    "expected_decision": "REVIEW",
                    "error_type": "adversarial_sample",
                    "confidence": overall_score,
                })

            # 检查是否达到优化阈值
            fb_stats = feedback_loop.get_stats()
            if fb_stats.get("ready_to_optimize"):
                logger.info(f"FeedbackLoop threshold reached ({fb_stats['buffer_size']}/{fb_stats['threshold']})")
                optimized = await feedback_loop.maybe_optimize()
                if optimized:
                    logger.info(f"Prompt optimized: {optimized.version}")
        except Exception as e:
            logger.warning(f"FeedbackLoop background collection failed: {e}")

    try:
        asyncio.create_task(_collect())
    except RuntimeError:
        pass  # 无事件循环时跳过


def _schedule_hard_case_mining(state: ModerationState):
    """
    v3.8: 难例挖掘 — 中低置信度样本自动入标注队列

    筛选条件: 0.3 < confidence < 0.7 的审核结果
    按违规类型分层, 写入 annotation_records 表
    """
    async def _mine():
        try:
            final_risk = state.get("final_risk") or {}
            overall_score = final_risk.get("overall_score", 0)
            decision = state.get("final_decision", "PASS")

            # 只收集中低置信度的案例
            def _sget(d, key):
                return d.get(key) or {}

            confidences = [
                _sget(state, "text_result").get("confidence", 0),
                _sget(state, "image_result").get("confidence", 0),
                _sget(state, "audio_result").get("confidence", 0),
            ]
            max_conf = max(confidences)

            # 不是"不确定"的案例 → 跳过
            if max_conf > 0.7 or max_conf < 0.3:
                return

            content_id = state.get("content_id", "unknown")
            violation_types = final_risk.get("violation_types", [])

            # 写入 annotation_records (如果表存在)
            try:
                from db.connection import get_session_factory
                from sqlalchemy import text
                import json as _json

                factory = get_session_factory()
                async with factory() as session:
                    await session.execute(
                        text("""
                            INSERT INTO annotation_records
                                (content_id, ai_violation_type, ai_decision, ai_confidence,
                                 annotation_status, priority, meta_info)
                            VALUES (:cid, :vt, :dec, :conf, 'PENDING', :pri, :meta)
                            ON CONFLICT (content_id) DO NOTHING
                        """),
                        {
                            "cid": content_id,
                            "vt": violation_types[0] if violation_types else "unknown",
                            "dec": decision,
                            "conf": max_conf,
                            "pri": "medium",
                            "meta": _json.dumps({
                                "overall_score": overall_score,
                                "source": "hard_case_miner",
                                "confidence_range": f"{min(confidences):.2f}-{max_conf:.2f}",
                            }, ensure_ascii=False),
                        },
                    )
                    await session.commit()
                    logger.info(f"Hard case mined: {content_id} conf={max_conf:.2f} → annotation queue")
            except Exception:
                pass  # 表不存在则跳过

        except Exception as e:
            logger.debug(f"Hard case mining skipped: {e}")

    try:
        asyncio.create_task(_mine())
    except RuntimeError:
        pass


def _schedule_memory_consolidation(state: ModerationState):
    """
    v3.8: Fire-and-forget Agent记忆整合 — 高重要性案例写入 CoreMemory

    在 risk_agent 评估完成后异步执行, 不阻塞审核响应.
    重要性 > 0.7 的案例进入核心记忆, 供后续 Agent 决策参考.
    """
    async def _consolidate():
        try:
            from memory.agent_memory import (
                get_agent_memory, MemoryEvent, ImportanceCalculator,
            )
            from memory.chroma_service import get_chroma_service
            from memory.redis_service import get_redis_service

            agent_mem = get_agent_memory(
                redis_service=get_redis_service(),
                chroma_service=get_chroma_service(),
            )

            final_risk = state.get("final_risk") or {}
            overall_score = final_risk.get("overall_score", 0.0)
            decision = state.get("final_decision", "PASS")
            violation_types = final_risk.get("violation_types", [])

            # 收集各模态度量
            def _sget(d, key):
                return (d.get(key) or {})

            text_conf = _sget(state, "text_result").get("confidence", 0)
            image_conf = _sget(state, "image_result").get("confidence", 0)
            audio_conf = _sget(state, "audio_result").get("confidence", 0)
            max_conf = max(text_conf, image_conf, audio_conf)

            is_adv = (
                _sget(state, "text_result").get("is_adversarial", False)
                or _sget(state, "image_result").get("is_adversarial", False)
                or (state.get("blackhat_result") or {}).get("is_blackhat", False)
            )

            for vt in (violation_types or ["none"]):
                if vt == "none":
                    continue
                importance = ImportanceCalculator.calculate(
                    violation_type=vt,
                    confidence=max_conf,
                    risk_score=overall_score,
                    is_adversarial=is_adv,
                    frequency=1,
                )
                if importance < 0.5:
                    continue  # 不重要的案例跳过

                content_preview = ""
                if state.get("content_type") == "text":
                    content_preview = (state.get("content") or {}).get("text", "")[:500]
                elif text_conf > 0:
                    content_preview = (state.get("content") or {}).get("text", "")[:500]

                event = MemoryEvent(
                    event_id=f"mem_{state.get('content_id', 'unknown')}_{vt}",
                    content_id=state.get("content_id", "unknown"),
                    event_type="moderation",
                    violation_type=vt,
                    decision=decision,
                    risk_score=overall_score,
                    confidence=max_conf,
                    summary=content_preview,
                    importance=importance,
                    metadata={
                        "content_type": state.get("content_type", "text"),
                        "is_adversarial": is_adv,
                        "account_id": state.get("account_id"),
                    },
                )
                await agent_mem.store(event)
                logger.info(
                    f"Memory consolidated: {vt} importance={importance:.2f} "
                    f"→ {'Core' if importance > 0.7 else 'Working/Archival'}"
                )

            await agent_mem.flush()
        except Exception as e:
            logger.warning(f"Memory consolidation failed (non-blocking): {e}")

    try:
        asyncio.create_task(_consolidate())
    except RuntimeError:
        pass


def _aggregate_blackhat_result(state: ModerationState):
    """
    v3.7: 从各 Agent 结果聚合 blackhat_result（替代独立 BlackhatAgent）

    收集 text/image/audio Agent 内部的 blackhat_patterns + adversarial_techniques,
    计算综合 blackhat_risk_score, 写入 state["blackhat_result"] 供下游消费.
    """
    all_patterns = []
    all_adversarials = []
    max_bh_score = 0.0
    any_blackhat = False

    for result_key in ("text_result", "image_result", "audio_result", "video_result"):
        r = state.get(result_key) or {}
        pats = r.get("blackhat_patterns", [])
        advs = r.get("adversarial_techniques", [])
        if pats:
            all_patterns.extend(pats)
        if advs:
            all_adversarials.extend(advs)
        if r.get("is_blackhat", False):
            any_blackhat = True
        max_bh_score = max(max_bh_score, r.get("blackhat_risk_score", 0))

    # 去重 patterns (按 type 去重, 保留最高 confidence)
    seen_types = {}
    for p in all_patterns:
        pt = p.get("type", "")
        if pt not in seen_types or p.get("confidence", 0) > seen_types[pt].get("confidence", 0):
            seen_types[pt] = p

    state["blackhat_result"] = {
        "pattern_detected": list(seen_types.values()),
        "adversarial_detected": all_adversarials,
        "account_risk": None,
        "blackhat_risk_score": max_bh_score,
        "is_blackhat": any_blackhat,
    }

    # v3.7: 将黑灰产模式注册到 GraphRAG (从 BlackhatAgent 迁移)
    if all_patterns:
        try:
            graph_rag = _get_graph_rag()
            account_id = state.get("account_id")
            if account_id:
                for p in list(seen_types.values()):
                    graph_rag.register_pattern(account_id, p.get("type", ""))
        except Exception as e:
            logger.warning(f"GraphRAG pattern registration failed: {e}")


# === 节点函数 ===

async def supervisor_node(state: ModerationState) -> ModerationState:
    """总控调度节点 — 内容分类 + 复杂度评估 + A2A 任务创建"""
    from common.logger import get_pipeline
    pipeline = get_pipeline()
    content_id = state.get("content_id", "unknown")
    content_type = state.get("content_type", "text")

    # A2A Protocol: 创建任务追踪
    try:
        from agent_moderation.a2a_protocol import get_a2a_registry
        a2a = get_a2a_registry()
        task = a2a.create_task(
            title=f"Moderation: {content_type}",
            description=f"Content moderation task for {content_id}",
            assigned_agent="supervisor",
            input_data={"content_id": content_id, "content_type": content_type},
        )
        state["_a2a_task_id"] = task.task_id
    except Exception as e:
        logger.debug(f"A2A task creation skipped: {e}")

    state["messages"].append({
        "role": "supervisor",
        "content": f"Processing {content_type} content",
    })
    start = time.time()
    result = await _get_supervisor().process(state)
    if pipeline:
        pipeline.step("🧠 SUPERVISOR", f"内容分类: {state.get('content_type')}",
                      input_data={"content_id": state.get("content_id"),
                                  "content_type": state.get("content_type")},
                      duration_ms=(time.time()-start)*1000)
    # 标记是否多模态 (视频同时包含视觉+音频)
    is_multimodal = state.get("content_type") in ("video",)
    state["_is_multimodal"] = is_multimodal
    return result


async def text_agent_node(state: ModerationState) -> ModerationState:
    """文本审核节点"""
    from common.logger import get_pipeline
    pipeline = get_pipeline()

    # v4.0: Planner 已处理 → 跳过核心审核, 仅聚合黑灰产结果
    if state.get("_planner_processed"):
        state["messages"].append({"role": "text_agent", "content": "Skipped (Planner pre-processed)"})
        _aggregate_blackhat_result(state)
        if pipeline:
            tr = state.get("text_result", {})
            pipeline.step("📝 TEXT_AGENT", "跳过 (Planner已处理)",
                          output_data={"violation_type": tr.get("violation_type"),
                                       "risk_score": tr.get("risk_score", 0)},
                          level="INFO")
        return state
    _send_a2a_message(state, "supervisor", "text_agent", "Text content analysis started")
    start = time.time()
    result = await _get_text_agent().process(state)
    _send_a2a_message(state, "text_agent", "debate_panel",
                      f"Text analysis + blackhat: {state.get('text_result', {}).get('violation_type', 'none')}")
    if pipeline:
        tr = state.get("text_result", {})
        pipeline.step("📝 TEXT_AGENT", f"文本审核完成",
                      input_data={"text_len": len(state.get("content", {}).get("text", "")),
                                  "violation": tr.get("violation_type", "none"),
                                  "confidence": tr.get("confidence", 0)},
                      output_data={"violation_type": tr.get("violation_type"),
                                   "risk_score": tr.get("risk_score", 0)},
                      duration_ms=(time.time()-start)*1000)

    # v4.1: 写入缓存, 确保 text_result 可靠传递给 risk_agent
    _tr_cache = state.get("text_result") or {}
    if _tr_cache and _tr_cache.get("risk_score", 0) > 0:
        _agent_result_cache[state["content_id"]] = dict(_tr_cache)
        # 保持缓存不超过 1000 条目
        if len(_agent_result_cache) > 1000:
            oldest = list(_agent_result_cache.keys())[:100]
            for k in oldest:
                _agent_result_cache.pop(k, None)

    # v3.7: 聚合各 Agent 的黑灰产检测结果 (替代独立 BlackhatAgent)
    _aggregate_blackhat_result(state)

    # v3.6: 触发 Agentic RAG 增强检索 — 降低门槛
    # 任何模态存在可疑信号 或 全模态任务 → 触发深度检索
    _tr = state.get("text_result") or {}
    _ir = state.get("image_result") or {}
    _ar = state.get("audio_result") or {}
    _br = state.get("blackhat_result") or {}
    _any_suspicious = (
        _tr.get("violation_type", "none") != "none"
        or _ir.get("violation_type", "none") != "none"
        or _ar.get("violation_type", "none") != "none"
        or _br.get("is_blackhat", False)
    )
    _is_multimodal = state.get("content_type") == "multi_modal"

    from common.logger import get_flow_logger as _get_fl
    _fl = _get_fl()

    if _any_suspicious or _is_multimodal:
        from common.logger import get_pipeline as _get_pl
        _pl = _get_pl()
        rag_start = time.time()

        if _fl:
            trigger_reason = "any_suspicious" if _any_suspicious else "multi_modal_task"
            _fl.box_start("🔍 深度RAG (AgenticRAG)", f"触发: {trigger_reason}")

        try:
            agentic_rag = _get_agentic_rag()
            text = state.get("content", {}).get("text", "")
            # 收集所有已检测到的违规类型
            all_vts = []
            for key in ("text_result", "image_result", "audio_result"):
                result = state.get(key) or {}
                vt = result.get("violation_type", "none")
                if vt != "none" and vt not in all_vts:
                    all_vts.append(vt)
            if not all_vts:
                all_vts = ["false_info"]  # multi_modal 默认检索诈骗类

            if _fl:
                _fl.box_step("📝 QueryRewrite", f"原始查询", f"\"{text[:60]}...\" ({len(text)}字)", "blue")

            rag_result = await agentic_rag.retrieve(
                query=text[:500],
                top_k=5,
                violation_types=all_vts,
                auto_refine=True,
            )

            state["_rag_result"] = {
                "results": [
                    {"id": r.id, "content": r.content[:100], "score": r.score}
                    for r in rag_result.get("results", [])
                ],
                "rounds": rag_result.get("total_rounds", 1),
                "self_rag_confidence": rag_result.get("self_rag", {}).get("confidence", 0),
                "graph_insights": rag_result.get("graph_insights"),
            }

            if _fl:
                n_results = len(rag_result.get("results", []))
                confidence = (rag_result.get("self_rag") or {}).get("confidence", 0)
                rounds = rag_result.get("total_rounds", 1)
                rewrite = (rag_result.get("query_rewrite") or {}).get("rewritten", "") or ""
                _fl.box_step("🔎 HybridSearch", f"RRF融合", f"→ {n_results}条 (BM25+Dense+CrossEncoder)", "green")
                _fl.box_step("✅ SelfRAG", f"质量评估", f"confidence={confidence:.2f} | rounds={rounds}", "green")
                # 转换为 dict 列表兼容 box_rag_result
                rag_results_for_log = []
                for r in (rag_result.get("results") or []):
                    if r is not None:
                        meta = getattr(r, "metadata", None) or {}
                        rag_results_for_log.append({
                            "similarity": getattr(r, "score", 0),
                            "violation_type": meta.get("violation_type", "?"),
                            "content": getattr(r, "content", "") or "",
                        })
                _fl.box_rag_result(rag_results_for_log, "blue")
                graph_insights = rag_result.get("graph_insights")
                if graph_insights:
                    related = graph_insights.get("related_violation_types", [])
                    if related:
                        rel_str = ", ".join(f"{r.get('type','?')}({r.get('weight',0):.0%})" for r in related[:5])
                        _fl.box_step("🔗 GraphRAG", "违规关联", rel_str, "green")
                _fl.box_end("🔍 深度RAG", f"检索{len(rag_result.get('results',[]))}条 | 置信度{confidence:.2f} | {rounds}轮")

            if _pl:
                _pl.step("🔍 AGENTIC_RAG", f"智能检索: {len(rag_result.get('results', []))}条结果",
                         output_data={"results": len(rag_result.get('results', [])),
                                      "rounds": rag_result.get('total_rounds', 1),
                                      "confidence": rag_result.get('self_rag', {}).get('confidence', 0)},
                         duration_ms=(time.time()-rag_start)*1000)
            logger.info(f"Agentic RAG: {len(rag_result.get('results', []))} results, "
                        f"{rag_result.get('total_rounds', 1)} rounds")
        except Exception as e:
            import traceback as _tb
            _tb.print_exc()
            if _fl:
                _fl.box_step("❌", "RAG检索失败", str(e)[:60], "red")
                _fl.box_end("🔍 深度RAG", "检索失败")
            if _pl:
                _pl.step("🔍 AGENTIC_RAG", f"RAG检索失败: {str(e)[:30]}", level="WARN")
            logger.warning(f"Agentic RAG failed: {e}", exc_info=True)

    return result


async def react_agent_node(state: ModerationState) -> ModerationState:
    """
    ReAct Agent 节点 — 多步推理深度分析

    触发条件: TextAgent 置信度 < 0.6 或检测到对抗样本
    用于复杂case的 Thought → Action → Observation 循环
    """
    from common.logger import get_pipeline
    pipeline = get_pipeline()
    state["messages"].append({"role": "react_agent", "content": "ReAct deep analysis in progress..."})
    start = time.time()

    try:
        react = _get_react_agent()
        content = state.get("content", {})
        content_type = state.get("content_type", "text")

        # 将 TextAgent 结果预填充为已知上下文
        text_result = state.get("text_result", {})
        react.context_prefill = {
            "known_keywords": text_result.get("keyword_matches", []),
            "known_violations": [text_result.get("violation_type")] if text_result.get("violation_type", "none") != "none" else [],
        }

        result = await react.run(content, content_type)

        # 将 ReAct 结果合并到 text_result
        if text_result:
            text_result["react_enhanced"] = True
            text_result["react_violation_type"] = result.violation_type
            text_result["react_confidence"] = result.confidence
            text_result["react_risk_score"] = result.risk_score
            text_result["react_steps"] = result.total_steps
            text_result["react_tools_called"] = result.tools_called
            text_result["react_reasoning"] = result.reasoning_trace[:300]
            # 如果 ReAct 置信度更高，用它覆盖原结果
            if result.confidence > text_result.get("confidence", 0):
                text_result["violation_type"] = result.violation_type
                text_result["confidence"] = result.confidence
                text_result["risk_score"] = max(text_result.get("risk_score", 0), result.risk_score)

        state["_react_result"] = {
            "activated": True,
            "final_decision": result.final_decision,
            "violation_type": result.violation_type,
            "confidence": result.confidence,
            "steps": result.total_steps,
            "tools_called": result.tools_called,
            "reasoning_trace": result.reasoning_trace,
        }

        if pipeline:
            pipeline.step("🔁 REACT_AGENT", f"ReAct推理: {result.total_steps}步, 置信度={result.confidence:.2f}",
                          output_data={"steps": result.total_steps,
                                       "tools": result.tools_called,
                                       "violation": result.violation_type,
                                       "confidence": result.confidence},
                          duration_ms=(time.time()-start)*1000)
        logger.info(f"ReAct: {result.total_steps} steps → {result.violation_type} (conf={result.confidence:.2f})")

    except Exception as e:
        logger.error(f"ReAct agent failed: {e}")
        state["_react_result"] = {"activated": True, "error": str(e)}
        if pipeline:
            pipeline.step("🔁 REACT_AGENT", f"ReAct失败: {str(e)[:40]}", level="WARN")

    return state


async def image_agent_node(state: ModerationState) -> ModerationState:
    """图片审核节点"""
    from common.logger import get_pipeline
    pipeline = get_pipeline()
    state["messages"].append({"role": "image_agent", "content": "Analyzing image content..."})
    start = time.time()
    result = await _get_image_agent().process(state)
    # v3.7: 聚合黑灰产结果
    _aggregate_blackhat_result(state)
    if pipeline:
        ir = state.get("image_result", {})
        pipeline.step("🖼️ IMAGE_AGENT", f"图片审核完成",
                      input_data={"size": len(state.get("content", {}).get("image", b"")),
                                  "filename": state.get("content", {}).get("filename", "")},
                      output_data={"violation_type": ir.get("violation_type"),
                                   "risk_score": ir.get("risk_score", 0)},
                      duration_ms=(time.time()-start)*1000)

    # 多模态 RAG: 图片视觉相似案例检索
    try:
        image_data = state.get("content", {}).get("image") or state.get("content", {}).get("image_data")
        if image_data:
            mm_rag = _get_multimodal_rag()
            ocr_text = state.get("image_result", {}).get("ocr_text", "")
            mm_start = time.time()
            mm_results = await mm_rag.retrieve_with_image(
                text_query=ocr_text or "",
                image_data=image_data,
                top_k=3,
                use_visual=True,
            )
            state["_multimodal_rag_result"] = {
                "activated": True,
                "results_count": len(mm_results),
                "top_scores": [{"id": r.id, "score": r.score, "modality": r.modality}
                              for r in mm_results[:3]],
            }
            if pipeline:
                pipeline.step("🖼️ MULTIMODAL_RAG", f"多模态检索: {len(mm_results)}条视觉相似案例",
                              output_data={"results": len(mm_results),
                                           "top_score": mm_results[0].score if mm_results else 0},
                              duration_ms=(time.time()-mm_start)*1000)
            logger.info(f"Multi-Modal RAG: {len(mm_results)} visual similar cases found")
    except Exception as e:
        logger.warning(f"Multi-Modal RAG failed (non-blocking): {e}")
        state["_multimodal_rag_result"] = {"activated": True, "error": str(e)[:100]}

    return result


async def audio_agent_node(state: ModerationState) -> ModerationState:
    """语音审核节点"""
    from common.logger import get_pipeline
    pipeline = get_pipeline()
    state["messages"].append({"role": "audio_agent", "content": "Analyzing audio content..."})
    start = time.time()
    result = await _get_audio_agent().process(state)
    # v3.7: 聚合黑灰产结果
    _aggregate_blackhat_result(state)
    if pipeline:
        ar = state.get("audio_result", {})
        pipeline.step("🎤 AUDIO_AGENT", f"语音审核完成",
                      output_data={"violation_type": ar.get("violation_type"),
                                   "risk_score": ar.get("risk_score", 0),
                                   "transcribed": (ar.get("transcribed_text", "") or "")[:50]},
                      duration_ms=(time.time()-start)*1000)
    return result


async def video_agent_node(state: ModerationState) -> ModerationState:
    """视频审核节点"""
    from common.logger import get_pipeline
    pipeline = get_pipeline()
    state["messages"].append({"role": "video_agent", "content": "Analyzing video content..."})
    start = time.time()
    result = await _get_video_agent().process(state)
    if pipeline:
        vr = state.get("video_result", {})
        pipeline.step("🎬 VIDEO_AGENT", f"视频审核完成",
                      output_data={"overall_risk": vr.get("overall_risk_score", 0),
                                   "frames_analyzed": vr.get("frame_count", 0)},
                      duration_ms=(time.time()-start)*1000)
    return result


async def file_agent_node(state: ModerationState) -> ModerationState:
    """全模态文件解析节点 — 解析上传文件后, 对图片/音频调用专用 Agent, 再转入文本审核流程"""
    from common.logger import get_pipeline
    pipeline = get_pipeline()

    # v4.0: Planner 已处理 → 跳过
    if state.get("_planner_processed"):
        state["messages"].append({"role": "file_agent", "content": "Skipped (Planner pre-processed)"})
        if pipeline:
            pipeline.step("📁 FILE_AGENT", "跳过 (Planner已处理)", level="INFO")
        return state
    state["messages"].append({"role": "file_agent", "content": "Parsing uploaded files..."})
    start = time.time()
    result = await _get_file_agent().process(state)
    if pipeline:
        fr = state.get("file_results", {})
        pipeline.step("📁 FILE_AGENT", f"文件解析完成",
                      output_data={"file_count": fr.get("file_count", 0),
                                   "total_chars": fr.get("total_chars", 0)},
                      duration_ms=(time.time()-start)*1000)

    # v3.5: 收集所有图片文件 (standalone + docx 嵌入), 提取上下文, 并行 VL 分析
    # docx 嵌入图片不再跳过 — 每张图片都结合周围文本上下文做联合审核
    content = state.get("content") or {}
    files = content.get("files", [])
    combined_text = content.get("text", "")  # FileAgent 已将 combined_text 写入 content["text"]

    # 1. 收集所有图片 + 音频
    all_image_infos = []  # [{filename, content, mime_type, is_embedded, context_before, context_after}, ...]
    audio_files = []

    for f in files:
        mime = f.get("mime_type", "")
        fname = f.get("filename", "").lower()
        is_embedded = f.get("_docx_embedded", False)

        if mime.startswith("image/"):
            context_before = ""
            context_after = ""
            char_pos = f.get("_char_position")

            # v3.5: 为嵌入图片提取周围文本上下文 (±500 字符)
            if is_embedded and char_pos is not None and char_pos >= 0 and combined_text:
                context_before = combined_text[max(0, char_pos - 500):char_pos]
                context_after = combined_text[char_pos:min(len(combined_text), char_pos + 500)]

            all_image_infos.append({
                "filename": f.get("filename", f"embedded_{len(all_image_infos)}.png"),
                "content": f.get("content", b""),
                "mime_type": mime,
                "is_embedded": is_embedded,
                "char_position": char_pos or 0,
                "context_before": context_before,
                "context_after": context_after,
            })
        elif mime.startswith("audio/") or fname.endswith(
            (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma")
        ):
            audio_files.append(f)

    # 2. 并行处理所有图片 (并发上限 5, 避免 VL API 过载)
    if all_image_infos:
        sem = asyncio.Semaphore(5)
        image_agent = _get_image_agent()

        async def _process_one_image(info: dict) -> dict:
            """处理单张图片 (独立 state, 避免并行冲突)"""
            async with sem:
                img_start = time.time()
                try:
                    # 构建隔离的 state
                    img_state = {
                        "content": {
                            "image": info["content"],
                            "filename": info["filename"],
                            "image_context": {
                                "before": info["context_before"],
                                "after": info["context_after"],
                            } if (info["context_before"] or info["context_after"]) else {},
                        },
                        "content_id": state.get("content_id", "unknown"),
                    }
                    result_state = await image_agent.process(img_state)
                    img_result = result_state.get("image_result") or {}
                    dur_ms = (time.time() - img_start) * 1000
                    logger.info(
                        f"[MultiModal] Image '{info['filename'][:40]}' "
                        f"embedded={info['is_embedded']} ctx={len(info['context_before'])}+{len(info['context_after'])} "
                        f"risk={img_result.get('risk_score', 0):.3f} {dur_ms:.0f}ms"
                    )
                    return {
                        "filename": info["filename"],
                        "is_embedded": info["is_embedded"],
                        "char_position": info["char_position"],
                        "result": img_result,
                        "risk_score": img_result.get("risk_score", 0),
                        "duration_ms": dur_ms,
                    }
                except Exception as e:
                    logger.warning(f"[MultiModal] ImageAgent failed for '{info['filename']}': {e}")
                    return {
                        "filename": info["filename"],
                        "is_embedded": info["is_embedded"],
                        "char_position": info.get("char_position", 0),
                        "result": {"error": str(e), "risk_score": 0.0},
                        "risk_score": 0.0,
                        "duration_ms": (time.time() - img_start) * 1000,
                    }

        # 并行执行所有图片 + 音频分析 (v3.7: 音频不再等待图片)
        img_start_all = time.time()

        # 构建所有并行任务
        all_tasks = [_process_one_image(info) for info in all_image_infos]
        task_types = ["image"] * len(all_image_infos)

        # v3.7: 音频与图片并行处理
        if audio_files:
            audio_file = audio_files[0]
            audio_agent = _get_audio_agent()

            async def _process_audio() -> dict:
                """处理音频 (独立 state, 与图片并行)"""
                audio_start = time.time()
                try:
                    audio_state = {
                        "content": {
                            "audio": audio_file.get("content", b""),
                            "filename": audio_file.get("filename", "unknown"),
                        },
                        "content_id": state.get("content_id", "unknown"),
                    }
                    audio_result_state = await audio_agent.process(audio_state)
                    audio_result = audio_result_state.get("audio_result") or {}
                    dur_ms = (time.time() - audio_start) * 1000
                    logger.info(
                        f"[MultiModal] Audio '{audio_file.get('filename', '?')[:30]}' "
                        f"risk={audio_result.get('risk_score', 0):.3f} {dur_ms:.0f}ms"
                    )
                    return {
                        "type": "audio",
                        "filename": audio_file.get("filename", "unknown"),
                        "result": audio_result,
                        "risk_score": audio_result.get("risk_score", 0),
                        "duration_ms": dur_ms,
                    }
                except Exception as e:
                    logger.warning(f"[MultiModal] AudioAgent failed: {e}")
                    return {
                        "type": "audio",
                        "filename": audio_file.get("filename", "unknown"),
                        "result": {"error": str(e), "risk_score": 0.0},
                        "risk_score": 0.0,
                        "duration_ms": (time.time() - audio_start) * 1000,
                    }

            all_tasks.append(_process_audio())
            task_types.append("audio")

        all_results = await asyncio.gather(*all_tasks, return_exceptions=True)

        # 3. 分离图片和音频结果
        valid_results = [r for r in all_results if isinstance(r, dict)]
        image_results_list = [r for r in valid_results if r.get("type") != "audio"]
        audio_results_list = [r for r in valid_results if r.get("type") == "audio"]

        # 合并图片结果: 取最高风险分的作为 state["image_result"], 全部存入 _all_image_results
        all_image_results = [r["result"] for r in image_results_list]
        max_risk = 0.0
        best_result = None
        for r in image_results_list:
            if r["risk_score"] > max_risk:
                max_risk = r["risk_score"]
                best_result = r

        if best_result:
            state["image_result"] = best_result["result"]
        state["_all_image_results"] = all_image_results

        # 合并音频结果
        if audio_results_list:
            audio_r = audio_results_list[0]
            state["audio_result"] = audio_r["result"]
            if pipeline:
                pipeline.step("🎤 AUDIO_AGENT", f"语音审核: {audio_r['filename'][:30]}",
                              output_data={"violation_type": audio_r["result"].get("violation_type"),
                                           "risk_score": audio_r["risk_score"],
                                           "asr_text": (audio_r["result"].get("transcribed_text", "") or "")[:80]},
                              duration_ms=audio_r.get("duration_ms", 0))

        # Pipeline 日志: 为每张图片记录步骤
        if pipeline:
            for r in image_results_list:
                tag = "📎" if r.get("is_embedded") else "🖼️"
                pipeline.step(
                    f"{tag} IMAGE_AGENT",
                    f"图片审核: {r['filename'][:30]}",
                    output_data={
                        "violation_type": r["result"].get("violation_type"),
                        "risk_score": r["risk_score"],
                        "embedded": r.get("is_embedded", False),
                        "has_context": r["result"].get("has_context", False),
                    },
                    duration_ms=r.get("duration_ms", 0),
                )

        total_dur = (time.time() - img_start_all) * 1000
        embedded_count = sum(1 for r in image_results_list if r.get("is_embedded"))
        standalone_count = sum(1 for r in image_results_list if not r.get("is_embedded"))
        audio_count = len(audio_results_list)
        logger.info(
            f"[MultiModal] Processed {len(image_results_list)} images "
            f"({standalone_count} standalone + {embedded_count} docx embedded) "
            f"+ {audio_count} audio in parallel, "
            f"max_risk={max_risk:.2f}, total={total_dur:.0f}ms"
        )

    return result


async def debate_node(state: ModerationState) -> ModerationState:
    """
    Debate Panel 节点 — 多 Agent 辩论

    触发条件: 各 Agent 意见不一致时由路由函数决定是否进入辩论
    """
    state["messages"].append({"role": "debate_panel", "content": "Multi-agent debate in progress..."})

    panel = _get_debate_panel()
    opinions = panel.collect_opinions(state)

    if len(opinions) <= 1:
        # v3.2: 单一意见但有 "uncertain" → 仍然触发人工审核
        has_uncertain = any(o.violation_type == "uncertain" for o in opinions)
        state["_debate_result"] = {
            "debated": False,
            "reason": "仅有单一Agent意见, 无需辩论",
            "needs_human_review": has_uncertain,
            "opinion_count": len(opinions),
        }
        if has_uncertain:
            state["_human_review"] = {
                "required": True,
                "reason": "Agent不确定(uncertain), 需要人工审核",
                "status": "PENDING",
            }
        return state

    debate_result = panel.debate(opinions)

    state["_debate_result"] = {
        "debated": True,
        "mode": debate_result.debate_mode.value,
        "final_type": debate_result.final_violation_type,
        "final_confidence": debate_result.final_confidence,
        "final_risk": debate_result.final_risk_score,
        "is_consensus": debate_result.is_consensus,
        "needs_human_review": debate_result.needs_human_review,
        "opinion_count": len(opinions),
        "summary": debate_result.debate_summary,
    }

    from common.logger import get_pipeline
    pipeline = get_pipeline()
    if pipeline:
        pipeline.step("⚖️ DEBATE", f"辩论: {debate_result.debate_mode.value}",
                      output_data={"mode": debate_result.debate_mode.value,
                                   "final_type": debate_result.final_violation_type,
                                   "confidence": debate_result.final_confidence,
                                   "consensus": debate_result.is_consensus,
                                   "opinions": len(opinions)})

    logger.info(
        f"Debate: {len(opinions)} opinions → {debate_result.debate_mode.value} → "
        f"{debate_result.final_violation_type} (conf={debate_result.final_confidence:.2f})"
    )

    return state


async def reflexion_node(state: ModerationState) -> ModerationState:
    """
    Reflexion 自反思节点 — 审核质量自检 + 迭代改进

    对当前审核结果进行自我评估:
    - 置信度是否足够
    - 证据链是否完整
    - 是否需要补充检索
    """
    state["messages"].append({"role": "reflexion", "content": "Self-reflection on moderation quality..."})

    # 收集所有 Agent 的结果
    agent_results = {}
    for key in ["text_result", "image_result", "audio_result", "video_result"]:
        r = state.get(key)
        if r and not r.get("error"):
            agent_results[key] = r

    if not agent_results:
        state["_reflexion_result"] = {"reflected": False, "reason": "无Agent结果可供反思"}
        return state

    reflexion = _get_reflexion_loop()
    content_id = state.get("content_id", "unknown")
    content_type = state.get("content_type", "text")

    # 对每个 Agent 结果运行 Reflexion
    reflexion_results = {}
    for key, result in agent_results.items():
        try:
            r = await reflexion.run(
                content_id=f"{content_id}_{key}",
                agent_result=result,
                content_type=content_type,
            )
            reflexion_results[key] = {
                "initial_confidence": r.initial_confidence,
                "final_confidence": r.final_confidence,
                "reflection_applied": r.reflection_applied,
                "rounds": r.rounds,
                "summary": r.summary,
            }
        except Exception as e:
            logger.warning(f"Reflexion failed for {key}: {e}")

    state["_reflexion_result"] = {
        "reflected": any(r.get("reflection_applied") for r in reflexion_results.values()),
        "details": reflexion_results,
    }

    from common.logger import get_pipeline
    pipeline = get_pipeline()
    if pipeline:
        reflected_count = sum(1 for r in reflexion_results.values() if r.get("reflection_applied"))
        pipeline.step("🔄 REFLEXION", f"自我反思完成",
                      output_data={"reflected": reflected_count > 0,
                                   "agents_reflected": reflected_count,
                                   "total_agents": len(reflexion_results)})

    return state


async def human_in_loop_node(state: ModerationState) -> ModerationState:
    """
    Human-in-the-Loop 节点 — 高风险/低共识内容暂停等待人工确认

    触发场景:
    - Debate 结果为升级 (escalate)
    - 风险分 > 0.8 且共识度 < 0.6
    - 检测到严重违规类型 (violence/illegal/terrorism) + 低置信度

    使用 LangGraph interrupt() 真正暂停工作流, 等待人工审核后再恢复
    """
    from langgraph.types import interrupt

    debate_result = (state.get("_debate_result") or {})

    # 检查是否需要人工介入
    human_review_state = (state.get("_human_review") or {})
    needs_human = (
        human_review_state.get("required", False)  # v3.2: 单Agent低置信度直通
        or debate_result.get("needs_human_review", False)
        or debate_result.get("mode") == "escalate"
    )

    if needs_human:
        state["messages"].append({
            "role": "human_in_loop",
            "content": "⚠️ 高风险低共识 — 需要人工审核介入",
        })

        # 构建中断上下文
        interrupt_context = {
            "content_id": state.get("content_id", "unknown"),
            "content_type": state.get("content_type", "text"),
            "reason": debate_result.get("summary", "多Agent分歧严重"),
            "current_risk": (state.get("final_risk") or {}).get("overall_score", 0),
            "violation_types": (state.get("final_risk") or {}).get("violation_types", []),
            "debate_summary": debate_result.get("summary", ""),
            "text_preview": (state.get("content") or {}).get("text", "")[:200],
        }

        state["_human_review"] = {
            "required": True,
            "reason": debate_result.get("summary", "多Agent分歧严重"),
            "status": "PENDING",
        }

        # R8·E4 (F1 修复): 注册 Redis 待审核队列（此前 Redis 队列永远为空，
        # 前端 HumanReviewPanel 消费 pending-reviews 无数据）。
        try:
            from api.routes.moderation import _register_pending_review
            await _register_pending_review(state.get("content_id", ""), dict(state))
        except Exception as e:
            logger.warning(f"[human_in_loop] register_pending_review failed: {e}")

        from common.logger import get_pipeline
        pipeline = get_pipeline()
        if pipeline:
            pipeline.step("👤 HUMAN_REVIEW", "⏸️ 工作流暂停,等待人工审核",
                          output_data={"reason": debate_result.get("summary", ""),
                                       "status": "PENDING_INTERRUPT"},
                          level="WARN")
        logger.warning(f"Human-in-the-Loop interrupt: {debate_result.get('summary')}")

        # LangGraph interrupt — 真正暂停工作流 (仅同步模式下有效)
        import contextvars
        try:
            human_decision = interrupt(interrupt_context)
            # 工作流恢复: human_decision 包含人工判定结果
            state["_human_review"]["status"] = "RESOLVED"
            state["_human_review"]["human_decision"] = human_decision

            if pipeline:
                pipeline.step("👤 HUMAN_REVIEW", "▶️ 人工审核完成,工作流恢复",
                              output_data={"decision": human_decision.get("decision", "?")})

            # 将人工判定注入状态
            state["human_decision"] = human_decision
            state["messages"].append({
                "role": "human_reviewer",
                "content": f"人工判定: {human_decision.get('decision', '?')} — {human_decision.get('reason', '')}",
            })
        except RuntimeError as e:
            # 异步任务模式下 interrupt() 不可用 (LangGraph 限制)
            # 优雅降级: 将人工审核标记为 PENDING, 继续执行风险评估
            if "get_config outside of a runnable context" in str(e):
                logger.warning(
                    f"Human-in-the-Loop not available in async mode, "
                    f"task will complete with REVIEW decision for manual check"
                )
                state["_human_review"]["status"] = "PENDING_ASYNC"
                # 强制决策为 REVIEW, 等待后续人工处理
                if state.get("final_risk") is None:
                    state["final_risk"] = {}
                state["final_risk"]["decision"] = "REVIEW"
                state["final_decision"] = "REVIEW"
            else:
                raise

    else:
        state["_human_review"] = {"required": False}

    return state


async def risk_agent_node(state: ModerationState) -> ModerationState:
    """
    综合风险评估节点 v4.1 — 融合 Debate Panel 的协商逻辑

    阶段1: 收集各 Agent 意见 → 多类型冲突时加权投票
    阶段2: 计算综合风险分 → 阈值比较 → PASS/REVIEW/REJECT
    阶段3: 事后处理 (GraphRAG / FeedbackLoop / HardCaseMining / MemoryConsolidation)
    """
    from common.logger import get_pipeline
    from common.logger import get_flow_logger as _get_fl
    pipeline_log = get_pipeline()
    fl = _get_fl()

    # v4.1: 从缓存恢复 agent 结果
    cid = state.get("content_id", "")
    if cid and cid in _agent_result_cache:
        cached = _agent_result_cache[cid]
        existing = state.get("text_result") or {}
        if not existing or existing.get("risk_score", 0) == 0:
            state["text_result"] = cached
            logger.info(f"[risk_agent] Recovered text_result from agent_result_cache for {cid}")

    state["messages"].append({"role": "risk_agent", "content": "Assessing overall risk (Debate merged)..."})
    start = time.time()

    # ═══════════════════ 阶段1: 收集意见 + 加权投票 (原 Debate) ═══════════════════
    panel = _get_debate_panel()
    opinions = panel.collect_opinions(state)

    if len(opinions) >= 2:
        unique_types = set(o.violation_type for o in opinions)
        if len(unique_types) >= 2:
            # 真正有分歧 → 加权投票
            debate_result = panel.debate(opinions)
            state["_debate_result"] = {
                "debated": True,
                "mode": debate_result.debate_mode.value,
                "final_type": debate_result.final_violation_type,
                "final_confidence": debate_result.final_confidence,
                "is_consensus": debate_result.is_consensus,
                "needs_human_review": debate_result.needs_human_review,
                "opinion_count": len(opinions),
                "summary": debate_result.debate_summary,
            }
            if fl:
                fl.box_step("⚖️", "意见协商 (加权投票)",
                           f"{len(unique_types)}种类型 → {debate_result.final_violation_type}",
                           "yellow")
            if pipeline_log:
                pipeline_log.step("⚖️ RISK_VOTE",
                                 f"加权投票: {debate_result.final_violation_type} "
                                 f"conf={debate_result.final_confidence:.2f}",
                                 output_data={"mode": debate_result.debate_mode.value,
                                              "types": len(unique_types)})
        else:
            # 多个意见但类型一致 → 快速共识
            avg_conf = sum(o.confidence for o in opinions) / len(opinions)
            state["_debate_result"] = {
                "debated": False, "is_consensus": True,
                "needs_human_review": False, "opinion_count": len(opinions),
                "final_type": list(unique_types)[0],
                "final_confidence": avg_conf,
                "summary": f"快速共识: {len(opinions)} 个Agent一致判定",
            }
    elif len(opinions) == 1:
        # 单一 Agent 意见 → 直接采纳
        op = opinions[0]
        has_uncertain = op.violation_type == "uncertain"
        state["_debate_result"] = {
            "debated": False,
            "needs_human_review": has_uncertain,
            "opinion_count": 1,
            "final_type": op.violation_type if not has_uncertain else "uncertain",
            "final_confidence": op.confidence,
            "summary": "单一Agent意见, 直接采纳",
        }
        if has_uncertain:
            state["_human_review"] = {"required": True,
                "reason": "Agent不确定(uncertain), 需要人工审核", "status": "PENDING"}
    else:
        state["_debate_result"] = {"debated": False, "opinion_count": 0,
            "needs_human_review": False, "summary": "无Agent提交意见"}

    # 辩论升级/Agent不确定 → 暂停等人工
    dr = state.get("_debate_result") or {}
    hr = state.get("_human_review") or {}
    if dr.get("needs_human_review") or hr.get("required"):
        state["_human_review"] = hr if hr.get("required") else {
            "required": True,
            "reason": dr.get("summary", "辩论升级"),
            "status": "PENDING",
        }
        # R20 修复: 待人工复核期间也必须给出非空终局（REVIEW），
        # 否则 final_decision 为空 → 评测归因/API 返回全部失效。
        if state.get("final_decision") in (None, ""):
            tr = state.get("text_result") or {}
            score = float(tr.get("risk_score", 0.0))
            vt = tr.get("violation_type", "none")
            state["final_risk"] = {
                "overall_score": score,
                "violation_types": [vt] if vt != "none" else [],
                "pending_human_review": True,
            }
            state["final_decision"] = "REVIEW"
        return state

    # ═══════════════════ 阶段2: 风险计算 (原 RiskAgent) ═══════════════════

    # GraphRAG 洞察
    try:
        graph_rag = _get_graph_rag()
        risk = state.get("final_risk") or {}
        violation_types = risk.get("violation_types", [])
        if violation_types:
            insights = graph_rag.get_insights(violation_types)
            state["_graph_insights"] = insights
    except Exception as e:
        logger.warning(f"GraphRAG insight failed: {e}")

    result = await _get_risk_agent().process(state)

    # R7·E3: 终止双签 — 确定性规则硬校验（高危类型/硬阈值/双签确认）
    from agent_moderation.workers.termination_check import apply_termination_check
    if apply_termination_check(state):
        logger.warning(f"[termination] 硬终止: {state.get('_termination', {}).get('reasons')}")
        # R21: 终止双签埋点（记录 3 条规则的命中原因）
        # R22: pipeline_log 可能为 None（独立进程/eval context），需判空
        _term = state.get("_termination") or {}
        if pipeline_log:
            pipeline_log.step("🛑 TERMINATION", "终止双签触发: 硬终止 → REJECT",
                              output_data={"hard_reject": True,
                                           "reasons": _term.get("reasons", []),
                                           "brain_suggested": _term.get("brain_suggested", False),
                                           "score": _term.get("score", 0)})
    elif pipeline_log:
        # 未触发硬终止也记录检查结果（三车道可观测性：双签未通过）
        _term = state.get("_termination") or {}
        pipeline_log.step("🛑 TERMINATION", "终止双签检查: 未触发硬终止",
                          output_data={"hard_reject": False,
                                       "brain_suggested": bool((state.get("_brain_decision") or {}).get("terminate_suggested")),
                                       "score": float((state.get("final_risk") or {}).get("overall_score", 0))})

    # ═══════════════════ 阶段3: 事后处理 (fire-and-forget) ═══════════════════
    _schedule_feedback_collection(state)
    _schedule_hard_case_mining(state)
    _schedule_memory_consolidation(state)

    if pipeline_log:
        fr = state.get("final_risk", {})
        pipeline_log.step("📊 RISK_ASSESS", f"风险评估: {state.get('final_decision', '?')}",
                          output_data={"decision": state.get("final_decision"),
                                       "score": fr.get("overall_score", 0),
                                       "types": fr.get("violation_types", []),
                                       "components": list(fr.get("components", {}).keys())},
                          duration_ms=(time.time()-start)*1000)

    _send_a2a_message(state, "risk_agent", "END",
                      f"Workflow completed: {state.get('final_decision', '?')}")
    return result


async def planner_node(state: ModerationState) -> ModerationState:
    """
    Planner — 多模态任务编排器 (固定路线, 0 LLM 调度开销)

    5-Phase Pipeline:
      Phase 1: 内容解析      FileAgent 解析文件 + 构建 ContentGraph
      Phase 2: 独立模态分析   ImageAgent(s) ‖ AudioAgent(s) 并行 (含上下文感知)
      Phase 3: 上下文融合     OCR/ASR → 合并文本 → TextAgent 增强分析
      Phase 4: 跨模态关联     规则引擎检测图文矛盾/图文互证/OCR融合/音频关联
      Phase 5: 结果输出      写入 state, 标记 _planner_processed

    DAG 依赖:
      FileAgent
        ├──→ ImageAgent(s) ──┐
        ├──→ AudioAgent(s) ──┤
        │                     ├──→ TextAgent → 跨模态关联 → 输出
        └──→ (文本内容) ──────┘
    """
    import asyncio as _asyncio
    import time as _time
    from types import SimpleNamespace as _SN
    from common.logger import get_pipeline
    from common.logger import get_flow_logger as _get_fl

    def _ensure_plain_dict(obj):
        """递归将 SimpleNamespace 和所有嵌套结构转为纯 dict/list/标量"""
        if isinstance(obj, _SN):
            return {k: _ensure_plain_dict(v) for k, v in obj.__dict__.items()
                    if not k.startswith("_")}
        elif isinstance(obj, dict):
            return {k: _ensure_plain_dict(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [_ensure_plain_dict(v) for v in obj]
        return obj

    pipeline = get_pipeline()
    fl = _get_fl()
    content_id = state.get("content_id", "unknown")
    content_type = state.get("content_type", "text")
    content = state.get("content") or {}
    files = content.get("files", [])
    text = content.get("text", "")

    # 单模态不经过 Planner (route 层已判断, 此处防御)
    if not (content_type in ("multi_modal",) or state.get("_is_multimodal") or (content_type == "text" and files)):
        return state

    state["messages"].append({"role": "planner", "content": f"Planner orchestrating: {len(files)} files"})
    if fl:
        fl.box_start("🔄 PLANNER", f"多模态编排: text={len(text)}字, files={len(files)}")
    t0 = _time.time()

    try:
        # ================================================================
        # Phase 1: 内容解析 — FileAgent 构建 ContentGraph
        # ================================================================
        if fl: fl.box_step("📁", "Phase 1 文件解析", f"{len(files)} 个文件", "blue")
        file_results = {}
        combined_text = text

        if files:
            from agent_moderation.agents.file_agent import FileAgent
            file_agent = FileAgent()
            state = await file_agent.process(state)
            file_results = state.get("file_results") or {}
            combined_text = state.get("content", {}).get("text", "") or text
            state["content"]["text"] = combined_text
            # v4.0.1: FileAgent 可能从 DOCX 中提取了嵌入图片, 重新读取 files
            files = state.get("content", {}).get("files", []) or files
            if fl:
                fl.box_step("📄", "文件解析完成",
                           f"text={len(combined_text)}字, files={len(files)}(含嵌入)",
                           "green")

        if pipeline:
            pipeline.step("📁 PLAN_P1_FILE", f"文件解析: {len(files)}文件 → {len(combined_text)}字")

        # ================================================================
        # Phase 2: 独立模态分析  ImageAgent ‖ AudioAgent (并行, 含上下文)
        # ================================================================
        if fl: fl.box_step("🎯", "Phase 2 模态并行分析", "图片 ‖ 音频", "blue")

        # 收集需要分析的图片和音频
        all_image_infos = []
        audio_files = []

        # 2a: 从 files 中收集图片和音频
        for f in files:
            mime = f.get("mime_type", "")
            fname = f.get("filename", "").lower()
            is_embedded = f.get("_docx_embedded", False)
            char_pos = f.get("_char_position")

            if mime.startswith("image/"):
                ctx_before = combined_text[max(0, char_pos - 500):char_pos] if is_embedded and char_pos is not None else ""
                ctx_after = combined_text[char_pos:min(len(combined_text), char_pos + 500)] if is_embedded and char_pos is not None else ""
                all_image_infos.append({
                    "filename": f.get("filename", f"image_{len(all_image_infos)}"),
                    "content": f.get("content", b""),
                    "mime_type": mime,
                    "is_embedded": is_embedded,
                    "char_position": char_pos,   # P2: 位置锚定, 供 Phase 3 插回文档
                    "context_before": ctx_before,
                    "context_after": ctx_after,
                })
            elif mime.startswith("audio/") or fname.endswith(
                (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma")
            ):
                audio_files.append(f)

        # 2b: 从内容中收集独立图片和音频
        for key in ["image", "image_data"]:
            img = content.get(key)
            if img and isinstance(img, bytes) and len(img) > 0:
                all_image_infos.append({
                    "filename": f"standalone_{key}",
                    "content": img,
                    "mime_type": "image/unknown",
                    "is_embedded": False,
                    "context_before": text[:500] if text else "",
                    "context_after": "",
                })
        for key in ["audio", "audio_data"]:
            aud = content.get(key)
            if aud and isinstance(aud, bytes) and len(aud) > 0:
                audio_files.append({"filename": f"standalone_{key}", "content": aud, "mime_type": "audio/unknown"})

        image_results = []
        audio_result = None

        if all_image_infos or audio_files:
            from agent_moderation.agents.image_agent import ImageAgent
            from agent_moderation.agents.audio_agent import AudioAgent
            image_agent = ImageAgent()
            audio_agent_instance = AudioAgent()
            sem = _asyncio.Semaphore(5)

            async def _process_one_image(info: dict) -> dict:
                async with sem:
                    img_state = {
                        "content": {
                            "image": info["content"],
                            "filename": info["filename"],
                            "image_context": {
                                "before": info["context_before"],
                                "after": info["context_after"],
                            } if (info["context_before"] or info["context_after"]) else {},
                        },
                        "content_id": content_id,
                    }
                    result_state = await image_agent.process(img_state)
                    img_result = result_state.get("image_result") or {}
                    # P2: 附上位置锚定, 供 Phase 3 按文档位置插回图片描述
                    img_result["char_position"] = info.get("char_position")
                    img_result["is_embedded"] = info.get("is_embedded", False)
                    return img_result

            async def _process_one_audio(f: dict) -> dict:
                audio_state = {
                    "content": {"audio": f["content"], "filename": f.get("filename", "unknown")},
                    "content_id": content_id,
                }
                result_state = await audio_agent_instance.process(audio_state)
                return result_state.get("audio_result") or {}

            # 图片 + 音频完全并行
            all_tasks = [_process_one_image(info) for info in all_image_infos]
            all_tasks += [_process_one_audio(f) for f in audio_files]
            all_task_labels = (
                [f"image_{i}" for i in range(len(all_image_infos))]
                + [f"audio_{i}" for i in range(len(audio_files))]
            )

            all_results = await _asyncio.gather(*all_tasks, return_exceptions=True)

            # 分类结果 (v4.0.1: 递归转纯 dict, 防止 SimpleNamespace 泄漏)
            for i, result in enumerate(all_results):
                if isinstance(result, Exception):
                    logger.warning(f"[Planner] Phase 2 task {all_task_labels[i]} failed: {result}")
                    continue
                if all_task_labels[i].startswith("image_"):
                    image_results.append(_ensure_plain_dict(result))
                else:
                    audio_result = _ensure_plain_dict(result)

            if fl:
                fl.box_step("🖼️", f"图片分析: {len(image_results)}/{len(all_image_infos)} 完成",
                           f"max_risk={max((r.get('risk_score',0) for r in image_results), default=0):.2f}", "green")
                if audio_result:
                    fl.box_step("🎤", "音频分析完成",
                               f"risk={audio_result.get('risk_score', 0):.2f}, "
                               f"ASR={(audio_result.get('transcribed_text','') or '')[:40]}",
                               "green")

        if pipeline:
            pipeline.step("🎯 PLAN_P2_MODAL",
                         f"模态分析: {len(image_results)}图片 + {1 if audio_result else 0}音频",
                         output_data={"image_count": len(image_results), "audio": bool(audio_result)})

        # ================================================================
        # Phase 3: 上下文融合  OCR/ASR → 合并文本 → TextAgent
        # ================================================================
        if fl: fl.box_step("🔗", "Phase 3 上下文融合", "OCR/ASR → 文本合并 → TextAgent", "blue")

        # 3a: 收集 OCR 文字 + 图片视觉描述 + ASR 转写
        # v4.1: 不仅注入 OCR 文字, 也注入 VL 模型返回的视觉场景描述和可疑元素,
        #       让 TextAgent 能基于「图文融合」而非仅「OCR文字」做判断
        ocr_texts = []
        image_descriptions = []  # v4.1: 视觉描述片段
        image_judgments = []     # P2: 每图判定+描述片段 [(char_position, is_embedded, block), ...]
        suspicious_images = []
        for i, img_r in enumerate(image_results):
            ocr = img_r.get("ocr_text", "")
            if ocr and ocr.strip():
                ocr_texts.append(f"[图片{i+1} OCR: {ocr}]")

            # v4.1: 收集 VL 视觉描述 (scene_description/reason/suspicious_elements)
            desc_parts = []
            scene = img_r.get("scene_description", "") or img_r.get("scene", "")
            if scene and scene.strip():
                desc_parts.append(f"场景: {scene}")
            reason = img_r.get("reason", "")
            if reason and reason.strip():
                desc_parts.append(f"判定: {reason}")
            suspicious = img_r.get("suspicious_elements", [])
            if suspicious:
                desc_parts.append(f"可疑元素: {', '.join(str(s) for s in suspicious[:5])}")
            if desc_parts:
                image_descriptions.append(
                    f"[图片{i+1} 视觉分析] {'; '.join(desc_parts)}")

            # P2: 每图违规判定注入 — 整体审核能明确看到图片判定结果与位置
            vt = img_r.get("violation_type", "none")
            conf = img_r.get("confidence", 0.0)
            risk = img_r.get("risk_score", 0.0)
            block = (f"[图片{i+1} 判定: {vt} conf={conf:.2f} risk={risk:.2f}]"
                     + (f" 内容: {'; '.join(desc_parts)}" if desc_parts else ""))
            image_judgments.append((img_r.get("char_position"), img_r.get("is_embedded", False), block))

            if vt != "none" or risk > 0.3:
                suspicious_images.append({
                    "index": i + 1,
                    "violation_type": vt,
                    "confidence": conf,
                    "risk_score": risk,
                    "reason": reason,
                })

        asr_text = ""
        if audio_result:
            asr_text = audio_result.get("transcribed_text", "") or ""
            if asr_text and asr_text.strip():
                asr_text = f"[音频转写: {asr_text}]"

        # 3b: P2 位置化融合 — 有 char_position 的图片描述/判定插回文档对应位置,
        #     保持"上文-图片描述-下文"上下文连贯; 无锚定的独立图追加末尾
        anchored = [(cp, txt) for cp, emb, txt in image_judgments if cp is not None and emb]
        standalone_blocks = [txt for cp, emb, txt in image_judgments if not (cp is not None and emb)]

        if anchored:
            position_text = combined_text
            for cp, block in sorted(anchored, key=lambda x: x[0], reverse=True):
                pos = max(0, min(int(cp), len(position_text)))
                position_text = position_text[:pos] + block + position_text[pos:]
            fused_text_parts = [position_text] + standalone_blocks
        else:
            fused_text_parts = [combined_text] + [txt for _, _, txt in image_judgments]

        if asr_text:
            fused_text_parts.append(asr_text)
        fused_text = "\n".join(p for p in fused_text_parts if p.strip())

        state["content"]["text"] = fused_text
        state["_fused_text"] = fused_text  # 保留融合文本供后续

        if fl:
            fl.box_step("📝", "文本融合",
                       f"原文{len(combined_text)}字 + OCR{len(ocr_texts)}段 + 视觉{len(image_descriptions)}段 + ASR{len(asr_text)}字 = {len(fused_text)}字",
                       "green")

        # 3c: TextAgent 对融合文本做增强分析 (v4.0.1: 结果转纯 dict)
        text_result = {}
        if fused_text.strip():
            from agent_moderation.agents.text_agent import TextAgent
            text_agent = TextAgent()
            text_state = {
                "content": {"text": fused_text},
                "content_id": content_id,
                "content_type": "text",
                "messages": [],
            }
            text_result_state = await text_agent.process(text_state)
            text_result = _ensure_plain_dict(text_result_state.get("text_result") or {})

            if fl:
                fl.box_step("🧠", "TextAgent 融合分析",
                           f"vt={text_result.get('violation_type','none')} "
                           f"conf={text_result.get('confidence',0):.2f} "
                           f"keywords={text_result.get('keyword_count',0)}",
                           "green")

        if pipeline:
            pipeline.step("🔗 PLAN_P3_FUSION",
                         f"文本融合: {len(fused_text)}字 → TextAgent",
                         output_data={"fused_len": len(fused_text),
                                      "violation_type": text_result.get("violation_type")})

        # ================================================================
        # Phase 4: 跨模态关联分析 (规则引擎, 0 LLM 调用)
        # ================================================================
        if fl: fl.box_step("🔀", "Phase 4 跨模态关联", "图文矛盾/图文互证/OCR融合/音频关联", "blue")

        cross_modal_findings = []

        # 4a: 图文矛盾检测
        text_vt = text_result.get("violation_type", "none")
        text_conf = text_result.get("confidence", 0)
        for si in suspicious_images:
            if si["violation_type"] != "none" and text_vt == "none" and si["confidence"] > 0.5:
                cross_modal_findings.append({
                    "type": "图文矛盾",
                    "severity": "high",
                    "detail": f"文本判定正常但图片{si['index']}检测到"
                             f"{si['violation_type']}(conf={si['confidence']:.2f})",
                    "suggestion": "图片可能用于绕过文本审核, 建议以图片判定为准",
                })

        # 4b: 图文互证增强
        for si in suspicious_images:
            if si["violation_type"] == text_vt and text_vt != "none":
                cross_modal_findings.append({
                    "type": "图文互证",
                    "severity": "info",
                    "detail": f"文本+图片{si['index']}一致判定为{text_vt}, 置信度提升",
                    "suggestion": f"建议置信度上浮 15%",
                })
                # 实际提升置信度
                if text_result:
                    text_result["confidence"] = min(
                        text_result.get("confidence", 0) * 1.15, 1.0
                    )

        # 4c: OCR 语义融合
        if ocr_texts and text_result.get("violation_type", "none") != "none":
            cross_modal_findings.append({
                "type": "OCR语义融合",
                "severity": "info",
                "detail": f"图片OCR文字与文本分析结果关联: {len(ocr_texts)}段OCR",
                "suggestion": "OCR内容已合并到文本分析中",
            })

        # 4d: 音频-文本关联
        if audio_result and audio_result.get("violation_type", "none") != "none":
            cross_modal_findings.append({
                "type": "音频关联",
                "severity": "medium" if audio_result.get("risk_score", 0) > 0.5 else "low",
                "detail": f"音频检测到{audio_result.get('violation_type')}"
                         f"(conf={audio_result.get('confidence', 0):.2f})",
                "suggestion": "音频转写已合并到文本分析中",
            })

        state["_cross_modal_findings"] = cross_modal_findings

        if fl:
            for f_cm in cross_modal_findings:
                icon = {"high": "⚠️", "medium": "⚡", "low": "→", "info": "✅"}.get(f_cm["severity"], "→")
                fl.box_step(icon, f_cm["type"], f_cm["detail"], "yellow" if f_cm["severity"] == "high" else "white")

        if pipeline:
            pipeline.step("🔀 PLAN_P4_CROSS_MODAL",
                         f"跨模态关联: {len(cross_modal_findings)} 发现",
                         output_data={"findings": len(cross_modal_findings)})

        # ================================================================
        # Phase 5: 结果输出  写入 state
        # ================================================================
        if fl: fl.box_step("📤", "Phase 5 输出", "写入 state", "blue")

        # 取最高风险分的图片结果作为 image_result
        best_image = None
        best_img_score = 0
        for ir in image_results:
            if ir.get("risk_score", 0) > best_img_score:
                best_img_score = ir.get("risk_score", 0)
                best_image = ir

        state["text_result"] = _ensure_plain_dict(text_result)
        state["image_result"] = _ensure_plain_dict(best_image or next(iter(image_results), {}))
        state["audio_result"] = _ensure_plain_dict(audio_result or {})
        state["file_results"] = _ensure_plain_dict(file_results)
        state["_planner_processed"] = True
        state["_task_plan"] = {
            "mode": "planner",
            "phases": ["parse", "modal", "fusion", "cross_modal", "output"],
            "image_count": len(image_results),
            "audio_count": 1 if audio_result else 0,
            "ocr_segments": len(ocr_texts),
            "image_descriptions": len(image_descriptions),  # v4.1
            "cross_modal_findings": len(cross_modal_findings),
        }

        total_ms = (_time.time() - t0) * 1000
        if fl:
            fl.box_end("🔄 PLANNER",
                       f"images={len(image_results)} audio={1 if audio_result else 0} "
                       f"vt={text_result.get('violation_type','none')} "
                       f"conf={text_result.get('confidence',0):.2f} "
                       f"cross_modal={len(cross_modal_findings)} ({total_ms:.0f}ms)")
        if pipeline:
            pipeline.step("🔄 PLANNER",
                         f"多模态编排完成: {len(image_results)}图+{1 if audio_result else 0}音 → "
                         f"{text_result.get('violation_type','none')} "
                         f"conf={text_result.get('confidence',0):.2f}",
                         output_data={
                             "images": len(image_results),
                             "audio": bool(audio_result),
                             "text_vt": text_result.get("violation_type"),
                             "text_conf": text_result.get("confidence", 0),
                             "cross_modal": len(cross_modal_findings),
                         },
                         duration_ms=total_ms)

        logger.info(f"[Planner] {content_id}: {len(image_results)} images + "
                    f"{1 if audio_result else 0} audio → "
                    f"{text_result.get('violation_type', 'none')} conf={text_result.get('confidence', 0):.2f} "
                    f"cross_modal={len(cross_modal_findings)}")

    except Exception as e:
        logger.error(f"[Planner] failed: {e}")
        import traceback as _tb
        _tb.print_exc()
        # v4.0.1: 即使失败也标记已处理, 保留已有的部分结果, 避免下游重复处理
        state["_planner_processed"] = True
        state["_task_plan"] = {"mode": "planner", "error": str(e)[:100],
                               "partial": True}
        if fl:
            fl.box_step("❌", "Planner 部分失败", str(e)[:80], "red")
            fl.box_step("⚠️", "降级", "保留已有结果, 跳过下游重复处理", "yellow")
            fl.box_end("🔄 PLANNER", f"PARTIAL (error: {str(e)[:40]})")
        if pipeline:
            pipeline.step("🔄 PLANNER", f"部分失败(已降级): {str(e)[:50]}", level="WARN")

    return state


# === 路由函数 ===

def triage_node(state: ModerationState) -> ModerationState:
    """分诊台（R6·E2）：风险×复杂度估计 → 三车道 low/med/high。

    消费 F3 的 ModelRouter（此前无人调用）。非文本内容直接走 med（规则分诊只对文本有效）。
    """
    content_type = state.get("content_type", "text")
    content = state.get("content") or {}
    files = content.get("files", [])

    # 多模态/含文件 → 直接走 med 标准车道，不走 fast_lane
    if content_type != "text" or files:
        reason = "非文本内容，直接走标准车道" if content_type != "text" else f"含{len(files)}个文件，走标准车道"
        state["_tier"] = "med"
        state["_triage"] = {"risk": 0.5, "complexity": 5, "pre_judgment": "UNCERTAIN",
                            "reason": reason, "cost_saved": False}
        # R21: 三车道分流埋点（非文本/含文件 → med）
        from common.logger import get_pipeline
        _pl = get_pipeline()
        if _pl:
            _pl.step("🚦 TRIAGE", f"分诊台: {reason}", output_data={
                "tier": "med", "risk": 0.5, "complexity": 5, "reason": reason,
            })
        return state

    from agent_moderation.workers.triage import TriageEngine

    text = state.get("content", {}).get("text", "")
    d = TriageEngine().triage(text, content_type)
    state["_tier"] = d.tier.value
    state["_triage"] = {
        "risk": d.risk, "complexity": d.complexity,
        "pre_judgment": d.pre_judgment, "reason": d.reason,
        "cost_saved": d.cost_saved,
    }
    logger.info(f"[triage] tier={d.tier.value} risk={d.risk} complexity={d.complexity} ({d.reason})")
    # R21: 三车道分流埋点（文本 → low/med/high）
    from common.logger import get_pipeline
    _pl = get_pipeline()
    if _pl:
        _pl.step("🚦 TRIAGE", f"分诊台: tier={state['_tier']} risk={d.risk:.2f} complexity={d.complexity}",
                 output_data={"tier": state["_tier"], "risk": d.risk, "complexity": d.complexity,
                              "pre_judgment": d.pre_judgment, "reason": d.reason,
                              "cost_saved": d.cost_saved})
    return state


def route_after_triage(state: ModerationState) -> Literal[
    "fast_lane", "brain", "text_agent", "image_agent", "audio_agent", "video_agent",
    "file_agent", "planner", "__end__"
]:
    """分诊后路由（R6·E2/E3）：low→快车道 / high→大脑 / med→现状路由"""
    tier = state.get("_tier", "med")
    # R21: 三车道分流埋点（记录最终落入哪条车道）
    from common.logger import get_pipeline as _get_pl_triage
    _pl_triage = _get_pl_triage()
    if tier == "low":
        logger.info("[triage] low → fast_lane")
        if _pl_triage:
            _pl_triage.step("🔀 LANE_ROUTE", "low → fast_lane (qwen 快车道)",
                            output_data={"tier": "low", "target": "fast_lane"})
        return "fast_lane"
    if tier == "high":
        logger.info("[triage] high → brain")
        if _pl_triage:
            _pl_triage.step("🔀 LANE_ROUTE", "high → brain (大脑仲裁)",
                            output_data={"tier": "high", "target": "brain"})
        return "brain"
    target = route_by_content_type(state)  # med：复用现状路由，行为不变
    if _pl_triage:
        _pl_triage.step("🔀 LANE_ROUTE", f"med → {target} (标准车道)",
                        output_data={"tier": "med", "target": target})
    return target


async def fast_lane_node(state: ModerationState) -> ModerationState:
    """快车道（R6·E3 + R19·M2）：小模型判定，无信号升级大模型。

    R19 修复：此前规则直判 PASS（0 LLM），导致无关键词违规（隐私窃取/歧视/
    虚假信息等）被系统性漏判（T1 实测 OutSafe 有害样本全放行）。
    现在快车道 = 小模型（规则信号评分器）判定：
      - 明确信号 → 小模型直接 REJECT/REVIEW/PASS（省大模型成本）
      - 无信号 → needs_upgrade → 走 text_agent 完整 LLM 审核（防漏判）
    """
    text = state.get("content", {}).get("text", "")
    result = None
    # R19·M3: 优先 qwen2.5 本地小模型（用户决策），异常/不可用 fallback 规则评分器
    try:
        from agent_moderation.workers.qwen_judge import QwenLocalJudge
        result = await QwenLocalJudge().judge(text)
    except Exception as e:
        logger.warning(f"[fast_lane] qwen2.5 小模型异常: {e}")
    if result is None:
        try:
            from agent_moderation.workers.rule_small_judge import RuleSmallJudge
            result = await RuleSmallJudge().judge(text)
        except Exception as e:
            logger.warning(f"[fast_lane] 规则小模型异常，升级完整审核: {e}")
            result = {"needs_upgrade": True}

    if result.get("needs_upgrade"):
        # 升级：完整 text_agent 审核（LLM 语义分析，防止规则漏判）
        logger.info("[fast_lane] 小模型无信号/低置信 → 升级完整审核")
        # R21: 快车道埋点（升级路径）
        from common.logger import get_pipeline as _get_pl_fl_up
        _pl_fl_up = _get_pl_fl_up()
        if _pl_fl_up:
            _pl_fl_up.step("⚡ FAST_LANE", "小模型无信号/低置信 → 升级 text_agent",
                           output_data={"path": "upgrade",
                                        "small_decision": result.get("decision"),
                                        "confidence": result.get("confidence"),
                                        "violation_type": result.get("violation_type"),
                                        "reason": str(result.get("reason", ""))[:120],
                                        "needs_upgrade": True})
        try:
            state = await _get_text_agent().process(state)
        except Exception as e:
            logger.error(f"[fast_lane] 升级审核异常: {e}")
            state["final_risk"] = {"overall_score": 0.05, "violation_types": []}
            state["final_decision"] = "REVIEW"
            return state
        tr = state.get("text_result") or {}
        score = float(tr.get("risk_score", 0.0))
        vt = tr.get("violation_type", "none")
        decision = "REJECT" if score >= 0.6 else ("REVIEW" if score >= 0.35 else "PASS")
        state["final_risk"] = {
            "overall_score": score,
            "violation_types": [vt] if vt != "none" else [],
        }
        state["final_decision"] = decision
        return state

    # 小模型采纳（快车道省大模型）
    decision = result.get("decision", "PASS")
    conf = float(result.get("confidence", 0.0))
    # R20: 透传小模型判定的违规类型（此前写死 "none"，REJECT 记录丢类型，
    # 下游按类型分析/强制终止全部失效）
    vt = result.get("violation_type") or "none"
    score = 0.9 if decision == "REJECT" else (0.55 if decision == "REVIEW" else 0.05)
    state["text_result"] = {
        "violation_type": vt, "confidence": conf, "risk_score": score,
        "decision": decision, "fast_lane": True,
        "small_model": True, "small_reason": result.get("reason", ""),
    }
    state["final_risk"] = {
        "overall_score": score,
        "violation_types": [vt] if vt != "none" else [],
    }
    state["final_decision"] = decision
    logger.info(f"[fast_lane] 小模型判定 {decision} conf={conf:.2f} vt={vt}（省大模型）")
    # R21: 快车道埋点（小模型采纳路径）
    from common.logger import get_pipeline as _get_pl_fl
    _pl_fl = _get_pl_fl()
    if _pl_fl:
        _pl_fl.step("⚡ FAST_LANE", f"小模型判定 {decision} conf={conf:.2f} vt={vt}（省大模型）",
                    output_data={"path": "adopt", "decision": decision, "confidence": conf,
                                 "violation_type": vt, "score": score,
                                 "small_model": True, "cost_saved": True})
    return state


def brain_node(state: ModerationState) -> ModerationState:
    """大脑 = 决策仲裁者（R6·E1）：4 类决策 + 终止建议。

    v5.0 规则版（无 LLM，确定性、可审计）。深度规划/仲裁在 P5 与 LLM 版衔接。
    4 类决策：规划 / 仲裁 / 升级 / 终止建议。
    """
    triage = state.get("_triage") or {}
    risk = triage.get("risk", 0.5)
    decisions = []

    # 1. 规划：按内容类型给出执行计划摘要
    content_type = state.get("content_type", "text")
    decisions.append({"type": "plan", "detail": f"按现有审核管线执行（{content_type} 路径）"})

    # 2. 仲裁：风险信号强时明确仲裁立场
    decisions.append({"type": "arbitrate", "detail": f"分诊风险 {risk:.2f}，{_risk_label(risk)}"})

    # 3. 升级：中高风险 → 建议人工复核（软信号；硬校验由确定性规则 E3 把关）。
    # R20 修复: 不得设置 _human_review.required=True，否则 risk_agent_node 阶段1
    # 会因 hr.required 提前 return，跳过风险评估/终止双签，final_decision 为空。
    # 大脑只给建议（suggested），真正的人工介入由 risk_agent 的确定性规则触发。
    escalate = risk >= 0.7
    if escalate:
        decisions.append({"type": "escalate", "detail": "风险偏高，建议人工复核"})
        state["_human_review"] = {"required": False, "reason": "大脑仲裁：风险偏高", "status": "suggested"}

    # 4. 终止建议：极高风险 → 建议直接终止（软建议，双签的硬校验在确定性层）
    terminate = risk >= 0.9
    decisions.append({"type": "terminate_suggest", "suggested": terminate,
                      "detail": "风险极高建议终止" if terminate else "未达终止阈值"})

    state["_brain_decision"] = {
        "decisions": decisions,
        "terminate_suggested": terminate,
        "plan_summary": f"大脑决策：{len(decisions)} 项，{_risk_label(risk)}",
    }
    logger.info(f"[brain] {len(decisions)} 类决策, terminate_suggested={terminate}")
    # R21: 大脑仲裁埋点（4 类决策 + 终止建议）
    from common.logger import get_pipeline as _get_pl_brain
    _pl_brain = _get_pl_brain()
    if _pl_brain:
        _pl_brain.step("🧠 BRAIN", f"{len(decisions)} 类决策, terminate_suggested={terminate}",
                       output_data={"decisions": [d["type"] for d in decisions],
                                    "terminate_suggested": terminate,
                                    "plan_summary": state["_brain_decision"]["plan_summary"],
                                    "risk": risk})
    return state


def _risk_label(risk: float) -> str:
    if risk >= 0.9:
        return "极高风险"
    if risk >= 0.7:
        return "高风险"
    if risk >= 0.4:
        return "中风险"
    return "低风险"


def route_by_content_type(state: ModerationState) -> Literal[
    "text_agent", "image_agent", "audio_agent", "video_agent", "file_agent", "planner", "__end__"
]:
    """根据内容类型路由 (v4.0: 多模态统一走 Planner)"""
    content_type = state.get("content_type", "text")
    content = state.get("content") or {}
    files = content.get("files", [])

    # 多模态/含文件 → Planner 统一调度
    if content_type == "multi_modal" or state.get("_is_multimodal") or (
        content_type == "text" and files
    ):
        logger.info(f"Routing multi-modal → planner (type={content_type}, files={len(files)})")
        return "planner"

    # 单模态: 直接路由到对应 Agent
    route_map = {
        "text": "text_agent",
        "image": "image_agent",
        "audio": "audio_agent",
        "video": "video_agent",
    }
    target = route_map.get(content_type, "text_agent")
    logger.info(f"Routing '{content_type}' → {target}")
    return target


def route_after_agent(state: ModerationState) -> Literal["react_agent", "debate_panel", "reflexion"]:
    """
    审核完成后路由 (v3.7: 移除 BlackhatAgent, 黑灰产检测已内嵌到各 Agent)

    优先: ReAct (低置信度/对抗) → Debate/Reflexion
    但如果 Agent 置信度极低 (<0.5)，先 Reflexion 再 Debate
    """
    # 检查是否需要 ReAct 深度分析 (v4.2: 任意模态, 查对应的 result)
    # ReAct 触发条件: violation_type != "none" AND (conf < 0.6 OR is_adversarial) AND NOT react_enhanced
    content_type = state.get("content_type", "text")
    modality_keys = {
        "text": "text_result",
        "image": "image_result",
        "audio": "audio_result",
        "video": "video_result",
        "multi_modal": "text_result",  # 多模态文本结果在 text_result
    }
    result_key = modality_keys.get(content_type, "text_result")
    result = state.get(result_key) or {}

    if result and not result.get("error"):
        vt = result.get("violation_type", "none")
        conf = result.get("confidence", 0)
        is_adv = result.get("is_adversarial", False)
        if vt != "none" and (conf < 0.6 or is_adv) and not result.get("react_enhanced"):
            logger.info(f"Routing to ReAct: type={content_type}, conf={conf:.2f}, adv={is_adv}")
            return "react_agent"

    return "risk_agent"


def route_to_debate(state: ModerationState) -> Literal["debate_panel", "human_in_loop", "risk_agent"]:
    """
    黑灰产检测后：判断是否需要辩论

    触发辩论条件 (v3.2 放宽):
    - 单Agent低置信度(conf<0.5) → 直通人工审核 (无需多Agent辩论)
    - 多个不同违规类型 → 辩论
    - Agent置信度 < 0.6 → 辩论 (自检)
    - 检测到对抗样本 → 辩论
    - 黑灰产模式检测到 ≥1 个pattern → 辩论
    """
    # v3.2: 单Agent低置信度直通人工审核 (绕过辩论)
    agent_count = 0
    any_low_confidence = False
    for key in ["text_result", "image_result", "audio_result", "video_result"]:
        r = state.get(key)
        if r and not r.get("error"):
            agent_count += 1
            conf = r.get("confidence", 0)
            if conf < 0.5:
                any_low_confidence = True

    if agent_count <= 1 and any_low_confidence:
        state["_human_review"] = {
            "required": True,
            "reason": f"单Agent低置信度(conf<0.5), 需要人工审核",
            "status": "PENDING",
        }
        logger.info("Routing single-agent low-confidence directly to human_in_loop")
        return "human_in_loop"

    # 收集违规类型
    violation_types = set()
    low_confidence = False
    has_adversarial = False

    for key in ["text_result", "image_result", "audio_result", "video_result"]:
        r = state.get(key)
        if r and not r.get("error"):
            vt = r.get("violation_type", "none")
            if vt and vt != "none":
                violation_types.add(vt)
            # 检查低置信度
            conf = r.get("confidence", 0)
            if vt != "none" and conf < 0.6:
                low_confidence = True
            # 检查对抗样本标记
            if r.get("is_adversarial", False):
                has_adversarial = True

    # 检查黑灰产结果（排除检测方法类模式）
    NON_VIOLATION_PATTERNS = {"BULK_GENERATION", "KEYWORD_VARIANT", "FORMAT_SPOOFING"}
    blackhat = state.get("blackhat_result", {})
    for p in blackhat.get("pattern_detected", []):
        ptype = p.get("type", "")
        if ptype and ptype not in NON_VIOLATION_PATTERNS:
            violation_types.add(ptype)

    # 多个不同的违规类型 → 触发辩论
    if len(violation_types) >= 2:
        logger.info(f"Routing to debate: {len(violation_types)} unique violation types: {violation_types}")
        return "risk_agent"

    # 低置信度 → 需要通过辩论或反思来提高判定质量
    if low_confidence:
        logger.info(f"Routing to debate: low confidence detected")
        return "risk_agent"

    # v3.1: 单Agent高危类型且中低置信度→ 触发辩论 (R20: 引用统一常量，含 crime)
    from agent_moderation.violation_types import HIGH_RISK_TYPES
    if len(violation_types) == 1:
        vt = list(violation_types)[0]
        if vt in HIGH_RISK_TYPES:
            # 检查置信度
            for key in ["text_result", "image_result", "audio_result", "video_result"]:
                r = state.get(key)
                if r and r.get("violation_type") == vt:
                    conf = r.get("confidence", 0)
                    if conf < 0.7:
                        logger.info(f"Routing to debate: single high-risk type '{vt}' with confidence {conf:.2f}")
                        return "risk_agent"

    # 对抗样本 → 需要辩论仔细审核
    if has_adversarial:
        logger.info(f"Routing to debate: adversarial sample detected")
        return "risk_agent"

    # 黑灰产模式 → 复杂case需要辩论
    if len(blackhat.get("pattern_detected", [])) >= 1:
        logger.info(f"Routing to debate: blackhat pattern detected")
        return "risk_agent"

    logger.info("Routing directly to risk_agent (simple case)")
    return "risk_agent"


def route_after_debate(state: ModerationState) -> Literal["reflexion", "human_in_loop", "risk_agent"]:
    """
    辩论后路由

    - 如果辩论结果升级 → 人工审核
    - 如果 _human_review.required (单Agent直通) → 人工审核
    - 如果辩论后置信度仍低 → Reflexion
    - 否则 → Risk
    """
    debate_result = (state.get("_debate_result") or {})
    human_review = (state.get("_human_review") or {})

    # v3.2: 检查单Agent直通标记
    if human_review.get("required"):
        return "human_in_loop"

    if debate_result.get("needs_human_review"):
        return "human_in_loop"

    if debate_result.get("debated") and debate_result.get("final_confidence", 1.0) < 0.6:
        return "reflexion"

    return "risk_agent"


def route_after_risk(state: ModerationState) -> Literal["human_in_loop", "__end__"]:
    """
    v3.2: risk_agent 后路由

    - 如果 risk_agent 设置了 _human_review.required 且状态为 PENDING → 人工审核
    - 人工审核已处理 (status=RESOLVED) → 正常结束
    - 否则 → 正常结束
    """
    human_review = (state.get("_human_review") or {})
    if human_review.get("required") and human_review.get("status") == "PENDING":
        logger.info(f"Risk agent flagged for human review: {human_review.get('reason')}")
        return "human_in_loop"
    return "__end__"


def route_after_human(state: ModerationState) -> Literal["risk_agent", "__end__"]:
    """
    人工审核节点后路由

    当前: 直接进入 Risk 评估 (未来可接入实际人工审核系统)
    """
    human_review = (state.get("_human_review") or {})
    if human_review.get("required"):
        logger.info("Human review required — proceeding to risk assessment with flag")
    return "risk_agent"


def route_after_reflexion(state: ModerationState) -> Literal["risk_agent"]:
    """Reflexion 后直接进入 Risk"""
    return "risk_agent"


# === 工作流构建 ===

def create_moderation_workflow() -> StateGraph:
    """
    创建内容审核工作流 v3.7

    全链路 (v4.2: reflexion 合并到 react_agent Phase 2):
      Supervisor → [Text|Image|Audio|Video] (含黑灰产检测)
        → [ReAct (含Phase2自校准)?] → [Human-in-Loop?] → Risk → END

    仅存节点:
      - human_in_loop: 高风险人工审核
    """
    workflow = StateGraph(ModerationState)

    # 添加所有节点 (v4.2: 移除 debate_panel + reflexion)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("text_agent", text_agent_node)
    workflow.add_node("image_agent", image_agent_node)
    workflow.add_node("audio_agent", audio_agent_node)
    workflow.add_node("video_agent", video_agent_node)
    workflow.add_node("file_agent", file_agent_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("react_agent", react_agent_node)
    workflow.add_node("human_in_loop", human_in_loop_node)
    workflow.add_node("risk_agent", risk_agent_node)
    # v5.0（R6·E1/E2/E3）：分诊台 + 快车道 + 大脑
    workflow.add_node("triage", triage_node)
    workflow.add_node("fast_lane", fast_lane_node)
    workflow.add_node("brain", brain_node)

    # 设置入口
    workflow.set_entry_point("supervisor")

    # === 路由配置 (v3.8: 复杂case先过TaskPlanner；v5.0: 先分诊三车道) ===

    # Supervisor → Triage（分诊台）→ 三车道
    workflow.add_edge("supervisor", "triage")
    workflow.add_conditional_edges(
        "triage", route_after_triage,
        {
            "fast_lane": "fast_lane",
            "brain": "brain",
            "text_agent": "text_agent",
            "image_agent": "image_agent",
            "audio_agent": "audio_agent",
            "video_agent": "video_agent",
            "file_agent": "file_agent",
            "planner": "planner",           # v3.8: 复杂任务先规划
            "__end__": END,
        },
    )

    # 快车道 → END（规则直判，无后续节点）
    workflow.add_edge("fast_lane", END)
    # 大脑 → 现状路由（决策后走现有执行管线，行为与 med 一致）
    workflow.add_conditional_edges(
        "brain", route_by_content_type,
        {
            "text_agent": "text_agent",
            "image_agent": "image_agent",
            "audio_agent": "audio_agent",
            "video_agent": "video_agent",
            "file_agent": "file_agent",
            "planner": "planner",
            "__end__": END,
        },
    )

    # Planner → FileAgent (规划后还是先解析文件)
    workflow.add_edge("planner", "file_agent")

    # 各模态 Agent → ReAct / Risk (v4.2: reflexion 合并到 react Phase 2)
    for agent in ["text_agent", "image_agent", "audio_agent", "video_agent"]:
        workflow.add_conditional_edges(agent, route_after_agent, {
            "react_agent": "react_agent",
            "risk_agent": "risk_agent",
        })

    # ReAct → Risk (v4.2: Phase 2 自校准后进入风险评估)
    workflow.add_edge("react_agent", "risk_agent")
    # FileAgent 解析完成后进入 TextAgent 语义分析
    workflow.add_edge("file_agent", "text_agent")

    # Human-in-Loop → Risk 或等待
    workflow.add_conditional_edges("human_in_loop", route_after_human, {
        "risk_agent": "risk_agent",
        "__end__": END,
    })

    # Risk → END (v3.2: risk_agent 设置 _human_review.required 标记, API层检测后注册待审核)
    # R8·E4 (F1 修复): risk_agent → 人工审核 或 结束（此前直连 END，route_after_risk 从未接线）
    workflow.add_conditional_edges("risk_agent", route_after_risk, {
        "human_in_loop": "human_in_loop",
        "__end__": END,
    })

    checkpointer = MemorySaver()
    logger.info("Moderation workflow compiled successfully")
    return workflow.compile(checkpointer=checkpointer)


# v3.1: 编译后的工作流缓存 (避免每次请求重新编译)
_compiled_workflow = None


def get_workflow():
    """获取编译后的工作流实例 (v3.1 — 全局缓存, 避免重复编译)"""
    global _compiled_workflow
    global _compiled_workflow
    if _compiled_workflow is None:
        _compiled_workflow = create_moderation_workflow()
    return _compiled_workflow
