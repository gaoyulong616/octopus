"""数据库连接管理"""
import logging
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from server.models.user import Base

# 使用 ~/.local/share/octopus/ 存放数据库以避开 macOS com.apple.provenance 只读问题
DB_PATH = Path.home() / ".local" / "share" / "octopus" / "users.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False
)
Session = sessionmaker(bind=engine)

Base.metadata.create_all(engine)

# 迁移：为新加的列做 ALTER TABLE ADD COLUMN（create_all 不会修改已有表）
try:
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
        for col, col_type in (("name", "VARCHAR(64)"),):
            if col not in cols:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type}"))
                conn.commit()
except Exception as e:
    logging.exception("users 表迁移失败: %s", e)