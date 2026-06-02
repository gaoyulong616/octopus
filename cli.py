"""交互式 CLI：多轮对话、slash 命令、权限确认、信号处理。"""

import json
import os
import readline  # 解决 macOS 中文退格问题
import signal
import sys
import _thread

from agent import run_agent
from config import (get, get_all, set_value, invalidate, is_dangerous,
                    get_models, switch_model, resolve_model,
                    check_permission_rule, run_hooks)
from commands import dispatch_command
from mcp import MCPManager
from tools import set_cwd, get_cwd

_interrupt_count = 0

from constants import CYAN as _CYAN, GREEN as _GREEN, YELLOW as _YELLOW
from constants import RED as _RED, BOLD as _BOLD, RESET as _RESET


def _signal_handler(signum, frame):
    global _interrupt_count
    _interrupt_count += 1
    if _interrupt_count >= 2:
        print(f"\n{_RED}⚠️  强制退出{_RESET}")
        sys.exit(1)
    print(f"\n{_YELLOW}⚠️  正在中断...（再次 Ctrl+C 强制退出）{_RESET}")
    signal.signal(signal.SIGINT, signal.default_int_handler)
    _thread.interrupt_main()


def setup_signal_handlers():
    signal.signal(signal.SIGINT, _signal_handler)


# ─────────────────────────────────────────────
# 权限确认
# ─────────────────────────────────────────────

def _confirm_action(tool_name: str, tool_input: dict, state: dict | None = None) -> bool:
    """对危险操作进行确认，返回 True 表示允许执行。

    支持四档：
      [y/o] once — 本次允许
      [s/a] session — 本次会话内允许该工具（不写入配置文件）
      [p]   permanent — 写入 permission_rules 永久放行
      [n]   deny — 拒绝
    """
    if state is None:
        state = {}
    permission_mode = get("permissions", "confirm")

    if permission_mode == "auto-approve":
        return True
    if permission_mode == "deny":
        return False

    # 已 session 级放行的工具直接通过
    auto_tools = state.get("auto_approved_tools", set())
    if tool_name in auto_tools:
        return True

    # 细粒度权限规则检查（包含持久化的 permission_rules）
    rule_result = check_permission_rule(tool_name, tool_input)
    if rule_result == "allow":
        return True
    if rule_result == "deny":
        return False

    # 读取类工具自动通过
    read_tools = {"read_file", "list_files", "grep_search", "web_search", "web_fetch"}
    if tool_name in read_tools:
        return True

    # 写入类工具需要确认
    command = ""
    if tool_name == "bash":
        command = tool_input.get("command", "")
    elif tool_name == "write_file":
        path = tool_input.get("path", "")
        mode = tool_input.get("mode", "w")
        command = f"write {path} (mode={mode})"
    elif tool_name == "edit_file":
        path = tool_input.get("path", "")
        command = f"edit {path}"

    # 非危险 bash 命令自动通过
    if tool_name == "bash" and not is_dangerous(command):
        return True

    # 显示确认提示
    print(f"\n  {_YELLOW}⚠️ {tool_name}: {_RESET}", end="")
    if tool_name == "bash":
        print(f"{_RED}{command}{_RESET}")
    else:
        print(f"{json.dumps(tool_input, ensure_ascii=False)[:200]}")
    print(f"  {_BOLD}[y]once  [s]session  [p]permanent  [n]拒绝{_RESET}")

    try:
        choice = input("  选择: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if choice in ("p", "permanent"):
        # 写入持久化 permission_rules：以工具名为 key 整工具放行
        _add_permanent_permission(tool_name, tool_input)
        return True
    if choice in ("s", "a", "session"):
        auto_tools.add(tool_name)
        state["auto_approved_tools"] = auto_tools
        return True
    return choice in ("y", "yes", "o", "once")


def _add_permanent_permission(tool_name: str, tool_input: dict):
    """把放行规则写入 ~/.octopus/config.json 的 permission_rules。"""
    try:
        from pathlib import Path
        config_path = Path.home() / ".octopus" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        cfg: dict = {}
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        rules = cfg.get("permission_rules", []) or []
        # 构造最小匹配 pattern
        if tool_name == "bash":
            cmd = (tool_input.get("command") or "").strip()
            # 取命令首词作为模式（同类命令都放行）
            pattern = cmd.split()[0] if cmd else ".*"
        elif tool_name in ("write_file", "edit_file"):
            path = tool_input.get("path") or ""
            # 默认放行该文件所在目录
            pattern = path.rsplit("/", 1)[0] + "/.*" if "/" in path else ".*"
        else:
            pattern = ".*"
        new_rule = {"tool": tool_name, "pattern": pattern, "action": "allow"}
        if new_rule not in rules:
            rules.append(new_rule)
        cfg["permission_rules"] = rules
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        invalidate()
    except Exception:
        pass


# ─────────────────────────────────────────────
# Slash 命令
# ─────────────────────────────────────────────

def _handle_slash_command(cmd: str, messages: list[dict],
                         state: dict | None = None) -> str | None:
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

def interactive_mode(resume_session_id: str | None = None,
                     session_name: str | None = None):
    """启动 TUI 交互模式。"""
    try:
        from tui import interactive_mode as tui_main
        tui_main(resume_session_id=resume_session_id,
                 session_name=session_name)
    except ImportError:
        # rich 不可用时，回退到简单 CLI
        _interactive_mode_fallback(resume_session_id=resume_session_id,
                                   session_name=session_name)


def _interactive_mode_fallback(resume_session_id: str | None = None,
                               session_name: str | None = None):
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

    state: dict = {"current_agent": None, "system_prompt_override": None,
                   "session_id": session_id}

    # SessionStart hook：会话启动后触发一次
    try:
        results = run_hooks("SessionStart", {
            "session_id": session_id or "",
            "cwd": get_cwd(),
            "model": get("model"),
            "resumed": "1" if resume_session_id else "0",
        })
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
                        task = result[len("__SKILL__"):]
                    else:
                        print(result)
                        continue

            _interrupt_count = 0

            def on_interrupt():
                _reset_interrupt()

            try:
                run_agent(
                    task,
                    messages=messages,
                    on_interrupt=on_interrupt,
                    confirm_fn=_confirm_action,
                    mcp=mcp,
                    system_prompt_override=state.get("system_prompt_override"),
                    session_id=session_id,
                )
                # 自动保存
                save_session(messages, session_id=session_id)
            except KeyboardInterrupt:
                setup_signal_handlers()
                print(f"\n{_YELLOW}⚠️  任务已取消，回到输入模式{_RESET}")
    finally:
        mcp.close_all()


def _reset_interrupt():
    global _interrupt_count
    _interrupt_count = 0
    setup_signal_handlers()
