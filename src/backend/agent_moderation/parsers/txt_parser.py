"""
纯文本文件解析器
"""
import logging

logger = logging.getLogger(__name__)


async def extract_text_from_txt(file_bytes: bytes, filename: str = "") -> str:
    """从纯文本文件中读取内容，自动检测编码"""
    # 尝试常见编码
    encodings = ['utf-8', 'utf-16', 'gbk', 'gb2312', 'gb18030', 'latin-1']

    for encoding in encodings:
        try:
            text = file_bytes.decode(encoding)
            # 限制长度 50000 字符
            if len(text) > 50000:
                text = text[:50000] + f"\n...[截断: 原文 {len(text)} 字符]"
            logger.info(f"TXT parsed: {filename}, encoding={encoding}, {len(text)} chars")
            return text
        except (UnicodeDecodeError, UnicodeError):
            continue

    # 所有编码都失败，用 latin-1 兜底（不会抛异常）
    text = file_bytes.decode('latin-1', errors='replace')
    logger.warning(f"TXT parse fallback (latin-1): {filename}, {len(text)} chars")
    return text[:50000] if len(text) > 50000 else text
