"""会话持久化：JSONL 追加存储、项目隔离、元数据索引、自动清理。

参照 Claude Code 的会话管理实现：
- 存储路径：~/.octopus/projects/<encoded-cwd>/<session-id>.jsonl
- 每条消息一行 JSON（crash-safe，损坏行跳过）
- 流式追加保存，无需重写整个文件
- 元数据索引缓存，快速列出会话
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from logger import get_logger as _get_logger
from tools import get_cwd

# 文件锁：Unix 用 fcntl，Windows 降级为无锁
try:
    import fcntl as _fcntl

    def _with_file_lock(filepath, mode, callback):
        """Execute callback with exclusive file lock (Unix).

        注意："w" 模式下 open 瞬间已截断文件，加锁太晚——并发读会读到空。
        使用 _with_file_lock_atomic 替代"w + 全文重写"场景。
        """
        with open(filepath, mode, encoding="utf-8") as f:
            try:
                _fcntl.flock(f.fileno(), _fcntl.LOCK_EX)
                return callback(f)
            finally:
                _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)

    def _with_file_lock_atomic(filepath, callback):
        """原子写入 + 跨进程/线程 RMW 互斥。

        使用 filepath 旁的 lock file（filepath + '.lock'）作为 flock 目标。
        不能直接锁 filepath——os.replace 会换掉 inode，flock 失效。
        lock file 始终存在（首次创建后不被替换），flock 稳定。
        tempfile + os.replace 保证原子写入，避免 torn write。

        filepath 可以不存在（首次创建）；os.replace 是 POSIX 原子操作，
        读进程要么看到旧文件要么看到新文件，不会读到中间态。
        """
        path_str = str(filepath)
        lock_path = path_str + ".lock"
        lockf = open(lock_path, "a+", encoding="utf-8")
        try:
            _fcntl.flock(lockf.fileno(), _fcntl.LOCK_EX)
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(Path(filepath).parent), prefix=".ses-", suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    result = callback(f)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, path_str)
                return result
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        finally:
            try:
                _fcntl.flock(lockf.fileno(), _fcntl.LOCK_UN)
            except OSError:
                pass
            lockf.close()

except ImportError:

    def _with_file_lock(filepath, mode, callback):
        """Execute callback without locking (Windows fallback)."""
        with open(filepath, mode, encoding="utf-8") as f:
            return callback(f)

    def _with_file_lock_atomic(filepath, callback):
        """Windows fallback：tempfile + os.replace（无锁）。"""
        path_str = str(filepath)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(Path(filepath).parent), prefix=".ses-", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                result = callback(f)
                f.flush()
            os.replace(tmp_path, path_str)
            return result
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

# ── 内存元数据缓存 ──

_meta_cache: dict[str, dict] = {}

# ── 内容 hash 缓存：避免刷新/切换时内容未变仍重复写盘 ──
_last_saved_hash: dict[str, str] = {}


def _messages_content_hash(messages: list[dict]) -> str:
    payload = json.dumps(
        [{"role": m.get("role", ""), "content": _serialize_content(m.get("content", ""))} for m in messages],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()

# ── 路径常量 ──

_BASE_DIR = Path.home() / ".octopus"
_SESSIONS_ROOT = _BASE_DIR / "projects"

# save_session 写入 meta 时硬编码的核心字段集合；不在此集合内的字段视为扩展字段透传保留
# 用 frozenset 加速 in 查询；新增扩展字段（如 mode/interrupted_at/auto_approved_tools）无需改这里
_META_CORE_FIELDS = frozenset(
    {
        "type",
        "session_id",
        "name",
        "cwd",
        "git_branch",
        "created_at",
        "updated_at",
        "message_count",
        "total_tokens",
        "first_message",
        "model",
    }
)


def _project_dir(cwd: str | None = None, user_id: str | None = None) -> Path:
    """返回当前项目的 sessions 目录。路径用 '-' 替换 '/' 编码。

    如果提供 user_id，则在用户隔离目录下创建。
    """
    if cwd is None:
        cwd = os.getcwd()
    encoded = cwd.replace("/", "-").replace("\\", "-")

    if user_id:
        root = _BASE_DIR / "users" / user_id / "projects"
    else:
        root = _SESSIONS_ROOT

    d = root / encoded
    d.mkdir(parents=True, exist_ok=True)
    return d


def _git_branch() -> str:
    """获取当前 git 分支名，失败返回空字符串。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
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
            text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            content = " ".join(text_parts)
        if isinstance(content, str) and content.strip():
            return content.strip()[:80]
    return ""


