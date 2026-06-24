"""验证外部 messages 始终保持全量，仅 llm_messages 被压缩。

核心契约：无论压缩是否触发，传入 run_agent 的 messages 列表只追加新内容，
早期消息永不被覆盖。session/UI 据此保存和恢复完整历史。
"""

from unittest.mock import MagicMock

import pytest

import agent
import context
from providers.base import ProviderResponse


def _make_final_message(text: str = "done", with_tool: bool = False):
    """构造 fake ProviderResponse（含 text block，可选 tool_use block）。"""
    blocks = [{"type": "text", "text": text}]
    if with_tool:
        blocks.append({"type": "tool_use", "id": "tool_1", "name": "bash",
                        "input": {"command": "echo hi"}})
    return ProviderResponse(
        content=blocks,
        stop_reason="end_turn",
        usage={"input_tokens": 10, "output_tokens": 5,
               "cache_creation_tokens": 0, "cache_read_tokens": 0},
    )


@pytest.fixture(autouse=True)
def stub_dependencies(monkeypatch):
    """避免 agent 真实调用 LLM/tools/metrics。"""
    mock_provider = MagicMock()
    mock_provider._name = "anthropic"
    mock_provider.probe_server_tools.return_value = set()
    monkeypatch.setattr("providers.get_provider", lambda model=None, provider_name=None: mock_provider)
    monkeypatch.setattr(agent, "build_system_blocks",
                        lambda *a, **kw:
                        [{"type": "text", "text": "stub"}])
    # 默认 compress 不动 messages（让 LLM 视图 == 全量）
    monkeypatch.setattr(agent, "compress_messages",
                        lambda provider, msgs, model, force=False: msgs)
    final_msg = _make_final_message()
    monkeypatch.setattr(agent, "_stream_with_retry",
                        lambda *a, **kw: (final_msg, set()))
    import metrics as _metrics
    monkeypatch.setattr(_metrics, "record_call", lambda **kw: {})


class TestFullHistoryPreserved:
    """run_agent 后外部 messages 必须保留所有原始消息。"""

    def test_external_messages_not_overwritten_when_compress_triggered(self, monkeypatch):
        """compress_messages 返回压缩版，外部 messages 仍保留全量。"""
        # 构造模拟压缩：把入参的前 N 条替换为 [摘要]
        def fake_compress(client, msgs, model, force=False):
            if len(msgs) <= 4:
                return msgs
            return [
                {"role": "user", "content": "[上下文摘要] ..."},
                {"role": "assistant", "content": "收到"},
            ] + msgs[-2:]

        monkeypatch.setattr(agent, "compress_messages", fake_compress)

        messages = [
            {"role": "user", "content": "原始问题1"},
            {"role": "assistant", "content": "原始回复1"},
            {"role": "user", "content": "原始问题2"},
            {"role": "assistant", "content": "原始回复2"},
        ]
        agent.run_agent("新问题", messages=messages, output_fn=lambda *a: None)

        # 外部 messages 应保留全部原始内容 + 新追加的 user + assistant
        contents = [m.get("content") for m in messages]
        assert "原始问题1" in contents
        assert "原始回复1" in contents
        assert "原始问题2" in contents
        assert "原始回复2" in contents
        assert "新问题" in contents

    def test_llm_view_isolated_from_external_messages(self, monkeypatch):
        """压缩后的 LLM 视图不影响外部 messages 引用。"""
        compress_calls = []

        def fake_compress(client, msgs, model, force=False):
            compress_calls.append(list(msgs))  # 记录入参快照
            return msgs

        monkeypatch.setattr(agent, "compress_messages", fake_compress)

        messages = []
        agent.run_agent("hello", messages=messages, output_fn=lambda *a: None)

        # compress 至少调用一次，入参就是 llm_messages
        assert len(compress_calls) >= 1
        # 外部 messages 应该 = user + assistant
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"


class TestCompressIsPure:
    """compress_messages 必须是纯函数：不修改入参 list 及其中 dict。"""

    def test_compress_does_not_mutate_input_list(self, monkeypatch):
        """force=True 触发压缩，入参 list 长度和元素应保持不变。"""
        # 让阈值很小，强制触发压缩路径
        monkeypatch.setattr(context, "get", lambda key, default=None: 100 if key == "context_threshold" else default)

        # mock provider.summarize 返回摘要
        provider = MagicMock()
        provider.summarize.return_value = "摘要内容"

        messages = []
        for i in range(10):
            messages.append({"role": "user", "content": f"问题{i}" * 50})
            messages.append({"role": "assistant", "content": f"回答{i}" * 50})

        original_snapshot = [dict(m) for m in messages]
        original_len = len(messages)

        result = context.compress_messages(provider, messages, "test-model", force=True)

        # 入参 list 和 dict 不应被修改
        assert len(messages) == original_len
        for orig, now in zip(original_snapshot, messages):
            assert orig == now

        # 返回的是新 list（结果长度可变）
        assert result is not messages or len(result) != original_len


