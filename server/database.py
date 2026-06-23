"""数据库连接管理"""
from pathlib import Path

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import get as get_config
from server.models.user import Base


def _build_engine() -> Engine:
    """根据配置创建数据库引擎。"""
    url = get_config("database_url")
    if url:
        if url.startswith("sqlite"):
            return create_engine(
                url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False,
            )
        return create_engine(url, echo=False)

    # 默认 SQLite
    db_path = Path.home() / ".octopus" / "users.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )


_engine: Engine | None = None
_sessionmaker: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session():
    """获取一个新的数据库会话。"""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = sessionmaker(bind=get_engine())
    return _sessionmaker()


# 首次使用时自动建表
Base.metadata.create_all(get_engine())
