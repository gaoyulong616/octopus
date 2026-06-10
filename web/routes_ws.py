"""WebSocket 端点：流式事件推送 + 双向命令通信。"""

from __future__ import annotations

import asyncio
import json
import os
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.agent_bridge import AgentBridge

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # 从 query 参数验证 token
    from web.app import get_auth_token
    token = websocket.query_params.get("token", "")
    if token != get_auth_token():
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()
    bridge = AgentBridge(loop)

    # 初始化会话：优先恢复最近更新的有内容会话
    from session import create_session, list_sessions, load_session
    from config import get, is_trusted_dir

    resume_id = None
    loaded_messages = []
    saved_cwd = None
    # 找到最新的有实际内容的会话（已按 updated_at 倒序）
    sessions = list_sessions()
    for s in sessions:
        sid = s.get("session_id")
        if not sid or s.get("message_count", 0) == 0:
            continue
        try:
            msgs, cwd_s, _ = load_session(sid)
            if msgs:
                resume_id = sid
                loaded_messages = msgs
                saved_cwd = cwd_s
                break
        except FileNotFoundError:
            continue

    if resume_id:
        bridge.session_id = resume_id
        bridge.messages.extend(loaded_messages)
        if saved_cwd and os.path.isdir(saved_cwd):
            bridge.agent_state.set_cwd(saved_cwd)
    else:
        bridge.session_id = create_session()

    bridge.state["session_id"] = bridge.session_id
    bridge.init_mcp()

    model = get("model")
    cwd = os.getcwd()
    trusted = is_trusted_dir(cwd)

    try:
        # 序列化恢复的消息
        resumed_messages = []
        if loaded_messages:
            resumed_messages = _serialize_messages_for_frontend(loaded_messages)

        await websocket.send_json({
            "type": "connected",
            "text": "",
            "meta": {
                "session_id": bridge.session_id,
                "model": model,
                "cwd": cwd,
                "trusted": trusted,
                "messages": resumed_messages,
            },
        })
    except Exception as e:
        from logger import log
        log(f"ws initial send failed: {e}")
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
        pass
    finally:
        # 先保存会话，再 cleanup（cleanup 会中断 agent 线程）
        if bridge.session_id and bridge.messages:
            from session import save_session
            save_session(bridge.messages, session_id=bridge.session_id)
        bridge.cancel_all_confirms()
        bridge.interrupt()
        bridge.cleanup()


async def _relay_events(websocket: WebSocket, bridge: AgentBridge):
    """唯一的事件消费者：将 agent 事件推送到 WebSocket。

    _handle_task 只启动 agent，不消费队列，避免竞争。
    """
    try:
        while True:
            event = await bridge.event_queue.get()
            try:
                await websocket.send_json(event)
            except Exception as e:
                from logger import log
                log(f"ws relay send failed: {e}")
                break
    except asyncio.CancelledError:
        pass


