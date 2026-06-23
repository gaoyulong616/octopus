"""认证核心：JWT + 密码"""
from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Any

import bcrypt
import jwt

from server.database import get_session as Session
from server.models.user import User

JWT_SECRET_PATH = Path.home() / ".octopus" / ".jwt_secret"

if JWT_SECRET_PATH.exists():
    with open(JWT_SECRET_PATH, "r") as f:
        JWT_SECRET = f.read().strip()
else:
    JWT_SECRET = secrets.token_urlsafe(32)
    JWT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(JWT_SECRET_PATH, "w") as f:
        f.write(JWT_SECRET)

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7
JWT_REFRESH_HOURS = 24 * 30


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: str, token_version: int) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + JWT_EXPIRE_HOURS * 3600,
        "v": token_version,
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, token_version: int) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + JWT_REFRESH_HOURS * 3600,
        "v": token_version,
        "type": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_user_from_token(token: str) -> User | None:
    payload = verify_token(token)
    if not payload:
        return None
    with Session() as db:
        user = db.query(User).filter(User.id == payload["sub"]).first()
        if not user or not user.is_active:
            return None
        if payload.get("v", 0) != user.token_version:
            return None
        return user