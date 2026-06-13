"""Statusline 渲染：在 TUI 顶部/底部显示一行可配置的状态信息。

模板占位符（由 render_statusline 替换）：
  {model}       — 当前模型名
  {cwd}         — 当前工作目录（缩写为 ~/... 形式）
  {cwd_full}    — 完整 cwd
  {git_branch}  — 当前 git 分支（不在 git 仓库则空）
  {tokens}      — 当前会话累计 token（input+output，由 state 提供）
  {session_id}  — 当前会话 ID（前 8 位）
  {cost}        — 当前会话累计成本（由 state 提供）
  {agent}       — 当前自定义 agent 名（未切换则空）

模板示例："{model}  |  {git_branch}  |  {cwd}  |  {tokens} tokens  |  ${cost}"
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

_branch_cache: dict[str, tuple[float, str]] = {}  # cwd -> (timestamp, branch)
_BRANCH_TTL = 5.0  # seconds


def _get_git_branch(cwd: str) -> str:
    now = time.monotonic()
    cached = _branch_cache.get(cwd)
    if cached and (now - cached[0]) < _BRANCH_TTL:
        return cached[1]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=2,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            _branch_cache[cwd] = (now, branch)
            return branch
    except Exception:
        pass
    _branch_cache[cwd] = (now, "")
    return ""


def _shorten_cwd(cwd: str) -> str:
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        return "~" + cwd[len(home):]
    return cwd


class _SafeDict(dict):
    """format_map 时缺失字段留空字符串而不抛错。"""

    def __missing__(self, key):
        return ""


def render_statusline(state: dict | None = None) -> str:
    """根据 config['statusline'] 模板和当前 state 渲染一行状态文本。"""
    from config import get
    template = get("statusline", "")
    if not template:
        return ""

    state = state or {}
    from tools import get_cwd
    cwd = get_cwd()

    st = state.get("session_tokens") or {}
    tokens_total = (st.get("input", 0) or 0) + (st.get("output", 0) or 0)
    cost = state.get("session_cost_usd", 0.0)

    fields: dict[str, Any] = {
        "model": get("model") or "?",
        "cwd": _shorten_cwd(cwd),
        "cwd_full": cwd,
        "git_branch": _get_git_branch(cwd),
        "tokens": tokens_total,
        "session_id": (state.get("session_id") or "")[:8],
        "cost": f"{cost:.4f}",
        "agent": state.get("current_agent") or "",
    }
    try:
        return template.format_map(_SafeDict(fields))
    except Exception:
        return template