async def _handle_commands(websocket: WebSocket, bridge: AgentBridge):
    """读取浏览器命令并分发处理。"""
    try:
        while True:
            if bridge.state.get("_should_quit"):
                break
            try:
                data = await websocket.receive_json()
            except Exception:
                break

            action = data.get("action", "")

            from logger import log as _log
            _log(f"ws recv action={action}")

            try:
                if action == "task":
                    asyncio.create_task(_handle_task(websocket, bridge, data.get("text", ""), bridge.task_lock))

                elif action == "confirm":
                    confirm_id = data.get("confirm_id", "")
                    approved = data.get("approved", False)
                    approve_all = data.get("approve_all", False)
                    from logger import log as _log
                    _log(f"ws confirm received: id={confirm_id} approved={approved} approve_all={approve_all}")
                    if approve_all and approved:
                        tool_name = bridge.get_confirm_tool_name(confirm_id)
                        _log(f"ws confirm tool_name={tool_name}")
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
                    # 后台启动，避免阻塞命令处理（/init 等会 await _handle_task）
                    asyncio.create_task(_handle_slash(websocket, bridge, data.get("text", ""), bridge.task_lock))

                elif action == "resume":
                    await _handle_resume(websocket, bridge, data.get("session_id", ""))

                elif action == "new_session":
                    skip_save = data.get("skip_save", False)
                    if not skip_save and bridge.session_id and bridge.messages:
                        from session import save_session
                        save_session(bridge.messages, session_id=bridge.session_id)
                    from session import create_session
                    new_id = create_session()
                    bridge.session_id = new_id
                    bridge.state["session_id"] = new_id
                    bridge.messages.clear()
                    await websocket.send_json({
                        "type": "session_created",
                        "text": "",
                        "meta": {"session_id": new_id},
                    })

                elif action == "set_mode":
                    mode = data.get("mode", "auto")
                    bridge.state["plan_mode"] = mode == "plan"
                    if mode == "plan":
                        bridge.state.pop("auto_approved_tools", None)
                    await websocket.send_json({
                        "type": "mode_changed",
                        "text": mode,
                        "meta": {},
                    })

                elif action == "plan_approve":
                    bridge.state["plan_mode"] = False
                    await websocket.send_json({
                        "type": "mode_changed",
                        "text": "auto",
                        "meta": {"note": "计划已批准，已切换到 Auto 模式，开始执行..."},
                    })
                    # 取出暂存的计划并作为新任务执行（通过 _handle_task 获取锁保护）
                    plan = bridge._pending_plan
                    if plan:
                        bridge._pending_plan = None
                        exec_prompt = (
                            "用户已批准以下实施计划，请立即按照计划逐步执行。\n\n"
                            f"## 实施计划\n\n{plan}"
                        )
                        asyncio.create_task(_handle_task(websocket, bridge, exec_prompt, bridge.task_lock))

                elif action == "plan_reject":
                    bridge._pending_plan = None
                    await websocket.send_json({
                        "type": "info",
                        "text": "计划未批准，仍处于 Plan 模式",
                        "meta": {},
                    })

                elif action == "trust_dir":
                    from config import trust_dir
                    from tools import get_cwd
                    trust_dir(get_cwd())
                    bridge.state["plan_mode"] = False
                    await websocket.send_json({
                        "type": "info", "text": "目录已信任", "meta": {},
                    })

                elif action == "switch_model":
                    model_name = data.get("model", "")
                    if model_name:
                        from config import switch_model, get
                        try:
                            resolved = switch_model(model_name)
                            current = get("model")
                            await websocket.send_json({
                                "type": "model_changed",
                                "text": current,
                                "meta": {"model": current, "requested": model_name, "resolved": resolved},
                            })
                        except ValueError as e:
                            await websocket.send_json({
                                "type": "error",
                                "text": str(e),
                            })

                elif action == "send_image":
                    # 前端发送的图片（base64），暂存到 bridge 的 pending images
                    image_data = data.get("image", "")
                    media_type = data.get("media_type", "image/png")
                    if image_data:
                        bridge.state.setdefault("_pending_images", []).append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        })
            except Exception as e:
                from logger import log as _log
                _log(f"ws action handler error: action={action} error={e}")

    except asyncio.CancelledError:
        pass


async def _handle_task(websocket: WebSocket, bridge: AgentBridge, task: str,
                       task_lock: asyncio.Lock | None = None):
    """启动 agent 执行任务。事件转发由 _relay_events 统一处理。"""
    if not task.strip():
        return
    if task_lock and task_lock.locked():
        await websocket.send_json({
            "type": "error", "text": "Agent 正在执行任务，请等待完成或发送中断",
            "meta": {},
        })
        return
    if task_lock:
        await task_lock.acquire()
    try:
        bridge.state.pop("last_task", None)
        # 如果有暂存的图片，附加到 user message 中
        pending_images = bridge.state.pop("_pending_images", None)
        if pending_images:
            content_parts = [{"type": "text", "text": task}]
            content_parts.extend(pending_images)
            bridge.messages.append({"role": "user", "content": content_parts})
            bridge.start_task(task, skip_user_message=True)
        else:
            bridge.start_task(task)

        # 等待 agent 完成标志（不消费队列，只检查状态）
        try:
            await bridge._done_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            # 保存会话
            if bridge.session_id and bridge.messages:
                from session import save_session
                save_session(bridge.messages, session_id=bridge.session_id)
            # 检测是否中断
            if bridge.state.get("_interrupted"):
                bridge.state.pop("_interrupted", None)
                bridge.state["last_task"] = task
    finally:
        if task_lock and task_lock.locked():
            task_lock.release()


