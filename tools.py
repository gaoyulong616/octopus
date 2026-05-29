"""工具定义、执行器和工作目录管理。"""

import glob as glob_module
import json
import os
import re
import shutil
import signal
import subprocess
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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
                "timeout": {"type": "integer", "description": "超时秒数，默认120", "default": 120},
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
    {
        "name": "web_search",
        "description": "搜索互联网，返回相关网页的标题、摘要和链接。"
                       "适合查询最新信息、文档、API 参考等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "最大返回结果数，默认10", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": "抓取指定 URL 的网页内容，返回纯文本。"
                       "可用于阅读搜索结果中的链接详情。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的网页 URL"},
                "max_length": {"type": "integer", "description": "返回内容的最大字符数，默认5000", "default": 5000},
            },
            "required": ["url"],
        },
    },
    {
        "name": "copy_file",
        "description": "复制文件。自动保留文件元数据（修改时间等）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源文件路径"},
                "destination": {"type": "string", "description": "目标文件路径"},
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "move_file",
        "description": "移动或重命名文件。",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源文件路径"},
                "destination": {"type": "string", "description": "目标文件路径"},
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "delete_file",
        "description": "删除文件（不能删除目录）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要删除的文件路径"},
            },
            "required": ["path"],
        },
    },
]
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


def run_bash(command: str, timeout: int = 120, output_fn=None) -> str:
    global _cwd
    try:
        proc = subprocess.Popen(
            command, shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
            preexec_fn=os.setsid, cwd=_cwd,
        )
        lines = []
        try:
            for line in proc.stdout:
                lines.append(line)
                if output_fn:
                    output_fn(line.rstrip("\n"))
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
            return f"[错误] 命令超时（{timeout}s）"
        except KeyboardInterrupt:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
            raise
        _update_cwd(command)
        output = "".join(lines).strip()
        if proc.returncode != 0:
            output += f"\n[exit code: {proc.returncode}]"
        return output or "(no output)"
    except Exception as e:
        return f"[错误] {e}"


from constants import MAX_FILE_SIZE as _MAX_FILE_SIZE


def run_read_file(path: str, encoding: str = "utf-8") -> str:
    try:
        abs_path = _abs_path(path)
        size = os.path.getsize(abs_path)
        if size > _MAX_FILE_SIZE:
            with open(abs_path, encoding=encoding) as f:
                head = f.read(5000)
            return (
                f"[警告] 文件过大 ({size / 1024:.0f}KB)，仅读取前 5000 字符\n\n{head}\n\n"
                f"... (共 {size} 字节)"
            )
        with open(abs_path, encoding=encoding) as f:
            return f.read()
    except FileNotFoundError:
        return f"[错误] 文件不存在: {path}"
    except Exception as e:
        return f"[错误] {e}"


def run_write_file(path: str, content: str, mode: str = "w") -> str:
    try:
        if len(content.encode("utf-8")) > _MAX_FILE_SIZE:
            return f"[错误] 内容过大 ({len(content)} 字符)，超过 1MB 限制"
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
# Web 工具
# ─────────────────────────────────────────────

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36")


class _DDGParser(HTMLParser):
    """解析 DuckDuckGo HTML 搜索结果页（备用）。"""

    def __init__(self):
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._in_title = False
        self._in_snippet = False
        self._current: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        cls = attr_dict.get("class", "")

        if tag == "div" and "result" in cls:
            self._in_result = True
            self._current = {}
        elif self._in_result and tag == "a":
            if "result__a" in cls:
                self._in_title = True
                href = attr_dict.get("href", "")
                if "uddg=" in href:
                    from urllib.parse import unquote
                    raw = href.split("uddg=", 1)[1].split("&", 1)[0]
                    self._current["url"] = unquote(raw)
                else:
                    self._current["url"] = href
            elif "result__snippet" in cls:
                self._in_snippet = True

    def handle_endtag(self, tag):
        if self._in_result and tag == "div":
            self._in_result = False
            if self._current.get("title"):
                self.results.append(self._current)
            self._current = {}
        if tag == "a":
            self._in_title = False
            self._in_snippet = False

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self._current["title"] = self._current.get("title", "") + text
        elif self._in_snippet:
            self._current["snippet"] = self._current.get("snippet", "") + " " + text


class _TextExtractor(HTMLParser):
    """从 HTML 中提取纯文本。"""

    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True
        elif tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self._pieces.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._pieces.append(data)

    def get_text(self) -> str:
        return " ".join("".join(self._pieces).split())


