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
            "  /resume [name]     切换到其他会话（↑↓ 选择、搜索、摘要预览）\n"
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
            "  /review            审查当前分支的代码变更\n"
            "  /diff              显示未提交的代码变更\n"
            "  /context           显示上下文使用情况（token 分布）\n"
            "  /memory [type]     列出长期记忆（按类型过滤）\n"
            "  /remember <内容>    保存长期记忆（格式: [type:]内容）\n"
            "  /forget [name]     删除指定记忆；不带参数则清空全部\n"
            "  /permissions       查看当前会话已批准的权限\n"
            "  /stats             查看 LLM 调用统计与成本\n"
            "  /compact           手动压缩对话上下文\n"
            "  /cwd               显示当前工作目录\n"
            "  /quit              退出\n"
            "\n  记忆类型: user / feedback / project / reference"
        )
    )


@_register("/clear", "Clear conversation history")
def cmd_clear(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    messages.clear()
    return CommandResult(text=f"{_YELLOW}对话历史已清除{_RESET}")


@_register("/model", "View/switch model")
def cmd_model(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from config import get, get_models, switch_model
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    current = get("model")
    models = get_models()
    if arg:
        try:
            model_name, provider = switch_model(arg.strip())
        except ValueError as e:
            return CommandResult(text=f"{_RED}{e}{_RESET}")
        ptext = f" {_DIM}{provider}{_RESET}" if provider and provider != "None" else ""
        return CommandResult(text=f"{_GREEN}模型已切换为: {model_name}{ptext}{_RESET}")
    lines = [f"{_CYAN}可用模型:{_RESET}"]
    for model_name, provider in sorted(models.items()):
        marker = " ← 当前" if model_name == current else ""
        ptext = f" {_DIM}{provider}{_RESET}" if provider else ""
        lines.append(f"  {model_name}{ptext}{marker}")
    lines.append(f"\n用法: /model <模型名>          如 /model glm-5.1")
    lines.append(f"      /model <提供商>/<模型名>  如 /model zhipu/glm-5.1")
    return CommandResult(text="\n".join(lines))


@_register("/models", "List configured models")
def cmd_models(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from config import get, get_models
    models = get_models()
    current = get("model")
    if not models:
        return CommandResult(text=f"{_YELLOW}未配置模型列表{_RESET}")
    providers = get("providers") or {}
    lines = [f"{_CYAN}已配置 {len(providers)} 个提供商, {len(models)} 个模型:{_RESET}"]
    for pname, pcfg in sorted(providers.items()):
        model_list = ", ".join(pcfg.get("models", []))
        lines.append(f"  {_BOLD}{pname}{_RESET}: {model_list}")
    lines.append(f"\n当前: {current} ({get('provider') or '—'})")
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


@_register("/memory", "List memories (optionally by type)")
def cmd_memory(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    from context import list_memories, MEMORY_TYPES
    parts = cmd.strip().split(maxsplit=1)
    type_filter = parts[1].strip() if len(parts) > 1 else None
    if type_filter and type_filter not in MEMORY_TYPES:
        return CommandResult(
            text=f"{_YELLOW}类型必须是 {','.join(MEMORY_TYPES)} 之一{_RESET}"
        )
    entries = list_memories(type_filter)
    if not entries:
        return CommandResult(text=f"{_YELLOW}暂无记忆{_RESET}")
    by_type: dict[str, list] = {}
    for e in entries:
        by_type.setdefault(e.get("type", "user"), []).append(e)
    type_labels = {"user": "用户", "feedback": "反馈", "project": "项目", "reference": "引用"}
    lines = [f"{_CYAN}共 {len(entries)} 条记忆:{_RESET}"]
    for t in MEMORY_TYPES:
        if t not in by_type:
            continue
        lines.append(f"\n{_BOLD}{type_labels.get(t, t)} ({len(by_type[t])}){_RESET}")
        for e in by_type[t]:
            name = e.get("name", "?")
            desc = e.get("description", "")
            lines.append(f"  {name}: {desc}")
    return CommandResult(text="\n".join(lines))


@_register("/remember", "Save long-term memory (format: [type:]content)")
def cmd_remember(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if not arg:
        return CommandResult(
            text=(
                f"{_YELLOW}用法:{_RESET}\n"
                "  /remember <内容>                # 默认 user 类型\n"
                "  /remember feedback: <内容>      # 指定类型\n"
                "  /remember project: <名称>: <内容> # 指定名称\n"
                f"  类型: user / feedback / project / reference"
            )
        )
    from context import save_memory, MEMORY_TYPES
    # 解析格式：[type:][name:]content
    mtype = "user"
    name = None
    text = arg.strip()
    if ":" in text:
        head, _, rest = text.partition(":")
        head = head.strip().lower()
        if head in MEMORY_TYPES:
            mtype = head
            text = rest.strip()
            # 再尝试解析 name
            if ":" in text:
                head2, _, rest2 = text.partition(":")
                if head2.strip() and not head2.strip().startswith(("http://", "https://")):
                    name = head2.strip()
                    text = rest2.strip()
    if not text:
        return CommandResult(text=f"{_YELLOW}内容不能为空{_RESET}")
    msg = save_memory(text, mtype=mtype, name=name)
    return CommandResult(text=f"{_GREEN}{msg}{_RESET}")


@_register("/forget", "Delete a memory by name, or clear all")
def cmd_forget(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    from context import delete_memory, clear_memory
    if not arg:
        return CommandResult(text=f"{_GREEN}{clear_memory()}{_RESET}")
    return CommandResult(text=f"{_GREEN}{delete_memory(arg)}{_RESET}")


@_register("/permissions", "Show approved permissions in current session")
def cmd_permissions(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    auto_tools = sorted(state.get("auto_approved_tools", set()))
    session_rules = state.get("session_permission_rules", [])
    if not auto_tools and not session_rules:
        return CommandResult(text=f"{_DIM}当前会话没有放行的工具/规则{_RESET}")
    lines = [f"{_CYAN}当前会话权限状态:{_RESET}"]
    if auto_tools:
        lines.append(f"\n{_BOLD}已放行工具:{_RESET}")
        for t in auto_tools:
            lines.append(f"  • {t}")
    if session_rules:
        lines.append(f"\n{_BOLD}会话级规则:{_RESET}")
        for r in session_rules:
            lines.append(f"  • {r.get('tool','?')}: {r.get('pattern','')} ({r.get('action','?')})")
    return CommandResult(text="\n".join(lines))


@_register("/stats", "Show LLM call statistics and cost")
def cmd_stats(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    import metrics
    parts = cmd.strip().split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    filters = {}
    if arg == "session":
        sid = state.get("session_id", "")
        if sid:
            filters["session"] = sid[:12]
    elif arg:
        # 当作 model 名过滤
        filters["model"] = arg
    text = metrics.format_stats(filters or None)
    return CommandResult(text=f"{_CYAN}LLM 调用统计{_RESET}\n\n{text}")


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


@_register("/review", "Review code changes")
def cmd_review(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    """审查当前分支的代码变更。"""
    from tools import get_cwd, run_bash
    import os

    cwd = get_cwd()

    # 获取当前分支名
    branch_result = run_bash("git rev-parse --abbrev-ref HEAD", timeout=10)
    branch = branch_result.strip().replace("\n", "")
    if "[错误]" in branch_result or "[exit code" in branch_result:
        return CommandResult(text=f"{_RED}不在 git 仓库中{_RESET}")

    # 获取 diff
    # 先尝试获取与 main 分支的 diff
    diff_result = run_bash(
        "git diff main...HEAD --stat 2>/dev/null || git diff master...HEAD --stat 2>/dev/null || git diff HEAD~1...HEAD --stat",
        timeout=30,
    )
    if not diff_result.strip() or "[错误]" in diff_result:
        diff_result = run_bash("git diff --stat", timeout=30)

    # 获取完整 diff
    full_diff = run_bash(
        "git diff main...HEAD 2>/dev/null || git diff master...HEAD 2>/dev/null || git diff HEAD~1...HEAD",
        timeout=30,
    )
    if not full_diff.strip() or "[错误]" in full_diff:
        full_diff = run_bash("git diff", timeout=30)

    if not full_diff.strip():
        return CommandResult(text=f"{_YELLOW}没有可审查的变更{_RESET}")

    # 获取 commit 历史
    log_result = run_bash(
        "git log --oneline -10 2>/dev/null",
        timeout=10,
    )

    # 构建审查 prompt
    review_prompt = (
        f"请审查以下代码变更，提供结构化的代码审查反馈。\n\n"
        f"## 分支: {branch}\n\n"
    )
    if log_result and "[错误]" not in log_result:
        review_prompt += f"## 最近提交\n```\n{log_result[:500]}\n```\n\n"
    if diff_result and "[错误]" not in diff_result:
        review_prompt += f"## 变更统计\n```\n{diff_result[:500]}\n```\n\n"
    review_prompt += (
        f"## 完整 Diff\n```\n{full_diff[:8000]}\n```\n\n"
        f"## 审查要求\n"
        f"1. 逐文件分析变更的意图和质量\n"
        f"2. 标出潜在问题：bug、安全漏洞、性能问题\n"
        f"3. 检查错误处理是否完善\n"
        f"4. 给出改进建议\n"
        f"5. 用中文输出\n"
    )

    return CommandResult(task_override=review_prompt)


@_register("/diff", "Show uncommitted changes")
def cmd_diff(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    """显示未提交的代码变更（交互式 Diff 查看器）。"""
    from tools import run_bash

    # 获取 staged 和 unstaged diff
    staged = run_bash("git diff --cached --stat", timeout=15)
    unstaged = run_bash("git diff --stat", timeout=15)
    full_diff = run_bash("git diff HEAD", timeout=30)

    if "[错误]" in full_diff or not full_diff.strip():
        return CommandResult(text=f"{_YELLOW}没有未提交的变更{_RESET}")

    # 分段显示：先统计，再详细 diff
    lines = [f"{_CYAN}未提交变更:{_RESET}"]

    if staged.strip() and "[错误]" not in staged:
        lines.append(f"\n{_BOLD}已暂存:{_RESET}")
        lines.append(staged)

    if unstaged.strip() and "[错误]" not in unstaged:
        lines.append(f"\n{_BOLD}未暂存:{_RESET}")
        lines.append(unstaged)

    # 完整 diff（限制长度）
    lines.append(f"\n{_BOLD}完整 Diff:{_RESET}")
    diff_text = full_diff
    if len(diff_text) > 12000:
        diff_text = diff_text[:12000] + f"\n{_DIM}... (截断，共 {len(full_diff)} 字符){_RESET}"
    lines.append(diff_text)

    return CommandResult(text="\n".join(lines))


@_register("/context", "Show context usage")
def cmd_context(cmd: str, messages: list[dict], state: dict) -> CommandResult:
    """显示上下文使用情况（token 分布可视化）。"""
    from config import get

    # 计算各角色 token 估算
    system_tokens = 0
    user_tokens = 0
    assistant_tokens = 0
    tool_tokens = 0

    for msg in messages:
        content = msg.get("content", "")
        role = msg.get("role", "")
        if isinstance(content, str):
            chars = len(content)
        elif isinstance(content, list):
            chars = sum(len(str(b)) for b in content if isinstance(b, dict))
        else:
            chars = 0
        # 粗略估算：4 字符 ≈ 1 token
        est = chars // 4
        if role == "user":
            user_tokens += est
        elif role == "assistant":
            assistant_tokens += est
        else:
            tool_tokens += est

    # Session 累计 token
    st = state.get("session_tokens", {"input": 0, "output": 0})
    session_input = st.get("input", 0)
    session_output = st.get("output", 0)
    session_total = session_input + session_output

    total = system_tokens + user_tokens + assistant_tokens + tool_tokens
    model = get("model", "")

    # 上下文窗口大小估算
    ctx_window = 200000  # 默认
    if "haiku" in model.lower():
        ctx_window = 200000
    elif "sonnet" in model.lower() or "opus" in model.lower():
        ctx_window = 200000

    pct = min(total / ctx_window * 100, 100) if ctx_window else 0

    # ASCII 进度条
    bar_width = 40
    filled = int(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)

    lines = [
        f"{_CYAN}上下文使用情况:{_RESET}",
        f"",
        f"  [{_G}{bar}{_R}] {_BOLD}{pct:.1f}%{_RESET}  ({total:,} / {ctx_window:,} est. tokens)",
        f"",
        f"  {_BOLD}消息分布:{_RESET}",
        f"    User:      {user_tokens:>8,} tokens",
        f"    Assistant: {assistant_tokens:>8,} tokens",
        f"    Tool:      {tool_tokens:>8,} tokens",
        f"",
        f"  {_BOLD}API 实际用量:{_RESET}",
        f"    Input:  {session_input:>8,} tokens",
        f"    Output: {session_output:>8,} tokens",
        f"    Total:  {session_total:>8,} tokens",
        f"",
        f"  消息数: {len(messages)}  模型: {model}",
    ]
    if pct > 80:
        lines.append(f"\n  {_YELLOW}⚠ 上下文使用超过 80%，建议 /compact 压缩{_RESET}")

    return CommandResult(text="\n".join(lines))


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
        # 渲染历史对话
        if messages:
            from tui import _render_history
            _render_history(messages)
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
