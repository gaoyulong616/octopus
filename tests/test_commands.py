"""斜杠命令测试：/init 和 /review 的 prompt 质量（对标 Claude Code 风格）。"""

import pytest

import commands


class TestInitPrompt:
    """验证 /init prompt 对标 Claude Code CLAUDE.md：精简、AI 协作指令而非项目文档。"""

    def _run_init(self, tmp_path, monkeypatch, with_existing=False):
        monkeypatch.setattr("tools.get_cwd", lambda: str(tmp_path))
        if with_existing:
            (tmp_path / "OCTOPUS.md").write_text("# old\nold content here\n")
            monkeypatch.setattr("builtins.input", lambda prompt: "y")
        return commands.cmd_init("/init", [], {})

    def test_returns_task_override_when_no_existing(self, tmp_path, monkeypatch):
        result = self._run_init(tmp_path, monkeypatch)
        assert result.task_override is not None
        assert result.text is None

    def test_prompt_states_target_length(self, tmp_path, monkeypatch):
        """prompt 应明确长度目标（30-80 行），防止生成冗长文档。"""
        result = self._run_init(tmp_path, monkeypatch)
        assert "30-80" in result.task_override

    def test_prompt_guides_agent_to_explore(self, tmp_path, monkeypatch):
        """prompt 应引导 agent 自己用工具探索，而非依赖预填信息。"""
        result = self._run_init(tmp_path, monkeypatch)
        prompt = result.task_override
        assert "read_file" in prompt or "list_files" in prompt

    def test_prompt_does_not_prefill_project_info(self, tmp_path, monkeypatch):
        """新版不应有"项目信息/语言/框架"等硬塞字段（旧版缺陷）。"""
        result = self._run_init(tmp_path, monkeypatch)
        prompt = result.task_override
        assert "## 项目信息" not in prompt
        assert "- 语言:" not in prompt
        assert "- 框架:" not in prompt

    def test_prompt_requires_four_core_sections(self, tmp_path, monkeypatch):
        """prompt 应明确要求四块内容。"""
        result = self._run_init(tmp_path, monkeypatch)
        prompt = result.task_override
        assert "常用命令" in prompt
        assert "架构概览" in prompt
        assert "关键约定" in prompt
        assert "添加新模块" in prompt

    def test_prompt_emphasizes_instructions_over_docs(self, tmp_path, monkeypatch):
        """应强调这是给 AI 的协作指令，不是项目文档。"""
        result = self._run_init(tmp_path, monkeypatch)
        prompt = result.task_override
        assert "协作指令" in prompt

    def test_prompt_excludes_readme_duplication(self, tmp_path, monkeypatch):
        """应明确禁止复制 README 内容。"""
        result = self._run_init(tmp_path, monkeypatch)
        prompt = result.task_override
        assert "README" in prompt
        assert "不要复制" in prompt

    def test_prompt_uses_write_file(self, tmp_path, monkeypatch):
        """应明确指示用 write_file 工具创建文件。"""
        result = self._run_init(tmp_path, monkeypatch)
        prompt = result.task_override
        assert "write_file" in prompt

    def test_prompt_includes_existing_when_overwriting(self, tmp_path, monkeypatch):
        """覆盖现有文件时，应把旧内容作为参考注入 prompt。"""
        result = self._run_init(tmp_path, monkeypatch, with_existing=True)
        prompt = result.task_override
        assert "old content here" in prompt

    def test_cancel_when_user_says_no(self, tmp_path, monkeypatch):
        """用户拒绝覆盖时应取消，返回 text 而非 task_override。"""
        (tmp_path / "OCTOPUS.md").write_text("# old")
        monkeypatch.setattr("tools.get_cwd", lambda: str(tmp_path))
        monkeypatch.setattr("builtins.input", lambda prompt: "n")
        result = commands.cmd_init("/init", [], {})
        assert result.task_override is None
        assert "已取消" in result.text


