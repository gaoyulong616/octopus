"""WebSocket 连接管理：AgentBridge 的管理外壳，承担事件路由和资源生命周期。

Phase 2：多 bridge 池化（活跃池）。
- 每个会话独立的 AgentBridge 实例（独立 agent 线程、独立 messages）
- 切走的会话进入池中继续跑，不销毁
- 每个 bridge 有独立的 event_queue 和 relay_task
- 通过 active_session_id 标识前台会话

向后兼容：对外暴露 send_json / receive_json / close 方法，参数签名兼容
FastAPI WebSocket，让 _handle_* 函数体无需修改。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import WebSocket

from logger import log as _log
from web.agent_bridge import AgentBridge


# 进程级 Connection 注册表：scheduler 等异步触发器按 session_id 查找 bridge
_CONNECTIONS: set["Connection"] = set()
_CONNECTIONS_LOCK = threading.Lock()


def register_connection(conn: "Connection") -> None:
    """注册 Connection 到全局表（用于定时任务触发时查找）。"""
    with _CONNECTIONS_LOCK:
        _CONNECTIONS.add(conn)


def unregister_connection(conn: "Connection") -> None:
    """注销 Connection。"""
    with _CONNECTIONS_LOCK:
        _CONNECTIONS.discard(conn)


def find_bridge_by_session_id(session_id: str) -> AgentBridge | None:
    """按 session_id 在所有活跃 Connection 的池中查找 bridge。

    用于定时任务触发时路由事件到对应 session 的 bridge。
    跨多 ws 连接（同 user 多 tab）时返回任意一个有效 bridge。
    """
    with _CONNECTIONS_LOCK:
        conns = list(_CONNECTIONS)
    for conn in conns:
        bridge = conn.get_bridge(session_id)
        if bridge is not None:
            return bridge
    return None


class Connection:
    """单个 WebSocket 连接的管理外壳。

    职责：
    - 包装 websocket + user + loop
    - 管理多 bridge 池（bridges dict + active_session_id）
    - 统一 send_json 入口（自动补 session_id 到 envelope）
    - 每个 bridge 有独立 relay_task 推送事件
    """

    def __init__(self, websocket: WebSocket, user: Any, loop: asyncio.AbstractEventLoop):
        self.websocket = websocket
        self.user = user
        self.loop = loop

        # 多 bridge 池：session_id → AgentBridge
        self.bridges: dict[str, AgentBridge] = {}
        self.active_session_id: str | None = None
        self._relay_tasks: dict[str, asyncio.Task] = {}
        self._gc_task: asyncio.Task | None = None

        self.closed: bool = False

        # 注册到进程级表（scheduler 触发时按 session_id 查找 bridge）
        register_connection(self)

        # 启动后台 GC（TTL 淘汰空闲会话）
        self._gc_task = asyncio.create_task(self._gc_loop())

    @property
    def active_bridge(self) -> AgentBridge | None:
        """当前前台 bridge（向后兼容 Phase 1 单 bridge 调用）。"""
        if self.active_session_id is None:
            return None
        return self.bridges.get(self.active_session_id)

    @property
    def bridge(self) -> AgentBridge:
        """获取当前活跃 bridge（断言非空，方便 _handle_* 直接使用）。"""
        b = self.active_bridge
        if b is None:
            raise RuntimeError("active_bridge not initialized")
        return b

    # ── WebSocket 兼容接口 ──

    async def send_json(self, event: dict) -> None:
        """FastAPI WebSocket.send_json 兼容入口。

        - 若 event 已带 session_id（如跨会话通知），保留
        - 否则用 active_session_id 填充
        - 发送失败标记 closed，不抛异常（避免中断 relay 循环）
        """
        if self.closed:
            return
        if "session_id" not in event and self.active_session_id:
            event["session_id"] = self.active_session_id
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

    # ── Bridge 池管理 ──

    def attach_bridge(self, bridge: AgentBridge) -> None:
        """绑定初始活跃 bridge（仅 WebSocket 建立时用一次）。

        后续新增/切换会话请走 get_or_create_bridge + switch_active。
        """
        if not bridge.session_id:
            raise RuntimeError("bridge.session_id 必须先设置")
        self.bridges[bridge.session_id] = bridge
        self.active_session_id = bridge.session_id
        self._start_relay_for(bridge)

    def get_or_create_bridge(self, session_id: str) -> AgentBridge:
        """从池中取 bridge，不存在则新建（不加载历史，由调用方负责）。"""
        bridge = self.bridges.get(session_id)
        if bridge is not None:
            return bridge

        bridge = AgentBridge(self.loop)
        bridge.session_id = session_id
        bridge.agent_state.user_id = self.user.id
        bridge.agent_state.user_root = str(self.user.home_dir)
        bridge.state["session_id"] = session_id
        bridge.state["user_id"] = self.user.id
        bridge.init_mcp()

        self.bridges[session_id] = bridge
        self._start_relay_for(bridge)
        _log("bridge 池新增: session=%s total=%d", session_id, len(self.bridges))
        return bridge

    def switch_active(self, session_id: str) -> AgentBridge:
        """切换前台会话（不销毁旧 bridge）。"""
        if session_id not in self.bridges:
            raise KeyError(f"bridge 不在池中: {session_id}")
        self.active_session_id = session_id
        _log("bridge 切换前台: session=%s 池大小=%d", session_id, len(self.bridges))
        return self.bridges[session_id]

    def get_bridge(self, session_id: str) -> AgentBridge | None:
        """从池中查 bridge（不创建）。"""
        return self.bridges.get(session_id)

    def has_bridge(self, session_id: str) -> bool:
        return session_id in self.bridges

    def detach_bridge(self, session_id: str) -> None:
        """从池中移除并清理指定 bridge（用于 TTL 淘汰）。"""
        bridge = self.bridges.pop(session_id, None)
        task = self._relay_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
        if bridge:
            try:
                bridge.cancel_all_confirms()
                bridge.interrupt()
                bridge.cleanup()
            except Exception as e:
                _log("detach_bridge 清理异常: %s", e)
        if self.active_session_id == session_id:
            self.active_session_id = next(iter(self.bridges), None)

    def _start_relay_for(self, bridge: AgentBridge) -> None:
        """为 bridge 启动独立 relay task（避免多 bridge 事件互相阻塞）。"""
        if bridge.session_id in self._relay_tasks:
            return  # 已启动
        task = asyncio.create_task(self._relay_events(bridge))
        self._relay_tasks[bridge.session_id] = task

    async def _relay_events(self, bridge: AgentBridge) -> None:
        """单个 bridge 的事件转发循环。"""
        try:
            while True:
                event = await bridge.event_queue.get()
                await self.send_json(event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _log("relay_events 异常: session=%s %s", bridge.session_id, e)

    def force_cleanup(self) -> None:
        """清理所有资源（遍历整个 bridges 池）。"""
        # 取消 GC 任务
        if self._gc_task and not self._gc_task.done():
            self._gc_task.cancel()
            self._gc_task = None
        for sid in list(self.bridges.keys()):
            self.detach_bridge(sid)
        # 取消所有 relay task
        for task in self._relay_tasks.values():
            if not task.done():
                task.cancel()
        self._relay_tasks.clear()
        self.bridges.clear()
        self.active_session_id = None
        self.closed = True
        # 从进程级注册表注销
        unregister_connection(self)

    # ── TTL 淘汰 ──

    async def _gc_loop(self) -> None:
        """后台 GC：每 60s 扫池，淘汰空闲超时的 bridge。

        策略：
        - 跳过活跃中的 bridge（task_lock.locked() 表示正在跑任务）
        - 跳过前台 bridge（active_session_id）
        - 超过 web_session_idle_timeout 秒无事件 → save_session 后 detach
        - 池大小 > web_max_active_sessions 时按 LRU 淘汰最久未活跃的
        """
        from config import get

        try:
            while not self.closed:
                await asyncio.sleep(60)
                if self.closed:
                    break
                try:
                    idle_timeout = int(get("web_session_idle_timeout", 3600))
                    max_sessions = int(get("web_max_active_sessions", 8))
                except Exception:
                    idle_timeout, max_sessions = 3600, 8

                now = asyncio.get_event_loop().time()
                import time as _time

                now_wall = _time.time()

                # 1. TTL 淘汰：空闲超时（跳过活跃中和前台）
                to_evict = []
                for sid, bridge in list(self.bridges.items()):
                    if sid == self.active_session_id:
                        continue
                    if bridge.is_running:
                        continue
                    if bridge.task_lock and bridge.task_lock.locked():
                        continue
                    idle = now_wall - getattr(bridge, "last_activity", now_wall)
                    if idle >= idle_timeout:
                        to_evict.append((sid, idle))
                for sid, idle in to_evict:
                    _log("GC TTL 淘汰: session=%s 空闲%.0fs", sid, idle)
                    self._archive_and_detach(sid)

                # 2. LRU 淘汰：池超上限时按最久未活跃排序淘汰
                if len(self.bridges) > max_sessions:
                    candidates = [
                        (sid, b) for sid, b in self.bridges.items()
                        if sid != self.active_session_id and not b.is_running
                    ]
                    candidates.sort(key=lambda kv: getattr(kv[1], "last_activity", 0))
                    excess = len(self.bridges) - max_sessions
                    for sid, _b in candidates[:excess]:
                        _log("GC LRU 淘汰: session=%s 池超上限%d", sid, max_sessions)
                        self._archive_and_detach(sid)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _log("GC loop 异常: %s", e)

    def _archive_and_detach(self, session_id: str) -> None:
        """淘汰前 save_session 保留进度，再 detach。"""
        bridge = self.bridges.get(session_id)
        if bridge is None:
            return
        try:
            if session_id and bridge.messages:
                from session import save_session

                save_session(
                    bridge.messages,
                    session_id=session_id,
                    user_id=self.user.id if self.user else None,
                )
        except Exception as e:
            _log("GC save_session 异常: session=%s %s", session_id, e)
        self.detach_bridge(session_id)