def _serialize_content(content: Any) -> Any:
    """将 Anthropic API 的 content blocks 序列化为可 JSON 化的格式。

    自动去重：API 可能返回重复的 blocks（特别是 DeepSeek），按唯一 ID 去重（不按文本内容）。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        result = []
        seen = set()
        for idx, block in enumerate(content):
            if isinstance(block, dict):
                # 跳过无有效 tool_use_id 的 tool_result，防止下次 load 后 API 报错
                if block.get("type") == "tool_result" and not block.get("tool_use_id"):
                    continue
                # 按唯一标识去重（不按文本内容）
                key = _block_key(block, idx)
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
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
                    d["tool_use_id"] = getattr(block, "tool_use_id", "") or ""
                    d["content"] = (
                        _serialize_content(block.content) if isinstance(block.content, (list, tuple)) else block.content
                    )
                    if not d["tool_use_id"]:
                        continue  # 跳过无有效 tool_use_id 的块，防止 API 报错
                elif block.type == "thinking":
                    d["thinking"] = block.thinking
                    if hasattr(block, "signature") and block.signature:
                        d["signature"] = block.signature
                elif block.type == "redacted_thinking":
                    d["redacted_thinking"] = getattr(block, "data", "")
                elif block.type == "server_tool_use":
                    d["id"] = block.id
                    d["name"] = block.name
                    d["input"] = block.input
                elif block.type == "web_search_tool_result":
                    d["content"] = _serialize_web_search_result(block)
                elif block.type == "web_fetch_tool_result":
                    d["content"] = _serialize_web_fetch_result(block)
                key = _block_key(d, idx)
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                result.append(d)
            else:
                # 非对象元素（裸字符串等），包装为 text block
                if isinstance(block, str) and block:
                    result.append({"type": "text", "text": block})
        return result
    return content


def _serialize_web_search_result(block: Any) -> list[dict]:
    """序列化 web_search_tool_result block 的 content。"""
    content = getattr(block, "content", [])
    if isinstance(content, list):
        result = []
        for item in content:
            if hasattr(item, "title") and hasattr(item, "url"):
                result.append(
                    {
                        "title": getattr(item, "title", ""),
                        "url": getattr(item, "url", ""),
                        "snippet": getattr(item, "snippet", ""),
                    }
                )
            elif isinstance(item, dict):
                result.append(item)
        return result
    return []


def _serialize_web_fetch_result(block: Any) -> dict | str:
    """序列化 web_fetch_tool_result block 的 content。"""
    content = getattr(block, "content", None)
    if content is None:
        return ""
    if hasattr(content, "content") and hasattr(content.content, "source"):
        src = content.content.source
        if hasattr(src, "data"):
            return {"data": src.data}
    if hasattr(content, "error_code"):
        return {"error_code": content.error_code}
    return str(content)[:500]


def _block_key(block: dict, index: int = 0) -> str | None:
    """为 content block 生成去重 key。使用 index 区分相同类型的相邻块。"""
    btype = block.get("type", "")
    if btype == "text":
        # 用 index 而非内容做 key，避免误去重相同内容的正常块
        return f"text:{index}"
    elif btype == "tool_use":
        return f"tool_use:{block.get('id', '')}:{block.get('name', '')}"
    elif btype == "tool_result":
        return f"tool_result:{block.get('tool_use_id', '')}"
    elif btype == "server_tool_use":
        return f"server_tool_use:{block.get('id', '')}:{block.get('name', '')}"
    elif btype in ("web_search_tool_result", "web_fetch_tool_result"):
        return f"{btype}:{hash(str(block.get('content', '')))}"
    return None


def _deserialize_content(content: Any) -> Any:
    """将 JSON 数据还原为 Anthropic SDK 可接受的格式。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        result = []
        for block in content:
            if isinstance(block, dict):
                try:
                    btype = block.get("type", "")
                    if btype == "thinking":
                        thinking_dict = {
                            "type": "thinking",
                            "thinking": block.get("thinking", ""),
                        }
                        if "signature" in block:
                            thinking_dict["signature"] = block["signature"]
                        result.append(thinking_dict)
                        continue
                    if btype == "redacted_thinking":
                        result.append(
                            {
                                "type": "redacted_thinking",
                                "data": block.get("data", ""),
                            }
                        )
                        continue
                    if btype == "tool_use":
                        result.append(
                            {
                                "type": "tool_use",
                                "id": block["id"],
                                "name": block["name"],
                                "input": block["input"],
                            }
                        )
                    elif btype == "tool_result":
                        tool_use_id = block.get("tool_use_id")
                        if not tool_use_id:
                            _get_logger().warning(
                                "deserialize: 跳过缺少 tool_use_id 的 tool_result block, content=%s",
                                str(block.get("content", ""))[:200],
                            )
                            continue
                        result.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": block["content"],
                            }
                        )
                    elif btype == "server_tool_use":
                        result.append(
                            {
                                "type": "server_tool_use",
                                "id": block["id"],
                                "name": block["name"],
                                "input": block["input"],
                            }
                        )
                    elif btype in ("web_search_tool_result", "web_fetch_tool_result"):
                        result.append(block)
                    elif btype == "text":
                        result.append({"type": "text", "text": block.get("text", "")})
                    else:
                        # 未知类型，尝试保留 type 字段；若无 type 则跳过
                        if btype:
                            result.append(block)
                except (KeyError, TypeError):
                    continue
            else:
                # 非 dict 元素（字符串等）直接跳过，避免 API 报错
                pass
        return result
    return content


