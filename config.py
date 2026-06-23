"""配置管理：支持配置文件 + 环境变量覆盖 + Hooks 系统。"""

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable

# 配置文件搜索路径（优先级从高到低）
_CONFIG_PATHS = [
    Path(".octopus") / "config.local.json",  # 项目本地级（gitignored，机器特定）
    Path(".octopus") / "config.json",  # 项目级
    Path.home() / ".octopus" / "config.json",  # 用户级
]

# 默认配置（api_key、base_url、model 为必配项，无默认值）
_DEFAULTS: dict[str, Any] = {
    "api_key": None,
    "base_url": None,
    "model": None,
    "provider": None,  # 当前活跃提供商名（对应 providers 中的 key）
    "providers": {},  # {"name": {"base_url": "...", "api_key": "...", "models": [...]}}
    "max_tokens": 8096,
    "max_iterations": 50,  # 单次 run_agent 最大迭代次数（防 LLM 陷入 tool→result→tool 死循环）
    "tool_failure_threshold": 3,  # 同一 (tool, input) 连续失败次数上限，超过即熔断
    "permissions": "confirm",  # auto-approve | confirm | deny
    "thinking_budget": None,  # Extended Thinking token budget, e.g. 10000
    "bash_timeout": 120,  # Bash 命令超时秒数
    "dangerous_commands": [
        "rm -rf",
        "rm -r",
        "rmdir",
        "git push --force",
        "git push -f",
        "git reset --hard",
        "git clean",
        "drop ",
        "delete from",
        "mkfs",
        "dd if=",
    ],
    "context_threshold": None,  # 手动覆盖压缩阈值（字符数）。None=根据模型上下文窗口自动计算
    "mcp_servers": {},  # {"name": {"command": "...", "args": [...], "env": {}}}
    "cleanup_period_days": 300,  # 会话自动清理天数
    "hooks": {},  # {"pre_tool_call": ["cmd1"], "post_tool_call": ["cmd2"]}
    "permission_rules": [],  # [{"tool": "bash", "allow": "npm test"}, ...]
    "statusline": "{model}  |  {git_branch}  |  {cwd}  |  {tokens} tokens",  # 状态栏模板
    "show_thinking": True,  # 默认展示 thinking 块
    # ── 日志配置 ──
    "log_level": "INFO",  # DEBUG / INFO / WARNING / ERROR
    "log_file": None,  # 日志文件路径，None=~/.octopus/octopus.log
    "log_max_bytes": 10485760,  # 日志轮转大小（10MB）
    "log_backup_count": 5,  # 保留的备份文件数
    "log_console": False,  # 是否同时输出到 stderr
    "video_directory": str(Path.home() / "videos"),
    "music_directory": str(Path.home() / "music"),
    "image_directory": str(Path.home() / "images"),
    "docs_directory": str(Path.home() / "docs"),
    # Web 多会话并行活跃：空闲会话 TTL 淘汰（秒），超过此时间无事件则清理
    "database_url": None,  # SQLAlchemy 数据库连接串，None=SQLite 默认路径
    "web_session_idle_timeout": 3600,
    # 活跃会话池上限（超过则按 LRU 淘汰最久未活跃的）
    "web_max_active_sessions": 8,
    # 外部提醒开关（Phase 4）
    "notify_sound": True,
    "notify_response_complete": True,
    "notify_ask_user_question": True,
    "notify_confirm_request": True,
    "notify_error": True,
    "notify_plan_submitted": True,
    "workdir_base": None,  # WebUI 每会话工作目录根路径。None=os.getcwd()
}

def get_model_provider(model: str | None = None) -> str:
    """获取 LLM Provider 名称。

    优先级：配置 > "anthropic" 默认。
    """
    configured = get("provider")
    if configured:
        return configured
    return "anthropic"

_config_cache: dict[str, Any] | None = None
_config_cache_mtime: float = 0.0


def _latest_config_mtime() -> float:
    """返回最近修改的配置文件的 mtime。"""
    mtime = 0.0
    for path in _CONFIG_PATHS:
        try:
            if path.exists():
                mtime = max(mtime, path.stat().st_mtime)
        except OSError:
            pass
    return mtime


