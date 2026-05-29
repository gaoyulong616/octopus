# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Python AI Agent，基于 Anthropic SDK 的 tool-use 能力，让 LLM 通过工具调用执行编程任务。

## 架构

模块化设计，每个文件职责单一：

| 文件 | 职责 |
|------|------|
| `octopus.py` | 主入口，解析参数（--continue/--resume/-n），分发到单次执行或交互模式 |
| `tui.py` | Rich TUI（流式 + Markdown 重渲染、diff 视图、任务进度、Plan/Auto 模式、会话选择器） |
| `cli.py` | CLI 逻辑（slash 命令分发、权限确认、信号处理、TUI 回退） |
| `commands.py` | Slash 命令注册表（装饰器注册、CommandResult、24 个命令独立函数） |
| `agent.py` | Agent 主循环（流式 API、重试退避、thinking 块、prompt cache、401 友好提示） |
| `tools.py` | 11 个工具 + 执行器 + bash 实时流式输出 + 文件大小保护 |
| `constants.py` | 共享常量（ANSI 颜色、文件大小限制、版本号） |
| `context.py` | 上下文压缩、系统提示词构建、多级项目指令注入（个人/项目/子目录）、跨会话记忆 |
| `session.py` | 会话管理（JSONL 追加存储、项目隔离、元数据索引、自动清理、导出） |
| `config.py` | 配置管理（多模型、文件 + 环境变量覆盖、危险命令检测、目录信任、配置校验） |
| `mcp.py` | MCP 客户端（连接外部工具服务器、工具发现/调用、断连自动重连） |
| `skills.py` | 自定义 Agent 和 Skill 加载（~/.agents/ .agents/ ~/.skills/ .skills/） |

## 核心流程

```
用户任务 → Claude API (stream) → text_delta → 实时流式输出 → tool_use → 执行工具 → 结果回传 → ... → 最终回复
```

## 运行方式

```bash
# 安装依赖
pip install -e .

# 配置文件 ~/.octopus/config.json（api_key、base_url、model 为必配项）
mkdir -p ~/.octopus

# 交互模式（Rich TUI）
python octopus.py

# 单次任务（纯 print 输出）
python octopus.py "帮我写一个 Python 斐波那契函数"

# 恢复最近会话
python octopus.py -c

# 交互式选择会话恢复
python octopus.py --resume

# 按名称恢复会话
python octopus.py --resume <name>

# 指定新会话名称
python octopus.py -n "重构任务"
```

## 配置

支持两种配置方式，环境变量优先级高于配置文件：

