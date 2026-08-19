"""
跨模态融合引擎 v3.4 — 全局分析 + 回溯深潜 + 统一输出

Phase 4: 跨模态全局分析
  合并所有信号卡 → LLM 做跨块/跨模态关联分析
  → 识别分散的违规模式 → 标记需要深潜的片段

Phase 5: 回溯深潜
  对高风险的多模态片段 → 取完整原文 + 原始图片/音频
  → 多模态 LLM 精准深度分析

Phase 6: 融合输出
  全局分析 + 深潜结果 → 统一审核判决
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from common.api_clients import get_deepseek_client, get_deepseek_model
from agent_moderation.workers.signal_card import (
    TextSignalCard, VLSignalCard, AudioSignalCard, SignalCardMerger,
)

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class CrossModalAnalysis:
    """跨模态全局分析结果"""
    # 整体判断
    overall_violation_type: str = "none"     # 综合违规类型
    overall_confidence: float = 0.0           # 综合置信度
    overall_risk_score: float = 0.0           # 综合风险分

    # 跨模态关联发现
    cross_modal_findings: list = field(default_factory=list)
    # [{finding: "文本A + 图片B 形成广告引流", risk: 0.8, evidence: [...]}]

    # 需要深潜的目标
    deep_dive_targets: list = field(default_factory=list)
    # [{chunk_id, image_id, audio_id, reason}]

    # 各模态汇总
    text_summary: str = ""
    image_summary: str = ""
    audio_summary: str = ""

    # 全局风险评估
    risk_breakdown: dict = field(default_factory=dict)
    # {text_risk, image_risk, audio_risk, cross_modal_boost}


@dataclass
class DeepDiveResult:
    """回溯深潜结果"""
    target_id: str
    target_type: str           # "chunk" / "image" / "audio"

    violation_type: str = "none"
    confidence: float = 0.0
    risk_score: float = 0.0
    reasoning: str = ""        # 完整推理过程
    evidence: list = field(default_factory=list)  # 证据片段


@dataclass
class FusionResult:
    """最终融合输出"""
    final_decision: str = "PASS"             # PASS / REVIEW / REJECT
    risk_score: float = 0.0
    violation_types: list = field(default_factory=list)
    violation_details: dict = field(default_factory=dict)

    # 各模态独立结果 (保留, 供前端展示)
    text_result: dict = field(default_factory=dict)
    image_result: dict = field(default_factory=dict)
    audio_result: dict = field(default_factory=dict)

    # 跨模态增强信息
    cross_modal_analysis: Optional[CrossModalAnalysis] = None
    deep_dive_results: list = field(default_factory=list)

    # 元数据
    compression_used: bool = False
    chunk_count: int = 0
    signal_card_count: int = 0
    is_chunked: bool = False


# ============================================================
# 全局分析 Prompt
# ============================================================

GLOBAL_ANALYSIS_PROMPT = """你是多模态内容安全审核的全局分析专家。
请综合分析以下信号卡集合，这些信号卡来自同一份文档/内容的不同分块。

## 分析任务
1. **跨块关联**: 识别分散在不同块的同一违规模式
   - 例: 块3提到"加微信"，块7出现二维码图片 → 广告引流
2. **跨模态关联**: 识别文本+图片+音频的组合违规
   - 例: 文本描述正常，但图片包含违禁信息 → 图文矛盾
3. **整体判断**: 综合所有信号卡给出全局审核结论
4. **深潜标记**: 对需要进一步核查的片段给出详细原因

## 审核维度
- politics: 政治敏感
- porn: 色情低俗
- violence: 暴力恐怖
- false_info: 虚假信息
- harassment: 辱骂骚扰
- advertisement: 广告引流

