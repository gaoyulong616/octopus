"""共享权限常量和工具摘要函数，供 cli.py / tui.py / web/agent_bridge.py 复用。"""

from __future__ import annotations

import json

# 读取类工具 — 任何模式下都自动通过（不修改文件系统）
READ_TOOLS: frozenset[str] = frozenset({
    "read_file", "list_files", "grep_search", "web_search",
    "web_fetch", "read_image", "task_list", "task_get",
    "sub_agent", "invoke_skill", "ask_user_question",
    "cron_list", "submit_plan",
})

# 编辑类工具 — Accept Edits 模式自动通过；Plan 模式禁止
EDIT_TOOLS: frozenset[str] = frozenset({
    "write_file", "edit_file", "multi_edit",
    "copy_file", "move_file", "notebook_edit",
    "task_create", "task_update",
    "worktree_create", "checkpoint_create",
    "schedule_wakeup", "cron_create",
    "enter_plan_mode",
})

# 破坏性操作 — Accept Edits 模式需要确认；Plan 模式禁止
DESTRUCTIVE_TOOLS: frozenset[str] = frozenset({
    "delete_file", "worktree_remove",
    "checkpoint_rollback", "cron_delete",
})

# 兼容旧引用：= EDIT_TOOLS ∪ DESTRUCTIVE_TOOLS ∪ {bash}
WRITE_TOOLS: frozenset[str] = EDIT_TOOLS | DESTRUCTIVE_TOOLS | frozenset({"bash"})


def summarize_tool(tool_name: str, tool_input: dict) -> str:
    """生成工具调用的简要摘要，用于确认对话框。"""
    if tool_name == "bash":
        cmd = tool_input.get("command", "")
        return cmd[:120] + ("..." if len(cmd) > 120 else "")
    if tool_name == "write_file":
        return tool_input.get("path", "")
    if tool_name == "edit_file":
        return tool_input.get("path", "")
    if tool_name in ("read_file", "read_image"):
        return tool_input.get("path", "")
    if tool_name in ("copy_file", "move_file"):
        return f"{tool_input.get('source', '')} → {tool_input.get('destination', '')}"
    if tool_name == "delete_file":
        return tool_input.get("path", "")
    if tool_name == "list_files":
        return tool_input.get("path", ".")
    if tool_name == "grep_search":
        return tool_input.get("pattern", "")
    if tool_name in ("web_search", "web_fetch"):
        text = tool_input.get("query", "") or tool_input.get("url", "")
        return text[:80]
    return json.dumps(tool_input, ensure_ascii=False)[:100]


def build_plan_hint(web_mode: bool = False) -> str:
    """构建 Plan 模式追加到 system prompt 的约束文本。"""
    common = (
        "\n\n## 当前模式：Plan（只读分析）\n"
        "你处于 Plan 模式，**完全只读**：可以自由使用读取类工具（read_file、list_files、grep_search、web_search 等）"
        "和只读 bash 命令（ls、cat、grep、pwd 等）进行探索。\n"
        "**禁止操作**：写入/编辑文件、删除、执行写 bash 命令（rm、mkdir、git push、npm install 等会修改文件系统/状态）。\n"
    )
    if web_mode:
        return common + (
            "请先充分分析（读取文件、搜索、浏览），然后输出结构化的实施计划文本。\n"
        )
    return common + (
        "分析完成后，**必须**调用 submit_plan 工具提交结构化的实施计划：\n"
        "- 计划应以 numbered list 列出每个步骤\n"
        "- 每个步骤说明要修改的文件和具体操作\n"
        "- 标注步骤之间的依赖关系\n"
        "- 包含验证方式（如何确认实施成功）\n"
        "调用 submit_plan 后，用户会审批你的计划；批准后会自动切换到 Accept Edits 模式开始执行。"
    )
