"""Agent 主循环：调用 LLM、执行工具、管理对话历史。"""

import json
from typing import Any, Callable

import anthropic

from context import build_system_prompt, compress_messages
from tools import TOOLS, execute_tool
from tools.exceptions import ToolError
from mcp import MCPManager
from config import get, run_hooks
from logger import get_logger as _get_logger

# 事件类型常量
EVT_THINKING = "thinking"
EVT_TOOL_CALL = "tool_call"
EVT_TOOL_RESULT = "tool_result"
EVT_RESPONSE = "response"
EVT_PROGRESS = "progress"
EVT_ERROR = "error"
EVT_STREAM = "stream"

from constants import CYAN as _CYAN, YELLOW as _YELLOW, GREEN as _GREEN
from constants import RED as _RED, DIM as _DIM, BOLD as _BOLD, RESET as _RESET

# ── 网络错误类型（用于重试） ──

try:
    import httpx
    _NET_ERRORS = (ConnectionError, TimeoutError,
                   httpx.ConnectError, httpx.TimeoutException,
                   httpx.ConnectTimeout, httpx.ReadTimeout)
except ImportError:
    _NET_ERRORS = (ConnectionError, TimeoutError)

# ── Client 单例复用 ──

_client: anthropic.Anthropic | None = None
_client_keys: tuple = ()


def _get_client() -> anthropic.Anthropic:
    """获取或创建缓存的 Anthropic client（配置不变时复用）。"""
    global _client, _client_keys
    current_keys = (get("api_key"), get("base_url"))
    if _client is None or _client_keys != current_keys:
        _client = anthropic.Anthropic(
            api_key=current_keys[0],
            base_url=current_keys[1] or None,
        )
        _client_keys = current_keys
    return _client


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


