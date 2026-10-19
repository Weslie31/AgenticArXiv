# AgenticArxiv/utils/llm_client.py
import os
from typing import Any, Dict, List, Optional
import requests


def normalize_base_url(base_url: str) -> str:
    """把 base_url 归一化为「不含 /v1」的形式。

    用户既可能填 https://api.openai.com，也可能按惯例填
    https://api.openai.com/v1；两种写法都应该能用，避免拼出 /v1/v1。
    """
    url = (base_url or "").strip().rstrip("/")
    while url.endswith("/v1"):
        url = url[: -len("/v1")].rstrip("/")
    return url


def build_chat_completions_url(base_url: str) -> str:
    """由 base_url 生成 chat completions 的完整地址（带不带 /v1 都行）。"""
    return f"{normalize_base_url(base_url)}/v1/chat/completions"


class LLMClient:
    """
    对接 OpenAI-compatible /v1/chat/completions 接口
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: int = 60,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key
        self.timeout_s = timeout_s

    def chat_completions(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 1000,
        stream: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if extra:
            payload.update(extra)

        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout_s)
        # 把上游返回的详细错误也抛出来，便于排查
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise RuntimeError(
                f"LLM {resp.status_code} on {url} model={model}: {detail}"
            )
        resp.raise_for_status()
        return resp.json()


# 按 base_url 推断默认模型
def _default_model_for(base_url: str) -> str:
    """根据 base_url 推断合理的默认模型名，避免在不同 provider 之间硬编码。"""
    u = (base_url or "").lower()
    if "deepseek" in u:
        return os.getenv("LLM_MODEL", "deepseek-flash")
    if "dashscope" in u or "aliyun" in u:
        return os.getenv("LLM_MODEL", "qwen-plus")
    if "anthropic" in u:
        return os.getenv("LLM_MODEL", "claude-3-5-sonnet-latest")
    if "googleapis" in u or "generativelanguage" in u:
        return os.getenv("LLM_MODEL", "gemini-1.5-pro")
    # antigravity / openai 通用默认
    return os.getenv("LLM_MODEL", "gpt-4o-mini")


def get_env_llm_client(default_model: Optional[str] = None) -> LLMClient:
    """
    从 settings 读取（系统级默认）：
    - LLM_BASE_URL   默认: https://antigravity.byssted.cn
    - LLM_API_KEY    必须通过 .env 或环境变量提供
    - LLM_MODEL      可选：覆盖默认模型（通过 default_model 参数传入）
    环境变量 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 优先级高于 settings（向后兼容）。
    """
    from config import settings

    base_url = os.getenv("LLM_BASE_URL", settings.antigravity_base_url)
    api_key = os.getenv("LLM_API_KEY", settings.antigravity_api_key)
    if not api_key:
        raise RuntimeError("Missing API key: set LLM_API_KEY env var or config")
    return LLMClient(base_url=base_url, api_key=api_key)


def get_app_llm_client() -> LLMClient:
    """返回系统当前生效的 LLM client（app_settings > 环境变量 > config 默认值）。"""
    from services.app_settings import get_llm_config

    cfg = get_llm_config()
    return LLMClient(base_url=cfg.base_url, api_key=cfg.api_key)
