"""上下文窗口管理和系统提示词构建。"""

import json
import os
import subprocess
from datetime import datetime
from typing import Any

import anthropic

from config import get
from tools import get_cwd


def _estimate_chars(messages: list[dict]) -> int:
    """粗略估算 messages 的总字符数。"""
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block))
                elif hasattr(block, "text"):
                    total += len(block.text) if block.text else 0
                elif hasattr(block, "input"):
                    total += len(json.dumps(block.input, ensure_ascii=False))
        else:
            total += len(str(content))
    return total


def _messages_to_text(messages: list[dict]) -> str:
    """将 messages 转为纯文本用于摘要。"""
    parts = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            parts.append(f"[{role}] {content}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append(f"[{role}] {block.get('text', '')}")
                    elif btype == "tool_use":
                        parts.append(
                            f"[{role}:tool_use:{block.get('name', '')}] "
                            f"{json.dumps(block.get('input', {}), ensure_ascii=False)}"
                        )
                    elif btype == "tool_result":
                        parts.append(
                            f"[{role}:tool_result] {str(block.get('content', ''))[:500]}"
                        )
                elif hasattr(block, "text") and block.text:
                    parts.append(f"[{role}] {block.text}")
        else:
            parts.append(f"[{role}] {str(content)[:500]}")
    return "\n".join(parts)


def compress_messages(
    client: anthropic.Anthropic,
    messages: list[dict],
    model: str,
) -> list[dict]:
    """当 messages 过长时，用 LLM 摘要压缩早期对话，保留最近的部分。"""
    chars = _estimate_chars(messages)
    threshold = get("context_threshold", 120_000)
    if chars < threshold:
        return messages

    keep_recent = 4
    if len(messages) <= keep_recent + 2:
        return messages

    old_messages = messages[:-keep_recent]
    recent_messages = messages[-keep_recent:]

    summary_prompt = (
        "请将以下对话历史压缩为一段简洁的摘要，保留关键信息："
        "做了什么操作、修改了哪些文件、得到了什么结论。"
        "用中文输出，不超过 500 字。不要输出其他内容。\n\n"
        f"{_messages_to_text(old_messages)}"
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": summary_prompt}],
        )
        summary = next((b.text for b in resp.content if b.type == "text"), "")
        if not summary:
            return messages
    except Exception:
        return messages

    compressed = [
        {"role": "user", "content": f"[上下文摘要] {summary}"},
        {"role": "assistant", "content": "收到，我已了解之前的上下文。"},
    ]
    return compressed + recent_messages


# ─────────────────────────────────────────────
# 系统提示词
# ─────────────────────────────────────────────

def _get_project_overview() -> str:
    """自动扫描项目根目录，生成简要的结构概览。"""
    cwd = get_cwd()
    lines = []

    # 检测 git 状态
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        if result.returncode == 0:
            branch_line = result.stdout.split("\n")[0]
            changes = [l for l in result.stdout.split("\n")[1:] if l.strip()]
            git_info = f"Git: {branch_line.strip()}"
            if changes:
                git_info += f"，{len(changes)} 个未提交变更"
            lines.append(git_info)
    except Exception:
        pass

    # 列出顶层文件/目录
    try:
        entries = sorted(os.listdir(cwd))
        dirs = [e for e in entries
                if os.path.isdir(os.path.join(cwd, e)) and not e.startswith(".")]
        files = [e for e in entries
                 if os.path.isfile(os.path.join(cwd, e)) and not e.startswith(".")]
        if dirs:
            lines.append(f"目录: {', '.join(dirs[:20])}")
        if files:
            lines.append(f"文件: {', '.join(files[:20])}")
    except Exception:
        pass

    return "\n".join(lines)


def _load_project_instructions() -> str:
    """加载项目根目录的 OCTOPUS.md 作为项目指令。"""
    cwd = get_cwd()
    for name in ("OCTOPUS.md", "CLAUDE.md"):
        path = os.path.join(cwd, name)
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    return content
            except OSError:
                pass
    return ""


def build_system_prompt() -> str:
    """动态构建系统提示词。"""
    overview = _get_project_overview()
    overview_section = ""
    if overview:
        overview_section = f"\n## 当前环境\n{overview}\n"

    instructions = _load_project_instructions()
    instructions_section = ""
    if instructions:
        instructions_section = f"\n## 项目指令\n{instructions}\n"

    return f"""你是一个强大的 AI Agent，可以通过工具完成各种编程任务。

今天是 {datetime.now().strftime('%Y-%m-%d')}。工作目录: {get_cwd()}
{overview_section}{instructions_section}
## 可用工具
- **bash**: 执行 shell 命令（工作目录在调用间持久化，支持 cd）
- **read_file**: 读取文件内容
- **write_file**: 创建或覆盖写入文件
- **edit_file**: 精确替换文件中的字符串（比 write_file 重写整个文件更高效安全）
- **list_files**: 列出目录内容，支持 glob 模式匹配
- **grep_search**: 在文件中搜索文本或正则表达式
- **web_search**: 搜索互联网，查询最新信息、文档、API 参考
- **web_fetch**: 抓取网页 URL 内容，获取页面纯文本

## 工作原则
- 拿到任务后先思考，再选择合适的工具
- 复杂任务开始前，先用任务列表规划步骤，完成后逐项标记：
  - 未开始: `- [ ] 任务描述`
  - 已完成: `- [x] 任务描述`
- 编辑已有文件时优先使用 edit_file，而非 write_file 重写整个文件
- 每次只调用一个工具，观察结果再决定下一步
- 遇到错误要分析原因并尝试修复，最多重试3次
- 任务完成后用清晰的语言告知用户结果
- 如果任务无法完成，说明原因

## 输出风格
- 简洁清晰，不啰嗦
- 代码用 markdown 代码块包裹
- 重要结果高亮展示
"""
