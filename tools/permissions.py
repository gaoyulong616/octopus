"""共享权限常量和工具摘要函数，供 cli.py / tui.py / web/agent_bridge.py 复用。"""

from __future__ import annotations

import json

# 读取类工具 — 这些工具不修改文件系统，权限检查时自动通过
READ_TOOLS: frozenset[str] = frozenset({
    "read_file", "list_files", "grep_search", "web_search",
    "web_fetch", "read_image", "task_list", "task_get",
})


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
    if web_mode:
        return (
            "\n\n## 当前模式：Plan（审批制）\n"
            "你处于 Plan 模式。所有工具调用都会请求用户确认后执行。\n"
            "请先充分分析（读取文件、搜索、浏览），然后输出结构化的实施计划。"
        )
    return (
        "\n\n## 当前模式：Plan（审批制）\n"
        "你处于 Plan 模式。所有工具调用都会请求用户确认后执行。\n"
        "请先充分分析（读取文件、搜索、浏览），然后调用 submit_plan 提交结构化的实施计划：\n"
        "分析完成后，**必须**调用 submit_plan 工具提交结构化的实施计划：\n"
        "- 计划应以 numbered list 列出每个步骤\n"
        "- 每个步骤说明要修改的文件和具体操作\n"
        "- 标注步骤之间的依赖关系\n"
        "- 包含验证方式（如何确认实施成功）\n"
        "调用 submit_plan 后，用户会审批你的计划；批准后会自动切换到 Auto 模式执行。"
    )
