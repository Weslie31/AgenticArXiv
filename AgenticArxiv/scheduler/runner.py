# AgenticArxiv/scheduler/runner.py
"""定时论文订阅调度器（单用户）。

- 订阅配置保存在 `subscriptions` 表，内存缓存 `_subs`。
- 每个启用的订阅按 `interval_minutes` 单独排定时任务。
- 执行结果持久化到 `subscription_runs` 表。
- SSE 事件按 session_id 广播。
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

import schedule

# 确保工具被注册
import tools.arxiv_tool  # noqa: F401
import tools.openalex_tool  # noqa: F401

from models.schemas import Paper
from models.store import store
from scheduler.subscription import DEFAULT_SUBSCRIPTIONS, Subscription, SubscriptionResult
from services.event_bus import EventBus
from tools.tool_registry import registry
from utils.logger import log

USER_SUBSCRIPTION_ID = "daily_user"
DEFAULT_MAX_RESULTS = 20


# ---------- helpers ----------


def _load_subscriptions_from_db() -> List[Subscription]:
    from models.db import get_sync_session
    from models.orm import SubscriptionRow

    subs: List[Subscription] = []
    with get_sync_session() as db:
        for r in db.query(SubscriptionRow).all():
            try:
                aspects = json.loads(r.aspects_json or "[]")
                keywords = json.loads(r.keywords_json or "[]")
                exclude = json.loads(r.exclude_keywords_json or "[]")
            except Exception:
                aspects, keywords, exclude = [], [], []

            subs.append(Subscription(
                id=r.sub_id,
                name=r.name or r.sub_id,
                aspects=aspects,
                keywords=keywords,
                exclude_keywords=exclude,
                days=r.days or 7,
                max_results=r.max_results or 15,
                enabled=bool(r.enabled),
                session_id=r.session_id or "default",
                interval_minutes=r.interval_minutes,
                match_mode=(r.match_mode or "any"),
                last_run_at=r.last_run_at,
                last_run_count=r.last_run_count or 0,
            ))
    return subs


def _persist_sub_result(sub_id: str, name: str, result: SubscriptionResult) -> None:
    from models.db import get_sync_session
    from models.orm import SubscriptionRunRow

    with get_sync_session() as db:
        db.add(SubscriptionRunRow(
            sub_id=sub_id,
            subscription_name=name,
            papers_count=result.papers_count,
            new_papers_count=result.new_papers_count,
            duration_ms=result.duration_ms,
            errors_json=json.dumps(result.errors, ensure_ascii=False),
            papers_json=json.dumps(result.papers, ensure_ascii=False),
            run_at=result.run_at,
        ))
        db.commit()


# ---------- Scheduler ----------


class SubscriptionScheduler:
    """定时论文订阅调度器。"""

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus or EventBus()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._subs: Dict[str, Subscription] = {}
        self._last_results: Dict[str, SubscriptionResult] = {}
        self._last_fetched_papers: Dict[str, List[Paper]] = {}
        self._keyword_translation_cache: Dict[tuple, List[str]] = {}
        self._loaded = False

    # -------------------- 订阅 CRUD --------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        for sub in _load_subscriptions_from_db():
            self._subs[sub.id] = sub
        self._loaded = True

    def get_subscriptions(self) -> List[Subscription]:
        self._ensure_loaded()
        return list(self._subs.values())

    def get_subscription(self, sub_id: str) -> Optional[Subscription]:
        self._ensure_loaded()
        return self._subs.get(sub_id)

    def add_subscription(self, sub: Subscription) -> Subscription:
        self._ensure_loaded()
        self._subs[sub.id] = sub
        self._save_subscription_to_db(sub)
        if self._running:
            self._reschedule()
        log.info(f"[Scheduler] 添加订阅: sub={sub.name} (id={sub.id})")
        return sub

    def update_subscription(self, sub_id: str, **kwargs) -> Optional[Subscription]:
        self._ensure_loaded()
        sub = self._subs.get(sub_id)
        if not sub:
            return None
        for k, v in kwargs.items():
            if hasattr(sub, k):
                setattr(sub, k, v)
        self._save_subscription_to_db(sub)
        if self._running:
            self._reschedule()
        return sub

    def remove_subscription(self, sub_id: str) -> bool:
        self._ensure_loaded()
        if sub_id not in self._subs:
            return False
        self._subs.pop(sub_id, None)
        from models.db import get_sync_session
        from models.orm import SubscriptionRow

        with get_sync_session() as db:
            db.query(SubscriptionRow).filter_by(sub_id=sub_id).delete()
            db.commit()
        if self._running:
            self._reschedule()
        return True

    # -------------------- 定时任务 --------------------

    def _clear_jobs(self) -> None:
        for job in list(schedule.get_jobs()):
            tags = {str(t) for t in job.tags}
            if any(t == "sub" or t.startswith("sub-") for t in tags):
                try:
                    schedule.cancel_job(job)
                except Exception:
                    pass

    def _schedule_subscription(self, sub: Subscription) -> None:
        if not sub.enabled or not sub.interval_minutes:
            return
        interval = max(1, int(sub.interval_minutes))
        tag = f"sub-{sub.id}"

        def _job(sid: str = sub.id) -> None:
            log.info(f"[Scheduler] sub={sid} 定时任务触发")
            try:
                self.run_subscription(sid)
            except Exception as e:
                log.warning(f"[Scheduler] sub={sid} 执行失败: {e}")

        schedule.every(interval).minutes.do(_job).tag(tag)
        log.info(f"[Scheduler] sub={sub.id} 每 {interval} 分钟")

    def _reschedule(self) -> None:
        self._clear_jobs()
        subs = self.get_subscriptions()
        for sub in subs:
            self._schedule_subscription(sub)
        active = sum(1 for s in subs if s.enabled and s.interval_minutes)
        log.info(f"[Scheduler] 重排完成: {active} 个定时任务")

    # -------------------- 关键词处理 --------------------

    def _translate_keywords_to_en(self, keywords: List[str]) -> List[str]:
        """含中文的关键词交给 LLM 翻成英文标题检索词（带进程内缓存）。"""
        if not keywords:
            return []
        has_cjk = any(
            any("\u4e00" <= ch <= "\u9fff" for ch in kw) for kw in keywords
        )
        if not has_cjk:
            return keywords

        cache_key = tuple(keywords)
        cached = self._keyword_translation_cache.get(cache_key)
        if cached:
            return cached

        try:
            from services.app_settings import get_llm_config
            from utils.llm_client import get_app_llm_client

            llm = get_app_llm_client()
            model = get_llm_config().model
            prompt = (
                "把下面的中文论文检索关键词翻译成英文学术检索词"
                "（用于匹配英文论文标题），只输出 JSON 字符串数组，不要解释：\n"
                + json.dumps(keywords, ensure_ascii=False)
            )
            resp = llm.chat_completions(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=800,
            )
            content = resp["choices"][0]["message"].get("content") or ""
            start, end = content.find("["), content.rfind("]")
            if start != -1 and end > start:
                arr = json.loads(content[start: end + 1])
                translated = [str(x).strip() for x in arr if str(x).strip()]
                if translated:
                    self._keyword_translation_cache[cache_key] = translated
                    log.info(f"[订阅拉取] 关键词翻译: {keywords} -> {translated}")
                    return translated
        except Exception as e:  # noqa: BLE001
            log.warning(f"[订阅拉取] 关键词翻译失败，使用原文: {e}")
        return keywords

    def _filter_papers(
        self,
        papers: List[dict],
        keywords: List[str],
        exclude_keywords: List[str],
        max_results: int,
    ) -> List[dict]:
        if not keywords and not exclude_keywords:
            return papers[:max_results]
        scored: List[tuple] = []
        for p in papers:
            title = (p.get("title") or "").lower()
            if any(kw.lower() in title for kw in exclude_keywords):
                continue
            score = self._keyword_score(title, keywords) if keywords else 0
            if keywords and score <= 0:
                continue
            scored.append((score, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:max_results]]

    @staticmethod
    def _keyword_score(title: str, keywords: List[str]) -> int:
        """返回标题完整命中的关键词个数。"""
        t = (title or "").lower()
        hits = 0
        for kw in keywords:
            parts = [p for p in re.split(r"[\s\-_/]+", (kw or "").lower()) if p]
            if parts and all(p in t for p in parts):
                hits += 1
        return hits

    @staticmethod
    def _keyword_partial_score(title: str, keywords: List[str]) -> int:
        t = (title or "").lower()
        return sum(
            1
            for kw in keywords
            for part in re.split(r"[\s\-_/]+", (kw or "").lower())
            if part and part in t
        )

    # -------------------- 执行 --------------------

    def fetch_subscription(self, sub: Subscription) -> SubscriptionResult:
        start_time = time.time()
        result = SubscriptionResult(
            subscription_id=sub.id,
            subscription_name=sub.name,
            papers_count=0,
            new_papers_count=0,
            errors=[],
        )
        aspects_str = ", ".join(sub.aspects) if sub.aspects else "<none>"
        log.info(
            f"[订阅拉取] name={sub.name} id={sub.id} "
            f"aspects=[{aspects_str}] days={sub.days} max_results={sub.max_results}"
        )

        try:
            all_papers = []
            seen_ids = set()
            try:
                existing_ids = {
                    p.id for p in store.get_session_papers(sub.session_id) if p.id
                }
            except Exception as e:  # noqa: BLE001
                log.warning(f"[订阅拉取] 读取会话已有论文失败: {e}")
                existing_ids = set()
            aspects_cfg = [a for a in (sub.aspects or []) if a]
            aspects = aspects_cfg or ["*"]
            if not aspects_cfg:
                log.info("[订阅拉取] 未配置分类，按全部 CS 检索")
            keywords = self._translate_keywords_to_en(sub.keywords)
            match_mode = (getattr(sub, "match_mode", "any") or "any").lower()
            fallback_used = False
            per_aspect_limit = (
                min((sub.max_results or 15) * 10, 200)
                if keywords else (sub.max_results or 15) * 3
            )
            for aspect in aspects:
                aspect_start = time.time()
                try:
                    raw = registry.execute_tool(
                        "get_recently_submitted_cs_papers",
                        {
                            "aspect": aspect,
                            "days": sub.days,
                            "max_results": per_aspect_limit,
                            "save_to_file": False,
                            "keywords": keywords or None,
                            "exclude_keywords": sub.exclude_keywords or None,
                            "exclude_paper_ids": list(existing_ids)[:500] or None,
                            "match_mode": match_mode,
                        },
                    )
                    if match_mode == "all" and not raw and keywords:
                        raw = registry.execute_tool(
                            "get_recently_submitted_cs_papers",
                            {
                                "aspect": aspect,
                                "days": sub.days,
                                "max_results": per_aspect_limit,
                                "save_to_file": False,
                                "keywords": keywords,
                                "exclude_keywords": sub.exclude_keywords or None,
                                "exclude_paper_ids": list(existing_ids)[:500] or None,
                                "match_mode": "any",
                            },
                        )
                        fallback_used = True
                    if isinstance(raw, list):
                        for p in raw:
                            if p.get("id") not in seen_ids:
                                all_papers.append(p)
                                seen_ids.add(p.get("id"))
                    log.info(
                        f"[订阅拉取] ↳ aspect={aspect} "
                        f"拉取到 {len(raw) if isinstance(raw, list) else 0} 篇 "
                        f"累计 {len(all_papers)} 用时 {(time.time() - aspect_start) * 1000:.0f}ms"
                    )
                except Exception as e:
                    result.errors.append(f"获取 {aspect} 失败: {str(e)}")
                    log.warning(f"订阅 {sub.id} 获取 {aspect} 失败: {e}")

            if keywords:
                if fallback_used:
                    result.errors.append(
                        "全部关键词同时命中的论文不足，已回退为“任一关键词”匹配"
                    )
                filtered = all_papers[: sub.max_results]
            else:
                filtered = self._filter_papers(
                    all_papers, [], sub.exclude_keywords, sub.max_results
                )
            log.info(f"[订阅拉取] 过滤: {len(all_papers)} → {len(filtered)} 篇")

            papers = [Paper(**p) for p in filtered if p.get("id")]
            new_papers = [p for p in papers if p.id not in existing_ids]
            fetched_at = datetime.now()

            store.set_last_papers(
                session_id=sub.session_id,
                papers=papers,
                merge=True,
                fetched_at=fetched_at,
                fetch_type="subscription",
            )
            log.info(f"[订阅拉取] 已写入 session={sub.session_id} 共 {len(papers)} 篇")

            sub.last_run_at = fetched_at
            sub.last_run_count = len(new_papers)
            self._subs[sub.id] = sub

            result.papers_count = len(all_papers)
            result.new_papers_count = len(new_papers)
            self._last_fetched_papers[sub.id] = list(papers)
            result.papers = [{"id": p.id, "title": p.title} for p in new_papers]
            result.duration_ms = int((time.time() - start_time) * 1000)

            self.event_bus.publish(
                sub.session_id,
                {
                    "type": "subscription_update",
                    "subscription_id": sub.id,
                    "subscription_name": sub.name,
                    "papers_count": len(new_papers),
                    "total_fetched": result.papers_count,
                    "errors": result.errors,
                    "duration_ms": result.duration_ms,
                },
            )

            _persist_sub_result(sub.id, sub.name, result)
            log.info(
                f"[订阅拉取] 完成: name={sub.name} "
                f"fetched={result.papers_count} filtered={result.new_papers_count} "
                f"duration={result.duration_ms}ms errors={len(result.errors)}"
            )
        except Exception as e:
            result.errors.append(str(e))
            result.duration_ms = int((time.time() - start_time) * 1000)
            log.error(f"订阅 {sub.id} 执行失败: {e}")

        self._last_results[sub.id] = result
        return result

    def run_all(self) -> List[SubscriptionResult]:
        """立即执行所有启用的订阅。"""
        subs = self.get_subscriptions()
        results = []
        all_papers: List[Paper] = []
        seen_ids = set()
        user_sub = next((s for s in subs if s.id == USER_SUBSCRIPTION_ID), None)
        global_max = (user_sub.max_results or DEFAULT_MAX_RESULTS) if user_sub else DEFAULT_MAX_RESULTS

        for sub in subs:
            if not sub.enabled:
                continue
            original_max = sub.max_results
            sub.max_results = min(sub.max_results, global_max)
            result = self.fetch_subscription(sub)
            results.append(result)
            sub.max_results = original_max

            for p in self._last_fetched_papers.get(sub.id, []):
                if p.id not in seen_ids:
                    all_papers.append(p)
                    seen_ids.add(p.id)

        if len(all_papers) > global_max:
            all_papers = all_papers[:global_max]

        if all_papers:
            store.set_last_papers(
                session_id="default",
                papers=all_papers,
                merge=True,
                fetch_type="subscription",
            )
            log.info(f"订阅合并完成: 共 {len(all_papers)} 篇论文")

        return results

    def run_subscription(self, sub_id: str) -> Optional[SubscriptionResult]:
        sub = self.get_subscription(sub_id)
        if not sub:
            return None
        return self.fetch_subscription(sub)

    def get_result(self, sub_id: str) -> Optional[SubscriptionResult]:
        return self._last_results.get(sub_id)

    # -------------------- 生命周期 --------------------

    def _schedule_loop(self):
        log.info("[Scheduler] 订阅调度器已启动")
        while self._running:
            try:
                schedule.run_pending()
            except Exception as e:
                log.warning(f"[Scheduler] run_pending 出错: {e}", exc_info=True)
            time.sleep(30)
        log.info("[Scheduler] 订阅调度器已停止")

    def start(self):
        if self._running:
            log.warning("调度器已在运行中")
            return
        self._running = True
        self._thread = threading.Thread(target=self._schedule_loop, daemon=True)
        self._thread.start()
        try:
            self._ensure_loaded()
            if not self._subs:
                for sub in DEFAULT_SUBSCRIPTIONS:
                    self._subs[sub.id] = sub
                    self._save_subscription_to_db(sub)
                log.info("[Scheduler] 初始化默认订阅")
            self._reschedule()
            log.info(f"[Scheduler] 已恢复 {len(self._subs)} 个订阅")
        except Exception as e:
            log.warning(f"[Scheduler] 恢复定时任务失败: {e}")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    # -------------------- 持久化 --------------------

    def _save_subscription_to_db(self, sub: Subscription) -> None:
        from models.db import get_sync_session
        from models.orm import SubscriptionRow

        with get_sync_session() as db:
            row = db.query(SubscriptionRow).filter_by(sub_id=sub.id).first()
            if not row:
                row = SubscriptionRow(sub_id=sub.id)
                db.add(row)
            row.name = sub.name
            row.aspects_json = json.dumps(sub.aspects, ensure_ascii=False)
            row.keywords_json = json.dumps(sub.keywords, ensure_ascii=False)
            row.exclude_keywords_json = json.dumps(sub.exclude_keywords, ensure_ascii=False)
            row.days = sub.days
            row.max_results = sub.max_results
            row.enabled = sub.enabled
            row.session_id = sub.session_id
            row.interval_minutes = sub.interval_minutes
            row.match_mode = getattr(sub, "match_mode", "any") or "any"
            row.last_run_at = sub.last_run_at
            row.last_run_count = sub.last_run_count
            db.commit()


# ---------- 全局单例 ----------

_scheduler: Optional[SubscriptionScheduler] = None


def get_scheduler(event_bus: Optional[EventBus] = None) -> SubscriptionScheduler:
    global _scheduler
    if _scheduler is None:
        from services.runtime import event_bus as _event_bus
        _scheduler = SubscriptionScheduler(event_bus or _event_bus)
    return _scheduler


def start_scheduler(event_bus: Optional[EventBus] = None):
    scheduler = get_scheduler(event_bus)
    scheduler.start()
    return scheduler
