"""会话管理测试。"""

import json
import os
from pathlib import Path

import pytest

from session import (
    create_session, append_message, load_session, list_sessions,
    rename_session, export_session, cleanup_sessions, _project_dir,
    _serialize_content, _deserialize_content,
)


@pytest.fixture(autouse=True)
def session_dir(tmp_path, monkeypatch):
    """将会话目录重定向到 tmp_path。"""
    import session
    monkeypatch.setattr(session, "_SESSIONS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(session, "_BASE_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    yield


class TestCreateSession:
    def test_create_basic(self):
        sid = create_session()
        assert len(sid) == 16

    def test_create_named(self):
        sid = create_session(name="test-session")
        _, _, meta = load_session(sid)
        assert meta.get("name") == "test-session"

    def test_session_file_exists(self):
        sid = create_session()
        project = _project_dir()
        assert (project / f"{sid}.jsonl").exists()


class TestAppendMessage:
    def test_append_user(self):
        sid = create_session()
        append_message(sid, "user", "hello")
        messages, _, _ = load_session(sid)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "hello"

    def test_append_multiple(self):
        sid = create_session()
        append_message(sid, "user", "hello")
        append_message(sid, "assistant", "hi there")
        append_message(sid, "user", "how are you")
        messages, _, _ = load_session(sid)
        assert len(messages) == 3

    def test_append_with_content_blocks(self):
        sid = create_session()
        content = [
            {"type": "text", "text": "hello"},
        ]
        append_message(sid, "assistant", content)
        messages, _, _ = load_session(sid)
        assert len(messages) == 1
        assert messages[0]["content"][0]["type"] == "text"


class TestLoadSession:
    def test_load_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            load_session("nonexistent-id")

    def test_load_preserves_order(self):
        sid = create_session()
        for i in range(5):
            append_message(sid, "user", f"msg {i}")
        messages, _, _ = load_session(sid)
        assert len(messages) == 5
        for i, m in enumerate(messages):
            assert m["content"] == f"msg {i}"


class TestListSessions:
    def test_list_empty(self):
        sessions = list_sessions()
        assert sessions == []

    def test_list_multiple(self):
        sid1 = create_session(name="first")
        sid2 = create_session(name="second")
        sessions = list_sessions()
        assert len(sessions) == 2


class TestRenameSession:
    def test_rename(self):
        sid = create_session(name="old")
        rename_session(sid, "new")
        _, _, meta = load_session(sid)
        assert meta.get("name") == "new"


class TestExportSession:
    def test_export(self, tmp_path):
        sid = create_session()
        append_message(sid, "user", "hello world")
        path = export_session(sid, output_path=str(tmp_path / "export.txt"))
        assert os.path.exists(path)
        content = Path(path).read_text()
        assert "hello world" in content


class TestCleanup:
    def test_cleanup_old(self):
        # Create a session and manually make it old
        sid = create_session()
        project = _project_dir()
        jsonl = project / f"{sid}.jsonl"
        # Modify mtime to be 31 days ago
        import time
        old_time = time.time() - (31 * 86400)
        os.utime(jsonl, (old_time, old_time))
        count = cleanup_sessions(max_age_days=30)
        assert count == 1
        assert not jsonl.exists()

    def test_cleanup_recent_kept(self):
        sid = create_session()
        # 追加消息让会话有 first_message，避免被空会话清理逻辑误删
        append_message(sid, "user", "hello")
        count = cleanup_sessions(max_age_days=30)
        assert count == 0


class TestSerialization:
    def test_serialize_string(self):
        assert _serialize_content("hello") == "hello"

    def test_serialize_list(self):
        content = [{"type": "text", "text": "hi"}]
        assert _serialize_content(content) == [{"type": "text", "text": "hi"}]

    def test_deserialize_string(self):
        assert _deserialize_content("hello") == "hello"

    def test_deserialize_tool_use(self):
        content = [{"type": "tool_use", "id": "1", "name": "bash", "input": {"command": "ls"}}]
        result = _deserialize_content(content)
        assert result[0]["type"] == "tool_use"
        assert result[0]["name"] == "bash"
