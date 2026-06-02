"""子 Agent 工具：在独立线程中运行子任务。

支持两种隔离粒度：
  - 默认（无隔离）：完整工具集，独立 message 历史
  - isolation="read-only"：禁用写入类工具（bash/write_file/edit_file/copy/move/delete 等）
  - isolation="worktree"：先创建 git worktree，子 agent 在其中运行（独立分支、独立 cwd）
"""

import threading
from typing import Any

from tools.exceptions import ToolError


# 各隔离模式下被禁止的工具
_RESTRICTED_TOOLS = {
    "read-only": {
        "bash", "write_file", "edit_file",
        "copy_file", "move_file", "delete_file",
        "notebook_edit",
        "worktree_create", "worktree_remove",
        "checkpoint_rollback",
    },
}


def _make_restricted_confirm(tool_name: str) -> Any:
    """生成 confirm_fn：对受限工具直接拒绝。"""
    blocked = _RESTRICTED_TOOLS.get(tool_name, set())

    def _confirm(name: str, tool_input: dict, state: dict | None = None) -> bool:
        if name in blocked:
            return False
        return True

    return _confirm


def run_sub_agent(task: str, description: str = "",
                  output_fn=None, isolation: str | None = None,
                  max_iterations: int | None = None) -> str:
    """在独立线程中运行子 Agent。

    Args:
        task: 子任务描述
        description: 任务简介（用于显示）
        output_fn: 输出回调
        isolation: 隔离粒度。None=完整权限；"read-only"=仅读取工具；"worktree"=独立 git worktree
        max_iterations: 子 agent 迭代上限（默认 8）

    子 agent 完成后会触发 SubagentStop hook。
    """
    if max_iterations is None:
        max_iterations = 8

    result_holder: dict = {"result": None, "error": None}
    worktree_path: str | None = None

    # worktree 隔离：先创建 worktree，子 agent 在其中运行
    if isolation == "worktree":
        try:
            from tools.git_tools import run_worktree_create
            wt_name = f"subagent-{threading.get_ident()}"
            wt_result = run_worktree_create(wt_name)
            # run_worktree_create 返回形如 "✓ 已创建 worktree: /path/to/dir"
            if "已创建" in wt_result or "created" in wt_result.lower():
                # 提取路径（寻找以 / 开头的部分）
                import re
                m = re.search(r'(/\S+)', wt_result)
                if m:
                    worktree_path = m.group(1)
        except Exception as e:
            raise ToolError(f"创建 worktree 失败: {e}")

    def _run():
        try:
            from agent import run_agent
            from config import run_hooks
            kwargs: dict = {
                "verbose": False,
                "output_fn": output_fn,
                "max_iterations": max_iterations,
            }
            if isolation in _RESTRICTED_TOOLS:
                kwargs["confirm_fn"] = _make_restricted_confirm(isolation)
            if worktree_path:
                # 子 agent 启动前切到 worktree 目录
                from tools import set_cwd
                set_cwd(worktree_path)
            result = run_agent(task, **kwargs)
            result_holder["result"] = result
            # SubagentStop hook
            try:
                run_hooks("SubagentStop", {
                    "isolation": isolation or "none",
                    "result_preview": (result or "")[:200],
                })
            except Exception:
                pass
        except ToolError:
            raise
        except Exception as e:
            result_holder["error"] = str(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=600)  # 10 分钟超时（worktree 隔离下耗时更长）

    # 清理 worktree
    if worktree_path:
        try:
            from tools.git_tools import run_worktree_remove
            run_worktree_remove(worktree_path)
        except Exception:
            pass

    if thread.is_alive():
        raise ToolError("子 Agent 超时（600s）")

    if result_holder["error"]:
        raise ToolError(f"子 Agent 错误: {result_holder['error']}")

    return result_holder["result"] or "(子 Agent 无输出)"