class TestReviewPrompt:
    """验证 /review prompt：严重度分级 + 让 agent 主动取完整 diff。"""

    def _run_review(self, monkeypatch, diff_stat, branch="feature-x"):
        def mock_bash(cmd, timeout=None, **kwargs):
            if "rev-parse" in cmd:
                return branch
            if "diff" in cmd and "--stat" in cmd:
                return diff_stat
            return ""
        monkeypatch.setattr("tools.run_bash", mock_bash)
        monkeypatch.setattr("tools.get_cwd", lambda: "/fake")
        return commands.cmd_review("/review", [], {})

    def test_no_changes_returns_text(self, monkeypatch):
        """无 diff 时返回 text，不是 task_override。"""
        result = self._run_review(monkeypatch, diff_stat="")
        assert result.task_override is None
        assert "没有可审查" in result.text

    def test_prompt_has_severity_levels(self, monkeypatch):
        """prompt 应包含四级严重度分级（阻断/重要/次要/提问）。"""
        result = self._run_review(monkeypatch, diff_stat="file.py | 10 ++++++----")
        prompt = result.task_override
        assert "阻断" in prompt
        assert "重要" in prompt
        assert "次要" in prompt
        assert "提问" in prompt or "澄清" in prompt

    def test_prompt_lets_agent_fetch_full_diff(self, monkeypatch):
        """prompt 应让 agent 自己执行 git diff 取完整内容，而非预填截断版。"""
        result = self._run_review(monkeypatch, diff_stat="file.py | 10 ++++++----")
        prompt = result.task_override
        # 应让 agent 主动 git diff（不再预填截断版）
        assert "git diff" in prompt
        # 应提示 agent 先确定主分支（避免硬编码 main）
        assert "主分支" in prompt or "git branch -a" in prompt
        # 旧版的"## 完整 Diff"硬塞段不应存在
        assert "## 完整 Diff" not in prompt

    def test_prompt_only_carries_stat_not_full_diff(self, monkeypatch):
        """prompt 只应携带 stat，不应携带完整 diff 内容（避免截断丢上下文）。"""
        stat = "big_file.py | 500 ++++++++++++++++++++++++++++++++++++++"
        result = self._run_review(monkeypatch, diff_stat=stat)
        prompt = result.task_override
        assert stat in prompt
        # 不应出现"## 完整 Diff"等硬塞完整 diff 的标题
        assert "完整 Diff" not in prompt

    def test_prompt_focuses_on_diff_only(self, monkeypatch):
        """prompt 应强调聚焦 diff，不评审未改动的代码。"""
        result = self._run_review(monkeypatch, diff_stat="file.py | 10 ++++++----")
        prompt = result.task_override
        assert "聚焦" in prompt
        assert "未改动" in prompt or "未改动的代码" in prompt

    def test_prompt_encourages_reading_full_files(self, monkeypatch):
        """prompt 应引导 agent 用 read_file 看完整文件理解上下文。"""
        result = self._run_review(monkeypatch, diff_stat="file.py | 10 ++++++----")
        prompt = result.task_override
        assert "read_file" in prompt

    def test_not_in_git_repo(self, monkeypatch):
        """不在 git 仓库时应返回错误文本。"""
        monkeypatch.setattr("tools.run_bash", lambda *a, **kw: "[错误] not a git repo")
        monkeypatch.setattr("tools.get_cwd", lambda: "/fake")
        result = commands.cmd_review("/review", [], {})
        assert result.task_override is None
        assert "不在 git 仓库" in result.text

    def test_no_changes_when_no_output_placeholder(self, monkeypatch):
        """run_bash 在 stdout 空时返回 '(no output)'，应识别为无变更（Bug 回归）。"""
        # branch 正常，但所有 diff 都返回 "(no output)"
        def mock_bash(cmd, timeout=None, **kwargs):
            if "rev-parse" in cmd:
                return "main"
            return "(no output)"
        monkeypatch.setattr("tools.run_bash", mock_bash)
        monkeypatch.setattr("tools.get_cwd", lambda: "/fake")
        result = commands.cmd_review("/review", [], {})
        assert result.task_override is None
        assert "没有可审查" in result.text

    def test_no_changes_when_exit_code_in_output(self, monkeypatch):
        """run_bash 非 0 退出时追加 '[exit code: N]'，应识别为无变更（Bug 回归）。"""
        def mock_bash(cmd, timeout=None, **kwargs):
            if "rev-parse" in cmd:
                return "main"
            return "\n[exit code: 128]"
        monkeypatch.setattr("tools.run_bash", mock_bash)
        monkeypatch.setattr("tools.get_cwd", lambda: "/fake")
        result = commands.cmd_review("/review", [], {})
        assert result.task_override is None
        assert "没有可审查" in result.text

    def test_not_in_git_repo_when_exit_code_in_branch(self, monkeypatch):
        """git rev-parse 失败返回 '[exit code: 128]'，应识别为不在仓库（Bug 回归）。"""
        monkeypatch.setattr("tools.run_bash", lambda *a, **kw: "\n[exit code: 128]")
        monkeypatch.setattr("tools.get_cwd", lambda: "/fake")
        result = commands.cmd_review("/review", [], {})
        assert result.task_override is None
        assert "不在 git 仓库" in result.text

    def test_no_error_marker_leaks_into_prompt(self, monkeypatch):
        """错误标记（[错误]/[exit code]/(no output)）不应泄漏到 prompt 文本（Bug 回归）。"""
        result = self._run_review(monkeypatch, diff_stat="file.py | 10 ++++++----")
        prompt = result.task_override
        assert "[错误]" not in prompt
        assert "[exit code" not in prompt
        assert "(no output)" not in prompt


