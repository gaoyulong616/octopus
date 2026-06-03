"""Bash 工具：执行 shell 命令，实时流式输出，工作目录持久化。"""

import os
import signal
import subprocess

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


def run_bash(command: str, timeout: int = 120, output_fn=None) -> str:
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
