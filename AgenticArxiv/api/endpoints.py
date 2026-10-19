# AgenticArxiv/api/endpoints.py
from __future__ import annotations

import json
import os
import queue
import tempfile
import urllib.request
from urllib.parse import quote, urlparse
from urllib.error import URLError, HTTPError

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal

from tools.tool_registry import registry
from models.schemas import (
    Paper, TranslateTask, PdfAsset, TranslateAsset,
    ChatLogItem, AgentStepItem, LogSessionSummary,
    PaperComparison, ComparisonReport, ComparisonDimension,
    PaperComparisonWithReport,
)
from models.store import store
from utils.logger import log

from services.runtime import event_bus, translate_runner
from services.log_service import log_service
from config import settings


router = APIRouter()


class HealthResponse(BaseModel):
    status: str = "ok"


class LLMConfigResponse(BaseModel):
    """系统生效的 LLM 配置（脱敏后）"""
    base_url: str
    api_key_masked: str   # 仅显示 sk-*** 后 4 位
    model: str
    is_default: bool      # True 表示最终生效的是系统默认配置
    warning: Optional[str] = None  # 配置存在问题时给出提示（如缺少自有 Key）


class LLMConfigUpdateRequest(BaseModel):
    """用户更新自己的 LLM 配置"""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class LLMConfigResetResponse(BaseModel):
    """重置回系统默认的响应"""
    ok: bool = True
    message: str = "已重置为系统默认 LLM 配置"


class LLMTestRequest(BaseModel):
    """测试用户配置是否可用"""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class LLMTestResponse(BaseModel):
    ok: bool
    message: str
    detail: Optional[str] = None


# ---------------- Translate per-user config ----------------

class TranslateConfigResponse(BaseModel):
    """系统生效的翻译配置（脱敏后）"""
    service: str
    api_key_masked: str   # 仅显示后 4 位；无 key 时为空字符串
    is_default: bool      # True = 系统默认（用户未自配 service/key）


class TranslateConfigUpdateRequest(BaseModel):
    """用户更新自己的翻译配置"""
    service: Optional[str] = None   # deepl / google / openai / azure / bing
    api_key: Optional[str] = None


class TranslateConfigResetResponse(BaseModel):
    ok: bool = True
    message: str = "已重置为系统默认翻译配置"


class TranslateTestRequest(BaseModel):
    service: Optional[str] = None
    api_key: Optional[str] = None


class TranslateTestResponse(BaseModel):
    ok: bool
    message: str
    detail: Optional[str] = None


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]


class ListToolsResponse(BaseModel):
    tools: List[ToolInfo]


class ExecuteToolRequest(BaseModel):
    name: str = Field(..., description="工具名称")
    args: Dict[str, Any] = Field(default_factory=dict, description="工具参数(JSON对象)")


class ExecuteToolResponse(BaseModel):
    name: str
    result: Any


class ArxivRecentRequest(BaseModel):
    session_id: str = Field(default="default", description="会话ID，用于短期记忆")
    max_results: int = Field(default=15, ge=1, le=100)
    aspect: str = Field(default="*", description="cs子领域，如 AI/LG/CL/... 或 *")
    days: int = Field(default=7, ge=1, le=30)
    output_path: Optional[str] = Field(
        default=None,
        description="可选：保存到指定文件路径；不传则用项目 output/recent_cs_papers.txt",
    )
    save_to_file: bool = Field(default=True, description="是否写入到文件")


class ArxivRecentResponse(BaseModel):
    session_id: str
    count: int
    papers: List[Paper]


class SessionListResponse(BaseModel):
    sessions: List[str]


class SessionPapersResponse(BaseModel):
    session_id: str
    papers: List[Paper]


class CreateTranslateTaskRequest(BaseModel):
    session_id: str = "default"
    ref: str | int | None = Field(
        default=None,
        description="论文引用: 1-based序号 或 arxiv id 或 title子串; 也支持 null 表示最近一次操作的论文",
    )
    force: bool = Field(default=False, description="是否强制重新翻译")
    service: str = Field(default="bing", description="翻译服务，如 bing/deepl/google")
    threads: int = Field(default=4, ge=1, le=32, description="线程数")
    keep_dual: bool = Field(
        default=False, description="是否保留双语 PDF（默认否，只保留中文）"
    )


class CreateTranslateTaskResponse(BaseModel):
    task: TranslateTask


class GetTaskResponse(BaseModel):
    task: TranslateTask


class AgentRunRequest(BaseModel):
    session_id: str = "default"
    task: str = Field(..., description="给Agent的任务描述")
    agent_model: Optional[str] = Field(default=None, description="可选：指定模型名")


class AgentRunResponse(BaseModel):
    task: str
    history: List[Dict[str, str]]
    final_observation: str


class DownloadPdfRequest(BaseModel):
    session_id: str = Field(default="default", description="会话ID，用于短期记忆")
    ref: str | int | None = Field(
        default=None,
        description="论文引用: 1-based序号 或 arxiv id 或 title子串; 也支持 null 表示最近一次操作的论文",
    )
    paper_id: Optional[str] = Field(default=None, description="直接指定 paper_id")
    force: bool = Field(default=False, description="是否强制重新下载")


class DownloadPdfResponse(BaseModel):
    session_id: str
    paper_id: str
    pdf_url: str
    local_path: str
    status: str
    existed: bool
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None


class UploadPdfResponse(BaseModel):
    paper_id: str
    local_path: str
    size_bytes: int
    sha256: str
    status: str = "READY"


class TranslatePdfRequest(BaseModel):
    session_id: str = Field(default="default", description="会话ID, 用于短期记忆")
    ref: str | int | None = Field(
        default=None,
        description="论文引用:1-based序号 或 arxiv id 或 title子串; 也支持 null 表示最近一次操作的论文",
    )
    paper_id: Optional[str] = Field(default=None, description="直接指定 paper_id")
    force: bool = Field(default=False, description="是否强制重新翻译（覆盖本地 mono）")
    service: str = Field(default="bing", description="翻译服务，如 bing/deepl/google")
    api_key: str | None = Field(default=None, description="翻译服务 API Key（如需要）")
    threads: int = Field(
        default=4, ge=1, le=32, description="线程数（服务器 4 核可设 4）"
    )
    keep_dual: bool = Field(
        default=False, description="是否保留双语 PDF（默认否，只保留中文）"
    )


class TranslatePdfResponse(BaseModel):
    session_id: str
    paper_id: str
    input_pdf_path: str
    output_pdf_path: str
    status: str
    existed: bool
    service: str
    threads: int
    log_path: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: str = Field(default="default")
    message: str = Field(..., description="用户对 Agent 的一句话/一个任务")
    agent_model: Optional[str] = None
    agent_type: str = Field(
        default="regex",
        description="Agent 架构: regex | mcp | skill_cli",
    )


class ChatResponse(BaseModel):
    session_id: str
    message: str
    reply: str
    history: List[Dict[str, str]]
    papers: List[Paper]
    pdf_assets: List[PdfAsset]
    translate_assets: List[TranslateAsset]
    tasks: List[TranslateTask] = Field(
        default_factory=list, description="该 session 的最近任务（可选）"
    )
    agent_type: str = Field(default="regex", description="使用的 Agent 架构")


class PdfAssetsResponse(BaseModel):
    assets: List[PdfAsset]


class TranslateAssetsResponse(BaseModel):
    assets: List[TranslateAsset]


DeleteKind = Literal["pdf", "translate"]


class DeleteAssetResponse(BaseModel):
    kind: DeleteKind
    paper_id: str
    removed_cache: bool
    deleted_files: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    message: str = ""


# ---------------- SSE ----------------
def _sse_pack(event_json: str) -> str:
    try:
        obj = json.loads(event_json)
        et = obj.get("type", "message")
    except Exception:
        et = "message"
    return f"event: {et}\ndata: {event_json}\n\n"


@router.get("/events")
def events(
           session_id: str = Query(default="default")):
    sid = session_id or "default"
    sub_id, q = event_bus.subscribe(sid)

    def gen():
        try:
            hello = json.dumps(
                {"type": "connected", "session_id": sid}, ensure_ascii=False
            )
            yield _sse_pack(hello)

            while True:
                try:
                    data = q.get(timeout=15)
                    yield _sse_pack(data)
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            event_bus.unsubscribe(sid, sub_id)

    async def event_generator():
        # SSE 需要这些 CORS 头
        yield {
            "event": "",
            "data": "",
            "comment": "cors headers",
            "headers": {
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        }
        async for chunk in gen():
            yield {"event": "", "data": chunk, "comment": ""}

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    })


# ---------------- helpers ----------------
def _is_under_root(path: str, root: str) -> bool:
    ap = os.path.abspath(path)
    ar = os.path.abspath(root)
    try:
        return os.path.commonpath([ap, ar]) == ar
    except Exception:
        return False


def _inline_pdf_response(file_path: str, filename: str) -> FileResponse:
    """
    返回浏览器原生 inline 预览的 PDF 响应。
    - FileResponse (Starlette) 默认支持 Range 请求，翻页/跳页体验更好。
    - ETag + 强缓存：同一篇论文打开多次无需重新下载。
    - Accept-Ranges: bytes 让 pdf.js 能做 range fetch。
    """
    # RFC 5987 filename* (UTF-8)
    safe_name = filename or os.path.basename(file_path)
    disp = f"inline; filename*=UTF-8''{quote(safe_name)}"
    # 基于文件大小 + 修改时间生成弱 ETag；这样换文件版本（重新下载）能自动失效
    try:
        size = os.path.getsize(file_path)
        mtime = int(os.path.getmtime(file_path))
        etag = f'W/"{size:x}-{mtime:x}"'
    except Exception:
        etag = None
    headers = {
        "Content-Disposition": disp,
        # 缓存 1 天 + 允许 stale 7 天；强制重新校验（ETag/If-None-Match）
        "Cache-Control": "private, max-age=86400, stale-while-revalidate=604800, must-revalidate",
        "Accept-Ranges": "bytes",
    }
    if etag:
        headers["ETag"] = etag
    return FileResponse(file_path, media_type="application/pdf", headers=headers)


