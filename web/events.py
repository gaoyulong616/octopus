"""事件序列化：将 agent 内部事件转为 JSON 安全的 WebSocket 消息。"""

from __future__ import annotations

from typing import Any

_MAX_TEXT_SIZE = 50_000


def serialize_event(
    event_type: str,
    text: str,
    meta: dict | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """将 agent emit 的事件转为 JSON 可序列化的 dict。

    session_id 用于多会话并行时前端路由事件到对应 tab。
    若为 None 则不填（前端按 active session 处理）。
    """
    meta = meta or {}
    safe_meta: dict[str, Any] = {}
    for k, v in meta.items():
        if k == "full_result":
            # full_result 可能很大，不发送完整内容
            raw = str(v)
            if len(raw) > 500:
                truncated = raw[:500]
                last_safe = max(truncated.rfind(" "), truncated.rfind("\n"), truncated.rfind("."))
                if last_safe > 400:
                    truncated = truncated[:last_safe]
                safe_meta["result_preview"] = truncated + "..."
            else:
                safe_meta["result_preview"] = raw
            continue
        if isinstance(v, (str, int, float, bool, type(None))):
            safe_meta[k] = v
        elif isinstance(v, dict):
            safe_meta[k] = _sanitize_dict(v)
        elif isinstance(v, (list, tuple)):
            safe_meta[k] = _sanitize_list(v)
    # 截断过长的 text 防止撑爆 WebSocket 帧
    if len(text) > _MAX_TEXT_SIZE:
        text = text[:_MAX_TEXT_SIZE] + f"\n... (截断，原始 {len(text)} 字符)"
    event: dict[str, Any] = {"type": event_type, "text": text, "meta": safe_meta}
    if session_id is not None:
        event["session_id"] = session_id
    return event


def _sanitize_dict(d: dict) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (str, int, float, bool, type(None))):
            result[k] = v
        elif isinstance(v, dict):
            result[k] = _sanitize_dict(v)
        elif isinstance(v, (list, tuple)):
            result[k] = _sanitize_list(v)
    return result


def _sanitize_list(lst: list | tuple) -> list[Any]:
    result: list[Any] = []
    for v in lst:
        if isinstance(v, (str, int, float, bool, type(None))):
            result.append(v)
        elif isinstance(v, dict):
            result.append(_sanitize_dict(v))
        elif isinstance(v, (list, tuple)):
            result.append(_sanitize_list(v))
    return result
