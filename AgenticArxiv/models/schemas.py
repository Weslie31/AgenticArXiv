# AgenticArxiv/models/schemas.py
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict
from datetime import datetime


class Paper(BaseModel):
    id: str
    title: str
    authors: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    published: Optional[str] = None
    updated: Optional[str] = None
    pdf_url: Optional[str] = None
    paper_url: Optional[str] = None  # 论文详情页 URL（DOI 链接 / arxiv abs / openalex）
    primary_category: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    comment: Optional[str] = None
    links: List[str] = Field(default_factory=list)
    fetched_at: Optional[datetime] = None  # 本次被检索到/写入 session 的时间
    fetch_type: str = "manual"  # 'manual' | 'subscription'


class SessionState(BaseModel):
    session_id: str
    last_papers: List[Paper] = Field(default_factory=list)
    last_active_paper_id: Optional[str] = None
    last_active_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.now)


TaskStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]


class TranslateTask(BaseModel):
    task_id: str
    session_id: str
    paper_id: str
    status: TaskStatus = "PENDING"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    progress: float = 0.0
    input_pdf_url: Optional[str] = None
    input_pdf_path: Optional[str] = None
    output_pdf_path: Optional[str] = None
    error: Optional[str] = None
    meta: Dict[str, str] = Field(default_factory=dict)


# --- PDF / Translate asset schemas (formerly in pdf_cache.py / translate_cache.py) ---

PdfAssetStatus = Literal["NOT_DOWNLOADED", "DOWNLOADING", "READY", "FAILED", "STALE"]


class PdfAsset(BaseModel):
    paper_id: str
    pdf_url: str = ""
    local_path: str = ""
    status: PdfAssetStatus = "NOT_DOWNLOADED"
    size_bytes: int = 0
    sha256: Optional[str] = None
    downloaded_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.now)
    error: Optional[str] = None


TranslateAssetStatus = Literal["NOT_TRANSLATED", "TRANSLATING", "READY", "FAILED", "STALE"]


class TranslateAsset(BaseModel):
    paper_id: str
    input_pdf_path: str = ""
    output_mono_path: str = ""
    output_dual_path: Optional[str] = None
    status: TranslateAssetStatus = "NOT_TRANSLATED"
    service: Optional[str] = None
    threads: int = 0
    translated_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.now)
    error: Optional[str] = None


# --- Paper Summary schemas ---

PaperSummaryStatus = Literal["NOT_SUMMARIZED", "SUMMARIZING", "READY", "FAILED"]


class PaperSummary(BaseModel):
    paper_id: str
    status: PaperSummaryStatus = "NOT_SUMMARIZED"
    background: Optional[str] = None  # 论文背景
    innovation: Optional[str] = None   # 创新点
    summarized_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.now)
    error: Optional[str] = None


# --- Logging schemas ---

class ChatLogItem(BaseModel):
    msg_id: str
    session_id: str
    role: str
    content: Optional[str] = None
    model: Optional[str] = None
    agent_type: Optional[str] = None
    created_at: Optional[datetime] = None


class AgentStepItem(BaseModel):
    step_index: int
    thought: Optional[str] = None
    action_name: Optional[str] = None
    action_args: Optional[str] = None
    observation: Optional[str] = None
    llm_latency_ms: Optional[int] = None
    tool_latency_ms: Optional[int] = None
    created_at: Optional[datetime] = None


class LogSessionSummary(BaseModel):
    session_id: str
    message_count: int
    last_active_at: Optional[datetime] = None


# --- Paper Comparison schemas ---

ComparisonStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]


class ComparisonDimension(BaseModel):
    """单个对比维度的结果"""
    name: str  # 维度名称，如 "方法论"、"性能"、"创新点"
    paper_values: Dict[str, str] = Field(default_factory=dict)  # paper_id -> 该论文在此维度的内容
    ranking: List[str] = Field(default_factory=list)  # paper_id 排序列表
    summary: Optional[str] = None  # 维度总结


class PaperComparison(BaseModel):
    """论文对比会话"""
    comparison_id: str
    session_id: str
    paper_ids: List[str] = Field(default_factory=list)
    status: ComparisonStatus = "PENDING"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    error: Optional[str] = None


class ComparisonReport(BaseModel):
    """完整的对比报告"""
    comparison_id: str
    overview: Optional[str] = None  # 综合概述
    dimensions: List[ComparisonDimension] = Field(default_factory=list)
    recommendations: Optional[str] = None  # 根据需求推荐
    created_at: datetime = Field(default_factory=datetime.now)


class PaperComparisonWithReport(BaseModel):
    """包含完整报告的对比结果"""
    comparison: PaperComparison
    report: Optional[ComparisonReport] = None
    papers: List[Paper] = Field(default_factory=list)  # 论文详情列表


# ============== Annotation (论文批注) ==============

class AnnotationCreate(BaseModel):
    paper_id: str = Field(..., description="arXiv 论文短 ID")
    session_id: str = Field(default="default")
    page_number: Optional[int] = None
    highlighted_text: str = Field(..., min_length=1, max_length=8000)
    comment: str = Field(..., min_length=1, max_length=4000)
    chunk_index: Optional[int] = None


class AnnotationUpdate(BaseModel):
    page_number: Optional[int] = None
    highlighted_text: Optional[str] = Field(default=None, min_length=1, max_length=8000)
    comment: Optional[str] = Field(default=None, min_length=1, max_length=4000)


class Annotation(BaseModel):
    id: int
    paper_id: str
    session_id: str
    chunk_index: Optional[int] = None
    page_number: Optional[int] = None
    highlighted_text: str
    comment: str
    created_at: datetime
    updated_at: datetime


class AnnotationList(BaseModel):
    paper_id: str
    session_id: str
    items: List[Annotation] = Field(default_factory=list)


class AnnotationCite(BaseModel):
    """RAG 答案里引用的批注"""
    annotation_id: int
    page_number: Optional[int] = None
    snippet: str         # 高亮原文片段（截断）
    comment: str         # 用户评论（截断）
    score: float


# ============== Paper Tags & Bookmarks (跨会话个人兴趣库) ==============

class PaperTag(BaseModel):
    """单条论文标签记录"""
    id: int
    paper_id: str
    tag: str
    created_at: datetime


class PaperTagList(BaseModel):
    """某篇论文的所有标签"""
    paper_id: str
    tags: List[str] = Field(default_factory=list)        # 平铺字符串数组，方便前端直接 v-for
    items: List[PaperTag] = Field(default_factory=list)   # 完整对象（含时间）


class PaperBookmark(BaseModel):
    """单条论文收藏记录"""
    id: int
    paper_id: str
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PaperBookmarkWithPaper(BaseModel):
    """收藏夹列表项：收藏记录 + 关联论文元数据（便于收藏夹面板直接展示）"""
    bookmark: PaperBookmark
    paper: Optional[Paper] = None        # 论文可能已被清理：None 时仅展示 paper_id
    tags: List[str] = Field(default_factory=list)


class PaperBookmarkList(BaseModel):
    """收藏夹列表（按 tag 筛选时也可复用此结构）"""
    items: List[PaperBookmarkWithPaper] = Field(default_factory=list)
    total: int = 0
    all_tags: List[str] = Field(default_factory=list, description="全部可用 tag，供筛选 UI 使用")
