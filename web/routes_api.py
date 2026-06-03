"""REST API 端点：会话管理、配置、模型、agents、skills、命令列表。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

router = APIRouter(prefix="/api")


# ── 会话 ──

@router.get("/sessions")
async def list_sessions():
    from session import list_sessions as _list
    return _list()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    from session import load_session
    try:
        messages, cwd, meta = load_session(session_id)
        return {"session_id": session_id, "messages": messages, "cwd": cwd, "meta": meta}
    except FileNotFoundError:
        return {"error": "Session not found"}


@router.post("/sessions")
async def create_session(body: dict[str, Any] = Body(default={})):
    from session import create_session as _create
    name = body.get("name") if body else None
    return {"session_id": _create(name=name)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    from pathlib import Path
    from session import _project_dir
    import json
    project = _project_dir()
    filepath = project / f"{session_id}.jsonl"
    if filepath.exists():
        filepath.unlink()
        # 更新索引
        index_file = project / "index.json"
        if index_file.exists():
            try:
                with open(index_file, encoding="utf-8") as f:
                    index = json.load(f)
                index.pop(session_id, None)
                with open(index_file, "w", encoding="utf-8") as f:
                    json.dump(index, f, ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, OSError):
                pass
        return {"ok": True}
    return {"error": "Session not found"}


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: str, body: dict[str, Any] = Body(default={})):
    from session import rename_session
    rename_session(session_id, body.get("name", ""))
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
