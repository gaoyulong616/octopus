"""WebSocket 端点：流式事件推送 + 双向命令通信。"""

from __future__ import annotations

import asyncio
import os
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from logger import log as _log
from web.agent_bridge import AgentBridge
from web.connection import Connection

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
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
    loop = asyncio.get_running_loop()
    connection = Connection(websocket, user, loop)

    from config import get, is_trusted_dir
    from session import create_session
    from web.agent_bridge import compute_session_cwd

    initial_session_id = create_session(user_id=user.id)
    bridge = connection.get_or_create_bridge(initial_session_id)
    session_cwd = compute_session_cwd(user.id, initial_session_id)
    bridge.agent_state.set_cwd(session_cwd)
    connection.switch_active(initial_session_id)

    _log("ws 连接: session=%s user=%s 池大小=1", bridge.session_id, user.username)

    model = get("model")
    cwd = bridge.agent_state.get_cwd()
    trusted = is_trusted_dir(cwd)

    try:
        await connection.send_json(
            {
                "type": "connected",
                "text": "",
                "meta": {
                    "session_id": bridge.session_id,
                    "model": model,
                    "cwd": cwd,
                    "trusted": trusted,
                    "messages": [],
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                    },
                },
            }
        )
    except Exception as e:
        _log("ws initial send failed: %s", e)
        return

    command_task = asyncio.create_task(_handle_commands(connection))

    try:
        await command_task
    except WebSocketDisconnect:
        _log("ws 断开")
    finally:
        # 持久化所有活跃会话
        from session import save_session

        for sid, b in connection.bridges.items():
            if sid and b.messages:
                try:
                    save_session(b.messages, session_id=sid, user_id=user.id)
                except Exception as e:
                    _log("save_session 失败 session=%s: %s", sid, e)
        connection.force_cleanup()


