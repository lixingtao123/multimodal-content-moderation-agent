"""
FileAgent v3.4 — 文件内容审查 Agent

支持全模态输入: 文本 + 多文件 (PDF/Word/TXT/图片)
对每个文件调用对应解析器提取文本，然后汇总给 TextAgent 做语义审核

v3.4 升级:
  - 保留图片在文本中的位置锚定信息 (char_position)
  - 图片不丢弃, 记录为 image_anchors 供 MMCC 构建使用
  - 文档解析时提取嵌入图片的位置
  - 废弃 MAX_COMBINED_CHARS 硬截断, 长文本由协调器信号卡压缩处理

工作流:
  1. 解析用户直接输入的文本 (如有)
  2. 逐文件解析: PDF → pdfplumber, Word → python-docx, TXT → 编码检测
  3. 记录图片位置锚定信息
  4. 汇总所有文本 → TextAgent 语义分析
"""
import time
import logging
from typing import Optional

from agent_moderation.state import ModerationState
from agent_moderation.agents.base import BaseAgent
from agent_moderation.parsers import extract_text_from_pdf, extract_text_from_docx, extract_text_from_txt
# v3.4: docx 图片提取
from agent_moderation.parsers.docx_parser import extract_text_and_images_from_docx

logger = logging.getLogger(__name__)

# 支持的文件扩展名映射
EXTENSION_MAP = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",     # .doc 也尝试用 docx 解析
    ".txt": "txt",
    ".md": "txt",
    ".csv": "txt",
    ".json": "txt",
    ".xml": "txt",
    ".html": "txt",
    ".htm": "txt",
    ".log": "txt",
    ".py": "txt",
    ".js": "txt",
    ".ts": "txt",
    ".java": "txt",
    ".go": "txt",
    ".rs": "txt",
    ".cpp": "txt",
    ".c": "txt",
    ".h": "txt",
    ".yaml": "txt",
    ".yml": "txt",
    ".toml": "txt",
    ".ini": "txt",
    ".cfg": "txt",
    ".conf": "txt",
}


def get_file_type(filename: str) -> str:
    """根据扩展名确定文件类型"""
    import os
    ext = os.path.splitext(filename)[1].lower()
    return EXTENSION_MAP.get(ext, "unknown")


