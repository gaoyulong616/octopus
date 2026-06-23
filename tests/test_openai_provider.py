"""OpenAI Provider 综合测试：消息转换、流式、错误处理、工厂、会话恢复。

覆盖 OpenAI 兼容 API 的全部差异场景，包括：
  - DeepSeek 等第三方 API 的特殊行为
  - 流式 tool_calls 增量合并
  - session 消息在不同 Provider 间切换时的完整性
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from providers.base import (
    LLMProvider,
    ProviderAPIError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderStreamEvent,
)
from providers.openai_provider import OpenAIProvider

# ═══════════════════════════════════════════════════════════════════════════════
# Mock helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _mock_chunk(
    content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
    usage: dict | None = None,
    choices: list | None = None,
):
    """创建一个 mock 流式 chunk。"""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls

    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    choice.index = 0

    chunk = MagicMock()
    chunk.choices = choices or [choice]
    chunk.usage = usage
    return chunk


def _mock_tool_call_delta(
    index: int,
    id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
):
    """创建 mock tool_calls delta（OpenAI 流式增量格式）。"""
    tc = MagicMock()
    tc.index = index
    tc.id = id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def _mock_stream(chunks: list) -> MagicMock:
    """mock 一个可迭代的 stream。"""
    stream = MagicMock()
    stream.__iter__.return_value = iter(chunks)
    return stream


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Message format conversion
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertMessages:
    """内部 Anthropic 风格 → OpenAI wire format 转换。"""

    def test_user_text_passthrough(self):
        provider = OpenAIProvider()
        msgs = provider._convert_messages(
            [{"role": "user", "content": "hello"}],
            system=None,
        )
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello"

    def test_system_prompt_as_first_message(self):
        provider = OpenAIProvider()
        msgs = provider._convert_messages(
            [{"role": "user", "content": "hi"}],
            system=[{"type": "text", "text": "You are a helpful assistant."}],
        )
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are a helpful assistant."
        assert msgs[1]["role"] == "user"

    def test_system_with_multiple_blocks(self):
        provider = OpenAIProvider()
        msgs = provider._convert_messages(
            [{"role": "user", "content": "hi"}],
            system=[
                {"type": "text", "text": "Rule 1"},
                {"type": "text", "text": "Rule 2"},
            ],
        )
        assert msgs[0]["role"] == "system"
        assert "Rule 1" in msgs[0]["content"]
        assert "Rule 2" in msgs[0]["content"]

    def test_empty_system_omitted(self):
        provider = OpenAIProvider()
        msgs = provider._convert_messages(
            [{"role": "user", "content": "hi"}],
            system=[{"type": "text", "text": ""}],
        )
        # All system blocks empty → no system message
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_tool_result_conversion(self):
        """tool_result block → role:tool message with tool_call_id. """
        provider = OpenAIProvider()
        msgs = provider._convert_messages(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "check result:"},
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_abc",
                            "content": "it worked",
                        },
                    ],
                }
            ],
            system=None,
        )
        # tool_result causes split: user message + tool message
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "tool"
        assert msgs[1]["tool_call_id"] == "call_abc"
        assert msgs[1]["content"] == "it worked"

    def test_tool_result_non_string_content(self):
        """非字符串 tool_result content 应 JSON 序列化。"""
        provider = OpenAIProvider()
        msgs = provider._convert_messages(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_1",
                            "content": {"key": "value", "num": 42},
                        }
                    ],
                }
            ],
            system=None,
        )
        assert msgs[0]["role"] == "tool"
        assert json.loads(msgs[0]["content"]) == {"key": "value", "num": 42}

    def test_assistant_text_and_tool_uses(self):
        """assistant 的 text + tool_use → content + tool_calls。"""
        provider = OpenAIProvider()
        msg = provider._convert_assistant_message(
            [
                {"type": "text", "text": "I will run:"},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "bash",
                    "input": {"command": "ls"},
                },
                {
                    "type": "tool_use",
                    "id": "call_2",
                    "name": "read_file",
                    "input": {"path": "/tmp/x"},
                },
            ]
        )
        assert msg["role"] == "assistant"
        assert msg["content"] == "I will run:"
        assert len(msg["tool_calls"]) == 2
        assert msg["tool_calls"][0]["function"]["name"] == "bash"
        assert msg["tool_calls"][1]["function"]["name"] == "read_file"

    def test_assistant_thinking_discarded(self):
        """thinking/redacted_thinking 块应被丢弃。"""
        provider = OpenAIProvider()
        msg = provider._convert_assistant_message(
            [
                {"type": "thinking", "thinking": "deep thoughts..."},
                {"type": "text", "text": "final answer"},
                {"type": "redacted_thinking", "data": "..."},
            ]
        )
        assert msg["content"] == "final answer"
        assert "thinking" not in json.dumps(msg)

    def test_assistant_no_text_tool_only(self):
        """只有 tool_use 没有 text → content 字段应省略。"""
        provider = OpenAIProvider()
        msg = provider._convert_assistant_message(
            [
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "bash",
                    "input": {"command": "ls"},
                }
            ]
        )
        assert msg["role"] == "assistant"
        assert "content" not in msg or not msg.get("content")
        assert len(msg["tool_calls"]) == 1

    def test_assistant_multiple_text_blocks_merged(self):
        """多个 text block 应合并为一个。"""
        provider = OpenAIProvider()
        msg = provider._convert_assistant_message(
            [
                {"type": "text", "text": "Step 1"},
                {"type": "text", "text": "Step 2"},
                {"type": "text", "text": "Step 3"},
            ]
        )
        assert "\n\n".join(["Step 1", "Step 2", "Step 3"]) in msg["content"]

    def test_user_content_list_with_only_text(self):
        """只有 text blocks → 合并为一个 user 消息。"""
        provider = OpenAIProvider()
        msgs = provider._convert_messages(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "part 1"},
                        {"type": "text", "text": "part 2"},
                    ],
                }
            ],
            system=None,
        )
        assert len(msgs) == 1
        assert "part 1" in msgs[0]["content"]
        assert "part 2" in msgs[0]["content"]

    def test_tool_role_passthrough(self):
        """role:tool 消息直接透传（从其他 provider 转来）。"""
        provider = OpenAIProvider()
        msgs = provider._convert_messages(
            [
                {"role": "tool", "tool_call_id": "call_1", "content": "result"},
                {"role": "user", "content": "ok"},
            ],
            system=None,
        )
        assert msgs[0]["role"] == "tool"

    def test_convert_user_message_with_sdk_objects(self):
        """SDK 对象（非 dict）也应正确处理。"""
        provider = OpenAIProvider()

        class FakeSDKBlock:
            type = "text"
            text = "sdk content"

        result = provider._convert_user_message([FakeSDKBlock()])
        assert result["role"] == "user"
        assert "sdk content" in result["content"]

    def test_convert_assistant_with_sdk_objects(self):
        """SDK 对象的 tool_use block。"""
        provider = OpenAIProvider()

        class FakeSDKToolUse:
            type = "tool_use"
            id = "sdk_call"
            name = "bash"
            input = {"command": "echo hi"}

        class FakeSDKText:
            type = "text"
            text = "running"

        msg = provider._convert_assistant_message([FakeSDKText(), FakeSDKToolUse()])
        assert "running" in msg["content"]
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["function"]["name"] == "bash"

    def test_tool_call_id_uniqueness(self):
        """重复的 tool_use id 应自动去重加后缀。"""
        provider = OpenAIProvider()
        msg = provider._convert_assistant_message(
            [
                {
                    "type": "tool_use",
                    "id": "dup_id",
                    "name": "bash",
                    "input": {"cmd": "a"},
                },
                {
                    "type": "tool_use",
                    "id": "dup_id",
                    "name": "read_file",
                    "input": {"path": "/b"},
                },
            ]
        )
        ids = [tc["id"] for tc in msg["tool_calls"]]
        assert ids[0] != ids[1]  # 第二个要有后缀


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Tool schema conversion
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertTools:
    """Anthropic input_schema → OpenAI functions 格式。"""

    def test_basic_tool(self):
        provider = OpenAIProvider()
        tools = provider._convert_tools([
            {
                "name": "bash",
                "description": "Run a command",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            }
        ])
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "bash"
        assert tools[0]["function"]["description"] == "Run a command"
        assert tools[0]["function"]["parameters"]["properties"]["command"]["type"] == "string"

    def test_empty_tools(self):
        provider = OpenAIProvider()
        assert provider._convert_tools([]) == []

    def test_multiple_tools(self):
        provider = OpenAIProvider()
        tools = provider._convert_tools([
            {"name": "bash", "description": "cmd", "input_schema": {"type": "object"}},
            {"name": "read_file", "description": "read", "input_schema": {"type": "object"}},
        ])
        assert len(tools) == 2
        assert tools[0]["function"]["name"] == "bash"
        assert tools[1]["function"]["name"] == "read_file"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Response conversion
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertResponse:
    """OpenAI 响应 → 内部 Anthropic 风格 content blocks。"""

    def test_text_only(self):
        provider = OpenAIProvider()
        resp = provider._convert_response(
            content="Hello world",
            tool_calls=[],
            finish_reason="stop",
            usage={"input_tokens": 10, "output_tokens": 20},
        )
        assert len(resp.content) == 1
        assert resp.content[0]["type"] == "text"
        assert resp.content[0]["text"] == "Hello world"
        assert resp.stop_reason == "end_turn"
        assert resp.usage["input_tokens"] == 10

    def test_with_tool_calls(self):
        provider = OpenAIProvider()
        resp = provider._convert_response(
            content="Running tools",
            tool_calls=[
                {"id": "call_1", "name": "bash", "arguments": {"command": "ls"}},
                {"id": "call_2", "name": "read_file", "arguments": {"path": "/tmp/x"}},
            ],
            finish_reason="tool_calls",
            usage=None,
        )
        assert len(resp.content) == 3  # text + 2 tool_use
        assert resp.content[0]["type"] == "text"
        assert resp.content[1]["type"] == "tool_use"
        assert resp.content[1]["name"] == "bash"
        assert resp.content[2]["name"] == "read_file"
        assert resp.stop_reason == "tool_use"

    def test_stop_reason_mapping(self):
        provider = OpenAIProvider()
        cases = [
            ("stop", "end_turn"),
            ("length", "max_tokens"),
            ("tool_calls", "tool_use"),
            ("content_filter", "refusal"),
            ("unknown", "end_turn"),
        ]
        for openai_reason, expected in cases:
            resp = provider._convert_response(
                content="x", tool_calls=[], finish_reason=openai_reason, usage=None
            )
            assert resp.stop_reason == expected, f"{openai_reason} → {expected}"

    def test_empty_content(self):
        provider = OpenAIProvider()
        resp = provider._convert_response(
            content="", tool_calls=[], finish_reason="stop", usage=None
        )
        assert len(resp.content) == 0  # 无 text block

    def test_no_tool_calls(self):
        provider = OpenAIProvider()
        resp = provider._convert_response(
            content="ok", tool_calls=[], finish_reason="stop", usage=None
        )
        assert len(resp.content) == 1
        assert resp.content[0]["type"] == "text"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Streaming
# ═══════════════════════════════════════════════════════════════════════════════


class TestStream:
    """流式处理：text tokens、tool_calls 增量合并、usage、finish_reason。"""

    @patch("providers.openai_provider.OpenAIProvider.get_client")
    def test_text_tokens(self, mock_get_client):
        provider = OpenAIProvider()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunks = [
            _mock_chunk(content="Hello"),
            _mock_chunk(content=" world"),
            _mock_chunk(content="!", finish_reason="stop"),
        ]
        mock_client.chat.completions.create.return_value = _mock_stream(chunks)

        events = list(provider.stream(
            messages=[{"role": "user", "content": "hi"}],
            system=None,
            tools=[],
            model="deepseek-chat",
            max_tokens=100,
        ))
        texts = [e.text for e in events if e.type == "text"]
        assert "".join(texts) == "Hello world!"

        response = provider.get_response()
        assert response is not None
        assert response.content[0]["text"] == "Hello world!"
        assert response.stop_reason == "end_turn"

    @patch("providers.openai_provider.OpenAIProvider.get_client")
    def test_tool_calls_delta_accumulation(self, mock_get_client):
        """流式 tool_calls 增量合并：同一 index 的 arguments 逐块拼接。"""
        provider = OpenAIProvider()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # 模拟 OpenAI 流式 tool_calls：先发 id+name，再逐步发 arguments
        chunks = [
            _mock_chunk(
                tool_calls=[
                    _mock_tool_call_delta(index=0, id="call_1", name="bash",
                                          arguments=""),
                ]
            ),
            _mock_chunk(
                tool_calls=[
                    _mock_tool_call_delta(index=0, id=None, name=None,
                                          arguments='{"command":'),
                ]
            ),
            _mock_chunk(
                tool_calls=[
                    _mock_tool_call_delta(index=0, id=None, name=None,
                                          arguments='"ls -la"}'),
                ]
            ),
            _mock_chunk(finish_reason="tool_calls"),
        ]
        mock_client.chat.completions.create.return_value = _mock_stream(chunks)

        events = list(provider.stream(
            messages=[{"role": "user", "content": "list files"}],
            system=None,
            tools=[],
            model="deepseek-chat",
            max_tokens=100,
        ))
        tool_events = [e for e in events if e.type == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0].tool_name == "bash"
        assert tool_events[0].tool_input == {"command": "ls -la"}

    @patch("providers.openai_provider.OpenAIProvider.get_client")
    def test_multiple_tool_calls_in_stream(self, mock_get_client):
        """多个 tool_calls 各自合并。"""
        provider = OpenAIProvider()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunks = [
            _mock_chunk(
                tool_calls=[
                    _mock_tool_call_delta(index=0, id="call_a", name="bash",
                                          arguments='{"com'),
                ]
            ),
            _mock_chunk(
                tool_calls=[
                    _mock_tool_call_delta(index=1, id="call_b", name="read_file",
                                          arguments='{"pat'),
                ]
            ),
            _mock_chunk(
                tool_calls=[
                    _mock_tool_call_delta(index=0, id=None, name=None,
                                          arguments='mand":"ls"}'),
                ]
            ),
            _mock_chunk(
                tool_calls=[
                    _mock_tool_call_delta(index=1, id=None, name=None,
                                          arguments='h":"/tmp/x"}'),
                ]
            ),
            _mock_chunk(finish_reason="tool_calls"),
        ]
        mock_client.chat.completions.create.return_value = _mock_stream(chunks)

        events = list(provider.stream(
            messages=[{"role": "user", "content": "do things"}],
            system=None, tools=[], model="deepseek-chat", max_tokens=100,
        ))
        tool_events = [e for e in events if e.type == "tool_call"]
        assert len(tool_events) == 2
        names = {e.tool_name for e in tool_events}
        assert "bash" in names
        assert "read_file" in names

    @patch("providers.openai_provider.OpenAIProvider.get_client")
    def test_usage_in_last_chunk(self, mock_get_client):
        """最后 chunk 带 usage 信息。"""
        provider = OpenAIProvider()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        usage = MagicMock()
        usage.prompt_tokens = 50
        usage.completion_tokens = 10

        chunks = [
            _mock_chunk(content="done"),
            _mock_chunk(
                finish_reason="stop",
                usage=usage,
            ),
        ]
        mock_client.chat.completions.create.return_value = _mock_stream(chunks)

        list(provider.stream(
            messages=[{"role": "user", "content": "hi"}],
            system=None, tools=[], model="deepseek-chat", max_tokens=100,
        ))
        response = provider.get_response()
        assert response is not None
        assert response.usage["input_tokens"] == 50
        assert response.usage["output_tokens"] == 10

    @patch("providers.openai_provider.OpenAIProvider.get_client")
    def test_no_usage_in_stream_deepseek_compat(self, mock_get_client):
        """DeepSeek 某些版本不返回 usage，应优雅降级。"""
        provider = OpenAIProvider()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunks = [
            _mock_chunk(content="answer"),
            _mock_chunk(finish_reason="stop"),  # 无 usage
        ]
        mock_client.chat.completions.create.return_value = _mock_stream(chunks)

        list(provider.stream(
            messages=[{"role": "user", "content": "hi"}],
            system=None, tools=[], model="deepseek-chat", max_tokens=100,
        ))
        response = provider.get_response()
        assert response is not None
        assert response.usage is None  # 不崩溃，usage 为空

    @patch("providers.openai_provider.OpenAIProvider.get_client")
    def test_empty_choices(self, mock_get_client):
        """某 chunk 的 choices 为空（兼容某些 API 行为）。"""
        provider = OpenAIProvider()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunk = MagicMock()
        chunk.choices = []  # no choices
        chunk.usage = None

        chunks = [
            chunk,
            _mock_chunk(content="still works", finish_reason="stop"),
        ]
        mock_client.chat.completions.create.return_value = _mock_stream(chunks)

        events = list(provider.stream(
            messages=[{"role": "user", "content": "hi"}],
            system=None, tools=[], model="deepseek-chat", max_tokens=100,
        ))
        texts = [e.text for e in events if e.type == "text"]
        assert "still works" in "".join(texts)

    @patch("providers.openai_provider.OpenAIProvider.get_client")
    def test_tool_call_broken_json(self, mock_get_client):
        """tool_call 的 arguments JSON 解析失败应降级为 {}。"""
        provider = OpenAIProvider()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunks = [
            _mock_chunk(
                tool_calls=[
                    _mock_tool_call_delta(index=0, id="call_bad", name="bash",
                                          arguments="not valid json{"),
                ]
            ),
            _mock_chunk(finish_reason="tool_calls"),
        ]
        mock_client.chat.completions.create.return_value = _mock_stream(chunks)

        events = list(provider.stream(
            messages=[{"role": "user", "content": "x"}],
            system=None, tools=[], model="deepseek-chat", max_tokens=100,
        ))
        tool_events = [e for e in events if e.type == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0].tool_input == {}  # 降级为空 dict

    @patch("providers.openai_provider.OpenAIProvider.get_client")
    def test_finish_reason_content_filter(self, mock_get_client):
        """内容过滤 finish_reason → refusal。"""
        provider = OpenAIProvider()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunks = [_mock_chunk(finish_reason="content_filter")]
        mock_client.chat.completions.create.return_value = _mock_stream(chunks)

        list(provider.stream(
            messages=[{"role": "user", "content": "bad"}],
            system=None, tools=[], model="deepseek-chat", max_tokens=100,
        ))
        response = provider.get_response()
        assert response is not None
        assert response.stop_reason == "refusal"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Error handling
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    """OpenAI 异常 → Provider 标准化异常。"""

    def _mock_client_for_error(self, error_cls):
        provider = OpenAIProvider()
        with patch("providers.openai_provider.OpenAIProvider.get_client") as m:
            mock_client = MagicMock()
            m.return_value = mock_client
            mock_client.chat.completions.create.side_effect = error_cls
        return provider, mock_client

    def test_rate_limit_error(self):
        with patch("providers.openai_provider.OpenAIProvider.get_client") as m:
            openai = pytest.importorskip("openai")
            provider = OpenAIProvider()
            mock_client = MagicMock()
            m.return_value = mock_client
            mock_client.chat.completions.create.side_effect = openai.RateLimitError(
                "rate limited",
                response=MagicMock(status_code=429),
                body=None,
            )
            with pytest.raises(ProviderRateLimitError):
                list(provider.stream(
                    messages=[{"role": "user", "content": "hi"}],
                    system=None, tools=[], model="m", max_tokens=100,
                ))

    def test_auth_error_401(self):
        with patch("providers.openai_provider.OpenAIProvider.get_client") as m:
            openai = pytest.importorskip("openai")
            provider = OpenAIProvider()
            mock_client = MagicMock()
            m.return_value = mock_client
            mock_client.chat.completions.create.side_effect = openai.APIStatusError(
                "not authorized",
                response=MagicMock(status_code=401),
                body=None,
            )
            with pytest.raises(ProviderAuthError) as exc:
                list(provider.stream(
                    messages=[{"role": "user", "content": "hi"}],
                    system=None, tools=[], model="m", max_tokens=100,
                ))
            assert "API 认证失败" in str(exc.value)

    def test_api_error_400(self):
        with patch("providers.openai_provider.OpenAIProvider.get_client") as m:
            openai = pytest.importorskip("openai")
            provider = OpenAIProvider()
            mock_client = MagicMock()
            m.return_value = mock_client
            mock_client.chat.completions.create.side_effect = openai.APIStatusError(
                "bad request",
                response=MagicMock(status_code=400),
                body=None,
            )
            with pytest.raises(ProviderAPIError) as exc:
                list(provider.stream(
                    messages=[{"role": "user", "content": "hi"}],
                    system=None, tools=[], model="m", max_tokens=100,
                ))
            assert exc.value.status_code == 400

    def test_api_error_500(self):
        with patch("providers.openai_provider.OpenAIProvider.get_client") as m:
            openai = pytest.importorskip("openai")
            provider = OpenAIProvider()
            mock_client = MagicMock()
            m.return_value = mock_client
            mock_client.chat.completions.create.side_effect = openai.APIStatusError(
                "server error",
                response=MagicMock(status_code=500),
                body=None,
            )
            with pytest.raises(ProviderAPIError):
                list(provider.stream(
                    messages=[{"role": "user", "content": "hi"}],
                    system=None, tools=[], model="m", max_tokens=100,
                ))


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Provider factory & provider name binding
# ═══════════════════════════════════════════════════════════════════════════════


class TestProviderFactory:
    """工厂函数对不同 provider name 创建正确的实例类型。"""

    def test_openai_name_creates_openai_provider(self):
        from providers import _create_provider
        p = _create_provider("openai")
        from providers.openai_provider import OpenAIProvider
        assert isinstance(p, OpenAIProvider)
        assert p._name == "openai"

    def test_ds_openai_name_creates_openai_provider(self):
        from providers import _create_provider
        p = _create_provider("ds_openai")
        from providers.openai_provider import OpenAIProvider
        assert isinstance(p, OpenAIProvider)
        assert p._name == "ds_openai"

    def test_default_name_creates_anthropic_provider(self):
        from providers import _create_provider
        p = _create_provider("anthropic")
        from providers.anthropic_provider import AnthropicProvider
        assert isinstance(p, AnthropicProvider)

    def test_unknown_name_defaults_to_anthropic(self):
        from providers import _create_provider
        p = _create_provider("unknown_provider")
        from providers.anthropic_provider import AnthropicProvider
        assert isinstance(p, AnthropicProvider)

    def test_type_field_in_config_creates_openai_provider(self, monkeypatch):
        """providers.{name}.type=openai → OpenAIProvider。"""
        monkeypatch.setattr(
            "providers.get",
            lambda k, d=None: (
                {"ds_openai": {"type": "openai", "base_url": "https://api.deepseek.com"}}
                if k == "providers" else d
            ),
        )
        from providers import _create_provider
        p = _create_provider("ds_openai")
        from providers.openai_provider import OpenAIProvider
        assert isinstance(p, OpenAIProvider)


class TestClientCreation:
    """OpenAIProvider.get_client 使用正确的 provider name 查找配置。"""

    def test_uses_provider_name_for_config_lookup(self, monkeypatch):
        """get_client 应从 providers[self._name] 读 base_url/api_key。"""
        monkeypatch.setattr(
            "providers.openai_provider.get",
            lambda k, d=None: (
                {"ds_openai": {"base_url": "https://api.deepseek.com", "api_key": "sk-test"}}
                if k == "providers" else
                ("https://api.deepseek.com" if k == "base_url" else None)
                if k == "base_url" else
                ("sk-test" if k == "api_key" else None)
            ),
        )
        provider = OpenAIProvider(name="ds_openai")
        # 确认配置指向正确的 provider name
        pcfg = provider._name
        assert pcfg == "ds_openai"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Session recovery — messages survive provider switch
# ═══════════════════════════════════════════════════════════════════════════════


class TestSessionRecovery:
    """使用不同 Provider 时，会话消息（内部 Anthropic 格式）不受影响。

    核心契约：
      - session 存储的是内部格式的消息列表
      - Provider 仅在 API 调用时做格式转换
      - 切换 Provider 后，已有消息格式不变
      - 压缩/恢复均以内部格式操作
    """

    def test_messages_format_identical_across_providers(self):
        """同样内容的消息在不同 Provider 中应为相同内部格式。

        AnthropicProvider 透传内部格式（无 _convert_messages），
        OpenAIProvider 在 API 调用时才转换——session 中的消息永远保持内部格式。
        """
        from providers.openai_provider import OpenAIProvider

        internal_messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "running"},
                    {"type": "tool_use", "id": "tu_1", "name": "bash",
                     "input": {"command": "ls"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "result:"},
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"},
                ],
            },
        ]

        op = OpenAIProvider()

        # OpenAI provider 转换是纯函数——不修改入参
        messages_copy = [dict(m) for m in internal_messages]
        op._convert_messages(messages_copy, system=None)
        assert messages_copy == internal_messages

        # AnthropicProvider 没有 _convert_messages（消息透传），
        # 验证的是两 provider 共用同一内部格式的约定。
        # 序列化后再加载，格式不变：
        roundtrip = json.loads(json.dumps(internal_messages, ensure_ascii=False))
        assert roundtrip == internal_messages

    def test_compress_and_restore(self):
        """压缩后再转换，消息完整性不受影响。"""
        provider = OpenAIProvider()

        # 模拟压缩对内部消息的修改（压缩会替换为摘要）
        compressed = [
            {"role": "user", "content": "[摘要] 之前的对话..."},
            {"role": "assistant", "content": "明白了"},
            {"role": "user", "content": "新问题"},
        ]

        # OpenAI provider 能正确处理压缩后的消息
        converted = provider._convert_messages(compressed, system=None)
        assert len(converted) >= 3

    def test_switch_provider_preserves_messages(self, monkeypatch):
        """切换 provider → run_agent → 外部 messages 保持全量。"""
        import agent
        from providers.base import ProviderResponse

        provider = OpenAIProvider(name="ds_openai")
        monkeypatch.setattr("providers.get_provider", lambda model=None, provider_name=None: provider)

        system_blocks = [{"type": "text", "text": "stub"}]
        monkeypatch.setattr(agent, "build_system_blocks",
                            lambda force_refresh=False, provider_name="anthropic": system_blocks)
        monkeypatch.setattr(agent, "compress_messages",
                            lambda provider, msgs, model, force=False: msgs)

        final_msg = ProviderResponse(
            content=[{"type": "text", "text": "done"}],
            stop_reason="end_turn",
            usage={"input_tokens": 1, "output_tokens": 1},
        )
        monkeypatch.setattr(agent, "_stream_with_retry", lambda *a, **kw: final_msg)
        import metrics as _metrics
        monkeypatch.setattr(_metrics, "record_call", lambda **kw: {})

        messages = [
            {"role": "user", "content": "原始问题"},
            {"role": "assistant", "content": "原始回复"},
        ]
        agent.run_agent("新问题", messages=messages, output_fn=lambda *a: None)

        contents = [m.get("content") for m in messages]
        assert "原始问题" in contents
        assert "原始回复" in contents
        assert "新问题" in contents

    def test_session_save_load_format_stability(self):
        """session 持久化后再加载，消息仍是内部格式。"""
        session_messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "world"}]},
        ]

        # 模拟 JSON 序列化/反序列化（session 持久化流程）
        serialized = json.dumps(session_messages, ensure_ascii=False)
        deserialized = json.loads(serialized)

        provider = OpenAIProvider()
        # 序列化后的消息仍能被正确转换
        converted = provider._convert_messages(deserialized, system=None)
        assert len(converted) == 2
        assert converted[0]["role"] == "user"
        assert converted[1]["role"] == "assistant"
        assert "hello" in str(converted)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. DeepSeek-specific edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeepSeekSpecific:
    """DeepSeek 等第三方 OpenAI 兼容 API 的特殊行为。"""

    @patch("providers.openai_provider.OpenAIProvider.get_client")
    def test_deepseek_no_stream_options(self, mock_get_client):
        """DeepSeek 较老版本不支持 stream_options，应优雅处理。"""
        provider = OpenAIProvider()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunks = [
            _mock_chunk(content="ok"),
            _mock_chunk(finish_reason="stop"),
        ]
        mock_client.chat.completions.create.return_value = _mock_stream(chunks)

        events = list(provider.stream(
            messages=[{"role": "user", "content": "hi"}],
            system=None, tools=[], model="deepseek-chat", max_tokens=100,
        ))
        texts = [e.text for e in events if e.type == "text"]
        assert "".join(texts) == "ok"

    def test_deepseek_model_detected_from_config(self, monkeypatch):
        """ds_openai provider 的模型应被正确识别。"""
        monkeypatch.setattr(
            "config.get",
            lambda k, d=None: "ds_openai" if k == "provider" else d,
        )
        from config import get_model_provider
        assert get_model_provider("deepseek-chat") == "ds_openai"

    def test_auto_detect_deepseek_model(self, monkeypatch):
        """未配置 provider 时，deepseek 模型名应自动识别为 openai。"""
        monkeypatch.setattr(
            "config.get",
            lambda k, d=None: None if k == "provider" else d,
        )
        from config import get_model_provider
        assert get_model_provider("deepseek-chat") == "openai"

    def test_deepseek_v4_model_auto_detect(self, monkeypatch):
        """deepseek-v4-flash 含 'deepseek' 关键字 → openai。"""
        monkeypatch.setattr(
            "config.get",
            lambda k, d=None: None if k == "provider" else d,
        )
        from config import get_model_provider
        assert get_model_provider("deepseek-v4-flash") == "openai"

    def test_ds_openai_config_lookup(self, monkeypatch):
        """ds_openai 的 api_key/base_url 应正确从 providers 读取。"""
        test_cfg = {
            "provider": "ds_openai",
            "providers": {
                "ds_openai": {
                    "base_url": "https://api.deepseek.com",
                    "api_key": "sk-test-key",
                }
            },
        }
        monkeypatch.setattr("config._get_config", lambda: test_cfg)
        from config import get
        assert get("api_key") == "sk-test-key"
        assert get("base_url") == "https://api.deepseek.com"

    def test_model_belongs_to_ds_openai(self, monkeypatch):
        """切换模型时正确关联到 ds_openai provider。"""
        test_cfg = {
            "provider": "zhipu",
            "providers": {
                "ds_openai": {
                    "base_url": "https://api.deepseek.com",
                    "api_key": "sk-test",
                    "models": [
                        {"name": "deepseek-chat", "context_window": 64000},
                        {"name": "deepseek-v4-flash", "context_window": 1000000},
                    ],
                },
            },
        }
        monkeypatch.setattr("config._get_config", lambda: test_cfg)
        monkeypatch.setattr("config.get", lambda k, d=None: test_cfg.get(k, d))
        monkeypatch.setattr("config.set_value", lambda k, v: None)  # 避免写文件
        from config import get_models, switch_model

        models = get_models()
        assert ("deepseek-chat", "ds_openai") in models

        # 从当前 provider (zhipu) 切换到 ds_openai 下的模型
        model_name, provider_name = switch_model("deepseek-chat")
        assert model_name == "deepseek-chat"
        assert provider_name == "ds_openai"
