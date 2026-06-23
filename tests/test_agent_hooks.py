"""Agent hooks 测试：验证关键 hook 触发点。

使用 mock SDK 不真实调用 LLM。
"""

from unittest.mock import MagicMock

import pytest

import agent
from providers.base import ProviderResponse


def _make_final_message():
    """构造一个 fake ProviderResponse。"""
    return ProviderResponse(
        content=[{"type": "text", "text": "done"}],
        stop_reason="end_turn",
        usage={"input_tokens": 10, "output_tokens": 5,
               "cache_creation_tokens": 0, "cache_read_tokens": 0},
    )


@pytest.fixture(autouse=True)
def stub_dependencies(monkeypatch):
    """避免 agent 真实创建 LLM Provider 和调用 tools。"""
    mock_provider = MagicMock()
    mock_provider._name = "anthropic"
    mock_provider.probe_server_tools.return_value = set()
    monkeypatch.setattr("providers.get_provider", lambda model=None, provider_name=None: mock_provider)
    monkeypatch.setattr(agent, "build_system_blocks",
                        lambda *a, **kw:
                        [{"type": "text", "text": "stub", "cache_control": {"type": "ephemeral"}}])
    monkeypatch.setattr(agent, "compress_messages",
                        lambda provider, msgs, model, force=False: msgs)
    # mock _stream_with_retry 直接返回 fake ProviderResponse
    final_msg = _make_final_message()
    monkeypatch.setattr(agent, "_stream_with_retry",
                        lambda *a, **kw: final_msg)
    # 跳过 metrics 写入
    import metrics as _metrics
    monkeypatch.setattr(_metrics, "record_call", lambda **kw: {})


class TestHookDispatch:
    def test_user_prompt_submit_hook_called(self, monkeypatch):
        captured = []
        monkeypatch.setattr(agent, "run_hooks",
                            lambda event, ctx=None: captured.append((event, ctx)) or [])
        agent.run_agent("hello", output_fn=lambda *a: None)
        assert any(e == "UserPromptSubmit" for e, _ in captured)

    def test_stop_hook_on_final_reply(self, monkeypatch):
        events_seen = []
        monkeypatch.setattr(agent, "run_hooks",
                            lambda event, ctx=None: events_seen.append(event) or [])
        agent.run_agent("hello", output_fn=lambda *a: None)
        assert "Stop" in events_seen

    def test_pretool_hook_with_legacy_alias(self, monkeypatch):
        """旧名 pre_tool_call 仍可通过 get_hooks 取到（兼容）。"""
        import config
        # 直接 patch get，返回带 hooks 的配置
        def fake_get(key, default=None):
            if key == "hooks":
                return {"pre_tool_call": ["echo legacy"]}
            return default
        monkeypatch.setattr(config, "get", fake_get)
        from config import get_hooks
        hooks = get_hooks("PreToolUse")
        assert "echo legacy" in hooks
        hooks_legacy = get_hooks("pre_tool_call")
        assert "echo legacy" in hooks_legacy


class TestMetricsIntegration:
    def test_metrics_recorded_on_call(self, monkeypatch):
        recorded = []

        def fake_record(**kw):
            recorded.append(kw)
            return {}

        import metrics as _metrics
        monkeypatch.setattr(_metrics, "record_call", fake_record)

        agent.run_agent("hello", output_fn=lambda *a: None,
                        session_id="test-session-abc")
        assert len(recorded) >= 1
        rec = recorded[0]
        assert rec["session_id"] == "test-session-abc"
        assert rec["input_tokens"] == 10
        assert rec["output_tokens"] == 5
