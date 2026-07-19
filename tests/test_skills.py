"""Skills 模块测试。"""

import os

import pytest

from skills import (
    _parse_frontmatter, parse_skill_args, render_skill,
    AgentDef, load_agents, search_agents, list_agents_summary,
    resolve_context_patterns,
    SkillDef, SkillArg,
    invalidate_cache,
)


@pytest.fixture(autouse=True)
def clear_skill_cache():
    """每个测试前清除缓存，避免测试间干扰。"""
    invalidate_cache()


class TestParseFrontmatter:
    def test_no_frontmatter(self):
        meta, body = _parse_frontmatter("just content")
        assert meta == {}
        assert body == "just content"

    def test_simple_frontmatter(self):
        content = "---\ndescription: test skill\n---\nbody content"
        meta, body = _parse_frontmatter(content)
        assert meta.get("description") == "test skill"
        assert "body content" in body

    def test_arguments_frontmatter(self):
        content = """---
description: test
arguments:
  - name: query
    description: search query
    required: true
---
body"""
        meta, body = _parse_frontmatter(content)
        assert meta.get("description") == "test"
        assert len(meta.get("arguments", [])) == 1
        assert meta["arguments"][0]["name"] == "query"


class TestParseSkillArgs:
    def test_basic(self):
        result = parse_skill_args("key=value name=john")
        assert result == {"key": "value", "name": "john"}

    def test_empty(self):
        result = parse_skill_args("")
        assert result == {}

    def test_value_with_equals(self):
        result = parse_skill_args("expr=a=b")
        assert result == {"expr": "a=b"}


class TestRenderSkill:
    def test_basic_substitution(self):
        skill = SkillDef(name="test", content="Hello {{name}}!")
        result = render_skill(skill, {"name": "world"})
        assert result == "Hello world!"

    def test_unfilled_optional(self):
        skill = SkillDef(name="test", content="Hello {{name}} {{optional}}")
        result = render_skill(skill, {"name": "world"})
        assert "optional" not in result
        assert "Hello world" in result

    def test_no_args(self):
        skill = SkillDef(name="test", content="plain text")
        result = render_skill(skill, {})
        assert result == "plain text"


class TestAgentFrontmatter:
    """Agent 定义应解析 frontmatter，分离 description 和 body。"""

    def test_agent_with_frontmatter(self, tmp_path, monkeypatch):
        """有 frontmatter 的 agent md，description 提取，body 去除 frontmatter。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "reviewer.md").write_text(
            "---\ndescription: 代码审查专家\n---\n你是一个代码审查 agent。",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        assert "reviewer" in agents
        a = agents["reviewer"]
        assert a.description == "代码审查专家"
        # body 不应包含 frontmatter
        assert "description:" not in a.content
        assert "---" not in a.content
        assert "代码审查 agent" in a.content

    def test_agent_without_frontmatter(self, tmp_path, monkeypatch):
        """无 frontmatter 的 agent md，description 为空，content 是完整内容。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "simple.md").write_text("你是一个简单 agent。", encoding="utf-8")
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        a = agents["simple"]
        assert a.description == ""
        assert "简单 agent" in a.content


