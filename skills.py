"""自定义 Agents 和 Skills：加载、渲染、管理。

对标 Claude Code 的 skill 系统设计，提供：
- 多级目录扫描（全局 / 个人 / 项目），高优先级覆盖低优先级
- 带 mtime 校验的缓存，避免重复读盘
- 增强的 frontmatter 解析（类型推断、列表、嵌套属性）
- 参数验证（必填检查、默认值、类型提示）
- 内置模板变量（{{cwd}}、{{date}}、{{user}} 等）
- skill 搜索 / 发现
- 错误信息包含来源路径，便于定位问题
"""

from __future__ import annotations

import datetime
import glob as glob_module
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────

@dataclass
class SkillArg:
    """Skill / Agent 的参数定义。"""
    name: str
    description: str = ""
    required: bool = False
    default: str = ""


@dataclass
class AgentDef:
    """一个自定义 Agent 定义，对标 SkillDef 的元数据体系。"""
    name: str
    description: str = ""
    content: str = ""
    source: str = ""
    # ── 扩展元数据（来自 frontmatter） ──
    extends: str = ""                                              # 继承的父 agent 名称
    arguments: list[SkillArg] = field(default_factory=list)      # 参数定义
    allowed_tools: list[str] = field(default_factory=list)      # 工具白名单（仅允许这些工具）
    restricted_tools: list[str] = field(default_factory=list)   # 工具黑名单（禁止这些工具）
    context_patterns: list[str] = field(default_factory=list)   # 上下文文件 glob 模式
    tags: list[str] = field(default_factory=list)               # 分类标签
    version: str = ""                                           # 语义版本
    scope: str = ""                                             # 来源层级: global/personal/project
    license: str = ""                                           # 许可协议


@dataclass
class SkillDef:
    """一个 Skill 定义，对标 Claude Code 的 skill metadata。"""
    name: str
    description: str = ""
    arguments: list[SkillArg] = field(default_factory=list)
    content: str = ""
    source: str = ""
    # ── 扩展元数据（来自 frontmatter） ──
    allowed_tools: list[str] = field(default_factory=list)   # 推荐工具白名单
    dependencies: list[str] = field(default_factory=list)    # 依赖的其他 skill
    license: str = ""                                        # 许可协议
    version: str = ""                                        # 语义版本
    tags: list[str] = field(default_factory=list)            # 分类标签
    scope: str = ""                                          # 来源层级: global/personal/project


# ─────────────────────────────────────────────
# 缓存：避免每次调用都读盘
# ─────────────────────────────────────────────

_cache: dict[str, Any] = {
    "agents": None,
    "skills": None,
    "mtime": 0.0,
    "ttl": 5.0,
    "agents_dir_mtime": 0.0,
    "skills_dir_mtime": 0.0,
}


def invalidate_cache() -> None:
    """强制下一次 load 重新读盘。"""
    _cache["agents"] = None
    _cache["skills"] = None
    _cache["mtime"] = 0.0
    _cache["agents_dir_mtime"] = 0.0
    _cache["skills_dir_mtime"] = 0.0


def _dirs_mtime(dirs: list[tuple[str, str]]) -> float:
    """获取目录列表中最新的文件 mtime（用于热重载检测）。"""
    latest = 0.0
    for directory, _scope in dirs:
        if not os.path.isdir(directory):
            continue
        try:
            for entry in os.scandir(directory):
                if entry.is_file() and entry.name.endswith(".md"):
                    try:
                        latest = max(latest, entry.stat().st_mtime)
                    except OSError:
                        pass
        except OSError:
            pass
    return latest


def _cache_fresh() -> bool:
    """缓存时间戳是否仍在 TTL 内。"""
    return time.time() - _cache["mtime"] <= _cache["ttl"]


# ─────────────────────────────────────────────
# 目录扫描
# ─────────────────────────────────────────────