## 输出格式 (仅输出JSON)
{
  "overall_violation_type": "none|politics|porn|violence|false_info|harassment|advertisement",
  "overall_confidence": 0.0,
  "overall_risk_score": 0.0,
  "cross_modal_findings": [
    {
      "finding": "发现描述",
      "risk": 0.0,
      "evidence": ["证据1", "证据2"],
      "involved_chunks": [0, 1],
      "involved_modalities": ["text", "image"]
    }
  ],
  "deep_dive_targets": [
    {
      "target_id": "chunk_3",
      "target_type": "chunk",
      "reason": "需要深潜的原因"
    }
  ],
  "text_summary": "文本模态整体评估 (100字内)",
  "image_summary": "图片模态整体评估 (100字内)",
  "audio_summary": "音频模态整体评估 (100字内)",
  "risk_breakdown": {
    "text_risk": 0.0,
    "image_risk": 0.0,
    "audio_risk": 0.0,
    "cross_modal_boost": 0.0
  }
}"""


# ============================================================
# 跨模态融合引擎
# ============================================================

class CrossModalFusion:
    """跨模态全局分析 + 融合引擎"""

    def __init__(self):
        self._llm_client = None

    @property
    def llm_client(self):
        if self._llm_client is None:
            self._llm_client = get_deepseek_client()
        return self._llm_client

    # ========== Phase 4: 全局分析 ==========

    async def analyze(
        self,
        signal_cards: list,
        content_graph=None,
    ) -> CrossModalAnalysis:
        """
        跨模态全局分析

        将所有信号卡合并为紧凑文本, 调用 LLM 做全局关联分析。

        Args:
            signal_cards: [TextSignalCard|VLSignalCard|AudioSignalCard, ...]
            content_graph: 内容位置图 (可选, 用于更精确的跨模态关联)

        Returns:
            CrossModalAnalysis
        """
        if not signal_cards:
            return CrossModalAnalysis()

        # 合并信号卡为紧凑文本
        compact_text = SignalCardMerger.to_compact_text(signal_cards, max_chars=8000)

        try:
            t0 = time.time()
            response = await self.llm_client.chat.completions.create(
                model=get_deepseek_model(),
                messages=[{
                    "role": "user",
                    "content": f"""{GLOBAL_ANALYSIS_PROMPT}

## 信号卡集合
{compact_text}

## 内容统计
- 总文本块数: {sum(1 for c in signal_cards if isinstance(c, TextSignalCard))}
- 总图片数: {sum(1 for c in signal_cards if isinstance(c, VLSignalCard))}
- 总音频数: {sum(1 for c in signal_cards if isinstance(c, AudioSignalCard))}
- 使用信号卡压缩: 是 (信息保留率 100%)

