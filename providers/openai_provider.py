"""OpenAI 兼容 API Provider：支持 GPT / DeepSeek / GLM / Qwen 等。"""

from __future__ import annotations

import json
import threading
from typing import Any, Generator

from config import get
from logger import get_logger as _get_logger

from .base import (
    LLMProvider,
    ProviderAPIError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderStreamEvent,
)


# ── Client 单例复用 ──

_client: Any = None
_client_keys: tuple = ()
_client_lock = threading.Lock()


def _import_openai():
    """延迟导入 openai，避免未安装时直接 ImportError。"""
    try:
        import openai
        return openai
    except ImportError:
        raise ImportError(
            "使用 OpenAI 兼容 Provider 需安装 openai 包：pip install openai"
        )


class OpenAIProvider(LLMProvider):
    """OpenAI 兼容 API Provider。

    消息格式转换：
      - 内部 Anthropic 风格 content blocks → OpenAI messages/tool_calls
      - OpenAI 流式响应 → ProviderStreamEvent + ProviderResponse

    支持通过 name 参数绑定到不同的 Provider 配置（如 openai / ds_openai），
    这样同一套转换逻辑可复用给多个 OpenAI 兼容 API。
    """

    _last_response: ProviderResponse | None = None
    _last_response_data: dict | None = None  # 原始响应数据（tool_calls 等）

    def __init__(self, name: str = "openai"):
        self._name = name

    # ── Client 创建 ──

    def get_client(self) -> Any:
        global _client, _client_keys
        openai = _import_openai()

        # 按优先级取配置：providers[self._name] > 顶层 base_url/api_key
        provider_cfg = (get("providers") or {}).get(self._name, {})
        base_url = provider_cfg.get("base_url") or get("base_url")
        api_key = provider_cfg.get("api_key") or get("api_key")

        current_keys = (base_url, api_key)
        with _client_lock:
            if _client is None or _client_keys != current_keys:
                _client = openai.OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                )
                _client_keys = current_keys
        return _client

    # ── 服务端工具探测（OpenAI 不支持） ──

    def probe_server_tools(self, model: str) -> set[str]:
        return set()

    # ── 流式调用 ──

    def stream(
        self,
        messages: list[dict],
        system: list[dict] | None,
        tools: list[dict],
        model: str,
        max_tokens: int,
        **kwargs,
    ) -> Generator[ProviderStreamEvent, None, None]:
        _log = _get_logger()
        client = self.get_client()
        self._last_response = None
        self._last_response_data = None

        # 转换消息格式
        openai_messages = self._convert_messages(messages, system)
        # 转换工具 schema
        openai_tools = self._convert_tools(tools)

        stream_kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            messages=openai_messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        if openai_tools:
            stream_kwargs["tools"] = openai_tools

        _log.debug(
            "OpenAI 请求: model=%s max_tokens=%d messages=%d tools=%d",
            model,
            max_tokens,
            len(openai_messages),
            len(openai_tools),
        )

        try:
            response = client.chat.completions.create(**stream_kwargs)
        except _import_openai().RateLimitError as e:
            raise ProviderRateLimitError(str(e)) from e
        except _import_openai().APIStatusError as e:
            if e.status_code == 401:
                raise ProviderAuthError(
                    "API 认证失败 (401)。请检查 API Key 是否正确配置。\n"
                    "  配置文件: ~/.octopus/config.json\n"
                    "  环境变量: OCTOPUS_API_KEY"
                ) from e
            raise ProviderAPIError(str(e), status_code=e.status_code) from e

        # 流式处理：增量合并 tool_calls
        tool_call_acc: dict[int, dict] = {}  # index -> {id, name, arguments}
        finish_reason: str | None = None
        response_content: str = ""
        response_tool_calls: list[dict] = []
        usage: dict | None = None

        for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            finish = chunk.choices[0].finish_reason if chunk.choices else None

            # Text token
            if delta and delta.content:
                yield ProviderStreamEvent(type="text", text=delta.content)
                response_content += delta.content

            # Tool calls delta（增量合并）
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_call_acc:
                        tool_call_acc[idx] = {"id": "", "name": "", "arguments": ""}
                    acc = tool_call_acc[idx]
                    if tc.id:
                        acc["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            acc["name"] = tc.function.name
                        if tc.function.arguments:
                            acc["arguments"] += tc.function.arguments

            # Usage
            if chunk.usage:
                u = chunk.usage
                usage = {
                    "input_tokens": u.prompt_tokens,
                    "output_tokens": u.completion_tokens,
                }

            # Finish reason
            if finish:
                finish_reason = finish

        # 合并完整的 tool_calls
        for idx in sorted(tool_call_acc.keys()):
            tc = tool_call_acc[idx]
            try:
                arguments = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                _log.warning("tool_call %s arguments JSON 解析失败: %s", tc["id"], tc["arguments"][:200])
                arguments = {}
            response_tool_calls.append({
                "id": tc["id"],
                "name": tc["name"],
                "arguments": arguments,
            })
            yield ProviderStreamEvent(
                type="tool_call",
                tool_name=tc["name"],
                tool_input=arguments,
                tool_id=tc["id"],
            )

        # 构建完整响应
        self._last_response = self._convert_response(
            content=response_content,
            tool_calls=response_tool_calls,
            finish_reason=finish_reason or "stop",
            usage=usage,
        )
        _log.debug(
            "OpenAI 响应: finish_reason=%s content=%dchars tool_calls=%d",
            finish_reason,
            len(response_content),
            len(response_tool_calls),
        )

    def get_response(self) -> ProviderResponse | None:
        return self._last_response

    # ── 非流式总结（用于上下文压缩） ──

    def summarize(self, prompt: str, model: str, max_tokens: int = 1024) -> str:
        client = self.get_client()
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content or ""
        return ""

    # ── 消息格式转换：内部格式 → OpenAI wire format ──

    def _convert_messages(self, messages: list[dict], system: list[dict] | None) -> list[dict]:
        """将 Anthropic 风格 messages 转为 OpenAI messages 数组。

        Anthropic system prompt（content blocks）转为 {"role": "system"} 放首位。
        """
        result: list[dict] = []

        # System prompt → role:system message
        if system:
            system_text = "\n\n".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in system
            )
            if system_text.strip():
                result.append({"role": "system", "content": system_text})

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user":
                converted = self._convert_user_message(content)
                if isinstance(converted, list):
                    result.extend(converted)
                else:
                    result.append(converted)
            elif role == "assistant":
                result.append(self._convert_assistant_message(content))
            elif role == "tool":
                # 已经是 OpenAI 格式（从其他 provider 转来），透传
                result.append(msg)
            else:
                result.append({"role": role, "content": str(content) if content else ""})

        return result

    def _convert_user_message(self, content: Any) -> dict:
        """Anthropic user message（content blocks）→ OpenAI user message.

        tool_result blocks → {"role": "tool", "tool_call_id": id, "content": str}
        text blocks → 合并为字符串
        """
        if isinstance(content, str):
            return {"role": "user", "content": content}

        if not isinstance(content, list):
            return {"role": "user", "content": str(content)}

        # 如果 content list 只有 text block，简单字符串即可
        text_parts: list[str] = []
        tool_results: list[dict] = []
        has_tool_result = False

        for block in content:
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_result":
                    has_tool_result = True
                    tool_results.append(self._convert_tool_result(block))
                else:
                    text_parts.append(str(block))
            elif isinstance(block, str):
                text_parts.append(block)
            else:
                # SDK 对象
                btype = getattr(block, "type", "")
                if btype == "text":
                    text_parts.append(getattr(block, "text", ""))
                elif btype == "tool_result":
                    has_tool_result = True
                    tid = getattr(block, "tool_use_id", "") or ""
                    tc = getattr(block, "content", "")
                    tc_str = json.dumps(tc, ensure_ascii=False) if not isinstance(tc, str) else tc
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tid,
                        "content": tc_str,
                    })
                else:
                    text_parts.append(str(block))

        # OpenAI 不支持 tool_result 在 user 消息内部混排：
        # 需要把 tool_result 拆成独立 {"role": "tool"} 消息
        if has_tool_result:
            result: list[dict] = []
            if text_parts and any(t.strip() for t in text_parts):
                merged = "\n\n".join(t for t in text_parts if t.strip())
                if merged.strip():
                    result.append({"role": "user", "content": merged})
            result.extend(tool_results)
            # 如果 messages 列表中有多个这样的消息会导致消息列表结构被破坏。
            # 但是 _convert_assistant_message 只产出一条 assistant 消息，
            # 所以这里返回的 list 会被父调用方展平。
            # 使用特殊标记：简化为单个 user + 多条 tool 消息。
            # 实际上，我们只需要返回一个代表多消息的 list，让 _convert_messages 去展平
            return result  # type: ignore[return-value]

        merged_text = "\n\n".join(t for t in text_parts if t.strip())
        return {"role": "user", "content": merged_text or ""}

    def _convert_tool_result(self, block: dict) -> dict:
        """Anthropic tool_result block → OpenAI tool message."""
        tid = block.get("tool_use_id", "")
        tc = block.get("content", "")
        tc_str = json.dumps(tc, ensure_ascii=False) if not isinstance(tc, str) else tc
        return {
            "role": "tool",
            "tool_call_id": tid,
            "content": tc_str,
        }

    def _convert_assistant_message(self, content: Any) -> dict:
        """Anthropic assistant message（content blocks）→ OpenAI assistant message。

        拆解方式：
          - text blocks → 合并为 content 字符串
          - tool_use blocks → tool_calls 数组
          - thinking/redacted_thinking → 丢弃
        """
        if isinstance(content, str):
            return {"role": "assistant", "content": content}

        if not isinstance(content, list):
            return {"role": "assistant", "content": str(content)}

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        seen_ids = set()

        for i, block in enumerate(content):
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tid = block.get("id", f"call_{i}")
                    if tid in seen_ids:
                        tid = f"{tid}_{i}"
                    seen_ids.add(tid)
                    tool_calls.append({
                        "id": tid,
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                        },
                    })
                # thinking/redacted_thinking/其他 —— 跳过
            else:
                btype = getattr(block, "type", "")
                if btype == "text":
                    text_parts.append(getattr(block, "text", ""))
                elif btype == "tool_use":
                    tid = getattr(block, "id", f"call_{i}")
                    if tid in seen_ids:
                        tid = f"{tid}_{i}"
                    seen_ids.add(tid)
                    tool_calls.append({
                        "id": tid,
                        "type": "function",
                        "function": {
                            "name": getattr(block, "name", ""),
                            "arguments": json.dumps(getattr(block, "input", {}), ensure_ascii=False),
                        },
                    })
                # 其他 block types 跳过

        result: dict = {"role": "assistant"}
        merged = "\n\n".join(t for t in text_parts if t.strip())
        if merged:
            result["content"] = merged
        if tool_calls:
            result["tool_calls"] = tool_calls

        return result

    # ── 工具 Schema 转换 ──

    def convert_tools(self, tools: list[dict]) -> list[dict]:
        return self._convert_tools(tools)

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Anthropic input_schema 格式 → OpenAI functions 格式。"""
        if not tools:
            return tools
        result = []
        for t in tools:
            name = t.get("name", "")
            desc = t.get("description", "")
            input_schema = t.get("input_schema", {})
            result.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": input_schema,
                },
            })
        return result

    # ── 响应格式转换：OpenAI → 内部格式 ──

    def _convert_response(
        self,
        content: str,
        tool_calls: list[dict],
        finish_reason: str,
        usage: dict | None,
    ) -> ProviderResponse:
        """OpenAI 流式响应字段 → ProviderResponse（Anthropic 内部风格）。"""
        content_blocks: list[dict] = []
        if content:
            content_blocks.append({"type": "text", "text": content})
        for tc in tool_calls:
            content_blocks.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc["arguments"],
            })

        # Stop reason 映射
        sr_map = {
            "stop": "end_turn",
            "length": "max_tokens",
            "tool_calls": "tool_use",
            "content_filter": "refusal",
        }
        stop_reason = sr_map.get(finish_reason, "end_turn")

        return ProviderResponse(
            content=content_blocks,
            stop_reason=stop_reason,
            usage=usage,
        )
