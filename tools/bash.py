"""Bash 工具：执行 shell 命令，实时流式输出，工作目录持久化，支持 Bubblewrap 沙箱隔离。"""

import os
import signal
import subprocess
import threading
import uuid
import time

from tools.state import get_state
from tools.exceptions import ToolError


_BWRAP_PATH = ""


def _find_bwrap() -> str:
    global _BWRAP_PATH
    if _BWRAP_PATH:
        return _BWRAP_PATH
    for path in ["/usr/bin/bwrap", "/usr/local/bin/bwrap", "/bin/bwrap"]:
        if os.path.exists(path):
            _BWRAP_PATH = path
            return path
    try:
        result = subprocess.run(["which", "bwrap"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            _BWRAP_PATH = result.stdout.strip()
            return _BWRAP_PATH
    except Exception:
        pass
    return ""


def get_cwd() -> str:
    return get_state().get_cwd()


def set_cwd(path: str):
    get_state().set_cwd(path)


def _update_cwd(command: str):
    get_state().update_cwd(command)


def _kill_proc_group(proc):
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


_background_tasks: dict[str, dict] = {}
_BG_TTL = 300
_BG_MAX_TASKS = 50


def _cleanup_bg_tasks():
    now = time.time()
    expired = [
        tid for tid, t in _background_tasks.items()
        if t.get("status") != "running"
        and t.get("completed_at", now) < now - _BG_TTL
    ]
    for tid in expired:
        del _background_tasks[tid]


def get_background_tasks() -> dict[str, dict]:
    _cleanup_bg_tasks()
    return _background_tasks


def _build_bwrap_args(user_id: str | None) -> list[str]:
    if not user_id or not _find_bwrap():
        return []

    args = [_find_bwrap()]
    args.append("--ro-bind")
    args.append("/")
    args.append("/")

    args.append("--proc")
    args.append("/proc")

    args.append("--dev")
    args.append("/dev")

    args.append("--tmpfs")
    args.append("/tmp")

    args.append("--tmpfs")
    args.append("/var/tmp")

    from tools.state import get_state
    state = get_state()
    if state.user_root:
        user_root = state.user_root
        args.append("--bind")
        args.append(user_root)
        args.append(user_root)

    cwd = get_cwd()
    if os.path.isdir(cwd):
        args.append("--bind")
        args.append(cwd)
        args.append(cwd)

    args.append("--chdir")
    args.append(cwd)

    args.append("--unshare-ipc")
    args.append("--unshare-pid")
    args.append("--unshare-net")

    args.append("--")
    args.append("/bin/bash")
    args.append("-c")

    return args


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
                    bwrap_args = _build_bwrap_args(parent_state.user_id)
                    if bwrap_args:
                        full_cmd = bwrap_args + [command]
                    else:
                        full_cmd = command

                    proc = subprocess.Popen(
                        full_cmd, shell=(not bwrap_args), stdout=subprocess.PIPE,
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
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            _kill_proc_group(proc)
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
        bwrap_args = _build_bwrap_args(get_state().user_id)
        if bwrap_args:
            full_cmd = bwrap_args + [command]
            shell = False
        else:
            full_cmd = command
            shell = True

        proc = subprocess.Popen(
            full_cmd, shell=shell, stdout=subprocess.PIPE,
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