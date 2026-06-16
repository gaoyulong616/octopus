"""认证 API 路由"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Request, Response
from pydantic import BaseModel

from server.auth import (
    create_access_token,
    create_refresh_token,
    get_user_from_token,
    hash_password,
    verify_password,
)
from server.database import Session
from server.models.user import User

router = APIRouter(prefix="/api/auth")


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/register")
async def register(body: RegisterRequest):
    with Session() as db:
        existing = db.query(User).filter(User.username == body.username).first()
        if existing:
            return {"error": "用户名已存在"}

        user = User(
            username=body.username,
            password_hash=hash_password(body.password),
            email=body.email,
        )
        db.add(user)
        db.commit()
        user.ensure_dirs()

    return {"user_id": user.id, "username": user.username}


@router.post("/login")
async def login(response: Response, body: LoginRequest):
    with Session() as db:
        user = db.query(User).filter(User.username == body.username).first()
        if not user or not verify_password(body.password, user.password_hash):
            return {"error": "用户名或密码错误"}

        if not user.is_active:
            return {"error": "账户已被禁用"}

        user.last_login_at = datetime.utcnow()
        user.token_version += 1
        db.commit()

        access_token = create_access_token(user.id, user.token_version)
        refresh_token = create_refresh_token(user.id, user.token_version)

        response.set_cookie(
            "octopus_token", access_token,
            httponly=True, max_age=7 * 24 * 3600, samesite="lax"
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user.to_dict()
        }


@router.post("/refresh")
async def refresh(body: RefreshRequest):
    user = get_user_from_token(body.refresh_token)
    if not user:
        return {"error": "无效的 refresh token"}

    access_token = create_access_token(user.id, user.token_version)
    return {"access_token": access_token}


@router.get("/me")
async def get_me(request: Request):
    user = request.state.user if hasattr(request.state, "user") else None
    if not user:
        return {"error": "用户不存在"}
    return user.to_dict()


@router.patch("/me/password")
async def change_password(request: Request, body: ChangePasswordRequest):
    user = request.state.user if hasattr(request.state, "user") else None
    if not user:
        return {"error": "用户不存在"}

    if not verify_password(body.current_password, user.password_hash):
        return {"error": "当前密码错误"}

    with Session() as db:
        db_user = db.query(User).filter(User.id == user.id).first()
        if not db_user:
            return {"error": "用户不存在"}

        db_user.password_hash = hash_password(body.new_password)
        db_user.token_version += 1
        db.commit()

    return {"message": "密码修改成功"}


@router.get("/stats")
async def get_stats(request: Request):
    user = request.state.user if hasattr(request.state, "user") else None
    if not user:
        return {"error": "用户不存在"}

    import json
    from pathlib import Path

    stats = {
        "sessions": 0,
        "tokens": 0,
        "cost": 0.0,
        "days": 0,
    }

    projects_dir = user.home_dir / "projects"
    if projects_dir.exists():
        for project_dir in projects_dir.iterdir():
            if project_dir.is_dir():
                for session_file in project_dir.glob("*.jsonl"):
                    stats["sessions"] += 1
                    try:
                        with open(session_file, "r", encoding="utf-8") as f:
                            for line in f:
                                try:
                                    msg = json.loads(line)
                                    if "usage" in msg:
                                        usage = msg["usage"]
                                        stats["tokens"] += usage.get("input_tokens", 0)
                                        stats["tokens"] += usage.get("output_tokens", 0)
                                except json.JSONDecodeError:
                                    continue
                    except Exception:
                        continue

    if user.created_at:
        delta = datetime.utcnow() - user.created_at
        stats["days"] = delta.days + 1

    return stats


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("octopus_token")
    return {"message": "登出成功"}