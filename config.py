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
    """运行时修改配置（不写入文件）。"""
    cfg = _get_config()
    cfg[key] = value


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
