"""配置管理：支持配置文件 + 环境变量覆盖。"""

import json
import os
from pathlib import Path
from typing import Any

# 配置文件搜索路径（优先级从高到低）
_CONFIG_PATHS = [
    Path(".octopus") / "config.json",   # 项目级
    Path.home() / ".octopus" / "config.json",  # 用户级
]

# 默认配置
_DEFAULTS: dict[str, Any] = {
    "model": "deepseek-v4-flash",
    "models": {},           # 模型别名映射，如 {"sonnet": "claude-sonnet-4-20250514"}
    "default_model": "",    # 默认使用的模型别名
    "max_tokens": 8096,
    "max_iterations": 20,
    "api_key": "",
    "base_url": "",
    "permissions": "confirm",  # auto-approve | confirm | deny
    "dangerous_commands": [
        "rm -rf", "rm -r", "rmdir",
        "git push --force", "git push -f",
        "git reset --hard", "git clean",
        "drop ", "delete from",
        "mkfs", "dd if=",
    ],
    "context_threshold": 120_000,
    "mcp_servers": {},  # {"name": {"command": "...", "args": [...], "env": {}}}
}

_config_cache: dict[str, Any] | None = None


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
    """获取完整配置（合并默认值 + 配置文件 + 环境变量）。"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    cfg = dict(_DEFAULTS)
    cfg.update(_load_config_file())

    # 环境变量覆盖
    env_map = {
        "OCTOPUS_MODEL": "model",
        "OCTOPUS_API_KEY": "api_key",
        "OCTOPUS_BASE_URL": "base_url",
        "OCTOPUS_MAX_TOKENS": ("max_tokens", int),
        "OCTOPUS_MAX_ITERATIONS": ("max_iterations", int),
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
    return cfg


def get(key: str, default: Any = None) -> Any:
    """获取单个配置值。"""
    return _get_config().get(key, default)


def get_all() -> dict[str, Any]:
    """获取完整配置。"""
    return dict(_get_config())


def set_value(key: str, value: Any):
    """运行时修改配置并持久化到用户配置文件。"""
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
    global _config_cache
    _config_cache = None


def is_dangerous(command: str) -> bool:
    """检查命令是否包含危险操作模式。"""
    dangerous_patterns = get("dangerous_commands", [])
    cmd_lower = command.lower().strip()
    return any(cmd_lower.startswith(p) or f" {p}" in cmd_lower
               for p in dangerous_patterns)


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


def get_models() -> dict[str, str]:
    """获取配置的模型列表，返回 {alias: model_name}。"""
    models = get("models", {})
    if not models:
        # 没有配置模型列表时，返回当前模型自身
        current = get("model")
        return {current: current}
    return models


def resolve_model(name: str) -> str:
    """将别名解析为实际模型名。找不到时返回原名。"""
    models = get("models", {})
    # 先查别名
    if name in models:
        return models[name]
    # 再查反向映射（别名本身是模型名）
    for alias, model_name in models.items():
        if model_name == name or alias == name:
            return model_name
    return name


def switch_model(name: str) -> str:
    """切换模型并返回实际模型名。"""
    resolved = resolve_model(name)
    set_value("model", resolved)
    return resolved
