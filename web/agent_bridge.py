"""同步 Agent → 异步 WebSocket 桥接。

每个 WebSocket 连接创建独立的 AgentBridge 实例：
- 后台线程运行 run_agent()
- asyncio.Queue 转发事件到 WebSocket
- concurrent.futures.Future 实现 confirm_fn 的阻塞等待
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from concurrent.futures import Future
from typing import Any, Callable

from web.events import serialize_event


class AgentBridge:
    """将同步的 agent 事件流桥接到异步 WebSocket。"""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.event_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._done_event: asyncio.Event = asyncio.Event()

        self._confirm_futures: dict[str, Future] = {}
        self._confirm_tool_names: dict[str, str] = {}  # confirm_id → tool_name
        self._agent_thread: threading.Thread | None = None
        self._interrupt_event: threading.Event = threading.Event()
        self._running: bool = False

        # Agent 状态（每个连接独立）
        self.messages: list[dict] = []
        self.session_id: str | None = None
        self.state: dict[str, Any] = {
            "current_agent": None,
            "system_prompt_override": None,
            "plan_mode": False,
            "auto_approved_tools": set(),
            "session_tokens": {"input": 0, "output": 0},
        }

        # MCP 管理器（延迟初始化）
        self._mcp = None

    def cleanup(self):
        """清理资源，防止内存泄漏。在 WebSocket 断连时调用。"""
        for future in self._confirm_futures.values():
            if not future.done():
                future.cancel()
        self._confirm_futures.clear()
        self._confirm_tool_names.clear()
        self._running = False
        if self._mcp:
            try:
                self._mcp.close_all()
            except Exception:
                pass

    def init_mcp(self):
        """初始化 MCP 连接。"""
        from mcp import MCPManager
        from config import get
        self._mcp = MCPManager()
        mcp_configs = get("mcp_servers", {})
        if mcp_configs:
            self._mcp.connect_all(mcp_configs)

    def close_mcp(self):
        """关闭 MCP 连接。"""
        if self._mcp:
            self._mcp.close_all()
            self._mcp = None

    def start_task(self, task: str):
        """在后台线程中启动 agent 执行任务。"""
        self._interrupt_event.clear()
        self._running = True
        self._done_event.clear()

        # 设置 ask_user_question 回调
        from tools.agent_tools import set_ask_fn
        set_ask_fn(self._make_ask_fn())

        def _worker():
            try:
                from agent import run_agent
                run_agent(
                    task,
                    messages=self.messages,
                    confirm_fn=self._make_confirm_fn(),
                    mcp=self._mcp,
                    system_prompt_override=self._build_system_prompt(),
                    output_fn=self._make_output_fn(),
                    verbose=False,
                )
                # Post-run: 检测 submit_plan / enter_plan_mode
                from tools.state import get_state
                pending = get_state().pending_plan
                if pending:
                    get_state().pending_plan = None
                    self._enqueue({"type": "plan_submitted", "text": pending, "meta": {}})
                if get_state().pending_plan_mode:
                    get_state().pending_plan_mode = False
                    self.state["plan_mode"] = True
                    self.state.pop("auto_approved_tools", None)
                    self._enqueue({"type": "plan_mode_entered", "text": "已进入 Plan 模式", "meta": {}})
            except KeyboardInterrupt:
                self._enqueue({"type": "error", "text": "任务已取消", "meta": {}})
            except Exception as e:
                self._enqueue({"type": "error", "text": f"Agent 错误: {e}", "meta": {}})
            finally:
                self._running = False
                self.loop.call_soon_threadsafe(self._done_event.set)
                self._enqueue({"type": "done", "text": "", "meta": {}})

        self._agent_thread = threading.Thread(target=_worker, daemon=True)
        self._agent_thread.start()

    def interrupt(self):
        """请求中断当前任务。"""
        self._interrupt_event.set()

    def resolve_confirm(self, confirm_id: str, approved: bool):
        """浏览器返回确认结果后，解除 agent 线程的阻塞。"""
        future = self._confirm_futures.get(confirm_id)
        if future and not future.done():
            future.set_result(approved)

    def resolve_ask(self, ask_id: str, answer: str):
        """浏览器返回 ask_user_question 回答后，解除阻塞。"""
        future = self._confirm_futures.get(ask_id)
        if future and not future.done():
            future.set_result(answer)

    def get_confirm_tool_name(self, confirm_id: str) -> str | None:
        """获取指定确认请求对应的工具名。"""
        return self._confirm_tool_names.get(confirm_id)

    def cancel_all_confirms(self):
        """断连时取消所有等待中的确认。"""
        for confirm_id, future in self._confirm_futures.items():
            if not future.done():
                future.set_result(False)
        self._confirm_futures.clear()

    @property
    def is_running(self) -> bool:
        return self._running

    # ── 内部方法 ──

    def _build_system_prompt(self) -> str | None:
        """构建 system prompt，Plan 模式追加约束。"""
        override = self.state.get("system_prompt_override")
        if self.state.get("plan_mode"):
            from tools.permissions import build_plan_hint
            plan_hint = build_plan_hint(web_mode=True)
            if override:
                return override + plan_hint
            from context import build_system_prompt
            return build_system_prompt() + plan_hint
        return override

    def _make_output_fn(self) -> Callable:
        """创建 output_fn 回调：将 agent 事件推入异步队列。"""

        def output_fn(event_type: str, text: str, meta: dict | None = None):
            # 检查中断标志
            if self._interrupt_event.is_set():
                self._interrupt_event.clear()
                raise KeyboardInterrupt

            event = serialize_event(event_type, text, meta)
            self._enqueue(event)

            # 累计 token 用量
            if event_type == "response" and meta and meta.get("usage"):
                u = meta["usage"]
                st = self.state.get("session_tokens", {"input": 0, "output": 0})
                st["input"] += u.get("input_tokens", 0)
                st["output"] += u.get("output_tokens", 0)
                self.state["session_tokens"] = st

        return output_fn

    def _make_ask_fn(self) -> Callable:
        """创建 ask_user_question 回调：发送问题到浏览器，阻塞等待回答。"""

        def ask_fn(question: str, header: str, options: list[dict], multi_select: bool) -> str:
            ask_id = uuid.uuid4().hex[:12]
            future: Future[str] = Future()
            self._confirm_futures[ask_id] = future  # 复用 confirm futures 存储

            self._enqueue({
                "type": "ask_user_question",
                "text": question,
                "meta": {
                    "ask_id": ask_id,
                    "header": header,
                    "options": options,
                    "multi_select": multi_select,
                },
            })

            try:
                return future.result(timeout=120)
            except Exception:
                return "(超时未响应)"

        return ask_fn

    def _make_confirm_fn(self) -> Callable:
        """创建 confirm_fn：发送确认请求到浏览器，阻塞等待响应。"""

        def confirm_fn(tool_name: str, tool_input: dict) -> bool:
            from config import check_permission_rule
            from tools.permissions import READ_TOOLS, WRITE_TOOLS, summarize_tool

            # 1. 细粒度权限规则
            rule = check_permission_rule(tool_name, tool_input)
            if rule == "allow":
                return True
            if rule == "deny":
                return False

            # 2. Plan 模式：仅写入类工具需要浏览器确认
            if self.state.get("plan_mode"):
                if tool_name not in WRITE_TOOLS:
                    return True
                # 其他工具走浏览器确认流程（fall through to step 6）

            # 3. 权限模式检查
            from config import get
            permissions = get("permissions", "confirm")
            if permissions == "auto-approve":
                return True
            if permissions == "deny":
                return False

            # 4. 已自动放行的工具
            if tool_name in self.state.get("auto_approved_tools", set()):
                return True

            # 5. 读取类工具自动通过
            if tool_name in READ_TOOLS:
                return True

            # 6. 非危险 bash 命令自动通过
            from config import is_dangerous
            if tool_name == "bash" and not is_dangerous(tool_input.get("command", "")):
                return True

            # 7. 危险操作发送确认请求到浏览器，阻塞等待
            confirm_id = uuid.uuid4().hex[:12]
            future: Future[bool] = Future()
            self._confirm_futures[confirm_id] = future
            self._confirm_tool_names[confirm_id] = tool_name

            self._enqueue({
                "type": "confirm_request",
                "text": "",
                "meta": {
                    "confirm_id": confirm_id,
                    "tool_name": tool_name,
                    "tool_summary": summarize_tool(tool_name, tool_input),
                },
            })

            try:
                return future.result(timeout=120)
            except Exception:
                from logger import log
                log(f"confirm timeout for {tool_name}")
                return False
            finally:
                self._confirm_futures.pop(confirm_id, None)
                self._confirm_tool_names.pop(confirm_id, None)

        return confirm_fn

    def _enqueue(self, event: dict):
        """线程安全地将事件推入异步队列。"""
        try:
            self.loop.call_soon_threadsafe(self.event_queue.put_nowait, event)
        except RuntimeError:
            pass  # event loop 已关闭
