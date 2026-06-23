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

    def test_default_permissions(self):
        assert config.get("permissions") == "confirm"


class TestConfigFile:
    def test_load_from_file(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"api_key": "sk-test", "model": "test-model"}))
        monkeypatch.setattr(config, "_CONFIG_PATHS", [cfg_file])
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


class TestProviderModels:
    def test_get_models_from_providers(self, monkeypatch):
        monkeypatch.setattr(config, "_get_config", lambda: {
            "model": "deepseek-v4-flash",
            "provider": "deepseek",
            "providers": {
                "deepseek": {
                    "base_url": "https://api.deepseek.com",
                    "api_key": "sk-test",
                    "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
                },
                "zhipu": {
                    "base_url": "https://open.bigmodel.cn",
                    "api_key": "key2",
                    "models": ["glm-5.1"],
                },
            },
        })
        models = config.get_models()
        assert ("glm-5.1", "zhipu") in models

    def test_switch_model_changes_provider(self, monkeypatch):
        cfg = {
            "model": "deepseek-v4-flash",
            "provider": "deepseek",
            "providers": {
                "deepseek": {
                    "base_url": "https://api.deepseek.com",
                    "api_key": "sk-deep",
                    "models": ["deepseek-v4-flash"],
                },
                "zhipu": {
                    "base_url": "https://open.bigmodel.cn",
                    "api_key": "sk-zhipu",
                    "models": ["glm-5.1"],
                },
            },
        }
        monkeypatch.setattr(config, "_get_config", lambda: cfg)
        config.switch_model("glm-5.1")
        assert cfg["provider"] == "zhipu"
        assert cfg["model"] == "glm-5.1"

    def test_get_api_key_from_provider(self, monkeypatch):
        monkeypatch.setattr(config, "_get_config", lambda: {
            "model": "glm-5.1",
            "provider": "zhipu",
            "api_key": "top-level-key",
            "providers": {
                "zhipu": {
                    "base_url": "https://open.bigmodel.cn",
                    "api_key": "zhipu-key",
                    "models": ["glm-5.1"],
                },
            },
        })
        assert config.get("api_key") == "zhipu-key"
        assert config.get("base_url") == "https://open.bigmodel.cn"

    def test_fallback_to_top_level(self, monkeypatch):
        monkeypatch.setattr(config, "_get_config", lambda: {
            "model": "some-model",
            "api_key": "top-key",
            "base_url": "https://top.url",
        })
        assert config.get("api_key") == "top-key"
        assert config.get("base_url") == "https://top.url"


class TestContextWindow:
    """测试 models 对象格式和 get_context_window。"""

    def test_default_context_window(self, monkeypatch):
        """无 providers 配置时默认 200k。"""
        monkeypatch.setattr(config, "_get_config", lambda: {"model": "any-model"})
        assert config.get_context_window() == 200_000

    def test_context_window_from_provider(self, monkeypatch):
        """从 providers 对象格式读取 context_window。"""
        monkeypatch.setattr(config, "_get_config", lambda: {
            "model": "deepseek-v4-flash",
            "provider": "deepseek",
            "providers": {
                "deepseek": {
                    "base_url": "https://api.deepseek.com",
                    "api_key": "test",
                    "models": [
                        {"name": "deepseek-v4-flash", "context_window": 128000},
                    ],
                },
            },
        })
        assert config.get_context_window("deepseek-v4-flash") == 128_000

    def test_context_window_unknown_model_defaults(self, monkeypatch):
        """模型不在 providers 中时默认 200k。"""
        monkeypatch.setattr(config, "_get_config", lambda: {
            "model": "other-model",
            "providers": {
                "deepseek": {
                    "base_url": "https://api.deepseek.com",
                    "api_key": "test",
                    "models": [{"name": "deepseek-v4-flash", "context_window": 128000}],
                },
            },
        })
        assert config.get_context_window("other-model") == 200_000

    def test_models_backward_compat_string_array(self, monkeypatch):
        """旧格式字符串数组仍能正常工作。"""
        monkeypatch.setattr(config, "_get_config", lambda: {
            "model": "glm-5.1",
            "provider": "zhipu",
            "providers": {
                "zhipu": {
                    "base_url": "https://open.bigmodel.cn",
                    "api_key": "test",
                    "models": ["glm-5.1"],
                },
            },
        })
        models = config.get_models()
        assert ("glm-5.1", "zhipu") in models