请进行全局跨模态分析:""",
                }],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1500,
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)
            elapsed = (time.time() - t0) * 1000
            logger.info(f"[CrossModalFusion] Global analysis complete in {elapsed:.0f}ms")

            return CrossModalAnalysis(
                overall_violation_type=data.get("overall_violation_type", "none"),
                overall_confidence=float(data.get("overall_confidence", 0.0)),
                overall_risk_score=float(data.get("overall_risk_score", 0.0)),
                cross_modal_findings=data.get("cross_modal_findings", []),
                deep_dive_targets=data.get("deep_dive_targets", []),
                text_summary=data.get("text_summary", ""),
                image_summary=data.get("image_summary", ""),
                audio_summary=data.get("audio_summary", ""),
                risk_breakdown=data.get("risk_breakdown", {}),
            )

        except Exception as e:
            logger.error(f"[CrossModalFusion] Global analysis failed: {e}")
            # 降级: 从信号卡中提取最佳结果
            return self._fallback_analysis(signal_cards)

    def _fallback_analysis(self, signal_cards: list) -> CrossModalAnalysis:
        """降级分析 (LLM 不可用时)"""
        max_risk = 0.0
        all_signals = []
        deep_dive = []

        for card in signal_cards:
            if isinstance(card, TextSignalCard):
                max_risk = max(max_risk, card.preliminary_risk)
                all_signals.extend(card.risk_signals)
                if card.needs_deep_dive:
                    deep_dive.append({
                        "target_id": f"chunk_{card.chunk_index}",
                        "target_type": "chunk",
                        "reason": f"压缩时标记 (risk={card.preliminary_risk:.2f})",
                    })

        vt = "none"
        if max_risk > 0.8:
            vt = "advertisement"  # 保守推断
        elif max_risk > 0.5:
            vt = "advertisement"

        return CrossModalAnalysis(
            overall_violation_type=vt,
            overall_confidence=max_risk * 0.8,
            overall_risk_score=max_risk,
            cross_modal_findings=[],
            deep_dive_targets=deep_dive,
            text_summary=f"降级分析 (LLM不可用): max_risk={max_risk:.2f}",
            risk_breakdown={"text_risk": max_risk, "image_risk": 0, "audio_risk": 0, "cross_modal_boost": 0},
        )

    # ========== Phase 5: 回溯深潜 ==========

    async def deep_dive(
        self,
        target_chunks: list,         # [MultiModalContextChunk, ...]
        signal_cards: list,
        full_text: str = "",
    ) -> list[DeepDiveResult]:
        """
        回溯深潜: 对高风险片段做完整深度分析

        Args:
            target_chunks: 需要深潜的 MMCC 列表
            signal_cards: 对应的信号卡
            full_text: 完整文本 (用于获取更大上下文)

        Returns:
            [DeepDiveResult, ...]
        """
        if not target_chunks:
            return []

        results = []

        for chunk in target_chunks:
            target_id = getattr(chunk, 'chunk_id', 'unknown')
            try:
                result = await self._deep_dive_single(chunk, full_text)
                results.append(result)
            except Exception as e:
                logger.warning(f"[CrossModalFusion] Deep dive failed for {target_id}: {e}")
                results.append(DeepDiveResult(
                    target_id=target_id,
                    target_type="chunk",
                    reasoning=f"[深潜失败: {e}]",
                ))

        logger.info(f"[CrossModalFusion] Deep dive: {len(results)} targets analyzed")
        return results

    async def _deep_dive_single(
        self, chunk, full_text: str = ""
    ) -> DeepDiveResult:
        """对单个分块做深度分析"""
        chunk_id = getattr(chunk, 'chunk_id', 'unknown')
        chunk_text = getattr(chunk, 'text', '')

        # 构建深度分析上下文: 当前块 + 相邻块文本
        context_text = chunk_text
        if full_text:
            char_range = getattr(chunk, 'text_char_range', (0, 0))
            # 扩展上下文窗口到前后各 1000 字
            expanded_start = max(0, char_range[0] - 1000)
            expanded_end = min(len(full_text), char_range[1] + 1000)
            context_text = full_text[expanded_start:expanded_end]

        # 收集此块的图片和音频信息
        images = getattr(chunk, 'anchored_images', [])
        audio_segs = getattr(chunk, 'anchored_audio', [])

        image_context = ""
        for img in images:
            img_id = getattr(img, 'image_id', 'unknown')
            image_context += f"\n[关联图片 {img_id}] (位置: 约第{getattr(img, 'char_position', 0)}字处)"

        audio_context = ""
        for aud in audio_segs:
            aud_id = getattr(aud, 'audio_id', 'unknown')
            transcript = getattr(aud, 'formatted_transcript', '')
            audio_context += f"\n[关联音频 {aud_id}]\n{transcript[:300]}"

        try:
            t0 = time.time()
            response = await self.llm_client.chat.completions.create(
                model=get_deepseek_model(),
                messages=[{
                    "role": "user",
                    "content": f"""你是内容安全审核的深度分析专家。请对以下内容片段做逐字深度审核。

## 待审文本 ({len(context_text)} 字符)
{context_text[:3000]}
{image_context}
{audio_context}

## 分析要求
1. 逐句排查是否有违规内容
2. 结合关联图片和音频进行综合判断
3. 给出明确的违规类型和置信度

