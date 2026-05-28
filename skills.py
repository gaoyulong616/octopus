"""自定义 Agents 和 Skills：加载、渲染、管理。"""

import glob as glob_module
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentDef:
    """一个自定义 Agent 定义。"""
    name: str
    content: str       # 完整 md 内容，作为 system prompt
    source: str        # 来源路径


@dataclass
class SkillArg:
    """Skill 的参数定义。"""
    name: str
    description: str = ""
    required: bool = False


@dataclass
class SkillDef:
    """一个自定义 Skill 定义。"""
    name: str
    description: str = ""
    arguments: list[SkillArg] = field(default_factory=list)
    content: str = ""  # 正文模板（去除 frontmatter 后）
    source: str = ""


def _scan_md_files(*dirs: str) -> dict[str, tuple[str, str]]:
    """扫描多个目录下的 .md 文件，后扫描的覆盖先扫描的。
    返回 {name: (abs_path, content)}。
    """
    found: dict[str, tuple[str, str]] = {}
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        for filepath in sorted(glob_module.glob(os.path.join(directory, "*.md"))):
            name = os.path.splitext(os.path.basename(filepath))[0]
            if name.startswith("_"):
                continue
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()
                found[name] = (filepath, content)
            except OSError:
                continue
    return found


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 Markdown frontmatter（--- 包裹的 YAML）。
    返回 (metadata_dict, body_content)。
    不依赖 pyyaml，手写简单解析。
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    raw_meta = parts[1].strip()
    body = parts[2].strip()

    meta: dict = {}
    current_key = None
    current_list: list | None = None

    for line in raw_meta.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # 顶层 key: value
        top_match = re.match(r'^(\w+):\s*(.*)', stripped)
        if top_match and not line.startswith(" "):
            key, val = top_match.groups()
            current_key = key
            current_list = None

            if val:
                meta[key] = val.strip().strip('"').strip("'")
            elif key == "arguments":
                meta[key] = []
                current_list = meta[key]
            continue

        # 列表项 - name: value
        if stripped.startswith("- ") and current_list is not None:
            item_match = re.match(r'^-\s*(\w+):\s*(.*)', stripped)
            if item_match:
                item = {item_match.group(1): item_match.group(2).strip().strip('"').strip("'")}
                # 读取后续属性行
                current_list.append(item)
            continue

        # 属性行（缩进的 key: value，属于上一个列表项）
        if line.startswith("  ") and current_list and current_key == "arguments":
            attr_match = re.match(r'^\s+(\w+):\s*(.*)', line)
            if attr_match and current_list:
                k, v = attr_match.groups()
                current_list[-1][k] = v.strip().strip('"').strip("'")

    return meta, body


def load_agents() -> dict[str, AgentDef]:
    """加载所有 agents（个人级 + 项目级，项目级优先）。"""
    personal_dir = os.path.join(str(Path.home()), ".agents")
    project_dir = os.path.join(os.getcwd(), ".agents")
    files = _scan_md_files(personal_dir, project_dir)

    agents: dict[str, AgentDef] = {}
    for name, (path, content) in files.items():
        agents[name] = AgentDef(
            name=name,
            content=content,
            source=path,
        )
    return agents


def load_skills() -> dict[str, SkillDef]:
    """加载所有 skills（个人级 + 项目级，项目级优先）。"""
    personal_dir = os.path.join(str(Path.home()), ".skills")
    project_dir = os.path.join(os.getcwd(), ".skills")
    files = _scan_md_files(personal_dir, project_dir)

    skills: dict[str, SkillDef] = {}
    for name, (path, content) in files.items():
        meta, body = _parse_frontmatter(content)

        arguments = []
        for arg_data in meta.get("arguments", []):
            if isinstance(arg_data, dict):
                arguments.append(SkillArg(
                    name=arg_data.get("name", ""),
                    description=arg_data.get("description", ""),
                    required=arg_data.get("required", "false").lower() == "true",
                ))

        skills[name] = SkillDef(
            name=name,
            description=meta.get("description", ""),
            arguments=arguments,
            content=body,
            source=path,
        )
    return skills


def render_skill(skill: SkillDef, args: dict[str, str]) -> str:
    """替换 skill 模板中的 {{参数名}} 占位符，返回完整 prompt。"""
    prompt = skill.content

    # 替换参数占位符
    for key, value in args.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", value)

    # 清除未填充的可选参数占位符
    prompt = re.sub(r'\{\{\w+\}\}', '', prompt)

    return prompt.strip()


def parse_skill_args(args_str: str) -> dict[str, str]:
    """解析用户输入的 key=value 参数。"""
    result: dict[str, str] = {}
    for part in args_str.split():
        if "=" in part:
            key, value = part.split("=", 1)
            result[key.strip()] = value.strip()
    return result
