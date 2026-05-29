"""Octopus Agent TUI：Rich 渲染 + 原生终端交互，透明背景。"""

import os
import shutil
import sys

from rich.columns import Columns
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from agent import (
    EVT_ERROR, EVT_PROGRESS, EVT_RESPONSE, EVT_STREAM,
    EVT_THINKING, EVT_TOOL_CALL, EVT_TOOL_RESULT,
    run_agent,
)
from cli import _confirm_action, _handle_slash_command
from config import get, is_trusted_dir, trust_dir
from mcp import MCPManager
from session import save_session
from tools import get_cwd

# prompt_toolkit 自动完成（可选依赖）
try:
    from prompt_toolkit import prompt as _pt_prompt
    from prompt_toolkit.completion import Completer, Completion, PathCompleter
    from prompt_toolkit.styles import Style as _Style
    _HAS_PT = True
except ImportError:
    _HAS_PT = False
    Completer = object  # type: ignore

from constants import VERSION

# ANSI 颜色常量（原生 print 用）
from constants import RESET as _R, BOLD as _B, DIM as _DIM
from constants import GREEN as _G, CYAN as _C, YELLOW as _Y, RED as _RE

console = Console(theme=Theme({
    "markdown.code": "cyan",
    "markdown.h1": "bold cyan",
    "markdown.h2": "bold cyan",
    "markdown.h3": "bold",
    "markdown.item.bullet": "yellow",
    "markdown.item.number": "bold yellow",
}))


class _SlashCompleter(Completer):
    """Tab 自动完成 slash 命令 + 参数，匹配字符高亮。"""

    @property
    def COMMANDS(self) -> dict[str, str]:
        from commands import get_command_names, get_command_desc
        return {name.lstrip("/"): get_command_desc(name) for name in get_command_names()}

    @staticmethod
    def _highlight_match(text: str, prefix: str) -> list[tuple[str, str]]:
        """返回带高亮的 FormattedText：匹配部分用蓝色，其余正常。"""
        if not prefix:
            return [("", text)]
        lower_text = text.lower()
        lower_prefix = prefix.lower()
        idx = lower_text.find(lower_prefix)
        if idx == -1:
            return [("", text)]
        result = []
        if idx > 0:
            result.append(("", text[:idx]))
        result.append(("class:match", text[idx:idx + len(prefix)]))
        if idx + len(prefix) < len(text):
            result.append(("", text[idx + len(prefix):]))
        return result

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        if text.startswith("/agent "):
            from skills import load_agents
            prefix = text[len("/agent "):]
            for name in sorted(load_agents()):
                if name.lower().startswith(prefix.lower()):
                    yield Completion(
                        name,
                        start_position=-len(prefix),
                        display=self._highlight_match(name, prefix),
                    )
            return

        if text.startswith("/skill "):
            from skills import load_skills
            prefix = text[len("/skill "):]
            for name in sorted(load_skills()):
                if name.lower().startswith(prefix.lower()):
                    yield Completion(
                        name,
                        start_position=-len(prefix),
                        display=self._highlight_match(name, prefix),
                    )
            return

        if text.startswith("/model "):
            from config import get_models
            prefix = text[len("/model "):]
            configured = get_models()
            seen = set()
            for alias, model_name in sorted(configured.items()):
                # 别名前缀匹配
                if alias.lower().startswith(prefix.lower()):
                    seen.add(model_name)
                    yield Completion(
                        alias,
                        start_position=-len(prefix),
                        display=self._highlight_match(alias, prefix),
                        display_meta=model_name,
                    )
                # 完整模型名前缀匹配（不重复）
                if model_name.lower().startswith(prefix.lower()) and model_name not in seen:
                    yield Completion(
                        model_name,
                        start_position=-len(prefix),
                        display=self._highlight_match(model_name, prefix),
                        display_meta=alias,
                    )
            return

        if text.startswith("/"):
            prefix = text[1:].lower()
            # / 单独出现时显示全部命令
            if not prefix:
                for name, desc in self.COMMANDS.items():
                    yield Completion(
                        f"/{name}",
                        start_position=-len(text),
                        display=[("", f"/{name}")],
                        display_meta=desc,
                    )
            else:
                for name, desc in self.COMMANDS.items():
                    if name.startswith(prefix):
                        display_name = f"/{name}"
                        yield Completion(
                            f"/{name}",
                            start_position=-len(text),
                            display=self._highlight_match(display_name, f"/{prefix}"),
                            display_meta=desc,
                        )
            return

        # 路径补全：非 slash 输入时补全文件系统路径
        if _HAS_PT:
            from prompt_toolkit.completion import PathCompleter as _PC
            path_comp = _PC(expanduser=True)
            yield from path_comp.get_completions(document, complete_event)


