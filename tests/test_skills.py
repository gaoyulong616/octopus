"""Skills 模块测试。"""

import os

import pytest

from skills import (
    _parse_frontmatter, parse_skill_args, render_skill,
    SkillDef, SkillArg,
)


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
