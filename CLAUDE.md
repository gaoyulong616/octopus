# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Python AI Agent，类似 Claude Code 的最小实现。基于 Anthropic SDK 的 tool-use 能力，让 LLM 通过工具调用执行编程任务。

## 架构

模块化设计，每个文件职责单一：

| 文件 | 职责 |
|------|------|
| `octopus.py` | 主入口，解析参数，分发到单次执行或交互模式 |
| `tui.py` | Rich TUI 界面（实时流式 + Markdown 重渲染、diff 视图、任务进度、Plan/Auto 模式、Shift+Tab 切换、目录信任提示） |
| `cli.py` | CLI 逻辑（slash 命令、权限确认、信号处理、TUI 回退） |
| `agent.py` | Agent 主循环（流式 API 调用 LLM、执行工具、事件回调输出） |
| `tools.py` | 8 个工具定义 + 执行器 + 工作目录管理 |
| `context.py` | 上下文压缩（长对话自动摘要）、系统提示词构建（含任务规划指引）、项目指令注入 |
| `session.py` | 对话历史持久化（保存/加载/列表） |
| `config.py` | 配置管理（多模型、文件 + 环境变量覆盖 + 危险命令检测 + 目录信任） |
| `mcp.py` | MCP 客户端（连接外部工具服务器、工具发现/调用） |
| `skills.py` | 自定义 Agent 和 Skill 加载（~/.agents/ .agents/ ~/.skills/ .skills/） |

## 核心流程

```
用户任务 → Claude API (stream) → text_delta → 实时流式输出 → tool_use → 执行工具 → 结果回传 → ... → 最终回复
```

## 运行方式

```bash
# 安装依赖
pip install anthropic rich prompt_toolkit

# 配置文件 ~/.octopus/config.json（api_key 可写在配置中）
mkdir -p ~/.octopus

# 交互模式（Rich TUI）
python octopus.py

# 单次任务（纯 print 输出）
python octopus.py "帮我写一个 Python 斐波那契函数"
```

## 配置

支持两种配置方式，环境变量优先级高于配置文件：

1. 配置文件：`.octopus/config.json`（项目级）或 `~/.octopus/config.json`（用户级）
2. 环境变量：`OCTOPUS_MODEL`、`OCTOPUS_API_KEY`、`OCTOPUS_BASE_URL` 等

完整配置文件示例：

```json
{
  "api_key": "sk-b1a1...c5d4",
  "base_url": "https://api.deepseek.com/anthropic",
  "model": "deepseek-v4-flash",
  "default_model": "ds-flash",
  "models": {
    "ds-flash": "deepseek-v4-flash",
    "ds-pro": "deepseek-v4-pro",
    "sonnet": "claude-sonnet-4-20250514",
    "opus": "claude-opus-4-20250514",
    "haiku": "claude-haiku-4-5-20251001"
  },
  "max_tokens": 8096,
  "max_iterations": 20,
  "permissions": "confirm",
  "dangerous_commands": [
    "rm -rf", "rm -r", "rmdir",
    "git push --force", "git push -f",
    "git reset --hard", "git clean",
    "drop ", "delete from",
    "mkfs", "dd if="
  ],
  "context_threshold": 120000,
  "mcp_servers": {}
}
```

可配置项：`model`、`models`、`default_model`、`api_key`、`base_url`、`max_tokens`、`max_iterations`、`permissions`、`dangerous_commands`、`context_threshold`、`mcp_servers`

权限模式：`auto-approve`（全部自动）、`confirm`（危险操作确认）、`deny`（禁止危险操作）

## MCP 服务器

支持连接外部 MCP 工具服务器。在配置文件的 `mcp_servers` 中添加：

```json
{
  "mcp_servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    }
  }
}
```

## 工具列表

- `bash` — 执行 shell 命令（工作目录在调用间持久化）
- `read_file` — 读取文件内容
- `write_file` — 创建/覆盖写入文件
- `edit_file` — 精确字符串替换编辑
- `list_files` — 目录列表，支持 glob 模式和递归
- `grep_search` — 正则文本搜索
- `web_search` — 搜索互联网（DuckDuckGo API + Wikipedia，无需 API key）
- `web_fetch` — 抓取网页 URL 内容，返回纯文本

## Slash 命令（交互模式）

`/help` `/clear` `/save` `/sessions` `/load <id>` `/search <关键词>` `/model [alias/name]` `/models` `/agents` `/agent [name]` `/skills` `/skill <name>` `/config [key=val]` `/plan` `/auto` `/continue` `/cwd` `/quit`

### 快捷键

- `Tab` — 触发补全（slash 命令 / 文件路径），匹配字符蓝色高亮
- `Shift+Tab` — 切换 Plan（只读）/ Auto（全自动）模式
- `↑↓` — 浏览输入历史
- `Esc+Enter` — 插入换行（多行输入）
- `Ctrl+C` — 暂停当前任务（可 `/continue` 恢复）/ 空输入按两次退出
- `Ctrl+L` — 清屏

## 自定义 Agents 和 Skills

- Agent：`~/.agents/<name>.md` 或 `.agents/<name>.md`（项目级优先），内容作为 system prompt
- Skill：`~/.skills/<name>.md` 或 `.skills/<name>.md`（项目级优先），支持 frontmatter 和 `{{参数}}` 占位符
- `/agents` 列出，`/agent <name>` 切换，`/agent default` 恢复默认
- `/skills` 列出，`/skill <name>` 执行

## 项目指令

自动读取项目根目录的 `OCTOPUS.md` 或 `CLAUDE.md` 作为项目指令，注入到系统提示词中。

## 开发指南

- 新增工具：在 `tools.py` 的 `TOOLS` 列表添加 schema，实现处理函数，在 `TOOL_HANDLERS` 注册
- 新增 slash 命令：在 `cli.py` 的 `_handle_slash_command` 中添加
- 新增配置项：在 `config.py` 的 `_DEFAULTS` 中添加
- Agent 输出事件：`agent.py` 定义了 7 种事件类型（EVT_STREAM、EVT_THINKING、EVT_TOOL_CALL、EVT_TOOL_RESULT、EVT_RESPONSE、EVT_PROGRESS、EVT_ERROR），token 用量通过 `final_message.usage` 获取
- TUI 流式渲染：先 `sys.stdout.write()` 实时输出原始文本，事件结束时 `\033[{n}A\033[J` 回退并用 `Markdown()` 重渲染
- Diff 视图：`edit_file` 工具调用时用 `difflib.unified_diff` 对比，`+` 绿底 `#b8f0b8 on #1a4020`，`-` 红底 `#f0b8b8 on #401a1a`
- 任务进度：`_render_with_tasks()` 解析 `- [x]`/`- [ ]` 任务列表，渲染 ✔(绿)/◻(灰) 状态指示器
- Plan 模式：写入类工具（bash/write_file/edit_file）自动拒绝，system prompt 追加只读约束
- 权限确认：`_confirm_action()` 支持 `[a]` 放行同类工具（`auto_approved_tools` set），读取类工具自动通过
- 目录信任：`config.py` 的 `is_trusted_dir()`/`trust_dir()` 管理 `~/.octopus/trusted_dirs.json`
- 任务暂停：Ctrl+C 中断后 `state["last_task"]` 保存任务，`/continue` 恢复
- Session 自动保存：每轮对话后自动调用 `save_session(messages)` 保存到 `~/.octopus/sessions/`
- 输入历史存储在 `~/.octopus/history.txt`
- 配置持久化：`set_value()` 同时写入 `~/.octopus/config.json`
