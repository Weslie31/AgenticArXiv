# AgenticArxiv/tools/pdf_download_tool.py
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, Any, Optional, Union

from tools.tool_registry import registry
from models.store import store
from models.schemas import Paper
from models.schemas import PdfAsset
from utils.pdf_downloader import (
    normalize_arxiv_pdf_url,
    safe_filename,
    acquire_lock,
    release_lock,
    download_pdf,
)
from utils.pdf_resolver import get_fallback_urls
from config import settings
from utils.logger import log


def _fallback_pdf_url(paper_id: str) -> str:
    """返回最后兜底的 PDF URL。

    - arXiv 形态 ID（YYMM.NNNNN）→ arxiv.org/pdf/{id}.pdf
    - DOI（10.xxx/yyy）→ 空串，调用方应进入 fallback 列表
    - 其他 → arxiv.org/pdf/{id}.pdf（可能 404，由调用方处理）
    """
    if not paper_id:
        return ""
    # DOI：不要拼到 arxiv URL（必定 404），让 fallback 流程去试 OpenAlex OA 等
    if paper_id.startswith("10.") and "/" in paper_id:
        return ""
    # OpenAlex ID（W2741809807）也不走 arxiv
    if paper_id.startswith("W") and paper_id[1:].isdigit():
        return ""
    return f"https://arxiv.org/pdf/{paper_id}.pdf"


def _build_paper_page_url(paper_id: str, paper) -> str:
    """
    构造"论文详情页"URL（不是出版社首页）。
    优先级：
      1. DOI        → https://doi.org/{doi}
      2. arXiv ID   → https://arxiv.org/abs/{id}
      3. OpenAlex   → https://openalex.org/W{id}
      4. 兜底       → paper.pdf_url 或 arXiv pdf 链接
    """
    if not paper_id:
        return ""

    # 1) DOI
    if paper_id.startswith("10.") and "/" in paper_id:
        return f"https://doi.org/{paper_id}"

    # 2) arXiv ID（YYMM.NNNNN 或 YYMM.NNNNNNN）
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", paper_id):
        return f"https://arxiv.org/abs/{paper_id}"

    # 3) OpenAlex ID（短码形如 W2741809807，或完整 URL）
    if paper_id.startswith("W") and paper_id[1:].isdigit():
        return f"https://openalex.org/{paper_id}"
    if "openalex.org/" in paper_id:
        return paper_id

    # 4) 兜底
    pdf_url = getattr(paper, "pdf_url", None)
    if pdf_url:
        return pdf_url
    return f"https://arxiv.org/pdf/{paper_id}.pdf"


