"""Security 模块测试：路径敏感度、SSRF 防护。"""

import os
import pytest

from tools.security import is_sensitive_path, is_internal_url


class TestSensitivePath:
    def test_ssh_key_blocked(self, tmp_path):
        home = tmp_path.as_posix()
        path = str(tmp_path / ".ssh" / "id_rsa")
        # 模拟 home
        os.environ["HOME"] = home
        # 强制展开
        os.makedirs(tmp_path / ".ssh", exist_ok=True)
        # 写入空文件
        with open(path, "w") as f:
            f.write("")
        # is_sensitive_path 检查 home + 模式
        # 注意：os.path.realpath 会解析符号链接，这里直接传相对路径
        assert is_sensitive_path("~/.ssh/id_rsa")

    def test_env_blocked(self, tmp_path):
        os.environ["HOME"] = tmp_path.as_posix()
        os.makedirs(tmp_path / ".env", exist_ok=True)
        with open(tmp_path / ".env" / "vars", "w") as f:
            f.write("")
        # .env 在 home 下视为敏感
        assert is_sensitive_path(str(tmp_path / ".env" / "vars"))

    def test_env_example_allowed(self, tmp_path):
        os.environ["HOME"] = tmp_path.as_posix()
        # .env.example / .env.template 应允许
        for name in (".env.example", ".env.template", ".env.sample"):
            f = tmp_path / name
            f.write_text("")
            # is_sensitive_path 直接传 home 路径下的 .env.xxx
            # 但 .env.example 不在 home 子目录下，而是 home 本身
            assert not is_sensitive_path(str(f)), f"{name} 不应被阻止"

    def test_random_project_path_allowed(self, tmp_path):
        f = tmp_path / "config.json"
        f.write_text("{}")
        # 项目目录下的常规文件不应被阻止
        # 注意：is_sensitive_path 主要在 home 下生效
        assert not is_sensitive_path(str(f))

    def test_credentials_filename(self, tmp_path):
        os.environ["HOME"] = tmp_path.as_posix()
        f = tmp_path / "credentials.json"
        f.write_text("{}")
        # 直接的 credentials.json 文件名匹配
        assert is_sensitive_path(str(f))

    def test_empty_path(self):
        assert not is_sensitive_path("")


class TestInternalURL:
    def test_localhost_blocked(self):
        assert is_internal_url("http://localhost:8080")

    def test_127_blocked(self):
        assert is_internal_url("http://127.0.0.1/")

    def test_private_10_blocked(self):
        # 注意：DNS 解析依赖于系统，对 example.com 一般是公网
        # 这里只测明确的私有 IP
        assert is_internal_url("http://10.0.0.1/")

    def test_192_168_blocked(self):
        assert is_internal_url("http://192.168.1.1/")

    def test_non_http_blocked(self):
        assert is_internal_url("file:///etc/passwd")
        assert is_internal_url("ftp://example.com/")
