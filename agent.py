"""Agent 主循环：调用 LLM、执行工具、管理对话历史。"""

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import metrics
from config import check_permission_rule, get, is_dangerous, run_hooks
from context import build_system_blocks, compress_messages
from logger import get_logger as _get_logger
from logger import get_session_logger as _get_session_logger
from mcp import MCPManager
from tools import execute_tool
from tools.exceptions import ToolError
from tools.schemas import build_tools

# 事件类型常量
EVT_THINKING = "thinking"
EVT_TOOL_CALL = "tool_call"
EVT_TOOL_RESULT = "tool_result"
EVT_RESPONSE = "response"
EVT_PROGRESS = "progress"
EVT_ERROR = "error"
EVT_STREAM = "stream"
EVT_TRUNCATED = "truncated"  # max_tokens 截断（区别于真错误）
EVT_STREAM_REWIND = "stream_rewind"  # 流式重试前通知 UI 清空累积 buffer

# scheduler 回调桥接：用线程本地存储，避免 sub_agent 子线程污染父 agent 的 emit
_emit_local = threading.local()


def _get_current_emit() -> Callable | None:
    """获取当前线程绑定的 emit。子 agent 线程有独立 emit，不影响父线程。"""
    return getattr(_emit_local, "emit", None)


def _set_current_emit(emit: Callable | None) -> None:
    _emit_local.emit = emit


from constants import BOLD as _BOLD
from constants import CYAN as _CYAN
from constants import DIM as _DIM
from constants import GREEN as _GREEN
from constants import RED as _RED
from constants import RESET as _RESET
from constants import YELLOW as _YELLOW

# ── 网络错误类型（用于重试） ──

try:
    import httpx

    _NET_ERRORS = (
        ConnectionError,
        TimeoutError,
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
    )
except ImportError:
    _NET_ERRORS = (ConnectionError, TimeoutError)



def _bump_failure(store: OrderedDict, key: str, new_count: int, lru_max: int, freeze_threshold: int) -> None:
    """更新熔断计数并维护 LRU。

    成功或失败都会调用（失败时 new_count=count+1）；写入后若 key 存在则移到末尾，
    超过 lru_max 时丢弃最旧未访问的 key。**已达 freeze_threshold 的 key 永不淘汰**
    （否则熔断保护会被 LRU 绕过——同一失败 key 淘汰后 .get() 返回 0 重新累积）。
    """
    store[key] = new_count
    store.move_to_end(key)
    while len(store) > lru_max:
        # 从最旧开始找第一个可淘汰的（未达冻结阈值）
        oldest_key, oldest_count = next(iter(store.items()))
        if oldest_count >= freeze_threshold:
            # 最旧的已冻结，找下一个未冻结的
            evicted = False
            for k, c in list(store.items()):
                if c < freeze_threshold:
                    store.pop(k)
                    evicted = True
                    break
            if not evicted:
                # 全部已冻结，无法淘汰（极端场景），停止
                break
        else:
            store.popitem(last=False)


# 工具失败结果前缀（execute_tool / mcp.call_tool catch 异常后返回的字符串）
_ERROR_RESULT_PREFIXES = ("[错误]", "[MCP 错误]")


def _is_error_result(result: str) -> bool:
    """检测 execute_tool / mcp.call_tool 返回的字符串是否表示失败。

    execute_tool 和 mcp.call_tool 内部已 catch 所有异常返回 "[错误] ..." 字符串，
    所以 agent.py 不能再靠 try/except ToolError 触发熔断；必须显式检查字符串前缀。
    """
    return result.startswith(_ERROR_RESULT_PREFIXES)


def _normalize_confirm_result(result) -> tuple[bool, str | None, str]:
    """兼容 bool / 2-tuple / 3-tuple 返回的 confirm_fn 结果。

    返回 (approved, reason, source)：
    - approved: 是否允许执行
    - reason: 用户拒绝理由（仅 user source 且用户填了才有）
    - source: "user"（用户主动操作） | "system"（permission_rule/mode/safe_mode/超时）

    兼容性：
    - 旧 bool → (bool, None, "system")，保守判定为系统，文案走"权限限制"
    - 2-tuple (approved, reason) → source 默认 "user"（Web 早期返回格式）
    - 3-tuple (approved, reason, source) → 显式指定
    """
    if isinstance(result, tuple):
        approved = bool(result[0]) if result else False
        reason = result[1] if len(result) >= 2 else None
        if reason is not None:
            reason = str(reason).strip() or None
        source = result[2] if len(result) >= 3 else "user"
        if source not in ("user", "system"):
            source = "user"
        return approved, reason, source
    return bool(result), None, "system"


def _finalize_pending_tool_uses(messages: list[dict], llm_messages: list[dict], reason: str) -> None:
    """早退路径兜底：若 messages 末尾是含 tool_use 的 assistant 消息，合成对应 tool_result。

    否则下次 load_session 后调用 LLM 会被 API 拒绝（"messages: tool_use without tool_result"）。
    用于：连续截断早退、pause_turn 早退、refusal 早退、迭代上限早退、KeyboardInterrupt。
    """
    if not messages:
        return
    last = messages[-1]
    if last.get("role") != "assistant":
        return
    content = last["content"]
    if not isinstance(content, list):
        return
    pending = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype is None and isinstance(block, dict):
            btype = block.get("type")
        if btype != "tool_use":
            continue
        block_id = getattr(block, "id", None)
        if block_id is None and isinstance(block, dict):
            block_id = block.get("id")
        if not block_id:
            continue
        pending.append(
            {
                "type": "tool_result",
                "tool_use_id": block_id,
                "content": reason,
            }
        )
    if not pending:
        return
    msg = {"role": "user", "content": pending}
    messages.append(msg)
    # llm_messages 可能浅拷贝自 messages，但其引用独立——只在仍包含同一末尾 assistant 时追加
    if llm_messages and llm_messages[-1] is last:
        llm_messages.append(msg)


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