def _download_arxiv_pdf_impl(
    session_id: str = "default",
    ref: Union[str, int, None] = 1,
    paper_id: Optional[str] = None,
    pdf_url: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    按 session 的短期记忆 + ref(1-based/arxiv id/title子串) 下载 PDF 到 settings.pdf_raw_path
    支持 ref = None(JSON null): 表示"最近一次操作的论文"
    文件命名: {paper.id}.pdf (canonical)
    同时更新 output/pdf_cache.json

    支持非 arXiv 论文:
    - 如 tool 上游(如 get_paper_by_doi)已经得到可下载的 PDF URL,
      应通过 pdf_url 参数显式传入,跳过 best_oa 推导。
    """
    paper: Optional[Paper] = None
    explicit_pdf_url: Optional[str] = pdf_url  # 调用方传进来的,最优先

    if paper_id:
        paper = store.resolve_paper(session_id, paper_id=paper_id)
        # 优先顺序: 调用方传入 > paper.pdf_url > _fallback_pdf_url
        if explicit_pdf_url:
            pdf_url = explicit_pdf_url
        else:
            pdf_url = (paper.pdf_url if paper else None) or _fallback_pdf_url(paper_id)
    elif ref is None:
        # 指代: 最近一次操作的论文
        last_id = store.get_last_active_paper_id(session_id)
        if not last_id:
            raise ValueError("未找到指代对象: 请先下载/翻译/查状态某篇论文,或明确提供 ref (序号/id/标题)")
        paper_id = last_id
        paper = store.resolve_paper(session_id, paper_id=paper_id)
        if explicit_pdf_url:
            pdf_url = explicit_pdf_url
        else:
            pdf_url = (paper.pdf_url if paper else None) or _fallback_pdf_url(paper_id)
    else:
        paper = store.resolve_paper(session_id, ref)
        if paper is None:
            raise ValueError("未找到论文: 请先调用 /arxiv/recent 写入 session 记忆,或检查 ref 是否正确")
        paper_id = paper.id
        if explicit_pdf_url:
            pdf_url = explicit_pdf_url
        else:
            pdf_url = paper.pdf_url or _fallback_pdf_url(paper_id)

    # 一旦确定 paper_id，就更新 last_active（不区分下载/翻译，只要“操作了”就更新）
    store.set_last_active_paper_id(session_id, paper_id)

    pdf_url = normalize_arxiv_pdf_url(pdf_url)

    filename = safe_filename(paper_id) + ".pdf"
    local_path = os.path.join(settings.pdf_raw_path, filename)

    # 1) 若已存在且不强制，且状态已经是 READY，直接返回 READY
    existed = os.path.exists(local_path) and os.path.getsize(local_path) > 0
    asset = store.get_pdf_asset(paper_id)

    # 如果历史索引里标记为 FAILED 但磁盘上还有遗留的假 PDF (历史的 fallback PDF), 删掉
    if asset and asset.status == "FAILED":
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
        except Exception:
            pass
        existed = False

    if existed and not force:
        if asset is None:
            asset = PdfAsset(
                paper_id=paper_id,
                pdf_url=pdf_url,
                local_path=local_path,
                status="READY",
                size_bytes=os.path.getsize(local_path),
                downloaded_at=datetime.now(),
            )
            store.upsert_pdf_asset(asset)
        else:
            # 如果索引里不是 READY，纠正一下
            if asset.status != "READY":
                store.update_pdf_asset(
                    paper_id,
                    status="READY",
                    local_path=local_path,
                    pdf_url=pdf_url,
                    size_bytes=os.path.getsize(local_path),
                    downloaded_at=asset.downloaded_at or datetime.now(),
                    error=None,
                )
        return {
            "session_id": session_id,
            "paper_id": paper_id,
            "pdf_url": pdf_url,
            "local_path": local_path,
            "status": "READY",
            "existed": True,
        }

    # 2) 需要下载：加锁避免并发重复下载
    lock_path = local_path + ".lock"
    acquire_lock(lock_path)

    try:
        # 标记 DOWNLOADING
        if asset is None:
            asset = PdfAsset(
                paper_id=paper_id,
                pdf_url=pdf_url,
                local_path=local_path,
                status="DOWNLOADING",
                size_bytes=0,
                sha256=None,
                downloaded_at=None,
                error=None,
            )
            store.upsert_pdf_asset(asset)
        else:
            store.update_pdf_asset(
                paper_id,
                status="DOWNLOADING",
                pdf_url=pdf_url,
                local_path=local_path,
                error=None,
            )

        # 真正下载；若 primary url 为空（DOI/OpenAlex 等）则跳过，直接走 fallback 列表
        primary_err: Optional[Exception] = None
        if pdf_url:
            try:
                size_bytes, sha256_hex = download_pdf(pdf_url, local_path)
            except Exception as e:
                primary_err = e
                log.warning(f"[pdf_download] primary url failed ({pdf_url}): {e}")
                size_bytes, sha256_hex = 0, ""
        else:
            log.info(f"[pdf_download] no primary pdf_url for {paper_id} (DOI/OpenAlex id), skip primary, try fallbacks")
            size_bytes, sha256_hex = 0, ""
            raise RuntimeError("primary pdf_url is empty; falling back to alternative URLs")

        # 标记 READY
        store.update_pdf_asset(
            paper_id,
            status="READY",
            size_bytes=size_bytes,
            sha256=sha256_hex,
            downloaded_at=datetime.now(),
            error=None,
        )

        return {
            "session_id": session_id,
            "paper_id": paper_id,
            "pdf_url": pdf_url,
            "local_path": local_path,
            "status": "READY",
            "existed": False,
            "size_bytes": size_bytes,
            "sha256": sha256_hex,
        }

    except Exception as primary_err:
        # 尝试 fallback URL(OpenAlex best_oa / links 中的 PDF 等)
        # 即使 paper is None(常见场景: paper_id 传过来但 session 内没有元数据),
        # 也要构造一份兜底 URL 列表重试。
        fallback_tried_urls: list[str] = []
        fallback_err: str = ""
        succeeded = False
        final_size = 0
        final_sha = ""

        if paper is not None:
            # paper.links 已包含 OpenAlex best_oa_location.pdf_url(见 base_agent._openalex_dict_to_paper)
            links_attr = getattr(paper, "links", None) or []
            # 正确传入 DOI（来自 paper.paper_url 或 paper.id）和 OpenAlex ID
            doi = (paper.paper_url or "").replace("https://doi.org/", "") if paper.paper_url else (paper.id if paper.id.startswith("10.") else "")
            openalex_id = paper.id if not doi else ""
            candidate_urls = list(get_fallback_urls(
                doi=doi,
                openalex_id=openalex_id,
                links=links_attr,
            ))
        else:
            # paper 不在 session 里，至少用 paper_id 本身尝试 Semantic Scholar 兜底
            candidate_urls = list(get_fallback_urls(
                doi=paper_id if paper_id.startswith("10.") else "",
                openalex_id=paper_id if paper_id.startswith("W") else "",
            ))

        # 把调用方显式传入的 pdf_url 也加入候选(可能是 PMC/PubMed 等 OA PDF,
        # 之前 primary 失败但下载其实可用 - 例如原 URL 走的是 arxiv 镜像被 404)
        for extra in (explicit_pdf_url,):
            if extra and extra not in candidate_urls and extra != pdf_url:
                candidate_urls.append(extra)

        for fb_url in candidate_urls:
            if fb_url == pdf_url or fb_url in fallback_tried_urls:
                continue
            fallback_tried_urls.append(fb_url)
            log.info(f"[pdf_download] try fallback url: {fb_url}")
            try:
                final_size, final_sha = download_pdf(fb_url, local_path)
                succeeded = True
                pdf_url = fb_url   # 用成功的 URL 更新记录
                log.info(f"[pdf_download] fallback succeeded: {fb_url}")
                break
            except Exception as fb_e:
                fallback_err = str(fb_e)
                log.warning(f"[pdf_download] fallback failed ({fb_url}): {fb_e}")
                continue

        if succeeded:
            store.update_pdf_asset(
                paper_id,
                status="READY",
                pdf_url=pdf_url,
                size_bytes=final_size,
                sha256=final_sha,
                downloaded_at=datetime.now(),
                error=None,
            )
            return {
                "session_id": session_id,
                "paper_id": paper_id,
                "pdf_url": pdf_url,
                "local_path": local_path,
                "status": "READY",
                "existed": False,
                "size_bytes": final_size,
                "sha256": final_sha,
            }

        # 所有 URL 均失败: 标记为 FAILED,不写 fallback PDF (前端显示"无法下载"标签即可)
        reason = (
            f"Primary URL failed: {primary_err}; Fallbacks also failed: {fallback_err}"
            if fallback_tried_urls
            else str(primary_err)
        )

        # 清理: 如果之前已经存在"假 ready"的 fallback PDF (历史遗留), 删掉
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
        except Exception:
            pass

        # 写一个 FAILED 状态的 asset 记录(不写本地 PDF 文件)
        log.warning(f"[pdf_download] all urls failed for {paper_id}: {reason}")
        store.update_pdf_asset(
            paper_id,
            status="FAILED",
            pdf_url=pdf_url,
            local_path="",   # 没有本地文件
            size_bytes=0,
            sha256=None,
            downloaded_at=datetime.now(),
            error=reason,
        )

        return {
            "session_id": session_id,
            "paper_id": paper_id,
            "pdf_url": pdf_url,
            "local_path": "",
            "status": "FAILED",
            "existed": False,
            "size_bytes": 0,
            "sha256": None,
            "download_error": reason,
        }
    finally:
        release_lock(lock_path)


def download_arxiv_pdf(
    session_id: str = "default",
    ref: Union[str, int, None] = 1,
    paper_id: Optional[str] = None,
    pdf_url: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """下载 PDF，并登记对这篇论文缓存的引用。"""
    result = _download_arxiv_pdf_impl(
        session_id=session_id,
        ref=ref,
        paper_id=paper_id,
        pdf_url=pdf_url,
        force=force,
    )
    return result


PDF_DOWNLOAD_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "会话ID,用于从短期记忆中解析 ref 或读取 last_active_paper_id",
            "default": "default",
        },
        "ref": {
            "description": "论文引用: 1-based序号 或 arxiv id 或 title子串; 也支持 null 表示最近一次操作的论文",
            "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
        },
        "paper_id": {
            "type": "string",
            "description": "直接指定论文 ID (DOI/OpenAlex/arXiv id),跳过 ref 解析",
        },
        "pdf_url": {
            "type": "string",
            "description": "直接指定可下载的 PDF URL (覆盖自动推断,用于非 arXiv 论文如 PMC/PubMed/Unpaywall 等)",
        },
        "force": {
            "type": "boolean",
            "description": "是否强制重新下载 (覆盖本地文件)",
            "default": False,
        },
    },
    "required": [],
}

registry.register_tool(
    name="download_arxiv_pdf",
    description="按 session 短期记忆和 ref/paper_id 下载论文 PDF,并维护 pdf_cache.json 索引 (支持 arXiv 及非 arXiv 论文;非 arXiv 推荐传入 pdf_url 或 paper_id)",
    parameter_schema=PDF_DOWNLOAD_TOOL_SCHEMA,
    func=download_arxiv_pdf,
)
