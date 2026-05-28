"""MCP (Model Context Protocol) 客户端：连接外部工具服务器。"""

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any


class MCPServer:
    """与单个 MCP 服务器的连接，使用 stdio 传输。"""

    def __init__(self, name: str, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, cwd: str | None = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self._proc: subprocess.Popen | None = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._tools: list[dict] = []
        self._server_info: dict = {}
        self._connected = False

    def connect(self) -> bool:
        """启动 MCP 服务器子进程并完成握手。"""
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
            print(f"  [MCP] 服务器 '{self.name}' 命令未找到: {self.command}")
            return False
        except Exception as e:
            print(f"  [MCP] 启动服务器 '{self.name}' 失败: {e}")
            return False

        # 启动 stderr 监听线程（防止 stderr 缓冲区满导致阻塞）
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True
        )
        self._stderr_thread.start()

        # 初始化握手
        try:
            result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "octopus-agent", "version": "1.0.0"},
            })
            self._server_info = result.get("serverInfo", {})

            # 发送 initialized 通知
            self._send_notification("notifications/initialized", None)

            # 获取工具列表
            tools_result = self._send_request("tools/list", None)
            self._tools = tools_result.get("tools", [])
            self._connected = True
            return True
        except Exception as e:
            print(f"  [MCP] 服务器 '{self.name}' 握手失败: {e}")
            self.close()
            return False

    def _drain_stderr(self):
        """持续读取 stderr，防止缓冲区满。"""
        if self._proc and self._proc.stderr:
            try:
                for line in self._proc.stderr:
                    pass
            except Exception:
                pass

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _write_message(self, message: dict):
        """按 MCP stdio 格式发送消息（Content-Length 头）。"""
        body = json.dumps(message, ensure_ascii=False)
        header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(header.encode("utf-8"))
            self._proc.stdin.write(body.encode("utf-8"))
            self._proc.stdin.flush()

    def _read_message(self) -> dict:
        """按 MCP stdio 格式读取消息（Content-Length 头）。"""
        if not self._proc or not self._proc.stdout:
            raise ConnectionError("进程未启动")

        # 读取 Content-Length 行
        header_lines = []
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise ConnectionError("服务器关闭连接")
            decoded = line.decode("utf-8").strip()
            if decoded == "":
                break
            header_lines.append(decoded)

        # 解析 Content-Length
        content_length = 0
        for hl in header_lines:
            if hl.lower().startswith("content-length:"):
                content_length = int(hl.split(":", 1)[1].strip())
                break

        if content_length == 0:
            raise ConnectionError("无效的消息头")

        # 读取消息体
        body = self._proc.stdout.read(content_length)
        if not body:
            raise ConnectionError("服务器关闭连接")
        return json.loads(body.decode("utf-8"))

    def _send_request(self, method: str, params: Any) -> dict:
        """发送 JSON-RPC 请求并等待响应。"""
        with self._lock:
            msg = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": method,
            }
            if params is not None:
                msg["params"] = params
            self._write_message(msg)

            # 读取响应，跳过通知
            while True:
                response = self._read_message()
                if "id" in response and response["id"] == msg["id"]:
                    break
                # 跳过通知消息

        if "error" in response:
            err = response["error"]
            raise RuntimeError(f"MCP 错误 [{err.get('code')}]: {err.get('message')}")

        return response.get("result", {})

    def _send_notification(self, method: str, params: Any):
        """发送 JSON-RPC 通知（无 id，不等待响应）。"""
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._write_message(msg)

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """调用 MCP 服务器上的工具。"""
        result = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        # MCP 返回 content 数组，提取文本
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
        """获取此服务器提供的工具列表（转为 Anthropic tool schema 格式）。"""
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
        return self._connected and self._proc is not None and self._proc.poll() is None

    def close(self):
        """关闭连接，终止子进程。"""
        self._connected = False
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


class MCPManager:
    """管理多个 MCP 服务器连接，统一提供工具发现和调用。"""

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}
        # 工具名 → 服务器名 的映射
        self._tool_to_server: dict[str, str] = {}

    def connect_all(self, configs: dict[str, dict]) -> int:
        """连接所有配置的 MCP 服务器，返回成功连接数。"""
        connected = 0
        for name, cfg in configs.items():
            server = MCPServer(
                name=name,
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
                cwd=cfg.get("cwd"),
            )
            if server.connect():
                self._servers[name] = server
                # 注册工具映射
                for tool in server.get_tools():
                    self._tool_to_server[tool["name"]] = name
                tool_count = len(server.get_tools())
                info = server._server_info
                print(f"  [MCP] ✓ {name} ({info.get('name', '?')} v{info.get('version', '?')}) "
                      f"— {tool_count} 个工具")
                connected += 1
        return connected

    def get_all_tools(self) -> list[dict]:
        """获取所有 MCP 服务器提供的工具（Anthropic schema 格式）。"""
        tools = []
        for server in self._servers.values():
            tools.extend(server.get_tools())
        return tools

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """调用 MCP 工具，自动路由到正确的服务器。"""
        server_name = self._tool_to_server.get(tool_name)
        if not server_name:
            return f"[错误] 未找到 MCP 工具: {tool_name}"
        server = self._servers.get(server_name)
        if not server or not server.connected:
            return f"[错误] MCP 服务器 '{server_name}' 未连接"
        try:
            return server.call_tool(tool_name, arguments)
        except Exception as e:
            return f"[MCP 错误] {e}"

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._tool_to_server

    def close_all(self):
        """关闭所有连接。"""
        for server in self._servers.values():
            server.close()
        self._servers.clear()
        self._tool_to_server.clear()

    @property
    def server_names(self) -> list[str]:
        return list(self._servers.keys())
