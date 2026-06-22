"""同步 Agent → 异步 WebSocket 桥接。

每个 WebSocket 连接创建独立的 AgentBridge 实例：
- 后台线程运行 run_agent()
- asyncio.Queue 转发事件到 WebSocket
- concurrent.futures.Future 实现 confirm_fn 的阻塞等待
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from logger import log as _log
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
        self._soft_interrupt: bool = False
        self._running: bool = False

        # 每个连接拥有独立的 AgentState（cwd/tasks/plan 等完全隔离）
        from tools.state import AgentState

        self.agent_state = AgentState()

        # Agent UI 状态（每个连接独立）
        self.messages: list[dict] = []
        self.session_id: str | None = None
        self.state: dict[str, Any] = {
            "current_agent": None,
            "agent_persona": None,
            "mode": "accept-edits",
            "auto_approved_tools": set(),
            "session_tokens": {"input": 0, "output": 0},
            "session_cost_usd": 0.0,
        }

        # MCP 管理器（延迟初始化）
        self._mcp = None

        # 待审批的计划（agent 提交后暂存，前端批准/拒绝后消费）
        self._pending_plan: str | None = None
        self.task_lock: asyncio.Lock = asyncio.Lock()

    def cleanup(self):
        """清理资源，防止内存泄漏。在 WebSocket 断连时调用。"""
        futures = list(self._confirm_futures.values())
        for future in futures:
            if not future.done():
                future.cancel()
        self._confirm_futures.clear()
        self._confirm_tool_names.clear()
        self._running = False
        # 等待 agent 线程结束（最多 5 秒）
        if self._agent_thread is not None and self._agent_thread.is_alive():
            self._agent_thread.join(timeout=5)
        if self._mcp:
            try:
                self._mcp.close_all()
            except Exception:
                pass

    def init_mcp(self):
        """初始化 MCP 连接。"""
        from config import get
        from mcp import MCPManager

        self._mcp = MCPManager()
        mcp_configs = get("mcp_servers", {})
        if mcp_configs:
            self._mcp.connect_all(mcp_configs)

    def close_mcp(self):
        """关闭 MCP 连接。"""
        if self._mcp:
            self._mcp.close_all()
            self._mcp = None

    def start_task(self, task: str, skip_user_message: bool = False):
        """在后台线程中启动 agent 执行任务。"""
        self._interrupt_event.clear()
        self._running = True
        self._done_event.clear()

        # 创建 ask_fn 回调（每个任务独立，避免全局竞争）
        ask_fn = self._make_ask_fn()

        _log("agent 线程启动: session=%s task_len=%d", self.session_id, len(task))

        def _worker():
            try:
                from agent import run_agent

                _force_compact = self.state.pop("_force_compact_next", False)
                from constants import UI_CAPABILITIES_WEB

                agent_persona = self.state.get("agent_persona")
                plan_hint = None
                if self.state.get("mode") == "plan":
                    from tools.permissions import build_plan_hint

                    plan_hint = build_plan_hint(web_mode=True)

                run_agent(
                    task,
                    messages=self.messages,
                    skip_user_append=skip_user_message,
                    confirm_fn=self._make_confirm_fn(),
                    mcp=self._mcp,
                    agent_persona=agent_persona,
                    plan_hint=plan_hint,
                    ui_capabilities=UI_CAPABILITIES_WEB,
                    output_fn=self._make_output_fn(),
                    verbose=False,
                    session_id=self.session_id,
                    agent_state=self.agent_state,
                    ask_fn=ask_fn,
                    force_compact=_force_compact,
                )
                # Post-run: 检测 submit_plan / enter_plan_mode
                pending = self.agent_state.pending_plan
                if pending:
                    self.agent_state.pending_plan = None
                    self._pending_plan = pending
                    self._enqueue({"type": "plan_submitted", "text": pending, "meta": {}})
                if self.agent_state.pending_plan_mode:
                    self.agent_state.pending_plan_mode = False
                    self.state["mode"] = "plan"
                    self.state.pop("auto_approved_tools", None)
                    self._enqueue({"type": "plan_mode_entered", "text": "已进入 Plan 模式", "meta": {}})
            except KeyboardInterrupt:
                self.state["_interrupted"] = True
                self._enqueue({"type": "error", "text": "任务已取消", "meta": {}})
            except Exception as e:
                import traceback

                _log("agent 异常: %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
                self._enqueue({"type": "error", "text": f"Agent 错误: {e}", "meta": {}})
            finally:
                self._running = False
                _log("agent 线程结束: session=%s", self.session_id)
                self.loop.call_soon_threadsafe(self._done_event.set)
                done_meta = {}
                notify_sid = self.state.pop("_notify_complete_session", None)
                if notify_sid:
                    done_meta["completed_session_id"] = notify_sid
                self._enqueue({"type": "done", "text": "", "meta": done_meta})

        self._agent_thread = threading.Thread(target=_worker, daemon=True)
        self._agent_thread.start()

    def interrupt(self):
        """请求中断当前任务。

        设置中断标志，并尝试在 agent 线程中抛出 KeyboardInterrupt。
        """
        self._interrupt_event.set()
        # 尝试在线程中注入 KeyboardInterrupt（Python 3.12+ 支持的可靠方式）
        if self._agent_thread is not None and self._agent_thread.is_alive():
            import ctypes

            try:
                thread_id = self._agent_thread.ident
                if thread_id:
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(
                        ctypes.c_ulong(thread_id),
                        ctypes.py_object(KeyboardInterrupt),
                    )
            except Exception:
                pass

    def soft_interrupt(self):
        """软中断：等待当前流式输出完成后再中断，保留 assistant_msg。

        与 interrupt() 不同，此方法不在 EVT_STREAM 事件上抛出 KeyboardInterrupt，
        而是等到下一个非流式事件（此时 assistant_msg 已写入 messages）才触发。
        确保切走会话时不会丢失正在输出中的模型响应。
        """
        _log("soft_interrupt 设置: session=%s messages=%d", self.session_id, len(self.messages))
        self._soft_interrupt = True

    def resolve_confirm(self, confirm_id: str, approved: bool, reason: str | None = None):
        """浏览器返回确认结果后，解除 agent 线程的阻塞。

        reason 仅在用户主动拒绝时有值（可选），用于回喂给 LLM 帮助理解用户意图。
        """
        future = self._confirm_futures.get(confirm_id)
        if future and not future.done():
            future.set_result({"approved": approved, "reason": reason})

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
        items = list(self._confirm_futures.items())
        for confirm_id, future in items:
            if not future.done():
                future.set_result({"approved": False, "reason": None})
        self._confirm_futures.clear()
        self._confirm_tool_names.clear()

    @property
    def is_running(self) -> bool:
        return self._running

    # ── 内部方法 ──

    def _make_output_fn(self) -> Callable:
        """创建 output_fn 回调：将 agent 事件推入异步队列。"""

        def output_fn(event_type: str, text: str, meta: dict | None = None):
            # 硬中断：立即触发（用户点击停止按钮）
            if self._interrupt_event.is_set():
                self._interrupt_event.clear()
                raise KeyboardInterrupt

            # 软中断：跳过 EVT_STREAM（让流式输出完成，assistant_msg 写入 messages），
            # 其他事件触发中断 —— 此时 assistant_msg 已保存（agent.py:717）
            if self._soft_interrupt:
                if event_type == "stream":
                    return  # 流式中，不中断，也不入队（已是残片）
                _log("soft_interrupt 触发: event=%s session=%s messages=%d", event_type, self.session_id, len(self.messages))
                self._soft_interrupt = False
                raise KeyboardInterrupt

            event = serialize_event(event_type, text, meta)
            self._enqueue(event)

            # 累计 token 用量 + 成本
            if event_type == "response" and meta and meta.get("usage"):
                u = meta["usage"]
                st = self.state.get("session_tokens", {"input": 0, "output": 0})
                st["input"] += u.get("input_tokens", 0)
                st["output"] += u.get("output_tokens", 0)
                self.state["session_tokens"] = st
                if u.get("cost_usd"):
                    self.state["session_cost_usd"] = self.state.get("session_cost_usd", 0.0) + u["cost_usd"]

        return output_fn

    def _make_ask_fn(self) -> Callable:
        """创建 ask_user_question 回调：发送多问题到浏览器，阻塞等待完整答案 JSON。"""

        def ask_fn(questions: list[dict]) -> str:
            ask_id = uuid.uuid4().hex[:12]
            future: Future[str] = Future()
            self._confirm_futures[ask_id] = future  # 复用 confirm futures 存储

            self._enqueue(
                {
                    "type": "ask_user_question",
                    "text": "",
                    "meta": {
                        "ask_id": ask_id,
                        "questions": questions,
                    },
                }
            )

            try:
                # 超时按问题数线性放宽，避免问题多时不够用；每个问题 90s
                timeout = max(120, 90 * len(questions))
                return future.result(timeout=timeout)
            except Exception:
                return json.dumps(
                    [
                        {"header": q.get("header", "?"), "answer": "(超时未响应)"}
                        for q in questions
                    ],
                    ensure_ascii=False,
                )
            finally:
                # 关键：超时/异常后也必须清理，否则 _confirm_futures 残留累积（内存泄漏）
                self._confirm_futures.pop(ask_id, None)
                self._confirm_tool_names.pop(ask_id, None)

        return ask_fn

    def _make_confirm_fn(self) -> Callable:
        """创建 confirm_fn：发送确认请求到浏览器，阻塞等待响应。

        返回 (approved, reason, source)：
        - source="system"：权限规则/模式命中、超时
        - source="user"：用户在浏览器点了允许/允许所有/拒绝
        """

        def confirm_fn(tool_name: str, tool_input: dict) -> tuple[bool, str | None, str]:
            from config import check_permission_rule, get, is_dangerous
            from tools.permissions import (
                EDIT_TOOLS,
                READ_TOOLS,
                summarize_tool,
            )

            # 1. 细粒度权限规则（系统）
            rule = check_permission_rule(tool_name, tool_input)
            if rule == "allow":
                return (True, None, "system")
            if rule == "deny":
                return (False, None, "system")

            # 2. 全局权限模式（系统）
            permissions = get("permissions", "confirm")
            if permissions == "auto-approve":
                return (True, None, "system")
            if permissions == "deny":
                return (False, None, "system")

            # 3. 已自动放行的工具（系统：会话级配置）
            if tool_name in self.state.get("auto_approved_tools", set()):
                return (True, None, "system")

            # 4. 读取类工具自动通过（系统）
            if tool_name in READ_TOOLS:
                return (True, None, "system")

            # 5. 按当前模式分流
            mode = self.state.get("mode", "accept-edits")

            if mode == "plan":
                # Plan：完全只读。READ_TOOLS 已放行；只读 bash 自动；其他一律禁止
                if tool_name == "bash":
                    if is_dangerous(tool_input.get("command", "")):
                        return (False, None, "system")
                    return (True, None, "system")
                return (False, None, "system")

            if mode == "auto":
                # Auto：全自动（YOLO）
                return (True, None, "system")

            # accept-edits（默认）：编辑自动；非危险 bash 自动；
            # 破坏性工具 + 危险 bash + 未知工具 走浏览器确认
            if tool_name in EDIT_TOOLS:
                return (True, None, "system")

            if tool_name == "bash" and not is_dangerous(tool_input.get("command", "")):
                return (True, None, "system")

            # 6. 危险/未知操作发送确认请求到浏览器，阻塞等待（用户操作）
            confirm_id = uuid.uuid4().hex[:12]
            future: Future[dict] = Future()
            self._confirm_futures[confirm_id] = future
            self._confirm_tool_names[confirm_id] = tool_name

            self._enqueue(
                {
                    "type": "confirm_request",
                    "text": "",
                    "meta": {
                        "confirm_id": confirm_id,
                        "tool_name": tool_name,
                        "tool_summary": summarize_tool(tool_name, tool_input),
                    },
                }
            )

            try:
                result = future.result(timeout=120)
                # 用户主动操作 → source="user"（允许/拒绝/带理由都算）
                return (bool(result.get("approved")), result.get("reason"), "user")
            except Exception:
                _log("confirm timeout: tool=%s", tool_name)
                # 超时视为系统拒绝（用户没操作），文案走"权限限制"避免误导
                return (False, None, "system")
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
