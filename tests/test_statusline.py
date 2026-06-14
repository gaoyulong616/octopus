"""Statusline 模块测试。"""

import os
from pathlib import Path

import pytest

import statusline
from statusline import render_statusline, _shorten_cwd


class TestShortenCwd:
    def test_home_replaced(self):
        home = os.path.expanduser("~")
        assert _shorten_cwd(home + "/projects/foo").startswith("~")

    def test_outside_home_unchanged(self):
        assert _shorten_cwd("/tmp/x") == "/tmp/x"


class TestRenderStatusline:
    def test_returns_empty_when_no_template(self, tmp_path, monkeypatch):
        # 默认模板在 _DEFAULTS 中存在，需要 patch get 让它返回 ""
        import config
        monkeypatch.setattr(config, "get", lambda key, default=None: "" if key == "statusline" else default)
        assert render_statusline({}) == ""

    def test_template_substitution(self, monkeypatch):
        import config
        from tools import state as state_mod

        # 固定 cwd 以便 git_branch 等不依赖外部
        monkeypatch.setattr(state_mod.AgentState, "get_cwd",
                            lambda self: "/tmp/test-cwd")
        monkeypatch.setattr(config, "get", lambda key, default=None: {
            "statusline": "model={model} cwd={cwd} tokens={tokens} cost=${cost} branch={git_branch}",
            "model": "claude-sonnet-4-5",
        }.get(key, default))
        # 强制 statusline 模块也使用 mock 的 config.get
        import statusline as sl
        monkeypatch.setattr(sl, "_get_git_branch", lambda cwd: "main")

        out = sl.render_statusline({
            "session_tokens": {"input": 100, "output": 50},
            "session_cost_usd": 0.0123,
            "session_id": "abcdefghij",
        })
        assert "model=claude-sonnet-4-5" in out
        assert "tokens=150" in out
        assert "cost=$0.0123" in out
        assert "branch=main" in out

    def test_missing_field_safe(self, monkeypatch):
        import config
        from tools import state as state_mod
        monkeypatch.setattr(state_mod.AgentState, "get_cwd",
                            lambda self: "/tmp/x")
        monkeypatch.setattr(config, "get", lambda key, default=None: {
            "statusline": "{model} | {unknown_field}",
            "model": "test",
        }.get(key, default))
        import statusline as sl
        monkeypatch.setattr(sl, "_get_git_branch", lambda cwd: "")
        out = sl.render_statusline({})
        assert "test" in out
        # missing field 不抛错
        assert "unknown_field" not in out

    def test_agent_placeholder_falls_back_to_default(self, monkeypatch):
        """state 中没有 current_agent 时，{agent} 占位符回退到 'default'。"""
        import config
        from tools import state as state_mod
        monkeypatch.setattr(state_mod.AgentState, "get_cwd",
                            lambda self: "/tmp/x")
        monkeypatch.setattr(config, "get", lambda key, default=None: {
            "statusline": "agent={agent}",
            "model": "test",
        }.get(key, default))
        import statusline as sl
        monkeypatch.setattr(sl, "_get_git_branch", lambda cwd: "")
        # state 不含 current_agent
        out = sl.render_statusline({})
        assert "agent=default" in out

    def test_agent_placeholder_uses_current_agent(self, monkeypatch):
        """state 中有 current_agent 时，{agent} 显示该 agent 名。"""
        import config
        from tools import state as state_mod
        monkeypatch.setattr(state_mod.AgentState, "get_cwd",
                            lambda self: "/tmp/x")
        monkeypatch.setattr(config, "get", lambda key, default=None: {
            "statusline": "agent={agent}",
            "model": "test",
        }.get(key, default))
        import statusline as sl
        monkeypatch.setattr(sl, "_get_git_branch", lambda cwd: "")
        out = sl.render_statusline({"current_agent": "reviewer"})
        assert "agent=reviewer" in out
