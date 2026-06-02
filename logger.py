"""轻量级日志基础设施。

关键路径的日志记录：
- agent: LLM 调用、token 用量、重试
- tools: 工具执行耗时
- session: 会话创建/保存/加载
"""

from __future__ import annotations

import logging
from pathlib import Path

_LOG_DIR = Path.home() / ".octopus"
_LOG_FILE = _LOG_DIR / "octopus.log"

_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("octopus")
    _logger.setLevel(logging.DEBUG)

    # 防止重复添加 handler
    if not _logger.handlers:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        _logger.addHandler(fh)

    return _logger
