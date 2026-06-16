"""Agent 状态封装：工作目录、任务管理。

支持 per-connection 隔离：每个 TUI/Web 连接拥有独立的 AgentState 实例，
通过 threading.local 实现线程安全的状态切换。

多用户支持：
- user_id: 用户 ID，Web 模式下有效；TUI/CLI 模式为空字符串
- user_root: 用户根目录，Web 模式下用于路径边界检查；TUI/CLI 模式为空字符串
"""

from __future__ import annotations

import json
import os
import re
import threading

# 线程本地存储，实现 per-connection AgentState 隔离
_local = threading.local()


class AgentState:
    """Agent 运行状态，封装 cwd 和任务管理。"""

    def __init__(self, user_id: str = "", user_root: str = ""):
        self.user_id: str = user_id      # Web 模式：用户 ID；TUI 模式：""
        self.user_root: str = user_root  # Web 模式：用户根目录；TUI 模式：""
        self.cwd: str = user_root if user_root else os.getcwd()
        self.tasks: dict[int, dict] = {}
        self.next_task_id: int = 1
        self.pending_plan: str | None = None  # Plan 模式下 LLM 提交的计划文本
        self.pending_plan_mode: bool = False  # LLM 请求进入 plan 模式

    def get_cwd(self) -> str:
        return self.cwd

    def set_cwd(self, path: str) -> None:
        """设置工作目录，限制在用户目录内（Web 模式）"""
        new_cwd = self.abs_path(path)
        if self.user_root and not new_cwd.startswith(self.user_root + os.sep) and new_cwd != self.user_root:
            from tools.exceptions import ToolError
            raise ToolError(f"越权切换目录: {path}")
        self.cwd = new_cwd

    def abs_path(self, path: str) -> str:
        """解析路径为绝对路径，Web 模式下强制目录边界检查。"""
        abs_path = os.path.realpath(path) if os.path.isabs(path) else os.path.realpath(os.path.join(self.cwd, path))

        # Web 模式下强制目录边界
        if self.user_root:
            if not abs_path.startswith(self.user_root + os.sep) and abs_path != self.user_root:
                from tools.exceptions import ToolError
                raise ToolError(f"越权访问: {path}")

        return abs_path

    def update_cwd(self, command: str) -> None:
        """追踪 bash 命令中的 cd 操作。"""
        stripped = command.strip()
        old_cwd = self.cwd
        # 按 && ; \n 分割命令链
        parts = re.split(r"&&|;|\n", stripped)
        for part in parts:
            part = part.strip()
            # 去掉 || 后面的部分（只取成功路径）
            if "||" in part:
                part = part.split("||")[0].strip()
            if part.startswith("cd "):
                target = part[3:].strip().strip("\"'")
                if target == "":
                    new_dir = os.path.expanduser("~")
                else:
                    new_dir = os.path.expanduser(target)
                    if not os.path.isabs(new_dir):
                        new_dir = os.path.normpath(os.path.join(self.cwd, new_dir))
                if os.path.isdir(new_dir):
                    self.cwd = new_dir
        if self.cwd != old_cwd:
            try:
                from config import run_hooks
                run_hooks("CwdChanged", {"old": old_cwd, "new": self.cwd})
            except Exception:
                pass

    def task_create(self, subject: str, description: str = "", active_form: str = "") -> str:
        tid = self.next_task_id
        self.next_task_id += 1
        self.tasks[tid] = {
            "id": tid,
            "subject": subject,
            "description": description,
            "activeForm": active_form or subject,
            "status": "pending",
            "owner": None,
            "blocks": [],
            "blockedBy": [],
            "metadata": {},
        }
        return json.dumps({"id": tid, "subject": subject, "status": "pending"}, ensure_ascii=False)

    def task_update(self, task_id: int, **kwargs) -> str:
        tid = int(task_id)
        if tid not in self.tasks:
            return f"[错误] 任务 {tid} 不存在"
        task = self.tasks[tid]
        for key in ("subject", "description", "activeForm", "owner", "status"):
            if key in kwargs and kwargs[key] is not None:
                task[key] = kwargs[key]
        if "addBlocks" in kwargs and kwargs["addBlocks"]:
            for b in kwargs["addBlocks"]:
                b = int(b)
                if b not in task["blocks"] and b in self.tasks:
                    task["blocks"].append(b)
                    self.tasks[b]["blockedBy"].append(tid)
        if "addBlockedBy" in kwargs and kwargs["addBlockedBy"]:
            for b in kwargs["addBlockedBy"]:
                b = int(b)
                if b not in task["blockedBy"] and b in self.tasks:
                    task["blockedBy"].append(b)
                    self.tasks[b]["blocks"].append(tid)
        if "metadata" in kwargs and kwargs["metadata"] is not None:
            task["metadata"].update(kwargs["metadata"])
        return json.dumps({"id": tid, "status": task["status"]}, ensure_ascii=False)

    def task_list(self) -> str:
        if not self.tasks:
            return "没有任务"
        lines = []
        for tid, t in sorted(self.tasks.items()):
            blocks_str = ""
            if t["blockedBy"]:
                blocks_str = f" (blocked by: {t['blockedBy']})"
            lines.append(f"  #{t['id']} [{t['status']}] {t['subject']}{blocks_str}")
        return "\n".join(lines)

    def task_get(self, task_id: int) -> str:
        tid = int(task_id)
        if tid not in self.tasks:
            return f"[错误] 任务 {tid} 不存在"
        return json.dumps(self.tasks[tid], ensure_ascii=False, indent=2)


# 模块级默认实例（主线程使用）
_default_state: AgentState | None = None


def get_state() -> AgentState:
    """获取当前线程的 AgentState。

    优先级：线程本地活跃状态 > 全局默认实例。
    TUI 主线程使用全局默认；Web UI 每个连接的 agent 线程使用各自的活跃状态。
    """
    active = getattr(_local, "active_state", None)
    if active is not None:
        return active
    global _default_state
    if _default_state is None:
        _default_state = AgentState()
    return _default_state


def set_active_state(state: AgentState | None) -> None:
    """设置当前线程的活跃 AgentState（用于 per-connection 隔离）。"""
    _local.active_state = state


def reset_state() -> None:
    """重置状态（测试用）。"""
    global _default_state
    _default_state = AgentState()


# 向后兼容的模块级函数
def get_cwd() -> str:
    return get_state().get_cwd()


def set_cwd(path: str) -> None:
    get_state().set_cwd(path)
