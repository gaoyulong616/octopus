"""认证路由：登录/注册/登出/token刷新

多用户认证核心：JWT 签发/验证、密码哈希、邮箱找回（占位）、管理员功能。
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from threading import Lock

from fastapi import APIRouter, Body, HTTPException, Request, Response
from pydantic import BaseModel

from server.auth import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from server.database import Session
from server.models.user import User

router = APIRouter(prefix="/api/auth")


# ── 登录限流（防暴力破解） ──

_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_LOGIN_LOCK = Lock()
_LOGIN_WINDOW = 60  # 60 秒
_LOGIN_MAX_ATTEMPTS = 10  # 最多 10 次失败


def _check_login_rate_limit(username: str, ip: str) -> None:
    """检查登录限流。失败次数过多时返回 429。"""
    with _LOGIN_LOCK:
        now = time.time()
        key = f"{username}:{ip}"
        attempts = [t for t in _LOGIN_ATTEMPTS[key] if now - t < _LOGIN_WINDOW]
        if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试")
        _LOGIN_ATTEMPTS[key] = attempts


def _record_login_attempt(username: str, ip: str, success: bool) -> None:
    """记录登录尝试。成功时清空失败计数。"""
    with _LOGIN_LOCK:
        key = f"{username}:{ip}"
        if success:
            _LOGIN_ATTEMPTS.pop(key, None)
        else:
            _LOGIN_ATTEMPTS[key].append(time.time())


# ── Request/Response Models ──────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    username: str | None = None
    email: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: str


# ── 辅助 ──

def _get_client_ip(request: Request) -> str:
    """获取客户端 IP（支持反向代理）"""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Routes ──────────────────────────────────────────────────────────────────

@router.post("/register")
async def register(body: RegisterRequest, request: Request):
    """用户注册（首个用户自动设为管理员）"""
    if len(body.username) < 3 or len(body.username) > 64:
        raise HTTPException(status_code=400, detail="用户名需 3-64 字符")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6个字符")
    # 简单的用户名规则：只允许字母数字下划线连字符
    if not all(c.isalnum() or c in "_-." for c in body.username):
        raise HTTPException(status_code=400, detail="用户名只能包含字母、数字、下划线、连字符、点")

    with Session() as db:
        existing = db.query(User).filter(User.username == body.username).first()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")

        # 邮箱去重
        if body.email:
            email_existing = db.query(User).filter(User.email == body.email).first()
            if email_existing:
                raise HTTPException(status_code=400, detail="邮箱已被使用")

        # 检查是否是第一个用户 → 自动设为管理员
        user_count = db.query(User).count()
        is_first = user_count == 0

        user = User(
            username=body.username,
            password_hash=hash_password(body.password),
            email=body.email,
            is_admin=is_first,
        )
        db.add(user)
        db.flush()  # 触发 default (id) 生成
        user.ensure_dirs()
        db.commit()
        db.refresh(user)

    return {
        "user_id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
    }


@router.post("/login")
async def login(response: Response, body: LoginRequest, request: Request):
    """用户登录"""
    ip = _get_client_ip(request)
    _check_login_rate_limit(body.username, ip)

    with Session() as db:
        user = db.query(User).filter(User.username == body.username).first()
        if not user:
            _record_login_attempt(body.username, ip, False)
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not verify_password(body.password, user.password_hash):
            _record_login_attempt(body.username, ip, False)
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not user.is_active:
            _record_login_attempt(body.username, ip, False)
            raise HTTPException(status_code=403, detail="账户已被禁用")

        _record_login_attempt(body.username, ip, True)

        user.last_login_at = datetime.utcnow()
        user.token_version += 1
        db.commit()

        access_token = create_access_token(user.id, user.token_version)
        refresh_token = create_refresh_token(user.id, user.token_version)

        # 7 天 cookie（"记住我"延长到 30 天）
        max_age = 30 * 24 * 3600 if body.remember else 7 * 24 * 3600
        response.set_cookie(
            "octopus_token",
            access_token,
            httponly=True,
            max_age=max_age,
            samesite="lax",
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_admin": user.is_admin,
            },
        }


@router.post("/logout")
async def logout(response: Response):
    """登出"""
    response.delete_cookie("octopus_token")
    return {"ok": True}


@router.post("/refresh")
async def refresh(body: RefreshRequest):
    """刷新 access token"""
    payload = decode_token_unsafe(body.refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="无效的 refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="不是 refresh token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")

    with Session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="用户不存在或已禁用")

        if payload.get("v", 0) != user.token_version:
            raise HTTPException(status_code=401, detail="Token 已失效，请重新登录")

        access_token = create_access_token(user.id, user.token_version)
        return {
            "access_token": access_token,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_admin": user.is_admin,
            },
        }


@router.get("/me")
async def get_me(request: Request):
    """获取当前用户信息"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    with Session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_admin": user.is_admin,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        }


