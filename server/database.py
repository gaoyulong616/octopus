"""数据库连接管理（SQLite）"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.models.user import Base

# 数据库路径
DB_PATH = Path.home() / ".octopus" / "users.db"

# 创建引擎
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},  # SQLite 多线程支持
)

# Session 工厂
Session = sessionmaker(bind=engine)


def init_db():
    """初始化数据库表"""
    # 确保目录存在
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 创建表
    Base.metadata.create_all(engine)
