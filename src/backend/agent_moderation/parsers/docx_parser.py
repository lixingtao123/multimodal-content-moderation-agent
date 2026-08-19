"""
Word 文档 (.docx) 文本 + 图片提取器 v3.4

v3.4 升级:
  - 新增 extract_text_and_images_from_docx() → 返回文本 + 嵌入图片(带位置锚定)
  - 图片通过 python-docx 的 XML 定位到具体段落位置
  - 旧接口 extract_text_from_docx() 保持兼容, 内部调用新接口
"""
import io
import logging
import zipfile
from typing import Optional

logger = logging.getLogger(__name__)

# OOXML 命名空间
NSMAP = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
}

# 图片 content-type 映射 (扩展名 → MIME)
IMG_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


def _get_image_mime(filename: str) -> str:
    """根据文件名推断图片 MIME 类型"""
    import os
    ext = os.path.splitext(filename)[1].lower()
    return IMG_MIME_MAP.get(ext, "application/octet-stream")


async def extract_text_and_images_from_docx(
    file_bytes: bytes, filename: str = ""
) -> dict:
    """
    v3.4: 提取 .docx 中的文本 + 嵌入图片 (带位置锚定)

    处理流程:
      1. 用 python-docx 遍历段落, 累积文本位置
      2. 对有图片的段落, 从 zip 中提取图片 bytes
      3. 记录每张图片在文本中的 char_position

    Returns:
        {
            "text": "完整文本 (不限长)",
            "images": [
                {
                    "image_id": "docx_img_image1.png",
                    "char_position": 1234,       # 在全文中的字符偏移
                    "data": b"...",              # 图片原始 bytes
                    "filename": "image1.png",
                    "mime_type": "image/png",
                    "paragraph_index": 5,        # 所在段落索引
                    "image_index": 0,            # 全文中的图片序号
                },
                ...
            ]
        }
    """
    try:
        from docx import Document
    except ImportError:
        logger.error("python-docx not installed. Run: pip install python-docx")
        return {
            "text": f"[Word 解析失败: python-docx 未安装] {filename}",
            "images": [],
        }

    try:
        doc = Document(io.BytesIO(file_bytes))
    except Exception as e:
        logger.warning(f"DOCX parse error ({filename}): {e}")
        return {
            "text": f"[Word 解析错误: {str(e)[:100]}] {filename}",
            "images": [],
        }

    # 打开 zip 以提取原始图片 bytes
    try:
        docx_zip = zipfile.ZipFile(io.BytesIO(file_bytes))
    except Exception:
        docx_zip = None
        logger.warning(f"Cannot open {filename} as zip for image extraction")

    paragraphs = []
    images = []
    current_pos = 0
    image_idx = 0

    # 获取文档级别的 relationships (用于解析图片引用)
    doc_rels = doc.part.rels if hasattr(doc, 'part') else {}

    for para_idx, para in enumerate(doc.paragraphs):
        text = para.text
        para_start = current_pos

        # === 检测段落中的嵌入图片 ===
        para_images = _extract_images_from_paragraph(
            para, doc_rels, docx_zip, para_idx
        )
        for img_info in para_images:
            img_info["char_position"] = para_start
            img_info["image_id"] = f"docx_img_{img_info['filename']}_p{para_idx}"
            img_info["image_index"] = image_idx
            image_idx += 1
            images.append(img_info)

        # 追加文本
        if text.strip():
            paragraphs.append(text)
            current_pos += len(text) + 1  # +1 for newline separator
        elif text:  # 纯空白行
            paragraphs.append(text)
            current_pos += len(text) + 1
        else:
            # 空段落: 如果有图片, 图片位置已记录在上方
            # 空段也占一个换行
            if para_images:
                current_pos += 1  # 占位, 表示这里有内容

    # 也提取表格中的文本 (表格中通常没有图片)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                table_text = " | ".join(cells)
                paragraphs.append(table_text)
                current_pos += len(table_text) + 1

    # 关闭 zip
    if docx_zip:
        docx_zip.close()

    if not paragraphs and not images:
        return {"text": f"[Word 文档内容为空] {filename}", "images": []}

    result_text = "\n".join(paragraphs)
    total_paragraphs = len(doc.paragraphs)

    logger.info(
        f"DOCX v3.4 parsed: {filename}, "
        f"text={len(result_text)} chars, "
        f"{total_paragraphs} paragraphs, "
        f"{len(images)} embedded images"
    )

    return {"text": result_text, "images": images}


