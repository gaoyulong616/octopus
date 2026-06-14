"""上下文管理测试（覆盖类型化 memory 系统）。"""

import os
from pathlib import Path

import pytest

import context
from context import (save_memory, clear_memory, delete_memory, list_memories,
                     _load_memory, _estimate_chars, _scan_memory_dir,
                     _MEMORY_DIR)


@pytest.fixture(autouse=True)
def memory_dir(tmp_path, monkeypatch):
    """重定向 memory 目录到 tmp_path。"""
    base = tmp_path / "memory"
    monkeypatch.setattr(context, "_MEMORY_DIR", str(base))
    monkeypatch.setattr(context, "_MEMORY_INDEX", str(base / "MEMORY.md"))
    yield


class TestMemory:
    def test_save_default_user_type(self):
        msg = save_memory("test note")
        assert "user" in msg
        entries = list_memories()
        assert len(entries) == 1
        assert entries[0].get("type") == "user"

    def test_save_with_explicit_type(self):
        save_memory("don't summarize", mtype="feedback")
        entries = list_memories()
        assert entries[0].get("type") == "feedback"

    def test_save_with_name_and_description(self):
        save_memory("details", mtype="project", name="auth-refactor",
                    description="重构 auth 中间件")
        entries = list_memories()
        assert entries[0].get("name") == "auth-refactor"
        assert "auth" in entries[0].get("description", "")

    def test_load_renders_index(self):
        save_memory("like terse output", mtype="feedback", name="terse")
        text = _load_memory()
        assert "terse" in text
        assert "feedback" in text.lower() or "反馈" in text

    def test_save_multiple_creates_distinct_files(self):
        save_memory("note 1", name="foo")
        save_memory("note 2", name="foo")  # 同名应自增
        entries = list_memories()
        assert len(entries) == 2

    def test_delete_by_name(self):
        save_memory("xxx", name="will-delete")
        msg = delete_memory("will-delete")
        assert "1" in msg
        assert list_memories() == []

    def test_clear(self):
        save_memory("a")
        save_memory("b", mtype="feedback")
        clear_memory()
        assert _load_memory() == ""

    def test_invalid_type_falls_back_to_user(self):
        save_memory("zzz", mtype="bogus")
        entries = list_memories()
        assert entries[0].get("type") == "user"


class TestEstimateChars:
    def test_string_content(self):
        messages = [{"role": "user", "content": "hello"}]
        assert _estimate_chars(messages) == 5

    def test_list_content(self):
        messages = [{"role": "assistant", "content": [
            {"type": "text", "text": "hi"},
        ]}]
        assert _estimate_chars(messages) > 0

    def test_empty_messages(self):
        assert _estimate_chars([]) == 0


class TestStripOrphanToolResults:
    """回归测试：_strip_orphan_tool_results 防止压缩后产生孤儿 tool_result。"""

    def test_keeps_matched_pairs(self):
        from context import _strip_orphan_tool_results

        messages = [
            {"role": "assistant", "content": [{"type": "tool_use", "id": "X", "name": "bash", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "X", "content": "ok"}]},
        ]
        result = _strip_orphan_tool_results(messages)
        assert len(result) == 2
        assert len(result[1]["content"]) == 1  # tool_result 保留

    def test_strips_orphan_tool_result(self):
        """压缩后 user 首条引用不存在的 tool_use_id 应被移除。"""
        from context import _strip_orphan_tool_results

        messages = [
            {"role": "user", "content": "[上下文摘要] ..."},
            {"role": "assistant", "content": "收到"},
            # 这条 user 引用了不存在的 tool_use_id（被压缩掉了）
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "MISSING", "content": "ok"}]},
        ]
        result = _strip_orphan_tool_results(messages)
        # 第三条 user 的 tool_result 被剥离，content 为空 → 整条消息被丢弃
        assert len(result) == 2

    def test_preserves_text_blocks(self):
        """非 tool_use/tool_result 的 block 不受影响。"""
        from context import _strip_orphan_tool_results

        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
        ]
        result = _strip_orphan_tool_results(messages)
        assert result == messages

    def test_string_content_passthrough(self):
        """字符串 content 直接保留。"""
        from context import _strip_orphan_tool_results

        messages = [
            {"role": "user", "content": "plain string"},
        ]
        result = _strip_orphan_tool_results(messages)
        assert result == messages

