"""共享常量：ANSI 颜色、文件限制、版本号。"""

# ── 版本 ──
VERSION = "1.0.0"

# ── ANSI 转义序列 ──
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"

# ── 文件大小限制 ──
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB
