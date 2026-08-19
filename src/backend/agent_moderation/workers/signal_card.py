"""
信号卡压缩引擎 v3.4 — 替代暴力截断的 LLM 驱动压缩

核心理念:
  超长文本不截断/不采样, 而是逐块压缩为结构化"信号卡",
  保留语义信息而非丢弃文本。

信号卡类型:
  - TextSignalCard: 文本块的压缩表示
  - VLSignalCard: 图片+上下文的联合分析
  - AudioSignalCard: 音频转义文本+说话人信息

处理策略:
  - 短文本 (<3000): 不分块, 不做信号卡, 直接 LLM
  - 中文档 (3000-15000): 并行分块, 每块 TextAgent 直接处理
  - 长文档 (15000-80000): 信号卡压缩 → 全局分析 → 按需深潜
  - 超长文档 (>80000): Scout预扫 + 信号卡压缩 + 分级深潜
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from common.api_clients import get_deepseek_client, get_deepseek_model

logger = logging.getLogger(__name__)

# ============================================================
# 数据结构
# ============================================================

@dataclass
class TextSignalCard:
    """文本块压缩后的信号卡"""
    chunk_index: int
    char_start: int
    char_end: int
    text_length: int

    # 压缩后的语义信息
    summary: str = ""                          # 2-3句内容摘要
    risk_signals: list = field(default_factory=list)   # 风险信号: ["含暴力关键词", "诱导加微信"]
    suspicious_quotes: list = field(default_factory=list)  # 可疑原文引用 (保留证据!)
    entities: list = field(default_factory=list)      # 关键实体: 人名/组织/产品名
    topics: list = field(default_factory=list)        # 主题标签
    sentiment: str = "neutral"                       # positive/negative/neutral

    # 风险评估
    preliminary_risk: float = 0.0              # 0.0-1.0 预评估风险分
    needs_deep_dive: bool = False              # 是否需要回溯深潜

    # 多模态关联锚点
    anchored_image_ids: list = field(default_factory=list)
    anchored_audio_ids: list = field(default_factory=list)


@dataclass
class VLSignalCard:
    """图片+上下文联合分析信号卡"""
    image_id: str
    image_bytes_length: int

    # VL 分析结果
    image_description: str = ""                # 图片内容描述
    ocr_text: str = ""                         # 图片内 OCR 文字
    suspicious_elements: list = field(default_factory=list)  # [二维码, 联系方式, 水印]

    # 图文关系 (核心!)
    relation_to_text: str = "unknown"          # supplement / contradict / cipher / decoration / unknown
    relation_detail: str = ""                  # 关系详细说明

    # 联合风险
    joint_risk: float = 0.0                    # 图文联合风险分
    text_only_risk: float = 0.0                # 纯文本风险分 (来自同块 TextSignalCard)
    image_only_risk: float = 0.0               # 纯图片风险分

    needs_deep_dive: bool = False
    processing_level: int = 0                  # 1=跳过 2=OCR 3=VL完整


@dataclass
class AudioSignalCard:
    """音频转义文本信号卡"""
    audio_id: str
    audio_bytes_length: int

    # ASR 结果
    formatted_transcript: str = ""             # 带说话人标签的格式化文本
    raw_transcript: str = ""                   # 纯文本 (无标签)
    asr_confidence: float = 0.0

    # 说话人信息
    speaker_count: int = 0
    speaker_segments: list = field(default_factory=list)
    # [{speaker_id, start_ms, end_ms, text, asr_confidence, speaker_confidence}]

    # 音频质量
    has_background_noise: bool = False
    noise_segments: list = field(default_factory=list)

    # 风险信号
    risk_signals: list = field(default_factory=list)
    preliminary_risk: float = 0.0
    needs_deep_dive: bool = False

    # 说话人维度的风险归属
    speaker_attribution: dict = field(default_factory=dict)
    # {"说话人A": {"text_snippet": "...", "risk_score": 0.8, "violation_type": "advertisement"}}


# ============================================================
# 压缩引擎
# ============================================================

# 文本信号卡压缩 Prompt — 要求输出紧凑的结构化 JSON
TEXT_COMPRESSION_PROMPT = """你是内容安全审核的文本压缩专家。
请将以下文本块压缩为结构化信号卡，保留所有可能涉及违规的信息。