# ── 会话创建 ──


def create_session(name: str | None = None, cwd: str | None = None, user_id: str | None = None) -> str:
    """创建新会话，返回 session_id（UUID）。"""
    session_id = uuid.uuid4().hex[:16]
    project = _project_dir(cwd, user_id)
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
        # 多会话并行支持：会话级 mode 持久化（切走再切回恢复）
        "mode": "accept-edits",
    }

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")

    _meta_cache[session_id] = meta
    _update_index(project, meta)
    _get_logger().info("session 创建: %s cwd=%s", session_id, meta.get("cwd", ""))
    return session_id


# ── 追加消息（流式保存） ──


def append_message(
    session_id: str, role: str, content: Any, usage: dict | None = None, model: str = "", cwd: str | None = None, user_id: str | None = None
):
    """追加单条消息到 JSONL 文件（流式保存，无需重写）。"""
    project = _project_dir(cwd, user_id)
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

    def _write(f):
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    _with_file_lock(filepath, "a", _write)

    # 更新元数据首行
    _update_meta(session_id, project, role, content, usage, model)


def _update_meta(session_id: str, project: Path, role: str, content: Any, usage: dict | None, model: str):
    """更新内存中的 meta 缓存和索引，不重写 JSONL 文件。"""
    meta = _meta_cache.get(session_id)
    if meta is None:
        # 从文件加载
        filepath = project / f"{session_id}.jsonl"
        if filepath.exists():
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("type") == "meta":
                            meta = obj
                            break
                    except json.JSONDecodeError:
                        continue
    if meta is None:
        return

    meta["updated_at"] = datetime.now().isoformat()
    msg_count = meta.get("message_count", 0) + 1
    meta["message_count"] = msg_count
    if usage:
        meta["total_tokens"] = (
            meta.get("total_tokens", 0) + usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        )
    if model:
        meta["model"] = model
    if msg_count == 1 and role == "user":
        text = content if isinstance(content, str) else ""
        if isinstance(content, list):
            text = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        meta["first_message"] = text.strip()[:80]

    _meta_cache[session_id] = meta
    _update_index(project, meta)


def _update_index(project: Path, meta: dict):
    """更新项目的 session 索引文件。

    使用 flock 保护整个 read-modify-write，防止并发写丢更新。
    """
    index_file = project / "index.json"

    def _rmw(out_f):
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
                "pinned": meta.get("pinned", False),
            }
        json.dump(index, out_f, ensure_ascii=False, indent=2)

    _with_file_lock_atomic(index_file, _rmw)


# ── 加载会话 ──


def load_session(session_id: str, cwd: str | None = None, user_id: str | None = None) -> tuple[list[dict], str, dict]:
    """加载会话，返回 (messages, cwd, meta)。损坏行自动跳过。"""
    project = _project_dir(cwd, user_id)
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
                messages.append(
                    {
                        "role": obj["role"],
                        "content": _deserialize_content(obj["content"]),
                    }
                )

    if meta:
        _meta_cache[session_id] = meta
    _finalize_orphan_tool_uses(messages)
    # 加载后同步 hash 缓存，避免 load → 无操作 → save 触发重复写盘
    _last_saved_hash[session_id] = _messages_content_hash(messages)
    _get_logger().info("session 加载: %s messages=%d", session_id, len(messages))
    return messages, meta.get("cwd", ""), meta