class TestAgentSwitch:
    """/agent 切换：使用 agent_persona 追加层（不再用 system_prompt_override 替换）。"""

    def test_switch_to_existing_agent_sets_persona(self, monkeypatch):
        """切到自定义 agent：state.agent_persona 被设置（不再是 system_prompt_override）。"""
        from skills import AgentDef
        fake_agent = AgentDef(
            name="reviewer",
            description="代码审查",
            content="你是代码审查专家。",
        )
        monkeypatch.setattr("skills.load_agents", lambda: {"reviewer": fake_agent})

        state: dict = {}
        result = commands.cmd_agent("/agent reviewer", [], state)

        assert "已切换" in result.text
        assert state["current_agent"] == "reviewer"
        # 关键：用 agent_persona，不用 system_prompt_override（避免替换主系统提示词）
        assert state.get("agent_persona") == "你是代码审查专家。"
        assert state.get("system_prompt_override") is None

    def test_switch_to_default_clears_persona(self, monkeypatch):
        """/agent default 清除 agent_persona（不再用 system_prompt_override）。"""
        state = {"current_agent": "reviewer", "agent_persona": "你是审查专家。"}
        result = commands.cmd_agent("/agent default", [], state)

        assert "已切换回默认" in result.text
        assert state["current_agent"] is None
        assert state.get("agent_persona") is None

    def test_agent_not_found(self, monkeypatch):
        monkeypatch.setattr("skills.load_agents", lambda: {})
        state: dict = {}
        result = commands.cmd_agent("/agent ghost", [], state)
        assert "未找到" in result.text
        assert "current_agent" not in state

    def test_agent_no_arg_shows_current(self):
        state = {"current_agent": "reviewer"}
        result = commands.cmd_agent("/agent", [], state)
        assert "reviewer" in result.text

    def test_agents_command_lists_description(self, monkeypatch):
        """/agents 列表应展示 frontmatter 中的 description。"""
        from skills import AgentDef
        agents = {
            "reviewer": AgentDef(name="reviewer", description="代码审查专家", content="x"),
            "writer": AgentDef(name="writer", description="文档撰写", content="y"),
        }
        monkeypatch.setattr("skills.load_agents", lambda: agents)
        result = commands.cmd_agents("/agents", [], {})
        assert "代码审查专家" in result.text
        assert "文档撰写" in result.text
