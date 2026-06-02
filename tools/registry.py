"""工具注册表和执行器。"""

from typing import Any

from tools.state import get_state
from tools.exceptions import ToolError

from tools.bash import run_bash, get_cwd, set_cwd, _update_cwd
from tools.file_ops import (
    run_read_file, run_write_file, run_edit_file, run_list_files,
    run_grep_search, run_copy_file, run_move_file, run_delete_file,
    run_read_image, _abs_path,
)
from tools.web_tools import run_web_search, run_web_fetch
from tools.notebook import run_notebook_edit
from tools.agent_tools import run_sub_agent
from tools.git_tools import (
    run_worktree_create, run_worktree_remove,
    run_checkpoint_create, run_checkpoint_rollback,
)
from tools.sched_tools import (
    _cron_to_interval, run_schedule_wakeup,
    run_cron_create, run_cron_delete, run_cron_list,
)


# ─────────────────────────────────────────────
# 任务状态管理（委托到 AgentState）
# ─────────────────────────────────────────────

def _task_create(subject: str, description: str = "",
                 active_form: str = "") -> str:
    return get_state().task_create(subject, description, active_form)


def _task_update(task_id: int, **kwargs) -> str:
    return get_state().task_update(task_id, **kwargs)


def _task_list() -> str:
    return get_state().task_list()


def _task_get(task_id: int) -> str:
    return get_state().task_get(task_id)


# ─────────────────────────────────────────────
# 工具注册表
# ─────────────────────────────────────────────

TOOL_HANDLERS: dict[str, Any] = {
    "bash":       lambda inp: run_bash(inp["command"], inp.get("timeout", 120)),
    "read_file":  lambda inp: run_read_file(
                      inp["path"], inp.get("encoding", "utf-8"),
                      inp.get("offset"), inp.get("limit")),
    "write_file": lambda inp: run_write_file(inp["path"], inp["content"], inp.get("mode", "w")),
    "edit_file":  lambda inp: run_edit_file(
                      inp["path"], inp["old_string"],
                      inp["new_string"], inp.get("replace_all", False)),
    "list_files": lambda inp: run_list_files(
                      inp.get("path", "."), inp.get("pattern", ""),
                      inp.get("recursive", False)),
    "grep_search": lambda inp: run_grep_search(
                       inp["pattern"], inp.get("path", "."),
                       inp.get("include", ""), inp.get("max_results", 50)),
    "web_search": lambda inp: run_web_search(inp["query"], inp.get("max_results", 10)),
    "web_fetch":  lambda inp: run_web_fetch(inp["url"], inp.get("max_length", 5000)),
    "copy_file":  lambda inp: run_copy_file(inp["source"], inp["destination"]),
    "move_file":  lambda inp: run_move_file(inp["source"], inp["destination"]),
    "delete_file": lambda inp: run_delete_file(inp["path"]),
    "task_create": lambda inp: _task_create(
                       inp["subject"], inp.get("description", ""),
                       inp.get("activeForm", "")),
    "task_update": lambda inp: _task_update(
                       inp["taskId"],
                       status=inp.get("status"),
                       subject=inp.get("subject"),
                       description=inp.get("description"),
                       addBlocks=inp.get("addBlocks"),
                       addBlockedBy=inp.get("addBlockedBy")),
    "task_list":  lambda inp: _task_list(),
    "task_get":   lambda inp: _task_get(inp["taskId"]),
    "notebook_edit": lambda inp: run_notebook_edit(
                         inp["notebook_path"], inp["new_source"],
                         inp.get("cell_id"), inp.get("cell_type", "code"),
                         inp.get("edit_mode", "replace")),
    "sub_agent":  lambda inp: run_sub_agent(
                      inp["task"], inp.get("description", "")),
    "worktree_create": lambda inp: run_worktree_create(inp["name"]),
    "worktree_remove": lambda inp: run_worktree_remove(inp["path"]),
    "checkpoint_create": lambda inp: run_checkpoint_create(inp.get("message", "auto checkpoint")),
    "checkpoint_rollback": lambda inp: run_checkpoint_rollback(),
    "schedule_wakeup": lambda inp: run_schedule_wakeup(
                         inp["delay_seconds"], inp.get("reason", ""),
                         inp.get("prompt", "")),
    "cron_create": lambda inp: run_cron_create(
                       inp["cron"], inp["prompt"], inp["name"],
                       inp.get("recurring", True)),
    "cron_delete": lambda inp: run_cron_delete(inp["name"]),
    "cron_list":  lambda inp: run_cron_list(),
    "read_image": lambda inp: run_read_image(inp["path"]),
}


def execute_tool(name: str, tool_input: dict, output_fn=None) -> str:
    if name == "bash" and output_fn:
        try:
            return run_bash(
                tool_input["command"],
                tool_input.get("timeout", 30),
                output_fn=output_fn,
            )
        except ToolError as e:
            return f"[错误] {e.message}"

    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return f"[错误] 未知工具: {name}"
    try:
        return handler(tool_input)
    except ToolError as e:
        return f"[错误] {e.message}"
