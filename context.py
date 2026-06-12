"""上下文窗口管理和系统提示词构建。"""

import json
import os
import re
import subprocess
import time as _time
from datetime import datetime

import anthropic

from config import get, run_hooks, get_context_window
from logger import get_logger as _get_logger
from tools import get_cwd

# ── Memory：类型化、索引化的跨会话记忆 ──

_MEMORY_DIR = os.path.expanduser("~/.octopus/memory")
_MEMORY_INDEX = os.path.join(_MEMORY_DIR, "MEMORY.md")
_LEGACY_MEMORY_FILE = os.path.expanduser("~/.octopus/memory.md")

MEMORY_TYPES = ("user", "feedback", "project", "reference")


def _slugify(text: str) -> str:
    """把文本转为文件名安全的 slug。"""
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s[:48] or "memory"


def _ensure_memory_dir():
    os.makedirs(_MEMORY_DIR, exist_ok=True)


def _migrate_legacy_memory():
    """若旧 memory.md 存在且新目录为空，迁移为 user/legacy.md。"""
    if not os.path.isfile(_LEGACY_MEMORY_FILE):
        return
    if os.path.isdir(_MEMORY_DIR) and os.listdir(_MEMORY_DIR):
        return
    try:
        with open(_LEGACY_MEMORY_FILE, encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return
        _ensure_memory_dir()
        # 保存为 user 类型下的 legacy.md
        target = os.path.join(_MEMORY_DIR, "user", "legacy.md")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write("---\nname: legacy\ndescription: 从旧 memory.md 迁移的备忘\ntype: user\n---\n\n" + content)
        # 重命名旧文件避免重复迁移
        try:
            os.rename(_LEGACY_MEMORY_FILE, _LEGACY_MEMORY_FILE + ".bak")
        except OSError:
            pass
    except OSError as e:
        _get_logger().warning("memory 迁移失败: %s: %s", type(e).__name__, e)


def _parse_memory_file(path: str) -> dict | None:
    """解析单个 memory 文件，返回元数据字典。"""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None
    meta: dict = {"path": path, "content": content}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            raw = parts[1].strip()
            body = parts[2].strip()
            for line in raw.split("\n"):
                m = re.match(r"^(\w+):\s*(.*)$", line.strip())
                if m:
                    meta[m.group(1)] = m.group(2).strip().strip('"').strip("'")
            meta["body"] = body
    return meta


def _write_index(entries: list[dict]):
    """重写 MEMORY.md 索引（每行 ≤ 150 字符）。"""
    _ensure_memory_dir()
    lines = ["# Memory Index", ""]
    for e in entries:
        mtype = e.get("type", "user")
        name = e.get("name", "?")
        desc = e.get("description", "")
        slug = os.path.splitext(os.path.basename(e["path"]))[0]
        line = f"- [{name}]({mtype}/{slug}.md) — {desc}"
        if len(line) > 150:
            line = line[:147] + "..."
        lines.append(line)
    try:
        with open(_MEMORY_INDEX, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass


def _scan_memory_dir() -> list[dict]:
    """扫描所有 memory 文件，返回元数据列表。"""
    _migrate_legacy_memory()
    if not os.path.isdir(_MEMORY_DIR):
        return []
    entries: list[dict] = []
    for mtype in MEMORY_TYPES:
        type_dir = os.path.join(_MEMORY_DIR, mtype)
        if not os.path.isdir(type_dir):
            continue
        for fname in sorted(os.listdir(type_dir)):
            if not fname.endswith(".md") or fname.startswith("_"):
                continue
            meta = _parse_memory_file(os.path.join(type_dir, fname))
            if meta:
                meta.setdefault("type", mtype)
                meta.setdefault("name", os.path.splitext(fname)[0])
                entries.append(meta)
    return entries


def _load_memory() -> str:
    """加载 memory 索引注入系统提示词（仅索引行，正文按需读取）。"""
    entries = _scan_memory_dir()
    if not entries:
        return ""
    _write_index(entries)
    lines = [f"已加载 {len(entries)} 条记忆（按类型组织于 ~/.octopus/memory/）：", ""]
    by_type: dict[str, list[dict]] = {}
    for e in entries:
        by_type.setdefault(e.get("type", "user"), []).append(e)
    type_labels = {"user": "用户", "feedback": "反馈", "project": "项目", "reference": "引用"}
    for t in MEMORY_TYPES:
        if t not in by_type:
            continue
        lines.append(f"### {type_labels.get(t, t)}")
        for e in by_type[t]:
            name = e.get("name", "?")
            desc = e.get("description", "")
            lines.append(f"- {name}: {desc}")
        lines.append("")
    return "\n".join(lines).strip()


def save_memory(text: str, mtype: str = "user", name: str | None = None, description: str | None = None) -> str:
    """保存一条记忆。

    Args:
        text: 记忆正文。
        mtype: 类型（user/feedback/project/reference）。
        name: 简短名称（用于文件名和索引），不传则从 text 生成。
        description: 一句话描述（用于索引），不传则取 text 首句。
    """
    if mtype not in MEMORY_TYPES:
        mtype = "user"
    _ensure_memory_dir()
    name = (name or _slugify(text[:32])).strip()
    if not name:
        name = "memory"
    slug = _slugify(name)
    desc = (description or text.split("\n")[0]).strip()
    if len(desc) > 100:
        desc = desc[:97] + "..."

    type_dir = os.path.join(_MEMORY_DIR, mtype)
    os.makedirs(type_dir, exist_ok=True)
    target = os.path.join(type_dir, f"{slug}.md")

    # 同名已存在则递增 -2、-3
    counter = 1
    while os.path.exists(target):
        counter += 1
        target = os.path.join(type_dir, f"{slug}-{counter}.md")

    frontmatter = (
        f"---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        f"type: {mtype}\n"
        f"created: {datetime.now().isoformat(timespec='seconds')}\n"
        f"---\n\n"
    )
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(frontmatter + text.strip() + "\n")
    except OSError as e:
        return f"保存失败: {e}"

    # 更新索引
    entries = _scan_memory_dir()
    _write_index(entries)
    return f"已记住 [{mtype}] {name}: {desc}"


def list_memories(mtype: str | None = None) -> list[dict]:
    """列出所有 memory 元数据。可选按类型过滤。"""
    entries = _scan_memory_dir()
    if mtype:
        entries = [e for e in entries if e.get("type") == mtype]
    return entries


def delete_memory(query: str) -> str:
    """按 name 或 slug 删除 memory。"""
    entries = _scan_memory_dir()
    if not entries:
        return "暂无记忆"
    query_lower = query.lower().strip()
    matched = []
    for e in entries:
        name = e.get("name", "").lower()
        slug = os.path.splitext(os.path.basename(e["path"]))[0].lower()
        if query_lower in name or query_lower == slug or query_lower in slug:
            matched.append(e)
    if not matched:
        return f"未找到匹配 '{query}' 的记忆"
    deleted = []
    for e in matched:
        try:
            os.remove(e["path"])
            deleted.append(e.get("name", "?"))
        except OSError:
            pass
    _write_index(_scan_memory_dir())
    return f"已删除 {len(deleted)} 条: {', '.join(deleted)}"


def clear_memory() -> str:
    """清除所有记忆（删除 memory 目录下所有文件）。"""
    import shutil

    if not os.path.isdir(_MEMORY_DIR):
        return "记忆已为空"
    try:
        shutil.rmtree(_MEMORY_DIR)
        return "所有记忆已清除"
    except OSError as e:
        return f"清除失败: {e}"


# ── 系统提示词缓存 ──
_cached_prompt: str | None = None
_cached_prompt_mtime: float = 0.0  # 用于 TTL 判断（_time.monotonic）
_cached_build_time: float = 0.0  # 用于文件 mtime 比较（_time.time）
_cached_cwd: str = ""
_CACHE_TTL = 5.0  # seconds

# ── 环境概览缓存 ──
_git_status_cache: str = ""
_git_status_mtime: float = 0.0
_GIT_CACHE_TTL = 30.0
_dir_listing_cache: str = ""
_dir_listing_mtime: float = 0.0
_DIR_LISTING_TTL = 60.0
_overview_cached_cwd: str = ""

# ── Skill 描述预算 ──
_SKILL_DESC_BUDGET_RATIO = 0.01  # 上下文窗口的 1%
_SKILL_DESC_MAX_CHARS = 1536     # 单条描述字符上限


def _estimate_chars(messages: list[dict]) -> int:
    """粗略估算 messages 的总字符数。"""
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block))
                elif hasattr(block, "text"):
                    total += len(block.text) if block.text else 0
                elif hasattr(block, "thinking"):
                    total += len(block.thinking) if block.thinking else 0
                elif hasattr(block, "input"):
                    total += len(json.dumps(block.input, ensure_ascii=False))
        else:
            total += len(str(content))
    return total


