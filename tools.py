"""工具定义、执行器和工作目录管理。"""

import glob as glob_module
import os
import re
import signal
import subprocess
from typing import Any

# ─────────────────────────────────────────────
# 工作目录持久化
# ─────────────────────────────────────────────

_cwd: str = os.getcwd()


def get_cwd() -> str:
    return _cwd


def set_cwd(path: str):
    global _cwd
    _cwd = path


# ─────────────────────────────────────────────
# 工具 Schema 定义
# ─────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "bash",
        "description": "在 shell 中执行命令。可用于文件操作、运行程序、安装包等。"
                       "工作目录会在调用之间持久化。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "timeout": {"type": "integer", "description": "超时秒数，默认30", "default": 30},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "读取本地文件内容。支持文本文件。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "encoding": {"type": "string", "description": "编码，默认utf-8", "default": "utf-8"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "将内容写入本地文件。目录不存在时自动创建。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "写入内容"},
                "mode": {"type": "string", "description": "'w'覆盖(默认) 或 'a'追加", "default": "w"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "对文件进行精确的字符串替换编辑。通过 old_string 定位要修改的位置，"
                       "替换为 new_string。如果 old_string 在文件中出现多次，必须提供足够的"
                       "上下文使其唯一，或者设置 replace_all=true 替换所有匹配。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "old_string": {"type": "string", "description": "要被替换的原始文本（必须精确匹配）"},
                "new_string": {"type": "string", "description": "替换后的新文本"},
                "replace_all": {"type": "boolean", "description": "是否替换所有匹配项，默认false", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_files",
        "description": "列出目录中的文件和子目录。支持 glob 模式匹配和递归搜索。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径，默认为当前工作目录", "default": "."},
                "pattern": {"type": "string", "description": "glob 匹配模式，如 '*.py'、'**/*.js'。不设置则列出所有文件", "default": ""},
                "recursive": {"type": "boolean", "description": "是否递归搜索子目录，默认false", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "grep_search",
        "description": "在文件中搜索文本或正则表达式。类似 grep 命令，返回匹配的文件名、"
                       "行号和匹配内容。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索模式（文本或正则表达式）"},
                "path": {"type": "string", "description": "搜索路径，默认为当前工作目录", "default": "."},
                "include": {"type": "string", "description": "只搜索匹配此 glob 模式的文件，如 '*.py'", "default": ""},
                "max_results": {"type": "integer", "description": "最大返回结果数，默认50", "default": 50},
            },
            "required": ["pattern"],
        },
    },
]

# ─────────────────────────────────────────────
# 工具执行器
# ─────────────────────────────────────────────

def _update_cwd(command: str):
    """追踪 bash 命令中的 cd 操作，持久化工作目录。"""
    global _cwd
    stripped = command.strip()
    for part in stripped.split("&&"):
        part = part.strip()
        if part.startswith("cd "):
            target = part[3:].strip().strip("\"'")
            if target == "":
                _cwd = os.path.expanduser("~")
            else:
                new_dir = os.path.expanduser(target)
                if not os.path.isabs(new_dir):
                    new_dir = os.path.normpath(os.path.join(_cwd, new_dir))
                if os.path.isdir(new_dir):
                    _cwd = new_dir


def _abs_path(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_cwd, path)


