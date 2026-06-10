"""Agent 主循环：调用 LLM、执行工具、管理对话历史。"""

import json
import os
import threading
import time
from typing import Any, Callable

import anthropic

from context import build_system_prompt, compress_messages
from tools import execute_tool
from tools.schemas import build_tools
from tools.exceptions import ToolError
from mcp import MCPManager
from config import get, run_hooks, check_permission_rule, is_dangerous
from logger import get_logger as _get_logger
import metrics

# 事件类型常量
EVT_THINKING = "thinking"
EVT_TOOL_CALL = "tool_call"
EVT_TOOL_RESULT = "tool_result"
EVT_RESPONSE = "response"
EVT_PROGRESS = "progress"
EVT_ERROR = "error"
EVT_STREAM = "stream"

_current_emit: Callable | None = None  # 用于 scheduler 回调桥接

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
_client_lock = threading.Lock()


def _get_client() -> anthropic.Anthropic:
    """获取或创建缓存的 Anthropic client（配置不变时复用）。线程安全。"""
    global _client, _client_keys
    current_keys = (get("api_key"), get("base_url"), get("host"))
    with _client_lock:
        if _client is None or _client_keys != current_keys:
            default_headers = {"Host": current_keys[2]} if current_keys[2] else None
            _client = anthropic.Anthropic(
                api_key=current_keys[0],
                base_url=current_keys[1] or None,
                default_headers=default_headers,
            )
            _client_keys = current_keys
    return _client


# ── 服务端工具探测 ──

_server_tools_cache: dict[tuple, set[str]] = {}


def _probe_server_tools(client: anthropic.Anthropic, model: str) -> set[str]:
    """探测 API 提供商支持哪些服务端工具，结果按 (base_url, api_key) 缓存。"""
    cache_key = (get("base_url"), get("api_key"))
    if cache_key in _server_tools_cache:
        return _server_tools_cache[cache_key]

    supported: set[str] = set()
    probe_list = [
        ("web_search_20260209", "web_search"),
        ("web_fetch_20260209", "web_fetch"),
    ]
    for tool_type, tool_name in probe_list:
        try:
            client.messages.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
                tools=[{"type": tool_type, "name": tool_name}],
            )
            supported.add(tool_name)
        except anthropic.BadRequestError:
            pass
        except Exception as e:
            _get_logger().warning("探测服务端工具 %s 失败: %s: %s", tool_name, type(e).__name__, e)

    _server_tools_cache[cache_key] = supported
    return supported


def _short_path(path: str) -> str:
    """缩短路径：优先用文件名，其次用相对 cwd 路径。"""
    if not path:
        return path
    cwd = os.getcwd()
    if path.startswith(cwd):
        rel = os.path.relpath(path, cwd)
        return rel
    return os.path.basename(path) or path


def _format_tool_input(tool_name: str, tool_input: dict) -> str:
    """将工具输入格式化为简洁的单行摘要。"""
    if tool_name == "bash":
        cmd = tool_input.get("command", "")
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        return cmd
    if tool_name == "edit_file":
        return _short_path(tool_input.get("path", ""))
    if tool_name in ("read_file", "write_file"):
        return _short_path(tool_input.get("path", ""))
    if tool_name == "list_files":
        path = tool_input.get("path", ".")
        pattern = tool_input.get("pattern", "")
        return f"{_short_path(path)} {pattern}".strip()
    if tool_name == "grep_search":
        return tool_input.get("pattern", "")
    if tool_name == "web_search":
        return tool_input.get("query", "")[:60]
    if tool_name == "web_fetch":
        return tool_input.get("url", "")[:80]
    return json.dumps(tool_input, ensure_ascii=False)[:80]


_READ_TOOLS = frozenset({"read_file", "read_image", "list_files", "grep_search", "web_search", "web_fetch"})


def _emit_server_search_result(emit, block) -> bool:
    """格式化并发射 web_search_tool_result。返回 True 表示成功处理。"""
    if block.type != "web_search_tool_result":
        return False
    content = getattr(block, "content", None)
    if isinstance(content, list) and len(content) > 0:
        lines = []
        for item in content:
            title = getattr(item, "title", "") or ""
            url = getattr(item, "url", "") or ""
            if title and url:
                lines.append(f"  {title}: {url}")
            elif url:
                lines.append(f"  {url}")
        text = "\n".join(lines) if lines else "(无搜索结果)"
        emit(EVT_TOOL_RESULT, text, {
            "tool": "web_search",
            "tool_use_id": getattr(block, "tool_use_id", ""),
        })
        return True
    if hasattr(content, "error_code"):
        emit(EVT_TOOL_RESULT, f"[搜索错误: {content.error_code}]", {
            "tool": "web_search",
            "tool_use_id": getattr(block, "tool_use_id", ""),
        })
        return True
    emit(EVT_TOOL_RESULT, "(无搜索结果)", {
        "tool": "web_search",
        "tool_use_id": getattr(block, "tool_use_id", ""),
    })
    return True


