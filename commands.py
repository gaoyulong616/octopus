"""Slash 命令注册表：每个命令独立函数，装饰器自动注册。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from constants import CYAN as _CYAN, GREEN as _GREEN, YELLOW as _YELLOW
from constants import RED as _RED, BOLD as _BOLD, RESET as _RESET, DIM as _DIM

# ── 命令注册表 ──

_REGISTRY: dict[str, Callable] = {}
_DESC: dict[str, str] = {}


def _register(name: str, desc: str = ""):
    """装饰器：注册 slash 命令处理器。"""
    def wrapper(fn: Callable):
        _REGISTRY[name] = fn
        _DESC[name] = desc
        return fn
    return wrapper


def get_command_names() -> list[str]:
    """返回所有已注册命令名（含 / 前缀）。"""
    return sorted(_REGISTRY.keys())


def get_command_desc(name: str) -> str:
    """返回命令描述文字。"""
    return _DESC.get(name, "")


# ── 返回类型 ──

@dataclass
class CommandResult:
    text: str | None = None
    quit: bool = False
    task_override: str | None = None


# ── 命令实现 ──

@_register("/help", "Show help")
def cmd_help(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    return CommandResult(
        text=(
            f"{_CYAN}可用命令:{_RESET}\n"
            "  /help              显示帮助信息\n"
            "  /init              生成项目指令文件 (OCTOPUS.md)\n"
            "  /clear             清除当前对话历史\n"
            "  /save              保存当前对话\n"
            "  /sessions          列出已保存的对话\n"
            "  /load <id>         加载已保存的对话\n"
            "  /resume [name]     切换到其他会话\n"
            "  /rename <名称>      重命名当前会话\n"
            "  /export [file]     导出对话为文本文件\n"
            "  /search <关键词>    搜索当前对话\n"
            "  /model [name]      查看/切换当前模型\n"
            "  /models            列出已配置的模型\n"
            "  /agents            列出可用 agents\n"
            "  /agent [name]      查看/切换当前 agent\n"
            "  /skills            列出可用 skills\n"
            "  /skill <name>      执行 skill\n"
            "  /config [key=val]  查看/修改配置\n"
            "  /plan              切换到 Plan 模式（只读）\n"
            "  /auto              切换到 Auto 模式（全自动）\n"
            "  /continue          继续上次中断的任务\n"
            "  /remember <内容>    保存长期记忆\n"
            "  /forget            清除所有记忆\n"
            "  /compact           手动压缩对话上下文\n"
            "  /cwd               显示当前工作目录\n"
            "  /quit              退出"
        )
    )


@_register("/clear", "Clear conversation history")
def cmd_clear(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    messages.clear()
    return CommandResult(text=f"{_YELLOW}对话历史已清除{_RESET}")


@_register("/save", "Save current session")
def cmd_save(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from session import save_session
    session_id = save_session(messages)
    return CommandResult(text=f"{_GREEN}已保存 session: {session_id}{_RESET}")


@_register("/sessions", "List saved sessions")
def cmd_sessions(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from session import list_sessions, _time_ago
    sessions = list_sessions()
    if not sessions:
        return CommandResult(text=f"{_YELLOW}没有已保存的 session{_RESET}")
    lines = [f"{_CYAN}已保存的 sessions:{_RESET}"]
    for s in sessions[:15]:
        preview = s.get("first_message", "") or s.get("name", s["session_id"])
        name = s.get("name", "")
        label = f"{name}" if name else preview[:50]
        branch = f" [{s['git_branch']}]" if s.get("git_branch") else ""
        ago = _time_ago(s.get("updated_at", ""))
        tokens = s.get("total_tokens", 0)
        token_info = f"  {tokens // 1000}k tok" if tokens else ""
        lines.append(
            f"  {_DIM}{s['session_id'][:8]}{_RESET}  "
            f"{label}{branch}  "
            f"({_DIM}{ago}{_RESET}, {s['message_count']} msgs{token_info})"
        )
    return CommandResult(text="\n".join(lines))


@_register("/load", "Load a session")
def cmd_load(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from session import load_session
    from tools import set_cwd
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if not arg:
        return CommandResult(text=f"{_YELLOW}用法: /load <session_id>{_RESET}")
    try:
        loaded_messages, saved_cwd, _meta = load_session(arg.strip())
        messages.clear()
        messages.extend(loaded_messages)
        if saved_cwd and os.path.isdir(saved_cwd):
            set_cwd(saved_cwd)
        return CommandResult(
            text=f"{_GREEN}已加载 session: {arg} ({len(messages)} 条消息){_RESET}"
        )
    except FileNotFoundError as e:
        return CommandResult(text=f"{_RED}{e}{_RESET}")


@_register("/model", "View/switch model")
def cmd_model(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from config import get, get_models, switch_model
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    current = get("model")
    models = get_models()
    if arg:
        resolved = switch_model(arg.strip())
        return CommandResult(text=f"{_GREEN}模型已切换为: {resolved}{_RESET}")
    lines = [f"{_CYAN}可用模型:{_RESET}"]
    for alias, model_name in sorted(models.items()):
        marker = " ← 当前" if model_name == current else ""
        alias_part = f" ({alias})" if alias != model_name else ""
        lines.append(f"  {model_name}{alias_part}{marker}")
    lines.append(f"\n用法: /model <模型名/别名>  如 /model sonnet")
    return CommandResult(text="\n".join(lines))


@_register("/models", "List configured models")
def cmd_models(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from config import get, get_models
    models = get_models()
    current = get("model")
    if not models:
        return CommandResult(
            text=f"{_YELLOW}未配置模型列表{_RESET}\n"
                 '在 config.json 中设置 models: {"alias": "model-name", ...}'
        )
    lines = [f"{_CYAN}已配置 {len(models)} 个模型:{_RESET}"]
    for alias, model_name in sorted(models.items()):
        marker = " ← 当前" if model_name == current else ""
        lines.append(f"  {alias} → {model_name}{marker}")
    return CommandResult(text="\n".join(lines))


@_register("/agents", "List available agents")
def cmd_agents(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from skills import load_agents
    agents = load_agents()
    if not agents:
        return CommandResult(
            text=f"{_YELLOW}没有可用的 agent（放在 ~/.agents/ 或 .agents/ 目录）{_RESET}"
        )
    current = state.get("current_agent")
    lines = [f"{_CYAN}可用 Agents:{_RESET}"]
    for a_name, a_def in sorted(agents.items()):
        marker = " ← 当前" if a_name == current else ""
        lines.append(f"  {a_name}{marker}")
    return CommandResult(text="\n".join(lines))


@_register("/agent", "View/switch agent")
def cmd_agent(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from skills import load_agents
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if not arg:
        current = state.get("current_agent")
        if current:
            return CommandResult(text=f"当前 agent: {current}")
        return CommandResult(text=f"当前 agent: {_CYAN}default{_RESET}（默认）")
    agent_name = arg.strip()
    if agent_name == "default":
        state["current_agent"] = None
        state["system_prompt_override"] = None
        return CommandResult(text=f"{_GREEN}已切换回默认 agent{_RESET}")
    agents = load_agents()
    if agent_name not in agents:
        return CommandResult(
            text=f"{_RED}未找到 agent: {agent_name}{_RESET}（用 /agents 查看）"
        )
    state["current_agent"] = agent_name
    state["system_prompt_override"] = agents[agent_name].content
    return CommandResult(text=f"{_GREEN}已切换 agent: {agent_name}{_RESET}")


@_register("/skills", "List available skills")
def cmd_skills(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from skills import load_skills
    skills = load_skills()
    if not skills:
        return CommandResult(
            text=f"{_YELLOW}没有可用的 skill（放在 ~/.skills/ 或 .skills/ 目录）{_RESET}"
        )
    lines = [f"{_CYAN}可用 Skills:{_RESET}"]
    for s_name, s_def in sorted(skills.items()):
        desc = f" — {s_def.description}" if s_def.description else ""
        args_info = ""
        if s_def.arguments:
            arg_names = [a.name + ("" if a.required else "?")
                         for a in s_def.arguments]
            args_info = f" [{', '.join(arg_names)}]"
        lines.append(f"  {s_name}{args_info}{desc}")
    return CommandResult(text="\n".join(lines))


@_register("/skill", "Run a skill")
def cmd_skill(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from skills import load_skills, render_skill, parse_skill_args
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if not arg:
        return CommandResult(text=f"{_YELLOW}用法: /skill <name> [key=value ...]{_RESET}")
    skill_parts = arg.strip().split(maxsplit=1)
    skill_name = skill_parts[0]
    skill_args_str = skill_parts[1] if len(skill_parts) > 1 else ""
    skills = load_skills()
    if skill_name not in skills:
        return CommandResult(
            text=f"{_RED}未找到 skill: {skill_name}{_RESET}（用 /skills 查看）"
        )
    skill = skills[skill_name]
    args = parse_skill_args(skill_args_str)
    prompt = render_skill(skill, args)
    return CommandResult(task_override=prompt)


@_register("/config", "View/change config")
def cmd_config(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from config import get, get_all, set_value, invalidate
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if arg:
        if "=" in arg:
            key, val = arg.split("=", 1)
            key, val = key.strip(), val.strip()
            set_value(key, val)
            invalidate()
            return CommandResult(text=f"{_GREEN}已设置 {key} = {val}{_RESET}")
        else:
            key = arg.strip()
            val = get(key)
            return CommandResult(text=f"{key} = {val}")
    cfg = get_all()
    lines = [f"{_CYAN}当前配置:{_RESET}"]
    for k, v in cfg.items():
        if k == "api_key" and v:
            v = v[:8] + "..." + v[-4:]
        lines.append(f"  {k} = {v}")
    return CommandResult(text="\n".join(lines))


@_register("/search", "Search conversation")
def cmd_search(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if not arg:
        return CommandResult(text=f"{_YELLOW}用法: /search <关键词>{_RESET}")
    query = arg.strip().lower()
    results = []
    for i, msg in enumerate(messages):
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in content if isinstance(b, dict) and b.get("type") == "text"
            ]
            full = " ".join(text_parts)
        else:
            full = str(content)
        if query in full.lower():
            role = msg.get("role", "?")
            preview = full[:150].replace("\n", " ")
            if len(full) > 150:
                preview += "..."
            results.append(f"  #{i} [{role}] {preview}")
    if not results:
        return CommandResult(text=f'{_YELLOW}未找到匹配 "{arg}"{_RESET}')
    lines = [f'{_CYAN}搜索 "{arg}" 找到 {len(results)} 处:{_RESET}']
    lines.extend(results)
    return CommandResult(text="\n".join(lines))


@_register("/plan", "Plan mode (read-only)")
def cmd_plan(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    state["plan_mode"] = True
    state["auto_approved_tools"] = set()
    return CommandResult(text=f"{_YELLOW}已切换到 Plan 模式（只读，不执行写入操作）{_RESET}")


@_register("/auto", "Auto mode (full access)")
def cmd_auto(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    state["plan_mode"] = False
    return CommandResult(text=f"{_GREEN}已切换到 Auto 模式（允许所有操作）{_RESET}")


@_register("/continue", "Resume interrupted task")
def cmd_continue(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    last = state.get("last_task")
    if not last:
        return CommandResult(text=f"{_YELLOW}没有可继续的任务{_RESET}")
    state.pop("last_task", None)
    return CommandResult(task_override=last)


@_register("/remember", "Save long-term memory")
def cmd_remember(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if not arg:
        return CommandResult(text=f"{_YELLOW}用法: /remember <内容>{_RESET}")
    from context import save_memory
    return CommandResult(text=f"{_GREEN}{save_memory(arg.strip())}{_RESET}")


@_register("/forget", "Clear all memories")
def cmd_forget(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from context import clear_memory
    return CommandResult(text=f"{_GREEN}{clear_memory()}{_RESET}")


@_register("/compact", "Compress conversation context")
def cmd_compact(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    if not messages:
        return CommandResult(text=f"{_YELLOW}没有对话历史{_RESET}")
    import anthropic
    from config import get as _get
    from context import compress_messages
    client = anthropic.Anthropic(
        api_key=_get("api_key"),
        base_url=_get("base_url") or None,
    )
    old_count = len(messages)
    messages[:] = compress_messages(client, messages, _get("model"))
    return CommandResult(
        text=f"{_GREEN}对话已压缩: {old_count} → {len(messages)} 条消息{_RESET}"
    )


@_register("/cwd", "Show working directory")
def cmd_cwd(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from tools import get_cwd
    return CommandResult(text=f"工作目录: {get_cwd()}")


@_register("/init", "Generate project instructions file")
def cmd_init(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    """分析项目结构，生成 OCTOPUS.md 或 CLAUDE.md 项目指令文件。"""
    from tools import get_cwd, run_list_files, run_bash
    import os

    cwd = get_cwd()
    # 检测目标文件名：优先 OCTOPUS.md，已有则沿用；否则检查 CLAUDE.md；都没有则创建 OCTOPUS.md
    target = "OCTOPUS.md"
    existing_path = os.path.join(cwd, "OCTOPUS.md")
    if not os.path.exists(existing_path):
        claude_path = os.path.join(cwd, "CLAUDE.md")
        if os.path.exists(claude_path):
            target = "CLAUDE.md"
            existing_path = claude_path
        else:
            existing_path = os.path.join(cwd, "OCTOPUS.md")

    # 如果文件已存在，确认覆盖
    if os.path.exists(existing_path):
        try:
            choice = input(f"  {existing_path} 已存在，覆盖？[y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return CommandResult(text=f"{_DIM}已取消{_RESET}")
        except (EOFError, KeyboardInterrupt):
            return CommandResult(text=f"{_DIM}已取消{_RESET}")

    # 收集项目信息
    # 1. 文件结构
    files_output = run_list_files(".", "", recursive=True) or ""
    top_files = run_list_files(".", "", recursive=False) or ""

    # 2. 检测语言/框架
    lang_hints = []
    framework_hints = []
    py_files = [f for f in files_output.split("\n") if f.endswith(".py")]
    js_files = [f for f in files_output.split("\n") if f.endswith((".js", ".ts", ".tsx", ".jsx"))]

    if py_files:
        lang_hints.append("Python")
        # 检测框架
        if any("manage.py" in f for f in py_files):
            framework_hints.append("Django")
        if any("app.py" in f or "main.py" in f for f in py_files):
            framework_hints.append("Flask/FastAPI")
        if any("requirements" in f or "pyproject.toml" in f for f in files_output.split("\n")):
            pass  # 标准 Python 项目
    if js_files:
        lang_hints.append("JavaScript/TypeScript")
        if any("next.config" in f for f in files_output.split("\n")):
            framework_hints.append("Next.js")
        if any("package.json" in f for f in files_output.split("\n")):
            framework_hints.append("Node.js")

    # 3. 检测 git
    is_git = os.path.isdir(os.path.join(cwd, ".git"))

    # 4. 读取 README 如果存在
    readme_content = ""
    for readme_name in ("README.md", "readme.md", "README.txt"):
        readme_path = os.path.join(cwd, readme_name)
        if os.path.isfile(readme_path):
            try:
                with open(readme_path, encoding="utf-8", errors="ignore") as f:
                    readme_content = f.read()[:1000]
            except OSError:
                pass
            break

    # 5. 读取已有 CLAUDE.md/OCTOPUS.md 作为参考
    existing_content = ""
    if os.path.exists(existing_path):
        try:
            with open(existing_path, encoding="utf-8") as f:
                existing_content = f.read()
        except OSError:
            pass

    # 构建提示词让用户确认生成
    # 实际生成由 Agent 完成（追加一个任务到 messages）
    project_name = os.path.basename(cwd)
    lang_str = "/".join(lang_hints) if lang_hints else "Unknown"
    fw_str = ", ".join(framework_hints) if framework_hints else ""

    # 构建生成指令
    init_prompt = (
        f"请为项目 '{project_name}' 生成项目指令文件 {target}。\n\n"
        f"## 项目信息\n"
        f"- 路径: {cwd}\n"
        f"- 语言: {lang_str}\n"
    )
    if fw_str:
        init_prompt += f"- 框架: {fw_str}\n"
    if is_git:
        init_prompt += f"- Git: 是\n"
    init_prompt += (
        f"\n## 顶层文件\n"
        f"```\n{top_files[:500]}\n```\n"
    )
    if readme_content:
        init_prompt += (
            f"\n## README 摘要\n"
            f"```\n{readme_content[:500]}\n```\n"
        )

    init_prompt += (
        f"\n## 要求\n"
        f"1. 分析项目结构，生成清晰的项目指令文件\n"
        f"2. 包含以下部分：\n"
        f"   - 项目概述（一句话描述项目是什么）\n"
        f"   - 架构说明（模块/文件职责）\n"
        f"   - 运行方式（安装、启动命令）\n"
        f"   - 开发指南（编码规范、新增功能指引）\n"
        f"3. 用中文编写\n"
        f"4. 直接将内容写入 {target}\n"
    )

    if existing_content:
        init_prompt += (
            f"\n## 现有内容（作为参考改进）\n"
            f"```\n{existing_content[:1000]}\n```\n"
        )

    # 返回任务覆盖，让主循环执行这个生成任务
    return CommandResult(task_override=init_prompt)


@_register("/quit", "Exit")
def cmd_quit(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    return CommandResult(quit=True)


@_register("/rename", "Rename current session")
def cmd_rename(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from session import rename_session
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if not arg:
        return CommandResult(text=f"{_YELLOW}用法: /rename <名称>{_RESET}")
    session_id = state.get("session_id")
    if not session_id:
        return CommandResult(text=f"{_YELLOW}当前没有活跃会话{_RESET}")
    rename_session(session_id, arg.strip())
    return CommandResult(text=f"{_GREEN}会话已重命名为: {arg.strip()}{_RESET}")


@_register("/resume", "Switch to another session")
def cmd_resume(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from session import load_session, find_session_by_name
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""

    if arg:
        # 按名称/ID 恢复
        try:
            load_session(arg.strip())
            sid = arg.strip()
        except FileNotFoundError:
            sid = find_session_by_name(arg.strip())
            if not sid:
                return CommandResult(text=f"{_RED}未找到会话: {arg.strip()}{_RESET}")
    else:
        # 交互式选择器
        try:
            from tui import session_selector
        except ImportError:
            # fallback：直接调用简易版
            from session import list_sessions
            sessions = list_sessions()
            if not sessions:
                return CommandResult(text=f"{_YELLOW}没有已保存的会话{_RESET}")
            from tui import _session_selector_fallback
            sid = _session_selector_fallback(sessions)
        else:
            sid = session_selector()

        if not sid:
            return CommandResult(text=f"{_DIM}已取消{_RESET}")

    # 执行加载
    try:
        from tools import set_cwd
        loaded_messages, saved_cwd, _meta = load_session(sid)
        messages.clear()
        messages.extend(loaded_messages)
        if saved_cwd and os.path.isdir(saved_cwd):
            set_cwd(saved_cwd)
        state["session_id"] = sid
        return CommandResult(
            text=f"{_GREEN}已切换到会话: {sid[:8]} ({len(messages)} 条消息){_RESET}"
        )
    except FileNotFoundError as e:
        return CommandResult(text=f"{_RED}{e}{_RESET}")


@_register("/export", "Export session to text file")
def cmd_export(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from session import export_session
    parts = cmd.strip().split(maxsplit=1)
    filename = parts[1].strip() if len(parts) > 1 else None
    session_id = state.get("session_id")
    if not session_id:
        return CommandResult(text=f"{_YELLOW}当前没有活跃会话{_RESET}")
    path = export_session(session_id, output_path=filename)
    return CommandResult(text=f"{_GREEN}已导出到: {path}{_RESET}")


# ── 分发 ──

def dispatch_command(cmd: str, messages: list[dict], state: dict) -> CommandResult | None:
    """查找并执行命令处理器。返回 None 表示未注册的命令。"""
    name = cmd.strip().split(maxsplit=1)[0].lower()
    # 别名
    if name in ("/exit", "/q"):
        name = "/quit"
    handler = _REGISTRY.get(name)
    if handler is None:
        return None
    return handler(cmd, messages, state)
