# AgenticArxiv/models/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.mysql_uri,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

SyncSessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def get_sync_session() -> Session:
    return SyncSessionLocal()


# FastAPI 依赖注入工厂
def get_db() -> Session:
    """FastAPI Depends 用的 DB session 工厂。

    用完由 FastAPI 自动关闭（通过 try/finally），避免连接泄漏。
    """
    s = SyncSessionLocal()
    try:
        yield s
    finally:
        try:
            s.close()
        except Exception:
            pass


class session_scope:
    """
    Session 上下文管理器，兼容现有 get_sync_session() 用法。

    用法（与现有 store.py / log_service.py 完全一致）:
        with session_scope() as s:
            s.query(...)
            s.add(...)
            s.commit()
    """

    def __enter__(self) -> Session:
        self._session = get_sync_session()
        return self._session

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._session.rollback()
        self._session.close()
        return False


def init_db():
    """Create all tables (safe to call repeatedly)."""
    import models.orm  # noqa: F401 — ensure all models are registered
    Base.metadata.create_all(bind=engine)