def _messages_to_text(messages: list[dict]) -> str:
    """将 messages 转为纯文本用于摘要。"""
    parts = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            parts.append(f"[{role}] {content}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append(f"[{role}] {block.get('text', '')}")
                    elif btype == "tool_use":
                        parts.append(
                            f"[{role}:tool_use:{block.get('name', '')}] "
                            f"{json.dumps(block.get('input', {}), ensure_ascii=False)}"
                        )
                    elif btype == "tool_result":
                        parts.append(f"[{role}:tool_result] {str(block.get('content', ''))[:500]}")
                    elif btype == "thinking":
                        thinking = block.get("thinking", "")
                        if thinking:
                            parts.append(f"[{role}:thinking] {thinking[:500]}")
                elif hasattr(block, "text") and block.text:
                    parts.append(f"[{role}] {block.text}")
                elif hasattr(block, "thinking") and block.thinking:
                    parts.append(f"[{role}:thinking] {block.thinking[:500]}")
                elif hasattr(block, "input"):
                    # API 返回的 ToolUseBlock 对象
                    name = getattr(block, "name", "")
                    parts.append(f"[{role}:tool_use:{name}] {json.dumps(block.input, ensure_ascii=False)}")
        else:
            parts.append(f"[{role}] {str(content)[:500]}")
    return "\n".join(parts)


def compress_messages(
    client: anthropic.Anthropic,
    messages: list[dict],
    model: str,
    force: bool = False,
) -> list[dict]:
    """当 messages 过长时，用 LLM 摘要压缩早期对话，保留最近的部分。

    支持渐进式压缩：先压缩最旧的，如果仍超限则进一步压缩。
    当 force=True 时，跳过阈值检查直接压缩（用于显式 /compact 命令）。
    压缩前触发 PreCompact hook，允许外部脚本介入或记录。
    """
    chars = _estimate_chars(messages)
    # 阈值优先用 context_threshold 配置，否则根据模型上下文窗口自动计算
    manual_threshold = get("context_threshold")
    if manual_threshold:
        threshold = manual_threshold
    else:
        # 模型上下文窗口 (tokens) × 3 (chars/token) × 0.7 (安全余量)
        context_window = get_context_window(model)
        threshold = int(context_window * 3 * 0.7)
    if not force and chars < threshold:
        # 即使不压缩，也需清理不能重发的 server block 类型
        needs_clean = False
        for m in messages:
            c = m.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") in ("server_tool_use", "web_search_tool_result", "web_fetch_tool_result"):
                        needs_clean = True
                        break
            if needs_clean:
                break
        if needs_clean:
            return _truncate_tool_results(messages, max_result_chars=999999)
        return messages

    # PreCompact hook：压缩前通知外部
    try:
        run_hooks(
            "PreCompact",
            {
                "messages": str(len(messages)),
                "chars": str(chars),
                "threshold": str(threshold),
                "forced": "1" if force else "0",
            },
        )
    except Exception as e:
        _get_logger().warning("PreCompact hook 异常: %s: %s", type(e).__name__, e)

    keep_recent = 4
    if len(messages) <= keep_recent + 2:
        # 即使全部保留也超限，截断过长的 tool_result
        return _truncate_tool_results(messages)  # noqa: PostCompact skipped — no real compression occurred

    old_messages = messages[:-keep_recent]
    recent_messages = messages[-keep_recent:]

    summary_prompt = (
        "请将以下对话历史压缩为一段简洁的摘要，保留关键信息："
        "做了什么操作、修改了哪些文件、得到了什么结论。"
        "用中文输出，不超过 500 字。不要输出其他内容。\n\n"
        f"{_messages_to_text(old_messages)}"
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": summary_prompt}],
        )
        summary = next((b.text for b in resp.content if b.type == "text"), "")
        if not summary:
            return _truncate_tool_results(messages)
    except Exception as e:
        _get_logger().warning("上下文压缩 LLM 调用失败: %s: %s", type(e).__name__, e)
        return _truncate_tool_results(messages)

    compressed = [
        {"role": "user", "content": f"[上下文摘要] {summary}"},
        {"role": "assistant", "content": "收到，我已了解之前的上下文。"},
    ]
    result = compressed + recent_messages

    # 如果压缩后仍超限，进一步截断
    if _estimate_chars(result) > threshold:
        result = _truncate_tool_results(result)

    # PostCompact hook：压缩后通知外部
    try:
        run_hooks(
            "PostCompact",
            {
                "message_count": str(len(result)),
            },
        )
    except Exception as e:
        _get_logger().warning("PostCompact hook 异常: %s: %s", type(e).__name__, e)

    return result


def _truncate_tool_results(messages: list[dict], max_result_chars: int = 2000) -> list[dict]:
    """截断过长的 tool_result 内容，避免上下文溢出。

    同时将 server_tool_use / web_search_tool_result / web_fetch_tool_result
    转为普通 text block，因为这些类型不能在后续 API 请求中重发。
    """
    _server_block_types = {"server_tool_use", "web_search_tool_result", "web_fetch_tool_result"}
    truncated = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, list):
            new_content = []
            for block in content:
                if not isinstance(block, dict):
                    # SDK 对象（ThinkingBlock/TextBlock 等）转 dict
                    if hasattr(block, "type"):
                        if hasattr(block, "model_dump"):
                            block = block.model_dump()
                        elif hasattr(block, "to_dict"):
                            block = block.to_dict()
                        else:
                            block = {"type": block.type, **{k: getattr(block, k) for k in vars(block) if not k.startswith("_")}}
                    else:
                        continue
                btype = block.get("type", "")
                if btype == "tool_result":
                    result_text = str(block.get("content", ""))
                    if len(result_text) > max_result_chars:
                        block = dict(block)
                        block["content"] = result_text[:max_result_chars] + f"\n... (已截断，原长度 {len(result_text)})"
                elif btype in _server_block_types:
                    # 转为 text block，保留摘要信息
                    if btype == "server_tool_use":
                        summary = f"[{block.get('name', 'server_tool')}: {json.dumps(block.get('input', {}), ensure_ascii=False)[:200]}]"
                    elif btype in ("web_search_tool_result", "web_fetch_tool_result"):
                        results = block.get("content", [])
                        if isinstance(results, list):
                            summary = f"[{btype}: {len(results)} results]"
                        else:
                            summary = f"[{btype}]"
                    else:
                        summary = f"[{btype}]"
                    block = {"type": "text", "text": summary}
                new_content.append(block)
            truncated.append({**m, "content": new_content})
        else:
            truncated.append(m)
    return truncated


