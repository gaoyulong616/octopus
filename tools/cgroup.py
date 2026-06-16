"""cgroup 资源限制（Linux only）"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _has_cgroup_v2() -> bool:
    try:
        result = subprocess.run(
            ["stat", "-f", "%T", "/sys/fs/cgroup"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and "cgroup2fs" in result.stdout
    except Exception:
        return False


def _cgroup_path(user_id: str) -> str:
    base = "/sys/fs/cgroup"
    if _has_cgroup_v2():
        return f"{base}/octopus/{user_id}"
    return f"{base}/cpu/octopus/{user_id}"


def setup_cgroup(user_id: str, cpu_limit: float = 0.5, mem_limit_mb: int = 512):
    """为用户设置 cgroup 资源限制。"""
    try:
        cg_path = _cgroup_path(user_id)
        Path(cg_path).mkdir(parents=True, exist_ok=True)

        if _has_cgroup_v2():
            with open(f"{cg_path}/cpu.max", "w") as f:
                f.write(f"{int(cpu_limit * 100000)}\n")
            with open(f"{cg_path}/memory.max", "w") as f:
                f.write(f"{mem_limit_mb * 1024 * 1024}\n")
            with open(f"{cg_path}/cgroup.procs", "w") as f:
                f.write(f"{os.getpid()}\n")
        else:
            with open(f"{cg_path}/cpu.cfs_quota_us", "w") as f:
                f.write(f"{int(cpu_limit * 100000)}\n")
            with open(f"{cg_path}/cpu.cfs_period_us", "w") as f:
                f.write("100000\n")
            with open(f"{cg_path}/memory.limit_in_bytes", "w") as f:
                f.write(f"{mem_limit_mb * 1024 * 1024}\n")
            with open(f"{cg_path}/tasks", "w") as f:
                f.write(f"{os.getpid()}\n")
    except Exception:
        pass


def cleanup_cgroup(user_id: str):
    """清理用户的 cgroup。"""
    try:
        cg_path = _cgroup_path(user_id)
        if _has_cgroup_v2():
            with open(f"{cg_path}/cgroup.procs", "r") as f:
                for pid in f:
                    pid = pid.strip()
                    if pid:
                        with open(f"{cg_path}/../cgroup.procs", "w") as parent:
                            parent.write(pid)
            Path(cg_path).rmdir()
        else:
            with open(f"{cg_path}/tasks", "r") as f:
                for pid in f:
                    pid = pid.strip()
                    if pid:
                        with open(f"{cg_path}/../tasks", "w") as parent:
                            parent.write(pid)
            Path(cg_path).rmdir()
    except Exception:
        pass


def get_cgroup_stats(user_id: str) -> dict:
    """获取用户 cgroup 统计。"""
    try:
        cg_path = _cgroup_path(user_id)
        stats = {}
        if _has_cgroup_v2():
            if (Path(cg_path) / "cpu.stat").exists():
                with open(f"{cg_path}/cpu.stat") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 2:
                            stats[parts[0]] = int(parts[1])
            if (Path(cg_path) / "memory.stat").exists():
                with open(f"{cg_path}/memory.stat") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 2:
                            stats[parts[0]] = int(parts[1])
        else:
            if (Path(cg_path) / "cpuacct.stat").exists():
                with open(f"{cg_path}/cpuacct.stat") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 2:
                            stats[parts[0]] = int(parts[1])
            if (Path(cg_path) / "memory.stat").exists():
                with open(f"{cg_path}/memory.stat") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 2:
                            stats[parts[0]] = int(parts[1])
        return stats
    except Exception:
        return {}