def _fetch_pdf_from_arxiv(paper_id: str, dest_path: str, timeout: float = 30.0) -> int:
    """
    按需从 arxiv.org 拉 PDF 并保存到本地（用于 view endpoint 的 fallback）。
    仅当本地 raw PDF 不存在时调用，避免每次预览都打 arxiv。

    Returns 写入的字节数。失败抛 HTTPException。
    """
    # 非 arXiv ID（DOI / OpenAlex W...）→ arxiv 必定 404，直接拒绝
    if paper_id.startswith("10.") and "/" in paper_id:
        raise HTTPException(
            status_code=404,
            detail="非 arXiv 论文（DOI 类型）无在线 PDF 可获取，请先调用下载流程或手动上传",
        )
    if paper_id.startswith("W") and paper_id[1:].isdigit():
        raise HTTPException(
            status_code=404,
            detail="OpenAlex ID 无法直接获取 PDF，请先通过下载流程抓取",
        )

    candidates = [
        f"https://arxiv.org/pdf/{paper_id}.pdf",
        f"https://arxiv.org/pdf/{paper_id}",
    ]
    last_err: Optional[str] = None
    for url in candidates:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "AgenticArxiv/1.0 (+https://arxiv.org)",
                    "Accept": "application/pdf,*/*;q=0.5",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # 仅当 Content-Type 是 PDF 或 URL 看起来是 PDF 才接受
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "pdf" not in ctype and "octet-stream" not in ctype:
                    last_err = f"unexpected Content-Type: {ctype}"
                    continue
                # 原子写入：先写临时文件再 rename，避免半截文件
                tmp_dir = os.path.dirname(dest_path) or "."
                fd, tmp_path = tempfile.mkstemp(prefix=".pdf_dl_", dir=tmp_dir)
                try:
                    with os.fdopen(fd, "wb") as f:
                        total = 0
                        chunk = 64 * 1024
                        while True:
                            buf = resp.read(chunk)
                            if not buf:
                                break
                            f.write(buf)
                            total += len(buf)
                            # 简单 sanity check：超过 200MB 放弃
                            if total > 200 * 1024 * 1024:
                                raise HTTPException(
                                    status_code=413,
                                    detail="PDF 文件过大 (>200MB)，拒绝下载",
                                )
                    if total < 1024:
                        # 太小，基本不是真 PDF（可能是 HTML 错误页）
                        raise HTTPException(
                            status_code=502,
                            detail=f"arxiv 返回内容过小 ({total}B)，疑似非 PDF",
                        )
                    os.replace(tmp_path, dest_path)
                    return total
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
                    raise
        except HTTPException:
            raise
        except (URLError, HTTPError, TimeoutError) as e:
            last_err = f"{type(e).__name__}: {e}"
            continue
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue
    raise HTTPException(
        status_code=502,
        detail=f"无法从 arxiv 获取 PDF：{last_err or 'unknown error'}",
    )


def _has_active_task_for_paper(paper_id: str) -> bool:
    tasks = store.list_tasks(session_id=None, limit=10000)
    for t in tasks:
        if t.paper_id == paper_id and t.status in ("PENDING", "RUNNING"):
            return True
    return False


def _safe_remove_file(
    path: Optional[str], root: str, deleted: List[str], warnings: List[str]
) -> None:
    if not path:
        return
    ap = os.path.abspath(path)
    if not _is_under_root(ap, root):
        raise HTTPException(
            status_code=400, detail=f"拒绝删除：路径不在允许目录内: {ap}"
        )
    if not os.path.exists(ap):
        return
    try:
        if os.path.isdir(ap):
            raise HTTPException(
                status_code=400, detail=f"拒绝删除目录（仅允许文件）: {ap}"
            )
        os.remove(ap)
        deleted.append(ap)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除文件失败: {ap}, err={e}")


def _require_pdf(paper_id: str) -> None:
    """PDF/总结/RAG 相关操作只允许已下载的论文。"""
    asset = store.get_pdf_asset(paper_id)
    if not asset or asset.status not in ("READY", "STALE"):
        raise HTTPException(status_code=404, detail=f"论文 {paper_id} 尚未下载")


# ---------------- basic ----------------
@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/tools", response_model=ListToolsResponse)
def list_tools() -> ListToolsResponse:
    tools = registry.list_tools()
    return ListToolsResponse(tools=[ToolInfo(**t) for t in tools])


@router.post("/tools/execute", response_model=ExecuteToolResponse)
def execute_tool(req: ExecuteToolRequest) -> ExecuteToolResponse:
    try:
        args = dict(req.args or {})
        result = registry.execute_tool(req.name, args)
        return ExecuteToolResponse(name=req.name, result=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"工具执行失败: {str(e)}")


