"""
多模态上下文分块构建器 v3.4 — MMCC Builder

功能:
  1. 构建 ContentGraph — 记录所有模态在全文中的位置
  2. 构建 MultiModalContextChunk — 统一的多模态分块
  3. 图片风险分级 — 决定处理深度 (跳过/OCR/VL)
  4. 音频转义文本插入 — 在内容流中正确定位

核心理念:
  不同模态不再独立处理, 而是通过"位置"自然关联。
  图片和音频落在哪个文本范围, 就和该范围的文本一起处理。
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from agent_moderation.workers.signal_card import (
    TextSignalCard, VLSignalCard, AudioSignalCard,
)

logger = logging.getLogger(__name__)

# ============================================================
# 数据结构
# ============================================================

@dataclass
class SpeakerTurn:
    """单次发言"""
    speaker_id: str          # "说话人A" / "说话人B"
    start_ms: int
    end_ms: int
    text: str
    asr_confidence: float = 1.0
    speaker_confidence: float = 1.0


@dataclass
class AnchoredImage:
    """锚定在文本中的图片"""
    image_id: str
    image_bytes: bytes
    char_position: int                # 图片在全文中的字符偏移
    context_before: str = ""          # 前500字上下文
    context_after: str = ""           # 后500字上下文
    text_signal_summary: str = ""     # 所在段落的信号卡摘要 (分块后填充)
    scout_risk: float = 0.0           # 图片风险预扫分
    processing_level: int = 1         # 1=跳过 2=OCR 3=VL完整分析
    filename: str = ""


@dataclass
class AnchoredAudioSegment:
    """锚定的音频片段 (含说话人标签)"""
    audio_id: str
    audio_bytes: bytes
    char_position: int                # 转义文本在全文中的偏移
    transcript: str = ""              # ASR转义文本(纯文本)
    formatted_transcript: str = ""    # 带说话人标签的格式化文本
    speaker_segments: list = field(default_factory=list)  # [SpeakerTurn, ...]
    context_before: str = ""
    context_after: str = ""
    asr_confidence: float = 0.0
    has_background_noise: bool = False
    speaker_count: int = 0


@dataclass
class MultiModalContextChunk:
    """统一的多模态上下文分块"""
    chunk_id: str
    global_index: int

    # 文本
    text: str = ""                     # 该段的完整文本 (不截断)
    text_char_range: tuple = (0, 0)    # 在全文中的位置

    # 锚定图片
    anchored_images: list = field(default_factory=list)   # [AnchoredImage, ...]

    # 锚定音频
    anchored_audio: list = field(default_factory=list)    # [AnchoredAudioSegment, ...]

    # 元数据
    scout_risk: float = 0.0            # Scout预扫风险分
    neighbor_ids: list = field(default_factory=list)      # 相邻块 ID (用于深潜时取上下文)

    # 压缩后的信号卡 (Phase 3 填充)
    text_signal_card: Optional[TextSignalCard] = None
    vl_signal_cards: list = field(default_factory=list)    # [VLSignalCard, ...]
    audio_signal_cards: list = field(default_factory=list) # [AudioSignalCard, ...]


@dataclass
class ContentGraph:
    """内容位置图 — 记录所有模态在全文中的位置"""
    total_text_length: int = 0
    positions: list = field(default_factory=list)
    # [{char_offset, type: "text"|"image"|"audio", id, data}, ...]

    def add_text(self, char_offset: int, length: int):
        self.positions.append({
            "char_offset": char_offset,
            "type": "text",
            "length": length,
        })

    def add_image(self, char_offset: int, image_id: str, image_bytes: bytes,
                  filename: str = ""):
        self.positions.append({
            "char_offset": char_offset,
            "type": "image",
            "id": image_id,
            "data": image_bytes,
            "filename": filename,
        })

    def add_audio(self, char_offset: int, audio_id: str, audio_bytes: bytes,
                  transcript: str = "", formatted_transcript: str = "",
                  speaker_segments: list = None):
        self.positions.append({
            "char_offset": char_offset,
            "type": "audio",
            "id": audio_id,
            "data": audio_bytes,
            "transcript": transcript,
            "formatted_transcript": formatted_transcript,
            "speaker_segments": speaker_segments or [],
        })


# ============================================================
# MMCC 构建器
# ============================================================

# 分块参数
CHUNK_SIZE = 2000           # 每块字符数
OVERLAP = 200               # 块间重叠字符数
CONTEXT_WINDOW = 500        # 图片/音频的上下文窗口大小


class MMCCBuilder:
    """多模态上下文分块构建器"""

    @staticmethod
    def build_content_graph(content: dict) -> ContentGraph:
        """
        构建内容位置图

        将用户提交的各种内容 (文本/图片/音频/文件) 统一到一个位置序列中。
        图片和音频被放置在文本流的特定位置, 从而实现自然关联。

        Args:
            content: {"text": "...", "files": [...], "image": bytes, "audio": bytes, ...}

        Returns:
            ContentGraph with all modalities positioned
        """
        graph = ContentGraph()
        current_pos = 0

        # 1. 直接文本
        user_text = content.get("text", "")
        if user_text:
            graph.add_text(current_pos, len(user_text))
            current_pos += len(user_text)

        # 2. 直接图片 (嵌入在文本末尾)
        for key in ["image", "image_data"]:
            img = content.get(key)
            if img and isinstance(img, bytes) and len(img) > 0:
                img_id = f"direct_img_{key}"
                graph.add_image(current_pos, img_id, img, filename=f"{key}.jpg")
                # 图片不占用文本位置

        # 3. 直接音频 (嵌入在文本末尾)
        for key in ["audio", "audio_data"]:
            aud = content.get(key)
            if aud and isinstance(aud, bytes) and len(aud) > 0:
                aud_id = f"direct_audio_{key}"
                # 音频的转义文本将在后续处理中添加
                graph.add_audio(current_pos, aud_id, aud)

        # 4. 文件列表
        files = content.get("files", [])
        for f in files:
            filename = f.get("filename", "unknown")
            file_bytes = f.get("content", b"")
            mime_type = f.get("mime_type", "")

            if mime_type and mime_type.startswith("image/"):
                img_id = f"file_img_{filename}"
                # v3.4: docx 嵌入图片使用精确定位
                img_pos = f.get("_char_position")
                if img_pos is not None and img_pos >= 0:
                    graph.add_image(img_pos, img_id, file_bytes, filename=filename)
                else:
                    # 直接上传的图片, 锚定在文本末尾
                    graph.add_image(current_pos, img_id, file_bytes, filename=filename)
            elif mime_type and mime_type.startswith("audio/"):
                aud_id = f"file_audio_{filename}"
                graph.add_audio(current_pos, aud_id, file_bytes)
            else:
                # 文档类型 — 解析后的文本会追加到 current_pos
                # FileAgent 解析后文本追加位置
                pass

        graph.total_text_length = current_pos
        logger.info(f"[MMCC] ContentGraph built: text_len={current_pos}, "
                    f"images={sum(1 for p in graph.positions if p['type']=='image')}, "
                    f"audio={sum(1 for p in graph.positions if p['type']=='audio')}")
        return graph

    @staticmethod
    def build_chunks(
        content: dict,
        content_graph: ContentGraph,
        scout_heatmap: list = None,
    ) -> list[MultiModalContextChunk]:
        """
        构建多模态上下文分块

        按照 ~2000 字窗口滑动, 重叠 200 字。
        每块收集范围内的所有图片和音频。

        Args:
            content: 原始内容 dict
            content_graph: 内容位置图
            scout_heatmap: Scout 预扫风险热力图 [{pos_start, pos_end, risk}, ...]

        Returns:
            [MultiModalContextChunk, ...]
        """
        full_text = content.get("text", "")
        text_len = len(full_text)

        # 无文本但有图片/音频的特殊处理
        if text_len == 0:
            return MMCCBuilder._build_no_text_chunks(content, content_graph)

        # 短文本: 单块, 包含所有图片和音频
        if text_len <= CHUNK_SIZE:
            chunk = MMCCBuilder._build_single_chunk(
                full_text, 0, text_len, content_graph, scout_heatmap or [], 0
            )
            return [chunk]

        # 长文本: 滑动窗口分块
        chunks = []
        pos = 0
        idx = 0
        neighbor_map = {}  # chunk_id → [neighbor_ids]

        while pos < text_len:
            end = min(pos + CHUNK_SIZE, text_len)

            # 在 chunk_size 范围内找最佳切分点 (段落/句子边界)
            if end < text_len:
                end = MMCCBuilder._find_split_point(full_text, pos, end)

            chunk = MMCCBuilder._build_single_chunk(
                full_text, pos, end, content_graph, scout_heatmap or [], idx
            )
            chunks.append(chunk)

            # 下一块起点 (减去重叠)
            next_pos = max(pos + 1, end - OVERLAP)
            if next_pos <= pos:  # 防止无限循环
                next_pos = end
            # v3.4fix: 最后一块已处理, 退出循环 (防止末尾微块)
            if end >= text_len:
                break
            pos = next_pos
            idx += 1

        # 填充邻居关系 (用于深潜时取上下文)
        for i, chunk in enumerate(chunks):
            neighbors = []
            if i > 0:
                neighbors.append(chunks[i - 1].chunk_id)
            if i < len(chunks) - 1:
                neighbors.append(chunks[i + 1].chunk_id)
            chunk.neighbor_ids = neighbors

        logger.info(f"[MMCC] Built {len(chunks)} chunks from {text_len} chars "
                    f"(avg {text_len//max(len(chunks),1)} chars/chunk)")

        return chunks

    @staticmethod
    def _build_single_chunk(
        text: str, start: int, end: int,
        content_graph: ContentGraph,
        scout_heatmap: list,
        index: int,
    ) -> MultiModalContextChunk:
        """构建单个 MMCC"""
        chunk_text = text[start:end].strip()
        chunk_id = f"chunk_{index}"

        # 收集范围内的图片
        anchored_images = []
        for pos in content_graph.positions:
            if pos["type"] != "image":
                continue
            img_offset = pos["char_offset"]
            # 图片在块范围内或接近块边界
            if start - CONTEXT_WINDOW <= img_offset <= end + CONTEXT_WINDOW:
                img = AnchoredImage(
                    image_id=pos.get("id", f"img_{index}"),
                    image_bytes=pos.get("data", b""),
                    char_position=img_offset,
                    context_before=text[max(0, img_offset - CONTEXT_WINDOW):img_offset],
                    context_after=text[img_offset:min(len(text), img_offset + CONTEXT_WINDOW)],
                    filename=pos.get("filename", ""),
                )
                # 图片风险分级
                img.processing_level = MMCCBuilder._classify_image_level(
                    img, scout_heatmap
                )
                anchored_images.append(img)

        # 收集范围内的音频
        anchored_audio = []
        for pos in content_graph.positions:
            if pos["type"] != "audio":
                continue
            aud_offset = pos["char_offset"]
            if start - CONTEXT_WINDOW <= aud_offset <= end + CONTEXT_WINDOW:
                aud = AnchoredAudioSegment(
                    audio_id=pos.get("id", f"audio_{index}"),
                    audio_bytes=pos.get("data", b""),
                    char_position=aud_offset,
                    transcript=pos.get("transcript", ""),
                    formatted_transcript=pos.get("formatted_transcript", ""),
                    speaker_segments=[
                        SpeakerTurn(**s) if isinstance(s, dict) else s
                        for s in pos.get("speaker_segments", [])
                    ],
                    context_before=text[max(0, aud_offset - CONTEXT_WINDOW):aud_offset],
                    context_after=text[aud_offset:min(len(text), aud_offset + CONTEXT_WINDOW)],
                    asr_confidence=pos.get("asr_confidence", 0.0),
                    speaker_count=pos.get("speaker_count", len(pos.get("speaker_segments", []))),
                )
                anchored_audio.append(aud)

        # Scout 风险分
        scout_risk = 0.0
        if scout_heatmap:
            for h in scout_heatmap:
                hs = h.get("pos_start", 0)
                he = h.get("pos_end", 0)
                if hs < end and he > start:  # 有重叠
                    scout_risk = max(scout_risk, h.get("risk", 0.0))

        return MultiModalContextChunk(
            chunk_id=chunk_id,
            global_index=index,
            text=chunk_text,
            text_char_range=(start, end),
            anchored_images=anchored_images,
            anchored_audio=anchored_audio,
            scout_risk=scout_risk,
        )

    @staticmethod
    def _build_no_text_chunks(
        content: dict, content_graph: ContentGraph
    ) -> list[MultiModalContextChunk]:
        """无文本但有图片/音频时的特殊处理"""
        chunk = MultiModalContextChunk(
            chunk_id="chunk_0",
            global_index=0,
            text="",
            text_char_range=(0, 0),
        )

        for pos in content_graph.positions:
            if pos["type"] == "image":
                chunk.anchored_images.append(AnchoredImage(
                    image_id=pos.get("id", "img_0"),
                    image_bytes=pos.get("data", b""),
                    char_position=0,
                    filename=pos.get("filename", ""),
                ))
            elif pos["type"] == "audio":
                chunk.anchored_audio.append(AnchoredAudioSegment(
                    audio_id=pos.get("id", "audio_0"),
                    audio_bytes=pos.get("data", b""),
                    char_position=0,
                    transcript=pos.get("transcript", ""),
                    formatted_transcript=pos.get("formatted_transcript", ""),
                ))

        return [chunk]

    @staticmethod
    def _classify_image_level(
        img: AnchoredImage, scout_heatmap: list
    ) -> int:
        """
        图片风险分级

        Level 3 (高风险): 周围文本命中敏感词 或 Scout 标记
        Level 2 (中风险): 周围文本有可疑信号
        Level 1 (低风险): 其余情况

        Returns:
            1 (跳过), 2 (OCR), 3 (VL完整分析)
        """
        # 检查周围文本是否在 Scout 热力图中
        context_risk = 0.0
        for h in (scout_heatmap or []):
            hs = h.get("pos_start", 0)
            he = h.get("pos_end", 0)
            if hs < img.char_position + CONTEXT_WINDOW and he > img.char_position - CONTEXT_WINDOW:
                context_risk = max(context_risk, h.get("risk", 0.0))

        if context_risk > 0.6:
            return 3  # 高风险 → VL 完整分析
        elif context_risk > 0.2:
            return 2  # 中风险 → OCR
        else:
            return 1  # 低风险 → 跳过

    @staticmethod
    def _find_split_point(text: str, pos: int, end: int) -> int:
        """
        找最佳切分点: 段落边界 > 句子边界 > 硬截断

        从 end 位置回溯最多 500 字符寻找自然边界。
        v3.4fix: 必须超过最小块大小才接受切分点, 避免产生微块。
        """
        import re
        MIN_ACCEPTABLE = 300  # 切分点必须离起点至少 300 字符

        search_start = max(pos, end - 500)
        segment = text[search_start:min(len(text), end + 100)]

        # 1. 段落边界 (\n\n 或 \n\s*\n)
        for pattern in [r'\n\s*\n', r'\n#{1,3}\s', r'\n---']:
            for m in re.finditer(pattern, segment):
                abs_pos = search_start + m.start()
                if pos + MIN_ACCEPTABLE < abs_pos <= end:
                    return abs_pos

        # 2. 句子边界 — 必须超过最小块大小
        for m in re.finditer(r'[。！？!?.\n]', segment):
            abs_pos = search_start + m.end()
            if pos + MIN_ACCEPTABLE < abs_pos <= end:
                return abs_pos

        return end

    @staticmethod
    def inject_audio_transcript(
        content: dict, content_graph: ContentGraph,
        audio_id: str, formatted_transcript: str,
        speaker_segments: list,
    ):
        """
        将音频转义文本注入内容流

        在 ContentGraph 中更新音频节点的转义文本,
        同时在 content["text"] 末尾追加转义文本 (供后续分块处理)。
        """
        # 更新 ContentGraph
        for pos in content_graph.positions:
            if pos["type"] == "audio" and pos.get("id") == audio_id:
                pos["transcript"] = formatted_transcript
                pos["formatted_transcript"] = formatted_transcript
                pos["speaker_segments"] = speaker_segments
                pos["speaker_count"] = len(set(
                    s.get("speaker_id", "unknown") for s in speaker_segments
                )) if speaker_segments else 0
                # 标记音频已处理
                pos["asr_confidence"] = 0.95  # 简化处理
                break

        # 追加转义文本到 content["text"]
        if formatted_transcript:
            existing_text = content.get("text", "")
            separator = "\n\n[语音转义文本]\n" if existing_text else ""
            content["text"] = existing_text + separator + formatted_transcript
            content_graph.total_text_length = len(content["text"])

        return content_graph


def get_mmcc_builder() -> MMCCBuilder:
    return MMCCBuilder()
