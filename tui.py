"""Octopus Agent TUI：Rich 渲染 + 原生终端交互，透明背景。"""

import os
import shutil
import threading
from typing import Callable

from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from agent import (
    EVT_ERROR, EVT_PROGRESS, EVT_RESPONSE,
    EVT_THINKING, EVT_TOOL_CALL, EVT_TOOL_RESULT,
    run_agent,
)
from cli import _confirm_action, _handle_slash_command
from config import get
from mcp import MCPManager
from tools import get_cwd

VERSION = "1.0.0"

console = Console()


def _welcome():
    """绘制欢迎面板。"""
    model = get("model")
    cwd = get_cwd()
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        cwd = "~" + cwd[len(home):]

    term_width = shutil.get_terminal_size().columns

    left = Text()
    left.append("  ▗ ▗   ▖ ▖\n", style="cyan")
    left.append("    ▘▘ ▝▝\n\n", style="cyan")
    left.append(f"  {model}\n", style="dim")
    left.append(f"  {cwd}", style="dim")

    tips_lines = [
        "[bold]/help[/] all commands",
        "[bold]/agents[/] switch persona",
        "[bold]/skills[/] run templates",
        "[bold]/quit[/] exit",
    ]
    right = Text.from_markup(
        "[bold]Tips[/]\n" + "\n".join(tips_lines)
    )

    columns = Columns([left, right], padding=(0, 4), expand=True)

    console.print()
    console.print(Panel(
        Align.center(columns),
        title=f"[bold]Octopus Agent[/] v{VERSION}",
        border_style="dim",
        width=min(term_width - 4, 80),
        padding=(0, 2),
    ))
    console.print()


def _separator():
    """绘制输入分隔线。"""
    console.print(Rule(style="dim"))


def _status_line():
    """绘制状态提示。"""
    model = get("model")
    console.print(Text(f"  {model}  ·  /help for help", style="dim"))


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

    _separator()

    while True:
        # 状态行 + 提示符
        agent_label = state.get("current_agent")
        prefix = f" ({agent_label})" if agent_label else ""
        try:
            _status_line()
            task = console.input(f"[bold green]❯{prefix}[/] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye![/]")
            break

        task = task.strip()
        console.print()
        if not task:
            continue
        if task.lower() in ("quit", "exit", "q"):
            console.print("[dim]Bye![/]")
            break

        # slash 命令
        if task.startswith("/"):
            result = _handle_slash_command(task, messages, state)
            if result == "__QUIT__":
                console.print("[dim]Bye![/]")
                break
            if result is not None:
                if result.startswith("__SKILL__"):
                    task = result[len("__SKILL__"):]
                else:
                    # slash 命令输出含 ANSI 颜色码，直接 print 保留格式
                    print(result)
                    _separator()
                    continue

        # 运行 agent
        _run_and_display(task, messages, state, mcp)
        _separator()

    mcp.close_all()


def _run_and_display(task: str, messages: list[dict], state: dict, mcp: MCPManager):
    """运行 agent 并实时展示输出。"""
    # 显示用户输入（回显）
    console.print(Text(f"❯ {task}", style="bold"))

    def output_fn(event_type: str, text: str, meta: dict | None = None):
        meta = meta or {}
        if event_type == EVT_THINKING:
            console.print(Panel(
                Text(text, style="yellow"),
                title="💭 thinking",
                border_style="dim",
                padding=(0, 1),
            ))

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
            console.print(Markdown(text))

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
