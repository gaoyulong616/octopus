"""数据库连接管理"""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.models.user import Base

DB_PATH = Path.home() / ".octopus" / "users.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False
)
Session = sessionmaker(bind=engine)

Base.metadata.create_all(engine)