def _scan_md_files(*dirs: str) -> dict[str, tuple[str, str]]:
    """扫描多个目录下的 .md 文件，后扫描的覆盖先扫描的。

    约定：
    - 跳过以 _ 开头的文件（内部 / 模板文件）
    - 跳过 README.md（文档而非 skill 定义）
    - 返回 {name: (abs_path, content)}
    """
    found: dict[str, tuple[str, str]] = {}
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        for filepath in sorted(glob_module.glob(os.path.join(directory, "*.md"))):
            name = os.path.splitext(os.path.basename(filepath))[0]
            if name.startswith("_") or name.upper() == "README":
                continue
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()
                found[name] = (os.path.abspath(filepath), content)
            except OSError:
                continue
    return found


# ─────────────────────────────────────────────
# Frontmatter 解析（增强版）
# ─────────────────────────────────────────────

def _coerce_value(raw: str) -> Any:
    """将字符串值推断为合适的 Python 类型。"""
    s = raw.strip().strip('"').strip("'")
    if not s:
        return ""
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    # 逗号分隔列表： "a, b, c" -> ["a", "b", "c"]
    if "," in s and not s.startswith("["):
        return [x.strip() for x in s.split(",") if x.strip()]
    return s


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 Markdown frontmatter（--- 包裹的 YAML 子集）。

    支持：
    - 标量 key: value（自动类型推断）
    - 列表（- item 或 - key: value 带缩进属性）
    - 内联列表 [a, b, c]

    返回 (metadata_dict, body_content)。
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    raw_meta = parts[1].strip()
    body = parts[2].strip()

    meta: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list | None = None

    for line in raw_meta.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # 顶层 key: value（非缩进行）
        top_match = re.match(r"^([\w-]+):\s*(.*)", stripped)
        if top_match and not line.startswith(" ") and not line.startswith("\t"):
            key, val = top_match.groups()
            current_key = key
            current_list = None

            val_stripped = val.strip()
            # 内联列表 [a, b, c]
            if val_stripped.startswith("[") and val_stripped.endswith("]"):
                inner = val_stripped[1:-1]
                meta[key] = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
            elif val_stripped:
                meta[key] = _coerce_value(val_stripped)
            elif key in ("arguments", "dependencies", "allowed_tools", "tags"):
                meta[key] = []
                current_list = meta[key]
            else:
                meta[key] = ""
            continue

        # 列表项
        if stripped.startswith("- ") and current_list is not None:
            item_body = stripped[2:].strip()
            # - key: value 形式
            item_match = re.match(r"^([\w-]+):\s*(.*)", item_body)
            if item_match:
                item = {item_match.group(1): _coerce_value(item_match.group(2))}
                current_list.append(item)
            else:
                # 纯 - value 形式
                current_list.append(_coerce_value(item_body))
            continue

        # 缩进属性行（属于上一个列表项）
        if (line.startswith("  ") or line.startswith("\t")) and current_list and current_key:
            attr_match = re.match(r"^\s+([\w-]+):\s*(.*)", line)
            if attr_match and current_list and isinstance(current_list[-1], dict):
                k, v = attr_match.groups()
                current_list[-1][k] = _coerce_value(v)

    return meta, body


# ─────────────────────────────────────────────
# 目录层级
# ─────────────────────────────────────────────

def _skill_dirs() -> list[tuple[str, str]]:
    """返回 [(dir_path, scope_label), ...]，按优先级从低到高。"""
    home = str(Path.home())
    cwd = os.getcwd()
    return [
        (os.path.join(home, ".config", "octopus", "skills"), "global"),
        (os.path.join(home, ".skills"), "personal"),
        (os.path.join(cwd, ".skills"), "project"),
    ]


def _agent_dirs() -> list[tuple[str, str]]:
    home = str(Path.home())
    cwd = os.getcwd()
    return [
        (os.path.join(home, ".config", "octopus", "agents"), "global"),
        (os.path.join(home, ".agents"), "personal"),
        (os.path.join(cwd, ".agents"), "project"),
    ]


# ─────────────────────────────────────────────
# 加载
# ─────────────────────────────────────────────

