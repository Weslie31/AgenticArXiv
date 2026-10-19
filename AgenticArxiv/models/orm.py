# AgenticArxiv/models/orm.py
from datetime import datetime

from sqlalchemy import (
    Column, Integer, BigInteger, Float, LargeBinary, String, Text, DateTime, Index,
    Boolean,
)

from models.db import Base


# ---------------- 全局设置（单行，id 固定为 1） ----------------

class AppSettingsRow(Base):
    """系统级配置：LLM 与翻译服务。单用户部署，只保留一行。"""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True)
    llm_model = Column(String(128), nullable=True)
    llm_base_url = Column(String(512), nullable=True)
    llm_api_key = Column(String(255), nullable=True)
    translate_service = Column(String(32), nullable=True)
    translate_api_key = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PdfAssetRow(Base):
    __tablename__ = "pdf_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(String(64), unique=True, nullable=False, index=True)
    pdf_url = Column(String(512), default="")
    local_path = Column(String(512), default="")
    status = Column(String(32), default="NOT_DOWNLOADED")
    size_bytes = Column(BigInteger, default=0)
    sha256 = Column(String(128), nullable=True)
    downloaded_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    error = Column(Text, nullable=True)


class TranslateAssetRow(Base):
    __tablename__ = "translate_assets"
    __table_args__ = (
        Index("uq_translate_assets_paper", "paper_id", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(String(64), nullable=False)
    input_pdf_path = Column(String(512), default="")
    output_mono_path = Column(String(512), default="")
    output_dual_path = Column(String(512), nullable=True)
    status = Column(String(32), default="NOT_TRANSLATED")
    service = Column(String(64), nullable=True)
    threads = Column(Integer, default=0)
    translated_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    error = Column(Text, nullable=True)


class SessionRow(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("uq_sessions_session", "session_id", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), nullable=False, index=True)
    last_active_paper_id = Column(String(64), nullable=True)
    last_active_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class FeedPaperRow(Base):
    """全局论文池，所有 session 共享"""
    __tablename__ = "feed_papers"
    __table_args__ = (
        Index("ix_feed_papers_position", "position"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(String(64), unique=True, nullable=False, index=True)
    title = Column(String(512), default="")
    authors = Column(Text, default="[]")        # JSON array
    summary = Column(Text, nullable=True)
    published = Column(String(64), nullable=True)
    updated = Column(String(64), nullable=True)
    pdf_url = Column(String(512), nullable=True)
    primary_category = Column(String(32), nullable=True)
    categories = Column(Text, default="[]")     # JSON array
    comment = Column(Text, nullable=True)
    links = Column(Text, default="[]")          # JSON array
    position = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class SessionPaperRow(Base):
    __tablename__ = "session_papers"
    __table_args__ = (
        Index("ix_session_papers_sid_pos", "session_id", "position"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), nullable=False, index=True)
    paper_id = Column(String(64), nullable=False)
    title = Column(String(512), default="")
    authors = Column(Text, default="[]")        # JSON array
    summary = Column(Text, nullable=True)
    published = Column(String(64), nullable=True)
    updated = Column(String(64), nullable=True)
    pdf_url = Column(String(512), nullable=True)
    primary_category = Column(String(32), nullable=True)
    categories = Column(Text, default="[]")     # JSON array
    comment = Column(Text, nullable=True)
    links = Column(Text, default="[]")          # JSON array
    position = Column(Integer, default=0)
    fetched_at = Column(DateTime, nullable=True)
    fetch_type = Column(String(32), default="manual")  # 'manual' | 'subscription'
    created_at = Column(DateTime, default=datetime.now)


class TranslateTaskRow(Base):
    __tablename__ = "translate_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    paper_id = Column(String(64), nullable=False)
    status = Column(String(32), default="PENDING")
    progress = Column(Float, default=0.0)
    input_pdf_url = Column(String(512), nullable=True)
    input_pdf_path = Column(String(512), nullable=True)
    output_pdf_path = Column(String(512), nullable=True)
    error = Column(Text, nullable=True)
    meta = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# --- Logging tables ---

class ChatLogRow(Base):
    __tablename__ = "chat_logs"
    __table_args__ = (
        Index("ix_chat_logs_session", "session_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), nullable=False, index=True)
    msg_id = Column(String(64), unique=True, nullable=False, index=True)
    role = Column(String(16), nullable=False)       # 'user' | 'assistant'
    content = Column(Text, nullable=True)
    model = Column(String(128), nullable=True)
    agent_type = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class AgentStepRow(Base):
    __tablename__ = "agent_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    msg_id = Column(String(64), nullable=False, index=True)
    step_index = Column(Integer, nullable=False)
    thought = Column(Text, nullable=True)
    action_name = Column(String(128), nullable=True)
    action_args = Column(Text, nullable=True)
    observation = Column(Text, nullable=True)
    llm_latency_ms = Column(Integer, nullable=True)
    tool_latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


# --- Paper Comparison tables ---

class ComparisonRow(Base):
    __tablename__ = "paper_comparisons"
    __table_args__ = (
        Index("ix_comparisons_session", "session_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    comparison_id = Column(String(64), unique=True, nullable=False, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    paper_ids = Column(Text, default="[]")
    status = Column(String(32), default="PENDING")
    overview = Column(Text, nullable=True)
    recommendations = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ComparisonDimensionRow(Base):
    __tablename__ = "comparison_dimensions"
    __table_args__ = (
        Index("ix_comparison_dimensions_cmp_id", "comparison_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    comparison_id = Column(String(64), nullable=False, index=True)
    dimension_name = Column(String(64), nullable=False)
    paper_values = Column(Text, default="{}")
    ranking = Column(Text, default="[]")
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class PaperChunkRow(Base):
    __tablename__ = "paper_chunks"
    __table_args__ = (
        Index("ix_paper_chunks_paper_id_idx", "paper_id", "chunk_index"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(String(64), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    section = Column(String(128), nullable=True)
    text = Column(Text, nullable=False)
    text_hash = Column(String(64), nullable=False, index=True)
    token_count = Column(Integer, default=0)
    embedding_model = Column(String(64), nullable=True)
    embedding_blob = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PaperAnnotationRow(Base):
    __tablename__ = "paper_annotations"
    __table_args__ = (
        Index("ix_annot_paper_session", "paper_id", "session_id"),
        Index("ix_annot_session", "session_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(String(64), nullable=False)
    session_id = Column(String(128), nullable=False)
    chunk_index = Column(Integer, nullable=True)
    page_number = Column(Integer, nullable=True)
    highlighted_text = Column(Text, nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PaperTagRow(Base):
    __tablename__ = "paper_tags"
    __table_args__ = (
        Index("uq_paper_tag", "paper_id", "tag", unique=True),
        Index("ix_paper_tag_tag", "tag"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(String(64), nullable=False)
    tag = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class PaperBookmarkRow(Base):
    __tablename__ = "paper_bookmarks"
    __table_args__ = (
        Index("uq_paper_bookmark", "paper_id", unique=True),
        Index("ix_paper_bookmark_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(String(64), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ============== Subscriptions ==============

class SubscriptionRow(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("uq_subscriptions_sub_id", "sub_id", unique=True),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sub_id = Column(String(128), nullable=False)
    name = Column(String(128), nullable=False)
    aspects_json = Column(Text, nullable=False, default="[]")
    keywords_json = Column(Text, nullable=False, default="[]")
    exclude_keywords_json = Column(Text, nullable=False, default="[]")
    match_mode = Column(String(8), nullable=False, default="any")
    days = Column(Integer, nullable=False, default=7)
    max_results = Column(Integer, nullable=False, default=15)
    enabled = Column(Boolean, nullable=False, default=True)
    session_id = Column(String(128), nullable=False, default="default")
    interval_minutes = Column(Integer, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    last_run_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.now)


class SubscriptionRunRow(Base):
    __tablename__ = "subscription_runs"
    __table_args__ = (
        Index("ix_sub_runs_sub_id", "sub_id"),
        Index("ix_sub_runs_run_at", "run_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sub_id = Column(String(128), nullable=False)
    subscription_name = Column(String(128), nullable=False, default="")
    papers_count = Column(Integer, nullable=False, default=0)
    new_papers_count = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    errors_json = Column(Text, nullable=False, default="[]")
    papers_json = Column(Text, nullable=False, default="[]")
    run_at = Column(DateTime, default=datetime.now)
