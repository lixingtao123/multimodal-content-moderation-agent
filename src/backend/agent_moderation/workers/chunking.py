"""
文本智能分块引擎 v3.4 — 解决超长文档 LLM 上下文溢出

策略:
  - 短文本 (<3000 chars): 直接处理
  - 中文档 (3000-15000 chars): 边界感知分块 + 并行 LLM + 结果合并
  - 长文档 (15000-80000 chars): 信号卡压缩 + 全局分析 (由协调器处理)
  - 超长文档 (>80000 chars): Scout预扫 + 信号卡压缩 (由协调器处理)

v3.4 变更:
  - 删除 _sample_chunks() 取样模式 — 不再随机丢弃内容
  - 删除 MAX_CHUNKS 硬限制 — 所有分块都保留
  - 新增 CHUNK_THRESHOLD_LONG 阈值 — 超过此值走信号卡压缩路径
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 分块参数
CHUNK_SIZE = 2000              # 每块字符数 (中文约 500-800 tokens)
OVERLAP = 200                   # 块间重叠字符数 (避免边界截断)
CHUNK_THRESHOLD = 3000          # 超过此长度才分块
CHUNK_THRESHOLD_LONG = 15000    # v3.4: 超过此长度走信号卡压缩路径
CHUNK_THRESHOLD_EXTREME = 80000 # v3.4: 超过此长度启用 Scout 预扫


class TextChunker:
    """文本智能分块器"""

    @staticmethod
    def chunk(text: str, max_chunk_size: int = CHUNK_SIZE,
              overlap: int = OVERLAP) -> list[dict]:
        """
        将长文本切分为重叠块

        v3.4: 移除 max_chunks 参数和取样模式。
        所有分块都保留, 长文本由协调器通过信号卡压缩处理。

        切分优先级: 段落边界 > 句子边界 > 硬截断

        Returns:
            [{index, text, char_start, char_end, total_chunks, is_sampled}, ...]
            is_sampled 始终为 False (v3.4)
        """
        if not text or not text.strip():
            return [{"index": 0, "text": text or "", "char_start": 0,
                     "char_end": len(text or ""), "total_chunks": 1, "is_sampled": False}]

        text_len = len(text)

        # 短文本: 不分块
        if text_len <= CHUNK_THRESHOLD:
            return [{"index": 0, "text": text, "char_start": 0,
                     "char_end": text_len, "total_chunks": 1, "is_sampled": False}]

        # 分块 (段落边界优先) — 不再有数量上限
        chunks = TextChunker._split_by_boundary(text, max_chunk_size, overlap)

        # v3.4: 如果分块很多, 记录警告但保留所有块 (由协调器决定是否走压缩路径)
        if len(chunks) > 10:
            logger.info(f"Text chunked into {len(chunks)} blocks ({text_len} chars), "
                       f"will use signal card compression for efficiency")

        # 添加元数据
        result = []
        for i, chunk_text in enumerate(chunks):
            # 估算原始位置
            char_start = i * (max_chunk_size - overlap)
            char_end = min(char_start + len(chunk_text), text_len)
            result.append({
                "index": i,
                "text": chunk_text,
                "char_start": max(0, char_start),
                "char_end": char_end,
                "total_chunks": len(chunks),
                "is_sampled": False,  # v3.4: 永不为 True
            })

        return result

    @staticmethod
    def _split_by_boundary(text: str, chunk_size: int, overlap: int) -> list[str]:
        """按段落/句子边界分块 (v3.4: 加最小块大小限制)"""
        chunks = []
        pos = 0
        text_len = len(text)
        MIN_CHUNK = max(chunk_size // 4, 300)  # 最小块大小 (~500 chars 或 300)

        while pos < text_len:
            end = min(pos + chunk_size, text_len)
            remaining = text_len - pos

            # 剩余内容不足一个最小块 → 合并到前一块或作为最后一块
            if remaining < MIN_CHUNK:
                chunk_text = text[pos:].strip()
                if chunk_text:
                    if chunks and len(chunks[-1]) + len(chunk_text) < chunk_size + overlap:
                        chunks[-1] = chunks[-1] + "\n" + chunk_text
                    else:
                        chunks.append(chunk_text)
                break

            if end < text_len:
                # 在 chunk_size 范围内找最佳切分点
                # 优先级: 段落 > 句子 > 硬截断
                # v3.4fix: 只在 MIN_CHUNK 之后才接受切分点
                search_start = max(pos, end - 500)
                segment = text[search_start:end + 100]

                # 1. 找段落边界 (\n\n) — 必须超过最小块大小
                para_match = None
                for m in re.finditer(r'\n\s*\n', segment):
                    abs_pos = search_start + m.start()
                    if pos + MIN_CHUNK < abs_pos <= end:
                        para_match = abs_pos

                if para_match:
                    end = para_match
                else:
                    # 2. 找句子边界 (。！？! ? .) — 必须超过最小块大小
                    sentence_match = None
                    for m in re.finditer(r'[。！？!?.]\s*', segment):
                        abs_pos = search_start + m.end()
                        if pos + MIN_CHUNK < abs_pos <= end:
                            sentence_match = abs_pos
                    # 也找换行
                    if not sentence_match:
                        for m in re.finditer(r'\n', segment):
                            abs_pos = search_start + m.start()
                            if pos + MIN_CHUNK < abs_pos <= end:
                                sentence_match = abs_pos
                                break

                    if sentence_match:
                        end = sentence_match
                    # v3.4fix: 如果找不到满足最小块大小的边界, 使用硬截断

            chunk_text = text[pos:end].strip()
            if chunk_text:
                chunks.append(chunk_text)

            # 下一块起点 (减去重叠)
            next_pos = max(pos + 1, end - overlap)
            if next_pos <= pos:
                break
            if end >= text_len:
                break
            pos = next_pos

        return chunks

    @staticmethod
    def needs_chunking(text: str) -> bool:
        """判断文本是否需要分块"""
        return len(text) > CHUNK_THRESHOLD


class ChunkResultMerger:
    """分块结果合并器"""

    @staticmethod
    def merge(chunk_results: list[dict], chunk_metas: list[dict]) -> dict:
        """
        合并多个分块的审核结果

        合并策略:
          - violation_type: 取置信度最高的非 none 类型
          - risk_score: max(所有块) — 保守策略
          - confidence: 加权平均 (按块大小)
          - reasoning: 取 risk_score 最高的 3 块拼接
          - is_adversarial: OR 逻辑
          - keyword_matches: 合并去重
        """
        if not chunk_results:
            return {
                "violation_type": "none",
                "confidence": 0.0,
                "reason": "无有效分块结果",
                "reasoning": "[分块处理失败: 无结果]",
                "is_adversarial": False,
                "tags": [],
                "risk_score": 0.0,
                "chunk_count": 0,
                "is_chunked": True,
            }

        valid_results = [r for r in chunk_results if r and not r.get("error")]

        if not valid_results:
            return {
                "violation_type": "none",
                "confidence": 0.0,
                "reason": "所有分块处理失败",
                "reasoning": f"[分块处理失败: {len(chunk_results)}块全部出错]",
                "is_adversarial": False,
                "tags": [],
                "risk_score": 0.0,
                "chunk_count": len(chunk_results),
                "is_chunked": True,
            }

        # 1. 找最佳违规类型 (置信度最高的非 none)
        best_vt = "none"
        best_conf = 0.0
        all_types = set()
        all_tags = set()
        all_keywords = []
        has_adversarial = False
        max_risk = 0.0
        total_weight = 0.0
        weighted_conf = 0.0
        reasonings = []

        for i, r in enumerate(valid_results):
            vt = r.get("violation_type", "none")
            conf = r.get("confidence", 0.0)
            risk = r.get("risk_score", 0.0)
            text_len = len(chunk_metas[i]["text"]) if i < len(chunk_metas) else CHUNK_SIZE

            if vt != "none":
                all_types.add(vt)
                if conf > best_conf:
                    best_conf = conf
                    best_vt = vt

            max_risk = max(max_risk, risk)
            weighted_conf += conf * text_len
            total_weight += text_len

            if r.get("is_adversarial"):
                has_adversarial = True

            for tag in r.get("tags", []):
                all_tags.add(tag)

            for kw in r.get("keyword_matches", []):
                if isinstance(kw, dict):
                    all_keywords.append(kw.get("keyword", str(kw)))
                else:
                    all_keywords.append(str(kw))

            # 收集推理 (按 risk_score 排序)
            reasoning = r.get("reasoning", "")
            if reasoning:
                reasonings.append((risk, i, reasoning))

        # 2. 加权平均置信度
        avg_conf = weighted_conf / total_weight if total_weight > 0 else best_conf

        # 3. 合并推理 (top-3 最高风险)
        reasonings.sort(key=lambda x: x[0], reverse=True)
        merged_reasoning_parts = []
        for rank, (risk, idx, reasoning) in enumerate(reasonings[:3]):
            chunk_label = f"分块{idx+1}/{len(chunk_results)}"
            merged_reasoning_parts.append(f"[{chunk_label} risk={risk:.2f}]\n{reasoning[:500]}")

        merged_reasoning = "\n\n---\n\n".join(merged_reasoning_parts)

        # v3.4: 分块标注 (无取样信息)
        if len(chunk_results) > 10:
            merged_reasoning = (
                f"[文本共{len(chunk_results)}块 ({sum(len(c['text']) for c in chunk_metas)}字符), "
                f"使用信号卡压缩保证信息完整]\n\n{merged_reasoning}"
            )
        elif len(chunk_results) > 1:
            merged_reasoning = f"[文本已分为{len(chunk_results)}块并行审核]\n\n{merged_reasoning}"

        # 4. 构建合并结果
        violation_type = best_vt if best_vt != "none" else ("none" if not all_types else list(all_types)[0])

        return {
            "violation_type": violation_type,
            "confidence": round(avg_conf, 4),
            "reason": f"分块审核({len(valid_results)}/{len(chunk_results)}块有效): {violation_type}",
            "reasoning": merged_reasoning[:3000],
            "reasoning_chain": [
                f"[分块审核] {len(chunk_results)}块 → {len(valid_results)}块有效, "
                f"检测类型: {', '.join(all_types) if all_types else 'none'}"
            ],
            "is_adversarial": has_adversarial,
            "tags": list(all_tags),
            "risk_score": round(max_risk, 4),
            "chunk_count": len(chunk_results),
            "is_chunked": True,
            "all_violation_types": list(all_types),
            "keyword_matches": list(set(all_keywords))[:20],
        }


# ============================================================
# RAGChunker v1.0 — 入库分块专用 (chunk_size=800, overlap=100)
# ============================================================

class RAGChunker:
    """
    RAG 入库文档分块器

    与 TextChunker 的区别:
    - chunk_size 更小 (800字 vs 2000字): 适配 embedding 模型的最优输入长度
    - overlap 更小 (100字 vs 200字): 减少冗余，提高检索效率
    - 输出格式适配 ChromaDB 的 ParentDocument 模式
    - 父文档 ID + chunk 序号 作为索引键
    """

    CHUNK_SIZE = 800
    OVERLAP = 100
    MIN_CHUNK = 300

    @classmethod
    def chunk_for_rag(cls, text: str, doc_id: str) -> list[dict]:
        """
        将文档分块用于 RAG 入库

        Args:
            text: 文档原文
            doc_id: 父文档 ID

        Returns:
            [{chunk_id, parent_id, chunk_index, text, char_start, char_end}, ...]
            单块文本直接返回原文档
        """
        if len(text) <= cls.CHUNK_SIZE:
            return [{
                "chunk_id": doc_id,
                "parent_id": doc_id,
                "chunk_index": 0,
                "text": text,
                "char_start": 0,
                "char_end": len(text),
            }]

        chunks = []
        pos = 0
        chunk_idx = 0
        text_len = len(text)

        while pos < text_len:
            end = min(pos + cls.CHUNK_SIZE, text_len)

            # 边界感知拆分
            if end < text_len:
                # 优先 paragraph, 其次 sentence, 再 newline
                for boundary_char in ['\n\n', '\n', '。', '！', '？', '.', '!', '?', '；', ';']:
                    search_start = max(pos + cls.MIN_CHUNK, end - 200)
                    boundary = text.rfind(boundary_char, search_start, end + 50)
                    if boundary > search_start:
                        end = boundary + 1
                        break

            chunk_text = text[pos:end].strip()
            if chunk_text:
                chunks.append({
                    "chunk_id": f"{doc_id}_chunk{chunk_idx:03d}",
                    "parent_id": doc_id,
                    "chunk_index": chunk_idx,
                    "text": chunk_text,
                    "char_start": pos,
                    "char_end": end,
                })
                chunk_idx += 1

            pos = end - cls.OVERLAP
            if pos >= text_len:
                break

        return chunks if chunks else [{
            "chunk_id": doc_id,
            "parent_id": doc_id,
            "chunk_index": 0,
            "text": text,
            "char_start": 0,
            "char_end": len(text),
        }]
