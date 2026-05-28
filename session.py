"""对话历史持久化（session 保存/恢复/列表）。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tools import get_cwd

SESSIONS_DIR = Path.home() / ".octopus" / "sessions"


def _serialize_content(content: Any) -> Any:
    """将 Anthropic API 的 content blocks 序列化为可 JSON 化的格式。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        result = []
        for block in content:
            if isinstance(block, dict):
                result.append(block)
            elif hasattr(block, "type"):
                d: dict[str, Any] = {"type": block.type}
                if block.type == "text":
                    d["text"] = block.text
                elif block.type == "tool_use":
                    d["id"] = block.id
                    d["name"] = block.name
                    d["input"] = block.input
                elif block.type == "tool_result":
                    d["tool_use_id"] = block.tool_use_id
                    d["content"] = block.content
                result.append(d)
            else:
                result.append(block)
        return result
    return content


def _deserialize_content(content: Any) -> Any:
    """将 JSON 数据还原为 Anthropic SDK 可接受的格式。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        result = []
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "tool_use":
                    result.append({
                        "type": "tool_use",
                        "id": block["id"],
                        "name": block["name"],
                        "input": block["input"],
                    })
                elif btype == "tool_result":
                    result.append({
                        "type": "tool_result",
                        "tool_use_id": block["tool_use_id"],
                        "content": block["content"],
                    })
                else:
                    result.append(block)
            else:
                result.append(block)
        return result
    return content


def save_session(messages: list[dict], session_id: str | None = None) -> str:
    """保存对话历史到磁盘，返回 session ID。"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if session_id is None:
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = SESSIONS_DIR / f"{session_id}.json"
    data = {
        "id": session_id,
        "saved_at": datetime.now().isoformat(),
        "cwd": get_cwd(),
        "messages": [
            {"role": m["role"], "content": _serialize_content(m["content"])}
            for m in messages
        ],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return session_id


def load_session(session_id: str) -> tuple[list[dict], str]:
    """加载对话历史，返回 (messages, cwd)。"""
    filepath = SESSIONS_DIR / f"{session_id}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Session 不存在: {session_id}")
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    messages = [
        {"role": m["role"], "content": _deserialize_content(m["content"])}
        for m in data["messages"]
    ]
    return messages, data.get("cwd", "")


def list_sessions() -> list[dict]:
    """列出所有已保存的 session。"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), reverse=True):
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            sessions.append({
                "id": data["id"],
                "saved_at": data.get("saved_at", "?"),
                "cwd": data.get("cwd", "?"),
                "messages": len(data.get("messages", [])),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return sessions
