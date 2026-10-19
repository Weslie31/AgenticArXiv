# AgenticArxiv/services/paper_summary_service.py
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional, Dict, Any

from config import settings
from models.schemas import PaperSummary, PaperSummaryStatus
from utils.logger import log


class PaperSummaryService:
    """论文总结服务（JSON 文件存储）"""

    def __init__(self, cache_path: Optional[str] = None):
        self.cache_path = cache_path or os.path.join(
            settings.pdf_raw_path, "..", "paper_summaries.json"
        )
        self.cache_path = os.path.abspath(self.cache_path)
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)

    def _load_cache(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"Failed to load paper_summary cache: {e}")
        return {}

    def _save_cache(self, cache: Dict[str, Dict[str, Any]]) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"Failed to save paper_summary cache: {e}")

    def get_summary(self, paper_id: str) -> Optional[PaperSummary]:
        """获取论文总结"""
        cache = self._load_cache()
        data = cache.get(paper_id)
        if not data:
            return None

        return PaperSummary(
            paper_id=paper_id,
            status=data.get("status", "NOT_SUMMARIZED"),
            background=data.get("background"),
            innovation=data.get("innovation"),
            summarized_at=datetime.fromisoformat(data["summarized_at"]) if data.get("summarized_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
            error=data.get("error"),
        )

    def save_summary(self, paper_id: str, summary: PaperSummary) -> None:
        """保存论文总结"""
        cache = self._load_cache()
        cache[paper_id] = {
            "status": summary.status,
            "background": summary.background,
            "innovation": summary.innovation,
            "summarized_at": summary.summarized_at.isoformat() if summary.summarized_at else None,
            "updated_at": datetime.now().isoformat(),
            "error": summary.error,
        }
        self._save_cache(cache)

    def update_summary(
        self,
        paper_id: str,
        status: Optional[PaperSummaryStatus] = None,
        background: Optional[str] = None,
        innovation: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[PaperSummary]:
        """更新论文总结"""
        existing = self.get_summary(paper_id)
        if existing:
            if status is not None:
                existing.status = status
            if background is not None:
                existing.background = background
            if innovation is not None:
                existing.innovation = innovation
            if error is not None:
                existing.error = error
            existing.updated_at = datetime.now()
            if status == "READY":
                existing.summarized_at = datetime.now()
            self.save_summary(paper_id, existing)
            return existing

        # Create new
        new_summary = PaperSummary(
            paper_id=paper_id,
            status=status or "NOT_SUMMARIZED",
            background=background,
            innovation=innovation,
            error=error,
        )
        if status == "READY":
            new_summary.summarized_at = datetime.now()
        self.save_summary(paper_id, new_summary)
        return new_summary

    def delete_summary(self, paper_id: str) -> bool:
        """删除论文总结"""
        cache = self._load_cache()
        if paper_id in cache:
            del cache[paper_id]
            self._save_cache(cache)
            return True
        return False

    def list_summaries(self) -> list[PaperSummary]:
        """列出所有论文总结"""
        cache = self._load_cache()
        summaries = []
        for paper_id, data in cache.items():
            summaries.append(PaperSummary(
                paper_id=paper_id,
                status=data.get("status", "NOT_SUMMARIZED"),
                background=data.get("background"),
                innovation=data.get("innovation"),
                summarized_at=datetime.fromisoformat(data["summarized_at"]) if data.get("summarized_at") else None,
                updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
                error=data.get("error"),
            ))
        return summaries


# Singleton instance
paper_summary_service = PaperSummaryService()
