"""用户模型"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: uuid.uuid4().hex[:16]
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # SSO
    sso_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sso_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # JWT 版本号（换密码时递增，使旧 token 失效）
    token_version: Mapped[int] = mapped_column(default=0)

    @property
    def home_dir(self) -> Path:
        """用户根目录"""
        return Path.home() / ".octopus" / "users" / self.id

    def ensure_dirs(self):
        """确保用户目录结构存在"""
        (self.home_dir / "projects").mkdir(parents=True, exist_ok=True)
