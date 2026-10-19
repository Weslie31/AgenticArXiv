# AgenticArxiv/models/store.py
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Iterable

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from config import settings
from models.db import get_sync_session
from models.orm import (
    PdfAssetRow, TranslateAssetRow, SessionRow, SessionPaperRow, TranslateTaskRow,
    PaperTagRow, PaperBookmarkRow,
)
from models.schemas import (
    Paper, PdfAsset, TranslateAsset, TranslateTask,
    PaperTag, PaperTagList, PaperBookmark, PaperBookmarkWithPaper,
)

_REF_RE = re.compile(r"(?:第)?\s*(\d+)\s*(?:篇)?")


def _pdf_row_to_schema(row: PdfAssetRow) -> PdfAsset:
    raw_path = row.local_path or ""
    # 兼容旧数据：若存的是相对路径（如 ./output/pdf_raw/...），
    # 基于当前进程 cwd 转为绝对路径，保证 os.path.exists() 正常工作
    if raw_path and not os.path.isabs(raw_path):
        import pathlib
        raw_path = str(pathlib.Path(raw_path).resolve())
    return PdfAsset(
        paper_id=row.paper_id,
        pdf_url=row.pdf_url or "",
        local_path=raw_path,
        status=row.status or "NOT_DOWNLOADED",
        size_bytes=row.size_bytes or 0,
        sha256=row.sha256,
        downloaded_at=row.downloaded_at,
        updated_at=row.updated_at or datetime.now(),
        error=row.error,
    )


def _translate_row_to_schema(row: TranslateAssetRow) -> TranslateAsset:
    def _abs(path: str) -> str:
        if path and not os.path.isabs(path):
            import pathlib
            return str(pathlib.Path(path).resolve())
        return path

    return TranslateAsset(
        paper_id=row.paper_id,
        input_pdf_path=_abs(row.input_pdf_path or ""),
        output_mono_path=_abs(row.output_mono_path or ""),
        output_dual_path=_abs(row.output_dual_path) if row.output_dual_path else None,
        status=row.status or "NOT_TRANSLATED",
        service=row.service,
        threads=row.threads or 0,
        translated_at=row.translated_at,
        updated_at=row.updated_at or datetime.now(),
        error=row.error,
    )


def _task_row_to_schema(row: TranslateTaskRow) -> TranslateTask:
    meta = {}
    if row.meta:
        try:
            meta = json.loads(row.meta)
        except Exception:
            pass
    return TranslateTask(
        task_id=row.task_id,
        session_id=row.session_id,
        paper_id=row.paper_id,
        status=row.status or "PENDING",
        progress=row.progress or 0.0,
        input_pdf_url=row.input_pdf_url,
        input_pdf_path=row.input_pdf_path,
        output_pdf_path=row.output_pdf_path,
        error=row.error,
        meta=meta,
        created_at=row.created_at or datetime.now(),
        updated_at=row.updated_at or datetime.now(),
    )


def _paper_row_to_schema(row: SessionPaperRow) -> Paper:
    def _load_json_list(s):
        if not s:
            return []
        try:
            return json.loads(s)
        except Exception:
            return []

    return Paper(
        id=row.paper_id,
        title=row.title or "",
        authors=_load_json_list(row.authors),
        summary=row.summary,
        published=row.published,
        updated=row.updated,
        pdf_url=row.pdf_url,
        primary_category=row.primary_category,
        categories=_load_json_list(row.categories),
        comment=row.comment,
        links=_load_json_list(row.links),
        fetched_at=row.fetched_at,
        fetch_type=getattr(row, 'fetch_type', 'manual'),
    )


