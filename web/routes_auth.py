"""认证路由：登录/注册/登出/token刷新"""
from __future__ import annotations

from datetime import datetime

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


# ── Request/Response Models ──────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    username: str | None = None
    email: str | None = None


# ── Routes ──────────────────────────────────────────────────────────────────

@router.post("/register")
async def register(body: RegisterRequest):
    """用户注册"""
    if len(body.username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少3个字符")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6个字符")

    with Session() as db:
        # 检查用户名是否存在
        existing = db.query(User).filter(User.username == body.username).first()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")

        # 创建用户
        user = User(
            username=body.username,
            password_hash=hash_password(body.password),
            email=body.email,
        )
        user.ensure_dirs()
        db.add(user)
        db.commit()

    return {"user_id": user.id, "username": user.username}


@router.post("/login")
async def login(response: Response, body: LoginRequest):
    """用户登录"""
    with Session() as db:
        user = db.query(User).filter(User.username == body.username).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="账户已被禁用")

        # 更新最后登录时间和 token 版本
        user.last_login_at = datetime.utcnow()
        user.token_version += 1
        db.commit()

        access_token = create_access_token(user.id, user.token_version)
        refresh_token = create_refresh_token(user.id, user.token_version)

        # 设置 HTTP-only cookie
        response.set_cookie(
            "octopus_token",
            access_token,
            httponly=True,
            max_age=7 * 24 * 3600,
            samesite="lax",
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {"id": user.id, "username": user.username},
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

        # 检查 token 版本是否匹配
        if payload.get("v", 0) != user.token_version:
            raise HTTPException(status_code=401, detail="Token 已失效，请重新登录")

        # 生成新的 access token
        access_token = create_access_token(user.id, user.token_version)

        return {
            "access_token": access_token,
            "user": {"id": user.id, "username": user.username},
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
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "is_admin": user.is_admin,
        }


@router.patch("/me/password")
async def change_password(request: Request, body: ChangePasswordRequest):
    """修改密码"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

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
            if len(new_username) < 3:
                raise HTTPException(status_code=400, detail="用户名至少3个字符")
            if new_username != user.username:
                # 检查重名
                existing = db.query(User).filter(User.username == new_username).first()
                if existing:
                    raise HTTPException(status_code=400, detail="用户名已被使用")
                user.username = new_username

        if body.email is not None:
            user.email = body.email.strip() or None

        db.commit()

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
    }


# ── 辅助函数 ────────────────────────────────────────────────────────────────

def decode_token_unsafe(token: str) -> dict | None:
    """不解密版本号，仅解析 payload"""
    import jwt
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None
