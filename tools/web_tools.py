"""Web 工具：搜索互联网、抓取网页内容。"""

import json
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tools.exceptions import ToolError


_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36")


def _build_safe_opener():
    """构建检查重定向目标的 URL opener，防止 SSRF via redirect。"""
    from urllib.request import build_opener, HTTPRedirectHandler
    from tools.security import is_internal_url

    class _SafeRedirectHandler(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if is_internal_url(newurl):
                raise ToolError(f"重定向到内网地址被阻止: {newurl}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return build_opener(_SafeRedirectHandler)


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
        raise ToolError(f"搜索失败: {e}")


def run_web_fetch(url: str, max_length: int = 5000) -> str:
    try:
        from tools.security import is_internal_url, resolve_and_check
        if is_internal_url(url):
            raise ToolError(f"不允许访问内网地址: {url}")

        # 二次校验：在实际发请求前再解析一次 DNS，防止 DNS rebinding
        internal_ip = resolve_and_check(url)
        if internal_ip:
            raise ToolError(f"不允许访问内网地址: {url} (resolved: {internal_ip})")

        req = Request(url, headers={"User-Agent": _UA})
        opener = _build_safe_opener()
        with opener.open(req, timeout=20) as resp:
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
        raise ToolError(f"抓取失败: {e}")
