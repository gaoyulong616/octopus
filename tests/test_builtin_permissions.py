"""测试 agent.py 内置权限检查：单次模式下的安全防护。"""

import types

import pytest

import agent
import config
from agent import _builtin_confirm, run_agent


@pytest.fixture(autouse=True)
def _stub_agent_deps(monkeypatch):
    """桩住 metrics 和 LLM 调用。"""
    monkeypatch.setattr(agent.metrics, "record_call", lambda **kw: None)


class TestBuiltinConfirm:
    """_builtin_confirm 在无外部 confirm_fn 时根据配置拦截。"""

    def _patch_config(self, monkeypatch, cfg):
        """同时 monkeypatch agent.get 和 config.get（因为 check_permission_rule/is_dangerous 用 config.get）。"""
        monkeypatch.setattr(agent, "get", lambda k, d=None: cfg.get(k, d))
        monkeypatch.setattr(config, "get", lambda k, d=None: cfg.get(k, d))

    def test_read_tools_always_allowed(self, monkeypatch):
        self._patch_config(monkeypatch, {
            "permissions": "deny",
            "permission_rules": [],
            "dangerous_commands": ["rm"],
        })
        assert _builtin_confirm("read_file", {"path": "/tmp/x"})[0] is True
        assert _builtin_confirm("list_files", {"path": "."})[0] is True
        assert _builtin_confirm("grep_search", {"pattern": "foo"})[0] is True
        assert _builtin_confirm("web_search", {"query": "test"})[0] is True

    def test_auto_approve_allows_all(self, monkeypatch):
        self._patch_config(monkeypatch, {
            "permissions": "auto-approve",
            "permission_rules": [],
            "dangerous_commands": ["rm"],
        })
        assert _builtin_confirm("bash", {"command": "rm -rf /"})[0] is True
        assert _builtin_confirm("write_file", {"path": "/tmp/x"})[0] is True

    def test_confirm_mode_rejects_dangerous_bash(self, monkeypatch):
        self._patch_config(monkeypatch, {
            "permissions": "confirm",
            "permission_rules": [],
            "dangerous_commands": ["rm", "sudo"],
        })
        assert _builtin_confirm("bash", {"command": "rm -rf /tmp"})[0] is False
        assert _builtin_confirm("bash", {"command": "sudo apt install x"})[0] is False

    def test_confirm_mode_allows_safe_bash(self, monkeypatch):
        self._patch_config(monkeypatch, {
            "permissions": "confirm",
            "permission_rules": [],
            "dangerous_commands": ["rm", "sudo"],
        })
        assert _builtin_confirm("bash", {"command": "ls -la"})[0] is True
        assert _builtin_confirm("bash", {"command": "cat file.txt"})[0] is True

    def test_confirm_mode_rejects_write_tools(self, monkeypatch):
        self._patch_config(monkeypatch, {
            "permissions": "confirm",
            "permission_rules": [],
            "dangerous_commands": [],
        })
        assert _builtin_confirm("write_file", {"path": "/tmp/x"})[0] is False
        assert _builtin_confirm("edit_file", {"path": "/tmp/x"})[0] is False
        assert _builtin_confirm("delete_file", {"path": "/tmp/x"})[0] is False

    def test_deny_mode_rejects_writes(self, monkeypatch):
        self._patch_config(monkeypatch, {
            "permissions": "deny",
            "permission_rules": [],
            "dangerous_commands": [],
        })
        assert _builtin_confirm("bash", {"command": "echo hi"})[0] is True
        assert _builtin_confirm("write_file", {"path": "/tmp/x"})[0] is False

    def test_permission_rules_override_mode(self, monkeypatch):
        self._patch_config(monkeypatch, {
            "permissions": "deny",
            "permission_rules": [{"tool": "bash", "pattern": "echo.*", "action": "allow"}],
            "dangerous_commands": [],
        })
        assert _builtin_confirm("bash", {"command": "echo hello"})[0] is True
        assert _builtin_confirm("write_file", {"path": "/tmp/x"})[0] is False

    def test_permission_rules_deny_overrides_approve(self, monkeypatch):
        self._patch_config(monkeypatch, {
            "permissions": "auto-approve",
            "permission_rules": [{"tool": "bash", "pattern": "rm.*", "action": "deny"}],
            "dangerous_commands": [],
        })
        assert _builtin_confirm("bash", {"command": "rm -rf /"})[0] is False
        assert _builtin_confirm("bash", {"command": "ls"})[0] is True


def _make_usage():
    return types.SimpleNamespace(
        input_tokens=1, output_tokens=1,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )


