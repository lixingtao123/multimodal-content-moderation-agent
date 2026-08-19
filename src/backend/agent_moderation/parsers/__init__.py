"""
文件解析器 — 支持 PDF / Word / TXT / 图片 文本提取
"""
from .pdf_parser import extract_text_from_pdf
from .docx_parser import extract_text_from_docx, extract_text_and_images_from_docx
from .txt_parser import extract_text_from_txt

__all__ = [
    "extract_text_from_pdf",
    "extract_text_from_docx",
    "extract_text_and_images_from_docx",
    "extract_text_from_txt",
]