def _stream_with_retry(client, model, max_tokens, system_prompt, tools, messages, emit,
                       max_retries=3, thinking_budget=None):
    """带重试的流式 API 调用，指数退避。"""
    import time
    for attempt in range(max_retries + 1):
        try:
            kwargs = dict(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )
            if thinking_budget:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            with client.messages.stream(**kwargs) as stream:
                for text in stream.__stream_text__():
                    emit(EVT_STREAM, text)
                return stream.get_final_message()
        except anthropic.RateLimitError as e:
            if attempt >= max_retries:
                raise
            wait = 2 ** attempt
            emit(EVT_ERROR, f"Rate limited, retrying in {wait}s...")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code == 401:
                raise PermissionError(
                    "API 认证失败 (401)。请检查 API Key 是否正确配置。\n"
                    "  配置文件: ~/.octopus/config.json\n"
                    "  环境变量: OCTOPUS_API_KEY"
                ) from e
            if e.status_code >= 500 and attempt < max_retries:
                wait = 2 ** attempt
                emit(EVT_ERROR, f"Server error {e.status_code}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except _NET_ERRORS as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                emit(EVT_ERROR, f"Connection error, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("unreachable")


def run_agent(
    user_task: str,
    max_iterations: int | None = None,
    verbose: bool = True,
    messages: list[dict] | None = None,
    on_interrupt: Any = None,
    confirm_fn: Any = None,
    mcp: MCPManager | None = None,
    system_prompt_override: str | None = None,
    output_fn: Callable[[str, str, dict | None], None] | None = None,
) -> str:
    """
    运行 Agent 完成一个任务。

    Args:
        user_task: 用户的任务描述
        max_iterations: 最大工具调用轮次，None 则从配置读取
        verbose: 是否打印每步的思考过程（仅 print fallback 模式）
        messages: 外部传入的对话历史。None 创建新对话，否则追加。
        on_interrupt: 可选的回调，在中断时调用
        confirm_fn: 权限确认回调 (tool_name, tool_input) -> bool
        mcp: MCP 管理器实例，用于路由 MCP 工具调用
        system_prompt_override: 自定义 system prompt（来自 agent 切换）
        output_fn: 输出回调 (event_type, text, metadata)。为 None 时用 print。

    Returns:
        Agent 的最终回复
    """
    model = get("model")
    max_tokens = get("max_tokens")
    if max_iterations is None:
        max_iterations = get("max_iterations")

    client = _get_client()

    if messages is None:
        messages = [{"role": "user", "content": user_task}]
    else:
        messages.append({"role": "user", "content": user_task})

    iteration = 0

    def emit(event_type: str, text: str, meta: dict | None = None):
        """发送输出事件。优先 output_fn，否则 print。"""
        if output_fn:
            output_fn(event_type, text, meta)
        elif verbose:
            _print_event(event_type, text, meta)

    emit(EVT_PROGRESS, user_task, {"label": "任务"})

    # 合并内置工具和 MCP 工具
    all_tools = list(TOOLS)
    if mcp:
        mcp_tools = mcp.get_all_tools()
        all_tools.extend(mcp_tools)

    thinking_budget = get("thinking_budget")

    try:
        while iteration < max_iterations:
            iteration += 1

            messages[:] = compress_messages(client, messages, model,
                                                force=False)
            system_prompt = system_prompt_override or build_system_prompt()
            # Prompt Cache: system prompt 加 cache_control
            system_param = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}},
            ]

            emit(EVT_PROGRESS, f"调用 LLM (轮次 {iteration}/{max_iterations})")

            # 使用流式 API，实时输出文本 token（含重试）
            final_message = _stream_with_retry(
                client, model, max_tokens, system_param, all_tools, messages, emit,
                thinking_budget=thinking_budget,
            )

            messages.append({"role": "assistant", "content": final_message.content})

            # 日志：LLM 调用完成
            _log = _get_logger()
            usage = getattr(final_message, 'usage', None)
            if usage:
                _log.info("LLM iteration=%d model=%s input=%d output=%d",
                          iteration, model, usage.input_tokens, usage.output_tokens)

            # Stop Reason 处理
            stop_reason = getattr(final_message, 'stop_reason', None)
            if stop_reason == "max_tokens":
                emit(EVT_ERROR, f"达到最大 token 数 ({max_tokens})，回复被截断。"
                     "可用 /config max_tokens=<N> 增大限制。")

            tool_results = []
            has_tool_use = any(
                b.type == "tool_use" for b in final_message.content
            )

            for block in final_message.content:
                if block.type == "thinking":
                    thinking_text = getattr(block, "thinking", "") or ""
                    emit(EVT_THINKING, thinking_text)

                elif block.type == "text" and block.text.strip():
                    if has_tool_use:
                        # 文本已通过 EVT_STREAM 实时输出，这里只发空事件标记切换
                        emit(EVT_THINKING, "")
                    # 最终回复在循环末尾处理

                elif block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    # Pre-tool hook
                    hook_results = run_hooks("pre_tool_call", {
                        "tool": tool_name,
                        "input": json.dumps(tool_input, ensure_ascii=False)[:500],
                    })
                    blocked = False
                    for hr in hook_results:
                        if "[hook exit code:" in hr or "[hook 错误" in hr:
                            emit(EVT_TOOL_RESULT, f"Hook 阻止: {hr}", {
                                "tool": tool_name, "rejected": True,
                            })
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": f"[Hook 阻止执行] {hr}",
                            })
                            blocked = True
                            break
                    if blocked:
                        continue

                    summary = _format_tool_input(tool_name, tool_input)
                    emit(EVT_TOOL_CALL, summary, {
                        "tool": tool_name,
                        "input": tool_input,
                    })

                    # 权限确认
                    if confirm_fn and not confirm_fn(tool_name, tool_input):
                        emit(EVT_TOOL_RESULT, "已拒绝", {
                            "tool": tool_name, "rejected": True,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": "[用户拒绝执行此操作]",
                        })
                        continue

                    # 路由：内置工具 or MCP 工具
                    try:
                        if mcp and mcp.has_tool(tool_name):
                            result = mcp.call_tool(tool_name, tool_input)
                        else:
                            result = execute_tool(tool_name, tool_input, output_fn=output_fn)
                    except ToolError as e:
                        error_msg = f"[错误] {e.message}"
                        emit(EVT_TOOL_RESULT, error_msg, {
                            "tool": tool_name,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": error_msg,
                        })
                        continue
                    except Exception as e:
                        error_msg = f"[错误] {type(e).__name__}: {str(e)[:200]}"
                        emit(EVT_TOOL_RESULT, error_msg, {
                            "tool": tool_name,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": error_msg,
                        })
                        continue

                    # 处理多模态结果（如 read_image 返回图片）
                    if isinstance(result, dict) and result.get("type") == "image":
                        image_data = result["source"]
                        emit(EVT_TOOL_RESULT, f"[图片: {image_data.get('media_type', '?')}, "
                             f"{len(image_data.get('data', '')) // 1024}KB base64]", {
                            "tool": tool_name,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": [
                                {"type": "text", "text": f"[已读取图片: {tool_input.get('path', '')}]"},
                                {"type": "image",
                                 "source": {"type": "base64",
                                            "media_type": image_data["media_type"],
                                            "data": image_data["data"]}},
                            ],
                        })
                    else:
                        result_preview = str(result)[:300].replace("\n", " ")
                        if len(str(result)) > 300:
                            result_preview += f"... ({len(str(result))} chars)"
                        emit(EVT_TOOL_RESULT, result_preview, {
                            "tool": tool_name,
                            "full_result": result,
                        })

                        # Post-tool hook
                        run_hooks("post_tool_call", {
                            "tool": tool_name,
                            "result_preview": result_preview[:200],
                        })

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result,
                        })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
                continue

            # 最终回复（文本已通过 EVT_STREAM 实时输出，这里只发换行收尾）
            final_text = next(
                (b.text for b in final_message.content if b.type == "text"), ""
            )
            usage = getattr(final_message, 'usage', None)
            usage_meta = {}
            if usage:
                usage_meta["input_tokens"] = usage.input_tokens
                usage_meta["output_tokens"] = usage.output_tokens
                cache_creation = getattr(usage, 'cache_creation_input_tokens', 0) or 0
                cache_read = getattr(usage, 'cache_read_input_tokens', 0) or 0
                if cache_creation or cache_read:
                    usage_meta["cache_creation_tokens"] = cache_creation
                    usage_meta["cache_read_tokens"] = cache_read
            else:
                usage_meta = None
            if final_text:
                emit(EVT_RESPONSE, "", {"usage": usage_meta} if usage_meta else {})
            return final_text

    except KeyboardInterrupt:
        emit(EVT_ERROR, "任务已被用户取消")
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


