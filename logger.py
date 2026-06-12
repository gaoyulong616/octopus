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

_LOG_FMT = "%(asctime)s [%(levelname)s] %(name)s [%(session_id)s]: %(message)s"


class _SessionIdFormatter(logging.Formatter):
    """自定义 Formatter，对缺失 session_id 的 record 补默认值 '-'。"""

    def format(self, record):
        record.__dict__.setdefault("session_id", "-")
        return super().format(record)


class SessionLoggerAdapter(logging.LoggerAdapter):
    """在每条日志中注入 session_id，用于多会话并发时区分来源。"""

    def process(self, msg, kwargs):
        kwargs.setdefault("extra", {})
        kwargs["extra"]["session_id"] = self.extra.get("session_id", "-")
        return msg, kwargs


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

    fmt = _SessionIdFormatter(_LOG_FMT, datefmt="%Y-%m-%d %H:%M:%S")

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


def get_session_logger(session_id: str | None = None) -> SessionLoggerAdapter:
    """获取带 session_id 的 logger adapter。session_id 为 None 时显示 '-'。"""
    return SessionLoggerAdapter(get_logger(), {"session_id": session_id or "-"})