def run_bash(command: str, timeout: int = 30) -> str:
    global _cwd
    try:
        proc = subprocess.Popen(
            command, shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, preexec_fn=os.setsid,
            cwd=_cwd,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
            return f"[错误] 命令超时（{timeout}s）"
        except KeyboardInterrupt:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
            raise
        _update_cwd(command)
        output = ""
        if stdout:
            output += stdout
        if stderr:
            output += f"\n[stderr]\n{stderr}"
        if proc.returncode != 0:
            output += f"\n[exit code: {proc.returncode}]"
        return output.strip() or "(no output)"
    except Exception as e:
        return f"[错误] {e}"


def run_read_file(path: str, encoding: str = "utf-8") -> str:
    try:
        with open(_abs_path(path), encoding=encoding) as f:
            return f.read()
    except FileNotFoundError:
        return f"[错误] 文件不存在: {path}"
    except Exception as e:
        return f"[错误] {e}"


def run_write_file(path: str, content: str, mode: str = "w") -> str:
    try:
        abs_path = _abs_path(path)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        with open(abs_path, mode, encoding="utf-8") as f:
            f.write(content)
        return f"✓ 已写入 {path}（{len(content)} 字符）"
    except Exception as e:
        return f"[错误] {e}"


def run_edit_file(path: str, old_string: str, new_string: str,
                  replace_all: bool = False) -> str:
    try:
        abs_path = _abs_path(path)
        with open(abs_path, encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            return f"[错误] 未在 {path} 中找到要替换的文本"
        if count > 1 and not replace_all:
            return (f"[错误] 要替换的文本在 {path} 中出现 {count} 次，"
                    "请提供更多上下文使其唯一，或设置 replace_all=true")

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"✓ 已编辑 {path}（替换了 {count} 处）"
    except FileNotFoundError:
        return f"[错误] 文件不存在: {path}"
    except Exception as e:
        return f"[错误] {e}"


def run_list_files(path: str = ".", pattern: str = "", recursive: bool = False) -> str:
    try:
        target = _abs_path(path)
        if not os.path.isdir(target):
            return f"[错误] 目录不存在: {path}"

        if pattern:
            if recursive:
                matches = glob_module.glob(
                    os.path.join(target, "**", pattern), recursive=True
                )
            else:
                matches = glob_module.glob(os.path.join(target, pattern))
            results = []
            for m in sorted(matches):
                rel = os.path.relpath(m, _cwd)
                if os.path.isdir(m):
                    rel += "/"
                results.append(rel)
            if not results:
                return f"在 {path} 中未找到匹配 '{pattern}' 的文件"
            return "\n".join(results)
        else:
            entries = sorted(os.listdir(target))
            results = []
            for entry in entries:
                if os.path.isdir(os.path.join(target, entry)):
                    results.append(f"{entry}/")
                else:
                    results.append(entry)
            if not results:
                return f"目录 {path} 为空"
            return "\n".join(results)
    except Exception as e:
        return f"[错误] {e}"


def run_grep_search(pattern: str, path: str = ".", include: str = "",
                    max_results: int = 50) -> str:
    try:
        target = _abs_path(path)
        try:
            regex = re.compile(pattern)
        except re.error:
            return f"[错误] 无效的正则表达式: {pattern}"

        results = []
        if os.path.isfile(target):
            files = [target]
        else:
            if include:
                files = glob_module.glob(
                    os.path.join(target, "**", include), recursive=True
                )
            else:
                files = glob_module.glob(
                    os.path.join(target, "**", "*"), recursive=True
                )
            files = [f for f in files if os.path.isfile(f)]

        for filepath in sorted(files):
            try:
                with open(filepath, encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = os.path.relpath(filepath, _cwd)
                            results.append(f"{rel}:{line_no}: {line.rstrip()}")
                            if len(results) >= max_results:
                                break
            except (PermissionError, OSError):
                continue
            if len(results) >= max_results:
                break

        if not results:
            return f"在 {path} 中未找到匹配 '{pattern}' 的内容"
        header = f"找到 {len(results)} 个结果"
        if len(results) >= max_results:
            header += f"（已截断，最多显示 {max_results} 个）"
        return header + "\n" + "\n".join(results)
    except Exception as e:
        return f"[错误] {e}"


# ─────────────────────────────────────────────
# 工具注册表
# ─────────────────────────────────────────────

TOOL_HANDLERS: dict[str, Any] = {
    "bash":       lambda inp: run_bash(inp["command"], inp.get("timeout", 30)),
    "read_file":  lambda inp: run_read_file(inp["path"], inp.get("encoding", "utf-8")),
    "write_file": lambda inp: run_write_file(inp["path"], inp["content"], inp.get("mode", "w")),
    "edit_file":  lambda inp: run_edit_file(
                      inp["path"], inp["old_string"],
                      inp["new_string"], inp.get("replace_all", False)),
    "list_files": lambda inp: run_list_files(
                      inp.get("path", "."), inp.get("pattern", ""),
                      inp.get("recursive", False)),
    "grep_search": lambda inp: run_grep_search(
                       inp["pattern"], inp.get("path", "."),
                       inp.get("include", ""), inp.get("max_results", 50)),
}


def execute_tool(name: str, tool_input: dict) -> str:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return f"[错误] 未知工具: {name}"
    return handler(tool_input)