class Store:
    """MySQL-backed store (synchronous, thread-safe via SQLAlchemy connection pool).

    单用户部署：没有账号体系，所有数据（会话、论文、标签、收藏、订阅）都是全局的。
    """

    def __init__(self, ttl_minutes: int = 60, max_papers: int = 50):
        self.ttl = timedelta(minutes=ttl_minutes)
        self.max_papers = max_papers

        # Ensure output directories exist
        os.makedirs(settings.pdf_raw_path, exist_ok=True)
        os.makedirs(settings.pdf_translated_path, exist_ok=True)

    # ============================================================
    # session 记忆
    # ============================================================

    def _upsert_session_row(self, db, session_id: str) -> SessionRow:
        """按 session_id upsert SessionRow。"""
        row = db.query(SessionRow).filter_by(session_id=session_id).first()
        if not row:
            row = SessionRow(session_id=session_id)
            db.add(row)
            db.flush()
        return row

    def set_last_papers(
        self,
        session_id: str,
        papers: List[Paper],
        merge: bool = True,
        fetched_at: Optional[datetime] = None,
        fetch_type: str = "manual",
    ) -> None:
        """
        保存论文列表到 session。
        - merge=True（默认）：与现有论文合并，新论文插到最前面，去重，截断到 max_papers
        - merge=False：全量替换
        - fetched_at：本次写入时间，merge=True 时新论文用此时间，旧论文保留原 fetched_at
        - fetch_type: 'manual' 手动检索 | 'subscription' 定时订阅
        """
        with get_sync_session() as db:
            self._upsert_session_row(db, session_id)
            ts = fetched_at or datetime.now()

            # 注意：必须在删除之前读取旧行，否则 merge 永远拿不到已有论文，
            # 等价于全量替换（历史 bug：订阅重复执行总是同一批论文）
            existing_rows = []
            if merge:
                existing_rows = (
                    db.query(SessionPaperRow)
                    .filter_by(session_id=session_id)
                    .order_by(SessionPaperRow.position)
                    .all()
                )

            db.query(SessionPaperRow).filter_by(session_id=session_id).delete()

            if merge:
                # 拷贝成普通 dict：bulk delete 之后不能再依赖 ORM 实例的属性
                existing_map = {
                    r.paper_id: {
                        "paper_id": r.paper_id,
                        "title": r.title,
                        "authors": r.authors,
                        "summary": r.summary,
                        "published": r.published,
                        "updated": r.updated,
                        "pdf_url": r.pdf_url,
                        "primary_category": r.primary_category,
                        "categories": r.categories,
                        "comment": r.comment,
                        "links": r.links,
                        "fetched_at": r.fetched_at,
                        "fetch_type": getattr(r, "fetch_type", "manual"),
                    }
                    for r in existing_rows
                }
                existing_ids = set(existing_map.keys())

                # 合并：新论文在前，未重复的旧论文在后
                merged_ids: List[str] = []
                for p in reversed(papers):
                    if p.id not in merged_ids:
                        merged_ids.append(p.id)
                for eid in existing_ids:
                    if eid not in merged_ids:
                        merged_ids.append(eid)
                merged_ids = merged_ids[: self.max_papers]

                for i, pid in enumerate(merged_ids):
                    p = next((x for x in papers if x.id == pid), None)
                    if p:
                        db.add(SessionPaperRow(
                            session_id=session_id,
                            paper_id=p.id,
                            title=p.title,
                            authors=json.dumps(p.authors, ensure_ascii=False),
                            summary=p.summary,
                            published=p.published,
                            updated=p.updated,
                            pdf_url=p.pdf_url,
                            primary_category=p.primary_category,
                            categories=json.dumps(p.categories, ensure_ascii=False),
                            comment=p.comment,
                            links=json.dumps(p.links, ensure_ascii=False),
                            position=i,
                            fetched_at=ts,
                            fetch_type=fetch_type,
                        ))
                    else:
                        old = existing_map[pid]
                        db.add(SessionPaperRow(
                            session_id=session_id,
                            paper_id=old["paper_id"],
                            title=old["title"],
                            authors=old["authors"],
                            summary=old["summary"],
                            published=old["published"],
                            updated=old["updated"],
                            pdf_url=old["pdf_url"],
                            primary_category=old["primary_category"],
                            categories=old["categories"],
                            comment=old["comment"],
                            links=old["links"],
                            position=i,
                            fetched_at=old["fetched_at"],
                            fetch_type=old["fetch_type"],
                        ))
            else:
                for i, p in enumerate(papers[: self.max_papers]):
                    db.add(SessionPaperRow(
                        session_id=session_id,
                        paper_id=p.id,
                        title=p.title,
                        authors=json.dumps(p.authors, ensure_ascii=False),
                        summary=p.summary,
                        published=p.published,
                        updated=p.updated,
                        pdf_url=p.pdf_url,
                        primary_category=p.primary_category,
                        categories=json.dumps(p.categories, ensure_ascii=False),
                        comment=p.comment,
                        links=json.dumps(p.links, ensure_ascii=False),
                        position=i,
                        fetched_at=ts,
                            fetch_type=fetch_type,
                    ))
            db.commit()

    def list_session_ids(self) -> List[str]:
        with get_sync_session() as db:
            rows = (
                db.query(SessionRow.session_id)
                .order_by(SessionRow.updated_at.desc())
                .all()
            )
            return [r[0] for r in rows]

    def get_last_papers(self, session_id: str) -> List[Paper]:
        """会话里的论文（manual + subscription）。

        Papers 面板、Agent 上下文都看这个；订阅论文也属于当前会话。
        """
        return self._get_last_papers_all(session_id)

    def _get_last_papers_all(self, session_id: str) -> List[Paper]:
        """解析 ref 时使用：manual + subscription 合并视图（订阅论文也能按 ref 定位）"""
        with get_sync_session() as db:
            paper_rows = (
                db.query(SessionPaperRow)
                .filter_by(session_id=session_id)
                .order_by(SessionPaperRow.fetched_at.desc(), SessionPaperRow.position)
                .all()
            )
            return [_paper_row_to_schema(r) for r in paper_rows]

    def get_session_papers(self, session_id: str) -> List[Paper]:
        """会话里的全部论文（manual + subscription），用于增量去重。"""
        return self._get_last_papers_all(session_id)

    def get_subscription_papers(self, session_id: str) -> List[Paper]:
        with get_sync_session() as db:
            paper_rows = (
                db.query(SessionPaperRow)
                .filter_by(session_id=session_id, fetch_type="subscription")
                .order_by(SessionPaperRow.fetched_at.desc(), SessionPaperRow.position)
                .all()
            )
            return [_paper_row_to_schema(r) for r in paper_rows]

    def get_all_subscription_papers(self) -> List[Paper]:
        """返回所有 session 下的订阅论文（去重，按 fetched_at 倒序）"""
        with get_sync_session() as db:
            paper_rows = (
                db.query(SessionPaperRow)
                .filter_by(fetch_type="subscription")
                .order_by(SessionPaperRow.fetched_at.desc(), SessionPaperRow.position)
                .all()
            )
            # 去重：相同 paper_id 只保留第一条
            seen = set()
            out: List[Paper] = []
            for r in paper_rows:
                if r.paper_id in seen:
                    continue
                seen.add(r.paper_id)
                out.append(_paper_row_to_schema(r))
            return out

    def remove_session_papers(
        self,
        session_id: str,
        paper_ids: List[str],
        fetch_type: str = "manual",
    ) -> int:
        """
        删除 session 中的指定论文（按 paper_id + fetch_type 过滤）。
        - fetch_type='manual'      → 仅删"会话论文"
        - fetch_type='subscription' → 仅删"订阅论文"
        - 返回实际删除的行数
        """
        if not paper_ids:
            return 0
        with get_sync_session() as db:
            q = db.query(SessionPaperRow).filter(
                SessionPaperRow.session_id == session_id,
                SessionPaperRow.paper_id.in_(paper_ids),
                SessionPaperRow.fetch_type == fetch_type,
            )
            deleted = q.delete(synchronize_session=False)
            db.commit()
            return int(deleted or 0)

    # -------- last active paper --------

    def set_last_active_paper_id(self, session_id: str, paper_id: str) -> None:
        if not paper_id:
            return
        with get_sync_session() as db:
            self._upsert_session_row(db, session_id)
            row = (
                db.query(SessionRow)
                .filter_by(session_id=session_id)
                .first()
            )
            if row is None:
                # 极少见：并发删除，upsert 已 commit
                row = SessionRow(session_id=session_id)
                db.add(row)
                db.flush()
            row.last_active_paper_id = paper_id
            row.last_active_at = datetime.now()
            row.updated_at = datetime.now()
            db.commit()

    def get_last_active_paper_id(self, session_id: str) -> Optional[str]:
        with get_sync_session() as db:
            row = (
                db.query(SessionRow)
                .filter_by(session_id=session_id)
                .first()
            )
            if not row:
                return None
            if row.last_active_at and (datetime.now() - row.last_active_at) > self.ttl:
                row.last_active_paper_id = None
                row.last_active_at = None
                db.commit()
                return None
            return row.last_active_paper_id

    def get_paper_by_id(self, paper_id: str) -> Optional[Paper]:
        """定位论文。如果从未保存过此论文，返回 None。"""
        with get_sync_session() as db:
            row = (
                db.query(SessionPaperRow)
                .filter_by(paper_id=paper_id)
                .first()
            )
            return _paper_row_to_schema(row) if row else None

    def resolve_paper(
        self,
        session_id: str,
        ref: Union[str, int, None] = None,
        paper_id: Optional[str] = None,
    ) -> Optional[Paper]:
        # 支持直接用 paper_id 定位
        if paper_id:
            return self.get_paper_by_id(paper_id)

        # ref 解析时用合并视图：manual + subscription，让订阅论文也能按序号/id 定位
        papers = self._get_last_papers_all(session_id)
        if not papers:
            return None

        if ref is None:
            last_id = self.get_last_active_paper_id(session_id)
            if not last_id:
                return None
            for p in papers:
                if p.id == last_id:
                    return p
            return None

        if isinstance(ref, int):
            idx = ref - 1
            return papers[idx] if 0 <= idx < len(papers) else None

        s = str(ref).strip()
        m = _REF_RE.fullmatch(s)
        if m:
            idx = int(m.group(1)) - 1
            return papers[idx] if 0 <= idx < len(papers) else None

        for p in papers:
            if p.id == s:
                return p

        low = s.lower()
        for p in papers:
            if low in (p.title or "").lower():
                return p
        return None

    # ============================================================
    # PDF cache（全局共享，按 paper_id）
    # ============================================================

    def get_pdf_asset(self, paper_id: str) -> Optional[PdfAsset]:
        with get_sync_session() as db:
            row = db.query(PdfAssetRow).filter_by(paper_id=paper_id).first()
            return _pdf_row_to_schema(row) if row else None

    def upsert_pdf_asset(self, asset: PdfAsset) -> PdfAsset:
        with get_sync_session() as db:
            row = db.query(PdfAssetRow).filter_by(paper_id=asset.paper_id).first()
            if not row:
                row = PdfAssetRow(paper_id=asset.paper_id)
                db.add(row)
            row.pdf_url = asset.pdf_url
            row.local_path = asset.local_path
            row.status = asset.status
            row.size_bytes = asset.size_bytes
            row.sha256 = asset.sha256
            row.downloaded_at = asset.downloaded_at
            row.updated_at = datetime.now()
            row.error = asset.error
            db.commit()
            db.refresh(row)
            return _pdf_row_to_schema(row)

    def update_pdf_asset(self, paper_id: str, **kwargs) -> Optional[PdfAsset]:
        with get_sync_session() as db:
            row = db.query(PdfAssetRow).filter_by(paper_id=paper_id).first()
            if not row:
                return None
            for k, v in kwargs.items():
                if hasattr(row, k):
                    setattr(row, k, v)
            row.updated_at = datetime.now()
            db.commit()
            db.refresh(row)
            return _pdf_row_to_schema(row)

    def delete_pdf_asset(self, paper_id: str) -> bool:
        with get_sync_session() as db:
            row = db.query(PdfAssetRow).filter_by(paper_id=paper_id).first()
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True

    def list_pdf_assets(self, paper_ids: Optional[set] = None) -> List[PdfAsset]:
        """列出 PDF 资产。paper_ids 不为 None 时只返回这些论文。"""
        with get_sync_session() as db:
            q = db.query(PdfAssetRow)
            if paper_ids is not None:
                if not paper_ids:
                    return []
                q = q.filter(PdfAssetRow.paper_id.in_(list(paper_ids)))
            rows = q.order_by(PdfAssetRow.updated_at.desc()).all()
            return [_pdf_row_to_schema(r) for r in rows]

    # ============================================================
    # Translate cache（全局共享，按 paper_id）
    # ============================================================

    def get_translate_asset(self, paper_id: str) -> Optional[TranslateAsset]:
        with get_sync_session() as db:
            row = db.query(TranslateAssetRow).filter_by(paper_id=paper_id).first()
            return _translate_row_to_schema(row) if row else None

    def upsert_translate_asset(self, asset: TranslateAsset) -> TranslateAsset:
        with get_sync_session() as db:
            row = db.query(TranslateAssetRow).filter_by(paper_id=asset.paper_id).first()
            if not row:
                row = TranslateAssetRow(paper_id=asset.paper_id)
                db.add(row)
            row.input_pdf_path = asset.input_pdf_path
            row.output_mono_path = asset.output_mono_path
            row.output_dual_path = asset.output_dual_path
            row.status = asset.status
            row.service = asset.service
            row.threads = asset.threads
            row.translated_at = asset.translated_at
            row.updated_at = datetime.now()
            row.error = asset.error
            db.commit()
            db.refresh(row)
            return _translate_row_to_schema(row)

    def update_translate_asset(self, paper_id: str, **kwargs) -> Optional[TranslateAsset]:
        with get_sync_session() as db:
            row = db.query(TranslateAssetRow).filter_by(paper_id=paper_id).first()
            if not row:
                return None
            for k, v in kwargs.items():
                if hasattr(row, k):
                    setattr(row, k, v)
            row.updated_at = datetime.now()
            db.commit()
            db.refresh(row)
            return _translate_row_to_schema(row)

    def delete_translate_asset(self, paper_id: str) -> bool:
        with get_sync_session() as db:
            row = db.query(TranslateAssetRow).filter_by(paper_id=paper_id).first()
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True

    def list_translate_assets(self, paper_ids: Optional[set] = None) -> List[TranslateAsset]:
        """列出译文资产。paper_ids 不为 None 时只返回这些论文。"""
        with get_sync_session() as db:
            q = db.query(TranslateAssetRow)
            if paper_ids is not None:
                if not paper_ids:
                    return []
                q = q.filter(TranslateAssetRow.paper_id.in_(list(paper_ids)))
            rows = q.order_by(TranslateAssetRow.updated_at.desc()).all()
            return [_translate_row_to_schema(r) for r in rows]

    def count_translate_path_refs(self, path: str) -> int:
        """有多少条译文记录共用同一个文件路径（历史共享文件可能被多条引用）。"""
        if not path:
            return 0
        with get_sync_session() as db:
            return (
                db.query(TranslateAssetRow)
                .filter(TranslateAssetRow.output_mono_path == path)
                .count()
            )

    # ============================================================
    # Tasks
    # ============================================================

    def has_active_task_for_paper(self, paper_id: str) -> bool:
        """检查该论文是否有进行中的翻译任务。"""
        with get_sync_session() as db:
            return (
                db.query(TranslateTaskRow)
                .filter(
                    TranslateTaskRow.paper_id == paper_id,
                    TranslateTaskRow.status.in_(("PENDING", "RUNNING")),
                )
                .first()
                is not None
            )

    def create_translate_task(
        self,
        session_id: str,
        paper_id: str,
        input_pdf_url: Optional[str] = None,
        meta: Optional[Dict[str, str]] = None,
    ) -> TranslateTask:
        task_id = uuid.uuid4().hex
        now = datetime.now()
        with get_sync_session() as db:
            row = TranslateTaskRow(
                task_id=task_id,
                session_id=session_id,
                paper_id=paper_id,
                status="PENDING",
                input_pdf_url=input_pdf_url,
                meta=json.dumps(meta or {}, ensure_ascii=False),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return _task_row_to_schema(row)

    def get_task(self, task_id: str) -> Optional[TranslateTask]:
        """查询任务。"""
        with get_sync_session() as db:
            row = db.query(TranslateTaskRow).filter_by(task_id=task_id).first()
            return _task_row_to_schema(row) if row else None

    def update_task(self, task_id: str, **kwargs) -> Optional[TranslateTask]:
        with get_sync_session() as db:
            row = db.query(TranslateTaskRow).filter_by(task_id=task_id).first()
            if not row:
                return None
            for k, v in kwargs.items():
                if k == "meta" and isinstance(v, dict):
                    row.meta = json.dumps(v, ensure_ascii=False)
                elif hasattr(row, k):
                    setattr(row, k, v)
            row.updated_at = datetime.now()
            db.commit()
            db.refresh(row)
            return _task_row_to_schema(row)

    def list_tasks(
        self, session_id: Optional[str] = None, limit: int = 50
    ) -> List[TranslateTask]:
        with get_sync_session() as db:
            q = db.query(TranslateTaskRow)
            if session_id:
                q = q.filter_by(session_id=session_id)
            rows = q.order_by(TranslateTaskRow.updated_at.desc()).limit(max(1, limit)).all()
            return [_task_row_to_schema(r) for r in rows]

    # ============================================================
    # 启动校验
    # ============================================================

    def validate_local_paths(self) -> None:
        """
        启动时校验：READY 资产对应的本地文件丢失时，标记为 STALE（而非 FAILED）。

        之所以不直接置 FAILED：
        - 真实下载失败和"文件被外部清理"在用户感知上不同；
        - STALE 状态对前端可见，能引导用户重下；FAILED 会被 UI 误判为"未下载/下载失败"。

        同时：db 里可能存的是相对路径（历史数据），read 路径会 _abs 化，
        这里校验时也做相同处理，避免误判。

        反向孤儿修复：磁盘 pdf_raw 目录下有 .pdf，但 pdf_assets 表里没记录，
        （通常是某个老版本/绕过路径写入的文件，或事务失败留下的孤儿）。
        这里扫描 pdf_raw_path，把孤儿补成 READY 行，让前端重启后能正常识别。
        """
        import pathlib

        def _abs(path: str) -> str:
            if path and not os.path.isabs(path):
                return str(pathlib.Path(path).resolve())
            return path or ""

        with get_sync_session() as db:
            for row in db.query(PdfAssetRow).filter_by(status="READY").all():
                p = _abs(row.local_path or "")
                if not p or not os.path.exists(p):
                    row.status = "STALE"
                    row.error = f"local file missing: {row.local_path}"
                    row.updated_at = datetime.now()
            for row in db.query(TranslateAssetRow).filter_by(status="READY").all():
                p = _abs(row.output_mono_path or "")
                if not p or not os.path.exists(p):
                    row.status = "STALE"
                    row.error = f"local file missing: {row.output_mono_path}"
                    row.updated_at = datetime.now()
            db.commit()

        # 反向孤儿：扫描 pdf_raw_path，把磁盘有但 db 缺失的 PDF 补成 READY 行
        # safe_filename 用 [^A-Za-z0-9._-]+ → _ 的规则，DOI 里的 / 全部变 _，
        # 还原规则就是把 basename 里的 _ 替换回 /（仅一次，按 paper_id 形态还原）。
        try:
            from config import settings
            from utils.pdf_downloader import safe_filename
            if not os.path.isdir(settings.pdf_raw_path):
                return

            with get_sync_session() as db:
                # 1) 已索引的 paper_id 集合，避免 upsert 时 unique 冲突
                existing_ids = {pid for pid, in db.query(PdfAssetRow.paper_id).all() if pid}
                # 2) 已索引的 local_path 集合（绝对路径归一化）
                existing_paths = {
                    os.path.normcase(os.path.abspath(p or ""))
                    for p, in db.query(PdfAssetRow.local_path).all() if p
                }

            for fname in os.listdir(settings.pdf_raw_path):
                if not fname.lower().endswith(".pdf"):
                    continue
                fpath = os.path.abspath(os.path.join(settings.pdf_raw_path, fname))
                if os.path.normcase(fpath) in existing_paths:
                    continue
                if os.path.getsize(fpath) <= 0:
                    continue

                # 反推 paper_id：把 _ 还原回 /（safe_filename 的反向）
                # 但要避免破坏文件名里合法的 _（如 10.1007_s00366-... 的 _s）
                # 策略：尝试多种还原（按常见 DOI / arXiv 形态匹配）
                stem = fname[:-4]  # 去 .pdf
                candidate_ids = Store._recover_paper_id_from_safe_name(stem)
                if not candidate_ids:
                    continue

                inserted = False
                for pid in candidate_ids:
                    if pid in existing_ids:
                        # 已被索引（仅路径不一致），只更新 local_path
                        try:
                            self.update_pdf_asset(
                                pid,
                                local_path=fpath,
                                status="READY",
                                size_bytes=os.path.getsize(fpath),
                                error=None,
                            )
                            inserted = True
                            break
                        except Exception:
                            continue
                    # 补一行新记录
                    try:
                        asset = PdfAsset(
                            paper_id=pid,
                            pdf_url="",
                            local_path=fpath,
                            status="READY",
                            size_bytes=os.path.getsize(fpath),
                            sha256=None,
                            downloaded_at=datetime.now(),
                            error=None,
                        )
                        self.upsert_pdf_asset(asset)
                        existing_ids.add(pid)
                        inserted = True
                        break
                    except Exception:
                        # unique 冲突 / 并发失败 — 视为已存在
                        existing_ids.add(pid)
                        continue
                # 即便没匹配上 candidate_ids，文件留着不删，下次能再扫
        except Exception:
            # 孤儿修复失败不影响主流程
            pass


    @staticmethod
    def _recover_paper_id_from_safe_name(stem: str) -> List[str]:
        """
        从 safe_filename 后的 basename 反推可能的 paper_id 列表。
        safe_filename 把 [^A-Za-z0-9._-]+ 替换为 _，DOI 里的 / 全部变 _。

        启发式还原：
        1. 如果 stem 是纯数字 + . (如 arXiv 形态 YYMM.NNNNN) → 直接返回原 stem
        2. 如果 stem 以 W 开头且后续是数字（OpenAlex ID）→ 直接返回原 stem
        3. 否则把 _ 还原回 /，得到候选 DOI；再用 safe_filename 校验一致性
        """
        from utils.pdf_downloader import safe_filename as _sfn
        candidates: List[str] = []

        # arXiv 形态：YYMM.NNNNN 或 YYMM.NNNNNvN
        if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", stem):
            candidates.append(stem)
            return candidates

        # OpenAlex ID 形态：W + 数字
        if re.match(r"^W\d+$", stem):
            candidates.append(stem)
            return candidates

        # DOI 形态：尝试把 _ 还原回 /，再用 safe_filename 反向校验
        # DOI 里只可能出现 /，所以 _ → / 是唯一的反向变换
        if "_" in stem:
            candidate = stem.replace("_", "/")
            if _sfn(candidate) == stem:
                candidates.append(candidate)
                return candidates

        # 无 _ 的纯字符串（如普通 ID）
        candidates.append(stem)
        return candidates


    # ============================================================
    # Tags
    # ============================================================

    @staticmethod
    def _normalize_tag(raw: str) -> str:
        """统一标签格式：去空白、转小写、限制长度。空字符串视为非法。"""
        if raw is None:
            return ""
        t = str(raw).strip().lower()
        # 单个 tag 最多 64 字符；前端校验后端兜底
        return t[:64]

    def list_tags_for_paper(self, paper_id: str) -> PaperTagList:
        """返回某论文的所有标签（平铺 + 完整对象），按 created_at 倒序。"""
        with get_sync_session() as db:
            rows = (
                db.query(PaperTagRow)
                .filter_by(paper_id=paper_id)
                .order_by(PaperTagRow.created_at.desc())
                .all()
            )
            items = [
                PaperTag(
                    id=r.id,
                    paper_id=r.paper_id,
                    tag=r.tag,
                    created_at=r.created_at or datetime.now(),
                )
                for r in rows
            ]
            return PaperTagList(
                paper_id=paper_id,
                tags=[it.tag for it in items],
                items=items,
            )

    def add_tag(self, paper_id: str, tag: str) -> PaperTagList:
        """为论文加 tag；已存在则直接返回（unique index 兜底）。"""
        norm = self._normalize_tag(tag)
        if not norm:
            raise ValueError("tag 不能为空")
        with get_sync_session() as db:
            try:
                row = PaperTagRow(paper_id=paper_id, tag=norm)
                db.add(row)
                db.commit()
                db.refresh(row)
            except IntegrityError:
                # 重复 tag：忽略，返回已存在的记录
                db.rollback()
        return self.list_tags_for_paper(paper_id)

    def remove_tag(self, paper_id: str, tag: str) -> PaperTagList:
        """删除论文的一个 tag。"""
        norm = self._normalize_tag(tag)
        with get_sync_session() as db:
            row = (
                db.query(PaperTagRow)
                .filter_by(paper_id=paper_id, tag=norm)
                .first()
            )
            if row:
                db.delete(row)
                db.commit()
        return self.list_tags_for_paper(paper_id)

    def list_all_tags(self) -> List[str]:
        """所有出现过的 tag，去重排序，供收藏夹筛选 UI 使用。"""
        with get_sync_session() as db:
            rows = (
                db.query(PaperTagRow.tag)
                .distinct()
                .order_by(PaperTagRow.tag.asc())
                .all()
            )
            return [r[0] for r in rows if r[0]]

    # ============================================================
    # Bookmarks
    # ============================================================

    @staticmethod
    def _bookmark_row_to_schema(row: PaperBookmarkRow) -> PaperBookmark:
        return PaperBookmark(
            id=row.id,
            paper_id=row.paper_id,
            note=row.note,
            created_at=row.created_at or datetime.now(),
            updated_at=row.updated_at or datetime.now(),
        )

    def is_bookmarked(self, paper_id: str) -> bool:
        with get_sync_session() as db:
            return (
                db.query(PaperBookmarkRow)
                .filter_by(paper_id=paper_id)
                .first()
                is not None
            )

    def get_bookmark(self, paper_id: str) -> Optional[PaperBookmark]:
        with get_sync_session() as db:
            row = (
                db.query(PaperBookmarkRow)
                .filter_by(paper_id=paper_id)
                .first()
            )
            return self._bookmark_row_to_schema(row) if row else None

    def add_bookmark(self, paper_id: str, note: Optional[str] = None) -> PaperBookmark:
        """收藏一篇论文（幂等：已收藏则更新 note 并返回新记录）。"""
        with get_sync_session() as db:
            row = (
                db.query(PaperBookmarkRow)
                .filter_by(paper_id=paper_id)
                .first()
            )
            if row:
                # 已收藏：note 显式传值才覆盖（None 视为不清空）
                if note is not None:
                    row.note = note
                row.updated_at = datetime.now()
            else:
                row = PaperBookmarkRow(paper_id=paper_id, note=note)
                db.add(row)
            db.commit()
            db.refresh(row)
            return self._bookmark_row_to_schema(row)

    def update_bookmark_note(self, paper_id: str, note: Optional[str]) -> Optional[PaperBookmark]:
        """只更新 note 字段（note=None 表示清空）。"""
        with get_sync_session() as db:
            row = (
                db.query(PaperBookmarkRow)
                .filter_by(paper_id=paper_id)
                .first()
            )
            if not row:
                return None
            row.note = note
            row.updated_at = datetime.now()
            db.commit()
            db.refresh(row)
            return self._bookmark_row_to_schema(row)

    def remove_bookmark(self, paper_id: str) -> bool:
        with get_sync_session() as db:
            row = (
                db.query(PaperBookmarkRow)
                .filter_by(paper_id=paper_id)
                .first()
            )
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True

    def list_bookmarks(
        self, tag: Optional[str] = None, limit: int = 500
    ) -> List[PaperBookmarkWithPaper]:
        """
        列出所有收藏（可按 tag 筛选）。
        返回值同时附带论文元数据（从 session_papers 聚合查询）。
        """
        norm_tag = self._normalize_tag(tag) if tag else None
        with get_sync_session() as db:
            if norm_tag:
                # 通过 paper_tags join 过滤
                bm_rows = (
                    db.query(PaperBookmarkRow)
                    .join(PaperTagRow, PaperTagRow.paper_id == PaperBookmarkRow.paper_id)
                    .filter(
                        PaperTagRow.tag == norm_tag,
                    )
                    .order_by(PaperBookmarkRow.created_at.desc())
                    .limit(max(1, limit))
                    .all()
                )
            else:
                bm_rows = (
                    db.query(PaperBookmarkRow)
                    .order_by(PaperBookmarkRow.created_at.desc())
                    .limit(max(1, limit))
                    .all()
                )

            if not bm_rows:
                return []

            paper_ids = [r.paper_id for r in bm_rows]
            # 从 session_papers 聚合查询论文元数据
            sp_rows = (
                db.query(SessionPaperRow)
                .filter(
                    SessionPaperRow.paper_id.in_(paper_ids),
                )
                .all()
            )
            # 去重：保留每个 paper_id 的第一条
            seen = set()
            paper_by_id: Dict[str, Paper] = {}
            for r in sp_rows:
                if r.paper_id in seen:
                    continue
                seen.add(r.paper_id)
                paper_by_id[r.paper_id] = _paper_row_to_schema(r)

            # 批量加载每条收藏的 tags
            tag_rows = (
                db.query(PaperTagRow)
                .filter(
                    PaperTagRow.paper_id.in_(paper_ids),
                )
                .order_by(PaperTagRow.tag.asc())
                .all()
            )
            tags_by_paper: Dict[str, List[str]] = {}
            for t in tag_rows:
                tags_by_paper.setdefault(t.paper_id, []).append(t.tag)

            results: List[PaperBookmarkWithPaper] = []
            for r in bm_rows:
                results.append(
                    PaperBookmarkWithPaper(
                        bookmark=self._bookmark_row_to_schema(r),
                        paper=paper_by_id.get(r.paper_id),
                        tags=tags_by_paper.get(r.paper_id, []),
                    )
                )
            return results

    def get_tags_map_for_papers(self, paper_ids: List[str]) -> Dict[str, List[str]]:
        """批量查询一批论文的 tags。"""
        if not paper_ids:
            return {}
        with get_sync_session() as db:
            rows = (
                db.query(PaperTagRow)
                .filter(
                    PaperTagRow.paper_id.in_(paper_ids),
                )
                .order_by(PaperTagRow.tag.asc())
                .all()
            )
        out: Dict[str, List[str]] = {}
        for r in rows:
            out.setdefault(r.paper_id, []).append(r.tag)
        return out

    def get_bookmarked_ids(self, paper_ids: List[str]) -> set:
        """批量查询哪些论文被收藏。"""
        if not paper_ids:
            return set()
        with get_sync_session() as db:
            rows = (
                db.query(PaperBookmarkRow.paper_id)
                .filter(
                    PaperBookmarkRow.paper_id.in_(paper_ids),
                )
                .all()
            )
        return {r[0] for r in rows}


store = Store()
