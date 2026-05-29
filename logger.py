"""轻量级日志基础设施。"""

import logging
import os
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

    # 文件 handler
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _logger.addHandler(fh)

    return _logger
