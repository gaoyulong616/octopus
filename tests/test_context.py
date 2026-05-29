"""上下文管理测试。"""

import os
from pathlib import Path

import pytest

import context
from context import save_memory, clear_memory, _load_memory, _estimate_chars


@pytest.fixture(autouse=True)
def memory_file(tmp_path, monkeypatch):
    """重定向记忆文件到 tmp_path。"""
    mem = tmp_path / "memory.md"
    monkeypatch.setattr(context, "_MEMORY_FILE", str(mem))
    yield


class TestMemory:
    def test_save_and_load(self):
        save_memory("test note")
        mem = _load_memory()
        assert "test note" in mem

    def test_save_multiple(self):
        save_memory("note 1")
        save_memory("note 2")
        mem = _load_memory()
        assert "note 1" in mem
        assert "note 2" in mem

    def test_clear(self):
        save_memory("will be cleared")
        clear_memory()
        assert _load_memory() == ""


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
