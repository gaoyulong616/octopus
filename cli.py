"""交互式 CLI：多轮对话、slash 命令、权限确认、信号处理。"""

import _thread
import json
import os
import signal
import sys

from agent import run_agent
from commands import dispatch_command
from config import (
    check_permission_rule,
    get,
    is_dangerous,
    run_hooks,
)
from mcp import MCPManager
from tools import get_cwd

_interrupt_count = 0

from constants import BOLD as _BOLD
from constants import CYAN as _CYAN
from constants import DIM as _DIM
from constants import GREEN as _GREEN
from constants import RED as _RED
from constants import RESET as _RESET
from constants import UI_CAPABILITIES_CLI
from constants import YELLOW as _YELLOW


def _arrow_select_fallback(items: list[tuple[str, str]]) -> int | None:
    """上下箭头选择菜单（cli.py 回退版）。返回选中索引或 None。"""
    if not items:
        return None
    sel = 0

    def _render():
        sys.stdout.write(f"\033[{len(items)}A\033[J")
        for i, (label, desc) in enumerate(items):
            if i == sel:
                print(f"  {_GREEN}▶{_RESET} {_BOLD}{label}{_RESET}  {_DIM}{desc}{_RESET}")
            else:
                print(f"    {_DIM}{label}  {desc}{_RESET}")

    for i, (label, desc) in enumerate(items):
        if i == sel:
            print(f"  {_GREEN}▶{_RESET} {_BOLD}{label}{_RESET}  {_DIM}{desc}{_RESET}")
        else:
            print(f"    {_DIM}{label}  {desc}{_RESET}")

    import termios
    import tty as _tty

    fd = sys.stdin.fileno()
    old_settings = None
    try:
        old_settings = termios.tcgetattr(fd)
        _tty.setcbreak(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    if ch3 == "A" and sel > 0:
                        sel -= 1
                        _render()
                    elif ch3 == "B" and sel < len(items) - 1:
                        sel += 1
                        _render()
                else:
                    return None
            elif ch in ("\r", "\n"):
                return sel
            elif ch == "\x03" or ch == "q":
                return None
    except Exception:
        return None
    finally:
        if old_settings is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass


def _signal_handler(signum, frame):
    global _interrupt_count
    _interrupt_count += 1
    if _interrupt_count >= 2:
        print(f"\n{_RED}⚠️  强制退出{_RESET}")
        # 保存会话后再退出
        _save_on_exit()
        sys.exit(1)
    print(f"\n{_YELLOW}⚠️  正在中断...（再次 Ctrl+C 强制退出）{_RESET}")
    signal.signal(signal.SIGINT, signal.default_int_handler)
    _thread.interrupt_main()


# 退出时保存的回调（由 interactive_mode 设置）
_exit_save_fn = None


def _save_on_exit():
    """信号处理中调用，保存当前会话。"""
    if _exit_save_fn:
        try:
            _exit_save_fn()
        except Exception:
            pass


def setup_signal_handlers():
    signal.signal(signal.SIGINT, _signal_handler)


# ─────────────────────────────────────────────
# 权限确认
# ─────────────────────────────────────────────


def _prompt_deny_reason() -> str | None:
    """用户选"拒绝"后弹单行输入框，返回理由（可空）或 None（取消）。"""
    prompt = f"  {_DIM}拒绝理由（可选，回车跳过，Esc 取消）：{_RESET}"
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        import termios
        import tty as _tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        buf = ""
        try:
            _tty.setcbreak(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch == "\x1b":  # Esc 取消
                    sys.stdout.write("\r\033[K")
                    sys.stdout.flush()
                    return None
                elif ch in ("\r", "\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return buf.strip() or None
                elif ch == "\x7f" or ch == "\x08":  # Backspace
                    if buf:
                        buf = buf[:-1]
                        # 整行重写，避免中文宽字符 \b \b 擦不干净
                        sys.stdout.write("\r\033[K")
                        sys.stdout.write(prompt + buf)
                        sys.stdout.flush()
                elif ch == "\x03":  # Ctrl+C
                    sys.stdout.write("\r\033[K")
                    sys.stdout.flush()
                    return None
                else:
                    buf += ch
                    sys.stdout.write(ch)
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        return None


def _confirm_action(tool_name: str, tool_input: dict, state: dict | None = None) -> tuple[bool, str | None, str]:
    """对危险操作进行确认。返回 (approved, reason, source)。

    source:
      "system" — 系统规则/配置（permission_mode/rule/READ_TOOLS 等自动放行或拒绝）
      "user"   — 用户在菜单里主动选择（执行/会话放行/拒绝）

    用户主动拒绝时弹出理由输入框（可选填）。
    """
    if state is None:
        state = {}
    permission_mode = get("permissions", "confirm")

    # ── 系统规则路径（不涉及用户交互）──
    if permission_mode == "auto-approve":
        return (True, None, "system")
    if permission_mode == "deny":
        return (False, None, "system")

    auto_tools = state.get("auto_approved_tools", set())
    if tool_name in auto_tools:
        return (True, None, "system")

    rule_result = check_permission_rule(tool_name, tool_input)
    if rule_result == "allow":
        return (True, None, "system")
    if rule_result == "deny":
        return (False, None, "system")

    from tools.permissions import READ_TOOLS

    if tool_name in READ_TOOLS:
        return (True, None, "system")

    # ── 按模式分流（plan / accept-edits / auto）──
    mode = state.get("mode", "accept-edits")

    if mode == "auto":
        # Auto：全自动（YOLO）
        return (True, None, "system")

    # accept-edits（默认）或 plan：编辑自动（plan 模式走下方确认）；
    # 破坏性 + 危险 bash 需要确认
    from tools.permissions import EDIT_TOOLS, DESTRUCTIVE_TOOLS

    if mode != "plan" and tool_name in EDIT_TOOLS:
        return (True, None, "system")

    if tool_name == "bash":
        command = tool_input.get("command", "")
        if not is_dangerous(command):
            return (True, None, "system")
        # 危险 bash 走确认
        print(f"\n  {_YELLOW}⚠️ bash:{_RESET} {_RED}{command}{_RESET}")
        items = [
            ("执行", "本次执行"),
            ("本次会话放行", "本次会话内自动允许 bash"),
            ("拒绝", "拒绝本次操作"),
        ]
        idx = _arrow_select_fallback(items)
        if idx is None or idx == 2:
            reason = _prompt_deny_reason()
            return (False, reason, "user")
        if idx == 1:
            auto_tools.add("bash")
            state["auto_approved_tools"] = auto_tools
        return (True, None, "user")

    if tool_name in DESTRUCTIVE_TOOLS:
        # 破坏性工具走确认
        print(f"\n  {_YELLOW}⚠️ {tool_name}:{_RESET} {json.dumps(tool_input, ensure_ascii=False)[:200]}")
        items = [
            ("执行", "本次执行"),
            ("本次会话放行", f"本次会话内自动允许 {tool_name}"),
            ("拒绝", "拒绝本次操作"),
        ]
        idx = _arrow_select_fallback(items)
        if idx is None or idx == 2:
            reason = _prompt_deny_reason()
            return (False, reason, "user")
        if idx == 1:
            auto_tools.add(tool_name)
            state["auto_approved_tools"] = auto_tools
        return (True, None, "user")

    # 未知工具默认问用户
    print(f"\n  {_YELLOW}⚠️ {tool_name}:{_RESET} {json.dumps(tool_input, ensure_ascii=False)[:200]}")
    items = [
        ("执行", "本次执行"),
        ("本次会话放行", f"本次会话内自动允许 {tool_name}"),
        ("拒绝", "拒绝本次操作"),
    ]
    idx = _arrow_select_fallback(items)
    if idx is None or idx == 2:
        reason = _prompt_deny_reason()
        return (False, reason, "user")
    if idx == 1:
        auto_tools.add(tool_name)
        state["auto_approved_tools"] = auto_tools
    return (True, None, "user")


# ─────────────────────────────────────────────
# Slash 命令
# ─────────────────────────────────────────────


def _handle_slash_command(cmd: str, messages: list[dict], state: dict | None = None) -> str | None:
    """处理 slash 命令，返回响应文本或 None。"""
    if state is None:
        state = {}
    result = dispatch_command(cmd, messages, state)
    if result is None:
        return None
    if result.quit:
        return "__QUIT__"
    if result.task_override:
        return f"__SKILL__{result.task_override}"
    return result.text


# ─────────────────────────────────────────────
# 交互模式主循环
# ─────────────────────────────────────────────


def interactive_mode(resume_session_id: str | None = None, session_name: str | None = None):
    """启动 TUI 交互模式。"""
    try:
        from tui import interactive_mode as tui_main

        tui_main(resume_session_id=resume_session_id, session_name=session_name)
    except ImportError:
        # rich 不可用时，回退到简单 CLI
        _interactive_mode_fallback(resume_session_id=resume_session_id, session_name=session_name)


def _interactive_mode_fallback(resume_session_id: str | None = None, session_name: str | None = None):
    """textual 不可用时的简单 CLI 回退。"""
    global _interrupt_count
    setup_signal_handlers()
    model = get("model")

    # 恢复会话或创建新会话
    from session import create_session, load_session, save_session

    messages: list[dict] = []
    session_id: str | None = None

    if resume_session_id:
        try:
            loaded_messages, saved_cwd, _meta = load_session(resume_session_id)
            messages.extend(loaded_messages)
            session_id = resume_session_id
            if saved_cwd and os.path.isdir(saved_cwd):
                from tools import set_cwd

                set_cwd(saved_cwd)
            print(f"  已恢复会话: {resume_session_id} ({len(messages)} 条消息)")
        except FileNotFoundError:
            print(f"  会话不存在: {resume_session_id}，创建新会话")

    if not session_id:
        session_id = create_session(name=session_name)
        if session_name:
            print(f"  会话已创建: {session_id} ({session_name})")

    print(f"{_CYAN}{'=' * 50}")
    print(f"  🐙 Octopus Agent  ({model})")
    print("  输入任务开始对话，/help 查看命令，quit 退出")
    print(f"{'=' * 50}{_RESET}")

    mcp = MCPManager()
    mcp_configs = get("mcp_servers", {})
    if mcp_configs:
        print(f"\n{_CYAN}连接 MCP 服务器...{_RESET}")
        count = mcp.connect_all(mcp_configs)
        if count == 0:
            print(f"  {_YELLOW}未成功连接任何 MCP 服务器{_RESET}")

    state: dict = {
        "current_agent": None,
        "agent_persona": None,
        "mode": "accept-edits",
        "auto_approved_tools": set(),
        "session_tokens": {"input": 0, "output": 0},
        "session_cost_usd": 0.0,
        "session_id": session_id,
    }

    # 注册退出保存回调
    global _exit_save_fn

    def _do_save():
        if session_id and messages:
            save_session(messages, session_id=session_id)

    _exit_save_fn = _do_save

    # SessionStart hook：会话启动后触发一次
    try:
        results = run_hooks(
            "SessionStart",
            {
                "session_id": session_id or "",
                "cwd": get_cwd(),
                "model": get("model"),
                "resumed": "1" if resume_session_id else "0",
            },
        )
        for r in results:
            if r.strip():
                print(f"  {_DIM}[SessionStart hook] {r}{_RESET}")
    except Exception:
        pass

    try:
        while True:
            agent_label = state.get("current_agent")
            prompt_prefix = f" ({agent_label})" if agent_label else ""
            try:
                task = input(f"\n{_GREEN}你{prompt_prefix}: {_RESET}").strip()
            except EOFError:
                print("\n再见！")
                break
            except KeyboardInterrupt:
                print()
                _interrupt_count = 0
                setup_signal_handlers()
                continue

            if not task:
                continue
            if task.lower() in ("quit", "exit", "q"):
                break

            if task.startswith("/"):
                result = _handle_slash_command(task, messages, state)
                if result == "__QUIT__":
                    break
                if result is not None:
                    if result.startswith("__SKILL__"):
                        task = result[len("__SKILL__") :]
                    else:
                        print(result)
                        continue

            _interrupt_count = 0

            def on_interrupt():
                _reset_interrupt()

            try:
                _force_compact = state.pop("_force_compact_next", False)
                # agent 人设 + Plan 模式 hint（独立传，不混进 persona）
                agent_persona = state.get("agent_persona")
                plan_hint = None
                if state.get("mode") == "plan":
                    from tools.permissions import build_plan_hint

                    plan_hint = build_plan_hint(web_mode=False)
                run_agent(
                    task,
                    messages=messages,
                    on_interrupt=on_interrupt,
                    confirm_fn=_confirm_action,
                    mcp=mcp,
                    agent_persona=agent_persona,
                    plan_hint=plan_hint,
                    ui_capabilities=UI_CAPABILITIES_CLI,
                    session_id=session_id,
                    force_compact=_force_compact,
                )
                # 自动保存
                save_session(messages, session_id=session_id)
            except KeyboardInterrupt:
                setup_signal_handlers()
                print(f"\n{_YELLOW}⚠️  任务已取消，回到输入模式{_RESET}")
            except Exception as e:
                # LLM API/网络错误等不应让整个 CLI 崩溃；打印错误回到输入循环
                import traceback

                print(f"\n{_RED}[错误] {type(e).__name__}: {e}{_RESET}")
                traceback.print_exc()
    finally:
        mcp.close_all()


def _reset_interrupt():
    global _interrupt_count
    _interrupt_count = 0
    setup_signal_handlers()