def run_web_search(query: str, max_results: int = 10) -> str:
    try:
        results: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        def _add(r: dict):
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                results.append(r)

        # 1. DuckDuckGo Instant Answer API
        try:
            ddg_url = "https://api.duckduckgo.com/?" + urlencode({
                "q": query, "format": "json", "no_redirect": 1, "no_html": 1,
            })
            ddg_req = Request(ddg_url, headers={"User-Agent": _UA})
            with urlopen(ddg_req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("AbstractText"):
                _add({
                    "title": data.get("Heading", query),
                    "snippet": data["AbstractText"],
                    "url": data.get("AbstractURL", ""),
                })
            for r in data.get("Results", []):
                _add({
                    "title": r.get("Text", "").split(" - ")[0],
                    "snippet": r.get("Text", ""),
                    "url": r.get("FirstURL", ""),
                })
            for t in data.get("RelatedTopics", []):
                if isinstance(t, dict) and "FirstURL" in t:
                    _add({
                        "title": t.get("Text", "").split(" - ")[0],
                        "snippet": t.get("Text", ""),
                        "url": t.get("FirstURL", ""),
                    })
        except Exception:
            pass

        # 2. DDG HTML 搜索（结果不足时补充）
        if len(results) < 3:
            try:
                html_url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
                html_req = Request(html_url, headers={"User-Agent": _UA})
                with urlopen(html_req, timeout=10) as resp:
                    html_data = resp.read().decode("utf-8", errors="replace")
                parser = _DDGParser()
                parser.feed(html_data)
                for r in parser.results:
                    _add(r)
                    if len(results) >= max_results:
                        break
            except Exception:
                pass

        # 3. Wikipedia 搜索（仍不足时补充）
        if len(results) < max_results:
            try:
                wiki_url = "https://en.wikipedia.org/w/api.php?" + urlencode({
                    "action": "query", "format": "json",
                    "list": "search", "srsearch": query,
                    "srlimit": max_results - len(results),
                })
                wiki_req = Request(wiki_url, headers={"User-Agent": _UA})
                with urlopen(wiki_req, timeout=10) as resp:
                    wiki_data = json.loads(resp.read().decode("utf-8"))
                for r in wiki_data.get("query", {}).get("search", []):
                    title = r.get("title", "")
                    _add({
                        "title": title,
                        "snippet": r.get("snippet", "")
                            .replace('<span class="searchmatch">', "")
                            .replace("</span>", ""),
                        "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    })
            except Exception:
                pass

        results = results[:max_results]
        if not results:
            return f"未找到与 '{query}' 相关的结果"

        lines = [f"搜索 '{query}' 找到 {len(results)} 个结果:"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            snippet = r.get("snippet", "").strip()
            link = r.get("url", "")
            lines.append(f"\n{i}. {title}")
            if snippet:
                lines.append(f"   {snippet}")
            if link:
                lines.append(f"   {link}")
        return "\n".join(lines)
    except Exception as e:
        return f"[错误] 搜索失败: {e}"


def run_web_fetch(url: str, max_length: int = 5000) -> str:
    try:
        req = Request(url, headers={"User-Agent": _UA})
        with urlopen(req, timeout=20) as resp:
            raw = resp.read()

        # 尝试从 Content-Type 获取编码
        content_type = resp.headers.get("Content-Type", "")
        encoding = "utf-8"
        if "charset=" in content_type:
            encoding = content_type.split("charset=")[1].split(";")[0].strip()

        html = raw.decode(encoding, errors="replace")

        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()

        if len(text) > max_length:
            text = text[:max_length] + f"\n... (已截断，共 {len(text)} 字符)"
        return text or "(页面无文本内容)"
    except Exception as e:
        return f"[错误] 抓取失败: {e}"


def run_copy_file(source: str, destination: str) -> str:
    try:
        src = _abs_path(source)
        dst = _abs_path(destination)
        if not os.path.exists(src):
            return f"[错误] 源文件不存在: {source}"
        if os.path.isdir(src):
            return f"[错误] 不支持复制目录: {source}"
        dst_dir = os.path.dirname(dst)
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, dst)
        return f"已复制: {source} → {destination}"
    except Exception as e:
        return f"[错误] 复制失败: {e}"


def run_move_file(source: str, destination: str) -> str:
    try:
        src = _abs_path(source)
        dst = _abs_path(destination)
        if not os.path.exists(src):
            return f"[错误] 源文件不存在: {source}"
        dst_dir = os.path.dirname(dst)
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)
        shutil.move(src, dst)
        return f"已移动: {source} → {destination}"
    except Exception as e:
        return f"[错误] 移动失败: {e}"


def run_delete_file(path: str) -> str:
    try:
        abs_path = _abs_path(path)
        if not os.path.exists(abs_path):
            return f"[错误] 文件不存在: {path}"
        if os.path.isdir(abs_path):
            return f"[错误] 不能删除目录，请使用 bash rm 命令: {path}"
        os.remove(abs_path)
        return f"已删除: {path}"
    except Exception as e:
        return f"[错误] 删除失败: {e}"


# ─────────────────────────────────────────────

TOOL_HANDLERS: dict[str, Any] = {
    "bash":       lambda inp: run_bash(inp["command"], inp.get("timeout", 120)),
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
    "web_search": lambda inp: run_web_search(inp["query"], inp.get("max_results", 10)),
    "web_fetch":  lambda inp: run_web_fetch(inp["url"], inp.get("max_length", 5000)),
    "copy_file":  lambda inp: run_copy_file(inp["source"], inp["destination"]),
    "move_file":  lambda inp: run_move_file(inp["source"], inp["destination"]),
    "delete_file": lambda inp: run_delete_file(inp["path"]),
}


def execute_tool(name: str, tool_input: dict, output_fn=None) -> str:
    if name == "bash" and output_fn:
        return run_bash(
            tool_input["command"],
            tool_input.get("timeout", 30),
            output_fn=output_fn,
        )
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return f"[错误] 未知工具: {name}"
    return handler(tool_input)