if _HAS_PT:
    _PT_STYLE = _Style.from_dict({
        "completion-menu": "",
        "completion-menu.completion": "",
        "completion-menu.completion.current": "bg:#3366cc #ffffff",
        "completion-menu.meta": "#888888",
        "completion-menu.meta.current": "bg:#3366cc #cccccc",
        "match": "#3388ff",
        "scrollbar": "bg:#3a3a4a",
        "scrollbar.button": "bg:#4a4a5a",
        "bottom-toolbar": "",
        "bottom-toolbar.text": "",
    })


def _read_task(
    model: str, prefix: str, completer: _SlashCompleter | None = None,
    state: dict | None = None,
) -> tuple[str, bool]:
    """读取用户输入，优先 prompt_toolkit，回退到原生 input。

    Returns:
        (text: str, was_cancelled_with_content: bool)
        was_cancelled_with_content 为 True 表示用户在有内容时按 Ctrl+C 清空输入。
    """
    if _HAS_PT:
        from prompt_toolkit import prompt as _pt_prompt
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.history import FileHistory
        from pathlib import Path

        history_dir = Path.home() / ".octopus"
        history_dir.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(history_dir / "history.txt"))

        cancelled = [False]
        kb = KeyBindings()

        @kb.add("backspace")
        def _(event):
            buf = event.current_buffer
            buf.delete_before_cursor()
            if buf.text.startswith("/"):
                buf.start_completion(select_first=False)

        @kb.add("c-h")
        def _(event):
            buf = event.current_buffer
            buf.delete_before_cursor()
            if buf.text.startswith("/"):
                buf.start_completion(select_first=False)

        @kb.add("c-c")
        def _(event):
            buf = event.current_buffer
            if buf.text:
                cancelled[0] = True
                buf.reset()
                event.app.exit()
            else:
                buf.reset()
                raise KeyboardInterrupt()

        @kb.add("escape", "enter")
        def _(event):
            event.current_buffer.insert_text("\n")

        @kb.add("escape", "c-m")
        def _(event):
            event.current_buffer.insert_text("\n")

        @kb.add("c-l")
        def _(event):
            import os
            os.system("clear")

        @kb.add("s-tab")
        def _(event):
            if state is not None:
                state["plan_mode"] = not state.get("plan_mode", False)
                state["auto_approved_tools"] = set()
                event.app.invalidate()

        def _message():
            plan = state and state.get("plan_mode", False)
            if plan:
                return [("bold #bb88ff", "❯ (plan) ")]
            if prefix:
                return [("bold ansibrightgreen", f"❯{prefix} ")]
            return [("bold ansibrightgreen", "❯ ")]

        message = _message

        def _toolbar():
            plan = state and state.get("plan_mode", False)
            mode_text = "PLAN" if plan else "AUTO"
            mode_style = "#bb88ff" if plan else "#88cc88"
            return [
                (mode_style, f" {mode_text} "),
                ("dim", f" {model}  "),
                ("#555555", "|  "),
                ("dim", "Shift+Tab mode  "),
                ("#555555", "|  "),
                ("dim", "Tab complete  "),
                ("#555555", "|  "),
                ("dim", "↑↓ history"),
            ]

        result = _pt_prompt(
            message,
            completer=completer,
            style=_PT_STYLE,
            complete_while_typing=True,
            key_bindings=kb,
            history=history,
            bottom_toolbar=_toolbar,
        )
        return result, cancelled[0]
    else:
        prompt_text = f" {_DIM}{model}{_R}\n{_G}{_B}❯{prefix}{_R} "
        return input(prompt_text), False


