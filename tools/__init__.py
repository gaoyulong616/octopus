"""工具包：Schema 定义、工具实现、执行器、工作目录管理。

向后兼容所有 `from tools import ...` 导入。
"""

# Schema
from tools.schemas import TOOLS

# CWD 管理
from tools.bash import get_cwd, set_cwd, _update_cwd

# Bash 工具
from tools.bash import run_bash

# 文件操作工具
from tools.file_ops import (
    _abs_path,
    run_read_file, run_write_file, run_edit_file,
    run_list_files, run_grep_search,
    run_copy_file, run_move_file, run_delete_file,
    run_read_image,
)

# Web 工具
from tools.web_tools import run_web_search, run_web_fetch

# Notebook 工具
from tools.notebook import run_notebook_edit

# 子 Agent 工具
from tools.agent_tools import run_sub_agent

# Git 工具
from tools.git_tools import (
    run_worktree_create, run_worktree_remove,
    run_checkpoint_create, run_checkpoint_rollback,
)

# 调度工具
from tools.sched_tools import (
    _cron_to_interval, run_schedule_wakeup,
    run_cron_create, run_cron_delete, run_cron_list,
)

# 注册表和执行器
from tools.registry import (
    TOOL_HANDLERS, execute_tool,
    _task_create, _task_update, _task_list, _task_get,
)

__all__ = [
    # Schema
    "TOOLS",
    # CWD
    "get_cwd", "set_cwd", "_update_cwd",
    # Bash
    "run_bash",
    # File ops
    "_abs_path",
    "run_read_file", "run_write_file", "run_edit_file",
    "run_list_files", "run_grep_search",
    "run_copy_file", "run_move_file", "run_delete_file",
    "run_read_image",
    # Web
    "run_web_search", "run_web_fetch",
    # Notebook
    "run_notebook_edit",
    # Agent
    "run_sub_agent",
    # Git
    "run_worktree_create", "run_worktree_remove",
    "run_checkpoint_create", "run_checkpoint_rollback",
    # Sched
    "_cron_to_interval", "run_schedule_wakeup",
    "run_cron_create", "run_cron_delete", "run_cron_list",
    # Registry
    "TOOL_HANDLERS", "execute_tool",
    "_task_create", "_task_update", "_task_list", "_task_get",
]
