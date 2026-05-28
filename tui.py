"""Octopus Agent TUI：基于 Textual 框架的终端用户界面。"""

import os
import threading
from typing import Any

from rich.markdown import Markdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Input, Static

from agent import (
    EVT_ERROR, EVT_PROGRESS, EVT_RESPONSE,
    EVT_THINKING, EVT_TOOL_CALL, EVT_TOOL_RESULT,
    run_agent,
)
from cli import _confirm_action, _handle_slash_command
from config import get
from mcp import MCPManager
from skills import load_agents
from tools import get_cwd

# ─────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────

VERSION = "1.0.0"
ASCII_LOGO = """
 [cyan]  ▗ ▗   ▖ ▖[/]
 [cyan]    ▘▘ ▝▝[/]
"""

TIPS = """[dim]Tips for getting started[/]
Run [bold]/help[/] to see all commands
Run [bold]/agents[/] to switch agent persona
Run [bold]/skills[/] to execute skill templates"""

OCTOPUS_CSS = """
Screen {
    layout: vertical;
}

#welcome {
    height: auto;
    max-height: 15;
    padding: 1 2;
    border: round $primary;
    margin: 1 1 0 1;
}

#welcome.hidden {
    display: none;
}

#output {
    height: 1fr;
    padding: 0 1;
    scrollbar-size: 1 1;
}

#input-bar {
    height: auto;
    padding: 0 1;
    dock: bottom;
}

#input-separator {
    height: 1;
    background: $primary-darken-2;
    margin: 0 0 1 0;
}

#prompt-input {
    margin: 0;
    padding: 0;
}

.status-line {
    color: $text-muted;
    background: $surface;
    height: 1;
    padding: 0 1;
}

.tool-call {
    color: $success;
}

.tool-result {
    color: $text-muted;
}

.thinking {
    color: $warning;
    background: $surface-darken-1;
    padding: 0 1;
}

.response {
    padding: 0;
}

.error {
    color: $error;
}

.block {
    margin: 0 0 1 0;
    padding: 0 1;
}
"""


# ─────────────────────────────────────────────
# 组件
# ─────────────────────────────────────────────

class WelcomePanel(Static):
    """欢迎面板。"""

    def __init__(self, model: str, **kwargs):
        cwd = get_cwd()
        # 截断过长的 cwd
        if len(cwd) > 45:
            cwd = "..." + cwd[-42:]
        content = f"""{ASCII_LOGO}
 [bold]Octopus Agent v{VERSION}[/]          {TIPS}
 [dim]{model} · {cwd}[/]
"""
        super().__init__(content, id="welcome", **kwargs)


class OutputArea(VerticalScroll):
    """输出滚动区域。"""

    def append_text(self, text: str, css_class: str = "block"):
        """追加文本块。"""
        widget = Static(text, classes=css_class)
        self.mount(widget)
        self.scroll_end(animate=False)

    def append_markdown(self, text: str, css_class: str = "block"):
        """追加 Markdown 渲染块。"""
        widget = Static(Markdown(text), classes=css_class)
        self.mount(widget)
        self.scroll_end(animate=False)

    def clear_output(self):
        """清空输出。"""
        for child in list(self.children):
            child.remove()


# ─────────────────────────────────────────────
# 主应用
# ─────────────────────────────────────────────