## 压缩要求
1. summary: 2-3句话概括文本内容，保留关键细节
2. risk_signals: 列出所有可疑信号（敏感词、诱导话术、异常模式等），即使不确定也要列出
3. suspicious_quotes: 摘录可能违规的原文句子（最多3句，每句不超过100字）
4. entities: 提取关键实体（人名、组织、产品、微信号/手机号/URL等）
5. topics: 1-3个主题标签
6. sentiment: 情感倾向 (positive/negative/neutral)
7. preliminary_risk: 预评估风险分 0.0-1.0
   - 0.0-0.2: 完全正常
   - 0.2-0.5: 有可疑但可能正常
   - 0.5-0.8: 疑似违规
   - 0.8-1.0: 明确违规
8. needs_deep_dive: 是否需要逐字深度审核 (true/false)

## 输出格式 (仅输出JSON, 不要其他内容)
{
  "summary": "...",
  "risk_signals": ["..."],
  "suspicious_quotes": ["..."],
  "entities": ["..."],
  "topics": ["..."],
  "sentiment": "neutral",
  "preliminary_risk": 0.0,
  "needs_deep_dive": false
}"""


class SignalCardCompressor:
    """LLM驱动的信号卡压缩器 — 替代暴力截断"""

    def __init__(self):
        self._llm_client = None

    @property
    def llm_client(self):
        if self._llm_client is None:
            self._llm_client = get_deepseek_client()
        return self._llm_client

    # ========== JSON 修复重试 ==========

    @staticmethod
    def _parse_json_with_repair(raw: str, chunk_index: int) -> dict:
        """
        解析 LLM 输出的 JSON, 失败时尝试修复常见问题:

        1. 未终止字符串 (补缺失的引号)
        2. 非法控制字符 (转义或移除)
        3. 非法转义序列 (如 \\s, \\d 等)
        4. 尾部截断 (补缺失的 })
        5. 空响应
        """
        import re as _re

        if not raw or not raw.strip():
            logger.warning(f"Chunk {chunk_index}: empty LLM response")
            return None

        raw = raw.strip()

        # 尝试 1: 直接解析
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.debug(f"Chunk {chunk_index}: direct JSON parse failed ({e.msg}), "
                        f"attempting repair...")

        # 尝试 2: 修复非法控制字符
        try:
            # 移除或转义 JSON 不允许的控制字符 (0x00-0x1f, 除了 \\t\\n\\r)
            cleaned = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 尝试 3: 修复非法转义序列 (LLM 有时输出 \\s, \\d 等非标准转义)
        try:
            # 将 \\X 替换为 X (用于非标准转义)
            fixed_escapes = _re.sub(r'\\(?!["\\/bfnrtu])', '', raw)
            return json.loads(fixed_escapes)
        except json.JSONDecodeError:
            pass

        # 尝试 4: 未终止字符串 — 找到最后一个完整键/值后截断重试
        try:
            # 补缺失的结尾引号和括号
            if raw.count('"') % 2 != 0:
                raw = raw.rstrip() + '"'
            # 补缺失的闭合括号
            open_braces = raw.count('{') - raw.count('}')
            open_brackets = raw.count('[') - raw.count(']')
            fixed = raw + ']' * open_brackets + '}' * open_braces
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # 尝试 5: 从文本中提取 JSON 结构 (摘取第一个 { 到最后一个 })
        try:
            start = raw.find('{')
            end = raw.rfind('}')
            if start >= 0 and end > start:
                extracted = raw[start:end + 1]
                return json.loads(extracted)
        except json.JSONDecodeError:
            pass

        # 尝试 6: 逐字段提取 (最后的手段)
        try:
            fields = {}
            patterns = {
                "summary": r'"summary"\s*:\s*"([^"]*)"',
                "preliminary_risk": r'"preliminary_risk"\s*:\s*([\d.]+)',
                "needs_deep_dive": r'"needs_deep_dive"\s*:\s*(true|false)',
            }
            for key, pattern in patterns.items():
                m = _re.search(pattern, raw, _re.IGNORECASE)
                if m:
                    if key == "preliminary_risk":
                        fields[key] = float(m.group(1))
                    elif key == "needs_deep_dive":
                        fields[key] = m.group(1).lower() == "true"
                    elif key == "summary":
                        fields[key] = m.group(1)

            # 尝试提取列表字段
            for list_key in ["risk_signals", "suspicious_quotes", "entities", "topics"]:
                m = _re.search(rf'"{list_key}"\s*:\s*\[(.*?)\]', raw, _re.DOTALL)
                if m:
                    items = _re.findall(r'"([^"]*)"', m.group(1))
                    fields[list_key] = items[:10]

            if "summary" in fields:
                logger.info(f"Chunk {chunk_index}: JSON repaired via field extraction "
                           f"(recovered {len(fields)} fields)")
                fields.setdefault("risk_signals", [])
                fields.setdefault("suspicious_quotes", [])
                fields.setdefault("entities", [])
                fields.setdefault("topics", [])
                fields.setdefault("sentiment", "neutral")
                fields.setdefault("preliminary_risk", 0.1)
                fields.setdefault("needs_deep_dive", False)
                return fields
        except Exception:
            pass

        logger.warning(f"Chunk {chunk_index}: all JSON repair attempts failed")
        return None

    # ========== 文本压缩 ==========

    async def compress_text_chunk(
        self, text: str, chunk_index: int,
        char_start: int = 0, char_end: int = 0,
    ) -> TextSignalCard:
        """
        将文本块压缩为 TextSignalCard

        一次 LLM 调用, 输出紧凑的结构化 JSON (~200 tokens 输出),
        比直接送原文给审核 (2000 tokens 输入 + 500 tokens 输出) 更省。
        """
        if not text or not text.strip():
            return TextSignalCard(
                chunk_index=chunk_index,
                char_start=char_start, char_end=char_end,
                text_length=len(text),
                summary="[空文本]",
            )

        text_len = len(text)

        try:
            t0 = time.time()
            response = await self.llm_client.chat.completions.create(
                model=get_deepseek_model(),
                messages=[{
                    "role": "user",
                    "content": f"{TEXT_COMPRESSION_PROMPT}\n\n## 待压缩文本 ({text_len} 字符)\n{text}",
                }],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=600,  # v3.4fix: 增大输出限制, 避免 JSON 被截断
            )
            raw = response.choices[0].message.content
            elapsed = (time.time() - t0) * 1000

            # 尝试解析 JSON, 失败则修复重试
            data = self._parse_json_with_repair(raw, chunk_index)
            if data is None:
                raise ValueError(f"JSON parse failed after repair: {raw[:100]}...")

            logger.debug(f"Text chunk {chunk_index} compressed in {elapsed:.0f}ms "
                        f"({text_len} chars → ~{len(raw)} chars)")

            return TextSignalCard(
                chunk_index=chunk_index,
                char_start=char_start,
                char_end=char_end,
                text_length=text_len,
                summary=data.get("summary", "")[:300],
                risk_signals=data.get("risk_signals", [])[:10],
                suspicious_quotes=data.get("suspicious_quotes", [])[:3],
                entities=data.get("entities", [])[:20],
                topics=data.get("topics", [])[:5],
                sentiment=data.get("sentiment", "neutral"),
                preliminary_risk=float(data.get("preliminary_risk", 0.0)),
                needs_deep_dive=bool(data.get("needs_deep_dive", False)),
            )

        except Exception as e:
            logger.warning(f"Text compression failed for chunk {chunk_index}: {e}")
            return TextSignalCard(
                chunk_index=chunk_index,
                char_start=char_start, char_end=char_end,
                text_length=text_len,
                summary=f"[压缩失败: {str(e)[:100]}]",
                preliminary_risk=0.1,
                needs_deep_dive=True,  # 压缩失败 → 标记深潜
            )

    # ========== 图片+上下文压缩 ==========

    async def compress_image_with_context(
        self, image_bytes: bytes, image_id: str,
        context_before: str = "", context_after: str = "",
        text_signal_summary: str = "",
    ) -> VLSignalCard:
        """
        VL模型分析图片 + 周围文本上下文 → VLSignalCard

        核心差异: VL 不仅看图片, 还接收周围文本作为上下文,
        从而判断图文关系 (补充/矛盾/暗语/无关)
        """
        # VL 分析由 ImageAgent 的 Qwen-VL 完成, 这里做结果包装
        # 实际 VL 调用在 multi_modal_coordinator 中通过 ImageAgent 执行
        return VLSignalCard(
            image_id=image_id,
            image_bytes_length=len(image_bytes),
        )

    # ========== 音频压缩 ==========

    async def compress_audio_transcript(
        self, transcript: str, audio_id: str,
        speaker_count: int = 0,
        speaker_segments: list = None,
    ) -> AudioSignalCard:
        """
        将音频转义文本压缩为 AudioSignalCard

        如果音频转义文本较短 (<500字), 直接保留全部。
        如果较长, 用文本压缩同样的方式处理。
        """
        card = AudioSignalCard(
            audio_id=audio_id,
            audio_bytes_length=0,
            formatted_transcript=transcript,
            raw_transcript=transcript,
            speaker_count=speaker_count,
            speaker_segments=speaker_segments or [],
        )

        if not transcript or not transcript.strip():
            return card

        # 短转义文本: 不做额外压缩
        if len(transcript) <= 500:
            card.asr_confidence = 0.95
            # 快速风险评估: 简单的敏感词检测在 AudioAgent 中做
            return card

        # 长转义文本: 用文本压缩同样的方式
        try:
            t0 = time.time()
            response = await self.llm_client.chat.completions.create(
                model=get_deepseek_model(),
                messages=[{
                    "role": "user",
                    "content": f"""{TEXT_COMPRESSION_PROMPT}