def _load_legacy(filepath: Path) -> tuple[list[dict], str, dict]:
    """加载旧版 JSON 格式的 session。"""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    messages = [{"role": m["role"], "content": _deserialize_content(m["content"])} for m in data.get("messages", [])]
    _finalize_orphan_tool_uses(messages)
    meta = {
        "session_id": data.get("id", ""),
        "name": "",
        "cwd": data.get("cwd", ""),
        "first_message": _extract_first_message(messages),
        "message_count": len(messages),
    }
    return messages, data.get("cwd", ""), meta


# ── 列出会话 ──


def list_sessions(cwd: str | None = None, user_id: str | None = None) -> list[dict]:
    """列出当前项目的所有会话（从索引读取），按更新时间倒序。"""
    project = _project_dir(cwd, user_id)
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
    sessions.sort(key=lambda s: not s.get("pinned", False))
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


def rename_session(session_id: str, name: str, cwd: str | None = None, user_id: str | None = None):
    """重命名会话。"""
    project = _project_dir(cwd, user_id)
    filepath = project / f"{session_id}.jsonl"
    if not filepath.exists():
        return

    _rewrite_meta_field(filepath, "name", name)
    # 更新缓存
    meta = _meta_cache.get(session_id)
    if meta:
        meta["name"] = name
    # 更新索引（加 flock 防 RMW 丢更新）
    index_file = project / "index.json"
    if index_file.exists():

        def _rmw(out_f):
            try:
                with open(index_file, encoding="utf-8") as f:
                    index = json.load(f)
                if session_id in index:
                    index[session_id]["name"] = name
                    json.dump(index, out_f, ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, OSError):
                pass

        try:
            _with_file_lock_atomic(index_file, _rmw)
        except OSError:
            pass


def pin_session(session_id: str, pinned: bool, cwd: str | None = None, user_id: str | None = None):
    """设置会话的置顶状态。"""
    project = _project_dir(cwd, user_id)
    filepath = project / f"{session_id}.jsonl"
    if not filepath.exists():
        return

    _rewrite_meta_field(filepath, "pinned", pinned)
    meta = _meta_cache.get(session_id)
    if meta:
        meta["pinned"] = pinned
    index_file = project / "index.json"
    if index_file.exists():

        def _rmw(out_f):
            try:
                with open(index_file, encoding="utf-8") as f:
                    index = json.load(f)
                if session_id in index:
                    index[session_id]["pinned"] = pinned
                    json.dump(index, out_f, ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, OSError):
                pass

        try:
            _with_file_lock_atomic(index_file, _rmw)
        except OSError:
            pass


def _rewrite_meta_field(filepath: Path, key: str, value: Any):
    """修改 JSONL 文件 meta 行的某个字段（原子写入）。"""
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

    # 原子写入：先写临时文件再 rename
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(filepath.parent), prefix=".meta-", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        os.replace(tmp_path, str(filepath))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def export_session(session_id: str, output_path: str | None = None, cwd: str | None = None) -> str:
    """导出会话为纯文本，返回文件路径。"""
    messages, session_cwd, meta = load_session(session_id, cwd)
    if not output_path:
        safe_name = re.sub(r"[^\w]", "_", meta.get("name", session_id))
        output_path = f"session_{safe_name}.md"

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


