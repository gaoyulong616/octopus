"""cgroups v2 资源限制：为每个用户创建独立的 cgroup，控制 CPU/内存/进程数。

仅在 Linux 上有效，且需要写入 /sys/fs/cgroup 的权限（通常需要 root 或适当的 delegation）。
非 Linux 环境或无权限时所有函数为 no-op。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

CGROUP_ROOT = "/sys/fs/cgroup/octopus"

# 默认资源限制
DEFAULT_CPU_QUOTA = "200000"  # 2 CPU time slices (100ms each)
DEFAULT_CPU_PERIOD = "100000"
DEFAULT_MEMORY_MAX = "2G"  # 2GB
DEFAULT_PIDS_MAX = "100"


def _is_linux() -> bool:
    return os.path.exists("/proc/sys/kernel/osrelease")


def ensure_user_cgroup(user_id: str) -> str | None:
    """确保用户 cgroup 存在，返回 cgroup 路径或 None（不可用）。"""
    if not _is_linux():
        return None

    cgroup_path = f"{CGROUP_ROOT}/{user_id}"
    try:
        os.makedirs(cgroup_path, exist_ok=True)

        # 设置资源限制
        # CPU：2 cores
        cpu_max = f"{DEFAULT_CPU_QUOTA} {DEFAULT_CPU_PERIOD}"
        with open(f"{cgroup_path}/cpu.max", "w") as f:
            f.write(cpu_max)

        # 内存：2GB
        with open(f"{cgroup_path}/memory.max", "w") as f:
            f.write(DEFAULT_MEMORY_MAX)

        # 进程数：100
        with open(f"{cgroup_path}/pids.max", "w") as f:
            f.write(DEFAULT_PIDS_MAX)

        # 启用空嵌套（允许子 cgroup）
        try:
            with open(f"{cgroup_path}/cgroup.subtree_control", "w") as f:
                f.write("+cpu +memory +pids")
        except (IOError, OSError):
            pass

        return cgroup_path
    except (IOError, OSError, PermissionError):
        return None


def move_to_cgroup(pid: int, user_id: str) -> bool:
    """将进程移动到用户 cgroup，返回是否成功。"""
    if not _is_linux():
        return False

    cgroup_path = ensure_user_cgroup(user_id)
    if not cgroup_path:
        return False

    try:
        with open(f"{cgroup_path}/cgroup.procs", "w") as f:
            f.write(str(pid))
        return True
    except (IOError, OSError, PermissionError):
        return False


def is_available() -> bool:
    """检查 cgroups v2 是否可用。"""
    if not _is_linux():
        return False
    return os.access(CGROUP_ROOT, os.W_OK)


def cleanup_user_cgroup(user_id: str) -> bool:
    """清理用户 cgroup（删除所有进程后将 cgroup 删除）。"""
    if not _is_linux():
        return False

    cgroup_path = f"{CGROUP_ROOT}/{user_id}"
    try:
        # 先杀掉所有进程
        try:
            with open(f"{cgroup_path}/cgroup.procs", "r") as f:
                for line in f:
                    pid = int(line.strip())
                    try:
                        os.kill(pid, 9)
                    except (ProcessLookupError, OSError):
                        pass
        except (IOError, OSError):
            pass

        # 删除 cgroup
        os.rmdir(cgroup_path)
        return True
    except (IOError, OSError, PermissionError):
        return False
