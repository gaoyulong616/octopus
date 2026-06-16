"""WebSocket 端点：流式事件推送 + 双向命令通信。

多用户支持：
- JWT 认证替换旧的全局 token 验证
- WebSocket 连接绑定用户上下文
- 会话按用户隔离存储
"""

from __future__ import annotations

import asyncio
import os
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from logger import log as _log
from web.agent_bridge import AgentBridge

router = APIRouter()


def _verify_jwt_and_get_user(token: str) -> tuple[str, str] | None:
    """验证 JWT token，返回 (user_id, username) 或 None。"""
    from server.auth import verify_token
    from server.database import Session
    from server.models.user import User

    try:
        import jwt
        payload = jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub")
        if not user_id:
            return None
    except Exception:
        return None

    with Session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            return None
        # 完整验证 token 版本
        full_payload = verify_token(token, user.token_version)
        if not full_payload:
            return None
        return (user.id, user.username)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # 获取 token（query param 或 cookie）
    token = websocket.query_params.get("token", "")
    if not token:
        token = websocket.cookies.get("octopus_token", "")

    # JWT 验证
    user_info = _verify_jwt_and_get_user(token) if token else None

    if user_info is None:
        # 回退：尝试旧的全局 token（兼容 TUI/CLI）
        from web.app import get_auth_token
        if token != get_auth_token():
            await websocket.close(code=4001, reason="Unauthorized")
            return
        user_id = ""
        username = "cli"
    else:
        user_id, username = user_info

    await websocket.accept()
    loop = asyncio.get_running_loop()
    bridge = AgentBridge(loop)

    # 设置用户隔离的 AgentState
    if user_id:
        from tools.state import AgentState
        from pathlib import Path
        user_root = str(Path.home() / ".octopus" / "users" / user_id)
        bridge.agent_state = AgentState(user_id=user_id, user_root=user_root)

    # 创建用户隔离的会话
    from config import get, is_trusted_dir
    from session import create_session

    bridge.session_id = create_session(user_id=user_id)

    bridge.state["session_id"] = bridge.session_id
    bridge.state["user_id"] = user_id
    bridge.state["username"] = username
    bridge.init_mcp()

    _log("ws 连接: session=%s user=%s", bridge.session_id, username or "cli")

    model = get("model")
    cwd = bridge.agent_state.get_cwd()
    trusted = is_trusted_dir(cwd)

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "text": "",
                "meta": {
                    "session_id": bridge.session_id,
                    "model": model,
                    "cwd": cwd,
                    "trusted": trusted,
                    "messages": [],
                    "user_id": user_id,
                    "username": username,
                },
            }
        )
    except Exception as e:
        _log("ws initial send failed: %s", e)
        return

    # 单一事件转发任务 + 命令处理任务
    relay_task = asyncio.create_task(_relay_events(websocket, bridge))
    command_task = asyncio.create_task(_handle_commands(websocket, bridge))

    try:
        done, pending = await asyncio.wait(
            [relay_task, command_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    except WebSocketDisconnect:
        _log("ws 断开: session=%s user=%s", bridge.session_id, username or "cli")
    finally:
        # 关键顺序：先 interrupt + cleanup 让 agent 线程结束，再 save_session。
        bridge.cancel_all_confirms()
        bridge.interrupt()
        bridge.cleanup()
        if bridge.session_id and bridge.messages:
            from session import save_session
            save_session(bridge.messages, session_id=bridge.session_id, user_id=user_id)


async def _relay_events(websocket: WebSocket, bridge: AgentBridge):
    """唯一的事件消费者：将 agent 事件推送到 WebSocket。"""
    try:
        while True:
            event = await bridge.event_queue.get()
            try:
                await websocket.send_json(event)
            except Exception as e:
                _log("ws relay send failed: %s", e)
                break
    except asyncio.CancelledError:
        pass


async def _handle_commands(websocket: WebSocket, bridge: AgentBridge):
    """读取浏览器命令并分发处理。"""
    user_id = bridge.state.get("user_id", "") or ""

    try:
        while True:
            if bridge.state.get("_should_quit"):
                break
            try:
                data = await websocket.receive_json()
            except Exception:
                break

            action = data.get("action", "")

            _log("ws action: %s", action)

            try:
                if action == "task":
                    asyncio.create_task(_handle_task(websocket, bridge, data.get("text", ""), bridge.task_lock))

                elif action == "confirm":
                    confirm_id = data.get("confirm_id", "")
                    approved = data.get("approved", False)
                    approve_all = data.get("approve_all", False)
                    _log("ws confirm: id=%s approved=%s approve_all=%s", confirm_id, approved, approve_all)
                    if approve_all and approved:
                        tool_name = bridge.get_confirm_tool_name(confirm_id)
                        _log("ws confirm tool_name=%s", tool_name)
                        if tool_name:
                            bridge.state.setdefault("auto_approved_tools", set()).add(tool_name)
                    bridge.resolve_confirm(confirm_id, approved)

                elif action == "ask_response":
                    ask_id = data.get("ask_id", "")
                    answer = data.get("answer", "")
                    bridge.resolve_ask(ask_id, answer)

                elif action == "interrupt":
                    bridge.interrupt()

                elif action == "slash":
                    asyncio.create_task(_handle_slash(websocket, bridge, data.get("text", ""), bridge.task_lock))

                elif action == "resume":
                    await _handle_resume(websocket, bridge, data.get("session_id", ""), bridge.task_lock)

                elif action == "new_session":
                    if bridge.task_lock and bridge.task_lock.locked():
                        old_session_id = bridge.session_id
                        bridge.soft_interrupt()
                        for _ in range(30):
                            await asyncio.sleep(0.1)
                            if not bridge.task_lock.locked():
                                break
                        if old_session_id != bridge.session_id:
                            bridge.state["_notify_complete_session"] = old_session_id
                    skip_save = data.get("skip_save", False)
                    if not skip_save and bridge.session_id and bridge.messages:
                        from session import save_session
                        save_session(bridge.messages, session_id=bridge.session_id, user_id=user_id)
                    from session import create_session
                    new_id = create_session(user_id=user_id)
                    bridge.session_id = new_id
                    bridge.state["session_id"] = new_id
                    bridge.messages.clear()
                    await websocket.send_json(
                        {
                            "type": "session_created",
                            "text": "",
                            "meta": {"session_id": new_id},
                        }
                    )

                elif action == "set_mode":
                    mode = data.get("mode", "auto")
                    bridge.state["plan_mode"] = mode == "plan"
                    if mode == "plan":
                        bridge.state.pop("auto_approved_tools", None)
                    await websocket.send_json(
                        {
                            "type": "mode_changed",
                            "text": mode,
                            "meta": {},
                        }
                    )

                elif action == "plan_approve":
                    bridge.state["plan_mode"] = False
                    await websocket.send_json(
                        {
                            "type": "mode_changed",
                            "text": "auto",
                            "meta": {"note": "计划已批准，已切换到 Auto 模式，开始执行..."},
                        }
                    )
                    plan = bridge._pending_plan
                    if plan:
                        bridge._pending_plan = None
                        exec_prompt = f"用户已批准以下实施计划，请立即按照计划逐步执行。\n\n## 实施计划\n\n{plan}"
                        asyncio.create_task(_handle_task(websocket, bridge, exec_prompt, bridge.task_lock))

                elif action == "plan_reject":
                    bridge._pending_plan = None
                    await websocket.send_json(
                        {
                            "type": "info",
                            "text": "计划未批准，仍处于 Plan 模式",
                            "meta": {},
                        }
                    )

                elif action == "trust_dir":
                    from config import trust_dir
                    from tools import get_cwd
                    trust_dir(get_cwd())
                    bridge.state["plan_mode"] = False
                    await websocket.send_json(
                        {
                            "type": "info",
                            "text": "目录已信任",
                            "meta": {},
                        }
                    )

                elif action == "switch_model":
                    model_name = data.get("model", "")
                    if model_name:
                        from config import get, switch_model
                        try:
                            resolved = switch_model(model_name)
                            current = get("model")
                            await websocket.send_json(
                                {
                                    "type": "model_changed",
                                    "text": current,
                                    "meta": {"model": current, "requested": model_name, "resolved": resolved},
                                }
                            )
                        except ValueError as e:
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "text": str(e),
                                }
                            )

                elif action == "send_image":
                    image_data = data.get("image", "")
                    media_type = data.get("media_type", "image/png")
                    if image_data:
                        bridge.state.setdefault("_pending_images", []).append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data,
                                },
                            }
                        )
            except Exception as e:
                _log("ws action handler error: action=%s error=%s", action, e)

    except asyncio.CancelledError:
        pass