## 注意事项
这是一段{ '多人对话' if speaker_count > 1 else '单人讲话' }的语音转义文本。
请特别关注不同说话人的言论差异。

## 待压缩转义文本 ({len(transcript)} 字符)
{transcript}""",
                }],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=400,
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)
            elapsed = (time.time() - t0) * 1000

            card.risk_signals = data.get("risk_signals", [])[:10]
            card.preliminary_risk = float(data.get("preliminary_risk", 0.0))
            card.needs_deep_dive = bool(data.get("needs_deep_dive", False))

            logger.debug(f"Audio transcript compressed in {elapsed:.0f}ms")

        except Exception as e:
            logger.warning(f"Audio compression failed: {e}")
            card.needs_deep_dive = True

        return card

    # ========== 批量并行压缩 ==========

    async def compress_text_batch(
        self, chunks: list[dict],
        max_concurrent: int = 10,
    ) -> list[TextSignalCard]:
        """
        并行压缩多个文本块

        Args:
            chunks: [{"index": i, "text": "...", "char_start": 0, "char_end": 2000}, ...]
            max_concurrent: 最大并发数

        Returns:
            [TextSignalCard, ...]
        """
        if not chunks:
            return []

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _compress_one(chunk: dict) -> TextSignalCard:
            async with semaphore:
                return await self.compress_text_chunk(
                    text=chunk.get("text", ""),
                    chunk_index=chunk.get("index", 0),
                    char_start=chunk.get("char_start", 0),
                    char_end=chunk.get("char_end", 0),
                )

        tasks = [_compress_one(c) for c in chunks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        cards = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning(f"Batch compression failed for chunk {i}: {r}")
                cards.append(TextSignalCard(
                    chunk_index=i,
                    text_length=len(chunks[i].get("text", "")),
                    summary=f"[压缩异常: {r}]",
                    needs_deep_dive=True,
                ))
            else:
                cards.append(r)

        logger.info(f"Compressed {len(chunks)} text chunks → {len(cards)} signal cards "
                    f"({sum(1 for c in cards if c.needs_deep_dive)} need deep dive)")
        return cards


# ============================================================
# 信号卡合并 (用于全局分析输入)
# ============================================================

class SignalCardMerger:
    """信号卡合并 — 为跨模态全局分析准备输入"""

    @staticmethod
    def to_compact_text(cards: list, max_chars: int = 8000) -> str:
        """
        将所有信号卡合并为紧凑的文本表示, 供 LLM 全局分析

        优先级: 高风险信号 > 可疑引用 > 摘要
        """
        # 按风险分排序
        sorted_cards = sorted(cards, key=lambda c: c.preliminary_risk, reverse=True)

        sections = []
        total = 0

        for card in sorted_cards:
            if total >= max_chars:
                sections.append(f"\n[... 剩余 {len(cards) - len(sections)} 个低风险块已省略 ...]")
                break

            if isinstance(card, TextSignalCard):
                part = SignalCardMerger._format_text_card(card)
            elif isinstance(card, VLSignalCard):
                part = SignalCardMerger._format_vl_card(card)
            elif isinstance(card, AudioSignalCard):
                part = SignalCardMerger._format_audio_card(card)
            else:
                continue

            if total + len(part) > max_chars:
                remaining = max_chars - total - 100
                part = part[:remaining] + "\n[...]"

            sections.append(part)
            total += len(part)

        return "\n\n---\n\n".join(sections)

    @staticmethod
    def _format_text_card(card: TextSignalCard) -> str:
        lines = [
            f"## 文本块 #{card.chunk_index} (位置 {card.char_start}-{card.char_end})",
            f"风险: {card.preliminary_risk:.2f} | 情感: {card.sentiment}",
            f"摘要: {card.summary}",
        ]
        if card.risk_signals:
            lines.append(f"风险信号: {', '.join(card.risk_signals[:5])}")
        if card.suspicious_quotes:
            lines.append(f"可疑引用: {'; '.join(card.suspicious_quotes[:2])}")
        if card.entities:
            lines.append(f"实体: {', '.join(card.entities[:8])}")
        if card.anchored_image_ids:
            lines.append(f"关联图片: {', '.join(card.anchored_image_ids)}")
        if card.anchored_audio_ids:
            lines.append(f"关联音频: {', '.join(card.anchored_audio_ids)}")
        return "\n".join(lines)

    @staticmethod
    def _format_vl_card(card: VLSignalCard) -> str:
        lines = [
            f"## 图片 {card.image_id}",
            f"描述: {card.image_description[:200]}",
            f"OCR: {card.ocr_text[:150]}",
            f"图文关系: {card.relation_to_text}",
            f"联合风险: {card.joint_risk:.2f}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_audio_card(card: AudioSignalCard) -> str:
        lines = [
            f"## 音频 {card.audio_id}",
            f"说话人数: {card.speaker_count}",
            f"转义文本 ({len(card.formatted_transcript)} 字):",
            f"{card.formatted_transcript[:500]}",
        ]
        if card.risk_signals:
            lines.append(f"风险信号: {', '.join(card.risk_signals[:5])}")
        if card.has_background_noise:
            lines.append("⚠️ 含背景噪音, ASR置信度降低")
        return "\n".join(lines)

    @staticmethod
    def collect_deep_dive_targets(cards: list) -> list[int]:
        """收集需要回溯深潜的块索引"""
        targets = []
        for card in cards:
            if isinstance(card, TextSignalCard) and card.needs_deep_dive:
                targets.append(card.chunk_index)
            elif isinstance(card, VLSignalCard) and card.needs_deep_dive:
                targets.append(card.image_id)  # 返回 image_id 而非索引
            elif isinstance(card, AudioSignalCard) and card.needs_deep_dive:
                targets.append(card.audio_id)
        return targets


# 全局单例
_compressor: Optional[SignalCardCompressor] = None


def get_signal_card_compressor() -> SignalCardCompressor:
    global _compressor
    if _compressor is None:
        _compressor = SignalCardCompressor()
    return _compressor
