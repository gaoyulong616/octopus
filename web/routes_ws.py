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

    # 初始化会话
    from session import create_session
    from config import get, is_trusted_dir

    bridge.session_id = create_session()
    bridge.state["session_id"] = bridge.session_id
    bridge.init_mcp()

    model = get("model")
    cwd = os.getcwd()
    trusted = is_trusted_dir(cwd)

    try:
        await websocket.send_json({
            "type": "connected",
            "text": "",
            "meta": {
                "session_id": bridge.session_id,
                "model": model,
                "cwd": cwd,
                "trusted": trusted,
            },
        })
    except Exception:
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
        bridge.cancel_all_confirms()
        bridge.interrupt()
        bridge.cleanup()
        if bridge.session_id and bridge.messages:
            from session import save_session
            save_session(bridge.messages, session_id=bridge.session_id)


async def _relay_events(websocket: WebSocket, bridge: AgentBridge):
    """唯一的事件消费者：将 agent 事件推送到 WebSocket。

    _handle_task 只启动 agent，不消费队列，避免竞争。
    """
    try:
        while True:
            event = await bridge.event_queue.get()
            try:
                await websocket.send_json(event)
            except Exception:
                break
    except asyncio.CancelledError:
        pass


async def _handle_commands(websocket: WebSocket, bridge: AgentBridge):
    """读取浏览器命令并分发处理。"""
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except Exception:
                break

            action = data.get("action", "")

            if action == "task":
                await _handle_task(websocket, bridge, data.get("text", ""))

            elif action == "confirm":
                confirm_id = data.get("confirm_id", "")
                approved = data.get("approved", False)
                approve_all = data.get("approve_all", False)
                if approve_all and approved:
                    tool_name = bridge.get_confirm_tool_name(confirm_id)
                    if tool_name:
                        bridge.state.setdefault("auto_approved_tools", set()).add(tool_name)
                bridge.resolve_confirm(confirm_id, approved)

            elif action == "interrupt":
                bridge.interrupt()

            elif action == "slash":
                await _handle_slash(websocket, bridge, data.get("text", ""))

            elif action == "resume":
                await _handle_resume(websocket, bridge, data.get("session_id", ""))

            elif action == "set_mode":
                mode = data.get("mode", "auto")
                bridge.state["plan_mode"] = mode == "plan"
                await websocket.send_json({
                    "type": "mode_changed",
                    "text": mode,
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

    except asyncio.CancelledError:
        pass


async def _handle_task(websocket: WebSocket, bridge: AgentBridge, task: str):
    """启动 agent 执行任务。事件转发由 _relay_events 统一处理。"""
    if not task.strip():
        return
    if bridge.is_running:
        await websocket.send_json({
            "type": "error", "text": "Agent 正在执行任务，请等待完成或发送中断",
            "meta": {},
        })
        return

    bridge.state.pop("last_task", None)
    bridge.start_task(task)
    busy = True

    # 等待 agent 完成标志（不消费队列，只检查状态）
    try:
        while bridge.is_running:
            await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        pass
    finally:
        busy = False
        # 保存会话
        if bridge.session_id and bridge.messages:
            from session import save_session
            save_session(bridge.messages, session_id=bridge.session_id)
        # 检测是否中断
        if bridge.state.get("_interrupted"):
            bridge.state.pop("_interrupted", None)
            bridge.state["last_task"] = task


async def _handle_slash(websocket: WebSocket, bridge: AgentBridge, cmd: str):
    """处理 slash 命令，适配 web 环境。"""
    name = cmd.strip().split(maxsplit=1)[0].lower()

    if name == "/init":
        await _handle_init(websocket, bridge, cmd)
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
        await websocket.send_json({
            "type": "slash_result", "text": "__QUIT__", "meta": {},
        })
        return

    if result.task_override:
        await websocket.send_json({
            "type": "slash_result", "text": f"执行: {result.task_override[:100]}", "meta": {},
        })
        await _handle_task(websocket, bridge, result.task_override)
        return

    text = _strip_ansi(result.text or "")
    await websocket.send_json({
        "type": "slash_result", "text": text, "meta": {},
    })


async def _handle_init(websocket: WebSocket, bridge: AgentBridge, cmd: str):
    """/init 的 web 适配：跳过 input() 确认，直接生成。"""
    from tools import get_cwd, run_list_files
    import os as _os

    cwd = get_cwd()
    target = "OCTOPUS.md"
    existing_path = _os.path.join(cwd, "OCTOPUS.md")
    if not _os.path.exists(existing_path):
        claude_path = _os.path.join(cwd, "CLAUDE.md")
        if _os.path.exists(claude_path):
            target = "CLAUDE.md"
            existing_path = claude_path

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
    await _handle_task(websocket, bridge, init_prompt)


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


async def _handle_resume(websocket: WebSocket, bridge: AgentBridge, session_id: str):
    """恢复指定会话。"""
    from session import load_session
    try:
        loaded_messages, saved_cwd, meta = load_session(session_id)
        bridge.messages.clear()
        bridge.messages.extend(loaded_messages)
        bridge.session_id = session_id
        bridge.state["session_id"] = session_id

        if saved_cwd and os.path.isdir(saved_cwd):
            from tools import set_cwd
            set_cwd(saved_cwd)

        await websocket.send_json({
            "type": "session_resumed",
            "text": "",
            "meta": {
                "session_id": session_id,
                "message_count": len(loaded_messages),
            },
        })
    except FileNotFoundError:
        await websocket.send_json({
            "type": "error", "text": f"会话不存在: {session_id}", "meta": {},
        })


def _strip_ansi(text: str) -> str:
    """去除 ANSI 颜色转义码。"""
    return re.sub(r'\033\[[0-9;]*m', '', text)
