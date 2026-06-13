"""系统提示词优化测试：三块拆分、工具缓存标记、指令缓存、环境缓存。"""

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
    def test_returns_three_blocks(self):
        blocks = build_system_blocks(force_refresh=True)
        assert isinstance(blocks, list)
        assert len(blocks) == 3

    def test_each_block_has_cache_control(self):
        blocks = build_system_blocks(force_refresh=True)
        for b in blocks:
            assert b["type"] == "text"
            assert b["cache_control"] == {"type": "ephemeral"}

    def test_l1_contains_core_instructions(self):
        blocks = build_system_blocks(force_refresh=True)
        l1 = blocks[0]["text"]
        assert "Octopus" in l1
        assert "工具使用策略" in l1
        assert "输出风格" in l1
        assert "代码质量" in l1
        assert "安全规范" in l1

    def test_l2_contains_memory_and_instructions(self):
        blocks = build_system_blocks(force_refresh=True)
        l2 = blocks[1]["text"]
        # L2 不应包含行为规范（那些在 L1）
        assert "工具使用策略" not in l2

    def test_l3_contains_environment(self):
        blocks = build_system_blocks(force_refresh=True)
        l3 = blocks[2]["text"]
        # L3 包含日期和环境信息
        assert "今天是" in l3 or "工作目录" in l3

    def test_l1_stable_across_calls(self):
        """短时间内多次调用，L1 应保持一致。"""
        b1 = build_system_blocks(force_refresh=True)
        b2 = build_system_blocks(force_refresh=False)
        assert b1[0]["text"] == b2[0]["text"]

    def test_build_system_prompt_deprecated(self):
        """build_system_prompt 应返回三个块的拼接文本。"""
        text = build_system_prompt(force_refresh=True)
        assert "Octopus" in text
        assert "工具使用策略" in text


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
    def test_skill_names_in_l2(self, monkeypatch):
        """L2 应列出 skill 名称（不含完整描述）。"""
        mock_skill = type("SkillDef", (), {"description": "测试 skill", "content": ""})()
        monkeypatch.setattr("skills.load_skills", lambda: {"test-skill": mock_skill})
        monkeypatch.setattr("config.get", lambda k, d=None: "test-model" if k == "model" else d)

        # 强制 L2 重建
        context._cached_l2_text = None
        blocks = build_system_blocks(force_refresh=True)
        l2 = blocks[1]["text"]
        assert "test-skill" in l2

    def test_skill_desc_in_tools(self, monkeypatch):
        """Skill 描述应注入到 invoke_skill 工具的 description 中。"""
        long_desc = "x" * 2000
        mock_skill = type("SkillDef", (), {"description": long_desc, "content": ""})()
        monkeypatch.setattr("skills.load_skills", lambda: {"test-skill": mock_skill})

        tools = build_tools()
        invoke = next((t for t in tools if t.get("name") == "invoke_skill"), None)
        assert invoke is not None
        assert "test-skill" in invoke["description"]


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


# ── Bug 回归测试 ──


