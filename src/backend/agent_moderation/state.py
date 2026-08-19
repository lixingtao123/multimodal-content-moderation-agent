"""
LangGraph 审核状态定义 v3.0 — ModerationState TypedDict
所有 Agent 节点读写此状态，是工作流的数据中枢

v3.0 新增:
  - _is_multimodal: 多模态标记
  - _debate_result: 辩论结果
  - _reflexion_result: 反思结果
  - _human_review: 人工审核状态
  - _rag_result: Agentic RAG 结果
  - _graph_insights: GraphRAG 洞察
"""
from typing import TypedDict, Annotated, Optional
import operator


class ModerationState(TypedDict, total=False):
    """内容审核状态 — LangGraph 工作流的全局状态 (v3.0)"""

    # 任务标识
    content_id: str
    content_type: str                    # text / image / audio / video

    # 原始内容
    content: dict                        # {"text": "..."} / {"image": bytes} / ...
    account_id: Optional[str]

    # 消息历史 (Agent 间传递，自动追加)
    messages: Annotated[list, operator.add]

    # 各 Agent 的分析结果
    text_result: Optional[dict]
    image_result: Optional[dict]
    audio_result: Optional[dict]
    video_result: Optional[dict]

    # 黑灰产识别结果
    blackhat_result: Optional[dict]

    # 综合风险评估
    final_risk: Optional[dict]
    final_decision: str                  # PASS / REVIEW / REJECT

    # === v3.0 新增字段 ===

    # 多模态标记 (视频 = 视觉 + 音频)
    _is_multimodal: bool

    # Debate Panel 结果
    _debate_result: Optional[dict]       # {debated, mode, final_type, final_confidence, ...}

    # Reflexion 结果
    _reflexion_result: Optional[dict]    # {reflected, details: {agent_key: {...}}}

    # Human-in-the-Loop 状态
    _human_review: Optional[dict]        # {required, reason, status}

    # Agentic RAG 结果
    _rag_result: Optional[dict]          # {results, rounds, self_rag_confidence, graph_insights}

    # GraphRAG 洞察
    _graph_insights: Optional[dict]      # {violation_types, related_violation_types, ...}

    # Multi-Modal RAG 结果 (图片视觉相似案例)
    _multimodal_rag_result: Optional[dict]  # {activated, results_count, top_scores}

    # ReAct Agent 结果
    _react_result: Optional[dict]        # {activated, steps, tools_called, reasoning_trace}

    # 人工审核决策 (Human-in-the-Loop 恢复后注入)
    human_decision: Optional[dict]       # {decision, reason, reviewer_id}

    # A2A Protocol 任务ID
    _a2a_task_id: Optional[str]

    # 文件审查结果 (FileAgent)
    file_results: Optional[dict]          # {file_count, total_chars, files, combined_text}

    # 辩论摘要 (供前端展示)
    debate_summary: Optional[dict]         # {had_debate, mode, opinions, ...}

    # 审核开始时间
    start_time: float

    # === v3.3: 异步任务 + 多模态协调字段 ===
    # 分块结果 (超长文本分块处理)
    _chunk_results: Optional[list]          # [{index, text, result}, ...]

    # 多模态融合结果
    _fusion_result: Optional[dict]          # {modalities_analyzed, text_chunked, is_truncated, ...}

    # 多图并行结果
    _multi_image_results: Optional[list]    # [{image_result}, ...]

    # 进度回调 (异步 Worker 注入)
    _progress_callback: Optional[callable]  # async def callback(step: str, progress: float)

    # 是否使用了分块处理
    is_chunked: bool

    # 是否被截断 (超长文本取样) — v3.4 废弃, 改用信号卡压缩替代暴力截断
    is_truncated: bool

    # === v3.4: 信号卡压缩 + 多模态上下文分块 ===
    # 信号卡列表 (替代暴力截断)
    _signal_cards: Optional[list]           # [TextSignalCard|VLSignalCard|AudioSignalCard, ...]

    # 多模态上下文分块
    _mmcc_chunks: Optional[list]            # [MultiModalContextChunk, ...]

    # 内容位置图
    _content_graph: Optional[dict]          # {positions: [...], total_text_length: N}

    # 说话人分段
    _speaker_segments: Optional[list]       # [{speaker_id, start_ms, end_ms, text}, ...]

    # 跨模态全局分析结果
    _cross_modal_analysis: Optional[dict]   # {findings, deep_dive_targets, ...}

    # 回溯深潜结果
    _deep_dive_results: Optional[list]      # [{target_id, violation_type, reasoning}, ...]

    # Scout 预扫风险热力图
    _scout_heatmap: Optional[list]          # [{pos_start, pos_end, risk}, ...]

    # 是否使用了信号卡压缩 (区别于暴力截断)
    compression_used: bool

    # v3.8: ReAct Plan-and-Execute 上下文
    _plan_context: Optional[dict]          # {plan_id, steps, current_step, completed_steps, step_results, replan_history, status}
    _task_plan: Optional[dict]             # 前端可展示的计划摘要

    # v4.0: Planner 是否已预处理标记 — 必须在此声明。
    # LangGraph StateGraph 仅传递 TypedDict 中声明的 key；未声明时 planner 设置的值
    # 会被丢弃，导致 file_agent_node 跳过检查失效、图片被重复处理 3 轮（见 task_2046b7d065524c53）。
    _planner_processed: bool

    # === v5.0: 分诊台 + 三车道 + 大脑（R6·E1/E2）===
    _tier: Optional[str]                   # triage 车道: low / med / high
    _triage: Optional[dict]                # {risk, complexity, pre_judgment, reason, cost_saved}
    _brain_decision: Optional[dict]        # 大脑仲裁决策: {decisions: [...], terminate_suggested, plan_summary}
    _termination: Optional[dict]           # R7·E3: 终止双签硬校验结果


def create_initial_state(
    content_id: str,
    content_type: str,
    content: dict,
    account_id: Optional[str] = None,
) -> ModerationState:
    """创建初始审核状态 (v3.0)"""
    return ModerationState(
        content_id=content_id,
        content_type=content_type,
        content=content,
        account_id=account_id,
        messages=[],
        text_result={},
        image_result={},
        audio_result={},
        video_result={},
        blackhat_result={},
        final_risk=None,
        final_decision="",
        # v3.0 默认值
        _is_multimodal=False,
        _debate_result={},
        _reflexion_result=None,
        _human_review={},   # v3.2: 初始化为空dict而非None, 避免.get()报错
        _rag_result=None,
        _graph_insights=None,
        _multimodal_rag_result=None,
        _react_result=None,
        start_time=0.0,
        # v3.3 默认值
        _chunk_results=None,
        _fusion_result=None,
        _multi_image_results=[],  # v3.3fix: 初始化为空列表而非 None, 避免 .append() 报错
        _progress_callback=None,
        is_chunked=False,
        is_truncated=False,
        # v3.4 默认值
        _signal_cards=None,
        _mmcc_chunks=None,
        _content_graph=None,
        _speaker_segments=None,
        _cross_modal_analysis=None,
        _deep_dive_results=None,
        _scout_heatmap=None,
        compression_used=False,
        # v3.8: ReAct Plan-and-Execute
        _plan_context=None,
        _task_plan=None,
        # v5.0: 分诊台 + 三车道 + 大脑
        _tier=None,
        _triage=None,
        _brain_decision=None,
        _termination=None,
    )
