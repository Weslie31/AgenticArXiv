# AgenticArxiv/scheduler/user_config.py
"""用户在设置面板配置的定时检索参数，保存到本地 JSON 文件。"""
from __future__ import annotations

import json
import os
import threading
from typing import List, Optional

_LOCK = threading.Lock()

# 间隔（分钟）-> 拉取天数（days）的映射
INTERVAL_DAYS_MAP = {
    5: 1,
    360: 3,        # 6 小时
    1440: 3,       # 1 天
    4320: 3,       # 3 天
    10080: 7,      # 7 天
}

DEFAULT_INTERVAL_OPTIONS = [5, 360, 1440, 4320, 10080]
DEFAULT_INTERVAL = 360  # 6 小时
DEFAULT_MAX_RESULTS = 20
DEFAULT_ASPECTS: List[str] = []
DEFAULT_ENABLED = True


def _config_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "data", "scheduler_user_config.json")


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def load_user_schedule() -> dict:
    """读取用户配置；不存在则返回默认值。"""
    path = _config_path()
    with _LOCK:
        if not os.path.exists(path):
            return {
                "interval_minutes": DEFAULT_INTERVAL,
                "aspects": list(DEFAULT_ASPECTS),
                "max_results": DEFAULT_MAX_RESULTS,
                "enabled": DEFAULT_ENABLED,
            }
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    return {
        "interval_minutes": data.get("interval_minutes", DEFAULT_INTERVAL),
        "aspects": data.get("aspects", list(DEFAULT_ASPECTS)),
        "max_results": data.get("max_results", DEFAULT_MAX_RESULTS),
        "enabled": data.get("enabled", DEFAULT_ENABLED),
    }


def save_user_schedule(
    *,
    interval_minutes: int,
    aspects: List[str],
    max_results: int,
    enabled: bool,
) -> dict:
    """保存并返回生效后的配置。"""
    # 字段约束
    if interval_minutes not in INTERVAL_DAYS_MAP:
        # 允许自定义值，但 snap 到最近档；这里为简单直接接受
        pass
    aspects = [a.strip() for a in aspects if a and a.strip()][:5]
    max_results = max(1, min(100, int(max_results)))
    payload = {
        "interval_minutes": int(interval_minutes),
        "aspects": aspects,
        "max_results": max_results,
        "enabled": bool(enabled),
    }
    path = _config_path()
    _ensure_dir(path)
    with _LOCK:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def interval_to_days(interval_minutes: int) -> int:
    """根据间隔（分钟）反算 arxiv 拉取的天数。"""
    return INTERVAL_DAYS_MAP.get(int(interval_minutes), 7)


# ============================================================
# 各订阅独立 enabled 状态持久化
# ============================================================

def _subscription_states_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(
        os.path.dirname(here), "data", "scheduler_subscription_states.json"
    )


def load_subscription_states() -> dict:
    """读取每个订阅独立的 enabled 状态。
    返回 {subscription_id: enabled_bool}。
    文件不存在或损坏返回空 dict（保持默认 True）。"""
    path = _subscription_states_path()
    with _LOCK:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    return {
        str(k): bool(v)
        for k, v in data.items()
        if isinstance(k, str)
    }


def save_subscription_enabled(sub_id: str, enabled: bool) -> None:
    """保存单个订阅的 enabled 状态。"""
    path = _subscription_states_path()
    _ensure_dir(path)
    with _LOCK:
        states: dict = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    states = json.load(f) or {}
            except Exception:
                states = {}
        states[str(sub_id)] = bool(enabled)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(states, f, ensure_ascii=False, indent=2)


def remove_subscription_state(sub_id: str) -> None:
    """从持久化文件中删除单个订阅的状态记录。"""
    path = _subscription_states_path()
    if not os.path.exists(path):
        return
    with _LOCK:
        try:
            with open(path, "r", encoding="utf-8") as f:
                states = json.load(f) or {}
        except Exception:
            return
        if str(sub_id) in states:
            states.pop(str(sub_id), None)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(states, f, ensure_ascii=False, indent=2)