def _load_config_file() -> dict[str, Any]:
    """从配置文件加载，优先项目级 > 用户级。"""
    merged: dict[str, Any] = {}
    for path in reversed(_CONFIG_PATHS):
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    merged.update(json.load(f))
            except (json.JSONDecodeError, OSError):
                continue
    return merged


def _get_config() -> dict[str, Any]:
    """获取完整配置（合并默认值 + 配置文件 + 环境变量）。
    自动检测配置文件变更并刷新缓存。
    """
    global _config_cache, _config_cache_mtime

    latest = _latest_config_mtime()
    if _config_cache is not None and latest <= _config_cache_mtime:
        return _config_cache

    cfg = dict(_DEFAULTS)
    cfg.update(_load_config_file())

    # 环境变量覆盖
    env_map = {
        "OCTOPUS_DATABASE_URL": "database_url",
        "OCTOPUS_MODEL": "model",
        "OCTOPUS_API_KEY": "api_key",
        "OCTOPUS_BASE_URL": "base_url",
        "OCTOPUS_HOST": "host",
        "OCTOPUS_MAX_TOKENS": ("max_tokens", int),
        "OCTOPUS_PERMISSIONS": "permissions",
    }
    for env_key, mapping in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            if isinstance(mapping, tuple):
                key, cast = mapping
                try:
                    cfg[key] = cast(val)
                except (ValueError, TypeError):
                    pass
            else:
                cfg[mapping] = val

    _config_cache = cfg
    _config_cache_mtime = latest
    return cfg


def get(key: str, default: Any = None) -> Any:
    """获取单个配置值。

    对 api_key 和 base_url，如果配置了 providers 且有活跃 provider，
    则从 providers[provider] 中读取，实现按提供商切换凭据。
    """
    cfg = _get_config()
    if key in ("api_key", "base_url", "host"):
        providers = cfg.get("providers")
        provider_name = cfg.get("provider")
        if providers and provider_name and provider_name in providers:
            val = providers[provider_name].get(key)
            if val is not None:
                return val
    return cfg.get(key, default)


def get_all() -> dict[str, Any]:
    """获取完整配置。"""
    return dict(_get_config())