def _finalize_orphan_tool_uses(messages: list[dict]) -> None:
    """规范化 messages：修复 server_tool_use 同消息内嵌 + 孤儿 tool_use/tool_result。

    三步处理：
    1. 将 assistant 消息中 server_tool_use+tool_result 拆分为标准 assistant→user 对
       （server_tool_use 转 tool_use 保留在 assistant，tool_result 移到下一条 user 消息）
    2. 清理孤儿 tool_result（无匹配 tool_use 的），防止已损坏的会话文件残留
    3. 为缺少 tool_result 的 tool_use 合成兜底结果
    """

    def _block_type(block):
        if isinstance(block, dict):
            return block.get("type", "")
        return getattr(block, "type", None) or ""

    def _block_id(block):
        if isinstance(block, dict):
            return block.get("id", "")
        return getattr(block, "id", None) or ""

    def _make_dict(block) -> dict:
        if isinstance(block, dict):
            return dict(block)
        # 优先用 SDK model_dump 保留全部字段（tool_result.tool_use_id 等）
        if hasattr(block, "model_dump"):
            return block.model_dump()
        if hasattr(block, "to_dict"):
            return block.to_dict()
        # 兜底：按 type 分字段构造
        bt = getattr(block, "type", "")
        if bt == "tool_result":
            return {
                "type": "tool_result",
                "tool_use_id": getattr(block, "tool_use_id", "") or "",
                "content": getattr(block, "content", ""),
            }
        return {
            "type": bt,
            "id": getattr(block, "id", ""),
            "name": getattr(block, "name", ""),
            "input": getattr(block, "input", {}),
        }

    # ── 第1步：拆分同消息内的 server_tool_use + tool_result ──
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") != "assistant":
            i += 1
            continue
        content = msg.get("content", "")
        if not isinstance(content, list):
            i += 1
            continue

        server_tool_ids: set[str] = set()
        for block in content:
            if _block_type(block) == "server_tool_use":
                tid = _block_id(block)
                if tid:
                    server_tool_ids.add(tid)

        if not server_tool_ids:
            i += 1
            continue

        kept_blocks = []
        moved_results = []
        for block in content:
            bt = _block_type(block)
            if bt == "server_tool_use":
                converted = _make_dict(block)
                converted["type"] = "tool_use"
                kept_blocks.append(converted)
            elif bt == "tool_result":
                tid = block.get("tool_use_id", "") if isinstance(block, dict) else getattr(block, "tool_use_id", "")
                if tid in server_tool_ids:
                    moved_results.append(_make_dict(block) if not isinstance(block, dict) else block)
                    continue
                kept_blocks.append(block)
            else:
                kept_blocks.append(block)

        messages[i]["content"] = kept_blocks

        if moved_results:
            messages.insert(i + 1, {"role": "user", "content": moved_results})
            i += 2
        else:
            i += 1

    # ── 第2步：收集所有 tool_use ID，清理孤儿 tool_result ──
    # 注意：assistant content 可能是 SDK 对象 list（agent.py 直接 append final_message.content），
    # 不能用 isinstance(block, dict) 判断，否则 SDK 形式的 tool_use 被跳过，
    # 引用其 id 的 dict tool_result 会被误判孤儿丢弃，破坏 messages 结构。
    all_tool_use_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        for block in content:
            if _block_type(block) in ("tool_use", "server_tool_use"):
                tid = _block_id(block)
                if tid:
                    all_tool_use_ids.add(tid)

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        filtered = []
        for block in content:
            if _block_type(block) == "tool_result":
                tid = block.get("tool_use_id", "") if isinstance(block, dict) else getattr(block, "tool_use_id", "")
                if tid and tid not in all_tool_use_ids:
                    continue  # 孤儿 tool_result，丢弃
            filtered.append(block)
        msg["content"] = filtered

    # ── 第2.5步：清理空消息（content 为 [] 的 user/assistant 消息）──
    messages[:] = [m for m in messages if m.get("content") or m.get("role") not in ("user", "assistant")]

    # ── 第3步：为缺少 tool_result 的 tool_use 合成兜底结果 ──
    existing_results: set[str] = set()
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        blocks = content if isinstance(content, list) else []
        for block in blocks:
            if _block_type(block) == "tool_result":
                tid = block.get("tool_use_id", "") if isinstance(block, dict) else getattr(block, "tool_use_id", "")
                if tid:
                    existing_results.add(tid)

    orphan_results: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") != "assistant":
            i += 1
            continue
        content = msg.get("content", "")
        if not isinstance(content, list):
            i += 1
            continue
        for block in content:
            if _block_type(block) not in ("tool_use", "server_tool_use"):
                continue
            tid = _block_id(block)
            if not tid or tid in existing_results:
                continue
            orphan_results.append(
                {"type": "tool_result", "tool_use_id": tid, "content": "[用户中断，工具未执行]"}
            )
            existing_results.add(tid)
        if orphan_results:
            if i + 1 < len(messages) and messages[i + 1].get("role") == "user":
                next_content = messages[i + 1].get("content", "")
                if isinstance(next_content, list):
                    next_content.extend(orphan_results)
            else:
                messages.insert(i + 1, {"role": "user", "content": orphan_results})
            orphan_results = []
            i += 1  # 跳过刚插入/修改的 user 消息
        i += 1