class TestAgentDefEnhanced:
    """AgentDef 增强元数据测试。"""

    def test_agent_with_full_frontmatter(self, tmp_path, monkeypatch):
        """完整 frontmatter 的 agent 应解析所有扩展字段。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "reviewer.md").write_text(
            "---\n"
            "description: 代码审查专家\n"
            "tags: [review, quality]\n"
            "allowed_tools: [read_file, grep_search, list_files]\n"
            "restricted_tools: [shell_exec, write_file]\n"
            "context_patterns: [\"**/*.py\", \"**/*.ts\"]\n"
            "version: 1.0.0\n"
            "---\n"
            "你是一个代码审查 agent。",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        a = agents["reviewer"]
        assert a.description == "代码审查专家"
        assert a.tags == ["review", "quality"]
        assert a.allowed_tools == ["read_file", "grep_search", "list_files"]
        assert a.restricted_tools == ["shell_exec", "write_file"]
        assert a.context_patterns == ["**/*.py", "**/*.ts"]
        assert a.version == "1.0.0"
        assert a.scope == "project"

    def test_agent_with_comma_separated_tags(self, tmp_path, monkeypatch):
        """逗号分隔的 tags 字符串应被正确解析。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "helper.md").write_text(
            "---\n"
            "description: helper\n"
            "tags: review, quality\n"
            "---\n"
            "helper content",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        a = agents["helper"]
        assert a.tags == ["review", "quality"]

    def test_agent_scope_tracking(self, tmp_path, monkeypatch):
        """agent 应正确追踪 scope（global/personal/project）。"""
        global_dir = tmp_path / ".config" / "octopus" / "agents"
        global_dir.mkdir(parents=True)
        (global_dir / "global_agent.md").write_text(
            "---\ndescription: global agent\n---\nglobal content",
            encoding="utf-8",
        )

        personal_dir = tmp_path / ".agents"
        personal_dir.mkdir()
        (personal_dir / "personal_agent.md").write_text(
            "---\ndescription: personal agent\n---\npersonal content",
            encoding="utf-8",
        )

        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        assert "global_agent" in agents
        assert "personal_agent" in agents
        assert agents["global_agent"].scope == "global"
        assert agents["personal_agent"].scope == "project"

    def test_agent_defaults(self, tmp_path, monkeypatch):
        """无扩展字段的 agent 应使用默认值。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "minimal.md").write_text(
            "---\ndescription: minimal\n---\nminimal content",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        a = agents["minimal"]
        assert a.allowed_tools == []
        assert a.restricted_tools == []
        assert a.context_patterns == []
        assert a.tags == []
        assert a.version == ""
        assert a.scope != ""  # 应有 scope 值


class TestSearchAgents:
    """search_agents 和 list_agents_summary 测试。"""

    def _setup_agents(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "reviewer.md").write_text(
            "---\ndescription: 代码审查专家\ntags: [review, quality]\n---\n审查代码",
            encoding="utf-8",
        )
        (agents_dir / "writer.md").write_text(
            "---\ndescription: 文档撰写助手\ntags: [docs, writing]\n---\n写文档",
            encoding="utf-8",
        )
        (agents_dir / "debugger.md").write_text(
            "---\ndescription: 调试专家\ntags: [debug, quality]\n---\n调试代码",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

    def test_search_by_keyword(self, tmp_path, monkeypatch):
        self._setup_agents(tmp_path, monkeypatch)
        results = search_agents(keyword="审查")
        assert len(results) == 1
        assert results[0].name == "reviewer"

    def test_search_by_tag(self, tmp_path, monkeypatch):
        self._setup_agents(tmp_path, monkeypatch)
        results = search_agents(tags=["quality"])
        assert len(results) == 2
        names = {a.name for a in results}
        assert names == {"reviewer", "debugger"}

    def test_search_by_keyword_and_tag(self, tmp_path, monkeypatch):
        self._setup_agents(tmp_path, monkeypatch)
        results = search_agents(keyword="调试", tags=["debug"])
        assert len(results) == 1
        assert results[0].name == "debugger"

    def test_search_no_results(self, tmp_path, monkeypatch):
        self._setup_agents(tmp_path, monkeypatch)
        results = search_agents(keyword="nonexistent")
        assert len(results) == 0

    def test_list_agents_summary(self, tmp_path, monkeypatch):
        self._setup_agents(tmp_path, monkeypatch)
        summary = list_agents_summary()
        assert "reviewer" in summary
        assert "writer" in summary
        assert "debugger" in summary
        assert "代码审查专家" in summary

    def test_list_agents_summary_empty(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        summary = list_agents_summary()
        assert "无可用" in summary


class TestResolveContextPatterns:
    def test_empty_patterns(self, tmp_path):
        agent = AgentDef(name="test", context_patterns=[])
        result = resolve_context_patterns(agent, str(tmp_path))
        assert result == ""

    def test_no_patterns_field(self, tmp_path):
        agent = AgentDef(name="test")
        result = resolve_context_patterns(agent, str(tmp_path))
        assert result == ""

    def test_matching_files(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hello')", encoding="utf-8")
        (tmp_path / "util.ts").write_text("const x = 1;", encoding="utf-8")
        (tmp_path / "readme.txt").write_text("ignore me", encoding="utf-8")

        agent = AgentDef(name="test", context_patterns=["**/*.py", "**/*.ts"])
        result = resolve_context_patterns(agent, str(tmp_path))
        assert "## 上下文文件" in result
        assert "### app.py" in result
        assert "```python" in result
        assert "print('hello')" in result
        assert "### util.ts" in result
        assert "```typescript" in result
        assert "const x = 1;" in result
        assert "readme.txt" not in result

    def test_no_matching_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")
        agent = AgentDef(name="test", context_patterns=["**/*.py"])
        result = resolve_context_patterns(agent, str(tmp_path))
        assert result == ""

    def test_binary_file_skipped(self, tmp_path):
        (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02\x03")
        agent = AgentDef(name="test", context_patterns=["**/*.bin"])
        result = resolve_context_patterns(agent, str(tmp_path))
        assert result == ""

    def test_large_file_skipped(self, tmp_path):
        big_content = "x" * (11 * 1024)
        (tmp_path / "big.py").write_text(big_content, encoding="utf-8")
        agent = AgentDef(name="test", context_patterns=["**/*.py"])
        result = resolve_context_patterns(agent, str(tmp_path))
        assert result == ""

    def test_max_files_limit(self, tmp_path):
        for i in range(25):
            (tmp_path / f"file_{i:02d}.py").write_text(f"# file {i}", encoding="utf-8")
        agent = AgentDef(name="test", context_patterns=["**/*.py"])
        result = resolve_context_patterns(agent, str(tmp_path))
        assert "### file_00.py" in result
        assert "### file_19.py" in result
        assert "### file_20.py" not in result
        assert "### file_24.py" not in result

    def test_total_size_limit(self, tmp_path):
        for i in range(6):
            content = "x" * (9 * 1024)
            (tmp_path / f"big_{i}.py").write_text(content, encoding="utf-8")
        agent = AgentDef(name="test", context_patterns=["**/*.py"])
        result = resolve_context_patterns(agent, str(tmp_path))
        count = result.count("### big_")
        assert count <= 6
        assert count >= 1

    def test_dedup_across_patterns(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hello')", encoding="utf-8")
        agent = AgentDef(name="test", context_patterns=["**/*.py", "**/*.py"])
        result = resolve_context_patterns(agent, str(tmp_path))
        assert result.count("### app.py") == 1

    def test_subdirectory_files(self, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "main.py").write_text("def main(): pass", encoding="utf-8")
        agent = AgentDef(name="test", context_patterns=["**/*.py"])
        result = resolve_context_patterns(agent, str(tmp_path))
        assert "### src/main.py" in result
        assert "def main(): pass" in result

    def test_unknown_extension_no_lang(self, tmp_path):
        (tmp_path / "config.xyz").write_text("data = 1", encoding="utf-8")
        agent = AgentDef(name="test", context_patterns=["**/*.xyz"])
        result = resolve_context_patterns(agent, str(tmp_path))
        assert "### config.xyz" in result
        assert "```\n" in result
        assert "```xyz" not in result

    def test_nonexistent_cwd(self, tmp_path):
        agent = AgentDef(name="test", context_patterns=["**/*.py"])
        result = resolve_context_patterns(agent, str(tmp_path / "nonexistent"))
        assert result == ""

    def test_unreadable_file_skipped(self, tmp_path):
        (tmp_path / "good.py").write_text("print('ok')", encoding="utf-8")
        bad = tmp_path / "bad.py"
        bad.write_text("content", encoding="utf-8")
        bad.chmod(0o000)
        try:
            agent = AgentDef(name="test", context_patterns=["**/*.py"])
            result = resolve_context_patterns(agent, str(tmp_path))
            assert "### good.py" in result
        finally:
            bad.chmod(0o644)


class TestAgentExtends:
    """Agent extends 继承测试。"""

    def test_extends_content_merge(self, tmp_path, monkeypatch):
        """子 agent 应继承父 agent 的 content，子追加在父之后。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "base.md").write_text(
            "---\ndescription: 基础 agent\ntags: [base]\n---\n你是基础助手。",
            encoding="utf-8",
        )
        (agents_dir / "advanced.md").write_text(
            "---\ndescription: 高级 agent\nextends: base\ntags: [advanced]\n---\n你还擅长代码审查。",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        assert "你是基础助手。" in agents["advanced"].content
        assert "你还擅长代码审查。" in agents["advanced"].content
        assert agents["advanced"].content.index("基础助手") < agents["advanced"].content.index("代码审查")

    def test_extends_tools_merge(self, tmp_path, monkeypatch):
        """子 agent 应合并父 agent 的工具列表。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "base.md").write_text(
            "---\nallowed_tools: [read_file, grep_search]\n---\nbase",
            encoding="utf-8",
        )
        (agents_dir / "child.md").write_text(
            "---\nextends: base\nallowed_tools: [read_file, write_file]\n---\nchild",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        child = agents["child"]
        assert "read_file" in child.allowed_tools
        assert "grep_search" in child.allowed_tools
        assert "write_file" in child.allowed_tools

    def test_extends_tags_merge(self, tmp_path, monkeypatch):
        """子 agent 应合并父 agent 的标签。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "base.md").write_text(
            "---\ntags: [review, quality]\n---\nbase",
            encoding="utf-8",
        )
        (agents_dir / "child.md").write_text(
            "---\nextends: base\ntags: [security]\n---\nchild",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        child = agents["child"]
        assert "review" in child.tags
        assert "quality" in child.tags
        assert "security" in child.tags

    def test_extends_description_fallback(self, tmp_path, monkeypatch):
        """子 agent 无 description 时应继承父 agent 的。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "base.md").write_text(
            "---\ndescription: 基础描述\n---\nbase",
            encoding="utf-8",
        )
        (agents_dir / "child.md").write_text(
            "---\nextends: base\n---\nchild",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        assert agents["child"].description == "基础描述"

    def test_extends_nonexistent_parent(self, tmp_path, monkeypatch):
        """extends 指向不存在的 agent 时不应报错。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "orphan.md").write_text(
            "---\nextends: nonexistent\n---\norphan content",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        assert agents["orphan"].content == "orphan content"

    def test_extends_child_description_overrides(self, tmp_path, monkeypatch):
        """子 agent 有 description 时应保留自己的，不用父的。"""
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "base.md").write_text(
            "---\ndescription: 基础描述\n---\nbase",
            encoding="utf-8",
        )
        (agents_dir / "child.md").write_text(
            "---\nextends: base\ndescription: 子描述\n---\nchild",
            encoding="utf-8",
        )
        monkeypatch.setattr("skills.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        agents = load_agents()
        assert agents["child"].description == "子描述"
