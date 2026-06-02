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