async def _handle_slash(websocket: WebSocket, bridge: AgentBridge, cmd: str,
                        task_lock: asyncio.Lock | None = None):
    """处理 slash 命令，适配 web 环境。"""
    cmd = cmd.strip()
    if not cmd:
        return
    name = cmd.split(maxsplit=1)[0].lower()

    if name == "/init":
        await _handle_init(websocket, bridge, cmd, task_lock)
        return

    if name == "/resume" and cmd.strip() == "/resume":
        await websocket.send_json({
            "type": "show_session_picker", "text": "", "meta": {},
        })
        return

    if name == "/export":
        await _handle_export(websocket, bridge, cmd)
        return

    if name == "/clear":
        bridge.messages.clear()
        await websocket.send_json({
            "type": "messages_cleared", "text": "对话历史已清除", "meta": {},
        })
        return

    from commands import dispatch_command
    result = dispatch_command(cmd, bridge.messages, bridge.state)

    if result is None:
        await websocket.send_json({
            "type": "slash_result", "text": f"未知命令: {cmd}", "meta": {},
        })
        return

    if result.quit:
        bridge.state["_should_quit"] = True
        await websocket.send_json({
            "type": "slash_result", "text": "会话已结束", "meta": {},
        })
        await websocket.close()
        return

    if result.task_override:
        await websocket.send_json({
            "type": "slash_result", "text": f"执行: {result.task_override[:100]}", "meta": {},
        })
        await _handle_task(websocket, bridge, result.task_override, task_lock)
        return

    text = _strip_ansi(result.text or "")
    await websocket.send_json({
        "type": "slash_result", "text": text, "meta": {},
    })


async def _handle_init(websocket: WebSocket, bridge: AgentBridge, cmd: str,
                        task_lock: asyncio.Lock | None = None):
    """/init 的 web 适配：跳过 input() 确认，直接生成。"""
    from tools import get_cwd, run_list_files
    import os as _os

    # /init 是独立任务，清空历史避免旧上下文干扰（如"已生成 OCTOPUS.md"摘要导致跳过写文件）
    bridge.messages.clear()
    try:
        await websocket.send_json({"type": "messages_cleared", "text": "", "meta": {}})
    except Exception:
        pass

    cwd = get_cwd()
    target = "OCTOPUS.md"
    existing_path = _os.path.join(cwd, "OCTOPUS.md")

    files_output = run_list_files(".", "", recursive=True) or ""
    top_files = run_list_files(".", "", recursive=False) or ""

    lang_hints, framework_hints = [], []
    py_files = [f for f in files_output.split("\n") if f.endswith(".py")]
    js_files = [f for f in files_output.split("\n") if f.endswith((".js", ".ts", ".tsx", ".jsx"))]
    if py_files:
        lang_hints.append("Python")
        if any("manage.py" in f for f in py_files):
            framework_hints.append("Django")
        if any("app.py" in f or "main.py" in f for f in py_files):
            framework_hints.append("Flask/FastAPI")
    if js_files:
        lang_hints.append("JavaScript/TypeScript")
        if any("next.config" in f for f in js_files):
            framework_hints.append("Next.js")
        if any("package.json" in f for f in files_output.split("\n")):
            framework_hints.append("Node.js")

    is_git = _os.path.isdir(_os.path.join(cwd, ".git"))

    readme_content = ""
    for readme_name in ("README.md", "readme.md"):
        readme_path = _os.path.join(cwd, readme_name)
        if _os.path.isfile(readme_path):
            try:
                with open(readme_path, encoding="utf-8", errors="ignore") as f:
                    readme_content = f.read()[:1000]
            except OSError:
                pass
            break

    existing_content = ""
    if _os.path.exists(existing_path):
        try:
            with open(existing_path, encoding="utf-8") as f:
                existing_content = f.read()
        except OSError:
            pass

    project_name = _os.path.basename(cwd)
    lang_str = "/".join(lang_hints) if lang_hints else "Unknown"
    fw_str = ", ".join(framework_hints) if framework_hints else ""

    init_prompt = (
        f"请为项目 '{project_name}' 生成项目指令文件 {target}。\n\n"
        f"## 项目信息\n- 路径: {cwd}\n- 语言: {lang_str}\n"
    )
    if fw_str:
        init_prompt += f"- 框架: {fw_str}\n"
    if is_git:
        init_prompt += "- Git: 是\n"
    init_prompt += f"\n## 顶层文件\n```\n{top_files[:500]}\n```\n"
    if readme_content:
        init_prompt += f"\n## README 摘要\n```\n{readme_content[:500]}\n```\n"
    init_prompt += (
        f"\n## 要求\n1. 分析项目结构，生成清晰的项目指令文件\n"
        f"2. 包含：项目概述、架构说明、运行方式、开发指南\n"
        f"3. 用中文编写\n4. 直接将内容写入 {target}\n"
    )
    if existing_content:
        init_prompt += f"\n## 现有内容（作为参考改进）\n```\n{existing_content[:1000]}\n```\n"

    await websocket.send_json({
        "type": "slash_result", "text": f"生成 {target}...", "meta": {},
    })
    await _handle_task(websocket, bridge, init_prompt, task_lock)