def _builtin_confirm(tool_name: str, tool_input: dict) -> tuple[bool, str | None, str]:
    """单次模式内置权限检查：无外部 confirm_fn 时根据配置决定是否放行。

    返回 (approved, reason, source)，所有拒绝都来自系统规则/配置，source 恒为 "system"。
    规则优先级：permission_rules > permission_mode > 危险命令检测
    """
    # 1. 细粒度权限规则（最高优先级）
    rule_result = check_permission_rule(tool_name, tool_input)
    if rule_result == "allow":
        return (True, None, "system")
    if rule_result == "deny":
        return (False, None, "system")

    # 2. 读取类工具始终放行
    if tool_name in _READ_TOOLS:
        return (True, None, "system")

    # 3. 根据 permission_mode 决定
    mode = get("permissions", "confirm")
    if mode == "auto-approve":
        return (True, None, "system")
    # confirm/deny 模式下，危险操作拒绝
    if tool_name == "bash":
        return (not is_dangerous(tool_input.get("command", "")), None, "system")
    # 写入类工具在 confirm/deny 模式下拒绝（无人可确认）
    return (False, None, "system")


def _stream_with_retry(
    provider, model, max_tokens, system_prompt, tools, messages, emit, max_retries=3, logger=None
):
    """带重试的流式 API 调用，指数退避。

    使用 provider.stream() 获取标准化事件流，重试逻辑捕获统一异常类型。
    """
    from providers.base import ProviderAPIError, ProviderAuthError, ProviderRateLimitError

    _logger = logger or _get_logger()
    thinking_budget_kw = {}
    from config import get as _get_cfg
    _tb = _get_cfg("thinking_budget")
    if _tb:
        thinking_budget_kw["thinking_budget"] = _tb

    for attempt in range(max_retries + 1):
        try:
            _logger.debug(
                "LLM 请求: model=%s max_tokens=%d messages=%d tools=%d attempt=%d/%d",
                model,
                max_tokens,
                len(messages),
                len(tools),
                attempt + 1,
                max_retries + 1,
            )
            _logger.debug(
                "LLM system_prompt (%d chars): %s",
                len(system_prompt[0]["text"]) if system_prompt else 0,
                system_prompt[0]["text"] if system_prompt else "",
            )
            try:
                _logger.debug("LLM messages 全量: %s", json.dumps(messages, ensure_ascii=False))
            except TypeError:
                _logger.debug("LLM messages 全量（序列化失败，转为 fallback）: %s", str(messages)[:10000])

            stream_tool_ids = set()  # 收集流式阶段已发射的 tool_call id，主循环据此跳过重复
            gen = provider.stream(
                messages=messages,
                system=system_prompt,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                **thinking_budget_kw,
            )
            for event in gen:
                if event.type == "text":
                    _logger.debug("LLM stream text: %s", event.text[:200])
                    emit(EVT_STREAM, event.text)
                elif event.type == "thinking":
                    emit(EVT_THINKING, event.text)
                elif event.type == "tool_call":
                    stream_tool_ids.add(event.tool_id)
                    summary = _format_tool_input(event.tool_name, event.tool_input)
                    emit(
                        EVT_TOOL_CALL,
                        summary,
                        {
                            "tool": event.tool_name,
                            "input": event.tool_input,
                            "tool_id": event.tool_id,
                        },
                    )
                elif event.type == "server_tool_use":
                    summary = _format_tool_input(event.tool_name, event.tool_input)
                    emit(
                        EVT_TOOL_CALL,
                        summary,
                        {
                            "tool": event.tool_name,
                            "input": event.tool_input,
                            "tool_id": event.tool_id,
                        },
                    )
                elif event.type in ("web_search_result", "web_fetch_result"):
                    emit(EVT_TOOL_RESULT, f"({event.type})", {"tool": event.tool_name})

            response = provider.get_response()
            if response is None:
                raise RuntimeError("Provider 未返回响应")

            _logger.debug(
                "LLM 响应: stop_reason=%s content_blocks=%d",
                response.stop_reason,
                len(response.content),
            )
            for i, block in enumerate(response.content):
                if block.get("type") == "text":
                    _logger.debug("LLM 响应 block[%d] text (%d chars): %s", i, len(block.get("text", "")), block.get("text", ""))
                elif block.get("type") == "thinking":
                    _logger.debug("LLM 响应 block[%d] thinking (%d chars): %s", i, len(block.get("thinking", "")), block.get("thinking", ""))
                elif block.get("type") == "tool_use":
                    _logger.debug(
                        "LLM 响应 block[%d] tool_use: %s input=%s",
                        i,
                        block.get("name", ""),
                        json.dumps(block.get("input", {}), ensure_ascii=False),
                    )
                elif block.get("type") == "server_tool_use":
                    _logger.debug(
                        "LLM 响应 block[%d] server_tool_use: %s input=%s",
                        i,
                        block.get("name", ""),
                        json.dumps(block.get("input", {}), ensure_ascii=False)[:300],
                    )
                else:
                    _logger.debug("LLM 响应 block[%d] %s", i, block.get("type", "?"))

            return response, stream_tool_ids

        except ProviderRateLimitError as e:
            _logger.debug("LLM RateLimitError attempt=%d/%d: %s", attempt + 1, max_retries + 1, e)
            if attempt >= max_retries:
                raise
            wait = 2**attempt
            emit(EVT_STREAM_REWIND, "")
            emit(EVT_ERROR, f"Rate limited, retrying in {wait}s...")
            time.sleep(wait)
        except ProviderAPIError as e:
            _logger.debug(
                "LLM APIStatusError status=%d attempt=%d/%d: %s", e.status_code, attempt + 1, max_retries + 1, e
            )
            if e.status_code == 401:
                raise PermissionError(
                    "API 认证失败 (401)。请检查 API Key 是否正确配置。\n"
                    "  配置文件: ~/.octopus/config.json\n"
                    "  环境变量: OCTOPUS_API_KEY"
                ) from e
            if e.status_code >= 500 and attempt < max_retries:
                wait = 2**attempt
                emit(EVT_STREAM_REWIND, "")
                emit(EVT_ERROR, f"Server error {e.status_code}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except ProviderAuthError:
            raise PermissionError(
                "API 认证失败 (401)。请检查 API Key 是否正确配置。\n"
                "  配置文件: ~/.octopus/config.json\n"
                "  环境变量: OCTOPUS_API_KEY"
            )
        except _NET_ERRORS as e:
            _logger.debug("LLM 网络错误 attempt=%d/%d: %s: %s", attempt + 1, max_retries + 1, type(e).__name__, e)
            if attempt < max_retries:
                wait = 2**attempt
                emit(EVT_STREAM_REWIND, "")
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
    system_prompt_override: str | list[dict] | None = None,
    agent_persona: str | None = None,
    ui_capabilities: str | None = None,
    plan_hint: str | None = None,
    output_fn: Callable[[str, str, dict | None], None] | None = None,
    session_id: str | None = None,
    safe_mode: bool = False,
    agent_state: Any = None,
    ask_fn: Any = None,
    skip_user_append: bool = False,
    force_compact: bool = False,
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
        system_prompt_override: 完全替换主系统提示词（仅 Plan 模式等特殊场景使用，
            会丢失 L1/L2/L3 三层缓存和所有工具规范，慎用）
        agent_persona: agent 人设追加层（来自 /agent 切换）。在 L1/L2/L3 三层之后
            追加为独立 cache 块，不替换主系统提示词，保留所有工具规范、记忆、项目指令
        ui_capabilities: 前端 UI 能力描述（来自 constants.UI_CAPABILITIES_*）。告诉 LLM
            当前 UI 支持哪些渲染能力（如 mermaid、markdown 表格等），让其自适应输出格式。
            作为独立 cache 块追加（在 agent_persona 之前）
        plan_hint: Plan 模式约束追加层。与 agent_persona 独立（不混进"Agent 人设"标题），
            让 LLM 清楚区分"人设指令"和"模式约束"。同样拼到 L3 末尾
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

    # 优先用 session 级模型/提供商（Web UI 多会话隔离）
    session_model = getattr(agent_state, "model", None) if agent_state else None
    session_provider = getattr(agent_state, "provider", None) if agent_state else None
    model = session_model or get("model")
    max_tokens = get("max_tokens")

    _log = _get_session_logger(session_id)
    _log.debug("用户输入: %s", user_task)

    from providers import get_provider

    provider = get_provider(model, provider_name=session_provider)

    if messages is None:
        messages = [{"role": "user", "content": user_task}]
    elif skip_user_append:
        pass  # 调用方已手动将 user message 加入 messages
    else:
        messages.append({"role": "user", "content": user_task})

    # 兜底：清理历史 messages 中可能存在的孤儿 tool_use/tool_result。
    # 多轮对话中前一轮异常退出（API 错误、外部异常等）可能残留 tool_use 无 tool_result，
    # 直接调用 LLM 会触发 400 "tool_use without tool_result"。
    # _finalize_orphan_tool_uses 是幂等的，对正常 messages 无副作用。
    try:
        from session import _finalize_orphan_tool_uses

        _finalize_orphan_tool_uses(messages)
    except Exception as e:
        _log.warning("入口处 _finalize_orphan_tool_uses 失败: %s: %s", type(e).__name__, e)

    # UserPromptSubmit hook：用户提交输入前触发（可阻断或注入上下文）
    try:
        prompt_results = run_hooks(
            "UserPromptSubmit",
            {
                "prompt": user_task[:500],
            },
        )
        blocking = [r for r in prompt_results if "[hook exit code:" in r or "[hook 错误" in r]
        if blocking:
            emit_msg = "UserPromptSubmit hook 阻止: " + blocking[0]
            if output_fn:
                output_fn(EVT_ERROR, emit_msg, {})
            return emit_msg
    except Exception as e:
        _log.warning("UserPromptSubmit hook 异常: %s: %s", type(e).__name__, e)

    # LLM 视图：可被 compress_messages 压缩，外部 messages 保持全量用于持久化和 UI 展示。
    # 顶层浅拷贝：content blocks 不会被原地修改（compress_messages / _truncate_tool_results 均为纯函数）。
    llm_messages: list[dict] = list(messages)

    iteration = 0

    _print = _make_print_event()

    def emit(event_type: str, text: str, meta: dict | None = None):
        """发送输出事件。优先 output_fn，否则 print。"""
        if output_fn:
            output_fn(event_type, text, meta)
        elif verbose:
            _print(event_type, text, meta)

    _set_current_emit(emit)

    emit(EVT_PROGRESS, user_task, {"label": "任务"})

    _log.info("agent 启动: model=%s session=%s iteration=0", model, session_id)

    # 探测服务端工具支持，动态构建工具 schema
    supported_server_tools = provider.probe_server_tools(model)
    _log.debug("服务端工具支持: %s", supported_server_tools or "(无)")
    all_tools = build_tools(supported_server_tools)
    _log.debug(
        "工具 schema 数量: %d, 工具列表: %s", len(all_tools), [t.get("name", t.get("type", "?")) for t in all_tools]
    )
    _log.debug("工具 schema 全量: %s", json.dumps(all_tools, ensure_ascii=False))
    if mcp:
        mcp_tools = mcp.get_all_tools()
        all_tools.extend(mcp_tools)
        _log.debug("MCP 工具数量: %d, 列表: %s", len(mcp_tools), [t.get("name", "?") for t in mcp_tools])

    # 工具数组缓存标记：对最后一个工具加 cache_control，让 API 缓存整个 tools 定义（仅 Anthropic）
    if all_tools and getattr(provider, '_name', '') == 'anthropic':
        all_tools[-1] = {**all_tools[-1], "cache_control": {"type": "ephemeral"}}

    thinking_budget = get("thinking_budget")
    max_iterations = get("max_iterations") or 50
    tool_failure_threshold = get("tool_failure_threshold") or 3

    _truncation_streak = 0  # 连续 max_tokens 截断计数，超过 3 次停止续写
    _pause_streak = 0  # 连续 pause_turn 计数，超过 5 次停止续写
    # 熔断计数：key=tool+input 哈希，value=连续失败次数。LRU 限制防止长会话内存增长
    _tool_failure_counts: OrderedDict[str, int] = OrderedDict()
    _TOOL_FAILURE_LRU_MAX = 256
    # 用户拒绝计数：同一 key 连续被用户拒绝 ≥2 次则停止本轮 agent。
    # 与失败计数独立，避免一次失败就触发；成功后同步清零
    _tool_denial_counts: OrderedDict[str, int] = OrderedDict()
    _DENIAL_FREEZE_THRESHOLD = 2

    try:
        while True:
            iteration += 1

            # 迭代上限：防 LLM 陷入 tool→result→tool 死循环
            if iteration > max_iterations:
                _log.warning("达到迭代上限 %d，自动停止", max_iterations)
                emit(
                    EVT_ERROR,
                    f"已达到迭代上限（{max_iterations} 轮），自动停止。可用 /config max_iterations=<N> 调整。",
                )
                emit(EVT_RESPONSE, "", {})
                _finalize_pending_tool_uses(messages, llm_messages, "[达到迭代上限，未执行]")
                return f"(达到迭代上限 {max_iterations} 轮)"

            # force_compact 只在第一次迭代生效（用户显式 /compact 后触发）
            _force_this_iter = force_compact and iteration == 1
            _pre_compress_count = len(llm_messages)
            _pre_compress_chars = sum(len(str(m)) for m in llm_messages)
            llm_messages = compress_messages(provider, llm_messages, model, force=_force_this_iter)
            _post_compress_chars = sum(len(str(m)) for m in llm_messages)
            _log.debug(
                "iteration=%d 压缩: llm_messages %d→%d, chars %d→%d (%s%.0f%%)",
                iteration,
                _pre_compress_count,
                len(llm_messages),
                _pre_compress_chars,
                _post_compress_chars,
                "+" if _post_compress_chars > _pre_compress_chars else "",
                (_post_compress_chars / _pre_compress_chars * 100) if _pre_compress_chars else 0,
            )
            # 构建系统提示词
            # - system_prompt_override: 完全替换（仅 Plan 模式等特殊场景，会丢失 L1/L2/L3 三层缓存）
            # - ui_capabilities / agent_persona: 拼接到 L3 末尾，复用 L3 的 cache_control
            #   不增加 cache breakpoint（Anthropic API 限制 4 块：L1+L2+L3+tools 已满）
            if system_prompt_override:
                if isinstance(system_prompt_override, list):
                    system_param = list(system_prompt_override)
                else:
                    block = {"type": "text", "text": system_prompt_override}
                    if getattr(provider, '_name', '') == 'anthropic':
                        block["cache_control"] = {"type": "ephemeral"}
                    system_param = [block]
            else:
                system_param = build_system_blocks(
                    provider_name=getattr(provider, '_name', 'anthropic'),
                    model_name=model,
                    session_provider=session_provider,
                )

                # ui_capabilities + agent_persona + plan_hint 拼到 L3 末尾（L3 是 system_param 最后一项）
                extras: list[str] = []
                if ui_capabilities:
                    extras.append(ui_capabilities)
                if agent_persona:
                    extras.append(
                        "## 当前 Agent 人设\n\n"
                        "请遵循以下人设指令。这些人设是对默认行为规范的**追加**，"
                        "若与上面的工具策略/安全规则/输出规范冲突，默认规范优先。\n\n" + agent_persona
                    )
                if plan_hint:
                    extras.append(plan_hint)
                if extras and system_param:
                    last_idx = len(system_param) - 1
                    last_block = system_param[last_idx]
                    system_param[last_idx] = {
                        **last_block,
                        "text": last_block["text"] + "\n\n---\n\n" + "\n\n---\n\n".join(extras),
                    }
                elif extras and not system_param:
                    _log.warning("system_param 为空，ui/persona/plan_hint 被丢弃")

            emit(EVT_PROGRESS, f"调用 LLM (轮次 {iteration})")

            # 使用流式 API，实时输出文本 token（含重试）
            t0 = time.monotonic()
            response, stream_emitted_tool_ids = _stream_with_retry(
                provider,
                model,
                max_tokens,
                system_param,
                all_tools,
                llm_messages,
                emit,
                logger=_log,
            )
            latency_ms = (time.monotonic() - t0) * 1000

            # response.content 已是 dict 格式，直接使用
            assistant_msg = {"role": "assistant", "content": response.content}
            messages.append(assistant_msg)
            llm_messages.append(assistant_msg)

            # 日志：LLM 调用完成 + metrics 持久化
            usage = response.usage
            if usage:
                _input_tokens = usage.get("input_tokens", 0) or 0
                _output_tokens = usage.get("output_tokens", 0) or 0
                _log.info(
                    "LLM iteration=%d model=%s input=%d output=%d latency=%dms",
                    iteration,
                    model,
                    _input_tokens,
                    _output_tokens,
                    int(latency_ms),
                )
                try:
                    cache_creation = usage.get("cache_creation_tokens", 0) or 0
                    cache_read = usage.get("cache_read_tokens", 0) or 0
                    _metrics_record = metrics.record_call(
                        session_id=session_id,
                        model=model,
                        input_tokens=_input_tokens,
                        output_tokens=_output_tokens,
                        cache_read=cache_read,
                        cache_write=cache_creation,
                        latency_ms=latency_ms,
                    )
                except Exception as e:
                    _log.warning("metrics 记录失败: %s: %s", type(e).__name__, e)
                    _metrics_record = None
            else:
                _metrics_record = None
            stop_reason = response.stop_reason
            _log.debug("assistant message 追加到 messages, stop_reason=%s", stop_reason)

            # refusal: 模型拒绝（安全原因），直接结束
            if stop_reason == "refusal":
                refusal_text = ""
                for b in response.content:
                    if b.get("type") == "text":
                        refusal_text = b.get("text", "")
                        break
                if not refusal_text:
                    refusal_text = "(模型拒绝执行，stop_reason=refusal，无文本说明)"
                _log.warning("模型拒绝: %s", refusal_text[:200])
                emit(EVT_ERROR, f"模型拒绝执行：{refusal_text[:200]}")
                # 与正常 end_turn 一样补 usage_meta，让 UI 层统计完整
                _usage_meta: dict | None = None
                if usage:
                    _usage_meta = {
                        "input_tokens": usage.get("input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                    }
                    _cc = usage.get("cache_creation_tokens", 0) or 0
                    _cr = usage.get("cache_read_tokens", 0) or 0
                    if _cc or _cr:
                        _usage_meta["cache_creation_tokens"] = _cc
                        _usage_meta["cache_read_tokens"] = _cr
                emit(EVT_RESPONSE, "", {"usage": _usage_meta} if _usage_meta else {})
                _finalize_pending_tool_uses(messages, llm_messages, "[模型拒绝，未执行]")
                return refusal_text

            truncated = stop_reason == "max_tokens"
            if truncated:
                _truncation_streak += 1
                if _truncation_streak > 3:
                    _log.warning("连续 %d 次截断，停止续写", _truncation_streak)
                    emit(
                        EVT_ERROR,
                        f"已连续 {_truncation_streak} 次截断，停止续写。建议 /config max_tokens=<N> 增大限制。",
                    )
                    # 直接返回残缺 final_text，避免 fall-through 后 tool_results continue
                    # 导致"emit EVT_ERROR 表示停止"与实际继续下一轮 LLM 调用矛盾
                    emit(EVT_RESPONSE, "", {})
                    final_text = next(
                        (
                            b.get("text", "")
                            for b in response.content
                            if b.get("type") == "text"
                        ),
                        "",
                    )
                    # 兜底：若截断时最后一个 block 是不完整 tool_use，messages[-1] 会留孤儿 tool_use。
                    # 这里通过 _finalize_pending_tool_uses 合成 tool_result 防止会话被永久污染
                    _finalize_pending_tool_uses(messages, llm_messages, "[回复被截断，未执行]")
                    return final_text or "(连续截断，回复不完整)"
                else:
                    emit(
                        EVT_TRUNCATED,
                        f"达到最大 token 数（{max_tokens}），将请求续写（第 {_truncation_streak} 次）。"
                        f"可用 /config max_tokens=<N> 增大限制。",
                    )
            else:
                _truncation_streak = 0  # 重置连续计数

            tool_results = []
            content_blocks = response.content

            # 精准识别最后一个不完整 tool_use：API 保证 content_blocks 中 tool_use 都是合法 JSON，
            # 但 max_tokens 截断时最后一个 block 若为 tool_use，input 字段可能不完整
            last_block = content_blocks[-1] if content_blocks else None
            last_block_is_truncated_tool_use = (
                truncated and last_block is not None and last_block.get("type") == "tool_use"
            )
            has_tool_use = any(b.get("type") == "tool_use" for b in content_blocks)

            for block in content_blocks:
                if block.get("type") == "thinking":
                    if not response.thinking_streamed:
                        thinking_text = block.get("thinking", "") or ""
                        emit(EVT_THINKING, thinking_text)

                elif block.get("type") == "redacted_thinking":
                    pass  # 加密的 thinking 块，保留在 messages 中但不展示

                elif block.get("type") == "text" and block.get("text", "").strip():
                    if has_tool_use:
                        # 文本已通过 EVT_STREAM 实时输出，这里只发空事件标记切换
                        emit(EVT_THINKING, "")
                    # 最终回复在循环末尾处理

                elif block.get("type") in ("server_tool_use", "web_search_tool_result", "web_fetch_tool_result"):
                    # 服务端工具已在流式发射中处理（_stream_with_retry），跳过
                    pass

                elif block.get("type") == "tool_use":
                    # 仅跳过最后一个可能不完整的 tool_use（其他 tool_use 完整可执行）
                    if block is last_block and last_block_is_truncated_tool_use:
                        emit(
                            EVT_TOOL_RESULT,
                            "已跳过（回复被截断，最后一个 tool_use 可能不完整）",
                            {
                                "tool": block.get("name", ""),
                                "rejected": True,
                                "tool_id": block.get("id", ""),
                            },
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.get("id", ""),
                                "content": "[回复被截断，最后一个 tool_use 不完整]",
                            }
                        )
                        continue

                    tool_name = block.get("name", "")
                    tool_input = block.get("input", {})
                    # 防御：第三方 provider 偶尔返回 input=None 或非 dict（应为 dict 但不保证）
                    if not isinstance(tool_input, dict):
                        _log.warning("tool_use.input 非 dict: type=%s, value=%r", type(tool_input).__name__, tool_input)
                        tool_input = {}
                    tool_id = block.get("id", "")

                    # PreToolUse hook（旧名 pre_tool_call 兼容）
                    hook_results = run_hooks(
                        "PreToolUse",
                        {
                            "tool": tool_name,
                            "input": json.dumps(tool_input, ensure_ascii=False)[:500],
                        },
                    )
                    blocked = False
                    for hr in hook_results:
                        if "[hook exit code:" in hr or "[hook 错误" in hr:
                            _log.debug("tool %s 被 PreToolUse hook 阻止: %s", tool_name, hr)
                            emit(
                                EVT_TOOL_RESULT,
                                f"Hook 阻止: {hr}",
                                {
                                    "tool": tool_name,
                                    "rejected": True,
                                    "tool_id": tool_id,
                                },
                            )
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": f"[Hook 阻止执行] {hr}",
                                }
                            )
                            blocked = True
                            break
                    if blocked:
                        continue

                    # 熔断检查：同一 (tool, input) 连续失败超阈值则跳过，避免 LLM 反复重试
                    # 提到 EVT_TOOL_CALL 之前，避免 UI 闪现"假调用"
                    _fc_payload = json.dumps(
                        {"tool": tool_name, "input": tool_input},
                        sort_keys=True,
                        ensure_ascii=False,
                        default=str,
                    )
                    _fc_key = hashlib.md5(_fc_payload.encode()).hexdigest()
                    _fc_count = _tool_failure_counts.get(_fc_key, 0)
                    if _fc_count >= tool_failure_threshold:
                        _log.warning("tool %s 已熔断（连续失败 %d 次）", tool_name, _fc_count)
                        emit(
                            EVT_TOOL_RESULT,
                            f"已熔断（连续失败 {_fc_count} 次，跳过执行）",
                            {"tool": tool_name, "rejected": True, "tool_id": tool_id},
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": f"[已熔断：同一调用连续失败 {_fc_count} 次，建议换思路]",
                            }
                        )
                        continue

                    # OpenAI 兼容 provider 在流式阶段已发射 EVT_TOOL_CALL，跳过重复
                    summary = _format_tool_input(tool_name, tool_input)
                    if tool_id not in stream_emitted_tool_ids:
                        emit(
                            EVT_TOOL_CALL,
                            summary,
                            {
                                "tool": tool_name,
                                "input": tool_input,
                                "tool_id": tool_id,
                            },
                        )

                    # 权限确认：外部 confirm_fn 优先，否则使用内置检查
                    # safe_mode 下只允许读取类工具
                    if safe_mode and tool_name not in _READ_TOOLS:
                        _log.debug(
                            "tool %s 被安全模式拒绝: input=%s",
                            tool_name,
                            json.dumps(tool_input, ensure_ascii=False)[:300],
                        )
                        emit(
                            EVT_TOOL_RESULT,
                            "已拒绝（安全模式）",
                            {
                                "tool": tool_name,
                                "rejected": True,
                                "tool_id": tool_id,
                            },
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": "[安全模式：仅允许读取类工具]",
                            }
                        )
                        continue
                    checker = confirm_fn or _builtin_confirm
                    approved, deny_reason, deny_source = _normalize_confirm_result(checker(tool_name, tool_input))
                    if not approved:
                        _log.debug(
                            "tool %s 被拒绝: input=%s source=%s reason=%s",
                            tool_name,
                            json.dumps(tool_input, ensure_ascii=False)[:300],
                            deny_source,
                            deny_reason,
                        )

                        # 仅"用户主动拒绝"才累加熔断计数（系统规则拒绝不算用户意愿）
                        if deny_source == "user":
                            _denial_count = _tool_denial_counts.get(_fc_key, 0)
                            if _denial_count + 1 >= _DENIAL_FREEZE_THRESHOLD:
                                _log.warning(
                                    "tool %s 连续被用户拒绝熔断（%d 次）",
                                    tool_name,
                                    _denial_count + 1,
                                )
                                emit(
                                    EVT_ERROR,
                                    f"连续被用户拒绝（{_denial_count + 1} 次），停止本轮",
                                )
                                # 取当前 assistant 消息的文本作为最终回复（与正常 end_turn 路径一致）
                                final_text = next(
                                    (
                                        b.get("text", "")
                                        for b in response.content
                                        if b.get("type") == "text"
                                    ),
                                    "",
                                ) or "[连续被用户拒绝，已停止]"
                                emit(EVT_RESPONSE, final_text)
                                # 本次循环的 tool_results 还没 append 到 messages 就 return，
                                # 会留下孤儿 tool_use（下次 load_session 后 API 报 400）
                                _finalize_pending_tool_uses(
                                    messages, llm_messages, "[连续被用户拒绝，未执行]"
                                )
                                return final_text

                            _bump_failure(
                                _tool_denial_counts,
                                _fc_key,
                                _denial_count + 1,
                                _TOOL_FAILURE_LRU_MAX,
                                _DENIAL_FREEZE_THRESHOLD,
                            )

                        # 文案区分：用户主动拒绝（带/不带理由）vs 系统规则拒绝
                        if deny_source == "user" and deny_reason:
                            content = (
                                f"[用户拒绝了此操作，理由：{deny_reason}。"
                                "不要重试同一操作，请根据理由调整或询问用户]"
                            )
                        elif deny_source == "user":
                            content = (
                                "[用户拒绝了此操作。不要重试同一操作，"
                                "如需继续请询问用户或换方案]"
                            )
                        else:
                            content = "[权限限制：此操作在当前模式下被拒绝]"

                        emit(
                            EVT_TOOL_RESULT,
                            "已拒绝",
                            {
                                "tool": tool_name,
                                "rejected": True,
                                "tool_id": tool_id,
                            },
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": content,
                            }
                        )
                        continue

                    _log.info("tool 调用: %s input=%s", tool_name, summary[:120])

                    # 路由：内置工具 or MCP 工具
                    # 注意：execute_tool / mcp.call_tool 内部已 catch 异常返回 "[错误] ..." 字符串，
                    # 因此下面的 try/except ToolError 仅捕获 SDK 路径之外的罕见异常；
                    # 真正的失败检测靠下面的 _is_error_result 判定字符串前缀。
                    t_tool = time.monotonic()
                    try:
                        if mcp and mcp.has_tool(tool_name):
                            result = mcp.call_tool(tool_name, tool_input)
                        else:
                            result = execute_tool(tool_name, tool_input, output_fn=output_fn)
                    except ToolError as e:
                        # 防御性兜底（execute_tool 当前不抛，但保留以应对未来重构）
                        _log.warning("tool 执行失败(ToolError): %s error=%s", tool_name, e.message)
                        _bump_failure(
                            _tool_failure_counts,
                            _fc_key,
                            _fc_count + 1,
                            _TOOL_FAILURE_LRU_MAX,
                            tool_failure_threshold,
                        )
                        error_msg = f"[错误] {e.message}"
                        emit(EVT_TOOL_RESULT, error_msg, {"tool": tool_name, "tool_id": tool_id})
                        tool_results.append({"type": "tool_result", "tool_use_id": tool_id, "content": error_msg})
                        continue
                    except Exception as e:
                        _log.error("Tool %s 执行失败", tool_name, exc_info=True)
                        _bump_failure(
                            _tool_failure_counts,
                            _fc_key,
                            _fc_count + 1,
                            _TOOL_FAILURE_LRU_MAX,
                            tool_failure_threshold,
                        )
                        error_msg = f"[错误] {type(e).__name__}: {str(e)[:200]}"
                        emit(EVT_TOOL_RESULT, error_msg, {"tool": tool_name, "tool_id": tool_id})
                        tool_results.append({"type": "tool_result", "tool_use_id": tool_id, "content": error_msg})
                        continue

                    _log.info("tool 完成: %s cost=%dms", tool_name, int((time.monotonic() - t_tool) * 1000))

                    # 失败检测：execute_tool/mcp 返回 "[错误]" / "[MCP 错误]" 前缀视为失败，触发熔断
                    if isinstance(result, str) and _is_error_result(result):
                        _bump_failure(
                            _tool_failure_counts,
                            _fc_key,
                            _fc_count + 1,
                            _TOOL_FAILURE_LRU_MAX,
                            tool_failure_threshold,
                        )
                    else:
                        # 成功 → 清除熔断计数
                        _tool_failure_counts.pop(_fc_key, None)
                        _tool_denial_counts.pop(_fc_key, None)

                    # 处理多模态结果（如 read_image 返回图片）
                    if isinstance(result, dict) and result.get("type") == "image":
                        image_data = result.get("source", {})
                        media_type = image_data.get("media_type", "image/png")
                        image_b64 = image_data.get("data", "")
                        emit(
                            EVT_TOOL_RESULT,
                            f"[图片: {media_type}, {len(image_b64) // 1024}KB base64]",
                            {
                                "tool": tool_name,
                                "tool_id": tool_id,
                            },
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": [
                                    {"type": "text", "text": f"[已读取图片: {tool_input.get('path', '')}]"},
                                    {
                                        "type": "image",
                                        "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                                    },
                                ],
                            }
                        )
                    else:
                        result_preview = str(result)[:300].replace("\n", " ")
                        if len(str(result)) > 300:
                            result_preview += f"... ({len(str(result))} chars)"
                        _log.debug(
                            "tool %s result 全量 (%d chars): %s", tool_name, len(str(result)), str(result)[:10000]
                        )
                        emit(
                            EVT_TOOL_RESULT,
                            result_preview,
                            {
                                "tool": tool_name,
                                "tool_id": tool_id,
                                "full_result": result,
                            },
                        )

                        # PostToolUse hook（旧名 post_tool_call 兼容）
                        run_hooks(
                            "PostToolUse",
                            {
                                "tool": tool_name,
                                "result_preview": result_preview[:200],
                            },
                        )

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": result,
                            }
                        )

            if tool_results:
                _log.debug(
                    "tool_results 追加到 messages, 数量=%d: %s",
                    len(tool_results),
                    json.dumps(tool_results, ensure_ascii=False)[:3000],
                )
                tool_results_msg = {"role": "user", "content": tool_results}
                messages.append(tool_results_msg)
                llm_messages.append(tool_results_msg)
                continue

            # pause_turn 连续计数（独立于截断 streak）
            if stop_reason == "pause_turn":
                _pause_streak += 1
                if _pause_streak > 5:
                    _log.warning("连续 %d 次 pause_turn，停止续写", _pause_streak)
                    emit(
                        EVT_ERROR,
                        f"已连续 {_pause_streak} 次 pause_turn，停止续写。模型可能陷入等待外部状态的死循环。",
                    )
                    emit(EVT_RESPONSE, "", {})
                    final_text = next(
                        (
                            b.get("text", "")
                            for b in response.content
                            if b.get("type") == "text"
                        ),
                        "",
                    )
                    _finalize_pending_tool_uses(messages, llm_messages, "[连续 pause_turn，未执行]")
                    return final_text or "(连续 pause_turn，回复不完整)"
            else:
                _pause_streak = 0  # 非 pause_turn 重置

            # 截断（max_tokens）或 pause_turn：追加 "请继续" 触发续写
            # 连续截断 > 3 次则停止续写（已在上面 emit EVT_ERROR）
            if (truncated and _truncation_streak <= 3) or stop_reason == "pause_turn":
                continue_msg = {"role": "user", "content": "请继续"}
                messages.append(continue_msg)
                llm_messages.append(continue_msg)
                _log.info("stop_reason=%s，追加 '请继续' 触发续写", stop_reason)
                continue

            # 最终回复（文本已通过 EVT_STREAM 实时输出，这里只发换行收尾）
            content_blocks = response.content
            final_text = next((b.get("text", "") for b in content_blocks if b.get("type") == "text"), "")
            usage = response.usage
            usage_meta = {}
            if usage:
                usage_meta["input_tokens"] = usage.get("input_tokens")
                usage_meta["output_tokens"] = usage.get("output_tokens")
                cache_creation = usage.get("cache_creation_tokens", 0) or 0
                cache_read = usage.get("cache_read_tokens", 0) or 0
                if cache_creation or cache_read:
                    usage_meta["cache_creation_tokens"] = cache_creation
                    usage_meta["cache_read_tokens"] = cache_read
                if _metrics_record and "cost_usd" in _metrics_record:
                    usage_meta["cost_usd"] = _metrics_record["cost_usd"]
            else:
                usage_meta = None
            emit(EVT_RESPONSE, "", {"usage": usage_meta} if usage_meta else {})

            _log.info("agent 完成: model=%s session=%s iteration=%d", model, session_id, iteration)

            # Stop hook：一次完整回复后触发
            try:
                run_hooks(
                    "Stop",
                    {
                        "iterations": str(iteration),
                        "final_text": final_text[:500],
                    },
                )
            except Exception as e:
                _log.warning("Stop hook 异常: %s: %s", type(e).__name__, e)

            return final_text

    except KeyboardInterrupt:
        emit(EVT_ERROR, "任务已被用户取消")
        try:
            run_hooks("StopFailure", {"reason": "interrupted"})
        except Exception as e:
            _log.warning("StopFailure hook 异常: %s: %s", type(e).__name__, e)
        _finalize_pending_tool_uses(messages, llm_messages, "[用户中断]")
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

        if event_type == EVT_STREAM_REWIND:
            # 重试前清空已累积的 stream buffer，避免上一次失败的残片混入
            buffer.clear()
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

        elif event_type == EVT_TRUNCATED:
            print(f"\n{_YELLOW}✂️ {text}{_RESET}")

        elif event_type == EVT_ERROR:
            print(f"\n{_RED}⚠️ {text}{_RESET}")

    return print_event
