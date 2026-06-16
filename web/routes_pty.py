"""WebSocket 端点 /ws/pty — 终端 PTY I/O"""

from __future__ import annotations

import asyncio
import json
import os
import threading

from fastapi import APIRouter, WebSocket

from web.pty_manager import PTYManager

router = APIRouter()

_BUF_SIZE = 65536


@router.websocket("/ws/pty")
async def pty_endpoint(websocket: WebSocket) -> None:
    # ── JWT 认证 ──
    token = websocket.query_params.get("token", "")
    if not token:
        cookie_token = websocket.headers.get("cookie", "")
        for part in cookie_token.split(";"):
            part = part.strip()
            if part.startswith("octopus_token="):
                token = part[len("octopus_token="):]
                break

    user = None
    if token:
        try:
            from server.auth import get_user_from_token
            user = get_user_from_token(token)
        except Exception:
            pass

    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    pty_mgr = PTYManager()
    pty_mgr.spawn()

    loop = asyncio.get_running_loop()
    output_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    # ── 读线程：PTY master → asyncio.Queue ──
    # uvloop 不支持 add_reader 监听 PTY fd，故用线程
    _reader_stop = threading.Event()

    def pty_reader() -> None:
        while not _reader_stop.is_set():
            try:
                data = os.read(pty_mgr.master_fd, _BUF_SIZE)
            except (OSError, ValueError):
                loop.call_soon_threadsafe(output_queue.put_nowait, None)
                break
            if not data:
                loop.call_soon_threadsafe(output_queue.put_nowait, None)
                break
            loop.call_soon_threadsafe(output_queue.put_nowait, data)

    reader_thread = threading.Thread(target=pty_reader, daemon=True)
    reader_thread.start()

    # ── 读协程：Queue → WebSocket ──
    async def reader() -> None:
        while True:
            data = await output_queue.get()
            if data is None:
                break
            try:
                await websocket.send_bytes(data)
            except Exception:
                break

    # ── 写协程：WebSocket → PTY ──
    async def writer() -> None:
        while True:
            try:
                msg = await websocket.receive_text()
            except Exception:
                break
            try:
                payload = json.loads(msg)
            except (json.JSONDecodeError, ValueError):
                continue
            action = payload.get("action", "")
            if action == "input":
                data = payload.get("data", "")
                pty_mgr.write(data.encode())
            elif action == "resize":
                pty_mgr.resize(payload.get("rows", 24), payload.get("cols", 80))

    try:
        await asyncio.wait(
            [asyncio.create_task(reader()), asyncio.create_task(writer())],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        _reader_stop.set()
        pty_mgr.kill()
        try:
            await websocket.close()
        except Exception:
            pass