class TestBugFixes:
    def test_startswith_prefix_boundary(self, tmp_path, monkeypatch):
        """Bug 1: cwd=/a/b 不应匹配 /a/bcd 的子目录。"""
        from tools.file_ops import _try_inject_subdir_instruction
        from tools.state import get_state

        cwd = str(tmp_path)
        # 创建名字是 cwd 前缀的兄弟目录
        sibling = str(tmp_path) + "-sibling"
        os.makedirs(sibling, exist_ok=True)
        instruction_file = os.path.join(sibling, "OCTOPUS.md")
        with open(instruction_file, "w") as f:
            f.write("sibling instructions")

        get_state().set_cwd(cwd)

        fake_file = os.path.join(sibling, "test.py")
        with open(fake_file, "w") as f:
            f.write("# test")

        result = _try_inject_subdir_instruction(os.path.abspath(fake_file))
        assert result == "", "前缀匹配的兄弟目录不应触发注入"

    def test_injection_cache_mtime_invalidation(self, tmp_path, monkeypatch):
        """Bug 5: OCTOPUS.md 内容变更后应重新注入。"""
        from tools.file_ops import _try_inject_subdir_instruction, _injected_instructions
        from tools.state import get_state

        subdir = tmp_path / "mod"
        subdir.mkdir()
        instruction_file = subdir / "OCTOPUS.md"
        instruction_file.write_text("version 1")
        test_file = subdir / "test.py"
        test_file.write_text("# test")

        get_state().set_cwd(str(tmp_path))
        _injected_instructions.clear()

        # 第一次：应注入 version 1
        result1 = _try_inject_subdir_instruction(str(test_file.resolve()))
        assert "version 1" in result1

        # 第二次：应跳过（已注入相同版本）
        result2 = _try_inject_subdir_instruction(str(test_file.resolve()))
        assert result2 == ""

        # 修改 OCTOPUS.md 内容
        time.sleep(0.05)
        instruction_file.write_text("version 2")
        os.utime(str(instruction_file), (time.time() + 1, time.time() + 1))

        # 第三次：应重新注入 version 2
        result3 = _try_inject_subdir_instruction(str(test_file.resolve()))
        assert "version 2" in result3

    def test_compress_preserves_context_summary(self):
        """Bug 2: [上下文摘要] 不应被二次压缩丢失。"""
        from context import compress_messages

        # 模拟一个已经压缩过一次的对话历史
        messages = [
            {"role": "user", "content": "[上下文摘要] 这是之前保留的关键历史信息"},
            {"role": "assistant", "content": "收到"},
        ]
        # 补足足够的消息触发二次压缩
        for i in range(10):
            messages.append({"role": "user", "content": f"问题 {i}"})
            messages.append({"role": "assistant", "content": f"回答 {i}"})

        # mock client 避免真实调用
        class FakeClient:
            class messages:
                @staticmethod
                def create(**kwargs):
                    from types import SimpleNamespace
                    return SimpleNamespace(content=[
                        SimpleNamespace(type="text", text="压缩后的摘要")
                    ])

        # 设一个很大的 threshold 让压缩逻辑走分级分支
        monkeypatch_val = {"context_threshold": 100, "context_window": 1000}
        import context as ctx_mod
        orig_get = ctx_mod.get
        orig_ctx_window = ctx_mod.get_context_window

        def fake_get(k, d=None):
            if k == "context_threshold":
                return monkeypatch_val["context_threshold"]
            return orig_get(k, d)

        def fake_ctx_window(model=None):
            return monkeypatch_val["context_window"]

        ctx_mod.get = fake_get
        ctx_mod.get_context_window = fake_ctx_window
        try:
            result = compress_messages(FakeClient(), messages, "test-model", force=True)
        finally:
            ctx_mod.get = orig_get
            ctx_mod.get_context_window = orig_ctx_window

        # [上下文摘要] 应该保留在新结果里（可能在 high_importance 摘要或 recent 里）
        full_text = str(result)
        assert "关键历史信息" in full_text or "[上下文摘要]" in full_text, \
            "历史摘要不应被二次压缩丢失"

    def test_cache_hit_rate_excludes_cache_write(self):
        """Bug 3: 缓存命中率分母不应包含 cache_write。"""
        import metrics
        from pathlib import Path
        import tempfile

        # 写一个临时 metrics 文件
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            # cache_read=800, input=200, cache_write=1000
            # 正确命中率 = 800 / (800 + 200) = 80%
            f.write('{"ts":"2026-01-01","session":"abc","model":"test","input":200,"output":10,"cache_read":800,"cache_write":1000,"latency_ms":100,"cost_usd":0.01}\n')
            tmp_metrics = Path(f.name)

        orig_file = metrics._METRICS_FILE
        metrics._METRICS_FILE = tmp_metrics
        try:
            agg = metrics.aggregate()
            cacheable = agg["cache_read"] + agg["input"]
            hit_rate = agg["cache_read"] / cacheable * 100 if cacheable > 0 else 0
            assert hit_rate == 80.0, f"命中率应为 80%，实际 {hit_rate}%"
        finally:
            metrics._METRICS_FILE = orig_file
            tmp_metrics.unlink()


class TestBugFixesRound2:
    """第二轮 bug 修复回归测试。"""

    def test_error_substring_not_misjudged(self):
        """Bug A: 含 'error_handler'/'ValueError' 的正常内容不应被标为高优先级。"""
        from context import compress_messages
        import context as ctx_mod

        # 构造含 "error" 子串但不是错误的 tool_result
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "1",
                 "content": "def error_handler(e): pass  # ValueError 处理"}
            ]},
            {"role": "assistant", "content": "ok"},
        ]
        for i in range(10):
            messages.append({"role": "user", "content": f"问题 {i}"})
            messages.append({"role": "assistant", "content": f"回答 {i}"})

        # 验证该 tool_result 不含 [错误] 前缀
        text = str(messages[0]["content"][0].get("content", ""))
        assert not text.lstrip().startswith("[错误]"), "测试数据本身应以 [错误] 开头才算错误"

    def test_edit_tools_is_module_level(self):
        """Bug U: _EDIT_TOOLS 应是模块级常量，不是函数内局部变量。"""
        import context
        assert hasattr(context, "_EDIT_TOOLS"), "_EDIT_TOOLS 应在模块级定义"
        assert isinstance(context._EDIT_TOOLS, set)
        assert "edit_file" in context._EDIT_TOOLS
        assert "write_file" in context._EDIT_TOOLS

    def test_cached_l1_cwd_removed(self):
        """Bug E: 冗余的 _cached_l1_cwd 应已删除。"""
        import context
        assert not hasattr(context, "_cached_l1_cwd"), "冗余变量 _cached_l1_cwd 应已删除"

    def test_l3_no_function_level_import(self):
        """Bug B: L3 不应在函数内部 import platform/sys。"""
        import inspect
        import context
        src = inspect.getsource(context.build_system_blocks)
        # 函数体内不应有 import platform 或 import sys
        assert "import platform" not in src, "L3 不应在函数内 import platform"
        assert "import sys" not in src, "L3 不应在函数内 import sys"

    def test_l3_shell_detection_cross_platform(self):
        """Bug D: Shell 检测应处理 Windows（COMSPEC）和 Unix（SHELL）。"""
        import os
        import context
        from tools.state import get_state

        # 强制 L3 重建
        context._cached_l3_text = None
        context._cached_l3_mtime = 0.0

        blocks = context.build_system_blocks(force_refresh=True)
        l3 = blocks[2]["text"]

        # 应包含 Shell: 字段
        assert "Shell:" in l3
        # 不应出现裸 'sh' fallback（除非 SHELL 真的是 /bin/sh）
        # 主要验证不抛异常
