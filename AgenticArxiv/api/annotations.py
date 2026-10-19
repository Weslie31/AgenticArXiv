# AgenticArxiv/api/annotations.py
"""论文批注 CRUD 端点，单用户模式。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from models.db import get_sync_session
from models.orm import PaperAnnotationRow
from models.schemas import (
    Annotation,
    AnnotationCreate,
    AnnotationList,
    AnnotationUpdate,
)
from utils.logger import log

router = APIRouter()


def _row_to_annotation(row: PaperAnnotationRow) -> Annotation:
    return Annotation(
        id=row.id,
        paper_id=row.paper_id,
        session_id=row.session_id,
        chunk_index=row.chunk_index,
        page_number=row.page_number,
        highlighted_text=row.highlighted_text,
        comment=row.comment,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/annotations/{paper_id}", response_model=AnnotationList)
def list_annotations(paper_id: str,
                     session_id: str = Query(default="default")):
    """列出某篇论文在某 session 的全部批注，按 created_at 倒序。"""
    try:
        with get_sync_session() as s:
            rows = (
                s.query(PaperAnnotationRow)
                .filter_by(paper_id=paper_id, session_id=session_id)
                .order_by(PaperAnnotationRow.created_at.desc())
                .all()
            )
            return AnnotationList(
                paper_id=paper_id,
                session_id=session_id,
                items=[_row_to_annotation(r) for r in rows],
            )
    except SQLAlchemyError as e:
        log.error(f"[annotations] list 失败: {e}")
        raise HTTPException(status_code=500, detail=f"批注查询失败: {e}")


@router.post("/annotations", response_model=Annotation)
def create_annotation(payload: AnnotationCreate,
                       ):
    """新增一条批注。"""
    try:
        with get_sync_session() as s:
            row = PaperAnnotationRow(
                paper_id=payload.paper_id,
                session_id=payload.session_id or "default",
                chunk_index=payload.chunk_index,
                page_number=payload.page_number,
                highlighted_text=payload.highlighted_text.strip(),
                comment=payload.comment.strip(),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            log.info(f"[annotations] 新增 id={row.id} paper={row.paper_id}")
            return _row_to_annotation(row)
    except SQLAlchemyError as e:
        log.error(f"[annotations] create 失败: {e}")
        raise HTTPException(status_code=500, detail=f"批注创建失败: {e}")


@router.put("/annotations/{annotation_id}", response_model=Annotation)
def update_annotation(annotation_id: int,
                       payload: AnnotationUpdate,
                       ):
    """更新批注的页码/原文片段/评论（部分字段更新）。"""
    try:
        with get_sync_session() as s:
            row = s.get(PaperAnnotationRow, annotation_id)
            if row is None:
                raise HTTPException(status_code=404, detail="批注不存在")
            if payload.page_number is not None:
                row.page_number = payload.page_number
            if payload.highlighted_text is not None:
                row.highlighted_text = payload.highlighted_text.strip()
            if payload.comment is not None:
                row.comment = payload.comment.strip()
            s.commit()
            s.refresh(row)
            log.info(f"[annotations] 更新 id={row.id}")
            return _row_to_annotation(row)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        log.error(f"[annotations] update 失败: {e}")
        raise HTTPException(status_code=500, detail=f"批注更新失败: {e}")


@router.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: int,
                       ):
    """删除一条批注。"""
    try:
        with get_sync_session() as s:
            row = s.get(PaperAnnotationRow, annotation_id)
            if row is None:
                raise HTTPException(status_code=404, detail="批注不存在")
            s.delete(row)
            s.commit()
            log.info(f"[annotations] 删除 id={annotation_id}")
            return {"deleted_id": annotation_id, "ok": True}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        log.error(f"[annotations] delete 失败: {e}")
        raise HTTPException(status_code=500, detail=f"批注删除失败: {e}")