def save_session(messages: list[dict], session_id: str | None = None, user_id: str | None = None) -> str:
    """保存完整对话。每次全量重写，避免追加导致的内容重复问题。"""
    # 空会话不保存：用户没发任何消息就刷新/切走，直接丢弃
    if not messages:
        return session_id or ""

    if session_id is None:
        session_id = create_session(user_id=user_id)

    _finalize_orphan_tool_uses(messages)

    # 内容未变则跳过写盘（避免刷新/切换时重复保存）
    content_hash = _messages_content_hash(messages)
    if _last_saved_hash.get(session_id) == content_hash:
        return session_id
    _last_saved_hash[session_id] = content_hash

    project = _project_dir(user_id=user_id)
    filepath = project / f"{session_id}.jsonl"

    # 保留已有 meta 中的 created_at、name、total_tokens，以及扩展字段（mode 等）
    created_at = datetime.now().isoformat()
    name = ""
    total_tokens = 0
    model = ""
    extra_meta: dict[str, Any] = {}  # 承载 mode/interrupted_at 等扩展字段
    existing_meta = _meta_cache.get(session_id)
    if existing_meta:
        created_at = existing_meta.get("created_at", created_at)
        name = existing_meta.get("name", "")
        total_tokens = existing_meta.get("total_tokens", 0)
        model = existing_meta.get("model", "")
        extra_meta = {k: v for k, v in existing_meta.items() if k not in _META_CORE_FIELDS}
    elif filepath.exists():
        try:
            with open(filepath, encoding="utf-8") as f:
                first = f.readline().strip()
                if first:
                    old = json.loads(first)
                    created_at = old.get("created_at", created_at)
                    name = old.get("name", "")
                    total_tokens = old.get("total_tokens", 0)
                    model = old.get("model", "")
                    extra_meta = {k: v for k, v in old.items() if k not in _META_CORE_FIELDS}
        except (json.JSONDecodeError, OSError):
            pass

    meta = {
        "type": "meta",
        "session_id": session_id,
        "name": name,
        "cwd": get_cwd(),
        "git_branch": _git_branch(),
        "created_at": created_at,
        "updated_at": datetime.now().isoformat(),
        "message_count": len(messages),
        "total_tokens": total_tokens,
        "first_message": _extract_first_message(messages),
        "model": model,
    }
    # 透传扩展字段（mode/interrupted_at 等），不被硬编码字段集抹掉
    meta.update(extra_meta)

    def _write_full(f):
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for m in messages:
            record = {
                "type": "message",
                "role": m["role"],
                "content": _serialize_content(m["content"]),
                "timestamp": datetime.now().isoformat(),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    _with_file_lock_atomic(filepath, _write_full)
    _meta_cache[session_id] = meta
    _update_index(project, meta)
    _get_logger().info("session 保存: %s messages=%d", session_id, len(messages))
    return session_id


# ── 清理 ──


def cleanup_sessions(max_age_days: int = 30, cwd: str | None = None, user_id: str | None = None):
    """清理会话文件：
    - 删除超过 max_age_days 天未更新的会话
    - 删除没有 name 和 first_message 的空会话
    """
    project = _project_dir(cwd, user_id)
    if not project.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=max_age_days)
    count = 0

    # 先清理索引中既无 name 也无 first_message 的空会话
    index_file = project / "index.json"
    index = {}
    if index_file.exists():
        try:
            with open(index_file, encoding="utf-8") as f:
                index = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # 找出并删除空会话（无 name 且无 first_message）
    empty_sids = [sid for sid, info in index.items() if not info.get("name") and not info.get("first_message")]
    for sid in empty_sids:
        fp = project / f"{sid}.jsonl"
        try:
            fp.unlink(missing_ok=True)
            count += 1
        except OSError:
            pass
        del index[sid]

    # 按时间清理：扫描所有 jsonl 文件
    for jsonl_file in project.glob("*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
            if mtime < cutoff:
                jsonl_file.unlink()
                count += 1
                sid = jsonl_file.stem
                index.pop(sid, None)
        except OSError:
            continue

    # 清理索引中的孤儿条目（指向已不存在的文件）
    to_remove = [sid for sid in index if not (project / f"{sid}.jsonl").exists()]
    for sid in to_remove:
        del index[sid]

    # 原子写入更新后的索引
    if index_file.exists() or (count > 0 and index):
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(project), prefix=".index-", suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(index, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, str(index_file))
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError:
            pass

    if count > 0:
        _get_logger().info("session 清理: 移除了 %d 个过期/空会话", count)
    return count