def _extract_images_from_paragraph(
    para, doc_rels: dict, docx_zip: Optional[zipfile.ZipFile], para_idx: int
) -> list[dict]:
    """
    从段落 XML 中提取嵌入图片

    查找 w:drawing > wp:inline > a:graphic > a:graphicData > pic:pic > pic:blipFill > a:blip
    从 blip 的 r:embed 属性获取关系 ID, 再通过 doc_rels 找到图片 target

    Returns:
        [{"filename": "image1.png", "data": bytes, "mime_type": "image/png"}, ...]
    """
    images = []

    try:
        from lxml import etree
    except ImportError:
        # 无 lxml 时尝试用 xml.etree (标准库)
        import xml.etree.ElementTree as ET
        _use_lxml = False
    else:
        _use_lxml = True

    if _use_lxml:
        # lxml 支持命名空间
        try:
            drawings = para._p.findall(".//w:drawing", NSMAP)
        except Exception:
            return images

        for drawing in drawings:
            # 查找 a:blip 元素
            blips = drawing.findall(".//a:blip", NSMAP)
            for blip in blips:
                embed_id = blip.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
                )
                if not embed_id:
                    continue

                img_info = _resolve_image_rel(embed_id, doc_rels, docx_zip)
                if img_info:
                    img_info["paragraph_index"] = para_idx
                    images.append(img_info)
    else:
        # xml.etree 回退: 手动处理命名空间
        try:
            drawing_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing"
            blip_ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
            embed_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"

            for drawing in para._p.iter(drawing_ns):
                for blip in drawing.iter(blip_ns):
                    embed_id = blip.get(embed_attr)
                    if not embed_id:
                        continue
                    img_info = _resolve_image_rel(embed_id, doc_rels, docx_zip)
                    if img_info:
                        img_info["paragraph_index"] = para_idx
                        images.append(img_info)
        except Exception:
            pass

    return images


def _resolve_image_rel(
    embed_id: str, doc_rels: dict, docx_zip: Optional[zipfile.ZipFile]
) -> Optional[dict]:
    """
    通过关系 ID 解析图片

    1. 从 doc_rels 中找到 rId 对应的 Relationship
    2. 从 Relationship.target_ref 获取图片文件名 (e.g., "media/image1.png")
    3. 从 zip 中提取图片 bytes
    """
    try:
        # 获取关系对象
        rel = doc_rels.get(embed_id)
        if rel is None:
            return None

        # rel.target_ref 是图片在 docx 内的路径, 如 "media/image1.png"
        target = rel.target_ref if hasattr(rel, 'target_ref') else str(rel.target_ref) if hasattr(rel, 'target_ref') else None
        if not target:
            return None

        # 在 zip 中定位图片
        zip_path = f"word/{target}" if not target.startswith("word/") else target

        if docx_zip:
            try:
                img_bytes = docx_zip.read(zip_path)
            except KeyError:
                # 尝试其他可能路径
                try:
                    img_bytes = docx_zip.read(target)
                except KeyError:
                    logger.debug(f"Image not found in zip: {zip_path} or {target}")
                    return None
        else:
            # 无 zip 访问: 尝试从 rel.target_part 获取
            if hasattr(rel, 'target_part') and rel.target_part:
                img_bytes = rel.target_part.blob
            else:
                return None

        import os
        img_filename = os.path.basename(target)

        return {
            "filename": img_filename,
            "data": img_bytes,
            "mime_type": _get_image_mime(img_filename),
        }

    except Exception as e:
        logger.debug(f"Failed to resolve image rel {embed_id}: {e}")
        return None


async def extract_text_from_docx(file_bytes: bytes, filename: str = "") -> str:
    """
    从 .docx 文件中提取文本 (向后兼容接口)

    v3.4: 内部调用 extract_text_and_images_from_docx(),
          仅返回文本部分, 图片提取逻辑在上层处理。
    """
    # v3.4: 移除 10000 字符硬截断
    # 长文本由协调器的信号卡压缩处理
    result = await extract_text_and_images_from_docx(file_bytes, filename)
    text = result.get("text", "")

    if text.startswith("[Word"):
        return text

    # v3.4: 不再截断 — 标记长文本, 由协调器处理
    if len(text) > 10000:
        logger.info(f"DOCX text is long ({len(text)} chars), "
                    f"will be handled by coordinator")

    return text