def _welcome():
    """绘制欢迎面板。"""
    model = get("model")
    cwd = get_cwd()
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        cwd = "~" + cwd[len(home):]
    if len(cwd) > 40:
        cwd = "..." + cwd[-37:]

    term_width = shutil.get_terminal_size().columns

    left = Text()
    left.append("     _\n", style="cyan")
    left.append("    (o o)\n", style="cyan")
    left.append("   //|||\\\\\n", style="cyan")
    left.append("\n")
    left.append(f"  {model}\n", style="dim")
    left.append(f"  {cwd}", style="dim")

    right = Text()
    right.append("Tips\n", style="bold")
    right.append("/help all commands\n", style="dim")
    right.append("/agents switch personal agent\n", style="dim")
    right.append("/skills run templates\n", style="dim")
    right.append("/quit exit\n", style="dim")

    content = Columns([left, right], equal=True, expand=True)

    console.print()
    console.print(Panel(
        content,
        title=f"[bold]Octopus Agent[/] v{VERSION}",
        border_style="dim",
        width=min(term_width - 4, 80),
        padding=(0, 2),
    ))
    console.print()


def interactive_mode(resume_session_id: str | None = None,
                     session_name: str | None = None):
    """Rich TUI 交互模式。"""
    from session import create_session, load_session, save_session as _save

    mcp = MCPManager()
    messages: list[dict] = []
    state: dict = {
        "current_agent": None,
        "system_prompt_override": None,
        "plan_mode": False,
        "auto_approved_tools": set(),
        "session_tokens": {"input": 0, "output": 0},
    }

    # 恢复或创建会话
    session_id: str | None = None
    if resume_session_id:
        try:
            loaded_messages, saved_cwd, _meta = load_session(resume_session_id)
            messages.extend(loaded_messages)
            session_id = resume_session_id
            if saved_cwd and os.path.isdir(saved_cwd):
                from tools import set_cwd
                set_cwd(saved_cwd)
            console.print(f"[green]已恢复会话: {resume_session_id} ({len(messages)} 条消息)[/]")
        except FileNotFoundError:
            console.print(f"[yellow]会话不存在: {resume_session_id}，创建新会话[/]")

    if not session_id:
        session_id = create_session(name=session_name)

    state["session_id"] = session_id

    # 目录信任检查
    cwd = get_cwd()
    if not is_trusted_dir(cwd):
        console.print(Panel(
            f"[bold]Do you trust this directory?[/]\n\n{cwd}\n\n"
            "[dim]Trusted directories allow file edits and command execution.[/]",
            border_style="yellow",
        ))
        try:
            choice = input("  [y] Trust  [n] Don't trust: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "n"
        if choice in ("y", "yes"):
            trust_dir(cwd)
        else:
            state["plan_mode"] = True
            console.print("[dim]Starting in Plan mode (read-only).[/]")

    _welcome()

    # 连接 MCP
    mcp_configs = get("mcp_servers", {})
    if mcp_configs:
        console.print("[dim]Connecting MCP servers...[/]")
        count = mcp.connect_all(mcp_configs)
        if count:
            console.print(f"[green]✓ Connected {count} MCP server(s)[/]")
        else:
            console.print("[yellow]No MCP servers connected[/]")

    slash_completer = _SlashCompleter() if _HAS_PT else None

    int_count = 0

    while True:
        # 输入前分隔线
        print(_DIM + "─" * shutil.get_terminal_size().columns + _R)
        agent_label = state.get("current_agent")
        model = get("model")
        prefix = f" ({agent_label})" if agent_label else ""
        try:
            task, was_cancelled = _read_task(
                model=model,
                prefix=prefix,
                completer=slash_completer,
                state=state,
            )
        except EOFError:
            print(f"\n{_DIM}Bye!{_R}")
            break
        except KeyboardInterrupt:
            int_count += 1
            if int_count >= 2:
                print(f"\n{_DIM}Bye!{_R}")
                break
            print(f"\n{_Y}Press Ctrl+C again to exit{_R}")
            print()
            continue

        if was_cancelled:
            int_count = 0
            continue

        int_count = 0

        task = task.strip()
        print()
        if not task:
            continue

        # slash 命令
        if task.startswith("/"):
            result = _handle_slash_command(task, messages, state)
            if result == "__QUIT__":
                print(f"{_DIM}Bye!{_R}")
                break
            if result is not None:
                if result.startswith("__SKILL__"):
                    task = result[len("__SKILL__"):]
                elif result.startswith("__CONTINUE__"):
                    task = result[len("__CONTINUE__"):]
                else:
                    print(result)
                    continue

        # 运行 agent
        try:
            interrupted = _run_and_display(task, messages, state, mcp)
            _save(messages, session_id=session_id)
        except Exception as exc:
            console.print(f"[red]Unexpected error: {exc}[/]")
            console.print("[dim]Type your next message to continue, or /quit to exit.[/]")
            continue
        if interrupted:
            state["last_task"] = task
            print(f"{_DIM}  Task paused. /continue to resume{_R}")
        else:
            state.pop("last_task", None)

    mcp.close_all()


# ─────────────────────────────────────────────
# 交互式会话选择器
# ─────────────────────────────────────────────

def session_selector() -> str | None:
    """交互式会话选择器，返回 session_id 或 None（取消）。

    使用 prompt_toolkit 实现上下选择、搜索过滤、摘要预览。
    回退到简单编号列表 + 输入。
    """
    from session import list_sessions, _time_ago
    sessions = list_sessions()
    if not sessions:
        console.print("[yellow]没有已保存的会话[/]")
        return None

    if not _HAS_PT:
        return _session_selector_fallback(sessions)

    return _session_selector_pt(sessions)


def _session_selector_fallback(sessions: list[dict]) -> str | None:
    """简单编号列表选择（无 prompt_toolkit 时使用）。"""
    from session import _time_ago
    console.print(f"\n{_C}选择会话:{_R}")
    for i, s in enumerate(sessions[:20]):
        preview = s.get("first_message", "") or s.get("name", s["session_id"][:8])
        label = s["name"] if s.get("name") else preview[:60]
        branch = f" [{s['git_branch']}]" if s.get("git_branch") else ""
        ago = _time_ago(s.get("updated_at", ""))
        msgs = s.get("message_count", 0)
        tokens = s.get("total_tokens", 0)
        token_info = f"  {tokens // 1000}k tok" if tokens else ""
        console.print(
            f"  {_DIM}{i + 1:>3}.{_R}  {label}{branch}  "
            f"({_DIM}{ago}{_R}, {msgs} msgs{token_info})"
        )
    try:
        choice = input(f"\n  选择 (1-{len(sessions[:20])}): ").strip()
        idx = int(choice) - 1
        if 0 <= idx < len(sessions[:20]):
            return sessions[idx]["session_id"]
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    return None


def _session_selector_pt(sessions: list[dict]) -> str | None:
    """prompt_toolkit 交互式会话选择器。"""
    from prompt_toolkit import prompt as _pt_prompt
    from prompt_toolkit.key_binding import KeyBindings
    from session import _time_ago

    PAGE_SIZE = 10
    if not sessions:
        return None

    # 选择状态
    sel = {"offset": 0, "idx": 0, "filter": "", "result": None}

    def _visible():
        q = sel["filter"].lower()
        if not q:
            return sessions[:50]
        return [s for s in sessions[:50]
                if q in s.get("name", "").lower()
                or q in s.get("first_message", "").lower()
                or q in s.get("session_id", "").lower()
                or q in s.get("git_branch", "").lower()]

    def _render():
        visible = _visible()
        if not visible:
            return
        max_idx = len(visible) - 1
        if sel["idx"] > max_idx:
            sel["idx"] = max_idx
        sel["offset"] = max(0, min(sel["offset"], max_idx - PAGE_SIZE + 1))

        lines_count = min(PAGE_SIZE, len(visible)) + 4
        sys.stdout.write(f"\033[{lines_count}A\033[J")
        sys.stdout.flush()

        filter_hint = f"  搜索: {sel['filter']}" if sel["filter"] else ""
        print(f"{_C}  选择会话 (↑↓ 选择 · Enter 确认 · 输入搜索 · Esc 取消){_R}{filter_hint}")
        print(f"  {_DIM}{'─' * 60}{_R}")

        start = sel["offset"]
        end = min(start + PAGE_SIZE, len(visible))
        for i in range(start, end):
            s = visible[i]
            is_cur = i == sel["idx"]
            preview = s.get("first_message", "") or s.get("name", s["session_id"][:8])
            label = s["name"] if s.get("name") else preview[:50]
            branch = f" [{s['git_branch']}]" if s.get("git_branch") else ""
            ago = _time_ago(s.get("updated_at", ""))
            msgs = s.get("message_count", 0)

            if is_cur:
                print(f"  {_G}▶ {label}{_R}{_DIM}{branch}  ({ago}, {msgs} msgs){_R}")
            else:
                print(f"    {_DIM}{label}{_R}{_DIM}{branch}  ({ago}, {msgs} msgs){_R}")

        # 底部摘要
        if 0 <= sel["idx"] < len(visible):
            s = visible[sel["idx"]]
            print(f"  {_DIM}{'─' * 60}{_R}")
            summary = s.get("first_message", "")[:100] or "(无摘要)"
            print(f"  {_DIM}ID: {s['session_id'][:16]}  摘要: {summary}{_R}")

    # 预留空间，初始渲染
    print("\n" * (PAGE_SIZE + 5))
    _render()

    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        if sel["idx"] > 0:
            sel["idx"] -= 1
            if sel["idx"] < sel["offset"]:
                sel["offset"] = sel["idx"]
        _render()

    @kb.add("down")
    def _(event):
        visible = _visible()
        if sel["idx"] < len(visible) - 1:
            sel["idx"] += 1
            if sel["idx"] >= sel["offset"] + PAGE_SIZE:
                sel["offset"] = sel["idx"] - PAGE_SIZE + 1
        _render()

    @kb.add("enter")
    def _(event):
        visible = _visible()
        if visible and 0 <= sel["idx"] < len(visible):
            sel["result"] = visible[sel["idx"]]["session_id"]
        event.app.exit()

    @kb.add("escape")
    def _(event):
        sel["result"] = None
        event.app.exit()

    @kb.add("c-c")
    def _(event):
        sel["result"] = None
        event.app.exit()

    @kb.add("backspace")
    def _(event):
        if sel["filter"]:
            sel["filter"] = sel["filter"][:-1]
            sel["idx"] = 0
            sel["offset"] = 0
            _render()

    # 注册所有可打印 ASCII 字符
    for code in range(32, 127):
        c = chr(code)
        if c not in ("\r", "\n"):
            @kb.add(c)
            def _handler(event, ch=c):
                sel["filter"] += ch
                sel["idx"] = 0
                sel["offset"] = 0
                _render()

    try:
        _pt_prompt(message="", key_bindings=kb)
    except (EOFError, KeyboardInterrupt):
        return None

    return sel["result"]


# ─────────────────────────────────────────────
# 渲染辅助函数
# ─────────────────────────────────────────────

import re as _re

_TASK_RE = _re.compile(r'^(\s*)- \[([ xX])\] (.*)$')


def _render_with_tasks(text: str):
    """渲染文本，任务列表项用彩色指示器，其余用 Markdown。"""
    lines = text.split('\n')
    in_code = False
    buf: list[str] = []

    def flush_buf():
        if buf:
            console.print(Markdown('\n'.join(buf), code_theme="default"))
            buf.clear()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            buf.append(line)
            continue
        if in_code:
            buf.append(line)
            continue
        m = _TASK_RE.match(line)
        if m:
            flush_buf()
            indent = m.group(1)
            checked = m.group(2).lower() == 'x'
            content = m.group(3)
            if checked:
                console.print(Text(f"{indent}  ✔ {content}", style="green"))
            else:
                console.print(Text(f"{indent}  ◻ {content}", style="dim"))
        else:
            buf.append(line)
    flush_buf()


def _show_edit_diff(tool_input: dict):
    """渲染 edit_file 的 diff 视图。"""
    import difflib
    path = tool_input.get("path", "")
    old = tool_input.get("old_string", "")
    new = tool_input.get("new_string", "")
    _p = Text("  edit_file  ", style="bold cyan")
    _p.append(path, style="bold")
    console.print(_p)
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = difflib.unified_diff(old_lines, new_lines, lineterm="")
    for line in diff:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("@@"):
            console.print(Text(f"  {line}", style="dim"))
        elif line.startswith("+"):
            console.print(Text(f"  {line}", style="green"))
        elif line.startswith("-"):
            console.print(Text(f"  {line}", style="red"))


class StreamRenderer:
    """封装流式渲染状态：累积文本、回退光标、Markdown 重渲染。"""

    def __init__(self):
        self._buf: list[str] = []
        self._lines: int = 0

    def flush(self):
        if not self._buf:
            return
        full = "".join(self._buf)
        self._buf.clear()
        if not full.endswith("\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._lines += 1
        sys.stdout.write(f"\033[{self._lines}A\033[J")
        self._lines = 0
        sys.stdout.flush()
        _render_with_tasks(full.strip())

    def make_output_fn(self, state: dict | None = None):
        """返回适配 agent 的 output_fn 回调。"""
        buf = self._buf
        lines_ref = self  # 闭包引用 self

        def output_fn(event_type: str, text: str, meta: dict | None = None):
            meta = meta or {}

            if event_type == EVT_STREAM:
                sys.stdout.write(text)
                sys.stdout.flush()
                buf.append(text)
                lines_ref._lines += text.count("\n")

            elif event_type == EVT_THINKING:
                lines_ref.flush()
                if text:
                    # thinking 是模型内部推理，通常为英文，仅以折叠摘要展示
                    preview = text[:200].replace("\n", " ")
                    if len(text) > 200:
                        preview += "..."
                    console.print(Text(f"  💭 {preview}", style="dim italic"))
                else:
                    sys.stdout.write("\n")
                    sys.stdout.flush()

            elif event_type == EVT_TOOL_CALL:
                lines_ref.flush()
                tool = meta.get("tool", "")
                tool_input = meta.get("input", {})
                if tool == "edit_file" and tool_input:
                    _show_edit_diff(tool_input)
                else:
                    _t = Text()
                    _t.append("  ")
                    _t.append(tool, style="bold cyan")
                    _t.append(f"  {text}")
                    console.print(_t)

            elif event_type == EVT_TOOL_RESULT:
                if meta.get("rejected"):
                    console.print(Text("  ✗ Rejected", style="red"))
                else:
                    console.print(Text(f"  → {text}", style="dim"))

            elif event_type == EVT_RESPONSE:
                lines_ref.flush()
                if meta and meta.get("usage"):
                    u = meta["usage"]
                    total = u["input_tokens"] + u["output_tokens"]
                    # 累计 session token
                    if state:
                        st = state.get("session_tokens", {"input": 0, "output": 0})
                        st["input"] += u["input_tokens"]
                        st["output"] += u["output_tokens"]
                        state["session_tokens"] = st
                        session_total = st["input"] + st["output"]
                        console.print(
                            f"[dim]tokens: ↑{u['output_tokens']} ↓{u['input_tokens']}"
                            f"  ·  {total} turn  ·  {session_total} session[/]"
                        )
                    else:
                        console.print(f"[dim]tokens: ↑{u['output_tokens']} ↓{u['input_tokens']}  ·  {total} total[/]")

            elif event_type == EVT_ERROR:
                lines_ref.flush()
                console.print(f"[red]⚠️ {text}[/]")

        return output_fn


def _run_and_display(task: str, messages: list[dict], state: dict, mcp: MCPManager):
    """运行 agent 并实时展示输出。"""
    console.print(f"[bold]> {task}[/]")

    renderer = StreamRenderer()

    # 构建 system prompt（Plan 模式追加约束）
    sys_prompt = state.get("system_prompt_override")
    if state.get("plan_mode"):
        plan_hint = ("\n\n## 当前模式：Plan（只读）\n"
                     "你处于 Plan 模式，只能分析和搜索，不能修改文件或执行命令。"
                     "请只使用 read_file、list_files、grep_search、web_search、web_fetch。\n"
                     "分析完成后，请输出结构化的实施计划：\n"
                     "1. 用 numbered list 列出每个步骤\n"
                     "2. 每个步骤说明要修改的文件和具体操作\n"
                     "3. 标注步骤之间的依赖关系\n"
                     "4. 用户确认后切换到 Auto 模式（/auto）执行")
        if sys_prompt:
            sys_prompt += plan_hint
        else:
            from context import build_system_prompt
            sys_prompt = build_system_prompt() + plan_hint

    def _confirm(tool_name: str, tool_input: dict) -> bool:
        if state.get("plan_mode"):
            write_tools = {"bash", "write_file", "edit_file"}
            if tool_name in write_tools:
                console.print(f"[yellow]  Plan 模式下不允许执行 {tool_name}[/]")
                return False
        return _confirm_action(tool_name, tool_input, state)

    try:
        run_agent(
            task,
            messages=messages,
            confirm_fn=_confirm,
            mcp=mcp,
            system_prompt_override=sys_prompt,
            output_fn=renderer.make_output_fn(state=state),
            verbose=False,
        )
        return False
    except KeyboardInterrupt:
        console.print("[yellow]⚠️ Task cancelled[/]")
        return True