# ─────────────────────────────────────────────
# 系统提示词
# ─────────────────────────────────────────────


def _get_project_overview() -> str:
    """自动扫描项目根目录，生成简要的结构概览（带缓存）。"""
    global _git_status_cache, _git_status_mtime
    global _dir_listing_cache, _dir_listing_mtime, _overview_cached_cwd

    cwd = get_cwd()
    now = _time.monotonic()

    # cwd 变化时清空所有缓存
    if cwd != _overview_cached_cwd:
        _git_status_cache = ""
        _dir_listing_cache = ""
        _overview_cached_cwd = cwd

    lines = []

    # 检测 git 状态（30s 缓存）
    if not _git_status_cache or (now - _git_status_mtime) >= _GIT_CACHE_TTL:
        try:
            result = subprocess.run(
                ["git", "status", "--short", "--branch"],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=5,
            )
            if result.returncode == 0:
                branch_line = result.stdout.split("\n")[0]
                changes = [l for l in result.stdout.split("\n")[1:] if l.strip()]
                git_info = f"Git: {branch_line.strip()}"
                if changes:
                    git_info += f"，{len(changes)} 个未提交变更"
                _git_status_cache = git_info
            else:
                _git_status_cache = ""
        except Exception as e:
            _get_logger().debug("获取 git 信息失败: %s: %s", type(e).__name__, e)
            _git_status_cache = ""
        _git_status_mtime = now

    if _git_status_cache:
        lines.append(_git_status_cache)

    # 列出顶层文件/目录（60s 缓存）
    if not _dir_listing_cache or (now - _dir_listing_mtime) >= _DIR_LISTING_TTL:
        dir_lines = []
        try:
            entries = sorted(os.listdir(cwd))
            dirs = [e for e in entries if os.path.isdir(os.path.join(cwd, e)) and not e.startswith(".")]
            files = [e for e in entries if os.path.isfile(os.path.join(cwd, e)) and not e.startswith(".")]
            if dirs:
                dir_lines.append(f"目录: {', '.join(dirs[:20])}")
            if files:
                dir_lines.append(f"文件: {', '.join(files[:20])}")
        except Exception as e:
            _get_logger().debug("列出工作目录文件失败: %s: %s", type(e).__name__, e)
        _dir_listing_cache = "\n".join(dir_lines)
        _dir_listing_mtime = now

    if _dir_listing_cache:
        lines.append(_dir_listing_cache)

    return "\n".join(lines)


