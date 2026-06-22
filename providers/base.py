"""Provider 抽象层：定义 LLM 提供商的标准接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generator


# ── 标准化流式事件 ──


@dataclass
class ProviderStreamEvent:
    """Provider 流式输出的标准化事件。

    type 取值：
      "text"             → 文本 token（增量）
      "thinking"         → thinking token（增量，Anthropic-only）
      "tool_call"        → 完整 tool_use block（完整到达时发射）
      "tool_call_delta"  → OpenAI tool_calls 增量（需按 index 合并）
      "server_tool_use"  → 服务端工具调用（web_search/web_fetch）
      "done"             → 流结束（携带 finish_reason）
    """
    type: str
    text: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_id: str = ""
    tool_index: int = 0  # OpenAI 增量合并用


# ── 标准化 Provider 响应 ──


@dataclass
class ProviderResponse:
    """Provider 完成后的完整响应，已转换为 Anthropic 内部格式。"""
    content: list[dict]  # Anthropic 风格 content blocks: {"type": "text"/"tool_use"/"thinking"/...}
    stop_reason: str     # 统一为: end_turn | max_tokens | tool_use | refusal
    usage: dict | None   # {"input_tokens": N, "output_tokens": N, ...}
    thinking_streamed: bool = False


# ── 统一异常 ──


class ProviderError(Exception):
    """Provider 错误的基类。"""


class ProviderRateLimitError(ProviderError):
    """Rate limit 触发（可重试）。"""


class ProviderAPIError(ProviderError):
    """API 返回错误状态码。"""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class ProviderAuthError(ProviderError):
    """认证失败（401），不可重试。"""


# ── 抽象基类 ──


class LLMProvider(ABC):
    """LLM 提供商的抽象基类。

    职责：
    1. Client 创建/缓存（get_client）
    2. 服务端工具探测（probe_server_tools）
    3. 流式请求 + 事件标准化（stream）
    4. Tool schema / 消息格式转换

    内部格式保持 Anthropic 风格 content blocks，Provider 只在 API 边界转换。
    """

    _name: str = ""

    @abstractmethod
    def get_client(self) -> Any:
        """获取或创建缓存的 API client。"""
        ...

    @abstractmethod
    def probe_server_tools(self, model: str) -> set[str]:
        """探测 API 提供商支持哪些服务端工具。返回工具名集合。"""
        ...

    @abstractmethod
    def stream(
        self,
        messages: list[dict],
        system: list[dict] | None,
        tools: list[dict],
        model: str,
        max_tokens: int,
        **kwargs,
    ) -> Generator[ProviderStreamEvent, None, None]:
        """发起流式 API 调用。

        系统提示词通过 system 参数传入（Anthropic 风格），
        Provider 内部按需转换为目标格式。

        Yields:
            ProviderStreamEvent: 标准化事件，供 agent.py 处理。

        迭代完成后调用 get_response() 获取最终结果。
        """
        ...

    @abstractmethod
    def get_response(self) -> ProviderResponse | None:
        """获取最近一次 stream() 调用的完整响应。"""
        ...

    @abstractmethod
    def summarize(self, prompt: str, model: str, max_tokens: int = 1024) -> str:
        """非流式总结调用，用于上下文压缩。

        发送 prompt 到 LLM 并返回文本结果（不涉及工具调用）。
        """
        ...

    def convert_tools(self, tools: list[dict]) -> list[dict]:
        """将 Anthropic 格式工具 schema 转为 Provider 格式。

        输入: [{"name": "bash", "description": "...", "input_schema": {...}}, ...]
        输出: Provider 特定格式（默认透传）
        """
        return tools