def _as_list(val: Any) -> list[str]:
    """将 frontmatter 值转为字符串列表（兼容 str/list）。"""
    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, str) and val:
        return [x.strip() for x in val.split(",") if x.strip()]
    return []


def load_agents(force_reload: bool = False) -> dict[str, AgentDef]:
    """加载所有 agents（全局 / 个人 / 项目，高优先级覆盖）。

    Args:
        force_reload: 跳过缓存强制重新读盘
    """
    if not force_reload and _cache["agents"] is not None and time.time() - _cache["mtime"] <= _cache["ttl"]:
        # 热重载：检测文件变更，mtime 变化则跳过缓存继续加载
        current_mtime = _dirs_mtime(_agent_dirs())
        if current_mtime <= _cache.get("agents_dir_mtime", 0.0):
            return _cache["agents"]
        _cache["agents_dir_mtime"] = current_mtime

    files: dict[str, tuple[str, str]] = {}
    scope_map: dict[str, str] = {}
    for directory, scope in _agent_dirs():
        scanned = _scan_md_files(directory)
        for name, value in scanned.items():
            files[name] = value
            scope_map[name] = scope

    agents: dict[str, AgentDef] = {}
    for name, (path, content) in files.items():
        meta, body = _parse_frontmatter(content)

        # 解析 arguments（与 SkillDef 相同格式）
        arguments: list[SkillArg] = []
        for arg_data in meta.get("arguments", []):
            if isinstance(arg_data, dict):
                arguments.append(SkillArg(
                    name=str(arg_data.get("name", "")),
                    description=str(arg_data.get("description", "") or ""),
                    required=bool(arg_data.get("required", False)),
                    default=str(arg_data.get("default", "") or ""),
                ))

        agents[name] = AgentDef(
            name=name,
            description=str(meta.get("description", "") or ""),
            content=body,
            source=path,
            extends=str(meta.get("extends", "") or ""),
            arguments=arguments,
            allowed_tools=_as_list(meta.get("allowed_tools", [])),
            restricted_tools=_as_list(meta.get("restricted_tools", [])),
            context_patterns=_as_list(meta.get("context_patterns", [])),
            tags=_as_list(meta.get("tags", [])),
            version=str(meta.get("version", "") or ""),
            scope=scope_map.get(name, ""),
            license=str(meta.get("license", "") or ""),
        )

    # 解析 extends 继承链
    _resolve_extends(agents)

    _cache["agents"] = agents
    _cache["mtime"] = time.time()
    return agents


def _resolve_extends(agents: dict[str, AgentDef], _seen: set[str] | None = None, _resolved: set[str] | None = None) -> None:
    """解析 agent 的 extends 继承，将父 agent 的属性合并到子 agent。

    合并规则：
    - content: 父 content + 子 content（子追加在父之后）
    - allowed_tools: 合并去重
    - restricted_tools: 合并去重
    - context_patterns: 合并去重
    - tags: 合并去重
    - description / version / scope / license / source: 子有值则保留，否则用父
    - 循环继承检测
    """
    if _resolved is None:
        _resolved = set()
    for name, agent in agents.items():
        if not agent.extends:
            continue
        if name in _resolved:
            continue
        _resolve_one_extends(agents, name, _seen or set(), _resolved)


def _resolve_one_extends(
    agents: dict[str, AgentDef], name: str, seen: set[str], resolved: set[str]
) -> None:
    """递归解析单个 agent 的继承链。"""
    agent = agents[name]
    if not agent.extends or name in resolved:
        return
    if name in seen:
        return
    seen = seen | {name}
    parent_name = agent.extends
    if parent_name not in agents:
        resolved.add(name)
        return
    parent = agents[parent_name]
    if parent.extends and parent_name not in resolved:
        _resolve_one_extends(agents, parent_name, seen, resolved)
    # 合并 content
    if parent.content and agent.content:
        agent.content = parent.content + "\n\n" + agent.content
    elif parent.content and not agent.content:
        agent.content = parent.content
    # 合并列表字段（去重，子优先）
    for field_name in ("allowed_tools", "restricted_tools", "context_patterns", "tags"):
        parent_vals = getattr(parent, field_name, [])
        child_vals = getattr(agent, field_name, [])
        merged = list(dict.fromkeys(parent_vals + child_vals))
        setattr(agent, field_name, merged)
    # 合并标量字段（子有值则保留）
    if not agent.description and parent.description:
        agent.description = parent.description
    if not agent.version and parent.version:
        agent.version = parent.version
    if not agent.license and parent.license:
        agent.license = parent.license
    resolved.add(name)


