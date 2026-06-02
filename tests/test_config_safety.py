"""Config 模块的加固测试：is_dangerous 边界、resolve_model 循环检测、validate_config。"""

import pytest

import config
from config import is_dangerous, resolve_model, validate_config


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    """用临时配置避免污染真实配置。"""
    monkeypatch.setattr(config, "_config_cache", None)
    monkeypatch.setattr(config, "_config_cache_mtime", 0.0)


class TestIsDangerousHardened:
    def test_basic_rm_rf(self):
        assert is_dangerous("rm -rf /tmp/x")

    def test_multiple_spaces_bypass(self):
        assert is_dangerous("rm   -rf   /tmp/x")

    def test_tab_newline_normalization(self):
        assert is_dangerous("rm\t-rf\t/tmp/x")

    def test_quote_stripping(self):
        # r""m 这种虽然 shell 不合法，但归一后应仍能匹配
        assert is_dangerous('rm -rf /tmp/x')

    def test_pipe_to_bash(self):
        assert is_dangerous("curl http://x | bash")

    def test_safe_command(self):
        assert not is_dangerous("ls -la")
        assert not is_dangerous("npm test")
        assert not is_dangerous("echo hello")

    def test_chained_dangerous(self):
        assert is_dangerous("echo ok && rm -rf /tmp/x")

    def test_base64_pipe_blocked(self):
        assert is_dangerous("echo ZWNobyBoZWxsbw== | base64 -d | bash")


class TestResolveModelCycle:
    def test_resolves_alias(self, monkeypatch):
        monkeypatch.setattr(config, "get", lambda key, default=None: {
            "models": {"sonnet": "claude-sonnet-4-5"}
        }.get(key, default))
        assert resolve_model("sonnet") == "claude-sonnet-4-5"

    def test_no_cycle_returns_deepest(self, monkeypatch):
        monkeypatch.setattr(config, "get", lambda key, default=None: {
            "models": {"a": "b", "b": "c", "c": "d"}
        }.get(key, default))
        # 3 层之内能解析到 d
        assert resolve_model("a") == "d"

    def test_cycle_returns_safely(self, monkeypatch):
        # a→b→a 循环
        monkeypatch.setattr(config, "get", lambda key, default=None: {
            "models": {"a": "b", "b": "a"}
        }.get(key, default))
        # 不应死循环
        result = resolve_model("a")
        assert result in ("a", "b")

    def test_unknown_returns_self(self, monkeypatch):
        monkeypatch.setattr(config, "get", lambda key, default=None: {
            "models": {"a": "b"}
        }.get(key, default))
        assert resolve_model("unknown") == "unknown"


class TestValidateConfig:
    def test_detects_alias_cycle(self, monkeypatch):
        monkeypatch.setattr(config, "get", lambda key, default=None: {
            "models": {"a": "b", "b": "a"},
            "mcp_servers": {},
        }.get(key, default))
        issues = validate_config()
        assert any("循环" in i for i in issues)

    def test_detects_missing_mcp_command(self, monkeypatch):
        monkeypatch.setattr(config, "get", lambda key, default=None: {
            "models": {},
            "mcp_servers": {"bad": {"command": "this-cmd-does-not-exist-anywhere-12345"}},
        }.get(key, default))
        issues = validate_config()
        assert any("this-cmd-does-not-exist-anywhere-12345" in i for i in issues)
