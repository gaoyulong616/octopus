"""WebSocket 连接管理：AgentBridge 的外壳，承担事件路由和资源生命周期。

Phase 1：单 bridge 包装，行为与原 routes_ws.py 直连 bridge 完全一致。
Phase 2 起：扩展为 bridges dict（活跃池），按 session_id 路由事件。

兼容性：对外暴露 send_json / receive_json / close 方法，参数签名兼容
FastAPI WebSocket，让 _handle_* 函数体无需修改即可同时接受 WebSocket
或 Connection（鸭子类型）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket

from logger import log as _log
from web.agent_bridge import AgentBridge


class Connection:
    """单个 WebSocket 连接的管理外壳。

    职责：
    - 包装 websocket + user + active_bridge
    - 统一 send_json 入口（自动补 session_id 到 envelope）
    - Phase 2 扩展为 bridges dict + route_event + gc_task
    """

    def __init__(self, websocket: WebSocket, user: Any, loop: asyncio.AbstractEventLoop):
        self.websocket = websocket
        self.user = user
        self.loop = loop
        self.active_bridge: AgentBridge | None = None
        self.closed: bool = False

    @property
    def bridge(self) -> AgentBridge:
        """获取当前活跃 bridge。

        Phase 1：单 bridge，直接返回 active_bridge。
        Phase 2：仍保留 active_bridge 作为"前台"概念，但增加 bridges dict 存所有活跃会话。
        """
        if self.active_bridge is None:
            raise RuntimeError("active_bridge not initialized")
        return self.active_bridge

    # ── WebSocket 兼容接口 ──

    async def send_json(self, event: dict) -> None:
        """FastAPI WebSocket.send_json 兼容入口。

        - 若 event 已带 session_id（如跨会话通知），保留
        - 否则用 active_bridge.session_id 填充
        - 发送失败标记 closed，不抛异常（避免中断 relay 循环）
        """
        if self.closed:
            return
        if "session_id" not in event and self.active_bridge and self.active_bridge.session_id:
            event["session_id"] = self.active_bridge.session_id
        try:
            await self.websocket.send_json(event)
        except Exception as e:
            _log("Connection.send_json failed: %s", e)
            self.closed = True

    async def receive_json(self) -> Any:
        """代理 websocket.receive_json（_handle_commands 用）。"""
        return await self.websocket.receive_json()

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """代理 websocket.close。"""
        if reason:
            await self.websocket.close(code=code, reason=reason)
        else:
            await self.websocket.close(code=code)

    # ── Bridge 管理 ──

    def attach_bridge(self, bridge: AgentBridge) -> None:
        """绑定活跃 bridge（Phase 2 会改为 bridges dict + active_session_id 切换）。"""
        self.active_bridge = bridge

    def detach_bridge(self) -> None:
        self.active_bridge = None

    def force_cleanup(self) -> None:
        """清理所有资源（Phase 2 会遍历整个 bridges 池）。"""
        bridge = self.active_bridge
        if bridge is None:
            return
        try:
            bridge.cancel_all_confirms()
            bridge.interrupt()
            bridge.cleanup()
        except Exception as e:
            _log("Connection.force_cleanup error: %s", e)
        self.active_bridge = None
        self.closed = True