async def _handle_export(websocket: WebSocket, bridge: AgentBridge, cmd: str):
    """/export 的 web 适配：返回内容供浏览器下载。"""
    from session import load_session

    session_id = bridge.session_id
    if not session_id:
        await websocket.send_json({
            "type": "error", "text": "当前没有活跃会话", "meta": {},
        })
        return

    try:
        messages, session_cwd, meta = load_session(session_id)
    except FileNotFoundError:
        await websocket.send_json({
            "type": "error", "text": "会话不存在", "meta": {},
        })
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
    await websocket.send_json({
        "type": "export_data",
        "text": text,
        "meta": {"filename": f"session_{session_id[:8]}.txt"},
    })


def _serialize_messages_for_frontend(messages: list) -> list:
    """将会话消息序列化为前端可渲染的简洁格式。

    过滤掉 tool_result（太长），只保留 user 文本、assistant 文本和 tool_use 调用。
    自动去重重复的 content blocks。
    对已完成的历史 tool_use 附加 done/result 字段，Web UI 可据此跳过 spinner。
    """
    # 第一遍：收集所有 tool_result
    tool_results: dict[str, str] = {}
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = block.get("tool_use_id", "")
                    if tid:
                        tool_results[tid] = str(block.get("content", ""))

    # 第二遍：配对 server_tool_use 和 web_search/fetch 结果（按位置顺序）
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
                        entry["blocks"].append({
                            "type": "image",
                            "data_url": f"data:{media_type};base64,{data}",
                        })
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
    """将 web_search_tool_result 格式化为可展示文本。"""
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
    """将 web_fetch_tool_result 格式化为可展示文本。"""
    content = block.get("content", "")
    if isinstance(content, dict):
        data = content.get("data", "")
        if data:
            return str(data)[:200]
        err = content.get("error_code", "")
        if err:
            return f"[抓取错误: {err}]"
    return str(content)[:200]


async def _handle_resume(websocket: WebSocket, bridge: AgentBridge, session_id: str):
    """恢复指定会话，发送历史消息给前端渲染。"""
    from session import load_session
    try:
        loaded_messages, saved_cwd, meta = load_session(session_id)
        bridge.messages.clear()
        bridge.messages.extend(loaded_messages)
        bridge.session_id = session_id
        bridge.state["session_id"] = session_id

        if saved_cwd and os.path.isdir(saved_cwd):
            bridge.agent_state.set_cwd(saved_cwd)

        serialized = _serialize_messages_for_frontend(loaded_messages)

        await websocket.send_json({
            "type": "session_resumed",
            "text": "",
            "meta": {
                "session_id": session_id,
                "message_count": len(loaded_messages),
                "messages": serialized,
            },
        })
    except FileNotFoundError:
        await websocket.send_json({
            "type": "error", "text": f"会话不存在: {session_id}", "meta": {},
        })


def _strip_ansi(text: str) -> str:
    """去除 ANSI 颜色转义码。"""
    return re.sub(r'\033\[[0-9;]*m', '', text)
