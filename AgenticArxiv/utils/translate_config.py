"""解析翻译服务配置（service / api_key）。

集中在一处实现，避免两条翻译链路行为不一致：
  - services/translate_runner.py   （异步任务）
  - tools/pdf_translate_tool.py    （同步接口 / Agent 工具调用）
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

from config import settings
from utils.logger import log

# pdf2zh 各翻译器真正读取的环境变量名，见 pdf2zh/translator.py：
#   DeepLTranslator  -> DEEPL_AUTH_KEY
#   OpenAITranslator -> OPENAI_API_KEY / OPENAI_BASE_URL
#   AzureTranslator  -> AZURE_APIKEY / AZURE_ENDPOINT / AZURE_REGION
SERVICE_KEY_ENVS = {
    "deepl": "DEEPL_AUTH_KEY",
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_APIKEY",
}

# 无需 Key 的服务（google 走公开网页接口，bing 免登录）
KEYLESS_SERVICES = {"bing", "google", "deeplx", "ollama"}

# pdf2zh 这个版本实际支持的引擎（见 pdf2zh/converter.py）。
# 注意：不支持 bing，旧配置里若存了 bing 会直接 ValueError。
SUPPORTED_SERVICES = {"google", "deepl", "deeplx", "ollama", "openai", "azure"}


def service_prefix(service: str) -> str:
    """'openai:deepseek-chat' -> 'openai'"""
    return (service or "").split(":", 1)[0].strip().lower()


def service_requires_key(service: str) -> bool:
    prefix = service_prefix(service)
    if prefix in KEYLESS_SERVICES:
        return False
    return prefix in SERVICE_KEY_ENVS


def is_supported_service(service: str) -> bool:
    return service_prefix(service) in SUPPORTED_SERVICES


def _load_app_translate_config() -> Tuple[str, str]:
    """返回当前系统配置的 (service, api_key)，空字符串表示未配置。"""
    try:
        from services.app_settings import get_translate_config

        cfg = get_translate_config()
        return cfg.service, cfg.api_key
    except Exception as e:  # noqa: BLE001
        log.warning(f"读取翻译配置失败: {e}")
        return "", ""


def resolve_translate_service(explicit_service: Optional[str] = None) -> str:
    """解析本次翻译使用的 service。

    优先级：请求显式传入 > 系统配置 > settings.pdf2zh_service。
    若选择了需要 Key 的服务却没有保存 Key，则回退到系统默认，
    避免把系统的 Key 当成别家服务商的 Key 传出去。
    """
    if explicit_service:
        if not is_supported_service(explicit_service):
            log.warning(
                f"翻译服务 {explicit_service!r} 不受当前 pdf2zh 支持，"
                f"已回退到系统默认 {settings.pdf2zh_service!r}"
            )
            return settings.pdf2zh_service
        return explicit_service

    app_service, app_key = _load_app_translate_config()
    if not app_service:
        return settings.pdf2zh_service

    if not is_supported_service(app_service):
        log.warning(
            f"翻译服务 {app_service!r} 不受当前 pdf2zh 支持，"
            f"已回退到系统默认 {settings.pdf2zh_service!r}"
        )
        return settings.pdf2zh_service

    if service_requires_key(app_service) and not app_key:
        log.warning(
            f"翻译服务 {app_service!r} 未配置 API Key，"
            f"已回退到系统默认 {settings.pdf2zh_service!r}"
        )
        return settings.pdf2zh_service

    return app_service


def resolve_translate_api_key(service: str, explicit_key: Optional[str] = None) -> str:
    """解析本次翻译使用的 api_key（可能为空字符串）。

    优先级：显式传入 > 系统配置（服务一致时）> 环境变量。
    """
    if explicit_key:
        return explicit_key

    app_service, app_key = _load_app_translate_config()
    if app_key and (not app_service or app_service == service):
        return app_key

    return os.environ.get("TRANSLATE_API_KEY", "")
