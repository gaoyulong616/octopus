"""认证核心：JWT + 密码"""
from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Any

import bcrypt
import jwt

# JWT 配置
_JWT_SECRET_FILE = Path.home() / ".octopus" / ".jwt_secret"

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7  # 7 天


def _load_jwt_secret() -> str:
    """加载或生成 JWT secret"""
    secret_file = _JWT_SECRET_FILE
    if secret_file.exists():
        return secret_file.read_text().strip()
    # 生成新 secret
    secret = secrets.token_urlsafe(32)
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(secret)
    return secret


JWT_SECRET = _load_jwt_secret()


def hash_password(password: str) -> str:
    """密码哈希（bcrypt rounds=12）"""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码（恒定时间比较）"""
    if not password_hash:
        return False
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: str, token_version: int) -> str:
    """签发 JWT"""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + JWT_EXPIRE_HOURS * 3600,
        "v": token_version,  # 版本号，换密码时递增
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, token_version: int) -> str:
    """签发 Refresh Token（有效期 30 天）"""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + 30 * 24 * 3600,
        "v": token_version,
        "type": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str, token_version: int) -> dict[str, Any] | None:
    """验证 token，返回 payload 或 None"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        # 检查版本号
        if payload.get("v", 0) != token_version:
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def decode_token_unsafe(token: str) -> dict[str, Any] | None:
    """不解密版本号，仅解析 payload（用于日志）"""
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None