async def _handle_task(websocket: WebSocket, bridge: AgentBridge, task: str, task_lock: asyncio.Lock | None = None):
    """启动 agent 执行任务。"""
    if not task.strip():
        return
    if task_lock and task_lock.locked():
        bridge.soft_interrupt()
        for _ in range(30):
            await asyncio.sleep(0.1)
            if not task_lock.locked():
                break
    if task_lock:
        await task_lock.acquire()
    try:
        bridge.state.pop("last_task", None)
        pending_images = bridge.state.pop("_pending_images", None)
        if pending_images:
            content_parts = [{"type": "text", "text": task}]
            content_parts.extend(pending_images)
            bridge.messages.append({"role": "user", "content": content_parts})
            bridge.start_task(task, skip_user_message=True)
        else:
            bridge.start_task(task)

        try:
            await bridge._done_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            user_id = bridge.state.get("user_id", "") or ""
            if bridge.session_id and bridge.messages:
                from session import save_session
                _log("_handle_task 保存会话: session=%s messages=%d user=%s",
                     bridge.session_id, len(bridge.messages), user_id)
                save_session(bridge.messages, session_id=bridge.session_id, user_id=user_id)
            if bridge.state.get("_interrupted"):
                bridge.state.pop("_interrupted", None)
                bridge.state["last_task"] = task
    finally:
        if task_lock and task_lock.locked():
            task_lock.release()


