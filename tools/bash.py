"""Bash 工具：执行 shell 命令，实时流式输出，工作目录持久化。"""

import os
import signal
import subprocess
import threading
import uuid
import time

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


# 后台任务追踪
_background_tasks: dict[str, dict] = {}
_BG_TTL = 300  # 完成后 5 分钟清理
_BG_MAX_TASKS = 50  # 最多同时追踪的后台任务数


def _cleanup_bg_tasks():
    """清理已超时的后台任务条目。"""
    now = time.time()
    expired = [
        tid for tid, t in _background_tasks.items()
        if t.get("status") != "running"
        and t.get("completed_at", now) < now - _BG_TTL
    ]
    for tid in expired:
        del _background_tasks[tid]


def get_background_tasks() -> dict[str, dict]:
    """返回所有后台任务状态。"""
    _cleanup_bg_tasks()
    return _background_tasks


def run_bash(command: str, timeout: int = 120, output_fn=None,
             run_in_background: bool = False) -> str:
    if run_in_background:
        _cleanup_bg_tasks()
        if len(_background_tasks) >= _BG_MAX_TASKS:
            raise ToolError(f"后台任务数量已达上限 ({_BG_MAX_TASKS})，请等待部分任务完成")
        task_id = uuid.uuid4().hex[:12]
        cmd_preview = command[:80] + ("..." if len(command) > 80 else "")
        _background_tasks[task_id] = {
            "id": task_id,
            "command": command,
            "status": "running",
            "started_at": time.time(),
            "output": "",
            "exit_code": None,
        }
        cwd = get_cwd()

        def _bg_worker():
            from tools.state import set_active_state
            parent_state = get_state()
            set_active_state(parent_state)
            try:
                try:
                    proc = subprocess.Popen(
                        command, shell=True, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True, bufsize=1,
                        preexec_fn=os.setsid, cwd=cwd,
                    )
                    lines = []
                    timed_out = False

                    def _kill_on_timeout():
                        nonlocal timed_out
                        timed_out = True
                        _kill_proc_group(proc)

                    timer = threading.Timer(timeout, _kill_on_timeout)
                    timer.daemon = True
                    timer.start()
                    try:
                        for line in proc.stdout:
                            lines.append(line)
                        proc.wait(timeout=5)
                    finally:
                        timer.cancel()

                    if timed_out:
                        _background_tasks[task_id]["status"] = "timeout"
                        _background_tasks[task_id]["output"] = f"[超时 {timeout}s]"
                        _background_tasks[task_id]["completed_at"] = time.time()
                    else:
                        _update_cwd(command)
                        output = "".join(lines).strip() or "(no output)"
                        if proc.returncode != 0:
                            output += f"\n[exit code: {proc.returncode}]"
                        _background_tasks[task_id]["status"] = "completed"
                        _background_tasks[task_id]["output"] = output
                        _background_tasks[task_id]["exit_code"] = proc.returncode
                        _background_tasks[task_id]["completed_at"] = time.time()
                except Exception as e:
                    _background_tasks[task_id]["status"] = "error"
                    _background_tasks[task_id]["output"] = str(e)
                    _background_tasks[task_id]["completed_at"] = time.time()

                # 通知 TUI（通过 output_fn 注入事件）
                if output_fn:
                    try:
                        output_fn("background_task", _background_tasks[task_id]["output"], {
                            "task_id": task_id,
                            "command": cmd_preview,
                            "status": _background_tasks[task_id]["status"],
                            "exit_code": _background_tasks[task_id].get("exit_code"),
                        })
                    except Exception:
                        pass
            finally:
                set_active_state(None)

        t = threading.Thread(target=_bg_worker, daemon=True)
        t.start()
        return f"[后台任务 {task_id}] 正在执行: {cmd_preview}"

    try:
        proc = subprocess.Popen(
            command, shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
            preexec_fn=os.setsid, cwd=get_cwd(),
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
        _update_cwd(command)
        output = "".join(lines).strip()
        if proc.returncode != 0:
            output += f"\n[exit code: {proc.returncode}]"
        return output or "(no output)"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))