def _emit_server_fetch_result(emit, block) -> bool:
    """格式化并发射 web_fetch_tool_result。返回 True 表示成功处理。"""
    if block.type != "web_fetch_tool_result":
        return False
    content = getattr(block, "content", None)
    content_text = ""
    if content and hasattr(content, "content") and hasattr(content.content, "source"):
        src = content.content.source
        if hasattr(src, "data"):
            content_text = src.data
    elif content and hasattr(content, "error_code"):
        content_text = f"[抓取错误: {content.error_code}]"
    else:
        content_text = str(content)[:500] if content else ""
    if len(content_text) > 500:
        content_text = content_text[:500] + f"… ({len(content_text)} 字符)"
    emit(EVT_TOOL_RESULT, content_text or "(无内容)", {
        "tool": "web_fetch",
        "tool_use_id": getattr(block, "tool_use_id", ""),
    })
    return True


def _builtin_confirm(tool_name: str, tool_input: dict) -> bool:
    """单次模式内置权限检查：无外部 confirm_fn 时根据配置决定是否放行。

    规则优先级：permission_rules > permission_mode > 危险命令检测
    """
    # 1. 细粒度权限规则（最高优先级）
    rule_result = check_permission_rule(tool_name, tool_input)
    if rule_result == "allow":
        return True
    if rule_result == "deny":
        return False

    # 2. 读取类工具始终放行
    if tool_name in _READ_TOOLS:
        return True

    # 3. 根据 permission_mode 决定
    mode = get("permissions", "confirm")
    if mode == "auto-approve":
        return True
    # confirm/deny 模式下，危险操作拒绝
    if tool_name == "bash":
        return not is_dangerous(tool_input.get("command", ""))
    # 写入类工具在 confirm/deny 模式下拒绝（无人可确认）
    return False