async def _handle_slash(websocket: WebSocket, bridge: AgentBridge, cmd: str, task_lock: asyncio.Lock | None = None):
    """处理 slash 命令，适配 web 环境。"""
    cmd = cmd.strip()
    if not cmd:
        return
    name = cmd.split(maxsplit=1)[0].lower()

    if name == "/init":
        await _handle_init(websocket, bridge, cmd, task_lock)
        return

    if name == "/resume" and cmd.strip() == "/resume":
        await websocket.send_json(
            {
                "type": "show_session_picker",
                "text": "",
                "meta": {},
            }
        )
        return

    if name == "/export":
        await _handle_export(websocket, bridge, cmd)
        return

    if name == "/clear":
        if task_lock and task_lock.locked():
            bridge.soft_interrupt()
            for _ in range(30):
                await asyncio.sleep(0.1)
                if not task_lock.locked():
                    break
        bridge.messages.clear()
        await websocket.send_json(
            {
                "type": "messages_cleared",
                "text": "对话历史已清除",
                "meta": {},
            }
        )
        return

    from commands import dispatch_command
    prev_agent = bridge.state.get("current_agent")
    from config import get as _config_get
    prev_model = _config_get("model")

    result = dispatch_command(cmd, bridge.messages, bridge.state)

    if result is None:
        await websocket.send_json(
            {
                "type": "slash_result",
                "text": f"未知命令: {cmd}",
                "meta": {},
            }
        )
        return

    if result.quit:
        bridge.state["_should_quit"] = True
        await websocket.send_json(
            {
                "type": "slash_result",
                "text": "会话已结束",
                "meta": {},
            }
        )
        await websocket.close()
        return

    if result.task_override:
        await websocket.send_json(
            {
                "type": "slash_result",
                "text": f"执行: {result.task_override[:100]}",
                "meta": {},
            }
        )
        await _handle_task(websocket, bridge, result.task_override, task_lock)
        return

    text = _strip_ansi(result.text or "")
    await websocket.send_json(
        {
            "type": "slash_result",
            "text": text,
            "meta": {},
        }
    )

    new_agent = bridge.state.get("current_agent")
    if new_agent != prev_agent:
        await websocket.send_json(
            {
                "type": "agent_changed",
                "text": "",
                "meta": {"name": new_agent or "default"},
            }
        )

    new_model = _config_get("model")
    if new_model != prev_model:
        await websocket.send_json(
            {
                "type": "model_changed",
                "text": new_model,
                "meta": {"model": new_model},
            }
        )