async def _handle_commands(connection: Connection):
    try:
        while True:
            if connection.active_bridge and connection.active_bridge.state.get("_should_quit"):
                break
            try:
                data = await connection.receive_json()
            except Exception:
                break

            action = data.get("action", "")

            # disconnect_session/delete_session 在 bridge 路由前处理，因为目标 session 可能不是 active_bridge
            if action == "disconnect_session":
                target_sid = data.get("session_id", "")
                if target_sid and connection.has_bridge(target_sid):
                    connection._archive_and_detach(target_sid)
                    # 显式带 session_id=target_sid，避免 _archive_and_detach 改了 active_session_id 后
                    # 被 send_json 自动注入成池中其他 bridge 的 id，导致前端误判为后台事件
                    await connection.send_json({
                        "type": "session_disconnected",
                        "text": "",
                        "meta": {"session_id": target_sid},
                        "session_id": target_sid,
                    })
                continue

            if action == "delete_session":
                target_sid = data.get("session_id", "")
                if target_sid:
                    # 先从活跃池移除（如存在）
                    if connection.has_bridge(target_sid):
                        connection._archive_and_detach(target_sid)
                    # 再删除文件
                    from session import _project_dir
                    import os
                    project = _project_dir(user_id=connection.user.id if connection.user else None)
                    filepath = project / f"{target_sid}.jsonl"
                    if filepath.exists():
                        filepath.unlink()
                    index_file = project / "index.json"
                    if index_file.exists():
                        from session import _with_file_lock_atomic
                        import json
                        def _rmv(out_f):
                            try:
                                with open(index_file, encoding="utf-8") as f:
                                    idx = json.load(f)
                                idx.pop(target_sid, None)
                                json.dump(idx, out_f, ensure_ascii=False, indent=2)
                            except (json.JSONDecodeError, OSError):
                                pass
                        try:
                            _with_file_lock_atomic(index_file, _rmv)
                        except OSError:
                            pass
                    await connection.send_json({
                        "type": "session_deleted",
                        "text": "",
                        "meta": {"session_id": target_sid},
                        "session_id": target_sid,
                    })
                continue

            # 按 session_id 路由到对应 bridge（默认 active_bridge）
            # confirm/ask_response 这类响应型 action 必须按 session_id 路由，
            # 否则切走后后台会话的 confirm_id 在 active_bridge 找不到
            sid = data.get("session_id") or ""
            if sid and connection.has_bridge(sid):
                bridge = connection.get_bridge(sid)
            else:
                bridge = connection.active_bridge
            if bridge is None:
                _log("ws action 无活跃 bridge，丢弃: action=%s", action)
                continue

            _log("ws action: %s session=%s", action, bridge.session_id)

            try:
                if action == "task":
                    asyncio.create_task(_handle_task(connection, bridge, data.get("text", ""), bridge.task_lock))

                elif action == "confirm":
                    confirm_id = data.get("confirm_id", "")
                    approved = data.get("approved", False)
                    approve_all = data.get("approve_all", False)
                    reason = data.get("reason") or None
                    _log("ws confirm: id=%s approved=%s approve_all=%s reason=%s", confirm_id, approved, approve_all, reason)
                    if approve_all and approved:
                        tool_name = bridge.get_confirm_tool_name(confirm_id)
                        _log("ws confirm tool_name=%s", tool_name)
                        if tool_name:
                            bridge.state.setdefault("auto_approved_tools", set()).add(tool_name)
                    bridge.resolve_confirm(confirm_id, approved, reason)

                elif action == "ask_response":
                    ask_id = data.get("ask_id", "")
                    answer = data.get("answer", "")
                    bridge.resolve_ask(ask_id, answer)

                elif action == "interrupt":
                    bridge.interrupt()

                elif action == "slash":
                    asyncio.create_task(_handle_slash(connection, bridge, data.get("text", ""), bridge.task_lock))

                elif action == "resume":
                    await _handle_resume(connection, data.get("session_id", ""))

                elif action == "new_session":
                    # 新会话：旧 bridge 不销毁，进入池继续跑
                    skip_save = data.get("skip_save", False)
                    if not skip_save and bridge.session_id and bridge.messages:
                        from session import save_session

                        save_session(bridge.messages, session_id=bridge.session_id, user_id=bridge.state.get("user_id"))
                    from session import create_session
                    from web.agent_bridge import compute_session_cwd

                    new_id = create_session(user_id=bridge.state.get("user_id"))
                    new_bridge = connection.get_or_create_bridge(new_id)
                    session_cwd = compute_session_cwd(bridge.state.get("user_id"), new_id)
                    new_bridge.agent_state.set_cwd(session_cwd)
                    connection.switch_active(new_id)
                    _log("new_session 切换前台: old=%s new=%s 池大小=%d",
                         bridge.session_id, new_id, len(connection.bridges))
                    await connection.send_json(
                        {
                            "type": "session_created",
                            "text": "",
                            "meta": {"session_id": new_id},
                        }
                    )

                elif action == "set_mode":
                    mode = data.get("mode", "accept-edits")
                    if mode not in ("plan", "accept-edits", "auto"):
                        mode = "accept-edits"
                    bridge.state["mode"] = mode
                    # 切模式=重置会话级放行（与 TUI Shift+Tab 一致）
                    bridge.state["auto_approved_tools"] = set()
                    await connection.send_json(
                        {
                            "type": "mode_changed",
                            "text": mode,
                            "meta": {},
                        }
                    )

                elif action == "plan_approve":
                    bridge.state["mode"] = "accept-edits"
                    await connection.send_json(
                        {
                            "type": "mode_changed",
                            "text": "accept-edits",
                            "meta": {"note": "计划已批准，已切换到 Accept Edits 模式，开始执行..."},
                        }
                    )
                    plan = bridge._pending_plan
                    if plan:
                        bridge._pending_plan = None
                        exec_prompt = f"用户已批准以下实施计划，请立即按照计划逐步执行。\n\n## 实施计划\n\n{plan}"
                        asyncio.create_task(_handle_task(connection, bridge, exec_prompt, bridge.task_lock))

                elif action == "plan_reject":
                    bridge._pending_plan = None
                    await connection.send_json(
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
                    bridge.state["mode"] = "accept-edits"
                    await connection.send_json(
                        {
                            "type": "info",
                            "text": "目录已信任",
                            "meta": {},
                        }
                    )

                elif action == "switch_model":
                    model_name = data.get("model", "")
                    if model_name:
                        from config import get_models

                        all_models = get_models()

                        # 显式 provider/model 格式：精确匹配
                        if "/" in model_name:
                            p_hint, m_hint = model_name.split("/", 1)
                            matched = next(((mn, p) for mn, p in all_models if mn == m_hint and p == p_hint), None)
                            if not matched:
                                await connection.send_json(
                                    {"type": "error", "text": f"模型 '{model_name}' 不存在"}
                                )
                        else:
                            # 纯模型名：检测歧义
                            candidates = [(mn, p) for mn, p in all_models if mn == model_name]
                            if len(candidates) > 1:
                                opts = ", ".join(f"{p}/{mn}" for mn, p in candidates)
                                await connection.send_json(
                                    {"type": "error", "text": f"模型 '{model_name}' 存在于多个提供商，请指定: {opts}"}
                                )
                                matched = None
                            elif len(candidates) == 1:
                                matched = candidates[0]
                            else:
                                matched = None
                                await connection.send_json(
                                    {"type": "error", "text": f"模型 '{model_name}' 不存在"}
                                )

                        if matched:
                            resolved_model, resolved_provider = matched
                            bridge.agent_state.model = resolved_model
                            bridge.agent_state.provider = resolved_provider
                            await connection.send_json(
                                {
                                    "type": "model_changed",
                                    "text": resolved_model,
                                    "meta": {"model": resolved_model, "provider": resolved_provider, "requested": model_name, "resolved": (resolved_model, resolved_provider)},
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


async def _handle_task(connection: Connection, bridge: AgentBridge, task: str, task_lock: asyncio.Lock | None = None):
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
        else:
            bridge.messages.append({"role": "user", "content": task.strip()})
        # start_task 之前手动 append user 消息，确保 save_session 能立即写入
        bridge.start_task(task, skip_user_message=True)

        # 立即保存 user 消息到持久化，让会话列表能立即看到新会话
        if bridge.session_id:
            from session import save_session

            save_session(bridge.messages, session_id=bridge.session_id, user_id=bridge.state.get("user_id"))

        try:
            await bridge._done_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            if bridge.session_id and bridge.messages:
                from session import save_session

                _log("_handle_task 保存会话: session=%s messages=%d", bridge.session_id, len(bridge.messages))
                save_session(bridge.messages, session_id=bridge.session_id, user_id=bridge.state.get("user_id"))
            if bridge.state.get("_interrupted"):
                bridge.state.pop("_interrupted", None)
                bridge.state["last_task"] = task
    finally:
        if task_lock and task_lock.locked():
            task_lock.release()


async def _handle_slash(connection: Connection, bridge: AgentBridge, cmd: str, task_lock: asyncio.Lock | None = None):
    cmd = cmd.strip()
    if not cmd:
        return
    name = cmd.split(maxsplit=1)[0].lower()

    # Web UI 中 /model 和 /models 走下拉菜单（per-session），命令行形式会污染全局，直接拦截
    if name in ("/model", "/models"):
        await connection.send_json(
            {
                "type": "slash_result",
                "text": "Web UI 请用顶部下拉菜单切换/查看模型（每个会话独立选择）",
                "meta": {},
            }
        )
        return

    if name == "/init":
        await _handle_init(connection, bridge, cmd, task_lock)
        return

    if name == "/resume" and cmd.strip() == "/resume":
        await connection.send_json(
            {
                "type": "show_session_picker",
                "text": "",
                "meta": {},
            }
        )
        return

    if name == "/export":
        await _handle_export(connection, bridge, cmd)
        return

    if name == "/clear":
        if task_lock and task_lock.locked():
            bridge.soft_interrupt()
            for _ in range(30):
                await asyncio.sleep(0.1)
                if not task_lock.locked():
                    break
        bridge.messages.clear()
        await connection.send_json(
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
        await connection.send_json(
            {
                "type": "slash_result",
                "text": f"未知命令: {cmd}",
                "meta": {},
            }
        )
        return

    if result.quit:
        bridge.state["_should_quit"] = True
        await connection.send_json(
            {
                "type": "slash_result",
                "text": "会话已结束",
                "meta": {},
            }
        )
        await connection.close()
        return

    if result.task_override:
        await connection.send_json(
            {
                "type": "slash_result",
                "text": f"执行: {result.task_override[:100]}",
                "meta": {},
            }
        )
        await _handle_task(connection, bridge, result.task_override, task_lock)
        return

    text = _strip_ansi(result.text or "")
    await connection.send_json(
        {
            "type": "slash_result",
            "text": text,
            "meta": {},
        }
    )

    new_agent = bridge.state.get("current_agent")
    if new_agent != prev_agent:
        await connection.send_json(
            {
                "type": "agent_changed",
                "text": "",
                "meta": {"name": new_agent or "default"},
            }
        )

    new_model = _config_get("model")
    if new_model != prev_model:
        await connection.send_json(
            {
                "type": "model_changed",
                "text": new_model,
                "meta": {"model": new_model},
            }
        )


async def _handle_init(connection: Connection, bridge: AgentBridge, cmd: str, task_lock: asyncio.Lock | None = None):
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
        await connection.send_json({"type": "messages_cleared", "text": "", "meta": {}})
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

    await connection.send_json(
        {
            "type": "slash_result",
            "text": f"生成 {target}...",
            "meta": {},
        }
    )
    await _handle_task(connection, bridge, init_prompt, task_lock)


async def _handle_export(connection: Connection, bridge: AgentBridge, cmd: str):
    from session import load_session

    session_id = bridge.session_id
    if not session_id:
        await connection.send_json(
            {
                "type": "error",
                "text": "当前没有活跃会话",
                "meta": {},
            }
        )
        return

    try:
        messages, session_cwd, meta = load_session(session_id, user_id=bridge.state.get("user_id"))
    except FileNotFoundError:
        await connection.send_json(
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
    await connection.send_json(
        {
            "type": "export_data",
            "text": text,
            "meta": {"filename": f"session_{session_id[:8]}.md"},
        }
    )


def _serialize_messages_for_frontend(messages: list) -> list:
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
    content = block.get("content", "")
    if isinstance(content, dict):
        data = content.get("data", "")
        if data:
            return str(data)[:200]
        err = content.get("error_code", "")
        if err:
            return f"[抓取错误: {err}]"
    return str(content)[:200]


async def _handle_resume(connection: Connection, session_id: str):
    """恢复会话：从活跃池找或 load_session 创建新 bridge，不销毁原 bridge。"""
    from session import load_session

    if not session_id:
        return

    user_id = connection.user.id

    # 1. 池中已有 → 直接切换前台
    existing = connection.get_bridge(session_id)
    if existing is not None:
        connection.switch_active(session_id)
        serialized = _serialize_messages_for_frontend(existing.messages)
        _log("_handle_resume 池中切换: session=%s messages=%d", session_id, len(existing.messages))
        await connection.send_json(
            {
                "type": "session_resumed",
                "text": "",
                "meta": {
                    "session_id": session_id,
                    "message_count": len(existing.messages),
                    "messages": serialized,
                    "agent": "default",
                },
            }
        )
        return

    # 2. 池中没有 → load_session 创建新 bridge 加入池
    try:
        loaded_messages, saved_cwd, meta = load_session(session_id, user_id=user_id)
    except FileNotFoundError:
        await connection.send_json(
            {
                "type": "error",
                "text": f"会话不存在: {session_id}",
                "meta": {},
            }
        )
        return

    _log("_handle_resume 新建 bridge: session=%s messages=%d", session_id, len(loaded_messages))
    from web.agent_bridge import compute_session_cwd

    new_bridge = connection.get_or_create_bridge(session_id)
    new_bridge.messages.extend(loaded_messages)
    session_cwd = compute_session_cwd(user_id, session_id)
    new_bridge.agent_state.set_cwd(session_cwd)

    connection.switch_active(session_id)

    serialized = _serialize_messages_for_frontend(loaded_messages)
    await connection.send_json(
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


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)