def _print_event(event_type: str, text: str, meta: dict | None = None):
    """print fallback：无 TUI 时直接输出到终端。"""
    meta = meta or {}

    if event_type == EVT_STREAM:
        import sys
        sys.stdout.write(text)
        sys.stdout.flush()
        return

    if event_type == EVT_PROGRESS:
        if meta.get("label") == "任务":
            print(f"\n{_CYAN}{_BOLD}📋 任务{_RESET}\n{text}")
        else:
            print(f"\n{_DIM}{text}{_RESET}")

    elif event_type == EVT_THINKING:
        print(f"\n{_YELLOW}💭 思考{_RESET}\n{text}")

    elif event_type == EVT_TOOL_CALL:
        tool = meta.get("tool", "")
        print(f"\n  {_GREEN}🔧 {tool}{_RESET} {text}")

    elif event_type == EVT_TOOL_RESULT:
        if meta.get("rejected"):
            print(f"  {_RED}✗ {text}{_RESET}")
        else:
            print(f"  {_DIM}→ {text}{_RESET}")

    elif event_type == EVT_RESPONSE:
        print(f"\n{_CYAN}{_BOLD}✅ 回复{_RESET}")
        print(text)

    elif event_type == EVT_ERROR:
        print(f"\n{_RED}⚠️ {text}{_RESET}")