async def _handle_init(websocket: WebSocket, bridge: AgentBridge, cmd: str, task_lock: asyncio.Lock | None = None):
    """处理 /init 命令的 web 适配。"""
    import os as _os
    from commands import build_init_prompt
    from tools import get_cwd

    if task_lock and task_lock.locked():
        bridge.soft_interrupt()
        for _ in range(30):
            await asyncio.sleep(0.1)
            if not task_lock.locked():
                break
    bridge.messages.clear()
    try:
        await websocket.send_json({"type": "messages_cleared", "text": "", "meta": {}})
    except Exception:
        pass

    cwd = get_cwd()
    target = "OCTOPUS.md"
    existing_path = _os.path.join(cwd, "OCTOPUS.md")

    existing_content = ""
    if _os.path.exists(existing_path):
        try:
            with open(existing_path, encoding="utf-8") as f:
                existing_content = f.read()
        except OSError:
            pass

    project_name = _os.path.basename(cwd.rstrip(_os.sep)) or cwd or "项目"
    init_prompt = build_init_prompt(project_name, target, existing_content)

    await websocket.send_json(
        {
            "type": "slash_result",
            "text": f"生成 {target}...",
            "meta": {},
        }
    )
    await _handle_task(websocket, bridge, init_prompt, task_lock)


async def _handle_export(websocket: WebSocket, bridge: AgentBridge, cmd: str):
    """处理 /export 命令的 web 适配。"""
    from session import load_session

    session_id = bridge.session_id
    user_id = bridge.state.get("user_id", "") or ""
    if not session_id:
        await websocket.send_json(
            {
                "type": "error",
                "text": "当前没有活跃会话",
                "meta": {},
            }
        )
        return

    try:
        messages, session_cwd, meta = load_session(session_id, user_id)
    except FileNotFoundError:
        await websocket.send_json(
            {
                "type": "error",
                "text": "会话不存在",
                "meta": {},
            }
        )
        return

    lines: list[str] = []
    if meta.get("name"):
        lines.append(f"# {meta['name']}")
    lines.append(f"# Session: {session_id}")
    lines.append(f"# Created: {meta.get('created_at', '')}")
    lines.append("")

    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for b in content:
                if isinstance(b, dict):
                    if b.get("type") == "text":
                        text_parts.append(b.get("text", ""))
                    elif b.get("type") == "tool_use":
                        text_parts.append(f"[tool: {b.get('name', '')}]")
            content = "\n".join(text_parts)
        lines.append(f"## {role.upper()}")
        lines.append(str(content))
        lines.append("")

    text = "\n".join(lines)
    await websocket.send_json(
        {
            "type": "export_data",
            "text": text,
            "meta": {"filename": f"session_{session_id[:8]}.md"},
        }
    )


