"""系统级配置（单用户部署）。

LLM 与翻译服务的设置保存在 app_settings 表（只有一行，id=1）。
未设置的字段回退到 config.py / 环境变量。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import IntegrityError

from models.db import get_sync_session
from models.orm import AppSettingsRow
from utils.logger import log


def _mask(key: str) -> str:
    k = key or ""
    if not k:
        return ""
    if len(k) <= 4:
        return k
    return "*" * 3 + k[-4:]


def _looks_masked(key: str) -> bool:
    return bool(key) and key.startswith("*" * 3) and len(key) <= 12


@dataclass
class LLMConfig:
    model: str
    base_url: str
    api_key: str
    is_default: bool = False
    warning: Optional[str] = None

    @property
    def api_key_masked(self) -> str:
        return _mask(self.api_key)


@dataclass
class TranslateConfig:
    service: str
    api_key: str
    is_default: bool = False

    @property
    def api_key_masked(self) -> str:
        return _mask(self.api_key)


def _get_row(db) -> AppSettingsRow:
    row = db.get(AppSettingsRow, 1)
    if row is not None:
        return row
    # 首次访问时 /llm/config 与 /translate/config 可能并发到达，两边都以为
    # 没有这一行而同时 INSERT，后到的一方会撞主键。这里把并发插入当作正常情况：
    # 回滚后重新读取对方已提交的行。
    try:
        row = AppSettingsRow(id=1)
        db.add(row)
        db.flush()
        return row
    except IntegrityError:
        db.rollback()
        row = db.get(AppSettingsRow, 1)
        if row is None:
            raise
        return row


def get_llm_config() -> LLMConfig:
    from config import settings

    system_model = settings.models.agent_model
    system_base = settings.antigravity_base_url
    system_key = settings.antigravity_api_key

    with get_sync_session() as db:
        row = _get_row(db)
        db.commit()
        model = (row.llm_model or "").strip()
        base_url = (row.llm_base_url or "").strip()
        api_key = (row.llm_api_key or "").strip()

    if base_url and not api_key:
        log.warning("自定义 Base URL 缺少 API Key，已整份回退到系统默认（避免系统 Key 外发）")
        return LLMConfig(
            model=system_model,
            base_url=system_base,
            api_key=system_key,
            is_default=True,
            warning=(
                "已保存的自定义 Base URL 缺少对应的 API Key，"
                "当前已回退到系统默认配置（系统 Key 不会发往第三方地址）"
            ),
        )

    is_default = not (model or base_url or api_key)
    return LLMConfig(
        model=model or system_model,
        base_url=base_url or system_base,
        api_key=api_key or system_key,
        is_default=is_default,
    )


def update_llm_config(base_url=..., api_key=..., model=...) -> None:
    """None/空串表示清空该字段；... 表示不修改。"""
    with get_sync_session() as db:
        row = _get_row(db)
        if base_url is not ...:
            row.llm_base_url = (base_url or "").strip() or None
        if api_key is not ...:
            key = (api_key or "").strip()
            if _looks_masked(key):
                raise ValueError("请填写完整的 API Key，不能提交脱敏后的值（***xxxx）")
            row.llm_api_key = key or None
        if model is not ...:
            row.llm_model = (model or "").strip() or None
        db.commit()


def reset_llm_config() -> None:
    with get_sync_session() as db:
        row = _get_row(db)
        row.llm_model = None
        row.llm_base_url = None
        row.llm_api_key = None
        db.commit()


def get_translate_config() -> TranslateConfig:
    from config import settings
    from utils.translate_config import is_supported_service

    with get_sync_session() as db:
        row = _get_row(db)
        db.commit()
        service = (row.translate_service or "").strip()
        key = (row.translate_api_key or "").strip()

    if service and not is_supported_service(service):
        log.warning("翻译服务不受当前 pdf2zh 支持，已回退到系统默认")
        service = ""

    return TranslateConfig(
        service=service or settings.pdf2zh_service,
        api_key=key or os.getenv("TRANSLATE_API_KEY", ""),
        is_default=not service,
    )


def update_translate_config(service=..., api_key=...) -> None:
    with get_sync_session() as db:
        row = _get_row(db)
        if service is not ...:
            svc = (service or "").strip()
            if svc:
                from utils.translate_config import is_supported_service
                if not is_supported_service(svc):
                    raise ValueError(f"不支持的翻译服务: {svc}")
            row.translate_service = svc or None
        if api_key is not ...:
            key = (api_key or "").strip()
            if _looks_masked(key):
                raise ValueError("请填写完整的 API Key，不能提交脱敏后的值（***xxxx）")
            row.translate_api_key = key or None
        db.commit()


def reset_translate_config() -> None:
    with get_sync_session() as db:
        row = _get_row(db)
        row.translate_service = None
        row.translate_api_key = None
        db.commit()
