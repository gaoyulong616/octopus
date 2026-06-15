"""REST API 端点：会话管理、配置、模型、agents、skills、命令列表。"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Body, UploadFile, File

router = APIRouter(prefix="/api")


# ── 会话 ──

@router.get("/sessions")
async def list_sessions():
    from session import list_sessions as _list
    return await asyncio.to_thread(_list)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    from session import load_session
    try:
        messages, cwd, meta = await asyncio.to_thread(load_session, session_id)
        return {"session_id": session_id, "messages": messages, "cwd": cwd, "meta": meta}
    except FileNotFoundError:
        return {"error": "Session not found"}


@router.post("/sessions")
async def create_session(body: dict[str, Any] = Body(default={})):
    from session import create_session as _create
    name = body.get("name") if body else None
    return {"session_id": await asyncio.to_thread(_create, name)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    from pathlib import Path
    from session import _project_dir, _with_file_lock_atomic
    import json
    project = await asyncio.to_thread(_project_dir)
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
    return {"error": "Session not found"}


@router.patch("/sessions/{session_id}")
async def patch_session(session_id: str, body: dict[str, Any] = Body(default={})):
    from session import rename_session, pin_session
    if "name" in body:
        rename_session(session_id, body["name"])
    if "pinned" in body:
        pin_session(session_id, bool(body["pinned"]))
    return {"ok": True}


# ── 配置 ──

@router.get("/config")
async def get_config():
    from config import get_all
    cfg = get_all()
    cfg.pop("api_key", None)
    return cfg


@router.patch("/config")
async def set_config(body: dict[str, Any] = Body(default={})):
    from config import set_value, invalidate
    for key, value in body.items():
        if key == "api_key":
            continue
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


# ── 文件浏览 ──

@router.get("/files")
async def list_files(path: str = ""):
    """列目录内容"""
    import os
    from pathlib import Path

    base = Path(path).resolve() if path else Path.cwd()
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
async def read_file(path: str = "", encoding: str = "utf-8"):
    """读文件内容"""
    from pathlib import Path

    filepath = Path(path).resolve()
    if not filepath.exists() or not filepath.is_file():
        return {"error": "文件不存在", "path": str(filepath)}

    file_size = filepath.stat().st_size
    if file_size > 1024 * 1024:
        return {"error": "文件超过 1MB", "path": str(filepath)}

    # 检测二进制文件（检查前 8KB 是否有空字节）
    try:
        with open(filepath, "rb") as f:
            head = f.read(8192)
            if b"\0" in head:
                return {"error": "二进制文件无法编辑", "binary": True, "path": str(filepath)}
    except Exception as e:
        return {"error": str(e)}

    # 检测 EOL 类型
    eol = "lf"
    if b"\r\n" in head:
        eol = "crlf"

    try:
        content = filepath.read_text(encoding=encoding, errors="replace")
        return {"path": str(filepath), "content": content, "size": file_size, "eol": eol, "encoding": encoding}
    except Exception as e:
        return {"error": str(e)}


@router.put("/file")
async def write_file(body: dict = Body(default={})):
    """写文件"""
    from pathlib import Path

    filepath = Path(body.get("path", "")).resolve()
    content = body.get("content", "")
    file_encoding = body.get("encoding", "utf-8") or "utf-8"
    eol = body.get("eol", "lf")

    if not filepath.parent.exists():
        return {"error": "父目录不存在"}

    try:
        # 统一换行符
        if eol == "crlf":
            content = content.replace("\r\n", "\n").replace("\n", "\r\n")
        else:
            content = content.replace("\r\n", "\n")

        filepath.write_text(content, encoding=file_encoding)
        return {"path": str(filepath), "ok": True}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/file")
async def delete_file(path: str = ""):
    """删除文件或目录"""
    import shutil
    from pathlib import Path

    filepath = Path(path).resolve()
    if not filepath.exists():
        return {"error": "路径不存在"}

    try:
        if filepath.is_dir():
            shutil.rmtree(str(filepath))
        else:
            filepath.unlink()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


@router.post("/file/create")
async def create_file(body: dict = Body(default={})):
    """创建文件或文件夹"""
    from pathlib import Path

    parent = Path(body.get("path", "")).resolve()
    name = body.get("name", "")
    entry_type = body.get("type", "file")

    if not name or "/" in name or "\\" in name:
        return {"error": "无效的名称"}
    if not parent.exists() or not parent.is_dir():
        return {"error": "父目录不存在"}

    target = parent / name
    if target.exists():
        return {"error": "已存在同名文件"}

    try:
        if entry_type == "dir":
            target.mkdir()
        else:
            target.write_text("", encoding="utf-8")
        return {"ok": True, "path": str(target)}
    except Exception as e:
        return {"error": str(e)}


@router.post("/file/rename")
async def rename_file(body: dict = Body(default={})):
    """重命名文件或目录"""
    from pathlib import Path

    filepath = Path(body.get("path", "")).resolve()
    new_name = body.get("name", "")
    if not new_name or "/" in new_name or "\\" in new_name:
        return {"error": "无效的名称"}
    if not filepath.exists():
        return {"error": "路径不存在"}

    try:
        new_path = filepath.parent / new_name
        if new_path.exists():
            return {"error": "目标已存在"}
        filepath.rename(new_path)
        return {"ok": True, "path": str(new_path)}
    except Exception as e:
        return {"error": str(e)}


@router.post("/file/upload")
async def upload_file(dir: str = "", file: UploadFile = File(None)):
    """上传文件到目录"""
    from pathlib import Path

    if not file:
        return {"error": "未选择文件"}

    target_dir = Path(dir).resolve() if dir else Path.cwd()
    if not target_dir.exists() or not target_dir.is_dir():
        return {"error": "目录不存在"}

    try:
        target_path = target_dir / file.filename
        content = await file.read()
        target_path.write_bytes(content)
        return {"ok": True, "path": str(target_path)}
    except Exception as e:
        return {"error": str(e)}


@router.get("/file/download")
async def download_file(path: str = ""):
    """下载文件"""
    from pathlib import Path
    from fastapi.responses import Response

    filepath = Path(path).resolve()
    if not filepath.exists() or not filepath.is_file():
        return {"error": "文件不存在"}

    try:
        content = filepath.read_bytes()
        filename = filepath.name
        cd = f'attachment; filename="{filename}"'
        return Response(content=content, media_type="application/octet-stream", headers={"Content-Disposition": cd})
    except Exception as e:
        return {"error": str(e)}