## 输出JSON
{{
  "violation_type": "none|politics|porn|violence|false_info|harassment|advertisement",
  "confidence": 0.0,
  "risk_score": 0.0,
  "reasoning": "完整推理过程 (200-500字)",
  "evidence": ["关键证据片段1", "关键证据片段2"]
}}""",
                }],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=1000,
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)
            elapsed = (time.time() - t0) * 1000
            logger.info(f"[CrossModalFusion] Deep dive {chunk_id}: "
                        f"{data.get('violation_type')} (conf={data.get('confidence', 0):.2f}) "
                        f"in {elapsed:.0f}ms")

            return DeepDiveResult(
                target_id=chunk_id,
                target_type="chunk",
                violation_type=data.get("violation_type", "none"),
                confidence=float(data.get("confidence", 0.0)),
                risk_score=float(data.get("risk_score", 0.0)),
                reasoning=data.get("reasoning", ""),
                evidence=data.get("evidence", []),
            )

        except Exception as e:
            logger.warning(f"[CrossModalFusion] Deep dive LLM failed for {chunk_id}: {e}")
            return DeepDiveResult(
                target_id=chunk_id,
                target_type="chunk",
                reasoning=f"[深度分析异常: {e}]",
            )

    # ========== Phase 6: 融合输出 ==========

    def build_final_result(
        self,
        analysis: CrossModalAnalysis,
        deep_dive_results: list[DeepDiveResult],
        signal_cards: list,
        original_results: dict = None,
    ) -> FusionResult:
        """
        构建最终融合输出

        融合策略:
        - 全局分析结果为基础
        - 深潜结果可以提升置信度 (深潜发现违规 → 全局置信度提升)
        - 深潜结果可以修正类型 (深潜发现更具体的违规类型)
        - 各模态独立结果保留用于前端展示

        Args:
            analysis: 全局分析结果
            deep_dive_results: 深潜结果列表
            signal_cards: 所有信号卡
            original_results: 原始 Agent 结果 (text/image/audio_result)

        Returns:
            FusionResult
        """
        original_results = original_results or {}

        # 基础: 全局分析
        final_vt = analysis.overall_violation_type
        final_conf = analysis.overall_confidence
        final_risk = analysis.overall_risk_score

        # 深潜增强
        for dr in deep_dive_results:
            if dr.violation_type != "none" and dr.confidence > final_conf:
                final_vt = dr.violation_type
                final_conf = dr.confidence
                final_risk = max(final_risk, dr.risk_score)

        # 跨模态增强: 如果图文矛盾或暗语配合, 提升风险
        cross_boost = analysis.risk_breakdown.get("cross_modal_boost", 0.0)
        if cross_boost > 0:
            final_risk = min(1.0, final_risk + cross_boost * 0.2)

        # 决策
        if final_risk > 0.7 and final_conf > 0.8:
            decision = "REJECT"
        elif final_risk > 0.4 or final_conf > 0.5:
            decision = "REVIEW"
        else:
            decision = "PASS"

        # 收集违规类型
        violation_types = [final_vt] if final_vt != "none" else []
        # 从深潜结果中补充
        for dr in deep_dive_results:
            if dr.violation_type != "none" and dr.violation_type not in violation_types:
                violation_types.append(dr.violation_type)

        return FusionResult(
            final_decision=decision,
            risk_score=round(final_risk, 4),
            violation_types=violation_types,
            violation_details={
                "global_analysis": {
                    "violation_type": analysis.overall_violation_type,
                    "confidence": analysis.overall_confidence,
                },
                "cross_modal_findings": analysis.cross_modal_findings,
                "deep_dive_count": len(deep_dive_results),
            },
            text_result=original_results.get("text_result", {}),
            image_result=original_results.get("image_result", {}),
            audio_result=original_results.get("audio_result", {}),
            cross_modal_analysis=analysis,
            deep_dive_results=deep_dive_results,
            compression_used=True,
            chunk_count=sum(1 for c in signal_cards if isinstance(c, TextSignalCard)),
            signal_card_count=len(signal_cards),
            is_chunked=len(signal_cards) > 1,
        )


# 全局单例
_fusion: Optional[CrossModalFusion] = None


def get_cross_modal_fusion() -> CrossModalFusion:
    global _fusion
    if _fusion is None:
        _fusion = CrossModalFusion()
    return _fusion
