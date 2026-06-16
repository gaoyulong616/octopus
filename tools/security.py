"""安全工具：路径验证、URL 安全检查。"""

import os
import socket
import ipaddress
from urllib.parse import urlparse


def validate_path(path: str, base: str | None = None) -> str:
    """验证路径安全，解析为绝对路径。

    对于写/删操作，警告但默认允许（保持向后兼容）。
    返回解析后的绝对路径。
    """
    from tools.state import get_cwd
    base = base or get_cwd()
    abs_path = os.path.realpath(os.path.join(base, path))
    return abs_path


def is_path_within_project(path: str, base: str | None = None) -> bool:
    """检查路径是否在项目目录内。"""
    from tools.state import get_cwd
    base = base or get_cwd()
    base_real = os.path.realpath(base)
    path_real = os.path.realpath(path)
    return path_real.startswith(base_real + os.sep) or path_real == base_real


_INTERNAL_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def is_internal_url(url: str) -> bool:
    """检查 URL 是否指向内网地址（SSRF 防护）。"""
    parsed = urlparse(url)

    # Only allow http/https
    if parsed.scheme not in ("http", "https"):
        return True

    hostname = parsed.hostname
    if not hostname:
        return False

    # Block obvious internal hostnames
    if hostname in ("localhost", "localhost.localdomain"):
        return True

    try:
        # DNS resolve and check IP
        addr_info = socket.getaddrinfo(hostname, None)
        for info in addr_info:
            ip = ipaddress.ip_address(info[4][0])
            for net in _INTERNAL_NETS:
                if ip in net:
                    return True
    except (socket.gaierror, ValueError):
        pass

    return False


def resolve_and_check(url: str) -> str:
    """解析 URL 的 IP 并验证不指向内网，返回解析后的 IP 地址。

    用于在实际发请求前做最终校验，防止 DNS rebinding 攻击。
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"URL 无有效 hostname: {url}")
    addr_info = socket.getaddrinfo(hostname, None)
    for info in addr_info:
        ip = ipaddress.ip_address(info[4][0])
        for net in _INTERNAL_NETS:
            if ip in net:
                return str(ip)
    return ""


# 敏感文件路径模式（防止 LLM 误读密钥/凭证）
_SENSITIVE_PATH_PATTERNS = [
    # SSH / GPG 密钥
    ".ssh/",
    ".gnupg/",
    # 云服务凭证
    ".aws/", ".azure/", ".gcp/",
    ".config/gcloud/",
    # 通用密钥文件
    ".env",
    ".npmrc", ".pypirc",
    ".docker/",
    # OAuth / tokens
    ".oauth/",
    ".netrc",
]

_SENSITIVE_FILE_NAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "credentials.json",
    "secrets.yml", "secrets.yaml", "secrets.json",
    ".htpasswd", ".pgpass",
}


def is_sensitive_path(path: str) -> bool:
    """检查路径是否指向敏感文件（密钥、凭证等）。"""
    if not path:
        return False
    expanded = os.path.expanduser(path)
    real = os.path.realpath(expanded).lower()
    home = os.path.expanduser("~").lower()

    # 检查文件名
    base = os.path.basename(real)
    if base in _SENSITIVE_FILE_NAMES:
        return True

    # 检查路径模式
    for pat in _SENSITIVE_PATH_PATTERNS:
        if pat in real:
            # 允许 .env.example / .env.template 这类样板文件
            if pat == ".env" and real.endswith((".env.example", ".env.template", ".env.sample", ".env.test", ".env.ci")):
                continue
            # SSH/GPG/云凭证目录只在 home 下判定敏感
            if pat not in (".env",) and not real.startswith(home + os.sep):
                continue
            return True
    return False


def is_path_within_user_dir(path: str, user_root: str) -> bool:
    """检查路径是否在用户目录内（多用户隔离用）。"""
    if not user_root:
        return True  # 无用户目录限制时默认允许
    path_real = os.path.realpath(os.path.expanduser(path))
    user_root_real = os.path.realpath(user_root)
    return path_real.startswith(user_root_real + os.sep) or path_real == user_root_real
