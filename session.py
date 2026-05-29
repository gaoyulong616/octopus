"""会话持久化：JSONL 追加存储、项目隔离、元数据索引、自动清理。

参照 Claude Code 的会话管理实现：
- 存储路径：~/.octopus/projects/<encoded-cwd>/<session-id>.jsonl
- 每条消息一行 JSON（crash-safe，损坏行跳过）
- 流式追加保存，无需重写整个文件
- 元数据索引缓存，快速列出会话
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from tools import get_cwd

# ── 路径常量 ──

_BASE_DIR = Path.home() / ".octopus"
_SESSIONS_ROOT = _BASE_DIR / "projects"


def _project_dir(cwd: str | None = None) -> Path:
    """返回当前项目的 sessions 目录。路径用 '-' 替换 '/' 编码。"""
    if cwd is None:
        cwd = os.getcwd()
    # 将路径转为安全的目录名：/home/user/project → -home-user-project
    encoded = cwd.replace("/", "-").replace("\\", "-")
    d = _SESSIONS_ROOT / encoded
    d.mkdir(parents=True, exist_ok=True)
    return d


def _git_branch() -> str:
    """获取当前 git 分支名，失败返回空字符串。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _time_ago(iso_str: str) -> str:
    """将 ISO 时间字符串转为人类可读的相对时间。"""
    try:
        dt = datetime.fromisoformat(iso_str)
        delta = datetime.now() - dt
        if delta < timedelta(minutes=1):
            return "刚刚"
        if delta < timedelta(hours=1):
            return f"{int(delta.total_seconds() / 60)} 分钟前"
        if delta < timedelta(days=1):
            return f"{int(delta.total_seconds() / 3600)} 小时前"
        if delta < timedelta(days=30):
            return f"{delta.days} 天前"
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso_str[:19]