def _serialize_messages_for_frontend(messages: list) -> list:
    """序列化消息供前端渲染。"""
    tool_results: dict[str, str] = {}
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = block.get("tool_use_id", "")
                    if tid:
                        tool_results[tid] = str(block.get("content", ""))

    server_tool_results: dict[str, str] = {}
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        server_uses = []
        server_results = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "server_tool_use":
                server_uses.append(block)
            elif btype == "web_search_tool_result":
                server_results.append(_format_server_search_result(block))
            elif btype == "web_fetch_tool_result":
                server_results.append(_format_server_fetch_result(block))
        for i, su in enumerate(server_uses):
            if i < len(server_results) and su.get("id"):
                server_tool_results[su["id"]] = server_results[i]

    result = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content:
            continue

        entry = {"role": role, "blocks": []}
        seen = set()

        def _dedup_key(block):
            btype = block.get("type", "")
            if btype == "text":
                return f"text:{block.get('text', '')}"
            elif btype in ("tool_use", "server_tool_use"):
                return f"tool_use:{block.get('id', id(block))}"
            return id(block)

        if isinstance(content, str):
            if content.strip():
                entry["blocks"].append({"type": "text", "text": content})
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                key = _dedup_key(block)
                if key in seen:
                    continue
                seen.add(key)
                if btype == "text" and block.get("text", "").strip():
                    entry["blocks"].append({"type": "text", "text": block["text"]})
                elif btype == "image":
                    source = block.get("source", {})
                    media_type = source.get("media_type", "image/png")
                    data = source.get("data", "")
                    if data:
                        entry["blocks"].append(
                            {
                                "type": "image",
                                "data_url": f"data:{media_type};base64,{data}",
                            }
                        )
                elif btype == "thinking":
                    thinking_text = block.get("thinking", "")
                    entry["blocks"].append({"type": "thinking", "thinking": thinking_text})
                elif btype in ("tool_use", "server_tool_use"):
                    tool_entry = {
                        "type": "tool_use",
                        "name": block.get("name", ""),
                        "input": block.get("input", {}),
                    }
                    tid = block.get("id", "")
                    if tid:
                        result_text = tool_results.get(tid) or server_tool_results.get(tid)
                        if result_text:
                            tool_entry["done"] = True
                            tool_entry["result"] = result_text[:200]
                    entry["blocks"].append(tool_entry)

        if entry["blocks"]:
            result.append(entry)
    return result


def _format_server_search_result(block: dict) -> str:
    """格式化搜索结果。"""
    content = block.get("content", [])
    if not isinstance(content, list):
        return str(content)[:200]
    lines = []
    for item in content:
        if isinstance(item, dict):
            title = item.get("title", "")
            url = item.get("url", "")
            snippet = item.get("snippet", "")
            if title and url:
                lines.append(f"  {title}: {url}")
            elif url:
                lines.append(f"  {url}")
            if snippet:
                lines.append(f"    {snippet[:100]}")
    return "\n".join(lines) if lines else "(无搜索结果)"


def _format_server_fetch_result(block: dict) -> str:
    """格式化抓取结果。"""
    content = block.get("content", "")
    if isinstance(content, dict):
        data = content.get("data", "")
        if data:
            return str(data)[:200]
        err = content.get("error_code", "")
        if err:
            return f"[抓取错误: {err}]"
    return str(content)[:200]


async def _handle_resume(websocket: WebSocket, bridge: AgentBridge, session_id: str,
                         task_lock: asyncio.Lock | None = None):
    """恢复指定会话。"""
    from session import load_session
    user_id = bridge.state.get("user_id", "") or ""

    if task_lock and task_lock.locked():
        old_session_id = bridge.session_id
        bridge.soft_interrupt()
        for _ in range(30):
            await asyncio.sleep(0.1)
            if not task_lock.locked():
                break
        if old_session_id != session_id:
            bridge.state["_notify_complete_session"] = old_session_id

    try:
        loaded_messages, saved_cwd, meta = load_session(session_id, user_id)
        _log("_handle_resume 加载会话: session=%s messages=%d user=%s", session_id, len(loaded_messages), user_id)
        bridge.messages.clear()
        bridge.messages.extend(loaded_messages)
        bridge.session_id = session_id
        bridge.state["session_id"] = session_id

        if saved_cwd and os.path.isdir(saved_cwd):
            bridge.agent_state.set_cwd(saved_cwd)

        serialized = _serialize_messages_for_frontend(loaded_messages)

        bridge.state["current_agent"] = None
        bridge.state["agent_persona"] = None
        bridge.state["session_tokens"] = {"input": 0, "output": 0}
        bridge.state["session_cost_usd"] = 0.0

        await websocket.send_json(
            {
                "type": "session_resumed",
                "text": "",
                "meta": {
                    "session_id": session_id,
                    "message_count": len(loaded_messages),
                    "messages": serialized,
                    "agent": "default",
                },
            }
        )
    except FileNotFoundError:
        await websocket.send_json(
            {
                "type": "error",
                "text": f"会话不存在: {session_id}",
                "meta": {},
            }
        )


def _strip_ansi(text: str) -> str:
    """去除 ANSI 颜色转义码。"""
    return re.sub(r"\033\[[0-9;]*m", "", text)
