# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Python AI Agent，类似 Claude Code 的最小实现。基于 Anthropic SDK 的 tool-use 能力，让 LLM 通过工具调用执行编程任务。

## 架构

模块化设计，每个文件职责单一：

| 文件 | 职责 |
|------|------|
| `octopus.py` | 主入口，解析参数，分发到单次执行或交互模式 |
| `cli.py` | 交互式 CLI、slash 命令、权限确认、信号处理 |
| `agent.py` | Agent 主循环（调用 LLM、执行工具、格式化输出） |
| `tools.py` | 工具 schema 定义、执行器实现、工作目录管理 |
| `context.py` | 上下文压缩（长对话自动摘要）、系统提示词构建、项目指令注入 |
| `session.py` | 对话历史持久化（保存/加载/列表） |
| `config.py` | 配置管理（文件 + 环境变量覆盖 + 危险命令检测） |
| `mcp.py` | MCP 客户端（连接外部工具服务器、工具发现/调用） |

## 核心流程

```
用户任务 → Claude API → tool_use → 执行工具 → 结果回传 → Claude API → ... → 最终回复
```

## 运行方式

```bash
# 设置 API key
export OCTOPUS_API_KEY=sk-your-key

# 单次任务
python octopus.py "帮我写一个 Python 斐波那契函数"

# 交互模式
python octopus.py

# 自定义 API 地址（兼容第三方代理）
export OCTOPUS_BASE_URL=https://your-endpoint

# 切换模型
export OCTOPUS_MODEL=claude-sonnet-4-20250514
```

## 配置

支持两种配置方式，环境变量优先级高于配置文件：

1. 配置文件：`.octopus/config.json`（项目级）或 `~/.octopus/config.json`（用户级）
2. 环境变量：`OCTOPUS_MODEL`、`OCTOPUS_API_KEY`、`OCTOPUS_BASE_URL` 等

可配置项：`model`、`max_tokens`、`max_iterations`、`api_key`、`base_url`、`permissions`、`dangerous_commands`、`context_threshold`、`mcp_servers`

权限模式：`auto-approve`（全部自动）、`confirm`（危险操作确认）、`deny`（禁止危险操作）

## MCP 服务器

支持连接外部 MCP 工具服务器。在 `.octopus/config.json` 中配置：

```json
{
  "mcp_servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "ghp_xxx"}
    }
  }
}
```

MCP 服务器在交互模式启动时自动连接，退出时清理。其提供的工具会自动合并到 Agent 可用工具列表中。

## 工具列表

- `bash` — 执行 shell 命令（工作目录在调用间持久化）
- `read_file` — 读取文件内容
- `write_file` — 创建/覆盖写入文件
- `edit_file` — 精确字符串替换编辑
- `list_files` — 目录列表，支持 glob 模式和递归
- `grep_search` — 正则文本搜索

## Slash 命令（交互模式）

`/help` `/clear` `/save` `/sessions` `/load <id>` `/model [name]` `/config [key=val]` `/cwd` `/quit`

## 项目指令

自动读取项目根目录的 `OCTOPUS.md` 或 `CLAUDE.md` 作为项目指令，注入到系统提示词中。

## 开发指南

- 新增工具：在 `tools.py` 的 `TOOLS` 列表添加 schema，实现处理函数，在 `TOOL_HANDLERS` 注册
- 新增 slash 命令：在 `cli.py` 的 `_handle_slash_command` 中添加
- 新增配置项：在 `config.py` 的 `_DEFAULTS` 中添加
- 上下文压缩阈值：通过配置 `context_threshold` 调整
- Session 存储在 `~/.octopus/sessions/` 目录