def _stream_with_retry(client, model, max_tokens, system_prompt, tools, messages, emit,
                       max_retries=3, thinking_budget=None):
    """带重试的流式 API 调用，指数退避。

    直接迭代 stream 以正确处理事件顺序：
    server_tool_use/web_search_tool_result 在流中实时发射，保证与 text_delta 的顺序一致。
    """
    from anthropic.lib.streaming._messages import TextEvent, ParsedContentBlockStopEvent
    from anthropic.lib.streaming._types import ThinkingEvent as _ThinkingEvent
    from anthropic.types import ServerToolUseBlock, WebSearchToolResultBlock, WebFetchToolResultBlock, WebSearchResultBlock

    _thinking_streamed = False

    for attempt in range(max_retries + 1):
        # 每次重试前重置状态，避免重复输出
        _thinking_streamed = False
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
                for event in stream:
                    if isinstance(event, TextEvent):
                        emit(EVT_STREAM, event.text)
                    elif isinstance(event, _ThinkingEvent):
                        _thinking_streamed = True
                        emit(EVT_THINKING, event.snapshot)
                    elif isinstance(event, ParsedContentBlockStopEvent):
                        block = event.content_block
                        if isinstance(block, ServerToolUseBlock):
                            summary = _format_tool_input(block.name, block.input)
                            emit(EVT_TOOL_CALL, summary, {
                                "tool": block.name,
                                "input": block.input,
                                "tool_id": block.id,
                            })
                        elif isinstance(block, WebSearchToolResultBlock):
                            _emit_server_search_result(emit, block)
                        elif isinstance(block, WebFetchToolResultBlock):
                            _emit_server_fetch_result(emit, block)
                return stream.get_final_message(), _thinking_streamed
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
    verbose: bool = True,
    messages: list[dict] | None = None,
    on_interrupt: Any = None,
    confirm_fn: Any = None,
    mcp: MCPManager | None = None,
    system_prompt_override: str | None = None,
    output_fn: Callable[[str, str, dict | None], None] | None = None,
    session_id: str | None = None,
    safe_mode: bool = False,
    agent_state: Any = None,
    ask_fn: Any = None,
) -> str:
    """
    运行 Agent 完成一个任务。

    主循环由 LLM 的 stop_reason 驱动：LLM 不调工具时返回 end_turn，循环自然结束。
    用户可随时 Ctrl+C 打断。

    Args:
        user_task: 用户的任务描述
        verbose: 是否打印每步的思考过程（仅 print fallback 模式）
        messages: 外部传入的对话历史。None 创建新对话，否则追加。
        on_interrupt: 可选的回调，在中断时调用
        confirm_fn: 权限确认回调 (tool_name, tool_input) -> bool
        mcp: MCP 管理器实例，用于路由 MCP 工具调用
        system_prompt_override: 自定义 system prompt（来自 agent 切换）
        output_fn: 输出回调 (event_type, text, metadata)。为 None 时用 print。
        session_id: 当前会话 ID（用于 metrics 持久化）
        safe_mode: 安全模式，只允许读取类工具

    Returns:
        Agent 的最终回复
    """
    # 设置 agent state（若外部传入则设为当前活跃状态，否则使用全局默认）
    if agent_state is not None:
        from tools.state import set_active_state
        set_active_state(agent_state)

    # 设置 ask_fn（若外部传入）
    if ask_fn is not None:
        from tools.agent_tools import set_ask_fn
        set_ask_fn(ask_fn)

    model = get("model")
    max_tokens = get("max_tokens")

    client = _get_client()

    if messages is None:
        messages = [{"role": "user", "content": user_task}]
    else:
        messages.append({"role": "user", "content": user_task})

    # UserPromptSubmit hook：用户提交输入前触发（可阻断或注入上下文）
    try:
        prompt_results = run_hooks("UserPromptSubmit", {
            "prompt": user_task[:500],
        })
        blocking = [r for r in prompt_results
                    if "[hook exit code:" in r or "[hook 错误" in r]
        if blocking:
            emit_msg = "UserPromptSubmit hook 阻止: " + blocking[0]
            if output_fn:
                output_fn(EVT_ERROR, emit_msg, {})
            return emit_msg
    except Exception as e:
        _get_logger().warning("UserPromptSubmit hook 异常: %s: %s", type(e).__name__, e)

    iteration = 0

    _print = _make_print_event()

    def emit(event_type: str, text: str, meta: dict | None = None):
        """发送输出事件。优先 output_fn，否则 print。"""
        if output_fn:
            output_fn(event_type, text, meta)
        elif verbose:
            _print(event_type, text, meta)

    global _current_emit
    _current_emit = emit

    emit(EVT_PROGRESS, user_task, {"label": "任务"})

    # 探测服务端工具支持，动态构建工具 schema
    supported_server_tools = _probe_server_tools(client, model)
    all_tools = build_tools(supported_server_tools)
    if mcp:
        mcp_tools = mcp.get_all_tools()
        all_tools.extend(mcp_tools)

    thinking_budget = get("thinking_budget")

    try:
        while True:
            iteration += 1

            messages[:] = compress_messages(client, messages, model,
                                                force=False)
            system_prompt = system_prompt_override or build_system_prompt()
            # Prompt Cache: system prompt 加 cache_control
            system_param = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}},
            ]

            emit(EVT_PROGRESS, f"调用 LLM (轮次 {iteration})")

            # 使用流式 API，实时输出文本 token（含重试）
            t0 = time.monotonic()
            final_message, thinking_streamed = _stream_with_retry(
                client, model, max_tokens, system_param, all_tools, messages, emit,
                thinking_budget=thinking_budget,
            )
            latency_ms = (time.monotonic() - t0) * 1000

            messages.append({"role": "assistant", "content": final_message.content})

            # 日志：LLM 调用完成 + metrics 持久化
            usage = getattr(final_message, 'usage', None)
            if usage:
                _get_logger().info(
                    "LLM iteration=%d model=%s input=%d output=%d latency=%dms",
                    iteration, model, usage.input_tokens, usage.output_tokens,
                    int(latency_ms),
                )
                try:
                    cache_creation = getattr(usage, 'cache_creation_input_tokens', 0) or 0
                    cache_read = getattr(usage, 'cache_read_input_tokens', 0) or 0
                    metrics.record_call(
                        session_id=session_id,
                        model=model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        cache_read=cache_read,
                        cache_write=cache_creation,
                        latency_ms=latency_ms,
                    )
                except Exception as e:
                    _get_logger().warning("metrics 记录失败: %s: %s", type(e).__name__, e)
            stop_reason = getattr(final_message, 'stop_reason', None)
            truncated = stop_reason == "max_tokens"
            if truncated:
                emit(EVT_ERROR, f"达到最大 token 数 ({max_tokens})，回复被截断。"
                     "可用 /config max_tokens=<N> 增大限制。")

            tool_results = []
            content_blocks = final_message.content or []
            has_tool_use = (
                not truncated
                and any(b.type == "tool_use" for b in content_blocks)
            )

            for block in content_blocks:
                if block.type == "thinking":
                    if not thinking_streamed:
                        thinking_text = getattr(block, "thinking", "") or ""
                        emit(EVT_THINKING, thinking_text)

                elif block.type == "redacted_thinking":
                    pass  # 加密的 thinking 块，保留在 messages 中但不展示

                elif block.type == "text" and block.text.strip():
                    if has_tool_use:
                        # 文本已通过 EVT_STREAM 实时输出，这里只发空事件标记切换
                        emit(EVT_THINKING, "")
                    # 最终回复在循环末尾处理

                elif block.type in ("server_tool_use", "web_search_tool_result", "web_fetch_tool_result"):
                    # 服务端工具已在流式发射中处理（_stream_with_retry），跳过
                    pass

                elif block.type == "tool_use":
                    # max_tokens 截断时为不完整的 tool_use 补一个错误 tool_result
                    if truncated:
                        emit(EVT_TOOL_RESULT, "已跳过（回复被截断，tool_use 可能不完整）", {
                            "tool": block.name, "rejected": True,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "[回复被截断，tool_use 不完整]",
                        })
                        continue

                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    # PreToolUse hook（旧名 pre_tool_call 兼容）
                    hook_results = run_hooks("PreToolUse", {
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

                    # 权限确认：外部 confirm_fn 优先，否则使用内置检查
                    # safe_mode 下只允许读取类工具
                    if safe_mode and tool_name not in _READ_TOOLS:
                        emit(EVT_TOOL_RESULT, "已拒绝（安全模式）", {
                            "tool": tool_name, "rejected": True,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": "[安全模式：仅允许读取类工具]",
                        })
                        continue
                    checker = confirm_fn or _builtin_confirm
                    if not checker(tool_name, tool_input):
                        emit(EVT_TOOL_RESULT, "已拒绝（权限限制）", {
                            "tool": tool_name, "rejected": True,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": "[权限限制：此操作在当前模式下被拒绝]",
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
                        _get_logger().error("Tool %s 执行失败", tool_name, exc_info=True)
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
                        image_data = result.get("source", {})
                        media_type = image_data.get("media_type", "image/png")
                        image_b64 = image_data.get("data", "")
                        emit(EVT_TOOL_RESULT, f"[图片: {media_type}, "
                             f"{len(image_b64) // 1024}KB base64]", {
                            "tool": tool_name,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": [
                                {"type": "text", "text": f"[已读取图片: {tool_input.get('path', '')}]"},
                                {"type": "image",
                                 "source": {"type": "base64",
                                            "media_type": media_type,
                                            "data": image_b64}},
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

                        # PostToolUse hook（旧名 post_tool_call 兼容）
                        run_hooks("PostToolUse", {
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
            content_blocks = final_message.content or []
            final_text = next(
                (b.text for b in content_blocks if b.type == "text"), ""
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
            emit(EVT_RESPONSE, "", {"usage": usage_meta} if usage_meta else {})

            # Stop hook：一次完整回复后触发
            try:
                run_hooks("Stop", {
                    "iterations": str(iteration),
                    "final_text": final_text[:500],
                })
            except Exception as e:
                _get_logger().warning("Stop hook 异常: %s: %s", type(e).__name__, e)

            return final_text

    except KeyboardInterrupt:
        emit(EVT_ERROR, "任务已被用户取消")
        try:
            run_hooks("StopFailure", {"reason": "interrupted"})
        except Exception as e:
            _get_logger().warning("StopFailure hook 异常: %s: %s", type(e).__name__, e)
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


def _make_print_event():
    """创建带独立 Markdown 缓冲区的 print fallback 函数。

    每次调用 run_agent 时创建一个独立实例，buffer 为闭包局部变量，
    天然线程隔离，避免并发 Agent 交叉污染。
    """
    buffer: list[str] = []

    def flush():
        if not buffer:
            return
        full_text = "".join(buffer).strip()
        buffer.clear()
        if not full_text:
            return
        print()
        try:
            from rich.console import Console
            from rich.markdown import Markdown

            Console().print(Markdown(full_text, code_theme="default"))
        except ImportError:
            print(full_text)

    def print_event(event_type: str, text: str, meta: dict | None = None):
        meta = meta or {}

        if event_type == EVT_STREAM:
            buffer.append(text)
            return

        flush()

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

        elif event_type == EVT_ERROR:
            print(f"\n{_RED}⚠️ {text}{_RESET}")

    return print_event
