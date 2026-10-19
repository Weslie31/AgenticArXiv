# AgenticArxiv/api/app.py
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ensure tools are registered (side-effect import)
import tools.arxiv_tool  # noqa: F401
import tools.openalex_tool  # noqa: F401
import tools.pdf_download_tool  # noqa: F401
import tools.pdf_translate_tool  # noqa: F401
import tools.cache_status_tool  # noqa: F401
import tools.rag_tool  # noqa: F401

from api.endpoints import router as api_router
from models.db import init_db
from models.store import store
from utils.logger import log


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Initializing database tables...")
    init_db()
    store.validate_local_paths()

    # 清理残留的下载锁文件
    from config import settings
    import os, glob
    lock_dirs = [settings.pdf_raw_path, settings.pdf_translated_path]
    cleaned = []
    for d in lock_dirs:
        if os.path.isdir(d):
            for lf in glob.glob(os.path.join(d, "*.lock")):
                try:
                    os.remove(lf)
                    cleaned.append(lf)
                except OSError:
                    pass
    if cleaned:
        log.info(f"清理残留锁文件: {cleaned}")
    else:
        log.info("无残留锁文件。")
    log.info("Database ready.")

    # 启动订阅调度器（后台线程，避免阻塞 uvicorn 启动）
    log.info("Starting subscription scheduler...")
    from scheduler.runner import get_scheduler
    import threading
    scheduler = get_scheduler()
    # 在后台线程启动（注册定时任务），不阻塞
    threading.Thread(target=scheduler.start, daemon=True).start()
    log.info("Subscription scheduler started.")

    yield
    log.info("Shutting down...")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agentic Arxiv API",
        version="0.2.0",
        description="Expose ToolRegistry tools via FastAPI (MySQL-backed)",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        # 凭据模式下不能使用 "*"，必须显式列出允许的来源。
        # 默认允许本地开发端口；生产环境请通过环境变量 CORS_ORIGINS 注入，逗号分隔。
        allow_origins=[
            o.strip()
            for o in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
            ).split(",")
            if o.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root():
        return {"msg": "Agentic Arxiv API is running", "docs": "/docs"}

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