def _extract_first_message(messages: list[dict]) -> str:
    """提取首条用户消息的前 80 字符作为预览。"""
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        if isinstance(content, list):
            text_parts = [
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            content = " ".join(text_parts)
        if isinstance(content, str) and content.strip():
            return content.strip()[:80]
    return ""


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
                elif block.type == "thinking":
                    d["thinking"] = block.thinking
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
                if btype == "thinking":
                    continue
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


# ── 会话创建 ──

def create_session(name: str | None = None, cwd: str | None = None) -> str:
    """创建新会话，返回 session_id（UUID）。"""
    session_id = uuid.uuid4().hex[:16]
    project = _project_dir(cwd)
    filepath = project / f"{session_id}.jsonl"

    meta = {
        "type": "meta",
        "session_id": session_id,
        "name": name or "",
        "cwd": cwd or os.getcwd(),
        "git_branch": _git_branch(),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "message_count": 0,
        "total_tokens": 0,
        "first_message": "",
        "model": "",
    }

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")

    _update_index(project, meta)
    return session_id


# ── 追加消息（流式保存） ──

def append_message(session_id: str, role: str, content: Any,
                   usage: dict | None = None, model: str = "",
                   cwd: str | None = None):
    """追加单条消息到 JSONL 文件（流式保存，无需重写）。"""
    project = _project_dir(cwd)
    filepath = project / f"{session_id}.jsonl"
    if not filepath.exists():
        return

    record = {
        "type": "message",
        "role": role,
        "content": _serialize_content(content),
        "timestamp": datetime.now().isoformat(),
    }
    if usage:
        record["usage"] = usage

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 更新元数据首行
    _update_meta(session_id, project, role, content, usage, model)


def _update_meta(session_id: str, project: Path, role: str,
                 content: Any, usage: dict | None, model: str):
    """更新 JSONL 文件的 meta 首行和索引。"""
    filepath = project / f"{session_id}.jsonl"
    if not filepath.exists():
        return

    lines: list[str] = []
    meta = None
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "meta":
                meta = obj
                continue
            lines.append(line)

    if meta is None:
        return

    meta["updated_at"] = datetime.now().isoformat()
    msg_count = meta.get("message_count", 0) + 1
    meta["message_count"] = msg_count
    if usage:
        meta["total_tokens"] = meta.get("total_tokens", 0) + usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    if model:
        meta["model"] = model
    # 首条用户消息作为预览
    if msg_count == 1 and role == "user":
        text = content if isinstance(content, str) else ""
        if isinstance(content, list):
            text = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        meta["first_message"] = text.strip()[:80]

    # 重写文件：meta 行 + 其余行
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for line in lines:
            f.write(line + "\n")

    _update_index(project, meta)


def _update_index(project: Path, meta: dict):
    """更新项目的 session 索引文件。"""
    index_file = project / "index.json"
    index: dict[str, dict] = {}
    if index_file.exists():
        try:
            with open(index_file, encoding="utf-8") as f:
                index = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    sid = meta.get("session_id", "")
    if sid:
        index[sid] = {
            "session_id": sid,
            "name": meta.get("name", ""),
            "first_message": meta.get("first_message", ""),
            "model": meta.get("model", ""),
            "git_branch": meta.get("git_branch", ""),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
            "message_count": meta.get("message_count", 0),
            "total_tokens": meta.get("total_tokens", 0),
            "cwd": meta.get("cwd", ""),
        }

    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


# ── 加载会话 ──

def load_session(session_id: str, cwd: str | None = None) -> tuple[list[dict], str, dict]:
    """加载会话，返回 (messages, cwd, meta)。损坏行自动跳过。"""
    project = _project_dir(cwd)
    filepath = project / f"{session_id}.jsonl"
    if not filepath.exists():
        # 尝试在全局 sessions 目录（兼容旧格式）
        legacy = _BASE_DIR / "sessions" / f"{session_id}.json"
        if legacy.exists():
            return _load_legacy(legacy)
        raise FileNotFoundError(f"Session 不存在: {session_id}")

    messages: list[dict] = []
    meta: dict = {}
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "meta":
                meta = obj
            elif obj.get("type") == "message":
                messages.append({
                    "role": obj["role"],
                    "content": _deserialize_content(obj["content"]),
                })

    return messages, meta.get("cwd", ""), meta


def _load_legacy(filepath: Path) -> tuple[list[dict], str, dict]:
    """加载旧版 JSON 格式的 session。"""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    messages = [
        {"role": m["role"], "content": _deserialize_content(m["content"])}
        for m in data.get("messages", [])
    ]
    meta = {
        "session_id": data.get("id", ""),
        "name": "",
        "cwd": data.get("cwd", ""),
        "first_message": _extract_first_message(messages),
        "message_count": len(messages),
    }
    return messages, data.get("cwd", ""), meta


# ── 列出会话 ──

def list_sessions(cwd: str | None = None) -> list[dict]:
    """列出当前项目的所有会话（从索引读取），按更新时间倒序。"""
    project = _project_dir(cwd)
    index_file = project / "index.json"
    if not index_file.exists():
        return []

    try:
        with open(index_file, encoding="utf-8") as f:
            index = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    sessions = list(index.values())
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return sessions


def get_latest_session(cwd: str | None = None) -> str | None:
    """返回当前项目最新会话的 ID。"""
    sessions = list_sessions(cwd)
    return sessions[0]["session_id"] if sessions else None


def find_session_by_name(query: str, cwd: str | None = None) -> str | None:
    """按名称模糊匹配会话，返回 session_id。"""
    sessions = list_sessions(cwd)
    query_lower = query.lower()
    # 精确匹配
    for s in sessions:
        if s.get("name", "").lower() == query_lower:
            return s["session_id"]
    # 首条消息包含查询词
    for s in sessions:
        if query_lower in s.get("first_message", "").lower():
            return s["session_id"]
    # 名称包含查询词
    for s in sessions:
        if query_lower in s.get("name", "").lower():
            return s["session_id"]
    return None


# ── 会话操作 ──

def rename_session(session_id: str, name: str, cwd: str | None = None):
    """重命名会话。"""
    project = _project_dir(cwd)
    filepath = project / f"{session_id}.jsonl"
    if not filepath.exists():
        return

    _rewrite_meta_field(filepath, "name", name)
    # 更新索引
    index_file = project / "index.json"
    if index_file.exists():
        try:
            with open(index_file, encoding="utf-8") as f:
                index = json.load(f)
            if session_id in index:
                index[session_id]["name"] = name
                with open(index_file, "w", encoding="utf-8") as f:
                    json.dump(index, f, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, OSError):
            pass


def _rewrite_meta_field(filepath: Path, key: str, value: Any):
    """修改 JSONL 文件 meta 行的某个字段。"""
    lines: list[str] = []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                lines.append(line)
                continue
            if obj.get("type") == "meta":
                obj[key] = value
                lines.append(json.dumps(obj, ensure_ascii=False))
            else:
                lines.append(line)

    with open(filepath, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def export_session(session_id: str, output_path: str | None = None,
                   cwd: str | None = None) -> str:
    """导出会话为纯文本，返回文件路径。"""
    messages, session_cwd, meta = load_session(session_id, cwd)
    if not output_path:
        safe_name = re.sub(r'[^\w]', '_', meta.get("name", session_id))
        output_path = f"session_{safe_name}.txt"

    lines: list[str] = []
    if meta.get("name"):
        lines.append(f"# {meta['name']}")
    lines.append(f"# Session: {session_id}")
    lines.append(f"# Created: {meta.get('created_at', '')}")
    lines.append(f"# Model: {meta.get('model', '')}")
    lines.append("")

    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for b in content:
                if isinstance(b, dict):
                    if b.get("type") == "text":
                        text_parts.append(b.get("text", ""))
                    elif b.get("type") == "tool_use":
                        text_parts.append(f"[tool: {b.get('name', '')}]")
                    elif b.get("type") == "tool_result":
                        text_parts.append(f"[result: {str(b.get('content', ''))[:200]}]")
            content = "\n".join(text_parts)
        lines.append(f"## {role.upper()}")
        lines.append(str(content))
        lines.append("")

    text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    return output_path


# ── 兼容旧接口 ──

def save_session(messages: list[dict], session_id: str | None = None) -> str:
    """保存完整对话（兼容旧调用方式，新代码应使用 create_session + append_message）。"""
    if session_id is None:
        # 新建会话
        session_id = create_session()

    project = _project_dir()
    filepath = project / f"{session_id}.jsonl"

    # 重写文件
    meta = {
        "type": "meta",
        "session_id": session_id,
        "name": "",
        "cwd": get_cwd(),
        "git_branch": _git_branch(),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "message_count": len(messages),
        "total_tokens": 0,
        "first_message": _extract_first_message(messages),
        "model": "",
    }

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for m in messages:
            record = {
                "type": "message",
                "role": m["role"],
                "content": _serialize_content(m["content"]),
                "timestamp": datetime.now().isoformat(),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    _update_index(project, meta)
    return session_id


# ── 清理 ──

def cleanup_sessions(max_age_days: int = 30, cwd: str | None = None):
    """删除超过 max_age_days 天未更新的会话文件。"""
    project = _project_dir(cwd)
    if not project.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=max_age_days)
    count = 0

    for jsonl_file in project.glob("*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
            if mtime < cutoff:
                jsonl_file.unlink()
                count += 1
        except OSError:
            continue

    # 清理索引中的过期条目
    index_file = project / "index.json"
    if index_file.exists() and count > 0:
        try:
            with open(index_file, encoding="utf-8") as f:
                index = json.load(f)
            # 删除不存在的 session
            to_remove = [sid for sid, _ in index.items()
                         if not (project / f"{sid}.jsonl").exists()]
            for sid in to_remove:
                del index[sid]
            with open(index_file, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, OSError):
            pass

    return count
