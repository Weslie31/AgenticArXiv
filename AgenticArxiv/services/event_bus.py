# AgenticArxiv/services/event_bus.py
from __future__ import annotations

import json
import queue
import threading
import uuid
from typing import Dict, Tuple, Any

from fastapi.encoders import jsonable_encoder


class EventBus:
    """
    进程内事件总线（按 session 隔离）。
    - key = session_id
    - 每个订阅一个 thread-safe Queue，用于 SSE StreamingResponse 读取
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # key = session_id, value = { sub_id: queue.Queue }
        self._subs: Dict[str, Dict[str, "queue.Queue[str]"]] = {}

    def subscribe(self, session_id: str) -> Tuple[str, "queue.Queue[str]"]:
        """按 session_id 订阅；返回 (sub_id, queue)。"""
        sid = session_id or "default"
        sub_id = uuid.uuid4().hex
        q: "queue.Queue[str]" = queue.Queue()
        with self._lock:
            self._subs.setdefault(sid, {})[sub_id] = q
        return sub_id, q

    def unsubscribe(self, session_id: str, sub_id: str) -> None:
        sid = session_id or "default"
        with self._lock:
            m = self._subs.get(sid)
            if not m:
                return
            m.pop(sub_id, None)
            if not m:
                self._subs.pop(sid, None)

    def publish(self, session_id: str, event: Dict[str, Any]) -> None:
        """只广播给指定 session 的订阅者。"""
        sid = session_id or "default"

        try:
            safe_event = jsonable_encoder(event)
            data = json.dumps(safe_event, ensure_ascii=False)
        except Exception as e:
            data = json.dumps(
                {"type": "event_bus_error", "message": f"event serialization failed: {e}"},
                ensure_ascii=False,
            )

        with self._lock:
            m = self._subs.get(sid)
            if not m:
                return
            for q in list(m.values()):
                try:
                    q.put_nowait(data)
                except queue.Full:
                    pass
