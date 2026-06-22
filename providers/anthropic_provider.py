"""Anthropic SDK Provider：直连 Anthropic API，格式近乎透传。"""

from __future__ import annotations

import threading
from typing import Any, Generator

import anthropic
from anthropic.lib.streaming._messages import ParsedContentBlockStopEvent, TextEvent
from anthropic.lib.streaming._types import ThinkingEvent as _ThinkingEvent
from anthropic.types import (
    Message,
    ServerToolUseBlock,
    WebFetchToolResultBlock,
    WebSearchToolResultBlock,
)

from config import get
from logger import get_logger as _get_logger

from .base import (
    LLMProvider,
    ProviderAPIError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderStreamEvent,
)


# ── Client 单例复用 ──

_client: anthropic.Anthropic | None = None
_client_keys: tuple = ()
_client_lock = threading.Lock()


class AnthropicProvider(LLMProvider):
    """Anthropic 原生 API Provider。

    消息格式接近透传（内部已用 Anthropic 风格），
    保留 cache_control / thinking / server_tool_use 等 Anthropic-only 特性。
    """

    _name = "anthropic"
    _last_response: ProviderResponse | None = None

    def get_client(self) -> anthropic.Anthropic:
        global _client, _client_keys
        current_keys = (get("api_key"), get("base_url"), get("host"))
        with _client_lock:
            if _client is None or _client_keys != current_keys:
                default_headers = {"Host": current_keys[2]} if current_keys[2] else None
                _client = anthropic.Anthropic(
                    api_key=current_keys[0],
                    base_url=current_keys[1] or None,
                    default_headers=default_headers,
                )
                _client_keys = current_keys
        return _client

    # ── 服务端工具探测 ──

    _server_tools_cache: dict[tuple, set[str]] = {}

    def probe_server_tools(self, model: str) -> set[str]:
        cache_key = (get("base_url"), get("api_key"))
        if cache_key in self._server_tools_cache:
            return self._server_tools_cache[cache_key]

        supported: set[str] = set()
        probe_list = [
            ("web_search_20260209", "web_search"),
            ("web_fetch_20260209", "web_fetch"),
        ]
        client = self.get_client()
        for tool_type, tool_name in probe_list:
            try:
                client.messages.create(
                    model=model,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                    tools=[{"type": tool_type, "name": tool_name}],
                )
                supported.add(tool_name)
            except anthropic.BadRequestError:
                pass
            except Exception as e:
                _get_logger().warning("探测服务端工具 %s 失败: %s: %s", tool_name, type(e).__name__, e)

        self._server_tools_cache[cache_key] = supported
        return supported

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
        thinking_budget = kwargs.get("thinking_budget")
        self._last_response = None

        api_kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        if thinking_budget:
            api_kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

        try:
            with client.messages.stream(**api_kwargs) as stream:
                thinking_streamed = False
                for event in stream:
                    if isinstance(event, TextEvent):
                        yield ProviderStreamEvent(type="text", text=event.text)
                    elif isinstance(event, _ThinkingEvent):
                        thinking_streamed = True
                        yield ProviderStreamEvent(type="thinking", text=event.snapshot)
                    elif isinstance(event, ParsedContentBlockStopEvent):
                        block = event.content_block
                        if isinstance(block, ServerToolUseBlock):
                            yield ProviderStreamEvent(
                                type="server_tool_use",
                                tool_name=block.name,
                                tool_input=block.input,
                                tool_id=block.id,
                            )
                        elif isinstance(block, WebSearchToolResultBlock):
                            # web_search tool result 在流中直接发射，agent.py 有独立处理
                            yield ProviderStreamEvent(type="web_search_result", tool_name="web_search")
                        elif isinstance(block, WebFetchToolResultBlock):
                            yield ProviderStreamEvent(type="web_fetch_result", tool_name="web_fetch")

                # 流结束，获取最终消息
                final_message = stream.get_final_message()
                self._last_response = self._convert_response(final_message, thinking_streamed)
                _log.debug(
                    "Anthropic 响应: stop_reason=%s content_blocks=%d",
                    getattr(final_message, "stop_reason", None),
                    len(final_message.content) if final_message.content else 0,
                )

        except anthropic.RateLimitError as e:
            raise ProviderRateLimitError(str(e)) from e
        except anthropic.APIStatusError as e:
            if e.status_code == 401:
                raise ProviderAuthError(
                    "API 认证失败 (401)。请检查 API Key 是否正确配置。\n"
                    "  配置文件: ~/.octopus/config.json\n"
                    "  环境变量: OCTOPUS_API_KEY"
                ) from e
            raise ProviderAPIError(str(e), status_code=e.status_code) from e

    def get_response(self) -> ProviderResponse | None:
        return self._last_response

    # ── 非流式总结（用于上下文压缩） ──

    def summarize(self, prompt: str, model: str, max_tokens: int = 1024) -> str:
        client = self.get_client()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.content and len(response.content) > 0:
            return response.content[0].text
        return ""

    # ── 格式转换（Anthropic 格式 ≈ 内部格式，近乎透传） ──

    def _convert_response(self, msg: Message, thinking_streamed: bool) -> ProviderResponse:
        """将 Anthropic Message 对象转为内部格式。"""
        content: list[dict] = []
        for block in msg.content or []:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            elif block.type == "thinking":
                content.append({
                    "type": "thinking",
                    "thinking": block.thinking,
                    "signature": getattr(block, "signature", ""),
                })
            elif block.type == "redacted_thinking":
                content.append({
                    "type": "redacted_thinking",
                    "data": getattr(block, "data", ""),
                })
            elif block.type == "server_tool_use":
                content.append({
                    "type": "server_tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            elif block.type == "web_search_tool_result":
                content.append({"type": "web_search_tool_result"})
            elif block.type == "web_fetch_tool_result":
                content.append({"type": "web_fetch_tool_result"})
            else:
                content.append({"type": block.type})

        stop_reason = getattr(msg, "stop_reason", None) or "end_turn"
        usage = getattr(msg, "usage", None)
        usage_dict = None
        if usage:
            usage_dict = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            }
            cc = getattr(usage, "cache_creation_input_tokens", 0) or 0
            cr = getattr(usage, "cache_read_input_tokens", 0) or 0
            if cc or cr:
                usage_dict["cache_creation_tokens"] = cc
                usage_dict["cache_read_tokens"] = cr

        return ProviderResponse(
            content=content,
            stop_reason=stop_reason,
            usage=usage_dict,
            thinking_streamed=thinking_streamed,
        )
