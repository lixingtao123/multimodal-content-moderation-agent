"""
PDF 文件文本提取器
使用 pdfplumber 提取文字
"""
import io
import logging

logger = logging.getLogger(__name__)


async def extract_text_from_pdf(file_bytes: bytes, filename: str = "") -> str:
    """从 PDF 文件中提取文本"""
    text_parts = []

    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed. Run: pip install pdfplumber")
        return f"[PDF 解析失败: pdfplumber 未安装] {filename}"

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            total_pages = len(pdf.pages)
            # 限制最多 30 页防止超长
            max_pages = min(total_pages, 30)
            for i, page in enumerate(pdf.pages[:max_pages]):
                text = page.extract_text()
                if text:
                    text_parts.append(f"[Page {i+1}] {text.strip()}")

        if not text_parts:
            return f"[PDF 内容为空或无可提取文本] {filename}"

        result = "\n".join(text_parts)
        if total_pages > max_pages:
            result += f"\n[PDF 共 {total_pages} 页, 仅提取前 {max_pages} 页]"
        logger.info(f"PDF parsed: {filename}, {len(text_parts)} pages, {len(result)} chars")
        return result

    except Exception as e:
        logger.warning(f"PDF parse error ({filename}): {e}")
        return f"[PDF 解析错误: {str(e)[:100]}] {filename}"