def load_skills(force_reload: bool = False) -> dict[str, SkillDef]:
    """加载所有 skills（全局 / 个人 / 项目，高优先级覆盖）。

    Args:
        force_reload: 跳过缓存强制重新读盘
    """
    if not force_reload and _cache["skills"] is not None and time.time() - _cache["mtime"] <= _cache["ttl"]:
        # 热重载：检测文件变更，mtime 变化则跳过缓存继续加载
        current_mtime = _dirs_mtime(_skill_dirs())
        if current_mtime <= _cache.get("skills_dir_mtime", 0.0):
            return _cache["skills"]
        _cache["skills_dir_mtime"] = current_mtime

    files: dict[str, tuple[str, str]] = {}
    scope_map: dict[str, str] = {}
    for directory, scope in _skill_dirs():
        scanned = _scan_md_files(directory)
        for name, value in scanned.items():
            files[name] = value
            scope_map[name] = scope

    skills: dict[str, SkillDef] = {}
    for name, (path, content) in files.items():
        meta, body = _parse_frontmatter(content)

        # 解析 arguments
        arguments: list[SkillArg] = []
        for arg_data in meta.get("arguments", []):
            if isinstance(arg_data, dict):
                arguments.append(SkillArg(
                    name=str(arg_data.get("name", "")),
                    description=str(arg_data.get("description", "") or ""),
                    required=bool(arg_data.get("required", False)),
                    default=str(arg_data.get("default", "") or ""),
                ))

        # 解析列表型元数据（兼容 str / list）— 使用模块级 _as_list

        skills[name] = SkillDef(
            name=name,
            description=str(meta.get("description", "") or ""),
            arguments=arguments,
            content=body,
            source=path,
            allowed_tools=_as_list(meta.get("allowed_tools", [])),
            dependencies=_as_list(meta.get("dependencies", [])),
            license=str(meta.get("license", "") or ""),
            version=str(meta.get("version", "") or ""),
            tags=_as_list(meta.get("tags", [])),
            scope=scope_map.get(name, ""),
        )

    _cache["skills"] = skills
    _cache["mtime"] = time.time()
    return skills


# ─────────────────────────────────────────────
# 参数验证
# ─────────────────────────────────────────────

