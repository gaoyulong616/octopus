"""事件序列化：将 agent 内部事件转为 JSON 安全的 WebSocket 消息。"""

from __future__ import annotations

from typing import Any


def serialize_event(event_type: str, text: str, meta: dict | None = None) -> dict[str, Any]:
    """将 agent emit 的事件转为 JSON 可序列化的 dict。"""
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
    return {"type": event_type, "text": text, "meta": safe_meta}


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
