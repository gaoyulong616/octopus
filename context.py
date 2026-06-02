"""上下文窗口管理和系统提示词构建。"""

import json
import os
import subprocess
import time as _time
from datetime import datetime
from typing import Any

import anthropic

from config import get
from tools import get_cwd

_MEMORY_FILE = os.path.expanduser("~/.octopus/memory.md")

# ── 系统提示词缓存 ──
_cached_prompt: str | None = None
_cached_prompt_mtime: float = 0.0
_cached_cwd: str = ""
_CACHE_TTL = 5.0  # seconds


def _load_memory() -> str:
    try:
        with open(_MEMORY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def save_memory(text: str) -> str:
    """追加记忆到 memory.md。"""
    os.makedirs(os.path.dirname(_MEMORY_FILE), exist_ok=True)
    with open(_MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n- {text}\n")
    return f"已记住: {text}"


def clear_memory() -> str:
    """清除所有记忆。"""
    if os.path.exists(_MEMORY_FILE):
        os.remove(_MEMORY_FILE)
    return "记忆已清除"


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
                        parts.append(
                            f"[{role}:tool_result] {str(block.get('content', ''))[:500]}"
                        )
                elif hasattr(block, "text") and block.text:
                    parts.append(f"[{role}] {block.text}")
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
    """
    chars = _estimate_chars(messages)
    threshold = get("context_threshold", 120_000)
    if not force and chars < threshold:
        return messages

    keep_recent = 4
    if len(messages) <= keep_recent + 2:
        # 即使全部保留也超限，截断过长的 tool_result
        return _truncate_tool_results(messages)

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
    except Exception:
        return _truncate_tool_results(messages)

    compressed = [
        {"role": "user", "content": f"[上下文摘要] {summary}"},
        {"role": "assistant", "content": "收到，我已了解之前的上下文。"},
    ]
    result = compressed + recent_messages

    # 如果压缩后仍超限，进一步截断
    if _estimate_chars(result) > threshold:
        return _truncate_tool_results(result)

    return result


def _truncate_tool_results(messages: list[dict], max_result_chars: int = 2000) -> list[dict]:
    """截断过长的 tool_result 内容，避免上下文溢出。"""
    truncated = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, list):
            new_content = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    result_text = str(block.get("content", ""))
                    if len(result_text) > max_result_chars:
                        block = dict(block)
                        block["content"] = result_text[:max_result_chars] + f"\n... (已截断，原长度 {len(result_text)})"
                new_content.append(block)
            truncated.append({**m, "content": new_content})
        else:
            truncated.append(m)
    return truncated


# ─────────────────────────────────────────────
# 系统提示词
# ─────────────────────────────────────────────

def _get_project_overview() -> str:
    """自动扫描项目根目录，生成简要的结构概览。"""
    cwd = get_cwd()
    lines = []

    # 检测 git 状态
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        if result.returncode == 0:
            branch_line = result.stdout.split("\n")[0]
            changes = [l for l in result.stdout.split("\n")[1:] if l.strip()]
            git_info = f"Git: {branch_line.strip()}"
            if changes:
                git_info += f"，{len(changes)} 个未提交变更"
            lines.append(git_info)
    except Exception:
        pass

    # 列出顶层文件/目录
    try:
        entries = sorted(os.listdir(cwd))
        dirs = [e for e in entries
                if os.path.isdir(os.path.join(cwd, e)) and not e.startswith(".")]
        files = [e for e in entries
                 if os.path.isfile(os.path.join(cwd, e)) and not e.startswith(".")]
        if dirs:
            lines.append(f"目录: {', '.join(dirs[:20])}")
        if files:
            lines.append(f"文件: {', '.join(files[:20])}")
    except Exception:
        pass

    return "\n".join(lines)


def _load_project_instructions() -> str:
    """加载多级项目指令：个人级 → 项目级 → 子目录级。

    加载顺序：
    1. 个人级: ~/.octopus/CLAUDE.md
    2. 项目级: 当前目录的 CLAUDE.md 或 OCTOPUS.md
    3. 子目录级: .claude/CLAUDE.md 或 .octopus/CLAUDE.md
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
            with open(abs_path, encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                sections.append((title, content))
                loaded_paths.add(abs_path)
                return True
        except OSError:
            pass
        return False

    # 1. 个人级：~/.octopus/OCTOPUS.md 或 ~/.claude/CLAUDE.md
    _try_load(os.path.expanduser("~/.octopus/OCTOPUS.md"), "个人级指令")
    _try_load(os.path.expanduser("~/.claude/CLAUDE.md"), "个人级指令")

    # 2. 项目级：当前目录下的 OCTOPUS.md 或 CLAUDE.md
    for name in ("OCTOPUS.md", "CLAUDE.md"):
        if _try_load(os.path.join(cwd, name), f"项目指令 ({name})"):
            break

    # 3. 子目录级：各代码模块目录下的指令文件
    try:
        entries = sorted(os.listdir(cwd))
    except OSError:
        entries = []
    for entry in entries:
        subdir = os.path.join(cwd, entry)
        if not os.path.isdir(subdir):
            continue
        if entry.startswith(".") or entry.startswith("__"):
            continue
        for name in ("OCTOPUS.md", "CLAUDE.md"):
            if _try_load(os.path.join(subdir, name), f"模块指令 ({entry}/{name})"):
                break

    if not sections:
        return ""

    parts: list[str] = []
    for title, content in sections:
        parts.append(f"### {title}\n{content}")
    return "\n\n".join(parts)


def _instruction_files_changed() -> bool:
    """检查项目指令文件是否有变更。"""
    cwd = get_cwd()
    check_files = [
        os.path.expanduser("~/.octopus/OCTOPUS.md"),
        os.path.expanduser("~/.claude/CLAUDE.md"),
        os.path.join(cwd, "OCTOPUS.md"),
        os.path.join(cwd, "CLAUDE.md"),
    ]
    for f in check_files:
        if os.path.isfile(f):
            try:
                mtime = os.path.getmtime(f)
                if mtime > _cached_prompt_mtime:
                    return True
            except OSError:
                pass
    return False


def build_system_prompt(force_refresh: bool = False) -> str:
    """动态构建系统提示词（带缓存）。"""
    global _cached_prompt, _cached_prompt_mtime, _cached_cwd

    cwd = get_cwd()
    now = _time.monotonic()

    # Check if cache is valid
    if (not force_refresh
            and _cached_prompt is not None
            and _cached_cwd == cwd
            and (now - _cached_prompt_mtime) < _CACHE_TTL):
        # Check if instruction files changed
        if not _instruction_files_changed():
            return _cached_prompt

    # Build fresh prompt
    overview = _get_project_overview()
    overview_section = ""
    if overview:
        overview_section = f"\n## 当前环境\n{overview}\n"

    instructions = _load_project_instructions()
    instructions_section = ""
    if instructions:
        instructions_section = f"\n## 项目指令\n{instructions}\n"

    memory_section = ""
    memory = _load_memory()
    if memory:
        memory_section = f"\n## 记忆\n{memory}\n"

    result = f"""你是一个强大的 AI Agent，可以通过工具完成各种编程任务。

今天是 {datetime.now().strftime('%Y-%m-%d')}。工作目录: {get_cwd()}
{overview_section}{instructions_section}{memory_section}
## 工作原则
- 拿到任务后先思考，再选择合适的工具
- 复杂任务开始前，先用 task_create 创建任务列表规划步骤，逐步用 task_update 标记进度
- 编辑已有文件时优先使用 edit_file，而非 write_file 重写整个文件
- 大文件使用 read_file 的 offset/limit 参数分段读取，避免一次性加载
- 遇到错误要分析原因并尝试修复，最多重试3次
- 任务完成后用清晰的语言告知用户结果
- 如果任务无法完成，说明原因

## 输出风格
- 简洁清晰，不啰嗦
- 代码用 markdown 代码块包裹
- 重要结果高亮展示
"""

    _cached_prompt = result
    _cached_prompt_mtime = now
    _cached_cwd = cwd
    return result
