"""Octopus Agent TUI：Rich 渲染 + 原生终端交互，透明背景。"""

import os
import shutil
import sys

from rich.columns import Columns
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

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

VERSION = "1.0.0"

# ANSI 颜色常量（原生 print 用）
_R = "\033[0m"
_B = "\033[1m"
_DIM = "\033[2m"
_G = "\033[92m"
_C = "\033[96m"
_Y = "\033[93m"
_RE = "\033[91m"

console = Console()


class _SlashCompleter(Completer):
    """Tab 自动完成 slash 命令 + 参数，匹配字符高亮。"""

    COMMANDS = {
        "help": "Show help",
        "clear": "Clear conversation history",
        "save": "Save current session",
        "sessions": "List saved sessions",
        "load": "Load a session",
        "search": "Search conversation",
        "model": "View/switch model",
        "models": "List configured models",
        "agents": "List available agents",
        "agent": "View/switch agent",
        "skills": "List available skills",
        "skill": "Run a skill",
        "config": "View/change config",
        "plan": "Plan mode (read-only)",
        "auto": "Auto mode (full access)",
        "continue": "Resume interrupted task",
        "remember": "Save long-term memory",
        "forget": "Clear all memories",
        "compact": "Compress conversation context",
        "cwd": "Show working directory",
        "quit": "Exit",
        "exit": "Exit",
        "q": "Exit",
    }

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

        if text.startswith("/load "):
            from session import list_sessions
            prefix = text[len("/load "):]
            for s in list_sessions()[:20]:
                sid = s["id"]
                if sid.lower().startswith(prefix.lower()):
                    meta = f"{s['saved_at'][:19]} ({s['messages']} msgs)"
                    yield Completion(
                        sid,
                        start_position=-len(prefix),
                        display=self._highlight_match(sid, prefix),
                        display_meta=meta,
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
    left.append("    .-.\n", style="cyan")
    left.append("   (o o)\n", style="cyan")
    left.append("\n")
    left.append(f"    {model}\n", style="dim")
    left.append(f"    {cwd}", style="dim")

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


def interactive_mode():
    """Rich TUI 交互模式。"""
    mcp = MCPManager()
    messages: list[dict] = []
    state: dict = {
        "current_agent": None,
        "system_prompt_override": None,
        "plan_mode": False,
        "auto_approved_tools": set(),
    }

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
        interrupted = _run_and_display(task, messages, state, mcp)
        save_session(messages)
        if interrupted:
            state["last_task"] = task
            print(f"{_DIM}  Task paused. /continue to resume{_R}")
        else:
            state.pop("last_task", None)

    mcp.close_all()


def _run_and_display(task: str, messages: list[dict], state: dict, mcp: MCPManager):
    """运行 agent 并实时展示输出。"""
    import re
    console.print(f"[bold]> {task}[/]")

    _task_re = re.compile(r'^(\s*)- \[([ xX])\] (.*)$')

    def _render_with_tasks(text: str):
        """渲染文本，任务列表项用彩色指示器，其余用 Markdown。"""
        lines = text.split('\n')
        in_code = False
        buf: list[str] = []

        def flush_buf():
            if buf:
                console.print(Markdown('\n'.join(buf)))
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
            m = _task_re.match(line)
            if m:
                flush_buf()
                indent, checked, content = m.group(1), m.group(2).lower() == 'x', m.group(3)
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
        console.print(f"  [edit_file] {path}")
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        diff = difflib.unified_diff(old_lines, new_lines, lineterm="")
        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("@@"):
                console.print(Text(f"  {line}", style="dim"))
            elif line.startswith("+"):
                console.print(Text(f"  {line}", style="#b8f0b8 on #1a4020"))
            elif line.startswith("-"):
                console.print(Text(f"  {line}", style="#f0b8b8 on #401a1a"))

    _stream_buf: list[str] = []
    _stream_lines = 0

    def output_fn(event_type: str, text: str, meta: dict | None = None):
        nonlocal _stream_buf, _stream_lines
        meta = meta or {}

        if event_type == EVT_STREAM:
            # 实时逐字渲染 + 累积用于后续 Markdown 重渲染
            sys.stdout.write(text)
            sys.stdout.flush()
            _stream_buf.append(text)
            _stream_lines += text.count("\n")

        elif event_type == EVT_THINKING:
            _flush_stream()
            if text:
                console.print(Panel(
                    Text(text[:500] + ("..." if len(text) > 500 else ""), style="dim"),
                    title="thinking",
                    border_style="dim",
                    padding=(0, 1),
                ))
            else:
                sys.stdout.write("\n")
                sys.stdout.flush()

        elif event_type == EVT_TOOL_CALL:
            _flush_stream()
            tool = meta.get("tool", "")
            tool_input = meta.get("input", {})
            if tool == "edit_file" and tool_input:
                _show_edit_diff(tool_input)
            else:
                console.print(f"  [{tool}] {text}")

        elif event_type == EVT_TOOL_RESULT:
            if meta.get("rejected"):
                console.print("  [Rejected]")
            else:
                console.print(f"  → {text}")

        elif event_type == EVT_RESPONSE:
            _flush_stream()
            if meta and meta.get("usage"):
                u = meta["usage"]
                total = u["input_tokens"] + u["output_tokens"]
                console.print(f"[dim]tokens: ↑{u['output_tokens']} · {total} total[/]")

        elif event_type == EVT_ERROR:
            _flush_stream()
            console.print(f"[red]⚠️ {text}[/]")

    def _flush_stream():
        """清空流缓冲区并用 Markdown 重渲染。"""
        nonlocal _stream_buf, _stream_lines
        if not _stream_buf:
            return
        full = "".join(_stream_buf)
        _stream_buf.clear()
        # 确保光标在内容行之后
        if not full.endswith("\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            _stream_lines += 1
        # 回退覆盖原始文本，渲染 Markdown
        sys.stdout.write(f"\033[{_stream_lines}A\033[J")
        _stream_lines = 0
        sys.stdout.flush()
        _render_with_tasks(full.strip())

    # 构建 system prompt（Plan 模式追加约束）
    sys_prompt = state.get("system_prompt_override")
    if state.get("plan_mode"):
        plan_hint = ("\n\n## 当前模式：Plan（只读）\n"
                     "你处于 Plan 模式，只能分析和搜索，不能修改文件或执行命令。"
                     "请只使用 read_file、list_files、grep_search、web_search、web_fetch。")
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
            output_fn=output_fn,
            verbose=False,
        )
        return False
    except KeyboardInterrupt:
        console.print("[yellow]⚠️ Task cancelled[/]")
        return True
