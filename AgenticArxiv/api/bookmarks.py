"""论文收藏 + 标签 跨会话个人兴趣库 API。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from models.db import get_sync_session
from models.schemas import (
    PaperBookmark,
    PaperBookmarkList,
    PaperBookmarkWithPaper,
    PaperTagList,
)
from models.store import store
from utils.logger import log

router = APIRouter()


# ---------------- Request / Response Schemas ----------------

class TagCreateRequest(BaseModel):
    tag: str = Field(..., min_length=1, max_length=64, description="标签名（自动 trim+lowercase）")


class BookmarkCreateRequest(BaseModel):
    """新增/覆盖收藏；已存在则视为更新 note。"""
    note: Optional[str] = Field(default=None, max_length=2000, description="用户备注（可空）")


class BookmarkUpdateRequest(BaseModel):
    """更新收藏的 note（note=null 表示清空）。"""
    note: Optional[str] = Field(default=None, max_length=2000)


class BookmarkDeleteResponse(BaseModel):
    paper_id: str
    removed: bool
    removed_tag_count: int = 0  # 顺手清理该论文的 tag 数量


# ---------------- Tags ----------------

@router.get(
    "/papers/{paper_id}/tags",
    response_model=PaperTagList,
    summary="获取某论文的所有标签",
)
def list_paper_tags(paper_id: str,
                    ) -> PaperTagList:
    try:
        return store.list_tags_for_paper(paper_id)
    except SQLAlchemyError as e:
        log.error(f"[tags] list 失败 paper={paper_id}: {e}")
        raise HTTPException(status_code=500, detail=f"标签查询失败: {e}")


@router.post(
    "/papers/{paper_id}/tags",
    response_model=PaperTagList,
    summary="为论文加一个标签（已存在则幂等返回）",
)
def add_paper_tag(paper_id: str,
                   payload: TagCreateRequest,
                   ) -> PaperTagList:
    try:
        return store.add_tag(paper_id, payload.tag)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SQLAlchemyError as e:
        log.error(f"[tags] add 失败 paper={paper_id} tag={payload.tag}: {e}")
        raise HTTPException(status_code=500, detail=f"标签创建失败: {e}")


@router.delete(
    "/papers/{paper_id}/tags/{tag}",
    response_model=PaperTagList,
    summary="删除论文的一个标签",
)
def remove_paper_tag(paper_id: str,
                      tag: str,
                      ) -> PaperTagList:
    try:
        return store.remove_tag(paper_id, tag)
    except SQLAlchemyError as e:
        log.error(f"[tags] remove 失败 paper={paper_id} tag={tag}: {e}")
        raise HTTPException(status_code=500, detail=f"标签删除失败: {e}")


@router.get(
    "/papers/tags",
    response_model=List[str],
    summary="列出所有出现过的标签（去重排序）",
)
def list_all_tags() -> List[str]:
    try:
        return store.list_all_tags()
    except SQLAlchemyError as e:
        log.error(f"[tags] list_all 失败: {e}")
        raise HTTPException(status_code=500, detail=f"标签列表查询失败: {e}")

# ---------------- Bookmarks ----------------

@router.get(
    "/papers/{paper_id}/bookmark",
    response_model=Optional[PaperBookmark],
    summary="获取某论文的收藏记录（未收藏则返回 null）",
)
def get_paper_bookmark(
    paper_id: str,
    include: Optional[List[str]] = Query(
        default=None,
        description="扩展字段预留：当前仅支持 paper_id 自身，未收藏返回 null",
    ),
):
    try:
        return store.get_bookmark(paper_id)
    except SQLAlchemyError as e:
        log.error(f"[bookmark] get 失败 paper={paper_id}: {e}")
        raise HTTPException(status_code=500, detail=f"收藏查询失败: {e}")


@router.post(
    "/papers/{paper_id}/bookmark",
    response_model=PaperBookmark,
    summary="系统收藏一篇论文（幂等；已收藏则更新 note）",
)
def add_paper_bookmark(
    paper_id: str,
    payload: BookmarkCreateRequest = BookmarkCreateRequest(),
) -> PaperBookmark:
    try:
        return store.add_bookmark(paper_id, payload.note)
    except SQLAlchemyError as e:
        log.error(f"[bookmark] add 失败 paper={paper_id}: {e}")
        raise HTTPException(status_code=500, detail=f"收藏失败: {e}")


@router.put(
    "/papers/{paper_id}/bookmark",
    response_model=PaperBookmark,
    summary="更新收藏的 note（仅改 note，不切换收藏状态）",
)
def update_paper_bookmark(
    paper_id: str,
    payload: BookmarkUpdateRequest,
) -> PaperBookmark:
    try:
        updated = store.update_bookmark_note(paper_id, payload.note)
    except SQLAlchemyError as e:
        log.error(f"[bookmark] update 失败 paper={paper_id}: {e}")
        raise HTTPException(status_code=500, detail=f"收藏更新失败: {e}")
    if updated is None:
        raise HTTPException(status_code=404, detail="论文未被收藏，无法更新 note")
    return updated


@router.delete(
    "/papers/{paper_id}/bookmark",
    response_model=BookmarkDeleteResponse,
    summary="系统取消收藏（同时清掉该论文的全部 tag，避免悬挂）",
)
def remove_paper_bookmark(paper_id: str,
                           ) -> BookmarkDeleteResponse:
    try:
        tags_before = store.list_tags_for_paper(paper_id).tags
        removed = store.remove_bookmark(paper_id)
        if removed and tags_before:
            for t in tags_before:
                store.remove_tag(paper_id, t)
        return BookmarkDeleteResponse(
            paper_id=paper_id,
            removed=removed,
            removed_tag_count=len(tags_before) if removed else 0,
        )
    except SQLAlchemyError as e:
        log.error(f"[bookmark] remove 失败 paper={paper_id}: {e}")
        raise HTTPException(status_code=500, detail=f"取消收藏失败: {e}")

@router.get(
    "/papers/bookmarks",
    response_model=PaperBookmarkList,
    summary="系统收藏夹列表（可按 tag 筛选）",
)
def list_paper_bookmarks(
    tag: Optional[str] = Query(default=None, description="按 tag 筛选"),
    limit: int = Query(default=500, ge=1, le=2000),
) -> PaperBookmarkList:
    try:
        items: List[PaperBookmarkWithPaper] = store.list_bookmarks(tag=tag, limit=limit)
        all_tags: List[str] = store.list_all_tags()
        return PaperBookmarkList(
            items=items,
            total=len(items),
            all_tags=all_tags,
        )
    except SQLAlchemyError as e:
        log.error(f"[bookmark] list 失败: {e}")
        raise HTTPException(status_code=500, detail=f"收藏列表查询失败: {e}")


# ---------------- Bulk helpers（论文列表行内渲染用） ----------------

class PaperFlagsRequest(BaseModel):
    """批量查询一批论文的收藏/标签信息（避免 N+1 请求）。"""
    paper_ids: List[str] = Field(..., min_length=1, max_length=500)


class PaperFlagsResponse(BaseModel):
    bookmarked: List[str] = Field(default_factory=list, description="被收藏的 paper_id 列表")
    tags_map: dict = Field(
        default_factory=dict,
        description="paper_id -> tags[] 映射",
    )


@router.post(
    "/papers/flags",
    response_model=PaperFlagsResponse,
    summary="批量查询论文的收藏/标签（论文列表行内 ⭐/🏷️ 渲染用）",
)
def get_paper_flags(payload: PaperFlagsRequest,
                     ) -> PaperFlagsResponse:
    try:
        bookmarked_ids = list(store.get_bookmarked_ids(payload.paper_ids))
        tags_map = store.get_tags_map_for_papers(payload.paper_ids)
        return PaperFlagsResponse(bookmarked=bookmarked_ids, tags_map=tags_map)
    except SQLAlchemyError as e:
        log.error(f"[bookmark] flags 失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量查询失败: {e}")
