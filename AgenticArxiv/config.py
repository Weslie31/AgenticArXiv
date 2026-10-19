# AgenticArxiv/config.py
import os

# 必须在任何 os.getenv 之前加载 .env，否则 dataclass field 默认值已定死。
try:
    from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_env_path, override=True)
except Exception:
    pass

from dataclasses import dataclass


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")


@dataclass(frozen=True)
class LLMModels:
    agent_model: str = os.getenv("MODEL", "deepseek-v4-flash")
    translate_model: str = "tab_flash_lite_preview"


@dataclass(frozen=True)
class Settings:
    antigravity_base_url: str = os.getenv(
        "LLM_BASE_URL", "https://antigravity.byssted.cn"
    )
    # 必须在 AgenticArxiv/.env 中配置 LLM_API_KEY（或设置同名环境变量）
    antigravity_api_key: str = os.getenv("LLM_API_KEY", "")
    models: LLMModels = LLMModels()

    # --- PDF download/cache ---
    pdf_raw_path: str = os.getenv(
        "PDF_RAW_PATH", os.path.join(DEFAULT_OUTPUT_DIR, "pdf_raw")
    )
    pdf_cache_path: str = os.getenv(
        "PDF_CACHE_PATH", os.path.join(DEFAULT_OUTPUT_DIR, "pdf_cache.json")
    )

    # --- PDF translate/cache ---
    pdf_translated_path: str = os.getenv(
        "PDF_TRANSLATED_PATH", os.path.join(DEFAULT_OUTPUT_DIR, "pdf_translated")
    )
    pdf_translated_log_path: str = os.getenv(
        "PDF_TRANSLATED_LOG_PATH", os.path.join(DEFAULT_OUTPUT_DIR, "pdf_translated_log")
    )
    translate_cache_path: str = os.getenv(
        "TRANSLATE_CACHE_PATH", os.path.join(DEFAULT_OUTPUT_DIR, "translate_cache.json")
    )

    # --- pdf2zh CLI ---
    pdf2zh_bin: str = os.getenv("PDF2ZH_BIN", "pdf2zh")
    pdf2zh_service: str = os.getenv("PDF2ZH_SERVICE", "openai:deepseek-v4-flash")
    pdf2zh_threads: int = int(os.getenv("PDF2ZH_THREADS", "4"))

    # --- MySQL ---
    mysql_uri: str = os.getenv(
        "MYSQL_URI",
        "mysql+pymysql://arxiv:change-me@127.0.0.1:3306/agentic_arxiv?charset=utf8mb4",
    )


settings = Settings()
