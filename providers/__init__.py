"""Provider 工厂：根据配置动态创建 LLM Provider 实例。"""

from __future__ import annotations

import threading
from typing import Any

from config import get, get_model_provider as _get_model_provider

from .base import LLMProvider, ProviderAPIError, ProviderAuthError, ProviderError, ProviderRateLimitError


# ── Provider 实例按 name 缓存（多会话隔离） ──

_providers: dict[str, LLMProvider] = {}
_providers_lock = threading.Lock()


def get_provider(model: str | None = None, provider_name: str | None = None) -> LLMProvider:
    """获取或创建缓存的 Provider 实例（线程安全）。

    provider_name 显式指定时按 name 查找；否则按 model 从配置推断。
    不同 name 的 provider 分别缓存，避免多会话互相覆盖。
    """
    name = provider_name or _get_model_provider(model)

    with _providers_lock:
        if name not in _providers:
            _providers[name] = _create_provider(name)
        return _providers[name]


def _create_provider(name: str) -> LLMProvider:
    """根据名称创建 Provider 实例。

    查找顺序：
      1. 如果 providers.{name}.type == "openai"，创建 OpenAIProvider
      2. 默认创建 AnthropicProvider
    """
    providers_cfg = get("providers") or {}
    pcfg = providers_cfg.get(name, {})
    ptype = pcfg.get("type", "") if isinstance(pcfg, dict) else ""

    if ptype == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(name=name)
    from .anthropic_provider import AnthropicProvider
    return AnthropicProvider(name=name)


__all__ = [
    "LLMProvider",
    "ProviderError",
    "ProviderRateLimitError",
    "ProviderAPIError",
    "ProviderAuthError",
    "get_provider",
]
