"""知识库图谱 API：扫描 md 文档，解析 frontmatter + 双链，返回 G6 图数据。"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Query, Request

from config import get as config_get

router = APIRouter(prefix="/api/kb")

_WIKI_LINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:\|[^\]]*)?(?:#[^\]]*)?\]\]")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_MD_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_MAX_FILES = 500
_MAX_FILE_BYTES = 1024 * 1024  # 单文件 1MB 截断


def _resolve_kb_root() -> Path | None:
    root = config_get("kb_directory")
    if not root:
        return None
    p = Path(root).expanduser()
    if not p.is_dir():
        return None
    return p.resolve()


def _safe_join(root: Path, rel: str) -> Path:
    """安全拼接路径，禁止越界。"""
    candidate = (root / rel).resolve()
    if root != candidate and root not in candidate.parents:
        raise HTTPException(status_code=400, detail="invalid path")
    return candidate


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """返回 (frontmatter_dict, body_text)。无 frontmatter 时 dict 为空。"""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_meta, body = m.group(1), m.group(2)
    try:
        meta = yaml.safe_load(raw_meta) or {}
        if not isinstance(meta, dict):
            meta = {}
    except yaml.YAMLError:
        meta = {}
    return meta, body


def _extract_title(meta: dict[str, Any], body: str, fallback: str) -> str:
    if isinstance(meta.get("title"), str) and meta["title"].strip():
        return meta["title"].strip()
    m = _MD_TITLE_RE.search(body)
    if m:
        return m.group(1).strip()
    return fallback


def _extract_wiki_links(body: str) -> list[str]:
    return [g.strip() for g in _WIKI_LINK_RE.findall(body) if g.strip()]


def _strip_md_for_summary(body: str, max_len: int = 240) -> str:
    """粗暴去 markdown 标记，取摘要。"""
    s = body
    s = re.sub(r"```[\s\S]*?```", " ", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", s)
    s = re.sub(r"\[\[([^\]\|#]+)[^\]]*\]\]", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^#{1,6}\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*[-*+]\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*\|.*\|\s*$", "", s, flags=re.MULTILINE)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len] + ("…" if len(s) > max_len else "")


def _scan_documents(root: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(raw) > _MAX_FILE_BYTES:
            raw = raw[:_MAX_FILE_BYTES]
        meta, body = _parse_frontmatter(raw)
        rel = path.relative_to(root).as_posix()
        title = _extract_title(meta, body, path.stem)
        category = meta.get("category") or _infer_category(rel)
        docs.append({
            "id": rel,
            "path": rel,
            "title": title,
            "category": str(category) if category else "Other",
            "tags": _normalize_tags(meta.get("tags")),
            "status": meta.get("status") or None,
            "updated": meta.get("updated") or None,
            "created": meta.get("created") or None,
            "summary": _strip_md_for_summary(body),
            "wiki_links": _extract_wiki_links(body),
            "size": path.stat().st_size,
        })
        if len(docs) >= _MAX_FILES:
            break
    return docs


def _infer_category(rel_path: str) -> str:
    top = rel_path.split("/", 1)[0] if "/" in rel_path else "Root"
    return top.capitalize()


def _normalize_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [t.strip() for t in re.split(r"[,;\s]+", raw) if t.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(t).strip() for t in raw if str(t).strip()]
    return []


def _build_graph(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """构造节点 + 边。边类型：wiki（双链）、tag（共同 tag）。"""
    by_lower_title: dict[str, dict[str, Any]] = {}
    by_stem: dict[str, dict[str, Any]] = {}
    for d in docs:
        by_lower_title.setdefault(d["title"].lower(), d)
        by_stem.setdefault(Path(d["path"]).stem.lower(), d)

    nodes = [{
        "id": d["id"],
        "label": d["title"],
        "category": d["category"],
        "tags": d["tags"],
        "status": d["status"],
        "updated": d["updated"],
        "summary": d["summary"],
        "path": d["path"],
        "size": d["size"],
    } for d in docs]

    edges: list[dict[str, Any]] = []
    # 同一对节点（无向）只保留一条边：wiki 优先于 tag
    pair_to_edge: dict[tuple[str, str], dict[str, Any]] = {}

    def _pair_key(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    def _add_edge(src: str, tgt: str, kind: str, label: str):
        if src == tgt:
            return
        key = _pair_key(src, tgt)
        existing = pair_to_edge.get(key)
        if existing:
            # wiki 优先；同 kind 时不覆盖（保留第一条）
            if kind == "wiki" and existing["kind"] != "wiki":
                pair_to_edge[key] = {"source": src, "target": tgt, "kind": kind, "label": label}
            return
        pair_to_edge[key] = {"source": src, "target": tgt, "kind": kind, "label": label}

    # 双链关系
    for d in docs:
        for link in d["wiki_links"]:
            target = by_lower_title.get(link.lower()) or by_stem.get(link.lower())
            if target:
                _add_edge(d["id"], target["id"], "wiki", "引用")

    # 共同 tag 关系（避免 O(n²)：只对每个 tag 做分组）
    tag_groups: dict[str, list[dict[str, Any]]] = {}
    for d in docs:
        for t in d["tags"]:
            tag_groups.setdefault(t.lower(), []).append(d)
    for tag, group in tag_groups.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                _add_edge(group[i]["id"], group[j]["id"], "tag", f"#{tag}")

    edges = list(pair_to_edge.values())

    return {"nodes": nodes, "edges": edges}


@router.get("/graph")
async def get_graph(request: Request):
    root = _resolve_kb_root()
    if not root:
        raise HTTPException(status_code=404, detail="kb_directory 未配置或目录不存在")
    docs = _scan_documents(root)
    graph = _build_graph(docs)
    return {
        "root": str(root),
        "count": len(docs),
        "nodes": graph["nodes"],
        "edges": graph["edges"],
    }


@router.get("/doc")
async def get_doc(
    request: Request,
    path: str = Query(..., description="相对 kb_directory 的 md 路径"),
):
    root = _resolve_kb_root()
    if not root:
        raise HTTPException(status_code=404, detail="kb_directory 未配置")
    full = _safe_join(root, path)
    if not full.is_file() or full.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail="文件不存在")
    raw = full.read_text(encoding="utf-8", errors="replace")
    if len(raw) > _MAX_FILE_BYTES:
        raw = raw[:_MAX_FILE_BYTES]
    meta, body = _parse_frontmatter(raw)
    return {
        "path": path,
        "meta": meta,
        "content": body,
    }