@router.post("/arxiv/recent", response_model=ArxivRecentResponse)
def arxiv_recent(req: ArxivRecentRequest) -> ArxivRecentResponse:
    tool_name = "get_recently_submitted_cs_papers"

    args: Dict[str, Any] = {
        "max_results": req.max_results,
        "aspect": req.aspect,
        "days": req.days,
        "save_to_file": req.save_to_file,
    }
    if req.output_path is not None:
        args["output_path"] = req.output_path

    try:
        result = registry.execute_tool(tool_name, args)
        if not isinstance(result, list):
            raise RuntimeError(f"工具返回类型异常: {type(result)}")

        papers_obj = [Paper(**p) for p in result]
        store.set_last_papers(req.session_id, papers_obj)

        return ArxivRecentResponse(
            session_id=req.session_id,
            count=len(papers_obj),
            papers=papers_obj,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取论文失败: {str(e)}")


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions() -> SessionListResponse:
    sessions = store.list_session_ids()
    return SessionListResponse(sessions=sessions)


@router.get("/sessions/{session_id}/papers", response_model=SessionPapersResponse)
def get_session_papers(session_id: str) -> SessionPapersResponse:
    papers = store.get_last_papers(session_id)
    return SessionPapersResponse(session_id=session_id, papers=papers)


@router.get("/sessions/{session_id}/papers/subscription", response_model=SessionPapersResponse)
def get_session_subscription_papers(session_id: str) -> SessionPapersResponse:
    papers = store.get_subscription_papers(session_id)
    return SessionPapersResponse(session_id=session_id, papers=papers)


class RemoveSessionPapersResponse(BaseModel):
    session_id: str
    fetch_type: str
    paper_ids: List[str]
    removed_count: int


@router.delete(
    "/sessions/{session_id}/papers",
    response_model=RemoveSessionPapersResponse,
)
def remove_session_papers(
    session_id: str,
    paper_ids: List[str] = Query(
        ...,
        description="要删除的 paper_id 列表（支持单个或批量）",
    ),
    fetch_type: Literal["manual", "subscription"] = Query(
        default="manual",
        description="manual=会话论文；subscription=订阅论文",
    ),
) -> RemoveSessionPapersResponse:
    """删除 session 中指定论文。"""
    unique_ids = [pid for pid in dict.fromkeys(paper_ids) if pid]
    if not unique_ids:
        return RemoveSessionPapersResponse(
            session_id=session_id,
            fetch_type=fetch_type,
            paper_ids=[],
            removed_count=0,
        )
    removed = store.remove_session_papers(session_id, unique_ids, fetch_type)
    return RemoveSessionPapersResponse(
        session_id=session_id,
        fetch_type=fetch_type,
        paper_ids=unique_ids,
        removed_count=removed,
    )


@router.get("/papers/subscription", response_model=SessionPapersResponse)
def get_all_subscription_papers() -> SessionPapersResponse:
    papers = store.get_all_subscription_papers()
    return SessionPapersResponse(session_id="all", papers=papers)


# ---------------- translate tasks (create -> auto-run) ----------------
@router.post("/translate/tasks", response_model=CreateTranslateTaskResponse)
def create_translate_task(
    req: CreateTranslateTaskRequest,
) -> CreateTranslateTaskResponse:
    try:
        t = translate_runner.enqueue(
            session_id=req.session_id,
            ref=req.ref,
            force=req.force,
            service=req.service,
            threads=req.threads,
            keep_dual=req.keep_dual,
        )
        return CreateTranslateTaskResponse(task=t)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建翻译任务失败: {str(e)}")


@router.get("/translate/tasks/{task_id}", response_model=GetTaskResponse)
def get_translate_task(task_id: str) -> GetTaskResponse:
    t = store.get_task(task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return GetTaskResponse(task=t)


# ---------------- agent ----------------
@router.post("/agent/run", response_model=AgentRunResponse)
def run_agent(req: AgentRunRequest) -> AgentRunResponse:
    try:
        from utils.llm_client import get_app_llm_client
        from services.app_settings import get_llm_config
        from agents.agent_engine import ReActAgent

        # 使用系统的 LLM 配置（用户未配置时回落到系统默认）
        llm_client = get_app_llm_client()
        user_cfg = get_llm_config()
        # 如果请求没有指定 agent_model，则使用用户配置的 model
        agent_model = req.agent_model or user_cfg.model

        agent = ReActAgent(llm_client)
        result = agent.run(
            task=req.task,
            agent_model=agent_model,
            session_id=req.session_id,
        )
        return AgentRunResponse(**result)
    except Exception as e:
        log.error(f"Agent运行失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Agent运行失败: {str(e)}")


# ---------------- pdf download ----------------
@router.post("/pdf/download", response_model=DownloadPdfResponse)
def pdf_download(req: DownloadPdfRequest) -> DownloadPdfResponse:
    tool_name = "download_arxiv_pdf"
    try:
        # download_arxiv_pdf 工具会自行 set_last_active / set_last_papers；
        # 工具内部会读写全局 session / 资产状态
        result = registry.execute_tool(
            tool_name,
            {
                "session_id": req.session_id,
                "ref": req.ref,
                "paper_id": req.paper_id,
                "force": req.force,
            },
        )
        if not isinstance(result, dict):
            raise RuntimeError(f"工具返回类型异常: {type(result)}")
        return DownloadPdfResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载PDF失败: {str(e)}")


# ---------------- pdf upload ----------------
from utils.pdf_downloader import (
    safe_filename as _safe_filename,
    acquire_lock as _acquire_lock,
    release_lock as _release_lock,
)


@router.post("/pdf/upload", response_model=UploadPdfResponse)
async def pdf_upload(
    paper_id: str = Query(..., description="论文 ID（DOI / OpenAlex ID / arXiv ID）"),
    session_id: str = Query(default="default", description="会话ID"),
    file: UploadFile = File(..., description="要上传的 PDF 文件"),
) -> UploadPdfResponse:
    """上传用户本地的 PDF 文件，落到 settings.pdf_raw_path 并标记为 READY。

    - 文件以 safe_filename(paper_id).pdf 命名（与下载工具保持一致）
    - 校验：必须是 .pdf 后缀、且前 4 字节是 %PDF 魔术字
    - 写文件使用 .part 临时文件，避免半截写入污染磁盘
    - 上传完成后更新 pdf_asset 状态为 READY（upsert）
    - 通过 SSE 广播 pdf_status_changed 事件，前端实时刷新
    """
    sid = session_id or "default"
    pid = (paper_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="paper_id 必填")

    # 文件名校验
    original_name = (file.filename or "").lower()
    if not original_name.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 .pdf 文件")

    filename = _safe_filename(pid) + ".pdf"
    target_dir = settings.pdf_raw_path
    os.makedirs(target_dir, exist_ok=True)
    local_path = os.path.join(target_dir, filename)
    part_path = local_path + ".part"
    lock_path = local_path + ".lock"

    # 检查是否已有锁（其他任务正在处理）
    if os.path.exists(lock_path):
        raise HTTPException(status_code=409, detail="该论文存在下载/上传任务进行中，请稍后再试")

    _acquire_lock(lock_path)

    try:
        # 流式写入到 .part，避免大文件全加载到内存
        total_bytes = 0
        header_checked = False
        try:
            with open(part_path, "wb") as f:
                while True:
                    chunk = await file.read(1024 * 256)  # 256 KB
                    if not chunk:
                        break
                    if not header_checked:
                        if not chunk.startswith(b"%PDF"):
                            raise HTTPException(
                                status_code=400,
                                detail="文件内容不是有效的 PDF（缺少 %PDF 文件头）",
                            )
                        header_checked = True
                    f.write(chunk)
                    total_bytes += len(chunk)

            if total_bytes <= 0:
                raise HTTPException(status_code=400, detail="上传的文件为空")

            # 原子替换：删除旧的，rename 上去
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass
            os.replace(part_path, local_path)

            # 计算 SHA-256（用于完整性校验）
            import hashlib as _hashlib
            sha256_hex = ""
            try:
                h = _hashlib.sha256()
                with open(local_path, "rb") as f:
                    for blk in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(blk)
                sha256_hex = h.hexdigest()
            except Exception:
                sha256_hex = ""

            # 写入 pdf_asset 记录（upsert）
            from datetime import datetime as _dt
            store.upsert_pdf_asset(PdfAsset(
                paper_id=pid,
                pdf_url="",  # 用户上传，没有远程 URL
                local_path=local_path,
                status="READY",
                size_bytes=total_bytes,
                sha256=sha256_hex or None,
                downloaded_at=_dt.now(),
                error=None,
            ))

            # 标记 last_active
            store.set_last_active_paper_id(sid, pid)

            # SSE 广播
            try:
                event_bus.publish(sid, {
                    "type": "pdf_status_changed",
                    "paper_id": pid,
                    "status": "READY",
                    "size_bytes": total_bytes,
                    "source": "upload",
                })
            except Exception:
                pass

            log.info(f"[pdf_upload] success: paper_id={pid}, size={total_bytes} bytes")

            return UploadPdfResponse(
                paper_id=pid,
                local_path=local_path,
                size_bytes=total_bytes,
                sha256=sha256_hex,
                status="READY",
            )
        except HTTPException:
            # 清理半截文件
            try:
                if os.path.exists(part_path):
                    os.remove(part_path)
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                if os.path.exists(part_path):
                    os.remove(part_path)
            except Exception:
                pass
            log.error(f"[pdf_upload] failed: paper_id={pid}, err={e}")
            raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")
    finally:
        _release_lock(lock_path)


# ---------------- pdf translate (sync 保留) ----------------
@router.post("/pdf/translate", response_model=TranslatePdfResponse)
def pdf_translate(req: TranslatePdfRequest) -> TranslatePdfResponse:
    tool_name = "translate_arxiv_pdf"
    try:
        result = registry.execute_tool(
            tool_name,
            {
                "session_id": req.session_id,
                "ref": req.ref,
                "paper_id": req.paper_id,
                "force": req.force,
                "service": req.service,
                "threads": req.threads,
                "keep_dual": req.keep_dual,
            },
        )
        if not isinstance(result, dict):
            raise RuntimeError(f"工具返回类型异常: {type(result)}")
        return TranslatePdfResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"翻译PDF失败: {str(e)}")


@router.post("/pdf/translate/async", response_model=CreateTranslateTaskResponse)
def pdf_translate_async(req: TranslatePdfRequest) -> CreateTranslateTaskResponse:
    try:
        t = translate_runner.enqueue(
            session_id=req.session_id,
            ref=req.ref,
            paper_id=req.paper_id,
            force=req.force,
            service=req.service,
            api_key=req.api_key,
            threads=req.threads,
            keep_dual=req.keep_dual,
        )
        return CreateTranslateTaskResponse(task=t)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建异步翻译任务失败: {str(e)}")


# ---------------- chat ----------------
@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        from utils.llm_client import get_app_llm_client
        from services.app_settings import get_llm_config

        # 使用系统的 LLM 配置
        llm_client = get_app_llm_client()
        user_cfg = get_llm_config()
        agent_model = req.agent_model or user_cfg.model

        if req.agent_type == "mcp":
            from mcp_protocol.mcp_agent import MCPAgent
            agent = MCPAgent(llm_client)
        elif req.agent_type == "skill_cli":
            from skill_cli.skill_agent import SkillAgent
            agent = SkillAgent(llm_client)
        else:
            from agents.agent_engine import ReActAgent
            agent = ReActAgent(llm_client)

        result = agent.run(
            task=req.message,
            agent_model=agent_model,
            session_id=req.session_id,
        )

        papers = store.get_last_papers(req.session_id)
        pdf_assets = store.list_pdf_assets()
        translate_assets = store.list_translate_assets()
        tasks = store.list_tasks(session_id=req.session_id, limit=50)

        history = result.get("history", [])
        reply = ""
        # 优先采用模型在 FINISH 时给出的自然语言答复（很多模型会写成
        # "Action: FINISH" 后继续输出答案），否则回退到最后一个工具 Observation
        if history and history[-1].get("action") == "FINISH":
            text = (history[-1].get("observation") or "").strip()
            if text and text != "任务完成":
                reply = text
        if not reply:
            for step in reversed(history):
                if step.get("action") not in ("FINISH", "FORCE_STOP", "ERROR"):
                    reply = step.get("observation", "")
                    break
        reply = reply or result.get("final_observation", "")

        return ChatResponse(
            session_id=req.session_id,
            message=req.message,
            reply=reply,
            history=result.get("history", []),
            papers=papers,
            pdf_assets=list(pdf_assets),
            translate_assets=list(translate_assets),
            tasks=tasks,
            agent_type=req.agent_type,
        )
    except Exception as e:
        log.error(f"/chat 失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"chat失败: {str(e)}")


@router.get("/pdf/assets", response_model=PdfAssetsResponse)
def list_pdf_assets() -> PdfAssetsResponse:
    return PdfAssetsResponse(assets=store.list_pdf_assets())


class DiscoveredPaper(BaseModel):
    paper_id: str
    local_path: str
    size_bytes: int
    has_translation: bool = False
    translation_path: Optional[str] = None


class DiscoveredPapersResponse(BaseModel):
    papers: List[DiscoveredPaper]


@router.get("/pdf/discovered", response_model=DiscoveredPapersResponse)
def list_discovered_papers(
) -> DiscoveredPapersResponse:
    """
    扫描 pdf_raw 目录，返回本地已有 PDF 的论文列表。
    对比页面的"已下载论文"分组依赖此接口。
    """
    discovered: List[DiscoveredPaper] = []
    raw_dir = settings.pdf_raw_path
    translated_dir = settings.pdf_translated_path
    legacy_translated_dir = settings.pdf_translated_path
    if os.path.isdir(raw_dir):
        for fname in os.listdir(raw_dir):
            if not fname.endswith(".pdf"):
                continue
            paper_id = fname[:-4]  # strip ".pdf"
            local_path = os.path.join(raw_dir, fname)
            size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
            if size == 0:
                continue

            # 论文 id 可能含 / 等不安全字符（如 DOI），必须用 safe_filename 拼路径
            safe_pid = _safe_filename(paper_id)
            has_translation = False
            translation_path = None
            for base in (translated_dir, legacy_translated_dir):
                for name in (f"{safe_pid}-mono.pdf", f"{safe_pid}-zh.pdf",
                             f"{safe_pid}.pdf"):
                    cand = os.path.join(base, name)
                    if os.path.exists(cand) and os.path.getsize(cand) > 0:
                        has_translation = True
                        translation_path = cand
                        break
                if has_translation:
                    break

            discovered.append(DiscoveredPaper(
                paper_id=paper_id,
                local_path=local_path,
                size_bytes=size,
                has_translation=has_translation,
                translation_path=translation_path,
            ))

    return DiscoveredPapersResponse(papers=discovered)


@router.get("/translate/assets", response_model=TranslateAssetsResponse)
def list_translate_assets(
) -> TranslateAssetsResponse:
    return TranslateAssetsResponse(
        assets=store.list_translate_assets()
    )


# ---------------- PDF view endpoints ----------------
@router.get("/pdf/view/raw/{paper_id:path}")
def view_raw_pdf(
    paper_id: str,
    session_id: str = Query(
        default="default", description="用于更新 last_active（可选）"
    ),
):
    """
    预览已下载 raw PDF（浏览器原生 inline 打开）。

    Fallback 行为：如果本地 raw PDF 不存在（例如订阅论文尚未下载），
    会按需从 arxiv.org 拉一次并落到本地，下次就快了。
    """
    sid = session_id or "default"

    asset = store.get_pdf_asset(paper_id)
    # 允许索引缺失但文件存在：fallback 到 canonical 路径
    # paper_id 可能含 / 等字符（如 DOI），必须用 safe_filename 拼路径
    canonical = os.path.join(settings.pdf_raw_path, f"{_safe_filename(paper_id)}.pdf")
    path = asset.local_path if asset and asset.local_path else canonical

    if asset and asset.status == "FAILED":
        raise HTTPException(
            status_code=409,
            detail=f"论文 PDF 下载失败，无法预览（请前往 {asset.pdf_url or '出版社页面'} 手动下载）",
        )
    if asset and asset.status not in (None, "READY", "STALE"):
        raise HTTPException(
            status_code=409, detail=f"PDF 未处于 READY，当前状态={asset.status}"
        )
    # STALE：磁盘文件丢失（启动校验时标记），让 on-demand 下载分支兜底
    # —— 不在此处直接拒绝，确保前端能通过"按需重下"恢复可用状态

    # 本地没有 → 按需从 arxiv 拉一次（最多 30s）
    if not path or not os.path.exists(path) or os.path.getsize(path) <= 0:
        os.makedirs(settings.pdf_raw_path, exist_ok=True)
        size = _fetch_pdf_from_arxiv(paper_id, canonical)
        path = canonical
        # 重下成功：把 STALE 恢复成 READY（资产已存在但 local_path 失效）
        if asset is not None and asset.status == "STALE":
            try:
                store.update_pdf_asset(
                    paper_id,
                    local_path=path,
                    status="READY",
                    size_bytes=size,
                    error=None,
                )
            except Exception:
                pass
    else:
        # 文件已存在：若 db 状态是 STALE（例如历史脏 path/历史脏数据），恢复成 READY
        # 避免每次预览都先以"未下载"展示再点开后"恢复"的体验割裂
        if asset is not None and asset.status == "STALE":
            try:
                store.update_pdf_asset(
                    paper_id,
                    local_path=path,
                    status="READY",
                    size_bytes=os.path.getsize(path),
                    error=None,
                )
                # 更新本地 asset 引用（虽然用完不返回给调用方，但保持一致）
                asset.status = "READY"
            except Exception:
                pass

    if not _is_under_root(path, settings.pdf_raw_path):
        raise HTTPException(status_code=400, detail="拒绝预览：文件不在允许目录内")

    # 顺手把 asset 注册一下，后续 pdf/assets 列表里能看到
    if not asset:
        try:
            store.update_pdf_asset(
                paper_id=paper_id,
                local_path=path,
                status="READY",
                size_bytes=os.path.getsize(path),
                updated_at=None,  # 让 store 自己填
            )
        except Exception:
            # update_pdf_asset 只在已有 row 时工作；如果 row 不存在则不阻断预览
            pass

    # 更新 last_active（预览也算一次操作）
    store.set_last_active_paper_id(sid, paper_id)

    filename = f"{paper_id}.pdf"
    return _inline_pdf_response(path, filename)


@router.get("/pdf/view/translated/{paper_id:path}")
def view_translated_pdf(
    paper_id: str,
    variant: Literal["mono", "dual"] = Query(default="mono"),
    session_id: str = Query(
        default="default", description="用于更新 last_active（可选）"
    ),
):
    """
    预览已翻译 PDF（默认 mono；若保留 dual 可用 variant=dual）
    """
    sid = session_id or "default"

    asset = store.get_translate_asset(paper_id)
    if asset and asset.status not in ("READY", "STALE"):
        raise HTTPException(
            status_code=409, detail=f"翻译未处于 READY，当前状态={asset.status}"
        )

    # 路径选择：优先读索引；索引缺失时 fallback 到 canonical
    # paper_id 可能含 / 等字符（如 DOI），必须用 safe_filename 拼路径
    safe_pid = _safe_filename(paper_id)
    mono_canonical = os.path.join(settings.pdf_translated_path, f"{safe_pid}-mono.pdf")
    dual_canonical = os.path.join(settings.pdf_translated_path, f"{safe_pid}-dual.pdf")

    if variant == "dual":
        path = (
            asset.output_dual_path
            if asset and asset.output_dual_path
            else dual_canonical
        )
        filename = f"{paper_id}-dual.pdf"
    else:
        path = (
            asset.output_mono_path
            if asset and asset.output_mono_path
            else mono_canonical
        )
        filename = f"{paper_id}-mono.pdf"

    if not path or not os.path.exists(path) or os.path.getsize(path) <= 0:
        raise HTTPException(status_code=404, detail="translated PDF 文件不存在")

    if not _is_under_root(path, settings.pdf_translated_path):
        raise HTTPException(status_code=400, detail="拒绝预览：文件不在允许目录内")

    store.set_last_active_paper_id(sid, paper_id)
    return _inline_pdf_response(path, filename)


# ---------------- delete endpoints (你已实现的删除功能保持不变) ----------------
@router.delete("/pdf/assets/{paper_id:path}", response_model=DeleteAssetResponse)
def delete_pdf_asset(
    paper_id: str,
    session_id: str = Query(
        default="default", description="用于 SSE 广播删除事件（可选）"
    ),
) -> DeleteAssetResponse:
    sid = session_id or "default"
    asset = store.get_pdf_asset(paper_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="pdf asset 不存在")
    if asset.status == "DOWNLOADING" or store.has_active_task_for_paper(paper_id):
        raise HTTPException(
            status_code=409, detail="该论文存在下载/翻译任务进行中，暂不可删除"
        )

    local_path = asset.local_path
    lock_path = (local_path or "") + ".lock"
    part_path = (local_path or "") + ".part"

    if lock_path and os.path.exists(lock_path):
        raise HTTPException(
            status_code=409, detail="检测到锁文件，可能仍在下载/处理中，暂不可删除"
        )

    deleted_files: List[str] = []
    warnings: List[str] = []

    _safe_remove_file(local_path, settings.pdf_raw_path, deleted_files, warnings)
    _safe_remove_file(part_path, settings.pdf_raw_path, deleted_files, warnings)
    _safe_remove_file(lock_path, settings.pdf_raw_path, deleted_files, warnings)

    removed_cache = store.delete_pdf_asset(paper_id)

    try:
        event_bus.publish(sid,
            {
                "type": "asset_deleted",
                "kind": "pdf",
                "paper_id": paper_id,
                "deleted_files": deleted_files,
            },
        )
    except Exception:
        pass

    return DeleteAssetResponse(
        kind="pdf",
        paper_id=paper_id,
        removed_cache=bool(removed_cache),
        deleted_files=deleted_files,
        warnings=warnings,
        message="已删除",
    )


@router.delete("/translate/assets/{paper_id:path}", response_model=DeleteAssetResponse)
def delete_translate_asset(
    paper_id: str,
    session_id: str = Query(
        default="default", description="用于 SSE 广播删除事件（可选）"
    ),
) -> DeleteAssetResponse:
    sid = session_id or "default"
    asset = store.get_translate_asset(paper_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="translate asset 不存在")

    if asset.status == "TRANSLATING" or store.has_active_task_for_paper(paper_id):
        raise HTTPException(
            status_code=409, detail="该论文存在翻译任务进行中，暂不可删除"
        )

    mono_path = asset.output_mono_path
    dual_path = asset.output_dual_path
    mono_lock = (mono_path or "") + ".lock"
    # paper_id 可能含 / 等字符（如 DOI），必须用 safe_filename 拼路径
    log_path = os.path.join(
        settings.pdf_translated_log_path,
        f"{_safe_filename(paper_id)}.pdf2zh.log",
    )

    if mono_lock and os.path.exists(mono_lock):
        raise HTTPException(
            status_code=409, detail="检测到锁文件，可能仍在翻译/处理中，暂不可删除"
        )

    deleted_files: List[str] = []
    warnings: List[str] = []

    # 历史共享文件可能被多条记录指向：只有独占该路径时才删文件
    shared = store.count_translate_path_refs(mono_path or "")
    if shared <= 1:
        _safe_remove_file(
            mono_path, settings.pdf_translated_path, deleted_files, warnings
        )
        if dual_path:
            _safe_remove_file(
                dual_path, settings.pdf_translated_path, deleted_files, warnings
            )
        _safe_remove_file(
            mono_lock, settings.pdf_translated_path, deleted_files, warnings
        )
    else:
        warnings.append(
            f"该译文文件仍被 {shared - 1} 条其他记录引用，文件保留"
        )

    _safe_remove_file(
        log_path, settings.pdf_translated_log_path, deleted_files, warnings
    )

    removed_cache = store.delete_translate_asset(paper_id)

    try:
        event_bus.publish(sid,
            {
                "type": "asset_deleted",
                "kind": "translate",
                "paper_id": paper_id,
                "deleted_files": deleted_files,
            },
        )
    except Exception:
        pass

    return DeleteAssetResponse(
        kind="translate",
        paper_id=paper_id,
        removed_cache=bool(removed_cache),
        deleted_files=deleted_files,
        warnings=warnings,
        message="已删除译文",
    )


# ---------------- logs ----------------

class LogSessionsResponse(BaseModel):
    sessions: List[LogSessionSummary]


class LogMessagesResponse(BaseModel):
    messages: List[ChatLogItem]


class LogStepsResponse(BaseModel):
    steps: List[AgentStepItem]


@router.get("/logs/sessions", response_model=LogSessionsResponse)
def get_log_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LogSessionsResponse:
    return LogSessionsResponse(sessions=log_service.list_sessions(limit, offset))


@router.get("/logs/sessions/{session_id}/messages", response_model=LogMessagesResponse)
def get_log_messages(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> LogMessagesResponse:
    return LogMessagesResponse(messages=log_service.list_messages(session_id, limit, offset))


@router.get("/logs/messages/{msg_id}/steps", response_model=LogStepsResponse)
def get_log_steps(
    msg_id: str,
) -> LogStepsResponse:
    return LogStepsResponse(steps=log_service.get_steps(msg_id))


# ---------------- subscription endpoints ----------------
from scheduler.runner import get_scheduler
from scheduler.subscription import Subscription


class SubscriptionResponse(BaseModel):
    id: str
    name: str
    aspects: List[str]
    keywords: List[str]
    exclude_keywords: List[str]
    days: int
    max_results: int
    enabled: bool
    session_id: str
    match_mode: str = "any"
    interval_minutes: Optional[int] = None
    last_run_at: Optional[str] = None
    last_run_count: int = 0
    created_at: str


class SubscriptionResultResponse(BaseModel):
    subscription_id: str
    subscription_name: str
    papers_count: int
    new_papers_count: int
    duration_ms: int
    errors: List[str] = Field(default_factory=list)
    run_at: str


class CreateSubscriptionRequest(BaseModel):
    id: Optional[str] = Field(default=None, description="订阅 ID，为空则自动生成")
    name: str = Field(..., description="订阅名称")
    aspects: List[str] = Field(default_factory=list, description="分类列表")
    keywords: List[str] = Field(default_factory=list, description="关键词列表")
    exclude_keywords: List[str] = Field(default_factory=list, description="排除关键词")
    match_mode: str = Field(default="any", pattern="^(any|all)$",
                            description="关键词匹配模式: any | all")
    days: int = Field(default=7, ge=1, le=30)
    max_results: int = Field(default=15, ge=1, le=100)
    enabled: bool = Field(default=True)
    session_id: str = Field(default="default")
    interval_minutes: Optional[int] = Field(default=None, ge=1, le=10080)


class UpdateSubscriptionRequest(BaseModel):
    name: Optional[str] = None
    aspects: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    exclude_keywords: Optional[List[str]] = None
    match_mode: Optional[str] = Field(default=None, pattern="^(any|all)$")
    days: Optional[int] = None
    max_results: Optional[int] = None
    enabled: Optional[bool] = None
    # 显式传 null 表示"改为仅手动"，所以这里不能把 None 当成"未提供"
    interval_minutes: Optional[int] = Field(default=None, ge=1, le=10080)


def _sub_to_response(sub: Subscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=sub.id,
        name=sub.name,
        aspects=sub.aspects,
        keywords=sub.keywords,
        exclude_keywords=sub.exclude_keywords,
        days=sub.days,
        max_results=sub.max_results,
        enabled=sub.enabled,
        session_id=sub.session_id,
        match_mode=getattr(sub, "match_mode", "any") or "any",
        interval_minutes=sub.interval_minutes,
        last_run_at=sub.last_run_at.isoformat() if sub.last_run_at else None,
        last_run_count=sub.last_run_count,
        created_at=sub.created_at.isoformat(),
    )


def _result_to_response(result) -> SubscriptionResultResponse:
    return SubscriptionResultResponse(
        subscription_id=result.subscription_id,
        subscription_name=result.subscription_name,
        papers_count=result.papers_count,
        new_papers_count=result.new_papers_count,
        duration_ms=result.duration_ms,
        errors=result.errors,
        run_at=result.run_at.isoformat() if hasattr(result, 'run_at') else None,
    )


@router.get("/subscriptions", response_model=List[SubscriptionResponse])
def list_subscriptions() -> List[SubscriptionResponse]:
    """列出系统的所有订阅"""
    scheduler = get_scheduler()
    return [_sub_to_response(sub) for sub in scheduler.get_subscriptions()]


@router.post("/subscriptions", response_model=SubscriptionResponse)
def create_subscription(req: CreateSubscriptionRequest) -> SubscriptionResponse:
    """创建新订阅"""
    sub = Subscription(
        id=req.id,
        name=req.name,
        aspects=req.aspects,
        keywords=req.keywords,
        exclude_keywords=req.exclude_keywords,
        days=req.days,
        max_results=req.max_results,
        enabled=req.enabled,
        session_id=req.session_id,
        match_mode=req.match_mode,
        interval_minutes=req.interval_minutes,
    )
    scheduler = get_scheduler()
    scheduler.add_subscription(sub)
    return _sub_to_response(sub)


@router.get("/subscriptions/{sub_id}", response_model=SubscriptionResponse)
def get_subscription(sub_id: str) -> SubscriptionResponse:
    """获取系统的单个订阅"""
    scheduler = get_scheduler()
    sub = scheduler.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return _sub_to_response(sub)


@router.patch("/subscriptions/{sub_id}", response_model=SubscriptionResponse)
def update_subscription(
    sub_id: str,
    req: UpdateSubscriptionRequest,
) -> SubscriptionResponse:
    """更新订阅配置"""
    scheduler = get_scheduler()
    provided = req.model_dump(exclude_unset=True)
    # interval_minutes 允许显式 null（清除自动间隔），其余 None 视为未提供
    kwargs = {
        k: v for k, v in provided.items()
        if v is not None or k == "interval_minutes"
    }
    sub = scheduler.update_subscription(sub_id, **kwargs)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return _sub_to_response(sub)


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: str) -> dict:
    """删除订阅"""
    scheduler = get_scheduler()
    if not scheduler.remove_subscription(sub_id):
        raise HTTPException(status_code=404, detail="订阅不存在")
    return {"status": "deleted", "id": sub_id}


@router.post("/subscriptions/{sub_id}/run", response_model=SubscriptionResultResponse)
def run_subscription(sub_id: str) -> SubscriptionResultResponse:
    """手动触发订阅执行"""
    scheduler = get_scheduler()
    result = scheduler.run_subscription(sub_id)
    if not result:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return _result_to_response(result)


@router.post("/subscriptions/run-all", response_model=List[SubscriptionResultResponse])
def run_all_subscriptions() -> List[SubscriptionResultResponse]:
    """触发系统的所有订阅立即执行"""
    scheduler = get_scheduler()
    results = scheduler.run_all()
    return [_result_to_response(r) for r in results]


@router.get("/subscriptions/{sub_id}/result", response_model=SubscriptionResultResponse)
def get_subscription_result(sub_id: str) -> SubscriptionResultResponse:
    """获取订阅最近一次执行结果"""
    scheduler = get_scheduler()
    result = scheduler.get_result(sub_id)
    if not result:
        raise HTTPException(status_code=404, detail="无执行记录")
    return _result_to_response(result)


# ---------------- paper summary ----------------
from services.paper_summary_service import paper_summary_service
from models.schemas import PaperSummary


class PaperSummaryResponse(BaseModel):
    paper_id: str
    status: str
    background: Optional[str] = None
    innovation: Optional[str] = None
    summarized_at: Optional[str] = None
    error: Optional[str] = None


class SummarizeRequest(BaseModel):
    session_id: str = Field(default="default", description="会话ID")
    ref: str | int | None = Field(
        default=None,
        description="论文引用:1-based序号 或 arxiv id 或 title子串",
    )
    paper_id: Optional[str] = Field(default=None, description="直接指定 paper_id")
    force: bool = Field(default=False, description="是否强制重新总结")


class SummarizeResponse(BaseModel):
    summary: PaperSummaryResponse
    message: str


@router.get("/summary/assets", response_model=List[PaperSummaryResponse])
def list_summary_assets(
) -> List[PaperSummaryResponse]:
    """列出系统已下载论文的总结"""
    summaries = paper_summary_service.list_summaries()
    return [
        PaperSummaryResponse(
            paper_id=s.paper_id,
            status=s.status,
            background=s.background,
            innovation=s.innovation,
            summarized_at=s.summarized_at.isoformat() if s.summarized_at else None,
            error=s.error,
        )
        for s in summaries
    ]


@router.get("/summary/assets/{paper_id:path}", response_model=PaperSummaryResponse)
def get_summary_asset(
    paper_id: str,
) -> PaperSummaryResponse:
    """获取指定论文的总结"""
    summary = paper_summary_service.get_summary(paper_id)
    if not summary:
        raise HTTPException(status_code=404, detail="该论文暂无总结")
    return PaperSummaryResponse(
        paper_id=summary.paper_id,
        status=summary.status,
        background=summary.background,
        innovation=summary.innovation,
        summarized_at=summary.summarized_at.isoformat() if summary.summarized_at else None,
        error=summary.error,
    )


@router.post("/pdf/summarize", response_model=SummarizeResponse)
def summarize_paper(req: SummarizeRequest) -> SummarizeResponse:
    """
    对论文进行 AI 总结（背景 + 创新点）

    支持三种入口：
    1) paper_id 直接指定
    2) ref 指定序号/id/标题
    3) session_id + last_active
    """
    from utils.pdf_text_extractor import extract_text_from_pdf

    sid = req.session_id or "default"

    # 解析 paper_id
    if not req.paper_id:
        if req.ref is not None:
            paper = store.resolve_paper(sid, ref=req.ref)
        else:
            last_id = store.get_last_active_paper_id(sid)
            if not last_id:
                raise HTTPException(
                    status_code=400,
                    detail="未找到论文：请提供 ref 或 paper_id，或先操作某篇论文",
                )
            paper = store.resolve_paper(sid, paper_id=last_id)

        if not paper:
            raise HTTPException(status_code=404, detail="未找到论文")
        paper_id = paper.id
    else:
        paper_id = req.paper_id
        paper = store.resolve_paper(sid, paper_id=paper_id)

    store.set_last_active_paper_id(sid, paper_id)

    # 检查 PDF 是否已下载
    _require_pdf(paper_id)
    pdf_asset = store.get_pdf_asset(paper_id)
    if not pdf_asset or pdf_asset.status != "READY":
        raise HTTPException(
            status_code=400,
            detail="请先下载论文 PDF，再进行总结",
        )

    pdf_path = pdf_asset.local_path
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=400, detail=f"PDF 文件不存在: {pdf_path}")

    # 检查是否已有总结（且不强制）
    existing = paper_summary_service.get_summary(paper_id)
    if existing and existing.status == "READY" and not req.force:
        return SummarizeResponse(
            summary=PaperSummaryResponse(
                paper_id=existing.paper_id,
                status=existing.status,
                background=existing.background,
                innovation=existing.innovation,
                summarized_at=existing.summarized_at.isoformat() if existing.summarized_at else None,
                error=existing.error,
            ),
            message="使用已有总结（force=true 可重新总结）",
        )

    # 更新状态为 SUMMARIZING
    paper_summary_service.update_summary(paper_id, status="SUMMARIZING")

    try:
        # 提取 PDF 文本
        log.info(f"正在提取 PDF 文本: {paper_id}")
        pdf_text = extract_text_from_pdf(pdf_path, max_chars=8000)

        # 构建 prompt
        paper_title = paper.title if paper else paper_id
        prompt = f"""请分析以下学术论文，提取并总结：

1. **研究背景**：该论文要解决什么问题？研究领域是什么？有什么重要性？

2. **主要创新点**：该论文提出了什么新方法/新观点/新贡献？与现有工作相比有何优势？

请用简洁专业的语言回答，中文回答。

---论文信息---
标题：{paper_title}
内容：
{pdf_text}

---请按以下格式输出---
## 研究背景
[你的总结]

## 主要创新点
[你的总结]
"""

        # 调用 LLM
        log.info(f"正在调用 LLM 总结论文: {paper_id}")
        from utils.llm_client import get_app_llm_client
        from services.app_settings import get_llm_config
        from utils.llm_client import _default_model_for

        # 使用系统的 LLM 配置（base_url/api_key）
        llm_client = get_app_llm_client()
        user_cfg = get_llm_config()
        # 1) 优先 LLM_MODEL 环境变量
        # 2) 用户 DB 配置
        # 3) 系统默认 (settings.models.agent_model)
        # 4) 按 base_url 推断
        import os as _os
        model_name = (
            _os.getenv("LLM_MODEL")
            or user_cfg.model
            or getattr(settings.models, "agent_model", None)
            or _default_model_for(_os.getenv("LLM_BASE_URL") or user_cfg.base_url)
        )
        log.info(f"LLM model for summary: {model_name}")
        resp = llm_client.chat_completions(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是一个专业的学术论文审稿人，擅长分析论文的研究背景和创新点。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        content = resp["choices"][0]["message"]["content"]

        # 解析背景和创新点
        background = ""
        innovation = ""

        if "## 研究背景" in content:
            parts = content.split("## 研究背景")
            if len(parts) > 1:
                remaining = parts[1]
                if "## 主要创新点" in remaining:
                    bg_parts = remaining.split("## 主要创新点")
                    background = bg_parts[0].strip()
                    innovation = bg_parts[1].strip() if len(bg_parts) > 1 else ""
                else:
                    background = remaining.strip()
        elif "## 主要创新点" in content:
            parts = content.split("## 主要创新点")
            innovation = parts[1].strip() if len(parts) > 1 else ""
        else:
            # 尝试按段落分割
            lines = content.split("\n")
            if len(lines) > 4:
                background = "\n".join(lines[: len(lines) // 2])
                innovation = "\n".join(lines[len(lines) // 2 :])

        # 保存总结
        summary = paper_summary_service.update_summary(
            paper_id,
            status="READY",
            background=background,
            innovation=innovation,
        )

        return SummarizeResponse(
            summary=PaperSummaryResponse(
                paper_id=summary.paper_id,
                status=summary.status,
                background=summary.background,
                innovation=summary.innovation,
                summarized_at=summary.summarized_at.isoformat() if summary.summarized_at else None,
                error=summary.error,
            ),
            message="总结完成",
        )

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        log.error(f"论文总结失败: {paper_id}, error={error_msg}")
        paper_summary_service.update_summary(paper_id, status="FAILED", error=error_msg)
        raise HTTPException(status_code=500, detail=f"总结失败: {error_msg}")


# =============================================================================
# Paper Comparison API Endpoints
# =============================================================================

from services.paper_comparison_service import paper_comparison_service


class CreateComparisonRequest(BaseModel):
    session_id: str = Field(default="default", description="会话ID")
    paper_ids: List[str] = Field(..., description="要对比的论文 ID 列表 (2-10 篇)")


class CreateComparisonResponse(BaseModel):
    comparison: PaperComparison
    papers: List[Paper]


class ComparisonResultResponse(BaseModel):
    comparison: PaperComparison
    papers: List[Paper]
    report: Optional[ComparisonReport]
    message: str = ""


class ComparisonListResponse(BaseModel):
    comparisons: List[PaperComparison]
    total: int


@router.post("/comparison/create", response_model=CreateComparisonResponse)
async def create_comparison(req: CreateComparisonRequest):
    """
    创建新的论文对比会话

    - 从系统 session 的论文中选择 2-10 篇进行对比
    - 返回创建的对比会话和论文详情
    """
    try:
        comparison = paper_comparison_service.create_comparison(
            session_id=req.session_id,
            paper_ids=req.paper_ids,
        )
        papers = paper_comparison_service.get_papers_for_comparison(req.paper_ids)

        log.info(f"创建对比会话: {comparison.comparison_id}, 论文数: {len(papers)}")
        return CreateComparisonResponse(
            comparison=comparison,
            papers=papers,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"创建对比会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/comparison/{comparison_id}", response_model=ComparisonResultResponse)
async def get_comparison_result(comparison_id: str):
    """
    获取对比结果

    - 返回对比会话、论文详情和对比报告
    - 如果对比尚未完成，报告部分为空
    """
    try:
        result = paper_comparison_service.get_comparison_with_report(comparison_id)
        if not result:
            raise HTTPException(status_code=404, detail="对比会话不存在")

        message = ""
        if result.comparison.status == "PENDING":
            message = "对比任务待执行"
        elif result.comparison.status == "RUNNING":
            message = "对比任务进行中"
        elif result.comparison.status == "FAILED":
            message = f"对比失败: {result.comparison.error}"
        elif result.comparison.status == "SUCCEEDED":
            message = "对比完成"

        return ComparisonResultResponse(
            comparison=result.comparison,
            papers=result.papers,
            report=result.report,
            message=message,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"获取对比结果失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/comparison/{comparison_id}/status")
async def get_comparison_status(comparison_id: str):
    """获取对比状态（轻量级接口；）"""
    comparison = paper_comparison_service.get_comparison(comparison_id)
    if not comparison:
        raise HTTPException(status_code=404, detail="对比会话不存在")
    return {
        "comparison_id": comparison.comparison_id,
        "status": comparison.status,
        "paper_count": len(comparison.paper_ids),
        "created_at": comparison.created_at.isoformat(),
        "updated_at": comparison.updated_at.isoformat(),
        "error": comparison.error,
    }


@router.get("/comparisons", response_model=ComparisonListResponse)
async def list_comparisons(
    session_id: str = Query(default="default", description="会话ID"),
    limit: int = Query(default=20, ge=1, le=100, description="返回数量"),
):
    """
    列出系统的对比会话

    - 按创建时间倒序排列
    - 可指定 session_id 过滤
    """
    comparisons = paper_comparison_service.list_comparisons(
        session_id=session_id,
        limit=limit,
    )
    return ComparisonListResponse(
        comparisons=comparisons,
        total=len(comparisons),
    )


@router.post("/comparison/{comparison_id}/papers")
async def add_papers_to_comparison(
    comparison_id: str,
    paper_ids: List[str] = Body(..., description="要添加的论文 ID 列表"),
):
    """
    向现有对比添加论文

    - 总论文数需保持在 2-10 篇
    """
    try:
        comparison = paper_comparison_service.add_papers_to_comparison(
            comparison_id=comparison_id,
            paper_ids=paper_ids,
        )
        if not comparison:
            raise HTTPException(status_code=404, detail="对比会话不存在")
        return {"comparison": comparison, "message": "论文添加成功"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"添加论文到对比失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/comparison/{comparison_id}")
async def delete_comparison(comparison_id: str):
    """删除对比会话"""
    success = paper_comparison_service.delete_comparison(comparison_id)
    if not success:
        raise HTTPException(status_code=404, detail="对比会话不存在")
    return {"message": "对比会话已删除", "comparison_id": comparison_id}


class ExecuteComparisonRequest(BaseModel):
    """执行对比的请求"""
    dimensions: Optional[List[str]] = Field(
        default=None,
        description="要分析的维度列表，默认 [方法论, 性能表现, 创新点]",
    )
    async_mode: bool = Field(
        default=True,
        description="是否异步执行，默认 True（后台运行）",
    )


@router.post("/comparison/{comparison_id}/execute")
async def execute_comparison(
    comparison_id: str,
    req: ExecuteComparisonRequest = ExecuteComparisonRequest(),
):
    """
    触发论文对比分析

    - 默认异步执行，在后台线程中运行
    - 同步执行适合短文本对比（2-3 篇论文）
    """
    try:
        comparison = paper_comparison_service.get_comparison(comparison_id)
        if not comparison:
            raise HTTPException(status_code=404, detail="对比会话不存在")

        if comparison.status in ("RUNNING",):
            return {
                "message": "对比正在进行中",
                "comparison_id": comparison_id,
                "status": comparison.status,
            }

        papers = paper_comparison_service.get_papers_for_comparison(comparison.paper_ids)
        if len(papers) < 2:
            raise HTTPException(status_code=400, detail="至少需要 2 篇论文")

        if req.async_mode:
            paper_comparison_service.execute_comparison_async(
                comparison_id=comparison_id,
                dimensions=req.dimensions,
            )
            return {
                "message": "对比任务已启动（异步执行）",
                "comparison_id": comparison_id,
                "status": "RUNNING",
            }
        else:
            success = paper_comparison_service.execute_comparison(
                comparison_id=comparison_id,
                dimensions=req.dimensions,
            )
            if success:
                result = paper_comparison_service.get_comparison_with_report(comparison_id)
                return {
                    "message": "对比完成",
                    "comparison_id": comparison_id,
                    "status": "SUCCEEDED",
                    "result": {
                        "comparison": result.comparison,
                        "papers": result.papers,
                        "report": result.report,
                    } if result else None,
                }
            else:
                raise HTTPException(status_code=500, detail="对比执行失败")

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"执行对比失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# RAG Paper QA API Endpoints
# =============================================================================

import threading as _rag_threading


class RagAskRequest(BaseModel):
    session_id: str = Field(default="default", description="会话ID")
    paper_id: str = Field(..., description="arXiv 论文短 ID")
    question: str = Field(..., description="用户问题")
    top_k: int = Field(default=5, ge=1, le=10, description="检索段落数")
    force_reindex: bool = Field(default=False, description="是否强制重新索引")
    include_annotations: bool = Field(
        default=True,
        description="是否把当前 session 的相关批注作为上下文",
    )
    # --- PDF 选区上下文（用户在 PDF 中拖选文字后提问时附带） ---
    selected_text: Optional[str] = Field(
        default=None,
        description="用户在 PDF 中拖选出的原文片段（必须注入到 prompt 上下文顶部）",
    )
    selected_page: Optional[int] = Field(
        default=None,
        description="选中片段所在的 PDF 页码（用于定位 chunk）",
    )


class RagAskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    annotations_used: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="实际注入到上下文的高相关批注列表",
    )
    confidence: str
    chunk_count: int
    indexed: bool
    indexed_new: int = 0


class RagIndexRequest(BaseModel):
    paper_id: str = Field(..., description="arXiv 论文短 ID")
    force: bool = Field(default=False, description="是否强制重建")


class RagIndexResponse(BaseModel):
    paper_id: str
    chunk_count: int
    status: str


class RagSummarizeRequest(BaseModel):
    paper_id: str = Field(..., description="arXiv 论文短 ID")
    focus: str = Field(
        default="general",
        description="general | method | experiment | conclusion | contribution",
    )
    max_length: int = Field(default=500, ge=100, le=2000)


class RagSummarizeResponse(BaseModel):
    paper_id: str
    summary: str
    focus: str


@router.post("/rag/ask", response_model=RagAskResponse)
def rag_ask(req: RagAskRequest) -> RagAskResponse:
    """
    RAG 论文问答：基于 PDF 全文回答用户问题。

    流程：
    1. 检查 PDF 是否已下载（status=READY）
    2. 若尚未索引，自动调用 index_paper_chunks（首次调用时）
    3. TF-IDF 检索 Top-K 相关段落
    4. 组装 Prompt → LLM 生成答案 + 引用
    """
    from tools.rag_tool import ask_paper

    _require_pdf(req.paper_id)

    # 调试日志：确认 selected_text 是否真的从前端传过来
    log.info(
        f"[RAG] 收到请求 paper={req.paper_id} "
        f"selected_text_len={len(req.selected_text) if req.selected_text else 0} "
        f"selected_page={req.selected_page} "
        f"question_prefix={req.question[:50]!r}"
    )

    try:
        result = ask_paper(
            paper_id=req.paper_id,
            question=req.question,
            top_k=req.top_k,
            force_reindex=req.force_reindex,
            session_id=req.session_id,
            include_annotations=req.include_annotations,
            selected_text=req.selected_text,
            selected_page=req.selected_page,
        )
    except Exception as e:
        log.error(f"[RAG] ask_paper 异常: {e}")
        raise HTTPException(status_code=500, detail=f"RAG 问答失败: {e}")

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # SSE 推送（RAG 回答完成）
    try:
        event_bus.publish(req.session_id or "default", {
            "type": "rag_answer",
            "paper_id": req.paper_id,
            "question": req.question,
            "answer": result.get("answer", ""),
            "confidence": result.get("confidence", "low"),
            "annotations_used": result.get("annotations_used", []),
        })
    except Exception:
        pass

    return RagAskResponse(
        answer=result.get("answer", ""),
        sources=result.get("sources", []),
        annotations_used=result.get("annotations_used", []),
        confidence=result.get("confidence", "low"),
        chunk_count=result.get("chunk_count", 0),
        indexed=result.get("indexed", False),
    )


@router.post("/rag/index", response_model=RagIndexResponse)
def rag_index(req: RagIndexRequest) -> RagIndexResponse:
    """
    预索引论文 PDF（异步），避免首次 ask_paper 时阻塞。
    """
    from tools.rag_tool import index_paper_chunks, reindex_paper

    _require_pdf(req.paper_id)

    pdf_asset = store.get_pdf_asset(req.paper_id)
    if not pdf_asset or pdf_asset.status != "READY":
        raise HTTPException(
            status_code=400,
            detail=f"论文 {req.paper_id} 尚未下载 PDF",
        )

    pdf_path = pdf_asset.local_path
    if not os.path.exists(pdf_path):
        raise HTTPException(
            status_code=400,
            detail=f"PDF 文件不存在: {pdf_path}",
        )

    def _do_index():
        if req.force:
            reindex_paper(req.paper_id)
        else:
            index_paper_chunks(req.paper_id, pdf_path)
        try:
            event_bus.publish(req.session_id or "default", {
                "type": "rag_indexed",
                "paper_id": req.paper_id,
                "status": "done",
            })
        except Exception:
            pass

    _rag_threading.Thread(target=_do_index, daemon=True).start()

    with get_sync_session() as s:
        from models.orm import PaperChunkRow
        count = s.query(PaperChunkRow).filter_by(paper_id=req.paper_id).count()

    return RagIndexResponse(
        paper_id=req.paper_id,
        chunk_count=count,
        status="indexing_in_background",
    )


@router.post("/rag/summarize", response_model=RagSummarizeResponse)
def rag_summarize(
    req: RagSummarizeRequest,
) -> RagSummarizeResponse:
    """RAG 论文摘要"""
    from tools.rag_tool import summarize_paper

    _require_pdf(req.paper_id)

    try:
        result = summarize_paper(
            paper_id=req.paper_id,
            focus=req.focus,
            max_length=req.max_length,
        )
    except Exception as e:
        log.error(f"[RAG] summarize_paper 异常: {e}")
        raise HTTPException(status_code=500, detail=f"RAG 摘要失败: {e}")

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return RagSummarizeResponse(
        paper_id=req.paper_id,
        summary=result.get("summary", ""),
        focus=result.get("focus", req.focus),
    )


@router.get("/rag/chunks/{paper_id:path}")
def rag_get_chunks(
    paper_id: str,
    limit: int = Query(default=20, ge=1, le=200),
):
    """查询某论文的 chunks（调试用）"""
    _require_pdf(paper_id)
    with get_sync_session() as s:
        from models.orm import PaperChunkRow
        rows = (
            s.query(PaperChunkRow)
            .filter_by(paper_id=paper_id)
            .order_by(PaperChunkRow.chunk_index)
            .limit(limit)
            .all()
        )
    return {
        "paper_id": paper_id,
        "total": len(rows),
        "chunks": [
            {
                "chunk_index": r.chunk_index,
                "page_start": r.page_start,
                "page_end": r.page_end,
                "section": r.section,
                "text_preview": r.text[:150] if r.text else "",
                "token_count": r.token_count,
            }
            for r in rows
        ],
    }


@router.get("/rag/search/{paper_id:path}")
def rag_search_chunks(
    paper_id: str,
    q: str = Query(..., description="检索 query"),
    top_k: int = Query(default=5, ge=1, le=20),
):
    """直接检索 chunks（调试用，不走 LLM）"""
    from tools.rag_tool import retrieve_chunks

    _require_pdf(paper_id)
    retrieved = retrieve_chunks(paper_id, q, top_k)
    return {"paper_id": paper_id, "query": q, "results": retrieved}


from models.db import get_sync_session


# ---------------- LLM per-user config (用户自配 LLM) ----------------
@router.get("/llm/config", response_model=LLMConfigResponse)
def get_my_llm_config() -> LLMConfigResponse:
    """获取系统的 LLM 配置（脱敏）"""
    from services.app_settings import get_llm_config
    cfg = get_llm_config()
    return LLMConfigResponse(
        base_url=cfg.base_url,
        api_key_masked=cfg.api_key_masked,
        model=cfg.model,
        is_default=cfg.is_default,
        warning=cfg.warning,
    )


@router.put("/llm/config", response_model=LLMConfigResponse)
def update_my_llm_config(
    req: LLMConfigUpdateRequest,
) -> LLMConfigResponse:
    """更新系统 LLM 配置。

    - 未提供的字段（前端没传）→ 不修改；
    - 显式传 null/空串 → 清空（回退到系统默认）；
    - 其他 → 写入。
    """
    from services.app_settings import get_llm_config, update_llm_config
    provided = req.model_dump(exclude_unset=True)  # 区分 "未传" vs "传 null"
    try:
        update_llm_config(
            base_url=provided.get("base_url", ...),
            api_key=provided.get("api_key", ...),
            model=provided.get("model", ...),
        )
    except ValueError as e:
        # 例如客户端把脱敏值（***xxxx）当成真实 Key 提交
        raise HTTPException(status_code=400, detail=str(e))
    cfg = get_llm_config()
    return LLMConfigResponse(
        base_url=cfg.base_url,
        api_key_masked=cfg.api_key_masked,
        model=cfg.model,
        is_default=cfg.is_default,
        warning=cfg.warning,
    )


@router.delete("/llm/config", response_model=LLMConfigResetResponse)
def reset_my_llm_config() -> LLMConfigResetResponse:
    """重置 LLM 配置，回退到系统默认"""
    from services.app_settings import reset_llm_config
    reset_llm_config()
    return LLMConfigResetResponse()


@router.post("/llm/test", response_model=LLMTestResponse)
def test_llm_config(
    req: LLMTestRequest,
) -> LLMTestResponse:
    """测试 LLM 配置是否可用（请求体优先 > 用户 DB > 环境变量 > 系统默认）"""
    from services.app_settings import get_llm_config
    from utils.llm_client import LLMClient
    import os as _os

    base_url = req.base_url
    api_key = req.api_key
    model = req.model

    if not base_url or not api_key or not model:
        cfg = get_llm_config()
        base_url = base_url or cfg.base_url
        api_key = api_key or cfg.api_key
        model = model or cfg.model or _os.getenv("LLM_MODEL") or settings.models.agent_model

    try:
        client = LLMClient(base_url=base_url, api_key=api_key, timeout_s=20)
        resp = client.chat_completions(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
            temperature=0,
        )
        if "choices" in resp and len(resp["choices"]) > 0:
            return LLMTestResponse(ok=True, message="LLM 配置可用")
        return LLMTestResponse(ok=False, message="响应格式异常", detail=str(resp)[:300])
    except Exception as e:
        return LLMTestResponse(ok=False, message="LLM 调用失败", detail=str(e)[:500])


@router.get("/llm/models")
def list_models() -> List[Dict[str, Any]]:
    """列出常见可用的 LLM 预设（供前端下拉用）"""
    return [
        {"id": "deepseek-chat", "label": "DeepSeek Chat", "provider": "deepseek"},
        {"id": "deepseek-flash", "label": "DeepSeek Flash（快）", "provider": "deepseek"},
        {"id": "qwen-plus", "label": "通义千问 Plus", "provider": "dashscope"},
        {"id": "qwen-turbo", "label": "通义千问 Turbo", "provider": "dashscope"},
        {"id": "qwen-max", "label": "通义千问 Max", "provider": "dashscope"},
        {"id": "gpt-4o-mini", "label": "GPT-4o mini", "provider": "openai"},
        {"id": "gpt-4o", "label": "GPT-4o", "provider": "openai"},
        {"id": "claude-3-5-sonnet-latest", "label": "Claude 3.5 Sonnet", "provider": "anthropic"},
        {"id": "gemini-1.5-pro", "label": "Gemini 1.5 Pro", "provider": "google"},
    ]


# ---------------- Translate per-user config ----------------

def _mask_key(key: str | None) -> str:
    """Key 脱敏：始终显示后 4 位（短 key 直接显示，避免 *** 无后缀）"""
    if not key:
        return ""
    return key if len(key) <= 4 else "***" + key[-4:]


def _get_translate_config() -> TranslateConfigResponse:
    """读取系统翻译配置；未配置时展示实际生效的默认引擎。"""
    from services.app_settings import get_translate_config

    cfg = get_translate_config()
    return TranslateConfigResponse(
        service=(cfg.service or "openai").split(":", 1)[0],
        api_key_masked=_mask_key(cfg.api_key),
        is_default=cfg.is_default,
    )


@router.get("/translate/config", response_model=TranslateConfigResponse)
def get_my_translate_config() -> TranslateConfigResponse:
    """获取翻译配置（脱敏）"""
    return _get_translate_config()


@router.put("/translate/config", response_model=TranslateConfigResponse)
def update_my_translate_config(
    req: TranslateConfigUpdateRequest,
) -> TranslateConfigResponse:
    """更新翻译配置。

    - service = null → 清空（回退系统默认）
    - api_key = "" → 清空
    """
    from services.app_settings import update_translate_config

    provided = req.model_dump(exclude_unset=True)
    try:
        update_translate_config(
            service=provided.get("service", ...),
            api_key=provided.get("api_key", ...),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _get_translate_config()


@router.delete("/translate/config", response_model=TranslateConfigResetResponse)
def reset_my_translate_config() -> TranslateConfigResetResponse:
    """重置翻译配置，回退到系统默认"""
    from services.app_settings import reset_translate_config

    reset_translate_config()
    return TranslateConfigResetResponse()


@router.post("/translate/test", response_model=TranslateTestResponse)
def test_translate_config(
    req: TranslateTestRequest,
) -> TranslateTestResponse:
    """
    测试翻译配置：请求体优先 > 用户 DB 配置 > 系统默认引擎。
    """
    import httpx
    from config import settings

    # 请求体优先，其次系统配置
    from services.app_settings import get_translate_config

    cfg = get_translate_config()
    service = req.service or cfg.service or (settings.pdf2zh_service or "openai").split(":", 1)[0]
    api_key = req.api_key or cfg.api_key or ""

    test_text = "Hello world"
    target_lang = "ZH"

    try:
        if service == "deepl":
            # DeepL 支持免费/付费两种 endpoint
            base = "https://api-free.deepl.com/v2/translate" if "-free" in api_key else "https://api.deepl.com/v2/translate"
            resp = httpx.post(
                base,
                data={"text": test_text, "target_lang": target_lang},
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                timeout=15,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"DeepL {resp.status_code}: {resp.text[:200]}")

        elif service == "google":
            if api_key:
                # 配了 Cloud API Key 就走官方接口
                resp = httpx.post(
                    f"https://translation.googleapis.com/language/translate/v2?key={api_key}",
                    json={"q": test_text, "target": "zh-CN", "source": "en"},
                    timeout=15,
                )
                data = resp.json()
                if resp.status_code != 200 or data.get("error"):
                    raise RuntimeError(
                        f"Google {resp.status_code}: "
                        f"{data.get('error', resp.text)[:200]}"
                    )
            else:
                # 没 Key 时测 pdf2zh 实际使用的公开接口
                resp = httpx.get(
                    "https://translate.google.com/m",
                    params={"tl": "zh-CN", "sl": "en", "q": test_text},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=15,
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"Google {resp.status_code}")

        elif service == "azure":
            if not api_key:
                raise RuntimeError("Azure Translator 需要 API Key")
            region = os.environ.get("AZURE_TRANSLATOR_REGION", "eastus")
            resp = httpx.post(
                f"https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&to=zh-Hans",
                json=[{"Text": test_text}],
                headers={
                    "Ocp-Apim-Subscription-Key": api_key,
                    "Ocp-Apim-Subscription-Region": region,
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Azure {resp.status_code}: {resp.text[:200]}")

        elif service == "openai":
            # OpenAI-compatible，需要 base_url
            base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            model = os.environ.get("TRANSLATE_MODEL", "gpt-4o-mini")
            from utils.llm_client import build_chat_completions_url
            resp = httpx.post(
                build_chat_completions_url(base_url),
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": f"Translate to {target_lang}, only output the translation:"},
                        {"role": "user", "content": test_text},
                    ],
                    "max_tokens": 100,
                },
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=20,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            translated = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if not translated:
                raise RuntimeError(f"OpenAI 返回为空: {data}")

        else:
            # bing / 默认：不需要 key，验证 pdf2zh 能识别该 service 名即可
            if not api_key:
                # bing 免费不需要 key，尝试验证 service 名合法
                import subprocess
                result = subprocess.run(
                    ["pdf2zh", "--version"], capture_output=True, text=True, timeout=5,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        "bing 翻译（无 key）验证：pdf2zh 未安装或不可用。"
                        "如需有 key 的高质量翻译，请切换 DeepL / Google / OpenAI / Azure。"
                    )

        return TranslateTestResponse(
            ok=True,
            message=f"✓ {service} 翻译配置正常",
            detail=None,
        )

    except Exception as e:
        return TranslateTestResponse(
            ok=False,
            message=f"✗ {service} 翻译失败",
            detail=str(e)[:400],
        )


# ---------------- annotations (论文批注) ----------------
# 单独文件，避免主 endpoints.py 膨胀；通过 include_router 聚合到统一 router。
from api.annotations import router as _annotations_router  # noqa: E402

router.include_router(_annotations_router)

# ---------------- paper tags & bookmarks (跨会话个人兴趣库) ----------------
from api.bookmarks import router as _bookmarks_router  # noqa: E402

router.include_router(_bookmarks_router)