class TestSegmentedCompress:
    """_segmented_compress 的分段行为。"""

    def test_single_segment_when_small(self):
        """消息总字符少 → 1 段，1 次调用，1 个摘要。"""
        provider = MagicMock()
        provider.summarize.return_value = "段摘要"

        messages = [
            {"role": "user", "content": "短消息1"},
            {"role": "assistant", "content": "短回复1"},
        ]
        result = context._segmented_compress(provider, messages, "test-model")
        assert len(result) == 1
        assert "段摘要" in result[0]
        assert provider.summarize.call_count == 1

    def test_multiple_segments_when_large(self, monkeypatch):
        """段数 > MERGE_THRESHOLD 时触发二次合并。"""
        # 让 context_window 很小，触发多段（保底 8000 chars 仍是单段上限）
        monkeypatch.setattr(context, "get_context_window", lambda model: 1000)

        provider = MagicMock()
        call_idx = {"i": 0}
        summaries = ["段1摘要", "段2摘要", "段3摘要", "段4摘要"]

        def fake_summarize(prompt, model, max_tokens=1024):
            idx = call_idx["i"] % len(summaries)
            call_idx["i"] += 1
            return summaries[idx]

        provider.summarize.side_effect = fake_summarize

        # 4 条消息，每条 > 单段上限 8000，每条单独成段 → 4 段
        messages = [{"role": "user", "content": "x" * 8001} for _ in range(4)]
        result = context._segmented_compress(provider, messages, "test-model")

        # 4 段压缩 + 1 次合并 = 5 次调用
        assert provider.summarize.call_count == 5
        # 合并后返回 1 个摘要
        assert len(result) == 1

    def test_returns_empty_when_all_llm_calls_fail(self):
        """所有 LLM 调用失败 → 返回空列表（调用方降级）。"""
        provider = MagicMock()
        provider.summarize.side_effect = RuntimeError("network down")

        messages = [{"role": "user", "content": "x" * 100}]
        result = context._segmented_compress(provider, messages, "test-model")
        assert result == []


class TestForceCompact:
    """force_compact 参数：让首次迭代强制压缩 LLM 视图，外部 messages 不受影响。"""

    def test_force_compact_first_iteration_only(self, monkeypatch):
        """force_compact=True → 第一次 compress 调用 force=True，后续迭代 force=False。"""
        compress_calls: list[tuple[int, bool]] = []

        def fake_compress(client, msgs, model, force=False):
            compress_calls.append((len(msgs), force))
            return msgs  # 不实际压缩，让循环结束

        monkeypatch.setattr(agent, "compress_messages", fake_compress)

        agent.run_agent("hello", messages=[], output_fn=lambda *a: None,
                        force_compact=True)

        assert len(compress_calls) >= 1
        # 第一次必须 force=True
        assert compress_calls[0][1] is True

    def test_force_compact_preserves_external_messages(self, monkeypatch):
        """force_compact=True 时 compress 返回压缩版，外部 messages 仍保留全量。"""
        def fake_compress(client, msgs, model, force=False):
            if force and len(msgs) > 4:
                return [{"role": "user", "content": "[摘要]"}] + msgs[-2:]
            return msgs

        monkeypatch.setattr(agent, "compress_messages", fake_compress)

        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        agent.run_agent("q3", messages=messages, output_fn=lambda *a: None,
                        force_compact=True)

        contents = [m.get("content") for m in messages]
        for original in ("q1", "a1", "q2", "a2", "q3"):
            assert original in contents


class TestCompactCommandPreservesHistory:
    """/compact 命令不应直接覆盖 messages。"""

    def test_cmd_compact_sets_state_flag_not_mutates_messages(self):
        import commands

        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        state: dict = {}
        result = commands.cmd_compact("/compact", messages, state)

        # messages 完全不变
        assert len(messages) == 4
        assert messages[0]["content"] == "q1"
        # state 标记下次 force_compact
        assert state.get("_force_compact_next") is True
        # 命令有回复
        assert result.text
