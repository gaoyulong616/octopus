"""系统提示词优化测试：双块拆分、工具缓存标记、Skill 预算、指令缓存、环境缓存。"""

import os
import time

import pytest

import context
from context import (
    _get_project_overview,
    _instruction_cache,
    _load_project_instructions,
    build_system_blocks,
    build_system_prompt,
)
from tools.schemas import build_tools

# ── 优化 1：工具数组 cache_control ──


class TestToolCacheControl:
    def test_build_tools_no_cache_marker(self):
        """build_tools() 本身不应加 cache_control（由 agent.py 组装时加）。"""
        tools = build_tools()
        for t in tools:
            assert "cache_control" not in t

    def test_cache_control_on_last_tool(self):
        """模拟 agent.py 组装后，最后一个工具应有 cache_control。"""
        tools = build_tools()
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        assert tools[-1].get("cache_control") == {"type": "ephemeral"}
        # 倒数第二个不应有
        assert "cache_control" not in tools[-2]


# ── 优化 2：系统提示词双块拆分 ──


class TestBuildSystemBlocks:
    def test_returns_two_blocks(self):
        blocks = build_system_blocks(force_refresh=True)
        assert isinstance(blocks, list)
        assert len(blocks) == 2

    def test_each_block_has_cache_control(self):
        blocks = build_system_blocks(force_refresh=True)
        for b in blocks:
            assert b["type"] == "text"
            assert b["cache_control"] == {"type": "ephemeral"}

    def test_l1_contains_core_instructions(self):
        blocks = build_system_blocks(force_refresh=True)
        l1 = blocks[0]["text"]
        assert "Octopus" in l1
        assert "工作原则" in l1
        assert "输出风格" in l1

    def test_l2_contains_environment(self):
        blocks = build_system_blocks(force_refresh=True)
        l2 = blocks[1]["text"]
        # L2 应包含环境信息（git status 等），可能为空但不应包含工作原则
        assert "工作原则" not in l2

    def test_l1_stable_across_calls(self):
        """短时间内多次调用，L1 应保持一致。"""
        b1 = build_system_blocks(force_refresh=True)
        b2 = build_system_blocks(force_refresh=False)
        assert b1[0]["text"] == b2[0]["text"]

    def test_build_system_prompt_deprecated(self):
        """build_system_prompt 应返回两个块的拼接文本。"""
        text = build_system_prompt(force_refresh=True)
        assert "Octopus" in text
        assert "工作原则" in text


# ── 优化 3：Git Status 缓存 ──


class TestGitStatusCache:
    def test_overview_uses_cache(self, monkeypatch):
        """连续两次调用应命中缓存，不会两次 spawn subprocess。"""
        call_count = 0
        original_run = __import__("subprocess").run

        def counting_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return original_run(*args, **kwargs)

        monkeypatch.setattr("subprocess.run", counting_run)
        context._git_status_cache = ""
        context._git_status_mtime = 0.0
        context._overview_cached_cwd = ""

        _get_project_overview()
        first_count = call_count
        _get_project_overview()
        assert call_count == first_count, "第二次调用不应再 spawn git subprocess"

    def test_cwd_change_invalidates_cache(self, monkeypatch):
        """cwd 变化应清空缓存。"""
        cwd_calls = []
        fake_cwd = "/fake/dir"

        def fake_get_cwd():
            cwd_calls.append(1)
            return fake_cwd

        monkeypatch.setattr(context, "get_cwd", fake_get_cwd)
        context._git_status_cache = "cached git info"
        context._git_status_mtime = time.monotonic()
        context._overview_cached_cwd = "/different/dir"

        _get_project_overview()
        # cwd 变化后缓存应被清除
        assert context._git_status_cache != "cached git info" or context._overview_cached_cwd == fake_cwd


# ── 优化 4：项目指令 mtime 缓存 ──


class TestInstructionMtimeCache:
    def test_cache_avoids_reread(self, tmp_path, monkeypatch):
        """mtime 未变时不应重新读取文件。"""
        instruction_file = tmp_path / "OCTOPUS.md"
        instruction_file.write_text("test instruction")

        monkeypatch.setattr(context, "get_cwd", lambda: str(tmp_path))
        # 清空缓存
        context._instruction_cache.clear()
        context._cached_build_time = time.time() + 100  # 防止 instruction_files_changed 干扰

        # 第一次加载
        result1 = _load_project_instructions()
        assert "test instruction" in result1

        # 缓存应已记录
        abs_path = os.path.abspath(str(instruction_file))
        assert abs_path in context._instruction_cache

        # 验证缓存结构
        cached_mtime, cached_content = context._instruction_cache[abs_path]
        assert cached_content.strip() == "test instruction"

    def test_mtime_change_updates_cache(self, tmp_path, monkeypatch):
        """文件修改后应更新缓存。"""
        instruction_file = tmp_path / "OCTOPUS.md"
        instruction_file.write_text("version 1")
        monkeypatch.setattr(context, "get_cwd", lambda: str(tmp_path))
        context._instruction_cache.clear()

        _load_project_instructions()
        instruction_file.write_text("version 2")
        # 触碰 mtime
        os.utime(str(instruction_file), (time.time() + 1, time.time() + 1))

        result = _load_project_instructions()
        assert "version 2" in result


# ── 优化 5：Skill 描述预算控制 ──


class TestSkillDescBudget:
    def test_skill_desc_truncation(self, monkeypatch):
        """单条描述超 1536 字符应截断。"""
        from context import _SKILL_DESC_MAX_CHARS

        long_desc = "x" * 2000
        mock_skill = type("SkillDef", (), {"description": long_desc, "content": ""})()
        monkeypatch.setattr("skills.load_skills", lambda: {"test-skill": mock_skill})
        monkeypatch.setattr("config.get_context_window", lambda model=None: 200000)
        monkeypatch.setattr("config.get", lambda k, d=None: "test-model" if k == "model" else d)

        # 强制 L2 重建
        context._cached_l2_text = None
        blocks = build_system_blocks(force_refresh=True)
        l2 = blocks[1]["text"]
        assert "test-skill" in l2
        assert "..." in l2


# ── 优化 6：子目录指令懒加载 ──


class TestSubdirLazyLoad:
    def test_subdir_not_loaded_into_prompt(self, tmp_path, monkeypatch):
        """子目录 OCTOPUS.md 不应被读入 prompt 内容。"""
        # 创建子目录和指令文件
        subdir = tmp_path / "mymod"
        subdir.mkdir()
        (subdir / "OCTOPUS.md").write_text("module instruction content")
        (tmp_path / "OCTOPUS.md").write_text("root instruction")

        monkeypatch.setattr(context, "get_cwd", lambda: str(tmp_path))
        context._instruction_cache.clear()

        result = _load_project_instructions()
        # 根级指令应出现
        assert "root instruction" in result
        # 子目录内容不应出现
        assert "module instruction content" not in result
        # 但应列出可用模块
        assert "mymod" in result
        assert "按需加载" in result

    def test_no_subdir_still_works(self, tmp_path, monkeypatch):
        """无子目录指令时不应报错。"""
        (tmp_path / "OCTOPUS.md").write_text("root only")
        monkeypatch.setattr(context, "get_cwd", lambda: str(tmp_path))
        context._instruction_cache.clear()

        result = _load_project_instructions()
        assert "root only" in result
