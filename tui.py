"""Octopus Agent TUI：Rich 渲染 + 原生终端交互，透明背景。"""

import os
import shutil

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
from config import get
from mcp import MCPManager
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
        "model": "View/switch model",
        "agents": "List available agents",
        "agent": "View/switch agent",
        "skills": "List available skills",
        "skill": "Run a skill",
        "config": "View/change config",
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
            prefix = text[len("/model "):]
            models = [
                "claude-sonnet-4-20250514",
                "claude-opus-4-20250514",
                "claude-haiku-4-5-20251001",
            ]
            env_model = os.environ.get("OCTOPUS_MODEL", "")
            if env_model and env_model not in models:
                models.insert(0, env_model)
            for m in models:
                if m.lower().startswith(prefix.lower()) or prefix.lower() in m.lower():
                    yield Completion(
                        m,
                        start_position=-len(prefix),
                        display=self._highlight_match(m, prefix),
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
    })


def _read_task(model: str, prefix: str, completer: _SlashCompleter | None = None) -> str:
    """读取用户输入，优先 prompt_toolkit，回退到原生 input。"""
    if _HAS_PT:
        from prompt_toolkit import prompt as _pt_prompt
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.history import FileHistory
        from pathlib import Path

        history_dir = Path.home() / ".octopus"
        history_dir.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(history_dir / "history.txt"))

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

        @kb.add("escape", "enter")
        def _(event):
            event.current_buffer.insert_text("\n")

        @kb.add("escape", "c-m")
        def _(event):
            event.current_buffer.insert_text("\n")

        message = [
            ("dim", f" {model}"),
            ("", "\n"),
            ("bold ansibrightgreen", f"❯{prefix} "),
        ]

        def _toolbar():
            return [
                ("dim", f" {model}  "),
                ("", "|  "),
                ("dim", "Esc+Enter newline  "),
                ("", "|  "),
                ("dim", "Tab complete  "),
                ("", "|  "),
                ("dim", "↑↓ history"),
            ]

        return _pt_prompt(
            message,
            completer=completer,
            style=_PT_STYLE,
            complete_while_typing=True,
            key_bindings=kb,
            history=history,
            bottom_toolbar=_toolbar,
        )
    else:
        prompt_text = f" {_DIM}{model}{_R}\n{_G}{_B}❯{prefix}{_R} "
        return input(prompt_text)


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
    state: dict = {"current_agent": None, "system_prompt_override": None}

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

    # 原生分隔线
    print(_DIM + "─" * shutil.get_terminal_size().columns + _R)

    slash_completer = _SlashCompleter() if _HAS_PT else None

    while True:
        agent_label = state.get("current_agent")
        model = get("model")
        prefix = f" ({agent_label})" if agent_label else ""
        try:
            task = _read_task(
                model=model,
                prefix=prefix,
                completer=slash_completer,
            )
        except (EOFError, KeyboardInterrupt):
            print(f"\n{_DIM}Bye!{_R}")
            break

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
                else:
                    print(result)
                    print(f"{_DIM}─{_R}")
                    continue

        # 运行 agent
        _run_and_display(task, messages, state, mcp)
        print(f"{_DIM}─{_R}")

    mcp.close_all()


def _run_and_display(task: str, messages: list[dict], state: dict, mcp: MCPManager):
    """运行 agent 并实时展示输出。"""
    console.print(Text(f"> {task}", style="bold"))

    def output_fn(event_type: str, text: str, meta: dict | None = None):
        meta = meta or {}
        if event_type == EVT_STREAM:
            import sys
            sys.stdout.write(text)
            sys.stdout.flush()

        elif event_type == EVT_THINKING:
            import sys
            sys.stdout.write("\n")
            sys.stdout.flush()
            if text:
                console.print(Panel(
                    Text(text, style="yellow"),
                    title="thinking",
                    border_style="dim",
                    padding=(0, 1),
                ))
            else:
                console.print(Text("  ...", style="dim"))

        elif event_type == EVT_TOOL_CALL:
            tool = meta.get("tool", "")
            console.print(Text(f"  🔧 {tool} ", style="green"), end="")
            console.print(Text(text, style="dim"))

        elif event_type == EVT_TOOL_RESULT:
            if meta.get("rejected"):
                console.print(Text("  ✗ Rejected", style="red"))
            else:
                console.print(Text(f"  → {text}", style="dim"))

        elif event_type == EVT_RESPONSE:
            if text:
                console.print(Markdown(text))
            else:
                import sys
                sys.stdout.write("\n")
                sys.stdout.flush()

        elif event_type == EVT_ERROR:
            console.print(Text(f"⚠️ {text}", style="red"))

    try:
        run_agent(
            task,
            messages=messages,
            confirm_fn=_confirm_action,
            mcp=mcp,
            system_prompt_override=state.get("system_prompt_override"),
            output_fn=output_fn,
            verbose=False,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ Task cancelled[/]")