def validate_args(defn: SkillDef | AgentDef, args: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """验证并补全参数，返回 (resolved_args, errors)。

    - 必填参数缺失 -> 加入 errors
    - 可选参数缺失但有 default -> 用 default 填充
    - 未声明的参数 -> 忽略（宽松策略）
    """
    resolved: dict[str, str] = {}
    errors: list[str] = []

    for arg_def in defn.arguments:
        if arg_def.name in args and args[arg_def.name]:
            resolved[arg_def.name] = args[arg_def.name]
        elif arg_def.required:
            errors.append(f"缺少必填参数: {arg_def.name}" + (f" ({arg_def.description})" if arg_def.description else ""))
        elif arg_def.default:
            resolved[arg_def.name] = arg_def.default

    return resolved, errors


# ─────────────────────────────────────────────
# 渲染
# ─────────────────────────────────────────────

def _builtin_variables() -> dict[str, str]:
    """内置模板变量，始终可用。"""
    now = datetime.datetime.now()
    return {
        "cwd": os.getcwd(),
        "date": now.strftime("%Y-%m-%d"),
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "time": now.strftime("%H:%M:%S"),
        "year": str(now.year),
        "user": os.environ.get("USER") or os.environ.get("USERNAME") or "",
        "home": str(Path.home()),
    }


def _render_template(content: str, args: dict[str, str]) -> str:
    """渲染模板：替换参数 + 内置变量，清除未填充占位符。"""
    prompt = content
    for key, value in args.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", str(value))
    for key, value in _builtin_variables().items():
        prompt = prompt.replace(f"{{{{{key}}}}}", value)
    prompt = re.sub(r"\{\{\w+\}\}", "", prompt)
    return prompt.strip()


def render_skill(skill: SkillDef, args: dict[str, str]) -> str:
    """渲染 skill 模板：替换参数 + 内置变量，返回完整 prompt。"""
    return _render_template(skill.content, args)


# ─────────────────────────────────────────────
# 搜索 / 发现
# ─────────────────────────────────────────────

def search_skills(keyword: str = "", tags: list[str] | None = None) -> list[SkillDef]:
    """按关键词 / 标签搜索 skill。

    - keyword: 匹配 name / description / tags（大小写不敏感）
    - tags: 必须全部命中
    """
    skills = load_skills()
    results: list[SkillDef] = []
    kw = keyword.lower()

    for skill in skills.values():
        if tags:
            skill_tags = [t.lower() for t in skill.tags]
            if not all(t.lower() in skill_tags for t in tags):
                continue
        if kw:
            haystack = " ".join([
                skill.name, skill.description, " ".join(skill.tags),
            ]).lower()
            if kw not in haystack:
                continue
        results.append(skill)

    return sorted(results, key=lambda s: s.name)


def list_skills_summary() -> str:
    """返回所有 skill 的简明列表（用于 CLI 展示和系统提示词）。"""
    skills = load_skills()
    if not skills:
        return "(无可用 skill)"
    lines: list[str] = []
    for name in sorted(skills):
        s = skills[name]
        desc = s.description or "(无描述)"
        if len(desc) > 80:
            desc = desc[:77] + "..."
        scope_tag = f"[{s.scope}]" if s.scope else ""
        lines.append(f"  - {name}{scope_tag}: {desc}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Agent 搜索 / 发现
# ─────────────────────────────────────────────

def search_agents(keyword: str = "", tags: list[str] | None = None) -> list[AgentDef]:
    """按关键词 / 标签搜索 agent。

    - keyword: 匹配 name / description / tags（大小写不敏感）
    - tags: 必须全部命中
    """
    agents = load_agents()
    results: list[AgentDef] = []
    kw = keyword.lower()

    for agent in agents.values():
        if tags:
            agent_tags = [t.lower() for t in agent.tags]
            if not all(t.lower() in agent_tags for t in tags):
                continue
        if kw:
            haystack = " ".join([
                agent.name, agent.description, " ".join(agent.tags),
            ]).lower()
            if kw not in haystack:
                continue
        results.append(agent)

    return sorted(results, key=lambda a: a.name)


def list_agents_summary() -> str:
    """返回所有 agent 的简明列表（用于 CLI 展示和系统提示词）。"""
    agents = load_agents()
    if not agents:
        return "(无可用 agent)"
    lines: list[str] = []
    for name in sorted(agents):
        a = agents[name]
        desc = a.description or "(无描述)"
        if len(desc) > 80:
            desc = desc[:77] + "..."
        scope_tag = f"[{a.scope}]" if a.scope else ""
        tags_tag = f" ({', '.join(a.tags)})" if a.tags else ""
        lines.append(f"  - {name}{scope_tag}{tags_tag}: {desc}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# 便捷：解析 CLI 参数
# ─────────────────────────────────────────────

_MAX_FILE_SIZE = 10 * 1024
_MAX_FILES = 20
_MAX_TOTAL_SIZE = 50 * 1024

_EXT_MAP = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
    ".r": "r",
    ".lua": "lua",
    ".vim": "vim",
    ".dockerfile": "dockerfile",
    ".tf": "hcl",
    ".hcl": "hcl",
    ".proto": "protobuf",
    ".graphql": "graphql",
    ".vue": "vue",
    ".svelte": "svelte",
}


def resolve_context_patterns(agent: AgentDef, cwd: str) -> str:
    if not agent.context_patterns:
        return ""

    all_files: list[str] = []
    seen: set[str] = set()
    for pattern in agent.context_patterns:
        matched = glob_module.glob(os.path.join(cwd, pattern), recursive=True)
        for fpath in sorted(matched):
            if fpath in seen:
                continue
            seen.add(fpath)
            if not os.path.isfile(fpath):
                continue
            all_files.append(fpath)

    if not all_files:
        return ""

    all_files = all_files[:_MAX_FILES]

    parts: list[str] = []
    total_size = 0

    for fpath in all_files:
        try:
            fsize = os.path.getsize(fpath)
            if fsize > _MAX_FILE_SIZE:
                continue
            with open(fpath, "rb") as f:
                head = f.read(1024)
            if b"\x00" in head:
                continue
            with open(fpath, encoding="utf-8", errors="replace") as f:
                content = f.read()
            if total_size + len(content) > _MAX_TOTAL_SIZE:
                break
            total_size += len(content)
            rel = os.path.relpath(fpath, cwd)
            ext = os.path.splitext(fpath)[1].lower()
            lang = _EXT_MAP.get(ext, "")
            fence = f"```{lang}" if lang else "```"
            parts.append(f"### {rel}\n{fence}\n{content}\n```")
        except OSError:
            continue

    if not parts:
        return ""

    return "## 上下文文件\n\n" + "\n\n".join(parts) + "\n"


def render_agent(agent: AgentDef, args: dict[str, str]) -> str:
    """渲染 agent 模板：替换参数 + 内置变量，返回完整 persona。"""
    return _render_template(agent.content, args)


def build_agent_persona(a_def: AgentDef, cwd: str, args: dict[str, str] | None = None) -> str:
    """构建完整的 agent persona 文本：人设 + 上下文文件 + 工具约束元信息。

    Args:
        a_def: Agent 定义
        cwd: 当前工作目录（用于 context_patterns）
        args: 用户传入的参数（如 /agent reviewer project=octopus）
    """
    # 渲染模板变量
    user_args = args or {}
    if a_def.arguments or "{{" in a_def.content:
        resolved, errors = validate_args(a_def, user_args)
        if errors:
            import logging
            logging.getLogger(__name__).debug("agent 参数验证: %s", errors)
        persona = render_agent(a_def, resolved)
    else:
        persona = a_def.content

    ctx = resolve_context_patterns(a_def, cwd)
    if ctx:
        persona = persona + "\n\n" + ctx if persona else ctx
    meta_parts: list[str] = []
    if a_def.allowed_tools:
        meta_parts.append(f"允许使用的工具: {', '.join(a_def.allowed_tools)}")
    if a_def.restricted_tools:
        meta_parts.append(f"禁止使用的工具: {', '.join(a_def.restricted_tools)}")
    if a_def.tags:
        meta_parts.append(f"角色标签: {', '.join(a_def.tags)}")
    if meta_parts:
        meta_block = (
            "## Agent 工具与角色约束\n\n"
            + "\n".join(f"- {p}" for p in meta_parts)
            + "\n\n请严格遵守以上工具约束。仅使用允许的工具，绝不使用被禁止的工具。"
        )
        persona = (persona + "\n\n" + meta_block) if persona else meta_block
    return persona


def parse_skill_args(args_str: str) -> dict[str, str]:
    """解析用户输入的 key=value 参数（支持引号包裹的值）。"""
    result: dict[str, str] = {}
    pattern = re.compile(r'([\w-]+)=(?:"([^"]*)"|\'([^\']*)\'|(\S+))')
    for m in pattern.finditer(args_str):
        key = m.group(1)
        value = m.group(2) or m.group(3) or m.group(4) or ""
        result[key] = value
    return result
