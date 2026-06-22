"""Provider 工厂：根据配置动态创建 LLM Provider 实例。"""

from __future__ import annotations

import threading
from typing import Any

from config import get, get_model_provider as _get_model_provider

from .base import LLMProvider, ProviderAPIError, ProviderAuthError, ProviderError, ProviderRateLimitError


# ── Provider 实例缓存 ──

_provider: LLMProvider | None = None
_provider_name: str = ""
_provider_lock = threading.Lock()


def get_provider(model: str | None = None) -> LLMProvider:
    """获取或创建缓存的 Provider 实例（线程安全）。

    首次调用或 provider 配置变化时创建新实例。
    """
    global _provider, _provider_name

    name = _get_model_provider(model)

    with _provider_lock:
        if _provider is None or _provider_name != name:
            _provider = _create_provider(name)
            _provider_name = name
    return _provider


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
    return AnthropicProvider()


__all__ = [
    "LLMProvider",
    "ProviderError",
    "ProviderRateLimitError",
    "ProviderAPIError",
    "ProviderAuthError",
    "get_provider",
]
