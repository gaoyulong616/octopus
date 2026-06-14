"""子 Agent 工具：在独立线程中运行子任务。

支持两种隔离粒度：
  - 默认（无隔离）：完整工具集，独立 message 历史
  - isolation="read-only"：禁用写入类工具（bash/write_file/edit_file/copy/move/delete 等）
  - isolation="worktree"：先创建 git worktree，子 agent 在其中运行（独立分支、独立 cwd）
"""

import threading
import time
from collections.abc import Callable
from typing import Any

from tools.exceptions import ToolError

# ask_user_question 回调使用 threading.local，避免多 agent 线程并发时跨连接污染
# （与 agent.py 的 _emit_local 同样模式）
_ask_local = threading.local()


def set_ask_fn(fn: Callable | None):
    """设置当前线程的 ask_user_question 回调。"""
    _ask_local.ask_fn = fn


def _get_ask_fn() -> Callable | None:
    """获取当前线程的 ask_user_question 回调。"""
    return getattr(_ask_local, "ask_fn", None)


# 各隔离模式下被禁止的工具
_RESTRICTED_TOOLS = {
    "read-only": {
        "bash",
        "write_file",
        "edit_file",
        "copy_file",
        "move_file",
        "delete_file",
        "notebook_edit",
        "worktree_create",
        "worktree_remove",
        "checkpoint_rollback",
    },
}


def _make_restricted_confirm(isolation_level: str) -> Any:
    """生成 confirm_fn：对受限工具直接拒绝。"""
    blocked = _RESTRICTED_TOOLS.get(isolation_level, set())

    def _confirm(name: str, tool_input: dict, state: dict | None = None) -> bool:
        if name in blocked:
            return False
        return True

    return _confirm


def run_sub_agent(
    task: str, description: str = "", output_fn=None, isolation: str | None = None, max_iterations: int | None = None
) -> str:
    """在独立线程中运行子 Agent。

    Args:
        task: 子任务描述
        description: 任务简介（用于显示）
        output_fn: 输出回调
        isolation: 隔离粒度。None=完整权限；"read-only"=仅读取工具；"worktree"=独立 git worktree
        max_iterations: 已废弃，保留仅为向后兼容 schema

    子 agent 完成后会触发 SubagentStop hook。
    """
    result_holder: dict = {"result": None, "error": None}
    worktree_path: str | None = None
    interrupt_event = threading.Event()

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

                m = re.search(r"(/\S+)", wt_result)
                if m:
                    worktree_path = m.group(1)
        except Exception as e:
            raise ToolError(f"创建 worktree 失败: {e}")

    def _run():
        try:
            from agent import run_agent
            from config import run_hooks
            from tools.state import AgentState, set_active_state

            kwargs: dict = {
                "verbose": False,
                "output_fn": output_fn,
            }
            # 关键：子 agent 用独立 AgentState，与父 agent 的 tasks/cwd 完全隔离
            # （否则两线程共享 _default_state，next_task_id 并发竞争、cwd 互相污染）
            sub_state = AgentState()
            kwargs["agent_state"] = sub_state
            if isolation in _RESTRICTED_TOOLS:
                kwargs["confirm_fn"] = _make_restricted_confirm(isolation)
            if worktree_path:
                # 子 agent 启动前切到 worktree 目录（仅影响 sub_state，不影响父 agent）
                sub_state.set_cwd(worktree_path)

            def _on_interrupt():
                interrupt_event.set()

            kwargs["on_interrupt"] = _on_interrupt
            # 显式 set_active_state 双保险（run_agent 内部也会设，但提前设确保整个线程生命周期一致）
            set_active_state(sub_state)
            result = run_agent(task, **kwargs)
            result_holder["result"] = result
            # SubagentStop hook
            try:
                run_hooks(
                    "SubagentStop",
                    {
                        "isolation": isolation or "none",
                        "result_preview": (result or "")[:200],
                    },
                )
            except Exception:
                pass
        except ToolError as e:
            result_holder["error"] = e.message
        except Exception as e:
            result_holder["error"] = f"{type(e).__name__}: {e}"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    # 可中断等待：每秒检查一次 interrupt_event
    deadline = time.time() + 600
    while thread.is_alive() and time.time() < deadline:
        thread.join(timeout=1.0)
        if interrupt_event.is_set():
            break

    if thread.is_alive():
        # 先等待线程完全结束后再清理 worktree，避免线程中文件操作失败
        thread.join(timeout=5)
        if worktree_path:
            try:
                from tools.git_tools import run_worktree_remove

                run_worktree_remove(worktree_path)
            except Exception as e:
                from logger import get_logger

                get_logger().warning("worktree 清理失败 %s: %s: %s", worktree_path, type(e).__name__, e)
        raise ToolError("子 Agent 超时（600s）")

    # 正常完成，清理 worktree
    if worktree_path:
        try:
            from tools.git_tools import run_worktree_remove

            run_worktree_remove(worktree_path)
        except Exception as e:
            from logger import get_logger

            get_logger().warning("worktree 清理失败 %s: %s: %s", worktree_path, type(e).__name__, e)

    if result_holder["error"]:
        raise ToolError(f"子 Agent 错误: {result_holder['error']}")

    return result_holder["result"] or "(子 Agent 无输出)"


def run_ask_user_question(question: str, header: str, options: list[dict], multi_select: bool = False) -> str:
    """向用户提出选项式问题，返回用户选择结果。"""
    ask_fn = _get_ask_fn()
    if not ask_fn:
        # 无 UI 回调时，返回所有选项让 LLM 自行判断
        labels = [o.get("label", "?") for o in options]
        return f"[无 UI 交互支持] 选项: {', '.join(labels)}。请根据上下文选择最合适的。"
    return ask_fn(question, header, options, multi_select)