class FileAgent(BaseAgent):
    """文件审查 Agent — 解析文件内容并做审核"""

    def __init__(self):
        super().__init__("file_agent")

    async def process(self, state: ModerationState) -> ModerationState:
        """
        处理全模态输入:
          - state["content"]["text"]: 用户直接输入的文字 (可选)
          - state["content"]["files"]: 上传的文件列表 [{filename, content, mime_type}, ...]
        """
        content = state.get("content", {})
        files = content.get("files", [])
        user_text = content.get("text", "")

        extracted_texts: list[str] = []
        file_results: list[dict] = []

        # === 1. 直接文本 ===
        if user_text and user_text.strip():
            extracted_texts.append(f"[用户输入文本]\n{user_text.strip()}")
            self.log_step(f"User text: {len(user_text)} chars")

        # === 2. 逐文件解析 ===
        # v3.4: 收集所有嵌入图片 (带位置锚定)
        all_docx_images = []  # [{image_id, char_position, data, filename, mime_type}, ...]

        for f in files:
            filename = f.get("filename", "unknown")
            file_bytes = f.get("content", b"")
            mime_type = f.get("mime_type", "")
            file_type = get_file_type(filename)

            t0 = time.time()
            parsed_text = ""
            # 该文件在 combined_text 中的起始位置 (稍后填充)
            file_text_prefix = f"[文件: {filename}]\n"

            if file_type == "pdf":
                parsed_text = await extract_text_from_pdf(file_bytes, filename)
            elif file_type == "docx":
                # v3.4: 使用增强解析器, 同时提取文本和嵌入图片
                docx_result = await extract_text_and_images_from_docx(file_bytes, filename)
                parsed_text = docx_result.get("text", "")
                docx_images = docx_result.get("images", [])
                if docx_images:
                    self.log_step(f"  📷 {filename}: found {len(docx_images)} embedded images")
                    # 暂存图片 (位置偏移将在汇总阶段计算)
                    all_docx_images.append({
                        "images": docx_images,
                        "file_index": len(file_results),  # 当前文件序号
                        "filename": filename,
                    })
            elif file_type == "txt":
                parsed_text = await extract_text_from_txt(file_bytes, filename)
            elif mime_type and mime_type.startswith("image/"):
                # 图片类型: 记录但不在此解析 (由 ImageAgent 处理)
                parsed_text = f"[图片文件] {filename} ({len(file_bytes)} bytes)"
                file_results.append({
                    "filename": filename, "type": "image",
                    "size": len(file_bytes), "parsed_length": 0,
                    "parse_time_ms": (time.time() - t0) * 1000,
                    "text": parsed_text, "error": None,
                })
                continue
            elif mime_type and mime_type.startswith("audio/"):
                # v3.4fix: 音频类型: 记录但不在此解析 (由 AudioAgent 处理)
                parsed_text = f"[音频文件] {filename} ({len(file_bytes)} bytes)"
                file_results.append({
                    "filename": filename, "type": "audio",
                    "size": len(file_bytes), "parsed_length": 0,
                    "parse_time_ms": (time.time() - t0) * 1000,
                    "text": parsed_text, "error": None,
                })
                continue
            elif filename.lower().endswith((".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma")):
                # v3.4fix: 扩展名判断音频文件 (由 AudioAgent 处理)
                parsed_text = f"[音频文件] {filename} ({len(file_bytes)} bytes)"
                file_results.append({
                    "filename": filename, "type": "audio",
                    "size": len(file_bytes), "parsed_length": 0,
                    "parse_time_ms": (time.time() - t0) * 1000,
                    "text": parsed_text, "error": None,
                })
                continue
            else:
                # 未知类型: 尝试当文本文件解析
                logger.info(f"Unknown file type for {filename}, trying as text")
                parsed_text = await extract_text_from_txt(file_bytes, filename)
                if parsed_text.startswith("[") and not any(
                    kw in parsed_text.lower() for kw in ["error", "fail", "empty"]
                ):
                    file_type = "txt_fallback"

            elapsed = (time.time() - t0) * 1000
            file_results.append({
                "filename": filename, "type": file_type,
                "size": len(file_bytes), "parsed_length": len(parsed_text),
                "parse_time_ms": elapsed, "text": parsed_text[:500],
                "error": None if not parsed_text.startswith("[") else parsed_text,
            })

            if parsed_text and not parsed_text.startswith("[PDF") and not parsed_text.startswith("[Word"):
                # 只添加成功解析的文本
                extracted_texts.append(f"[文件: {filename}]\n{parsed_text}")
            elif parsed_text:
                # 解析失败但仍然记录
                extracted_texts.append(parsed_text)

            self.log_step(f"Parsed {filename} ({file_type}): {len(parsed_text)} chars in {elapsed:.0f}ms")

        # === 3. 汇总 ===
        combined_text = "\n\n---\n\n".join(extracted_texts) if extracted_texts else "[无可提取的文本内容]"

        # v3.4: 废弃硬截断 — 长文本由协调器通过信号卡压缩处理,
        # FileAgent 保留完整文本, 不再暴力截断。
        # 标记 is_truncated=False 以区分旧版本行为。
        is_truncated = False
        if len(combined_text) > 20000:
            logger.info(f"FileAgent: text is long ({len(combined_text)} chars), "
                       f"will be handled by coordinator signal card compression")

        # v3.4: 收集图片锚定信息 (供 MMCC 构建使用)
        image_anchors = []

        # 1. 直接上传的图片文件
        image_files = [f for f in file_results if f.get("type") == "image"]
        current_pos = 0
        for ext_text in extracted_texts:
            for img_file in image_files:
                img_filename = img_file.get("filename", "")
                if img_filename in ext_text:
                    img_pos = ext_text.find(img_filename)
                    if img_pos >= 0:
                        # 从原始 files 列表中找到图片 bytes
                        img_data = b""
                        for orig_f in files:
                            if orig_f.get("filename") == img_filename:
                                img_data = orig_f.get("content", b"")
                                break
                        image_anchors.append({
                            "image_id": f"file_img_{img_filename}",
                            "char_position": current_pos + img_pos,
                            "filename": img_filename,
                            "size": img_file.get("size", 0),
                            "data": img_data,
                            "mime_type": img_file.get("mime_type", "image/png"),
                            "source": "direct_upload",
                        })
            current_pos += len(ext_text) + 5  # 5 = len("\n\n---\n\n")

        # 2. v3.4: docx 嵌入图片 (带精确定位)
        # 重新计算每个 extracted_text 在全文中位置, 将 docx 图片偏移到正确位置
        cumulative_pos = 0
        for i, ext_text in enumerate(extracted_texts):
            ext_prefix_len = len(ext_text) + 5  # 当前段 + 分隔符
            # 检查是否有 docx 图片属于这个文件
            for docx_img_group in all_docx_images:
                # 找到对应 extracted_text 的索引
                # extracted_texts 包含 [用户输入文本] (如有) + 各文件的文本
                # 文件文本带前缀 "[文件: {filename}]\n"
                group_filename = docx_img_group["filename"]
                if f"[文件: {group_filename}]" in ext_text:
                    prefix_len = len(f"[文件: {group_filename}]\n")
                    for img in docx_img_group["images"]:
                        # docx 中的 char_position 相对于 docx 文本
                        # 在 combined_text 中需要加上:
                        #   cumulative_pos + prefix_len + img["char_position"]
                        absolute_pos = cumulative_pos + prefix_len + img.get("char_position", 0)
                        image_anchors.append({
                            "image_id": f"docx_img_{img['filename']}_p{img.get('paragraph_index', 0)}",
                            "char_position": absolute_pos,
                            "filename": img.get("filename", ""),
                            "size": len(img.get("data", b"")),
                            "data": img.get("data", b""),
                            "mime_type": img.get("mime_type", "image/png"),
                            "paragraph_index": img.get("paragraph_index", 0),
                            "source": "docx_embedded",
                        })
            cumulative_pos += ext_prefix_len

        if image_anchors:
            self.log_step(f"  📷 Total image anchors: {len(image_anchors)} "
                         f"({sum(1 for a in image_anchors if a.get('source')=='docx_embedded')} from docx, "
                         f"{sum(1 for a in image_anchors if a.get('source')=='direct_upload')} direct uploads)")

        # 存储解析结果到 state
        state["file_results"] = {
            "file_count": len(files),
            "total_chars": len(combined_text),
            "files": file_results,
            "combined_text": combined_text,
            "is_truncated": is_truncated,
            # v3.4: 图片位置锚定
            "image_anchors": image_anchors,
        }

        # 将汇总文本注入 content 供 TextAgent 使用
        state["content"]["text"] = combined_text
        state["content_type"] = "text"  # 后续按文本审核流程走
        state["_is_multimodal"] = True

        # v3.4: 将 docx 嵌入图片注入 content["files"], 使其参与 ContentGraph + MMCC 流程
        if image_anchors:
            existing_files = list(state["content"].get("files", []))
            # v4.4: 幂等 — 按 (filename, _char_position) 查重, 避免 FileAgent 被多次调用时
            #      嵌入图被反复追加, 导致 files 累积、下游图片被重复处理多轮
            existing_embedded = {
                (f.get("filename", ""), f.get("_char_position", 0))
                for f in existing_files if f.get("_docx_embedded")
            }
            for anchor in image_anchors:
                if anchor.get("source") == "docx_embedded" and anchor.get("data"):
                    key = (anchor.get("filename", ""), anchor.get("char_position", 0))
                    if key in existing_embedded:
                        continue
                    existing_embedded.add(key)
                    existing_files.append({
                        "filename": anchor.get("filename", "embedded.png"),
                        "content": anchor.get("data", b""),
                        "mime_type": anchor.get("mime_type", "image/png"),
                        "_docx_embedded": True,
                        "_char_position": anchor.get("char_position", 0),
                    })
            if existing_files:
                state["content"]["files"] = existing_files

        self.log_step(f"FileAgent complete: {len(files)} files → {len(combined_text)} chars total")
        return state