@router.patch("/me")
async def update_profile(request: Request, body: UpdateProfileRequest):
    """更新个人资料（用户名/邮箱）"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    with Session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if body.username is not None:
            new_username = body.username.strip()
            if len(new_username) < 3 or len(new_username) > 64:
                raise HTTPException(status_code=400, detail="用户名需 3-64 字符")
            if not all(c.isalnum() or c in "_-." for c in new_username):
                raise HTTPException(status_code=400, detail="用户名只能包含字母、数字、下划线、连字符、点")
            if new_username != user.username:
                existing = db.query(User).filter(User.username == new_username).first()
                if existing:
                    raise HTTPException(status_code=400, detail="用户名已被使用")
                user.username = new_username

        if body.email is not None:
            new_email = body.email.strip() or None
            if new_email and new_email != user.email:
                existing = db.query(User).filter(User.email == new_email).first()
                if existing:
                    raise HTTPException(status_code=400, detail="邮箱已被使用")
            user.email = new_email

        db.commit()
        db.refresh(user)

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
    }


@router.patch("/me/password")
async def change_password(request: Request, body: ChangePasswordRequest):
    """修改密码"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6个字符")

    with Session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if not verify_password(body.old_password, user.password_hash):
            raise HTTPException(status_code=400, detail="原密码错误")

        user.password_hash = hash_password(body.new_password)
        user.token_version += 1  # 使所有旧 token 失效
        db.commit()

    return {"ok": True}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """忘记密码（占位实现：实际生产应发送邮件重置链接）

    当前实现：返回通用成功信息，不暴露用户是否存在（防枚举）。
    真实生产应：1) 生成短期重置 token 存库 2) 发邮件 3) 提供 /reset-password 端点。
    """
    # 故意不返回用户是否存在
    return {
        "ok": True,
        "message": "如邮箱存在，重置链接已发送（请检查邮箱）",
    }


# ── 管理员端点（仅 admin 可见） ──

def _require_admin(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    is_admin = getattr(request.state, "is_admin", False)
    if not user_id or not is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user_id


@router.get("/admin/users")
async def list_users(request: Request):
    """管理员：列出所有用户"""
    _require_admin(request)
    with Session() as db:
        users = db.query(User).order_by(User.created_at.desc()).all()
        return {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "is_active": u.is_active,
                    "is_admin": u.is_admin,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                }
                for u in users
            ]
        }


@router.patch("/admin/users/{user_id}/status")
async def set_user_status(request: Request, user_id: str, body: dict = Body(default={})):
    """管理员：启用/禁用用户"""
    _require_admin(request)
    is_active = body.get("is_active")
    if is_active is None:
        raise HTTPException(status_code=400, detail="缺少 is_active 字段")

    admin_id = request.state.user_id
    if user_id == admin_id and not is_active:
        raise HTTPException(status_code=400, detail="不能禁用自己的账户")

    with Session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        user.is_active = bool(is_active)
        if not is_active:
            user.token_version += 1  # 强制下线
        db.commit()

    return {"ok": True}


# ── 辅助函数 ────────────────────────────────────────────────────────────────

def decode_token_unsafe(token: str) -> dict | None:
    """不解密版本号，仅解析 payload"""
    import jwt
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None
