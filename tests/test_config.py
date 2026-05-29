"""配置模块测试。"""

import json
import os
from pathlib import Path

import pytest

import config


@pytest.fixture(autouse=True)
def clean_config(tmp_path, monkeypatch):
    """每个测试用例前清除配置缓存。"""
    config.invalidate()
    config._config_cache = None
    yield
    config.invalidate()
    config._config_cache = None


class TestConfigDefaults:
    def test_default_max_tokens(self):
        assert config.get("max_tokens") == 8096

    def test_default_max_iterations(self):
        assert config.get("max_iterations") == 20

    def test_default_permissions(self):
        assert config.get("permissions") == "confirm"


class TestConfigFile:
    def test_load_from_file(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"api_key": "sk-test", "model": "test-model"}))
        config._CONFIG_PATHS = [cfg_file]
        config.invalidate()
        assert config.get("api_key") == "sk-test"
        assert config.get("model") == "test-model"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OCTOPUS_MODEL", "env-model")
        config.invalidate()
        config._config_cache = None
        assert config.get("model") == "env-model"


class TestDangerousCommands:
    def test_rm_rf(self):
        assert config.is_dangerous("rm -rf /") is True

    def test_git_push_force(self):
        assert config.is_dangerous("git push --force") is True

    def test_safe_command(self):
        assert config.is_dangerous("ls -la") is False

    def test_git_log(self):
        assert config.is_dangerous("git log") is False


class TestValidation:
    def test_valid_max_tokens(self):
        assert config.validate_value("max_tokens", "100") == 100

    def test_invalid_max_tokens(self):
        with pytest.raises(ValueError):
            config.validate_value("max_tokens", "-1")

    def test_valid_permissions(self):
        assert config.validate_value("permissions", "auto-approve") == "auto-approve"

    def test_invalid_permissions(self):
        with pytest.raises(ValueError):
            config.validate_value("permissions", "invalid")

    def test_valid_base_url(self):
        assert config.validate_value("base_url", "https://api.example.com") == "https://api.example.com"

    def test_invalid_base_url(self):
        with pytest.raises(ValueError):
            config.validate_value("base_url", "not-a-url")


class TestModelResolution:
    def test_resolve_alias(self, monkeypatch):
        monkeypatch.setattr(config, "_get_config", lambda: {
            "model": "ds-flash",
            "models": {"ds-flash": "deepseek-v4-flash", "ds-pro": "deepseek-v4-pro"},
        })
        assert config.resolve_model("ds-flash") == "deepseek-v4-flash"
        assert config.resolve_model("ds-pro") == "deepseek-v4-pro"

    def test_resolve_unknown(self, monkeypatch):
        monkeypatch.setattr(config, "_get_config", lambda: {"model": "x", "models": {}})
        assert config.resolve_model("unknown") == "unknown"
