"""REST API 端点：会话管理、配置、模型、agents、skills、命令列表。

多用户支持：
- 会话 API（list_sessions, create_session, load_session 等）按 user_id 隔离
- user_id 从 request.state 获取（由 JWT 中间件注入）
- 文件浏览 API 增加目录边界检查
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request, UploadFile, File

router = APIRouter(prefix="/api")


def _get_user_id(request: Request) -> str:
    """从请求状态中获取 user_id（JWT 中间件注入）。"""
    return getattr(request.state, "user_id", "") or ""


# ── 会话 ──

@router.get("/sessions")
async def list_sessions(request: Request):
    from session import list_sessions as _list
    user_id = _get_user_id(request)
    return await asyncio.to_thread(_list, user_id)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    from session import load_session
    user_id = _get_user_id(request)
    try:
        messages, cwd, meta = await asyncio.to_thread(load_session, session_id, user_id)
        return {"session_id": session_id, "messages": messages, "cwd": cwd, "meta": meta}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/sessions")
async def create_session(request: Request, body: dict[str, Any] = Body(default={})):
    from session import create_session as _create
    user_id = _get_user_id(request)
    name = body.get("name") if body else None
    return {"session_id": await asyncio.to_thread(_create, name, None, user_id)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    from pathlib import Path
    from session import _project_dir, _with_file_lock_atomic
    import json
    user_id = _get_user_id(request)
    project = await asyncio.to_thread(_project_dir, user_id)
    filepath = project / f"{session_id}.jsonl"
    if filepath.exists():
        filepath.unlink()
        # 更新索引（flock 保护 RMW，防止并发写丢更新）
        index_file = project / "index.json"
        if index_file.exists():

            def _rmw(out_f):
                try:
                    with open(index_file, encoding="utf-8") as f:
                        index = json.load(f)
                    index.pop(session_id, None)
                    json.dump(index, out_f, ensure_ascii=False, indent=2)
                except (json.JSONDecodeError, OSError):
                    pass

            try:
                await asyncio.to_thread(_with_file_lock_atomic, index_file, _rmw)
            except OSError:
                pass
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Session not found")


@router.patch("/sessions/{session_id}")
async def patch_session(session_id: str, request: Request, body: dict[str, Any] = Body(default={})):
    from session import rename_session, pin_session
    user_id = _get_user_id(request)
    if "name" in body:
        rename_session(session_id, body["name"], user_id)
    if "pinned" in body:
        pin_session(session_id, bool(body["pinned"]), user_id)
    return {"ok": True}


# ── 配置 ──

@router.get("/config")
async def get_config(request: Request):
    from config import get_all, get_user_config
    user_id = _get_user_id(request)
    cfg = get_all()
    cfg.pop("api_key", None)
    # 合并用户个人配置（优先级更高）
    if user_id:
        user_cfg = get_user_config(user_id)
        for k, v in user_cfg.items():
            if k != "api_key":
                cfg[k] = v
    return cfg


@router.patch("/config")
async def set_config(request: Request, body: dict[str, Any] = Body(default={})):
    from config import set_value, set_user_value, invalidate
    user_id = _get_user_id(request)
    for key, value in body.items():
        if key == "api_key":
            continue
        if user_id:
            set_user_value(user_id, key, value)
        else:
            set_value(key, value)
    invalidate()
    return {"ok": True}


# ── 模型 ──

@router.get("/models")
async def list_models():
    from config import get_models, get
    models = get_models()
    return {"current": get("model"), "provider": get("provider") or "", "models": models}


# ── Agents ──

@router.get("/agents")
async def list_agents():
    from skills import load_agents
    agents = load_agents()
    return {"agents": list(agents)}


# ── Skills ──

@router.get("/skills")
async def list_skills():
    from skills import load_skills
    skills = load_skills()
    return {"skills": list(skills)}


# ── 命令 ──

@router.get("/commands")
async def list_commands():
    from commands import get_command_names, get_command_desc
    return {name: get_command_desc(name) for name in get_command_names()}


# ── 文件浏览（带用户目录边界检查） ──

def _check_path_in_user_root(path: str, user_id: str) -> str | None:
    """检查路径是否在用户目录内，返回错误信息或 None（表示允许）。"""
    if not user_id:
        return None  # TUI/CLI 模式，无边界限制
    user_root = str(Path.home() / ".octopus" / "users" / user_id)
    try:
        abs_path = str(Path(path).resolve()) if path else str(Path.cwd().resolve())
    except Exception:
        return "无效路径"
    if not abs_path.startswith(user_root + os.sep) and abs_path != user_root:
        return f"越权访问: {path}（超出用户目录）"
    return None


from pathlib import Path


@router.get("/files")
async def list_files(request: Request, path: str = ""):
    """列目录内容"""
    user_id = _get_user_id(request)
    base = Path(path).resolve() if path else Path.cwd()

    # 目录边界检查
    if user_id:
        user_root = str(Path.home() / ".octopus" / "users" / user_id)
        base_str = str(base)
        if not base_str.startswith(user_root + os.sep) and base_str != user_root:
            raise HTTPException(status_code=403, detail=f"越权访问: {path}")

    if not base.exists() or not base.is_dir():
        return {"error": "目录不存在", "path": str(base), "entries": []}

    entries = []
    try:
        for entry in sorted(base.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                st = entry.stat()
                entries.append({
                    "name": entry.name,
                    "path": str(entry.resolve()),
                    "type": "dir" if entry.is_dir() else "file",
                    "size": st.st_size if entry.is_file() else 0,
                    "mtime": st.st_mtime,
                })
            except OSError:
                continue
    except PermissionError:
        return {"error": "权限不足", "path": str(base), "entries": []}

    return {"path": str(base), "entries": entries}


@router.get("/file")
async def read_file(request: Request, path: str = "", encoding: str = "utf-8"):
    """读文件内容"""
    user_id = _get_user_id(request)

    # 目录边界检查
    if user_id:
        err = _check_path_in_user_root(path, user_id)
        if err:
            raise HTTPException(status_code=403, detail=err)

    filepath = Path(path).resolve()
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    file_size = filepath.stat().st_size
    if file_size > 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 1MB")

    # 检测二进制文件（检查前 8KB 是否有空字节）
    try:
        with open(filepath, "rb") as f:
            head = f.read(8192)
            if b"\0" in head:
                raise HTTPException(status_code=400, detail="二进制文件无法编辑")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 检测 EOL 类型
    eol = "lf"
    if b"\r\n" in head:
        eol = "crlf"

    try:
        content = filepath.read_text(encoding=encoding, errors="replace")
        return {"path": str(filepath), "content": content, "size": file_size, "eol": eol, "encoding": encoding}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/file")
async def write_file(request: Request, body: dict = Body(default={})):
    """写文件"""
    user_id = _get_user_id(request)

    # 目录边界检查
    file_path = body.get("path", "")
    if user_id:
        err = _check_path_in_user_root(file_path, user_id)
        if err:
            raise HTTPException(status_code=403, detail=err)

    filepath = Path(file_path).resolve()
    content = body.get("content", "")
    file_encoding = body.get("encoding", "utf-8") or "utf-8"
    eol = body.get("eol", "lf")

    if not filepath.parent.exists():
        raise HTTPException(status_code=400, detail="父目录不存在")

    try:
        # 统一换行符
        if eol == "crlf":
            content = content.replace("\r\n", "\n").replace("\n", "\r\n")
        else:
            content = content.replace("\r\n", "\n")

        filepath.write_text(content, encoding=file_encoding)
        return {"path": str(filepath), "ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/file")
async def delete_file(request: Request, path: str = ""):
    """删除文件或目录"""
    user_id = _get_user_id(request)

    # 目录边界检查
    if user_id:
        err = _check_path_in_user_root(path, user_id)
        if err:
            raise HTTPException(status_code=403, detail=err)

    import shutil
    filepath = Path(path).resolve()
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="路径不存在")

    try:
        if filepath.is_dir():
            shutil.rmtree(str(filepath))
        else:
            filepath.unlink()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/file/create")
async def create_file(request: Request, body: dict = Body(default={})):
    """创建文件或文件夹"""
    user_id = _get_user_id(request)

    parent = Path(body.get("path", "")).resolve()
    name = body.get("name", "")
    entry_type = body.get("type", "file")

    # 目录边界检查
    if user_id:
        err = _check_path_in_user_root(str(parent), user_id)
        if err:
            raise HTTPException(status_code=403, detail=err)

    if not name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="无效的名称")
    if not parent.exists() or not parent.is_dir():
        raise HTTPException(status_code=400, detail="父目录不存在")

    target = parent / name
    if target.exists():
        raise HTTPException(status_code=409, detail="已存在同名文件")

    try:
        if entry_type == "dir":
            target.mkdir()
        else:
            target.write_text("", encoding="utf-8")
        return {"ok": True, "path": str(target)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/file/rename")
async def rename_file(request: Request, body: dict = Body(default={})):
    """重命名文件或目录"""
    user_id = _get_user_id(request)

    filepath = Path(body.get("path", "")).resolve()
    new_name = body.get("name", "")

    # 目录边界检查
    if user_id:
        err = _check_path_in_user_root(str(filepath), user_id)
        if err:
            raise HTTPException(status_code=403, detail=err)

    if not new_name or "/" in new_name or "\\" in new_name:
        raise HTTPException(status_code=400, detail="无效的名称")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="路径不存在")

    try:
        new_path = filepath.parent / new_name
        if new_path.exists():
            raise HTTPException(status_code=409, detail="目标已存在")
        filepath.rename(new_path)
        return {"ok": True, "path": str(new_path)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/file/upload")
async def upload_file(request: Request, dir: str = "", file: UploadFile = File(None)):
    """上传文件到目录"""
    user_id = _get_user_id(request)

    if not file:
        raise HTTPException(status_code=400, detail="未选择文件")

    target_dir = Path(dir).resolve() if dir else Path.cwd()

    # 目录边界检查
    if user_id:
        err = _check_path_in_user_root(str(target_dir), user_id)
        if err:
            raise HTTPException(status_code=403, detail=err)

    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="目录不存在")

    try:
        target_path = target_dir / file.filename
        content = await file.read()
        target_path.write_bytes(content)
        return {"ok": True, "path": str(target_path)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/file/download")
async def download_file(request: Request, path: str = ""):
    """下载文件"""
    from fastapi.responses import Response

    user_id = _get_user_id(request)

    # 目录边界检查
    if user_id:
        err = _check_path_in_user_root(path, user_id)
        if err:
            raise HTTPException(status_code=403, detail=err)

    filepath = Path(path).resolve()
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        content = filepath.read_bytes()
        filename = filepath.name
        cd = f'attachment; filename="{filename}"'
        return Response(content=content, media_type="application/octet-stream", headers={"Content-Disposition": cd})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
