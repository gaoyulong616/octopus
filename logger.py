"""可配置的日志基础设施。

通过 config.get("log_*") 提供配置化支持：
  - log_level: DEBUG/INFO/WARNING/ERROR，默认 INFO
  - log_file: 日志文件路径，None 自动 ~/.octopus/octopus.log
  - log_max_bytes: 日志轮转大小，默认 10MB
  - log_backup_count: 保留的备份文件数，默认 5
  - log_console: 是否同时输出到 stderr，默认 false
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path.home() / ".octopus"
_DEFAULT_LOG_FILE = _LOG_DIR / "octopus.log"

_logger: logging.Logger | None = None


def log(msg: str, *args: object) -> None:
    """便捷函数，直接写一条 INFO 日志。支持 printf 风格格式化。"""
    if args:
        get_logger().info(msg, *args)
    else:
        get_logger().info(msg)


def get_logger() -> logging.Logger:
    """获取 octopus logger（首次调用时按配置初始化）。"""
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("octopus")

    # 防止重复添加 handler（同一进程多次调用）
    if _logger.handlers:
        return _logger

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 从配置读取日志设置（延迟导入，避免循环依赖）
    try:
        from config import get as _get_config

        level_name = (_get_config("log_level") or "INFO").upper()
        log_file = _get_config("log_file") or str(_DEFAULT_LOG_FILE)
        max_bytes = int(_get_config("log_max_bytes") or 10 * 1024 * 1024)
        backup_count = int(_get_config("log_backup_count") or 5)
        console = bool(_get_config("log_console") or False)
    except Exception:
        level_name = "INFO"
        log_file = str(_DEFAULT_LOG_FILE)
        max_bytes = 10 * 1024 * 1024
        backup_count = 5
        console = False

    level = getattr(logging, level_name, logging.INFO)
    _logger.setLevel(logging.DEBUG)  # 全局 DEBUG，由 handler 控制实际级别

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler（带轮转）
    fh = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)
    _logger.addHandler(fh)

    # 控制台 handler（可选）
    if console:
        import sys

        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(level)
        sh.setFormatter(fmt)
        _logger.addHandler(sh)

    return _logger