# ── 项目指令文件内容缓存 ──
_instruction_cache: dict[str, tuple[float, str]] = {}  # {abs_path: (mtime, content)}


def _load_project_instructions() -> str:
    """加载多级项目指令：个人级 → 项目级 → 子目录级。

    加载顺序：
    1. 个人级: ~/.octopus/OCTOPUS.md
    2. 项目级: 当前目录的 OCTOPUS.md
    3. 子目录级: 各代码模块目录下的 OCTOPUS.md

    文件内容通过 mtime 缓存，避免每次重复读磁盘。
    """
    cwd = get_cwd()
    sections: list[tuple[str, str]] = []
    loaded_paths: set[str] = set()

    def _try_load(path: str, title: str) -> bool:
        abs_path = os.path.abspath(path)
        if abs_path in loaded_paths:
            return False
        if not os.path.isfile(abs_path):
            return False
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError:
            return False

        # mtime 缓存命中则用缓存内容
        cached = _instruction_cache.get(abs_path)
        if cached and cached[0] == mtime:
            content = cached[1]
        else:
            try:
                with open(abs_path, encoding="utf-8") as f:
                    content = f.read().strip()
                _instruction_cache[abs_path] = (mtime, content)
            except OSError:
                return False

        if content:
            sections.append((title, content))
            loaded_paths.add(abs_path)
            return True
        return False

    # 1. 个人级：~/.octopus/OCTOPUS.md
    _try_load(os.path.expanduser("~/.octopus/OCTOPUS.md"), "个人级指令")

    # 2. 项目级：当前目录下的 OCTOPUS.md
    _try_load(os.path.join(cwd, "OCTOPUS.md"), "项目指令")

    # 3. 子目录级：只列出可用的模块目录，不加载内容（按需读取）
    try:
        entries = sorted(os.listdir(cwd))
    except OSError:
        entries = []
    available_modules = []
    for entry in entries:
        subdir = os.path.join(cwd, entry)
        if not os.path.isdir(subdir):
            continue
        if entry.startswith(".") or entry.startswith("__"):
            continue
        if os.path.isfile(os.path.join(subdir, "OCTOPUS.md")):
            available_modules.append(entry)
    if available_modules:
        parts_list: list[str] = []
        for title, content in sections:
            parts_list.append(f"### {title}\n{content}")
        parts_list.append(
            "### 模块指令（按需加载）\n"
            f"以下子目录包含 OCTOPUS.md: {', '.join(available_modules)}\n"
            "访问该目录下的文件时，应先 read_file 对应的 OCTOPUS.md。"
        )
        return "\n\n".join(parts_list)

    if not sections:
        return ""

    parts: list[str] = []
    for title, content in sections:
        parts.append(f"### {title}\n{content}")
    return "\n\n".join(parts)


