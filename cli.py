"""交互式 CLI：多轮对话、slash 命令、权限确认、信号处理。"""

import json
import os
import readline  # 解决 macOS 中文退格问题
import signal
import sys
import _thread

from agent import run_agent
from config import get, get_all, set_value, invalidate, is_dangerous, get_models, switch_model, resolve_model
from mcp import MCPManager
from session import save_session, load_session, list_sessions
from skills import load_agents, load_skills, render_skill, parse_skill_args
from tools import set_cwd, get_cwd

_interrupt_count = 0

# ANSI 颜色
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


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

def _confirm_action(tool_name: str, tool_input: dict) -> bool:
    """对危险操作进行确认，返回 True 表示允许执行。"""
    permission_mode = get("permissions", "confirm")

    if permission_mode == "auto-approve":
        return True
    if permission_mode == "deny":
        return False

    # confirm 模式：只对危险操作确认
    command = ""
    if tool_name == "bash":
        command = tool_input.get("command", "")
    elif tool_name == "write_file":
        path = tool_input.get("path", "")
        mode = tool_input.get("mode", "w")
        command = f"write {path} (mode={mode})"

    if not is_dangerous(command):
        return True

    # 显示确认提示
    print(f"\n  {_YELLOW}⚠️ 检测到潜在危险操作:{_RESET}")
    if tool_name == "bash":
        print(f"    {_RED}{command}{_RESET}")
    else:
        print(f"    {tool_name}: {json.dumps(tool_input, ensure_ascii=False)[:200]}")
    print(f"  {_BOLD}[y] 执行  [n] 拒绝  [a] 本轮全部允许{_RESET}")

    try:
        choice = input("  选择: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if choice == "a":
        set_value("permissions", "auto-approve")
        return True
    return choice in ("y", "yes")


# ─────────────────────────────────────────────
# Slash 命令
# ─────────────────────────────────────────────

def _handle_slash_command(cmd: str, messages: list[dict],
                         state: dict | None = None) -> str | None:
    """处理 slash 命令，返回响应文本或 None（表示不是 slash 命令）。
    state dict 可包含: current_agent, system_prompt_override
    """
    if state is None:
        state = {}
    parts = cmd.strip().split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if name == "/help":
        return (
            f"{_CYAN}可用命令:{_RESET}\n"
            "  /help              显示帮助信息\n"
            "  /clear             清除当前对话历史\n"
            "  /save              保存当前对话\n"
            "  /sessions          列出已保存的对话\n"
            "  /load <id>         加载已保存的对话\n"
            "  /model [name]      查看/切换当前模型\n"
            "  /models            列出已配置的模型\n"
            "  /agents            列出可用 agents\n"
            "  /agent [name]      查看/切换当前 agent\n"
            "  /skills            列出可用 skills\n"
            "  /skill <name>      执行 skill\n"
            "  /config [key=val]  查看/修改配置\n"
            "  /cwd               显示当前工作目录\n"
            "  /quit              退出"
        )

    if name == "/clear":
        messages.clear()
        return f"{_YELLOW}对话历史已清除{_RESET}"

    if name == "/save":
        session_id = save_session(messages)
        return f"{_GREEN}已保存 session: {session_id}{_RESET}"

    if name == "/sessions":
        sessions = list_sessions()
        if not sessions:
            return f"{_YELLOW}没有已保存的 session{_RESET}"
        lines = [f"{_CYAN}已保存的 sessions:{_RESET}"]
        for s in sessions[:10]:
            lines.append(
                f"  {s['id']}  {s['saved_at'][:19]}  "
                f"({s['messages']} 条消息)  {s['cwd']}"
            )
        return "\n".join(lines)

    if name == "/load":
        if not arg:
            return f"{_YELLOW}用法: /load <session_id>{_RESET}"
        try:
            loaded_messages, saved_cwd = load_session(arg.strip())
            messages.clear()
            messages.extend(loaded_messages)
            if saved_cwd and os.path.isdir(saved_cwd):
                set_cwd(saved_cwd)
            return (
                f"{_GREEN}已加载 session: {arg} "
                f"({len(messages)} 条消息){_RESET}"
            )
        except FileNotFoundError as e:
            return f"{_RED}{e}{_RESET}"

    if name == "/model":
        current = get("model")
        models = get_models()
        if arg:
            resolved = switch_model(arg.strip())
            return f"{_GREEN}模型已切换为: {resolved}{_RESET}"
        # 无参数时列出所有可用模型
        lines = [f"{_CYAN}可用模型:{_RESET}"]
        for alias, model_name in sorted(models.items()):
            marker = " ← 当前" if model_name == current else ""
            alias_part = f" ({alias})" if alias != model_name else ""
            lines.append(f"  {model_name}{alias_part}{marker}")
        lines.append(f"\n用法: /model <模型名/别名>  如 /model sonnet")
        return "\n".join(lines)

    if name == "/models":
        models = get_models()
        current = get("model")
        if not models:
            return f"{_YELLOW}未配置模型列表{_RESET}\n在 config.json 中设置 models: {{\"alias\": \"model-name\", ...}}"
        lines = [f"{_CYAN}已配置 {len(models)} 个模型:{_RESET}"]
        for alias, model_name in sorted(models.items()):
            marker = " ← 当前" if model_name == current else ""
            lines.append(f"  {alias} → {model_name}{marker}")
        return "\n".join(lines)

    # Agent 命令
    if name == "/agents":
        agents = load_agents()
        if not agents:
            return f"{_YELLOW}没有可用的 agent（放在 ~/.agents/ 或 .agents/ 目录）{_RESET}"
        current = state.get("current_agent")
        lines = [f"{_CYAN}可用 Agents:{_RESET}"]
        for a_name, a_def in sorted(agents.items()):
            marker = " ← 当前" if a_name == current else ""
            lines.append(f"  {a_name}{marker}")
        return "\n".join(lines)

    if name == "/agent":
        if not arg:
            current = state.get("current_agent")
            if current:
                return f"当前 agent: {current}"
            return f"当前 agent: {_CYAN}default{_RESET}（默认）"
        agent_name = arg.strip()
        if agent_name == "default":
            state["current_agent"] = None
            state["system_prompt_override"] = None
            return f"{_GREEN}已切换回默认 agent{_RESET}"
        agents = load_agents()
        if agent_name not in agents:
            return f"{_RED}未找到 agent: {agent_name}{_RESET}（用 /agents 查看）"
        state["current_agent"] = agent_name
        state["system_prompt_override"] = agents[agent_name].content
        return f"{_GREEN}已切换 agent: {agent_name}{_RESET}"

    # Skill 命令
    if name == "/skills":
        skills = load_skills()
        if not skills:
            return f"{_YELLOW}没有可用的 skill（放在 ~/.skills/ 或 .skills/ 目录）{_RESET}"
        lines = [f"{_CYAN}可用 Skills:{_RESET}"]
        for s_name, s_def in sorted(skills.items()):
            desc = f" — {s_def.description}" if s_def.description else ""
            args_info = ""
            if s_def.arguments:
                arg_names = [a.name + ("" if a.required else "?")
                             for a in s_def.arguments]
                args_info = f" [{', '.join(arg_names)}]"
            lines.append(f"  {s_name}{args_info}{desc}")
        return "\n".join(lines)

    if name == "/skill":
        if not arg:
            return f"{_YELLOW}用法: /skill <name> [key=value ...]{_RESET}"
        skill_parts = arg.strip().split(maxsplit=1)
        skill_name = skill_parts[0]
        skill_args_str = skill_parts[1] if len(skill_parts) > 1 else ""
        skills = load_skills()
        if skill_name not in skills:
            return f"{_RED}未找到 skill: {skill_name}{_RESET}（用 /skills 查看）"
        skill = skills[skill_name]
        args = parse_skill_args(skill_args_str)
        prompt = render_skill(skill, args)
        # 返回特殊标记，让主循环执行这个 prompt
        return f"__SKILL__{prompt}"

    if name == "/config":
        if arg:
            if "=" in arg:
                key, val = arg.split("=", 1)
                key = key.strip()
                val = val.strip()
                set_value(key, val)
                invalidate()
                return f"{_GREEN}已设置 {key} = {val}{_RESET}"
            else:
                key = arg.strip()
                val = get(key)
                return f"{key} = {val}"
        cfg = get_all()
        lines = [f"{_CYAN}当前配置:{_RESET}"]
        for k, v in cfg.items():
            if k == "api_key" and v:
                v = v[:8] + "..." + v[-4:]
            lines.append(f"  {k} = {v}")
        return "\n".join(lines)

    if name == "/cwd":
        return f"工作目录: {get_cwd()}"

    if name in ("/quit", "/exit", "/q"):
        return "__QUIT__"

    return None


# ─────────────────────────────────────────────
# 交互模式主循环
# ─────────────────────────────────────────────

def interactive_mode():
    """启动 TUI 交互模式。"""
    try:
        from tui import interactive_mode as tui_main
        tui_main()
    except ImportError:
        # rich 不可用时，回退到简单 CLI
        _interactive_mode_fallback()


def _interactive_mode_fallback():
    """textual 不可用时的简单 CLI 回退。"""
    global _interrupt_count
    setup_signal_handlers()
    model = get("model")
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

    messages: list[dict] = []
    state: dict = {"current_agent": None, "system_prompt_override": None}

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
                print("再见！")
                break

            if task.startswith("/"):
                result = _handle_slash_command(task, messages, state)
                if result == "__QUIT__":
                    print("再见！")
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
                )
            except KeyboardInterrupt:
                setup_signal_handlers()
                print(f"\n{_YELLOW}⚠️  任务已取消，回到输入模式{_RESET}")
    finally:
        mcp.close_all()


def _reset_interrupt():
    global _interrupt_count
    _interrupt_count = 0
    setup_signal_handlers()
