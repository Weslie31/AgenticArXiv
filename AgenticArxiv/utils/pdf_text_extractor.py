# AgenticArxiv/utils/pdf_text_extractor.py
from __future__ import annotations

import os
from typing import Optional

from utils.logger import log


def extract_text_from_pdf(pdf_path: str, max_chars: int = 8000) -> str:
    """
    从 PDF 文件提取文本（用于 AI 总结）
    
    Args:
        pdf_path: PDF 文件路径
        max_chars: 最大提取字符数（避免 token 溢出）
    
    Returns:
        提取的文本内容
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        try:
            import pymupdf as fitz
        except ImportError:
            log.error("需要安装 pymupdf: pip install pymupdf")
            raise ImportError("请安装 pymupdf: pip install pymupdf")

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

    doc = fitz.open(pdf_path)
    text_parts = []
    total_chars = 0

    # 优先提取前几页（通常包含摘要和背景）
    # 也提取最后几页（可能有结论）
    num_pages = len(doc)
    page_indices = list(range(min(5, num_pages)))  # 前5页
    if num_pages > 10:
        page_indices.extend(range(num_pages - 3, num_pages))  # 后3页
    page_indices = sorted(set(page_indices))

    for page_num in page_indices:
        if total_chars >= max_chars:
            break
        page = doc[page_num]
        text = page.get_text("text")
        if text:
            # 清理文本
            text = clean_text(text)
            remaining = max_chars - total_chars
            if len(text) > remaining:
                text = text[:remaining] + "\n... (内容截断)"
            text_parts.append(f"=== 第 {page_num + 1} 页 ===\n{text}")
            total_chars += len(text)

    doc.close()

    result = "\n\n".join(text_parts)
    log.info(f"从 PDF 提取了 {len(result)} 字符")
    return result


def clean_text(text: str) -> str:
    """清理 PDF 提取的文本"""
    import re
    # 移除多余的空白
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 移除页码等无关内容
    text = re.sub(r"^\d+\s*$", "", text, flags=re.MULTILINE)
    # 移除 URLs（保留链接文本）
    text = re.sub(r"https?://\S+", "", text)
    # 清理首尾空白
    text = text.strip()
    return text