def _instruction_files_changed() -> bool:
    """检查项目指令文件是否有变更（含子目录）。"""
    cwd = get_cwd()
    check_files = [
        os.path.expanduser("~/.octopus/OCTOPUS.md"),
        os.path.join(cwd, "OCTOPUS.md"),
    ]
    # 也检查子目录指令文件
    try:
        entries = sorted(os.listdir(cwd))
    except OSError:
        entries = []
    for entry in entries:
        subdir = os.path.join(cwd, entry)
        if os.path.isdir(subdir) and not entry.startswith(".") and not entry.startswith("__"):
            check_files.append(os.path.join(subdir, "OCTOPUS.md"))

    for f in check_files:
        if os.path.isfile(f):
            try:
                mtime = os.path.getmtime(f)
                if mtime > _cached_build_time:
                    return True
            except OSError:
                pass
    return False


def build_system_prompt(force_refresh: bool = False) -> str:
    """动态构建系统提示词（带缓存）。

    .. deprecated:: 使用 build_system_blocks() 替代，支持分层缓存。
    """
    blocks = build_system_blocks(force_refresh)
    return "\n".join(b["text"] for b in blocks)


# ── L1/L2 双块缓存 ──
_cached_l1_text: str | None = None
_cached_l1_mtime: float = 0.0
_cached_l2_text: str | None = None
_cached_l2_mtime: float = 0.0
_cached_blocks_cwd: str = ""


