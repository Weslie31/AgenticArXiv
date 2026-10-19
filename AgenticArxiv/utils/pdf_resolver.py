"""
PDF URL 解析器：将论文元数据转换为可下载的 PDF URL。

设计原则：避免在"存储论文"阶段发起大量 HTTP 请求（会导致超时阻塞），
采用"懒解析"策略——arXiv 格式 DOI 同步推算，其他 URL 在下载时动态验证。

策略优先级：
1. arXiv 镜像 — DOI 是 10.48550/arXiv.XXX 格式时，立即计算，无需网络
2. Unpaywall API — 在下载时调用（动态，获取最佳 OA PDF）
3. OpenAlex best_oa_location — 已在 Paper.links 中备用
"""
from __future__ import annotations

import re
from typing import Optional, List

from utils.logger import log


def _arxivid_from_doi(doi: str) -> Optional[str]:
    """从 DOI 提取 arXiv ID（如 10.48550/arXiv.2301.12345 → 2301.12345）"""
    if not doi:
        return None
    m = re.search(r'10\.48550/arXiv\.?(\d+\.\d+)', doi, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def resolve_pdf_url(
    doi: str,
    openalex_pdf_url: Optional[str] = None,
    openalex_best_url: Optional[str] = None,
    openalex_id: Optional[str] = None,
    links: Optional[List[str]] = None,
) -> Optional[str]:
    """
    解析可下载的 PDF URL（同步版）。

    同步路径（无网络开销）：
    - 如果 DOI 指向 arXiv → 返回 arXiv.org PDF URL（100% 可靠）

    动态路径（需网络，等 download 时再做）：
    - 其他情况返回 OpenAlex best_oa_location URL 作为候选，
      由 download_arxiv_pdf 在实际下载时验证并按需切换。

    参数:
        doi:              论文 DOI
        openalex_best_url: OpenAlex best_oa_location PDF URL
        openalex_id:      OpenAlex ID
        links:            论文所有链接列表（备用）

    返回:
        确定的 PDF URL（arXiv），或第一个候选 URL（非 arXiv）
    """
    # 同步快速路径：arXiv 论文直接构造 URL，无需网络
    if doi:
        arxivid = _arxivid_from_doi(doi)
        if arxivid:
            arxiv_url = f"https://arxiv.org/pdf/{arxivid}.pdf"
            log.info(f"[pdf_resolver] arXiv 论文，构造 URL: {arxiv_url}")
            return arxiv_url

    # 非 arXiv：返回 best_oa URL，让 download 时动态处理
    if openalex_best_url:
        log.info(f"[pdf_resolver] 非 arXiv，返回候选 URL: {openalex_best_url[:80]}")
        return openalex_best_url
    if openalex_pdf_url:
        return openalex_pdf_url
    return None


def _fetch_semantic_scholar_pdf_url(openalex_id: Optional[str] = None, doi: Optional[str] = None) -> Optional[str]:
    """通过 Semantic Scholar API 获取论文 PDF URL（免费，无需 API Key）。

    支持按 OpenAlex ID 或 DOI 查询。
    """
    import json, urllib.request, urllib.error

    if not openalex_id and not doi:
        return None

    # Semantic Scholar API: https://api.semanticscholar.org/graph/v1
    if openalex_id:
        # 提取纯 OpenAlex ID (W + 数字)
        oaid = openalex_id.lstrip("https://openalex.org/")
        # 不带前缀
        oaid = oaid.lstrip("W")
        fields = "openAccessInfo,pdf"
        url = f"https://api.semanticscholar.org/graph/v1/paper/W{oaid}?fields={fields}"
    elif doi:
        did = doi.lstrip("https://doi.org/")
        fields = "openAccessInfo,pdf"
        url = f"https://api.semanticscholar.org/graph/v1/paper/{did}?fields={fields}"
    else:
        return None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AgenticArXiv/1.0 (mailto:research@example.com)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            # 方式1: openAccessInfo.isOpenAccess + openAccessInfo.pdfUrl
            oa = data.get("openAccessInfo", {})
            if oa and oa.get("isOpenAccess") and oa.get("pdfUrl"):
                log.info(f"[pdf_resolver] Semantic Scholar OA PDF: {oa['pdfUrl'][:80]}")
                return oa["pdfUrl"]
            # 方式2: 直接 pdf 字段（某些接口返回）
            pdf = data.get("pdf")
            if pdf:
                return pdf
    except Exception as e:
        log.warning(f"[pdf_resolver] Semantic Scholar API failed: {e}")

    return None


def get_fallback_urls(
    doi: str,
    openalex_best_url: Optional[str] = None,
    openalex_pdf_url: Optional[str] = None,
    openalex_id: Optional[str] = None,
    links: Optional[List[str]] = None,
) -> List[str]:
    """
    返回所有候选 PDF URL，供下载时按序尝试。
    若候选列表为空，则动态调用 Semantic Scholar API 获取 PDF URL。
    """
    urls: List[str] = []

    # 1. arXiv 镜像（优先）
    if doi:
        arxivid = _arxivid_from_doi(doi)
        if arxivid:
            urls.append(f"https://arxiv.org/pdf/{arxivid}.pdf")

    # 2. OpenAlex OA URL
    for url in (openalex_best_url, openalex_pdf_url):
        if url and url not in urls:
            urls.append(url)

    # 3. links 里的 PDF URL
    if links:
        for link in links:
            if link and "pdf" in link.lower() and link not in urls:
                urls.append(link)

    # 4. Semantic Scholar 兜底（动态 API，候选为空时触发）
    if not urls:
        log.info("[pdf_resolver] 候选 URL 为空，尝试 Semantic Scholar 动态查询...")
        ss_url = _fetch_semantic_scholar_pdf_url(openalex_id=openalex_id, doi=doi)
        if ss_url:
            urls.append(ss_url)

    return urls
