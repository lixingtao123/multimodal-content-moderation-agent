"""
多模态并行协调器 v3.4 — 6阶段统一管线

v3.4 全面重构:
  Phase 0: 统一解析 + 位置锚定
  Phase 1: Scout 预扫 (AC自动机 + 哈希比对)
  Phase 2: MMCC 多模态分块构建
  Phase 3: 并行信号卡压缩 (替代暴力截断)
  Phase 4: 跨模态全局分析
  Phase 5: 回溯深潜 (高风险片段)
  Phase 6: 融合输出

传统路径 (短文本/简单场景): 保持原有并行 Agent 逻辑不变
"""
import asyncio
import logging
from typing import Optional

from agent_moderation.state import ModerationState

logger = logging.getLogger(__name__)

# v3.4: 导入新组件
from agent_moderation.workers.chunking import TextChunker, ChunkResultMerger, \
    CHUNK_THRESHOLD, CHUNK_THRESHOLD_LONG, CHUNK_THRESHOLD_EXTREME
from agent_moderation.workers.signal_card import get_signal_card_compressor, SignalCardMerger
from agent_moderation.workers.mmcc_builder import get_mmcc_builder
from agent_moderation.workers.cross_modal_fusion import get_cross_modal_fusion


class MultiModalCoordinator:
    """多模态并行协调器"""

    def __init__(self):
        self._text_agent = None
        self._image_agent = None
        self._audio_agent = None
        self._file_agent = None

    @property
    def text_agent(self):
        if self._text_agent is None:
            from agent_moderation.agents.text_agent import TextAgent
            self._text_agent = TextAgent()
        return self._text_agent

    @property
    def image_agent(self):
        if self._image_agent is None:
            from agent_moderation.agents.image_agent import ImageAgent
            self._image_agent = ImageAgent()
        return self._image_agent

    @property
    def audio_agent(self):
        if self._audio_agent is None:
            from agent_moderation.agents.audio_agent import AudioAgent
            self._audio_agent = AudioAgent()
        return self._audio_agent

    @property
    def file_agent(self):
        if self._file_agent is None:
            from agent_moderation.agents.file_agent import FileAgent
            self._file_agent = FileAgent()
        return self._file_agent

    async def coordinate(self, state: ModerationState,
                         progress_callback: Optional[callable] = None) -> ModerationState:
        """
        v3.4: 6阶段多模态协调管线

        - 短文本/简单场景: 保持原有并行 Agent 逻辑 (快速路径)
        - 长文本/多模态: 走完整 6 阶段管线 (信号卡压缩)
        """
        content = state.get("content", {})
        content_type = state.get("content_type", "text")
        content_id = state.get("content_id", "unknown")
        text = content.get("text", "")
        text_len = len(text)

        # ===== 快速路径: 短文本 + 无多模态混合 → 保持原逻辑 =====
        if text_len <= CHUNK_THRESHOLD_LONG and not content.get("files"):
            return await self._fast_path(state, progress_callback)

        # ===== 完整管线: 长文本或多模态混合 =====
        logger.info(f"[MultiModal v3.4] {content_id}: text_len={text_len}, "
                    f"using {'compression' if text_len > CHUNK_THRESHOLD_LONG else 'standard'} pipeline")

        # Phase 0: 统一解析 + 位置锚定
        if progress_callback:
            await progress_callback("phase0_parse", 0.05)

        content_graph = get_mmcc_builder().build_content_graph(content)
        state["_content_graph"] = {
            "positions": content_graph.positions,
            "total_text_length": content_graph.total_text_length,
        }

        # Phase 1: Scout 预扫 (仅极端长文本)
        scout_heatmap = []
        if text_len > CHUNK_THRESHOLD_EXTREME:
            if progress_callback:
                await progress_callback("phase1_scout", 0.08)
            scout_heatmap = await self._scout_scan(text)
            state["_scout_heatmap"] = scout_heatmap

        # Phase 2: MMCC 构建
        if progress_callback:
            await progress_callback("phase2_mmcc", 0.1)

        chunks = get_mmcc_builder().build_chunks(content, content_graph, scout_heatmap)
        state["_mmcc_chunks"] = [
            {
                "chunk_id": c.chunk_id,
                "global_index": c.global_index,
                "text_length": len(c.text),
                "image_count": len(c.anchored_images),
                "audio_count": len(c.anchored_audio),
                "scout_risk": c.scout_risk,
            }
            for c in chunks
        ]

        # Phase 3: 信号卡压缩 (替代暴力截断!)
        if progress_callback:
            await progress_callback("phase3_compress", 0.15)

        use_compression = text_len > CHUNK_THRESHOLD_LONG
        signal_cards = await self._phase3_compress(chunks, use_compression, progress_callback)
        state["_signal_cards"] = signal_cards

        # Phase 4: 跨模态全局分析
        if progress_callback:
            await progress_callback("phase4_global", 0.5)

        fusion = get_cross_modal_fusion()
        analysis = await fusion.analyze(signal_cards, content_graph)
        state["_cross_modal_analysis"] = {
            "overall_violation_type": analysis.overall_violation_type,
            "overall_confidence": analysis.overall_confidence,
            "overall_risk_score": analysis.overall_risk_score,
            "cross_modal_findings": analysis.cross_modal_findings,
            "deep_dive_count": len(analysis.deep_dive_targets),
            "risk_breakdown": analysis.risk_breakdown,
        }

        # Phase 5: 回溯深潜
        deep_dive_results = []
        if analysis.deep_dive_targets:
            if progress_callback:
                await progress_callback("phase5_deepdive", 0.7)

            target_chunks = [
                c for c in chunks
                if any(
                    t.get("target_id") == c.chunk_id
                    for t in analysis.deep_dive_targets
                )
            ]
            if target_chunks:
                deep_dive_results = await fusion.deep_dive(
                    target_chunks, signal_cards, text
                )
                state["_deep_dive_results"] = [
                    {
                        "target_id": dr.target_id,
                        "violation_type": dr.violation_type,
                        "confidence": dr.confidence,
                        "reasoning": dr.reasoning[:300],
                    }
                    for dr in deep_dive_results
                ]

        # Phase 6: 融合输出
        if progress_callback:
            await progress_callback("phase6_fusion", 0.85)

        # 提取各模态的原始结果 (保留兼容性)
        text_results = {}
        image_results = {}
        for card in signal_cards:
            if hasattr(card, 'preliminary_risk'):
                text_results[f"chunk_{card.chunk_index}"] = {
                    "risk": card.preliminary_risk,
                    "signals": card.risk_signals if hasattr(card, 'risk_signals') else [],
                    "needs_deep_dive": card.needs_deep_dive if hasattr(card, 'needs_deep_dive') else False,
                }

        final_result = fusion.build_final_result(
            analysis=analysis,
            deep_dive_results=deep_dive_results,
            signal_cards=signal_cards,
            original_results={
                "text_result": {"chunk_results": text_results, "is_chunked": True},
                "image_result": state.get("image_result", {}),
                "audio_result": state.get("audio_result", {}),
            },
        )

        # 写入 state (保持与原有接口的兼容性)
        state["text_result"] = final_result.text_result
        state["image_result"] = final_result.image_result
        state["audio_result"] = final_result.audio_result
        state["final_risk"] = {
            "overall_score": final_result.risk_score,
            "violation_types": final_result.violation_types,
            "violation_details": final_result.violation_details,
        }
        state["final_decision"] = final_result.final_decision
        state["is_chunked"] = final_result.is_chunked
        state["compression_used"] = final_result.compression_used

        state["_fusion_result"] = {
            "modalities_analyzed": list(set(
                t["type"] for t in content_graph.positions
            )) if content_graph.positions else ["text"],
            "text_chunked": len(chunks) > 1,
            "image_count": sum(1 for c in chunks for _ in c.anchored_images),
            "file_count": len(content.get("files", [])),
            "is_truncated": False,  # v3.4: 不再截断
            "compression_used": use_compression,
            "signal_card_count": len(signal_cards),
            "deep_dive_count": len(deep_dive_results),
        }

        if progress_callback:
            await progress_callback("coordinator_done", 0.95)

        logger.info(f"[MultiModal v3.4] {content_id} complete: "
                    f"chunks={len(chunks)}, cards={len(signal_cards)}, "
                    f"deep_dives={len(deep_dive_results)}, "
                    f"decision={final_result.final_decision} (risk={final_result.risk_score:.2f})")

        return state

    # ========== 快速路径 (向后兼容) ==========

    async def _fast_path(self, state: ModerationState,
                         progress_callback: Optional[callable] = None) -> ModerationState:
        """快速路径: 短文本/简单场景, 保持原有并行 Agent 逻辑"""
        content = state.get("content", {})
        content_type = state.get("content_type", "text")
        content_id = state.get("content_id", "unknown")

        plan = self._analyze_content(content, content_type)
        logger.info(f"[MultiModal FastPath] {content_id}: plan={plan['modalities']}")

        # 并行执行 (与 v3.3 逻辑一致)
        tasks = []
        task_labels = []

        if plan.get("has_text"):
            tasks.append(self._run_text_agent(state, plan, progress_callback))
            task_labels.append("text")

        for i, img_data in enumerate(plan.get("images", [])):
            tasks.append(self._run_image_agent(state, img_data, i))
            task_labels.append(f"image_{i}")

        if plan.get("has_audio"):
            tasks.append(self._run_audio_agent(state, plan))
            task_labels.append("audio")

        if plan.get("has_files"):
            tasks.append(self._run_file_agent(state, plan))
            task_labels.append("file")

        if tasks:
            if progress_callback:
                await progress_callback("multi_modal_coordinate", 0.1)
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for label, result in zip(task_labels, results):
                if isinstance(result, Exception):
                    logger.warning(f"[MultiModal] {label} agent failed: {result}")
                elif isinstance(result, dict):
                    if label == "text":
                        state["text_result"] = result
                    elif label.startswith("image_"):
                        existing = state.get("image_result") or {}
                        if not existing or existing.get("risk_score", 0) < result.get("risk_score", 0):
                            state["image_result"] = result
                        multi_img = state.get("_multi_image_results") or []
                        multi_img.append(result)
                        state["_multi_image_results"] = multi_img
                    elif label == "audio":
                        state["audio_result"] = result
                    elif label == "file":
                        state["file_results"] = result.get("file_results")
                        if result.get("content", {}).get("text"):
                            state["content"]["text"] = result["content"]["text"]

        state["_fusion_result"] = {
            "modalities_analyzed": plan["modalities"],
            "text_chunked": plan.get("needs_chunking", False),
            "image_count": plan.get("image_count", 0),
            "file_count": plan.get("file_count", 0),
            "is_truncated": False,
            "compression_used": False,
        }

        return state

    # ========== Phase 1: Scout 预扫 ==========

    async def _scout_scan(self, text: str) -> list[dict]:
        """
        Scout 预扫: AC自动机全文扫描 → 风险热力图

        纯本地, 毫秒级。用于极端长文本 (>80000字)。
        """
        heatmap = []
        if not text:
            return heatmap

        try:
            from mcp_servers.registry import get_tool_registry
            keyword_tool = get_tool_registry().get_keyword_check()

            # 按 2000 字分段扫描 (避免大文本阻塞)
            segment_size = 2000
            for pos in range(0, len(text), segment_size):
                segment = text[pos:pos + segment_size]
                result = await keyword_tool.execute(segment)
                if result.has_violation:
                    heatmap.append({
                        "pos_start": pos,
                        "pos_end": min(pos + segment_size, len(text)),
                        "risk": min(result.count / 10.0, 1.0),
                        "keywords": [m.get("keyword", "") for m in result.matches[:5]],
                    })

            if heatmap:
                logger.info(f"[Scout] {len(heatmap)} risky segments found in {len(text)} chars")

        except Exception as e:
            logger.warning(f"[Scout] scan failed (non-blocking): {e}")

        return heatmap

    # ========== Phase 3: 信号卡压缩 ==========

    async def _phase3_compress(
        self, chunks: list, use_compression: bool,
        progress_callback: Optional[callable] = None,
    ) -> list:
        """
        并行信号卡压缩

        - 如果 use_compression=True (长文本): 每块压缩为 TextSignalCard
        - 如果 use_compression=False (中文本): 每块直接 TextAgent 分析, 然后包装为信号卡
        """
        if not chunks:
            return []

        signal_cards = []

        if use_compression:
            # === 信号卡压缩路径 (长文本) ===
            compressor = get_signal_card_compressor()

            # 准备压缩输入
            compress_inputs = [
                {
                    "index": c.global_index,
                    "text": c.text,
                    "char_start": c.text_char_range[0] if c.text_char_range else 0,
                    "char_end": c.text_char_range[1] if c.text_char_range else len(c.text),
                }
                for c in chunks
            ]

            # 并行压缩
            text_cards = await compressor.compress_text_batch(compress_inputs)

            # 填充多模态关联信息
            for i, card in enumerate(text_cards):
                if i < len(chunks):
                    chunk = chunks[i]
                    card.anchored_image_ids = [
                        img.image_id if hasattr(img, 'image_id') else str(img)
                        for img in chunk.anchored_images
                    ]
                    card.anchored_audio_ids = [
                        aud.audio_id if hasattr(aud, 'audio_id') else str(aud)
                        for aud in chunk.anchored_audio
                    ]

            signal_cards.extend(text_cards)

            if progress_callback:
                await progress_callback("phase3_compressed", 0.4)

        else:
            # === 传统路径 (中文本): 每块 TextAgent 直接分析 ===
            # 然后包装为简化信号卡 (用于后续跨模态分析)
            chunk_results = await asyncio.gather(
                *[self._run_text_agent_on_chunk(chunk, progress_callback)
                  for chunk in chunks],
                return_exceptions=True,
            )

            from agent_moderation.workers.signal_card import TextSignalCard

            for i, (chunk, result) in enumerate(zip(chunks, chunk_results)):
                if isinstance(result, Exception):
                    signal_cards.append(TextSignalCard(
                        chunk_index=i,
                        char_start=chunk.text_char_range[0] if chunk.text_char_range else 0,
                        char_end=chunk.text_char_range[1] if chunk.text_char_range else 0,
                        text_length=len(chunk.text),
                        summary=f"[分析失败: {result}]",
                        needs_deep_dive=True,
                    ))
                elif isinstance(result, dict):
                    signal_cards.append(TextSignalCard(
                        chunk_index=i,
                        char_start=chunk.text_char_range[0] if chunk.text_char_range else 0,
                        char_end=chunk.text_char_range[1] if chunk.text_char_range else 0,
                        text_length=len(chunk.text),
                        summary=result.get("reason", ""),
                        risk_signals=result.get("tags", []),
                        preliminary_risk=result.get("risk_score", 0.0),
                        needs_deep_dive=result.get("risk_score", 0.0) > 0.5,
                        anchored_image_ids=[
                            img.image_id if hasattr(img, 'image_id') else str(img)
                            for img in chunk.anchored_images
                        ],
                        anchored_audio_ids=[
                            aud.audio_id if hasattr(aud, 'audio_id') else str(aud)
                            for aud in chunk.anchored_audio
                        ],
                    ))
                else:
                    signal_cards.append(TextSignalCard(
                        chunk_index=i,
                        text_length=len(chunk.text),
                        summary="[无结果]",
                    ))

            if progress_callback:
                await progress_callback("phase3_analyzed", 0.4)

        return signal_cards

    async def _run_text_agent_on_chunk(
        self, chunk, progress_callback=None
    ) -> dict:
        """对单个 MMCC 执行文本审核 (用于传统路径)"""
        from agent_moderation.state import create_initial_state

        chunk_state = create_initial_state(
            content_id=f"chunk_{chunk.global_index}",
            content_type="text",
            content={"text": chunk.text},
        )
        result_state = await self.text_agent.process(chunk_state)
        return result_state.get("text_result", {})

    def _analyze_content(self, content: dict, content_type: str) -> dict:
        """分析内容, 决策需要哪些 Agent"""
        plan = {
            "modalities": [],
            "has_text": False,
            "has_image": False,
            "has_audio": False,
            "has_files": False,
            "images": [],
            "text_length": 0,
            "image_count": 0,
            "file_count": 0,
            "needs_chunking": False,
            "is_truncated": False,
        }

        # 直接文本
        text = content.get("text", "")
        if text and text.strip():
            plan["has_text"] = True
            plan["modalities"].append("text")
            plan["text_length"] = len(text)

            from agent_moderation.workers.chunking import TextChunker
            plan["needs_chunking"] = TextChunker.needs_chunking(text)

        # 直接图片
        for key in ["image", "image_data"]:
            img = content.get(key)
            if img and isinstance(img, bytes) and len(img) > 0:
                plan["has_image"] = True
                plan["images"].append({"data": img, "key": key})
                plan["image_count"] += 1

        # 直接音频
        for key in ["audio", "audio_data"]:
            aud = content.get(key)
            if aud and isinstance(aud, bytes) and len(aud) > 0:
                plan["has_audio"] = True
                plan["modalities"].append("audio")

        # 文件列表
        files = content.get("files", [])
        if files:
            plan["has_files"] = True
            plan["modalities"].append("file")
            plan["file_count"] = len(files)

            # 分析文件类型
            for f in files:
                mime = f.get("mime_type", "")
                filename = f.get("filename", "")
                if mime and mime.startswith("image/"):
                    plan["has_image"] = True
                    plan["images"].append({"data": f.get("content"), "key": f"file:{filename}"})
                    plan["image_count"] += 1
                elif filename.lower().endswith((".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg")):
                    plan["has_audio"] = True

        if plan["has_image"] and "image" not in plan["modalities"]:
            plan["modalities"].append("image")

        return plan

    async def _run_text_agent(self, state: ModerationState, plan: dict,
                              progress_callback: Optional[callable] = None) -> dict:
        """
        执行文本审核 (支持分块) — v3.4 更新

        短文本: 直接 TextAgent
        中文档: 分块并行 + ChunkResultMerger (传统路径)
        长文档: 分块 + 信号卡压缩 + 合并 (由 coordinate() 管线处理, 此处仅做分块)
        """
        text = state["content"].get("text", "")
        if not text or not text.strip():
            return {}

        if not TextChunker.needs_chunking(text):
            # 短文本: 直接分析
            result_state = await self.text_agent.process(state)
            if progress_callback:
                await progress_callback("text_agent", 0.5)
            return result_state.get("text_result", {})

        # 分块
        if progress_callback:
            await progress_callback("text_chunking", 0.15)

        chunks = TextChunker.chunk(text)
        logger.info(f"[MultiModal] Text chunked: {len(chunks)} chunks from {len(text)} chars, "
                    f"compression={'enabled' if len(text) > CHUNK_THRESHOLD_LONG else 'disabled'}")

        # v3.4: 如果走了压缩路径 (coordinate 中已处理), 返回压缩后的结果
        # 这里仅用于快速路径中的中文档场景
        if len(text) > CHUNK_THRESHOLD_LONG:
            # 长文档: 返回占位结果, 由 coordinate() 管线的信号卡压缩+全局分析填充
            return {
                "is_chunked": True,
                "chunk_count": len(chunks),
                "compression_used": True,
                "violation_type": "none",  # 将由全局分析填充
                "confidence": 0.0,
                "risk_score": 0.0,
                "reason": f"文本已分{len(chunks)}块, 使用信号卡压缩处理",
            }

        # 中文档: 传统并行分块路径
        chunk_states = []
        for chunk_meta in chunks:
            chunk_state = dict(state)
            chunk_state["content"] = {**state.get("content", {}), "text": chunk_meta["text"]}
            chunk_states.append(chunk_state)

        chunk_results = await asyncio.gather(
            *[self.text_agent.process(cs) for cs in chunk_states],
            return_exceptions=True,
        )

        per_chunk_results = []
        for i, cr in enumerate(chunk_results):
            if isinstance(cr, Exception):
                logger.warning(f"[MultiModal] Chunk {i} failed: {cr}")
                per_chunk_results.append({"error": str(cr), "risk_score": 0.0})
            elif isinstance(cr, dict):
                per_chunk_results.append(cr.get("text_result", {}))
            else:
                per_chunk_results.append({"error": "unknown", "risk_score": 0.0})

        merged = ChunkResultMerger.merge(per_chunk_results, chunks)

        if progress_callback:
            await progress_callback("text_merged", 0.5)

        return merged

    async def _run_image_agent(self, state: ModerationState, img_data: dict, idx: int) -> dict:
        """执行单张图片审核"""
        try:
            img_state = dict(state)
            img_state["content"] = {
                **state.get("content", {}),
                "image": img_data.get("data"),
            }
            result_state = await self.image_agent.process(img_state)
            return result_state.get("image_result", {})
        except Exception as e:
            logger.warning(f"[MultiModal] Image agent failed for image {idx}: {e}")
            return {"error": str(e), "risk_score": 0.0}

    async def _run_audio_agent(self, state: ModerationState, plan: dict) -> dict:
        """执行音频审核"""
        try:
            result_state = await self.audio_agent.process(state)
            return result_state.get("audio_result", {})
        except Exception as e:
            logger.warning(f"[MultiModal] Audio agent failed: {e}")
            return {"error": str(e), "risk_score": 0.0}

    async def _run_file_agent(self, state: ModerationState, plan: dict) -> dict:
        """执行文件解析"""
        try:
            result_state = await self.file_agent.process(state)
            return {
                "file_results": result_state.get("file_results", {}),
                "content": {
                    "text": result_state.get("content", {}).get("text", ""),
                }
            }
        except Exception as e:
            logger.warning(f"[MultiModal] File agent failed: {e}")
            return {"file_results": {"error": str(e)}, "content": {}}


# 全局单例
_coordinator: Optional[MultiModalCoordinator] = None


def get_multi_modal_coordinator() -> MultiModalCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = MultiModalCoordinator()
    return _coordinator