def set_value(key: str, value: Any):
    """运行时修改配置并持久化到用户配置文件。"""
    value = validate_value(key, value)
    cfg = _get_config()
    cfg[key] = value
    # 持久化到用户级配置文件
    user_path = Path.home() / ".octopus" / "config.json"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if user_path.exists():
        try:
            with open(user_path, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    existing[key] = value
    with open(user_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def invalidate():
    """清除配置缓存，下次访问重新加载。"""
    global _config_cache, _config_cache_mtime
    _config_cache = None
    _config_cache_mtime = 0.0


def is_dangerous(command: str) -> bool:
    """检查命令是否包含危险操作模式。

    增强版：处理命令链、子 shell、管道注入、引号/多空格绕过等方式。
    """
    import re as _re

    dangerous_patterns = get("dangerous_commands", [])
    if not dangerous_patterns:
        return False

    # 归一化：tab/newline/多空格 → 单空格，方便后续匹配
    def _normalize(s: str) -> str:
        return _re.sub(r"\s+", " ", s).strip()

    cmd = _normalize(command)
    cmd_lower = cmd.lower()

    def _check(text: str) -> bool:
        text = _normalize(text).lower()
        if not text:
            return False
        # 引号剥离：`r""m -rf` → `rm -rf`
        text = _re.sub(r'["\']+', "", text)
        # 多空格再归一
        text = _re.sub(r"\s+", " ", text).strip()
        for p in dangerous_patterns:
            p_norm = _normalize(p).lower()
            if not p_norm:
                continue
            if text == p_norm or text.startswith(p_norm + " ") or (" " + p_norm) in (" " + text):
                return True
        return False

    # Quick check: direct pattern match on whole command
    if _check(cmd):
        return True

    # Split on chain operators and check each part
    parts = _re.split(r"[;\|]|&&|\|\|", cmd_lower)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Strip subshell markers
        part = part.lstrip("$(").rstrip(")")
        # Strip quotes from command name
        part = part.strip("\"'").strip()
        if _check(part):
            return True
        # 同时检查归一后的形式
        if _check(_re.sub(r"\s+", " ", part)):
            return True

    # Check for pipe-to-shell patterns
    pipe_dangerous = ["| bash", "| sh", "| zsh", "| python", "| perl", "| ruby", "| sudo ", "| su "]
    for pattern in pipe_dangerous:
        if pattern in cmd_lower:
            return True

    # Check for subshell execution patterns
    subshell_patterns = [r"\$\(", r"`"]
    for sp in subshell_patterns:
        if sp in cmd:
            # If subshell contains dangerous commands, flag it
            for p in dangerous_patterns:
                if p in cmd_lower:
                    return True

    # Check for base64 decode pipe (common bypass)
    if "base64" in cmd_lower and ("| bash" in cmd_lower or "| sh" in cmd_lower):
        return True

    # Check for -- separator (often used to bypass flag parsers)
    if _re.search(r"\brm\s+-[rRf]+\s+--\s*/", cmd_lower):
        return True

    return False


# ── 目录信任管理 ──

_TRUSTED_FILE = Path.home() / ".octopus" / "trusted_dirs.json"


def _load_trusted_dirs() -> list[str]:
    try:
        with open(_TRUSTED_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _save_trusted_dirs(dirs: list[str]):
    _TRUSTED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_TRUSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(dirs, f, ensure_ascii=False, indent=2)


def is_trusted_dir(cwd: str) -> bool:
    """检查目录是否已被信任（支持子目录继承）。"""
    cwd = str(Path(cwd).resolve())
    for d in _load_trusted_dirs():
        if cwd == d or cwd.startswith(d + os.sep):
            return True
    return False


def trust_dir(cwd: str):
    """将目录加入信任列表。"""
    cwd = str(Path(cwd).resolve())
    dirs = _load_trusted_dirs()
    if cwd not in dirs:
        dirs.append(cwd)
        _save_trusted_dirs(dirs)


def _model_name(m) -> str:
    """从 models 列表项中提取模型名。兼容字符串和 dict 两种格式。"""
    if isinstance(m, str):
        return m
    if isinstance(m, dict):
        return m.get("name", "")
    return str(m)


def _model_config(m) -> dict:
    """从 models 列表项中提取完整配置。字符串返回空 dict。"""
    if isinstance(m, dict):
        return m
    return {}


def get_models() -> list[tuple[str, str]]:
    """获取所有可用模型，返回 [(model_name, provider_name), ...]。

    从 providers 配置中扫描所有模型。无 providers 时返回当前模型自身。
    models 支持两种格式：
      - 字符串数组: ["deepseek-v4-flash"]
      - 对象数组:   [{"name": "deepseek-v4-flash", "context_window": 128000}]
    """
    providers = get("providers")
    if providers and isinstance(providers, dict):
        result: list[tuple[str, str]] = []
        for pname, pcfg in providers.items():
            if not isinstance(pcfg, dict):
                continue
            for m in pcfg.get("models", []):
                name = _model_name(m)
                if name:
                    result.append((name, pname))
        return result
    # 无 providers 配置时，返回当前模型自身
    current = get("model")
    if current:
        return [(current, "")]
    return []


def get_context_window(model_name: str | None = None) -> int:
    """获取指定模型的上下文窗口大小（tokens）。

    查找顺序：providers 中该模型的 context_window 字段 → 默认 200000。
    """
    if model_name is None:
        model_name = get("model")
    if not model_name:
        return 200_000

    providers = get("providers")
    if not providers or not isinstance(providers, dict):
        return 200_000

    for pname, pcfg in providers.items():
        if not isinstance(pcfg, dict):
            continue
        for m in pcfg.get("models", []):
            mc = _model_config(m)
            if mc.get("name") == model_name and mc.get("context_window"):
                return int(mc["context_window"])
    return 200_000


def switch_model(name: str) -> tuple[str, str | None]:
    """切换模型，自动切换对应的提供商凭据。

    支持格式：
      "model-name"           — 自动匹配提供商（唯一时；重复时报错）
      "provider/model-name"  — 显式指定提供商

    Returns:
        (model_name, provider_name) 成功

    Raises:
        ValueError: 模型不存在、提供商不存在、或模型有歧义
    """
    # 解析 provider/model 格式
    provider_hint = None
    model_name = name
    if "/" in name:
        provider_hint, model_name = name.split("/", 1)

    cfg = _get_config()
    providers = cfg.get("providers")
    if not providers or not isinstance(providers, dict):
        cfg["model"] = model_name
        return (model_name, None)

    all_models = get_models()

    # 显式指定提供商
    if provider_hint:
        if provider_hint not in providers:
            available = ", ".join(sorted(providers.keys()))
            raise ValueError(f"提供商 '{provider_hint}' 不存在。可用: {available}")
        pcfg = providers[provider_hint]
        model_names = [_model_name(m) for m in pcfg.get("models", [])]
        if isinstance(pcfg, dict) and model_name in model_names:
            cfg["provider"] = provider_hint
            cfg["model"] = model_name
            return (model_name, provider_hint)
        # 提供商存在但模型不在其列表中
        raise ValueError(f"提供商 '{provider_hint}' 下没有模型 '{model_name}'。可用: {', '.join(model_names)}")

    # 自动匹配：找到所有拥有该模型的提供商
    matched = [
        pname
        for pname, pcfg in providers.items()
        if isinstance(pcfg, dict) and model_name in [_model_name(m) for m in pcfg.get("models", [])]
    ]
    if len(matched) == 1:
        cfg["provider"] = matched[0]
        cfg["model"] = model_name
        return (model_name, matched[0])
    elif len(matched) > 1:
        opts = ", ".join(f"{p}/{model_name}" for p in matched)
        raise ValueError(f"模型 '{model_name}' 存在于多个提供商，请指定: {opts}")
    else:
        # 没找到
        available = sorted(set(m for m, _ in all_models))
        raise ValueError(f"模型 '{model_name}' 不存在。可用: {', '.join(available)}")


# ── 配置校验 ──

_VALIDATORS: dict[str, Callable] = {}


def _setup_validators():
    """延迟初始化校验器（避免模块级导入问题）。"""
    if _VALIDATORS:
        return

    def _positive_int(key):
        def validate(v):
            n = int(v)
            if n <= 0:
                raise ValueError(f"{key} 必须是正整数，得到: {v}")
            return n

        return validate

    def _one_of(choices):
        def validate(v):
            if v not in choices:
                raise ValueError(f"必须是 {choices} 之一，得到: {v}")
            return v

        return validate

    def _non_empty(key):
        def validate(v):
            s = str(v).strip()
            if not s:
                raise ValueError(f"{key} 不能为空")
            return s

        return validate

    def _base_url(v):
        if not str(v).startswith("http"):
            raise ValueError(f"base_url 必须以 http 开头: {v}")
        return v

    _VALIDATORS.update(
        {
            "max_tokens": _positive_int("max_tokens"),
            "max_iterations": _positive_int("max_iterations"),
            "tool_failure_threshold": _positive_int("tool_failure_threshold"),
            "bash_timeout": _positive_int("bash_timeout"),
            "context_threshold": _positive_int("context_threshold"),
            "permissions": _one_of(("auto-approve", "confirm", "deny")),
            "api_key": _non_empty("api_key"),
            "model": _non_empty("model"),
            "base_url": _base_url,
        }
    )


def validate_value(key: str, value: Any) -> Any:
    """校验配置值，返回校验后的值或抛出 ValueError。"""
    _setup_validators()
    validator = _VALIDATORS.get(key)
    if validator:
        return validator(value)
    return value


def validate_config() -> list[str]:
    """校验当前配置，返回问题列表（空列表表示全部通过）。"""
    _setup_validators()
    issues: list[str] = []
    for key, validator in _VALIDATORS.items():
        value = get(key)
        if value is None:
            continue
        try:
            validator(value)
        except (ValueError, TypeError) as e:
            issues.append(f"  {key}: {e}")

    # MCP servers command 存在性
    mcp_servers = get("mcp_servers", {}) or {}
    for sname, scfg in mcp_servers.items():
        if not isinstance(scfg, dict):
            continue
        cmd = scfg.get("command")
        if cmd:
            import shutil as _shutil

            if not _shutil.which(cmd):
                issues.append(f"  mcp_servers.{sname}: command '{cmd}' 不在 PATH 中")

    return issues


# ── Hooks 系统 ──

# 标准化事件名（PascalCase，与 Claude Code harness 对齐）。
# 同时兼容旧 snake_case 名：pre_tool_call → PreToolUse、post_tool_call → PostToolUse。
HOOK_EVENTS = (
    "SessionStart",  # 会话启动（创建/恢复后，进入主循环前）
    "UserPromptSubmit",  # 用户提交输入前（可修改/拦截输入）
    "PreToolUse",  # 工具调用前（可阻止执行）
    "PostToolUse",  # 工具调用后
    "Notification",  # 系统通知（权限请求、错误等）
    "Stop",  # 主 Agent 完成一次完整回复后
    "SubagentStop",  # 子 Agent 完成任务后
    "PreCompact",  # 上下文压缩前
)

# 旧名 → 新名（向后兼容）
_HOOK_ALIASES = {
    "pre_tool_call": "PreToolUse",
    "post_tool_call": "PostToolUse",
}


def _hook_keys_for(event: str) -> set[str]:
    """给定一个 event，返回所有可能的配置 key（新名 + 旧名双向匹配）。"""
    keys = {event}
    if event in _HOOK_ALIASES:
        keys.add(_HOOK_ALIASES[event])
    # 反向查找：如果 event 是新名，加入所有指向它的旧名
    for old, new in _HOOK_ALIASES.items():
        if new == event:
            keys.add(old)
    return keys


def get_hooks(event: str) -> list[str]:
    """获取指定事件的 hook 命令列表。兼容旧 snake_case 事件名。

    双向兼容：
    - 调用 get_hooks("PreToolUse") 会同时拿到 hooks["PreToolUse"] + hooks["pre_tool_call"]
    - 调用 get_hooks("pre_tool_call") 同理
    """
    hooks = get("hooks", {})
    if not isinstance(hooks, dict):
        return []
    out: list[str] = []
    seen: set = set()
    for key in _hook_keys_for(event):
        for cmd in hooks.get(key, []):
            if cmd not in seen:
                seen.add(cmd)
                out.append(cmd)
    return out


def run_hooks(event: str, context: dict | None = None) -> list[str]:
    """运行指定事件的所有 hooks。返回各 hook 的输出。"""
    commands = get_hooks(event)
    results = []
    env = dict(os.environ)
    if context:
        for k, v in context.items():
            env[f"OCTOPUS_HOOK_{k.upper()}"] = str(v)
    for cmd in commands:
        try:
            result = subprocess.run(
                shlex.split(cmd),
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                output += f"\n[hook exit code: {result.returncode}]"
            if result.stderr.strip():
                output += f"\n[stderr: {result.stderr.strip()[:200]}]"
            results.append(output)
        except subprocess.TimeoutExpired:
            results.append(f"[hook 超时: {cmd[:50]}]")
        except Exception as e:
            results.append(f"[hook 错误: {e}]")
    return results


# ── 细粒度权限规则 ──


def check_permission_rule(tool_name: str, tool_input: dict) -> str | None:
    """检查细粒度权限规则。

    Returns:
        "allow" — 明确允许
        "deny" — 明确拒绝
        None — 无匹配规则，使用默认行为
    """
    rules = get("permission_rules", [])
    if not rules or not isinstance(rules, list):
        return None

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_tool = rule.get("tool", "")
        if rule_tool and rule_tool != tool_name:
            continue

        # 匹配模式
        pattern = rule.get("pattern", "")
        if pattern:
            target = ""
            if tool_name == "bash":
                target = tool_input.get("command", "")
            elif tool_name in ("write_file", "edit_file"):
                target = tool_input.get("path", "")
            elif tool_name == "read_file":
                target = tool_input.get("path", "")

            import re

            try:
                if not re.search(pattern, target):
                    continue
            except re.error:
                continue

        action = rule.get("action", "")
        if action in ("allow", "deny"):
            return action

    return None