class OctopusApp(App):
    """Octopus Agent TUI 应用。"""

    CSS = OCTOPUS_CSS
    TITLE = "Octopus Agent"
    BINDINGS = [
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.messages: list[dict] = []
        self.mcp = MCPManager()
        self.state: dict = {
            "current_agent": None,
            "system_prompt_override": None,
        }
        self._agent_thread: threading.Thread | None = None
        self._running = False

    def compose(self) -> ComposeResult:
        model = get("model")
        yield WelcomePanel(model)
        yield OutputArea(id="output")
        with Container(id="input-bar"):
            yield Static("", id="input-separator")
            yield Input(placeholder="Ask Octopus...", id="prompt-input")

    def on_mount(self) -> None:
        # 连接 MCP
        mcp_configs = get("mcp_servers", {})
        if mcp_configs:
            output = self.query_one("#output", OutputArea)
            output.append_text("[dim]Connecting MCP servers...[/]")
            count = self.mcp.connect_all(mcp_configs)
            if count:
                output.append_text(f"[green]✓ Connected {count} MCP server(s)[/]")
            else:
                output.append_text("[yellow]No MCP servers connected[/]")

        # 聚焦输入框
        self.query_one("#prompt-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """用户提交输入。"""
        task = event.value.strip()
        input_widget = self.query_one("#prompt-input", Input)
        input_widget.value = ""

        if not task:
            return

        # 隐藏欢迎面板
        try:
            welcome = self.query_one("#welcome", WelcomePanel)
            welcome.add_class("hidden")
        except Exception:
            pass

        # 处理 quit
        if task.lower() in ("quit", "exit", "q"):
            self.exit()
            return

        # 处理 slash 命令
        if task.startswith("/"):
            result = _handle_slash_command(task, self.messages, self.state)
            if result == "__QUIT__":
                self.exit()
                return
            if result is not None:
                if result.startswith("__SKILL__"):
                    task = result[len("__SKILL__"):]
                else:
                    output = self.query_one("#output", OutputArea)
                    output.append_markdown(result)
                    input_widget.focus()
                    return

        # 执行 agent 任务
        self._run_agent(task)

    def _run_agent(self, task: str):
        """在后台线程运行 agent，通过回调更新 UI。"""
        output = self.query_one("#output", OutputArea)
        input_widget = self.query_one("#prompt-input", Input)

        # 显示用户输入
        output.append_text(f"[bold green]❯[/] {task}")

        # 禁用输入
        input_widget.disabled = True
        self._running = True

        def output_fn(event_type: str, text: str, meta: dict | None = None):
            """线程安全的 UI 更新。"""
            meta = meta or {}
            self.call_from_thread(self._on_agent_event, event_type, text, meta)

        def run():
            try:
                run_agent(
                    task,
                    messages=self.messages,
                    confirm_fn=_confirm_action,
                    mcp=self.mcp,
                    system_prompt_override=self.state.get("system_prompt_override"),
                    output_fn=output_fn,
                    verbose=False,
                )
            finally:
                self._running = False
                self.call_from_thread(self._on_agent_done)

        self._agent_thread = threading.Thread(target=run, daemon=True)
        self._agent_thread.start()

    def _on_agent_event(self, event_type: str, text: str, meta: dict):
        """在主线程处理 agent 输出事件。"""
        output = self.query_one("#output", OutputArea)

        if event_type == EVT_THINKING:
            output.append_text(text, "thinking")

        elif event_type == EVT_TOOL_CALL:
            tool = meta.get("tool", "")
            output.append_text(f"  🔧 [green]{tool}[/] {text}", "tool-call")

        elif event_type == EVT_TOOL_RESULT:
            if meta.get("rejected"):
                output.append_text(f"  ✗ [red]Rejected[/]", "tool-result")
            else:
                output.append_text(f"  → {text}", "tool-result")

        elif event_type == EVT_RESPONSE:
            output.append_markdown(text, "response")

        elif event_type == EVT_ERROR:
            output.append_text(f"⚠️ {text}", "error")

        elif event_type == EVT_PROGRESS:
            # 只更新标题栏，不在输出区显示
            if meta.get("label") != "任务":
                pass  # 可扩展

    def _on_agent_done(self):
        """Agent 任务完成，恢复输入。"""
        try:
            input_widget = self.query_one("#prompt-input", Input)
            input_widget.disabled = False
            input_widget.focus()
        except Exception:
            pass

    def action_cancel(self):
        """Ctrl+C 取消当前任务。"""
        if self._running:
            # agent 线程会自行处理 KeyboardInterrupt
            return
        # 非运行状态，不做任何事（避免误退出）

    def action_quit(self):
        """Ctrl+Q 退出。"""
        self.exit()

    def on_unmount(self) -> None:
        """清理。"""
        self.mcp.close_all()
