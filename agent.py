"""Agent 主循环：调用 LLM、执行工具、管理对话历史。"""

import json
import sys
from typing import Any

import anthropic

from config import get
from context import build_system_prompt, compress_messages
from tools import TOOLS, execute_tool
from mcp import MCPManager

# ANSI 颜色常量
_CYAN = "\033[96m"
_YELLOW = "\033[93m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _format_tool_input(tool_name: str, tool_input: dict) -> str:
    """将工具输入格式化为简洁的单行摘要。"""
    if tool_name == "bash":
        cmd = tool_input.get("command", "")
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        return cmd
    if tool_name == "edit_file":
        path = tool_input.get("path", "")
        old = tool_input.get("old_string", "")[:40]
        return f"{path}: \"{old}...\""
    if tool_name in ("read_file", "write_file"):
        return tool_input.get("path", "")
    if tool_name == "grep_search":
        return tool_input.get("pattern", "")
    if tool_name == "list_files":
        path = tool_input.get("path", ".")
        pattern = tool_input.get("pattern", "")
        return f"{path} {pattern}".strip()
    if tool_name == "web_search":
        return tool_input.get("query", "")[:60]
    if tool_name == "web_fetch":
        return tool_input.get("url", "")[:80]
    return json.dumps(tool_input, ensure_ascii=False)[:80]


def run_agent(
    user_task: str,
    max_iterations: int | None = None,
    verbose: bool = True,
    messages: list[dict] | None = None,
    on_interrupt: Any = None,
    confirm_fn: Any = None,
    mcp: MCPManager | None = None,
) -> str:
    """
    运行 Agent 完成一个任务。

    Args:
        user_task: 用户的任务描述
        max_iterations: 最大工具调用轮次，None 则从配置读取
        verbose: 是否打印每步的思考过程
        messages: 外部传入的对话历史。None 创建新对话，否则追加。
        on_interrupt: 可选的回调，在中断时调用
        confirm_fn: 权限确认回调 (tool_name, tool_input) -> bool
        mcp: MCP 管理器实例，用于路由 MCP 工具调用

    Returns:
        Agent 的最终回复
    """
    model = get("model")
    max_tokens = get("max_tokens")
    if max_iterations is None:
        max_iterations = get("max_iterations")

    client = anthropic.Anthropic(
        api_key=get("api_key"),
        base_url=get("base_url") or None,
    )

    if messages is None:
        messages = [{"role": "user", "content": user_task}]
    else:
        messages.append({"role": "user", "content": user_task})

    iteration = 0

    def log(tag: str, text: str, color: str = ""):
        if not verbose:
            return
        colors = {"cyan": _CYAN, "yellow": _YELLOW,
                  "green": _GREEN, "red": _RED, "dim": _DIM, "": ""}
        c = colors.get(color, "")
        print(f"\n{c}{tag}{_RESET}\n{text}")

    log(f"{_CYAN}{_BOLD}📋 任务{_RESET}", user_task)

    # 合并内置工具和 MCP 工具
    all_tools = list(TOOLS)
    if mcp:
        mcp_tools = mcp.get_all_tools()
        all_tools.extend(mcp_tools)

    try:
        while iteration < max_iterations:
            iteration += 1

            # 上下文压缩
            messages[:] = compress_messages(client, messages, model)

            system_prompt = build_system_prompt()

            # 调用 LLM
            if verbose:
                print(f"\n{_DIM}⏳ 调用 LLM (轮次 {iteration})...{_RESET}", end="", flush=True)

            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                tools=all_tools,
                messages=messages,
            )

            if verbose:
                print(f"\r{_DIM}  轮次 {iteration}/{max_iterations}{_RESET}")

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []

            for block in response.content:
                if block.type == "text" and block.text.strip():
                    # 思考过程用 dim 颜色，最终回复高亮
                    log(f"{_YELLOW}💭 思考{_RESET}", block.text, "yellow")

                elif block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    summary = _format_tool_input(tool_name, tool_input)
                    print(f"\n  {_GREEN}🔧 {tool_name}{_RESET} {summary}")

                    # 权限确认
                    if confirm_fn and not confirm_fn(tool_name, tool_input):
                        print(f"  {_RED}✗ 已拒绝{_RESET}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": "[用户拒绝执行此操作]",
                        })
                        continue

                    # 路由：内置工具 or MCP 工具
                    if mcp and mcp.has_tool(tool_name):
                        result = mcp.call_tool(tool_name, tool_input)
                    else:
                        result = execute_tool(tool_name, tool_input)

                    # 简洁的结果展示
                    result_preview = result[:300].replace("\n", " ")
                    if len(result) > 300:
                        result_preview += f"... ({len(result)} chars)"
                    print(f"  {_DIM}→ {result_preview}{_RESET}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result,
                    })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
                continue

            final_text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            print(f"\n{_CYAN}{_BOLD}✅ 回复{_RESET}")
            print(final_text)
            return final_text

    except KeyboardInterrupt:
        print(f"\n{_RED}⚠️ 任务已被用户取消{_RESET}")
        if messages and messages[-1].get("role") == "assistant":
            content = messages[-1]["content"]
            pending_results = []
            for block in content if isinstance(content, list) else []:
                if getattr(block, "type", None) == "tool_use":
                    pending_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "[用户中断]",
                    })
            if pending_results:
                messages.append({"role": "user", "content": pending_results})
        if on_interrupt:
            on_interrupt()
        return "[用户中断]"

    return ""
