"""Bash 工具：执行 shell 命令，实时流式输出，工作目录持久化。

多用户支持：
- 后台任务按 user_id 隔离存储
- 支持 Bubblewrap 沙箱隔离（user_root 非空时启用）
- 目录边界检查

阶段二沙箱：
- 使用 Bubblewrap 创建 namespace 隔离的运行环境
- 每个用户的 bash 命令在独立的空间内执行
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import uuid
import time
from pathlib import Path

from tools.state import get_state
from tools.exceptions import ToolError


def get_cwd() -> str:
    return get_state().get_cwd()


def set_cwd(path: str):
    get_state().set_cwd(path)


def _update_cwd(command: str):
    """追踪 bash 命令中的 cd 操作，持久化工作目录。"""
    get_state().update_cwd(command)


def _kill_proc_group(proc):
    """安全终止进程组：先 SIGTERM，等待后 SIGKILL。"""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


# 后台任务按用户隔离：{user_id: {task_id: task}}
_background_tasks: dict[str, dict[str, dict]] = {}
_BG_TTL = 300  # 完成后 5 分钟清理
_BG_MAX_TASKS = 50  # 最多同时追踪的后台任务数


def _get_user_id() -> str:
    """获取当前 AgentState 的 user_id。"""
    state = get_state()
    return getattr(state, "user_id", "") or ""


def _cleanup_bg_tasks(user_id: str):
    """清理已超时的后台任务条目。"""
    now = time.time()
    tasks = _background_tasks.get(user_id, {})
    expired = [
        tid for tid, t in tasks.items()
        if t.get("status") != "running"
        and t.get("completed_at", now) < now - _BG_TTL
    ]
    for tid in expired:
        del tasks[tid]
    if tasks:
        _background_tasks[user_id] = tasks


def get_background_tasks(user_id: str = "") -> dict[str, dict]:
    """返回指定用户的后台任务状态。"""
    uid = user_id or _get_user_id()
    _cleanup_bg_tasks(uid)
    return _background_tasks.get(uid, {})


def _is_bwrap_available() -> bool:
    """检查 Bubblewrap 是否可用。"""
    return shutil.which("bwrap") is not None


def _build_bwrap_command(command: str, cwd: str, user_root: str) -> list[str]:
    """构建 Bubblewrap 命令，实现进程级沙箱隔离。"""
    ws_dir = user_root  # 用户根目录作为 /workspace

    cmd = ["bwrap"]

    # Namespace 隔离
    cmd += [
        "--unshare-user",
        "--unshare-ipc",
        "--unshare-pid",
        "--new-session",
    ]

    # 根文件系统（只读）
    cmd += [
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/etc/ssl", "/etc/ssl",
        "--ro-bind", "/etc/passwd", "/etc/passwd",
        "--ro-bind", "/etc/group", "/etc/group",
        "--ro-bind", "/etc/nsswitch.conf", "/etc/nsswitch.conf",
        "--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf",
    ]

    # 用户可写目录
    cmd += ["--bind", ws_dir, "/workspace"]

    # 临时目录（独立）
    cmd += ["--tmpfs", "/tmp", "--tmpfs", "/var/tmp"]

    # proc 和 dev
    cmd += ["--proc", "/proc", "--dev", "/dev"]

    # 隐藏主目录（用户目录已挂载，其他 home 内容隐藏）
    home = str(Path.home())
    if home != user_root:
        cmd += ["--ro-bind-try", home, home]

    # 环境变量（隔离）
    cmd += [
        "--setenv", "HOME", "/workspace",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "USER", "octopus",
        "--setenv", "LANG", "en_US.UTF-8",
        "--unsetenv", "OCTOPUS_API_KEY",
        "--unsetenv", "API_KEY",
    ]

    # 工作目录
    cmd += ["--chdir", cwd]

    # 执行命令
    cmd += ["bash", "-c", command]

    return cmd


def _run_bash_sandboxed(command: str, cwd: str, user_root: str, timeout: int, output_fn=None) -> str:
    """使用 Bubblewrap 沙箱执行命令。"""
    bwrap_cmd = _build_bwrap_command(command, cwd, user_root)

    proc = subprocess.Popen(
        bwrap_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    lines = []
    try:
        for line in proc.stdout:
            lines.append(line)
            if output_fn:
                output_fn("stream", line.rstrip("\n"))
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        return f"[超时 {timeout}s]"
    except KeyboardInterrupt:
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        raise

    output = "".join(lines).strip()
    if proc.returncode != 0:
        output += f"\n[exit code: {proc.returncode}]"
    return output or "(no output)"


def _run_bash_native(command: str, cwd: str, timeout: int, output_fn=None) -> str:
    """普通 subprocess 执行（环境变量已过滤）。"""
    env = os.environ.copy()
    env.pop("OCTOPUS_API_KEY", None)
    env.pop("API_KEY", None)

    proc = subprocess.Popen(
        command, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
        cwd=cwd, env=env,
        preexec_fn=os.setsid,
    )

    lines = []
    try:
        for line in proc.stdout:
            lines.append(line)
            if output_fn:
                output_fn("stream", line.rstrip("\n"))
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_proc_group(proc)
        return f"[错误] 命令超时（{timeout}s）"
    except KeyboardInterrupt:
        _kill_proc_group(proc)
        raise
    except Exception as e:
        raise ToolError(str(e))

    output = "".join(lines).strip()
    if proc.returncode != 0:
        output += f"\n[exit code: {proc.returncode}]"
    return output or "(no output)"


def run_bash(command: str, timeout: int = 120, output_fn=None,
             run_in_background: bool = False) -> str:
    """执行 bash 命令，支持沙箱隔离。"""
    state = get_state()
    user_id = getattr(state, "user_id", "") or ""
    user_root = getattr(state, "user_root", "") or ""
    cwd = state.get_cwd()

    if run_in_background:
        # 后台任务隔离
        if user_id not in _background_tasks:
            _background_tasks[user_id] = {}
        tasks = _background_tasks[user_id]
        _cleanup_bg_tasks(user_id)
        if len(tasks) >= _BG_MAX_TASKS:
            raise ToolError(f"后台任务数量已达上限 ({_BG_MAX_TASKS})，请等待部分任务完成")
        task_id = uuid.uuid4().hex[:12]
        cmd_preview = command[:80] + ("..." if len(command) > 80 else "")
        tasks[task_id] = {
            "id": task_id,
            "command": command,
            "status": "running",
            "started_at": time.time(),
            "output": "",
            "exit_code": None,
        }

        def _bg_worker():
            from tools.state import set_active_state
            parent_state = get_state()
            set_active_state(parent_state)
            try:
                try:
                    if user_root and _is_bwrap_available():
                        output = _run_bash_sandboxed(command, cwd, user_root, timeout)
                    else:
                        output = _run_bash_native(command, cwd, timeout)
                except ToolError as e:
                    output = f"[错误] {e}"
                except Exception as e:
                    output = f"[错误] {e}"

                tasks[task_id]["status"] = "completed"
                tasks[task_id]["output"] = output
                tasks[task_id]["completed_at"] = time.time()

                # 通知
                if output_fn:
                    try:
                        output_fn("background_task", output, {
                            "task_id": task_id,
                            "command": cmd_preview,
                            "status": "completed",
                        })
                    except Exception:
                        pass
            finally:
                set_active_state(None)

        t = threading.Thread(target=_bg_worker, daemon=True)
        t.start()
        return f"[后台任务 {task_id}] 正在执行: {cmd_preview}"

    # 前台执行
    if user_root and _is_bwrap_available():
        return _run_bash_sandboxed(command, cwd, user_root, timeout, output_fn)
    else:
        return _run_bash_native(command, cwd, timeout, output_fn)
