"""MCP (Model Context Protocol) 客户端：连接外部工具服务器。

支持多种传输：
  - stdio（默认）：通过子进程的 stdin/stdout 通信
  - http：通过 HTTP POST 请求（适合无状态服务端，需服务端支持）
  - sse：通过 Server-Sent Events（占位，暂未实现）

所有传输实现统一的 TransportBase 接口（send_message / read_message / close）。
"""

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any


class TransportBase:
    """MCP 传输抽象基类。"""

    def send_message(self, message: dict) -> None:
        raise NotImplementedError

    def read_message(self) -> dict:
        raise NotImplementedError

    def close(self) -> None:
        pass


class StdioTransport(TransportBase):
    """stdio 传输：通过子进程的 stdin/stdout 通信（MCP 默认方式）。"""

    def __init__(self, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, cwd: str | None = None):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self._proc: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None

    def connect(self) -> bool:
        full_cmd = [self.command] + self.args
        proc_env = dict(os.environ)
        proc_env.update(self.env)

        try:
            self._proc = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                cwd=self.cwd,
                bufsize=0,
            )
        except FileNotFoundError:
            print(f"  [MCP] 命令未找到: {self.command}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"  [MCP] 启动失败: {e}", file=sys.stderr)
            return False

        # stderr drain 线程
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        return True

    def _drain_stderr(self):
        if self._proc and self._proc.stderr:
            try:
                for line in self._proc.stderr:
                    pass
            except Exception:
                pass

    def send_message(self, message: dict) -> None:
        body = json.dumps(message, ensure_ascii=False)
        header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(header.encode("utf-8"))
            self._proc.stdin.write(body.encode("utf-8"))
            self._proc.stdin.flush()

    def read_message(self) -> dict:
        if not self._proc or not self._proc.stdout:
            raise ConnectionError("进程未启动")

        header_lines = []
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise ConnectionError("服务器关闭连接")
            decoded = line.decode("utf-8").strip()
            if decoded == "":
                break
            header_lines.append(decoded)

        content_length = 0
        for hl in header_lines:
            if hl.lower().startswith("content-length:"):
                content_length = int(hl.split(":", 1)[1].strip())
                break
        if content_length == 0:
            raise ConnectionError("无效的消息头")

        body = self._proc.stdout.read(content_length)
        if not body:
            raise ConnectionError("服务器关闭连接")
        return json.loads(body.decode("utf-8"))

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def close(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None


class HTTPTransport(TransportBase):
    """HTTP 传输：每次请求通过 HTTP POST 发送，响应直接返回。

    适用于无状态 MCP 服务端（每个请求独立处理，无服务端推送）。
    服务端需实现 POST 接口，请求/响应 body 均为 JSON-RPC 2.0。

    配置示例：
        "mcp_servers": {
          "remote": {
            "transport": "http",
            "url": "https://mcp.example.com/rpc",
            "headers": {"Authorization": "Bearer xxx"}
          }
        }
    """

    def __init__(self, url: str, headers: dict | None = None, timeout: int = 30):
        self.url = url
        self.headers = {"Content-Type": "application/json"}
        if headers:
            self.headers.update(headers)
        self.timeout = timeout

    def connect(self) -> bool:
        # HTTP 是无连接的，做一次 ping 确认可达
        try:
            from urllib.request import Request, urlopen
            req = Request(self.url,
                          data=json.dumps({"jsonrpc": "2.0", "id": 0,
                                           "method": "ping"}).encode("utf-8"),
                          headers=self.headers)
            with urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 400:
                    print(f"  [MCP/HTTP] ping 失败: HTTP {resp.status}", file=sys.stderr)
                    return False
            return True
        except Exception as e:
            print(f"  [MCP/HTTP] 连接失败: {e}", file=sys.stderr)
            return False

    def send_message(self, message: dict) -> None:
        # HTTP 传输不在 send/read 分离，直接在 read_message 中收发
        self._pending = message

    def read_message(self) -> dict:
        msg = getattr(self, "_pending", None)
        if msg is None:
            raise ConnectionError("无待发送消息")
        from urllib.request import Request, urlopen
        req = Request(self.url,
                      data=json.dumps(msg).encode("utf-8"),
                      headers=self.headers)
        with urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def is_alive(self) -> bool:
        return True

    def close(self) -> None:
        pass


class SSETransport(TransportBase):
    """SSE 传输占位：当前版本暂不支持，需要服务端长连接。

    配置示例（参考用，未实现）：
        "mcp_servers": {
          "remote": {
            "transport": "sse",
            "url": "https://mcp.example.com/sse"
          }
        }
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("SSE 传输暂未实现，请使用 stdio 或 http")

    def send_message(self, message: dict) -> None:
        raise NotImplementedError

    def read_message(self) -> dict:
        raise NotImplementedError


# ─────────────────────────────────────────────
# MCPServer：使用 Transport 抽象
# ─────────────────────────────────────────────

class MCPServer:
    """与单个 MCP 服务器的连接，使用配置的传输方式。"""

    def __init__(self, name: str, transport: str = "stdio", **kwargs):
        self.name = name
        self.transport_name = transport
        if transport == "stdio":
            self._transport: TransportBase = StdioTransport(
                command=kwargs.get("command", ""),
                args=kwargs.get("args", []),
                env=kwargs.get("env", {}),
                cwd=kwargs.get("cwd"),
            )
        elif transport == "http":
            self._transport = HTTPTransport(
                url=kwargs.get("url", ""),
                headers=kwargs.get("headers"),
                timeout=kwargs.get("timeout", 30),
            )
        elif transport == "sse":
            self._transport = SSETransport(
                url=kwargs.get("url", ""),
            )
        else:
            raise ValueError(f"未知 MCP 传输: {transport}")

        self._request_id = 0
        self._lock = threading.Lock()
        self._tools: list[dict] = []
        self._server_info: dict = {}
        self._connected = False

    def connect(self) -> bool:
        if not self._transport.connect():
            return False
        try:
            result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "octopus-agent", "version": "1.0.0"},
            })
            self._server_info = result.get("serverInfo", {})
            self._send_notification("notifications/initialized", None)
            tools_result = self._send_request("tools/list", None)
            self._tools = tools_result.get("tools", [])
            self._connected = True
            return True
        except Exception as e:
            print(f"  [MCP] 服务器 '{self.name}' 握手失败: {e}")
            self.close()
            return False

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send_request(self, method: str, params: Any) -> dict:
        """发送 JSON-RPC 请求并等待响应。"""
        with self._lock:
            msg = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
            if params is not None:
                msg["params"] = params
            self._transport.send_message(msg)
            # 读取响应，跳过通知
            while True:
                response = self._transport.read_message()
                if "id" in response and response["id"] == msg["id"]:
                    break

        if "error" in response:
            err = response["error"]
            raise RuntimeError(f"MCP 错误 [{err.get('code')}]: {err.get('message')}")
        return response.get("result", {})

    def _send_notification(self, method: str, params: Any):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        try:
            self._transport.send_message(msg)
        except Exception:
            pass

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        result = self._send_request("tools/call", {"name": tool_name, "arguments": arguments})
        content = result.get("content", [])
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif item.get("type") == "image":
                    texts.append(f"[图片: {item.get('mimeType', 'unknown')}]")
                else:
                    texts.append(str(item))
            else:
                texts.append(str(item))
        return "\n".join(texts) if texts else "(no output)"

    def get_tools(self) -> list[dict]:
        anthropic_tools = []
        for tool in self._tools:
            schema = {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("inputSchema", {
                    "type": "object", "properties": {}
                }),
            }
            anthropic_tools.append(schema)
        return anthropic_tools

    @property
    def connected(self) -> bool:
        if not self._connected:
            return False
        try:
            return self._transport.is_alive()
        except Exception:
            return True  # HTTP 传输始终 alive

    def reconnect(self) -> bool:
        self.close()
        return self.connect()

    def close(self):
        self._connected = False
        try:
            self._transport.close()
        except Exception:
            pass


class MCPManager:
    """管理多个 MCP 服务器连接，统一提供工具发现和调用。"""

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}
        self._tool_to_server: dict[str, str] = {}

    def connect_all(self, configs: dict[str, dict]) -> int:
        connected = 0
        for name, cfg in configs.items():
            transport = cfg.get("transport", "stdio")
            try:
                server = MCPServer(name=name, transport=transport, **cfg)
            except ValueError as e:
                print(f"  [MCP] '{name}' 配置错误: {e}")
                continue
            except NotImplementedError as e:
                print(f"  [MCP] '{name}': {e}")
                continue
            if server.connect():
                self._servers[name] = server
                for tool in server.get_tools():
                    self._tool_to_server[tool["name"]] = name
                tool_count = len(server.get_tools())
                info = server._server_info
                print(f"  [MCP] ✓ {name} ({info.get('name', '?')} v{info.get('version', '?')}) "
                      f"[{transport}] — {tool_count} 个工具")
                connected += 1
        return connected

    def get_all_tools(self) -> list[dict]:
        tools = []
        for server in self._servers.values():
            tools.extend(server.get_tools())
        return tools

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        server_name = self._tool_to_server.get(tool_name)
        if not server_name:
            return f"[错误] 未找到 MCP 工具: {tool_name}"
        server = self._servers.get(server_name)
        if not server:
            return f"[错误] MCP 服务器 '{server_name}' 未注册"

        if not server.connected:
            reconnected = False
            for attempt in range(2):
                try:
                    if server.reconnect():
                        for tool in server.get_tools():
                            self._tool_to_server[tool["name"]] = server_name
                        reconnected = True
                        break
                except Exception:
                    pass
            if not reconnected:
                return f"[错误] MCP 服务器 '{server_name}' 断连且重连失败"

        try:
            return server.call_tool(tool_name, arguments)
        except Exception as e:
            return f"[MCP 错误] {e}"

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._tool_to_server

    def close_all(self):
        for server in self._servers.values():
            server.close()
        self._servers.clear()
        self._tool_to_server.clear()

    @property
    def server_names(self) -> list[str]:
        return list(self._servers.keys())