def build_system_blocks(force_refresh: bool = False) -> list[dict]:
    """构建双块系统提示词：L1 稳定 + L2 动态，各自带 cache_control。

    L1（稳定，会话内几乎不变）: 身份头 + 记忆 + 工作原则/输出风格
    L2（动态，30s 级别变化）: 环境概览 + 项目指令 + Skills 描述
    """
    global _cached_l1_text, _cached_l1_mtime
    global _cached_l2_text, _cached_l2_mtime
    global _cached_blocks_cwd, _cached_build_time

    cwd = get_cwd()
    now = _time.monotonic()
    l1_changed = force_refresh or _cached_blocks_cwd != cwd
    l2_changed = l1_changed or (now - _cached_l2_mtime) >= _CACHE_TTL or _instruction_files_changed()

    # ── L1: 稳定块 ──
    if l1_changed or _cached_l1_text is None:
        memory = _load_memory()
        memory_section = f"\n## 记忆\n{memory}\n" if memory else ""

        model_name = get("model")
        provider = get("provider") or ""
        provider_info = f"（提供商: {provider}）" if provider else ""

        _cached_l1_text = (
            f"你是 Octopus，一个 AI 编程助手。你当前运行在 {model_name} 模型上{provider_info}。"
            f"你可以通过工具完成各种编程任务。\n\n"
            f"今天是 {datetime.now().strftime('%Y-%m-%d')}。工作目录: {cwd}\n"
            f"{memory_section}"
            "## 工作原则\n"
            "- 拿到任务后先思考，再选择合适的工具\n"
            "- 复杂任务开始前，先用 task_create 创建任务列表规划步骤，逐步用 task_update 标记进度\n"
            "- 编辑已有文件时优先使用 edit_file，而非 write_file 重写整个文件\n"
            "- 大文件使用 read_file 的 offset/limit 参数分段读取，避免一次性加载\n"
            "- 遇到错误要分析原因并尝试修复，最多重试3次\n"
            "- 任务完成后用清晰的语言告知用户结果\n"
            "- 如果任务无法完成，说明原因\n\n"
            "## 输出风格\n"
            "- 简洁清晰，不啰嗦\n"
            "- 代码用 markdown 代码块包裹\n"
            "- 重要结果高亮展示\n"
        )
        _cached_l1_mtime = now

    # ── L2: 动态块 ──
    if l2_changed or _cached_l2_text is None:
        overview = _get_project_overview()
        overview_section = f"\n## 当前环境\n{overview}\n" if overview else ""

        instructions = _load_project_instructions()
        instructions_section = f"\n## 项目指令\n{instructions}\n" if instructions else ""

        skills_section = ""
        try:
            from skills import load_skills

            skills = load_skills()
            if skills:
                from config import get_context_window

                total_budget = int(get_context_window(get("model")) * _SKILL_DESC_BUDGET_RATIO * 3)
                sorted_skills = sorted(skills.items())
                lines = ["\n## 可用 Skills（通过 invoke_skill 工具按需加载）"]
                used = 0
                for i, (s_name, s_def) in enumerate(sorted_skills):
                    desc = s_def.description or "(无描述)"
                    if len(desc) > _SKILL_DESC_MAX_CHARS:
                        desc = desc[:_SKILL_DESC_MAX_CHARS - 3] + "..."
                    entry = f"- **{s_name}**: {desc}"
                    if used + len(entry) > total_budget:
                        remaining = len(sorted_skills) - i
                        lines.append(f"- ... 还有 {remaining} 个 skill 未显示（已超出预算）")
                        break
                    lines.append(entry)
                    used += len(entry)
                skills_section = "\n".join(lines) + "\n"
        except Exception as e:
            _get_logger().debug("加载 skills 失败: %s: %s", type(e).__name__, e)

        _cached_l2_text = f"{overview_section}{instructions_section}{skills_section}"
        _cached_l2_mtime = now
        _cached_build_time = _time.time()

    _cached_blocks_cwd = cwd

    return [
        {"type": "text", "text": _cached_l1_text, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": _cached_l2_text, "cache_control": {"type": "ephemeral"}},
    ]