1. 配置文件：`.octopus/config.json`（项目级）或 `~/.octopus/config.json`（用户级）
2. 环境变量：`OCTOPUS_MODEL`、`OCTOPUS_API_KEY`、`OCTOPUS_BASE_URL`、`OCTOPUS_MAX_TOKENS`、`OCTOPUS_MAX_ITERATIONS`、`OCTOPUS_PERMISSIONS`

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
  "thinking_budget": null,
  "bash_timeout": 120,
  "dangerous_commands": [
    "rm -rf", "rm -r", "rmdir",
    "git push --force", "git push -f",
    "git reset --hard", "git clean",
    "drop ", "delete from",
    "mkfs", "dd if="
  ],
  "context_threshold": 120000,
  "mcp_servers": {},
  "cleanup_period_days": 30
}
```

必配项：`api_key`、`base_url`、`model`（无默认值，必须在配置文件或环境变量中设置）

可配置项：`model`、`models`、`default_model`、`api_key`、`base_url`、`max_tokens`、`max_iterations`、`permissions`、`thinking_budget`、`bash_timeout`、`dangerous_commands`、`context_threshold`、`mcp_servers`、`cleanup_period_days`

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

- `bash` — 执行 shell 命令（工作目录在调用间持久化，实时流式输出）
- `read_file` — 读取文件内容（>1MB 自动截断）
- `write_file` — 创建/覆盖写入文件（>1MB 拒绝）
- `edit_file` — 精确字符串替换编辑
- `list_files` — 目录列表，支持 glob 模式和递归
- `grep_search` — 正则文本搜索
- `web_search` — 搜索互联网（DuckDuckGo JSON + HTML + Wikipedia 多源链式搜索）
- `web_fetch` — 抓取网页 URL 内容，返回纯文本
- `copy_file` — 复制文件（保留元数据）
- `move_file` — 移动或重命名文件
- `delete_file` — 删除文件

## Slash 命令（交互模式）

`/help` `/init` `/clear` `/save` `/sessions` `/load <id>` `/resume [name]` `/rename <名称>` `/export [file]` `/search <关键词>` `/model [alias/name]` `/models` `/agents` `/agent [name]` `/skills` `/skill <name>` `/config [key=val]` `/plan` `/auto` `/continue` `/compact` `/remember <内容>` `/forget` `/cwd` `/quit`

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

多级加载，全部注入到系统提示词中：

1. **个人级** — `~/.octopus/OCTOPUS.md` 和 `~/.claude/CLAUDE.md`
2. **项目级** — 当前目录的 `OCTOPUS.md` 或 `CLAUDE.md`
3. **子目录级** — 各代码模块目录下的 `OCTOPUS.md` 或 `CLAUDE.md`（如 `src/OCTOPUS.md`）

优先使用 `OCTOPUS.md`，不存在时 fallback 到 `CLAUDE.md`。

## 会话管理

参照 Claude Code 实现：

- **JSONL 追加存储**：`~/.octopus/projects/<encoded-cwd>/<session-id>.jsonl`（按项目隔离）
- **自动保存**：每轮对话后自动追加，无需手动 `/save`
- **恢复会话**：`-c` 恢复最近、`--resume` 交互选择（↑↓ 选择、搜索过滤、摘要预览）
- **会话命名**：`-n` 启动时指定、`/rename` 会话内修改
- **会话导出**：`/export` 导出为纯文本
- **自动清理**：超过 `cleanup_period_days`（默认 30 天）的会话自动删除
- **元数据索引**：`index.json` 缓存，快速列出会话

## 开发指南

- 新增工具：在 `tools.py` 的 `TOOLS` 列表添加 schema，实现处理函数，在 `TOOL_HANDLERS` 注册
- 新增 slash 命令：在 `commands.py` 用 `@_register("/name", "desc")` 装饰器注册，实现 `cmd_xxx` 函数
- 新增配置项：在 `config.py` 的 `_DEFAULTS` 中添加，如需校验在 `_VALIDATORS` 中添加
- 共享常量：统一使用 `constants.py`（ANSI 颜色、文件大小限制、版本号）
- Agent 输出事件：`agent.py` 定义 7 种事件类型（EVT_STREAM、EVT_THINKING、EVT_TOOL_CALL、EVT_TOOL_RESULT、EVT_RESPONSE、EVT_PROGRESS、EVT_ERROR），token 用量通过 `final_message.usage` 获取
- API 重试：`_stream_with_retry()` 捕获 RateLimitError/APIStatusError，指数退避最多 3 次，401 友好提示
- TUI 流式渲染：`StreamRenderer` 类封装流式状态，先 `sys.stdout.write()` 实时输出，`\033[{n}A\033[J` 回退后 `Markdown()` 重渲染
- Bash 实时流式：`run_bash()` 逐行读取 stdout，通过 `output_fn` 回调实时输出
- Diff 视图：`_show_edit_diff()` 用 `difflib.unified_diff` 对比，`+` 绿底 `#b8f0b8 on #1a4020`，`-` 红底 `#f0b8b8 on #401a1a`
- 任务进度：`_render_with_tasks()` 解析 `- [x]`/`- [ ]` 任务列表，渲染 ✔(绿)/◻(灰) 状态指示器
- Extended Thinking：`agent.py` 检测 `thinking` 块并 emit，API 传 `thinking={"type":"enabled","budget_tokens":N}`
- Plan 模式：写入类工具自动拒绝，system prompt 追加只读约束
- 权限确认：`_confirm_action()` 支持 `[a]` 放行同类工具（`auto_approved_tools` set），读取类工具自动通过
- 目录信任：`config.py` 的 `is_trusted_dir()`/`trust_dir()` 管理 `~/.octopus/trusted_dirs.json`
- 任务暂停：Ctrl+C 中断后 `state["last_task"]` 保存任务，`/continue` 恢复
- Prompt Cache：system prompt 用 `cache_control: {"type": "ephemeral"}` 标记
- 跨会话记忆：`context.py` 的 `_load_memory()`/`save_memory()` 管理 `~/.octopus/memory.md`，注入 system prompt
- `/compact`：调用 `compress_messages()` 强制压缩对话上下文
- 文件保护：`run_read_file()` >1MB 截断，`run_write_file()` >1MB 拒绝
- Bash 超时：默认 120s，可通过配置 `bash_timeout` 调整
- Session 自动保存：每轮对话后自动调用 `save_session(messages, session_id=...)` 追加到 JSONL
- MCP 自动重连：`MCPServer.reconnect()` + `MCPManager.call_tool()` 断连检测，最多重试 2 次
- 配置校验：`config.py` 的 `validate_config()` 启动时校验，`set_value()` 写入前校验
- 输入历史存储在 `~/.octopus/history.txt`
- 配置持久化：`set_value()` 同时写入 `~/.octopus/config.json`