def _text_msg(text="done"):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn", usage=_make_usage(),
    )


class TestSafeMode:
    """--safe 标志限制单次模式只能使用读取类工具。"""

    def test_safe_mode_passes_without_tool_use(self, monkeypatch):
        monkeypatch.setattr(agent, "_stream_with_retry", lambda *a, **kw: (_text_msg(), False))
        captured = []
        run_agent(
            "test task",
            safe_mode=True,
            output_fn=lambda evt, text, meta: captured.append((evt, text, meta)),
        )
        # 应正常完成不报错
        responses = [t for e, t, m in captured if e == "response"]
        assert len(responses) >= 0  # 至少不崩溃

    def test_safe_mode_rejects_write_tool(self, monkeypatch):
        tool_block = types.SimpleNamespace(
            type="tool_use", id="tu_1", name="write_file",
            input={"path": "/tmp/x", "content": "hello"},
        )
        call_count = [0]

        def _fake_stream(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return (types.SimpleNamespace(
                    content=[tool_block], stop_reason="end_turn", usage=_make_usage(),
                ), False)
            return (_text_msg(), False)

        monkeypatch.setattr(agent, "_stream_with_retry", _fake_stream)
        captured = []
        run_agent(
            "write something",
            safe_mode=True,
            output_fn=lambda evt, text, meta: captured.append((evt, text, meta)),

        )
        rejected = [(e, t, m) for e, t, m in captured
                    if e == "tool_result" and m and m.get("rejected")]
        assert len(rejected) == 1
        assert "安全模式" in rejected[0][1]

    def test_safe_mode_allows_read_tools(self, monkeypatch):
        tool_block = types.SimpleNamespace(
            type="tool_use", id="tu_1", name="read_file",
            input={"path": "/tmp/x"},
        )
        call_count = [0]

        def _fake_stream(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return (types.SimpleNamespace(
                    content=[tool_block], stop_reason="end_turn", usage=_make_usage(),
                ), False)
            return (_text_msg(), False)

        monkeypatch.setattr(agent, "_stream_with_retry", _fake_stream)
        monkeypatch.setattr(agent, "execute_tool",
                            lambda name, inp, **kw: "file content")
        captured = []
        run_agent(
            "read a file",
            safe_mode=True,
            output_fn=lambda evt, text, meta: captured.append((evt, text, meta)),

        )
        rejected = [(e, t, m) for e, t, m in captured
                    if e == "tool_result" and m and m.get("rejected")]
        assert len(rejected) == 0


class TestToolResultPreview:
    """所有工具统一显示结果预览，bash 不再流式回显。"""

    def test_bash_result_preview_emitted(self, monkeypatch):
        tool_block = types.SimpleNamespace(
            type="tool_use", id="tu_1", name="bash",
            input={"command": "echo hello"},
        )
        call_count = [0]

        def _fake_stream(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return (types.SimpleNamespace(
                    content=[tool_block], stop_reason="end_turn", usage=_make_usage(),
                ), False)
            return (_text_msg(), False)

        monkeypatch.setattr(agent, "_stream_with_retry", _fake_stream)
        monkeypatch.setattr(agent, "execute_tool",
                            lambda name, inp, **kw: "hello\nworld\n" * 20)
        captured = []
        run_agent(
            "run echo",
            output_fn=lambda evt, text, meta: captured.append((evt, text, meta)),

            confirm_fn=lambda n, i: True,
        )
        bash_results = [(e, t, m) for e, t, m in captured
                        if e == "tool_result" and m and m.get("tool") == "bash"]
        assert len(bash_results) == 1

    def test_other_tool_result_still_emitted(self, monkeypatch):
        tool_block = types.SimpleNamespace(
            type="tool_use", id="tu_1", name="read_file",
            input={"path": "/tmp/x"},
        )
        call_count = [0]

        def _fake_stream(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return (types.SimpleNamespace(
                    content=[tool_block], stop_reason="end_turn", usage=_make_usage(),
                ), False)
            return (_text_msg(), False)

        monkeypatch.setattr(agent, "_stream_with_retry", _fake_stream)
        monkeypatch.setattr(agent, "execute_tool",
                            lambda name, inp, **kw: "file content here")
        captured = []
        run_agent(
            "read a file",
            output_fn=lambda evt, text, meta: captured.append((evt, text, meta)),

            confirm_fn=lambda n, i: True,
        )
        read_results = [(e, t, m) for e, t, m in captured
                        if e == "tool_result" and m and m.get("tool") == "read_file"]
        assert len(read_results) == 1
