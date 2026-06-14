"""PTY 进程管理 — spawn shell 并维护 master fd 读写"""

from __future__ import annotations

import os
import pty
import signal
import struct
import termios
import fcntl


class PTYManager:
    """管理一个 PTY 子进程（shell）。"""

    def __init__(self) -> None:
        self.master_fd: int = -1
        self.child_pid: int = -1

    def spawn(self, shell: str | None = None) -> None:
        if not shell:
            shell = os.environ.get("SHELL", "/bin/bash")

        pid, master = pty.fork()
        if pid == 0:
            # 子进程：启动 shell
            os.execve(shell, [shell], os.environ)

        # 父进程
        self.child_pid = pid
        self.master_fd = master

    def write(self, data: bytes) -> int:
        if self.master_fd < 0:
            return 0
        try:
            return os.write(self.master_fd, data)
        except OSError:
            return 0

    def resize(self, rows: int, cols: int) -> None:
        if self.master_fd < 0:
            return
        # TIOCSWINSZ: set window size
        buf = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, buf)
        except OSError:
            pass

    def kill(self) -> None:
        if self.child_pid > 0:
            try:
                pgid = os.getpgid(self.child_pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(self.child_pid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
            # 等待子进程退出避免 zombie
            try:
                os.waitpid(self.child_pid, 0)
            except (ChildProcessError, OSError):
                pass
            self.child_pid = -1
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = -1

    def fileno(self) -> int:
        return self.master_fd
