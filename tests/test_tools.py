"""工具模块测试。"""

import os
import tempfile

import pytest

from tools import (
    _abs_path, _update_cwd, execute_tool, get_cwd, set_cwd,
    run_read_file, run_write_file, run_edit_file, run_list_files,
    run_grep_search, run_copy_file, run_move_file, run_delete_file,
)
from tools.exceptions import ToolError
from tools.state import get_state


@pytest.fixture(autouse=True)
def clean_cwd(tmp_path, monkeypatch):
    """每个测试用例前重置工作目录到 tmp_path。"""
    set_cwd(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    yield
    set_cwd(os.getcwd())


class TestCwdTracking:
    def test_initial_cwd(self, tmp_path):
        assert get_cwd() == str(tmp_path)

    def test_cd_absolute(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        _update_cwd(f"cd {sub}")
        assert get_cwd() == str(sub)

    def test_cd_relative(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        _update_cwd("cd sub")
        assert get_cwd() == str(sub)

    def test_cd_home(self):
        _update_cwd("cd ~")
        assert get_cwd() == os.path.expanduser("~")

    def test_cd_chained(self, tmp_path):
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        _update_cwd("cd a && cd b")
        assert get_cwd() == str(sub)

    def test_abs_path_relative(self, tmp_path):
        assert _abs_path("file.txt") == os.path.join(str(tmp_path), "file.txt")

    def test_abs_path_absolute(self):
        import os
        assert _abs_path("/tmp/file.txt") == os.path.realpath("/tmp/file.txt")


class TestReadFile:
    def test_read_normal(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = run_read_file("test.txt")
        assert result == "hello world"

    def test_read_not_found(self):
        with pytest.raises(ToolError):
            run_read_file("nonexistent.txt")

    def test_read_with_offset_limit(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
        result = run_read_file("lines.txt", offset=2, limit=2)
        assert "line2" in result
        assert "line3" in result
        assert "line1" not in result

    def test_read_offset_beyond_file(self, tmp_path):
        f = tmp_path / "short.txt"
        f.write_text("only one line\n", encoding="utf-8")
        with pytest.raises(ToolError):
            run_read_file("short.txt", offset=10, limit=5)


class TestWriteFile:
    def test_write_new(self, tmp_path):
        result = run_write_file("new.txt", "content")
        assert "已写入" in result
        assert (tmp_path / "new.txt").read_text() == "content"

    def test_write_creates_dirs(self, tmp_path):
        result = run_write_file("a/b/c.txt", "deep")
        assert "已写入" in result
        assert (tmp_path / "a" / "b" / "c.txt").read_text() == "deep"

    def test_write_append(self, tmp_path):
        f = tmp_path / "log.txt"
        f.write_text("line1\n", encoding="utf-8")
        run_write_file("log.txt", "line2\n", mode="a")
        assert f.read_text() == "line1\nline2\n"


class TestEditFile:
    def test_edit_simple(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world", encoding="utf-8")
        result = run_edit_file("edit.txt", "hello", "hi")
        assert "已编辑" in result
        assert f.read_text() == "hi world"

    def test_edit_not_found(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello", encoding="utf-8")
        with pytest.raises(ToolError):
            run_edit_file("edit.txt", "missing", "x")

    def test_edit_ambiguous(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("aaa bbb aaa", encoding="utf-8")
        with pytest.raises(ToolError):
            run_edit_file("edit.txt", "aaa", "x")

    def test_edit_replace_all(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("aaa bbb aaa", encoding="utf-8")
        result = run_edit_file("edit.txt", "aaa", "x", replace_all=True)
        assert "已编辑" in result
        assert f.read_text() == "x bbb x"


class TestListFiles:
    def test_list_dir(self, tmp_path):
        (tmp_path / "a.txt").write_text("")
        (tmp_path / "b.py").write_text("")
        result = run_list_files(".")
        assert "a.txt" in result
        assert "b.py" in result

    def test_list_pattern(self, tmp_path):
        (tmp_path / "a.txt").write_text("")
        (tmp_path / "b.py").write_text("")
        result = run_list_files(".", "*.py")
        assert "b.py" in result
        assert "a.txt" not in result

    def test_list_not_dir(self):
        with pytest.raises(ToolError):
            run_list_files("/nonexistent")


class TestGrepSearch:
    def test_grep_found(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello world\nfoo bar\n", encoding="utf-8")
        result = run_grep_search("hello")
        assert "a.txt" in result

    def test_grep_not_found(self, tmp_path):
        (tmp_path / "a.txt").write_text("nothing here\n", encoding="utf-8")
        result = run_grep_search("missing")
        assert "未找到" in result

    def test_grep_bad_regex(self):
        with pytest.raises(ToolError):
            run_grep_search("[invalid")


class TestFileOps:
    def test_copy(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("data", encoding="utf-8")
        result = run_copy_file("src.txt", "dst.txt")
        assert "已复制" in result
        assert (tmp_path / "dst.txt").read_text() == "data"

    def test_move(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("data", encoding="utf-8")
        result = run_move_file("src.txt", "dst.txt")
        assert "已移动" in result
        assert not src.exists()
        assert (tmp_path / "dst.txt").read_text() == "data"

    def test_delete(self, tmp_path):
        f = tmp_path / "del.txt"
        f.write_text("data", encoding="utf-8")
        result = run_delete_file("del.txt")
        assert "已删除" in result
        assert not f.exists()

    def test_delete_not_found(self):
        with pytest.raises(ToolError):
            run_delete_file("nonexistent.txt")

    def test_delete_dir(self, tmp_path):
        d = tmp_path / "dir"
        d.mkdir()
        with pytest.raises(ToolError):
            run_delete_file("dir")


class TestExecuteTool:
    def test_execute_write(self, tmp_path):
        result = execute_tool("write_file", {"path": "t.txt", "content": "hi"})
        assert "已写入" in result

    def test_execute_unknown(self):
        result = execute_tool("unknown_tool", {})
        assert "[错误]" in result


class TestTaskManagement:
    def setup_method(self):
        get_state().tasks.clear()
        get_state().next_task_id = 1

    def test_create_task(self):
        from tools import _task_create
        result = _task_create("Fix bug")
        import json
        data = json.loads(result)
        assert data["subject"] == "Fix bug"
        assert data["status"] == "pending"

    def test_update_task_status(self):
        from tools import _task_create, _task_update
        import json
        result = _task_create("Test task")
        tid = json.loads(result)["id"]
        result = _task_update(tid, status="in_progress")
        data = json.loads(result)
        assert data["status"] == "in_progress"

    def test_list_tasks(self):
        from tools import _task_create, _task_list
        _task_create("Task A")
        _task_create("Task B")
        result = _task_list()
        assert "Task A" in result
        assert "Task B" in result

    def test_task_dependencies(self):
        from tools import _task_create, _task_update, _task_get
        import json
        r1 = json.loads(_task_create("Parent task"))
        r2 = json.loads(_task_create("Child task"))
        tid1, tid2 = r1["id"], r2["id"]
        _task_update(tid2, addBlockedBy=[tid1])
        data = json.loads(_task_get(tid2))
        assert tid1 in data["blockedBy"]


class TestNotebookEdit:
    def test_create_and_edit(self, tmp_path):
        from tools import run_notebook_edit
        nb_path = tmp_path / "test.ipynb"
        nb = {
            "cells": [
                {"id": "cell_0", "cell_type": "code", "source": "print(1)",
                 "metadata": {}, "outputs": [], "execution_count": None},
            ],
            "metadata": {},
            "nbformat": 4, "nbformat_minor": 5,
        }
        import json
        nb_path.write_text(json.dumps(nb), encoding="utf-8")

        result = run_notebook_edit(str(nb_path), "print(2)", cell_id="cell_0")
        assert "已编辑" in result

        updated = json.loads(nb_path.read_text())
        assert updated["cells"][0]["source"] == "print(2)"
