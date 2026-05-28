# Octopus Agent

类似 Claude Code 的 Python AI Agent，基于 Anthropic SDK 的 tool-use 能力，让 LLM 通过工具调用自主完成编程任务。

## 特性

- **TUI 界面**：Rich 渲染终端 UI，透明背景，Markdown 回复，工具调用实时展示
- **8 个内置工具**：bash、文件读写/编辑、目录浏览、文本搜索、Web 搜索/抓取
- **自定义 Agents**：`~/.agents/` 或 `.agents/` 放 Markdown 文件定义 Agent 人设
- **自定义 Skills**：`~/.skills/` 或 `.skills/` 放 Markdown 模板定义快捷指令
- **上下文管理**：长对话自动摘要压缩，不丢关键信息
- **对话持久化**：保存/加载 session，跨会话延续上下文
- **权限安全**：危险操作确认机制（rm -rf、git push --force 等）
- **MCP 支持**：连接外部工具服务器，无限扩展能力
- **项目记忆**：自动读取 OCTOPUS.md / CLAUDE.md 作为项目指令

## 快速开始

```bash
# 安装依赖
pip install anthropic rich

# 设置 API key
export OCTOPUS_API_KEY=sk-your-key

# 交互模式（Rich TUI，透明背景）
python octopus.py

# 单次任务（纯文本输出）
python octopus.py "帮我写一个 Python 斐波那契函数"
```

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OCTOPUS_API_KEY` | API 密钥（必填） | - |
| `OCTOPUS_BASE_URL` | API 地址（兼容第三方） | Anthropic 官方 |
| `OCTOPUS_MODEL` | 模型名称 | deepseek-v4-flash |

### 配置文件

在项目根目录创建 `.octopus/config.json`：

```json
{
  "model": "claude-sonnet-4-20250514",
  "max_iterations": 20,
  "permissions": "confirm",
  "mcp_servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
    }
  }
}
```

## 工具列表

| 工具 | 说明 |
|------|------|
| `bash` | 执行 shell 命令，工作目录持久化 |
| `read_file` | 读取文件内容 |
| `write_file` | 写入文件（覆盖/追加） |
| `edit_file` | 精确字符串替换编辑 |
| `list_files` | 目录列表，支持 glob 模式 |
| `grep_search` | 正则文本搜索 |
| `web_search` | 搜索互联网（DuckDuckGo + Wikipedia） |
| `web_fetch` | 抓取网页内容，返回纯文本 |

## Slash 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/clear` | 清除对话历史 |
| `/save` | 保存当前对话 |
| `/sessions` | 列出已保存的对话 |
| `/load <id>` | 加载已保存的对话 |
| `/model [name]` | 查看/切换模型 |
| `/agents` | 列出可用 agents |
| `/agent [name]` | 查看/切换当前 agent |
| `/skills` | 列出可用 skills |
| `/skill <name>` | 执行 skill |
| `/config [key=val]` | 查看/修改配置 |
| `/cwd` | 显示工作目录 |
| `/quit` | 退出 |

## 自定义 Agents

在 `~/.agents/`（个人级）或 `.agents/`（项目级）放置 Markdown 文件，文件名即 Agent 名：

```markdown
# 代码审查 Agent

你是一个专业的代码审查专家。你的任务是：
- 审查代码的正确性、可读性和性能
- 指出潜在的 bug 和安全漏洞
```

切换：`/agent reviewer`，恢复默认：`/agent default`

## 自定义 Skills

在 `~/.skills/`（个人级）或 `.skills/`（项目级）放置 Markdown 模板：

```markdown
---
description: 审查当前代码变更
arguments:
  - name: scope
    description: 审查范围（可选）
    required: false
---

请审查当前的代码变更。{{scope}}

步骤：
1. 用 bash 运行 git diff
2. 逐文件分析变更
3. 输出审查结果
```

执行：`/skill review` 或 `/skill review scope=src/main.py`

## 项目结构

```
octopus_cli/
├── octopus.py    # 主入口
├── tui.py        # Rich TUI 界面（透明背景、Markdown 渲染）
├── agent.py      # Agent 主循环
├── tools.py      # 工具定义与执行器
├── cli.py        # CLI 逻辑（slash 命令、权限、TUI 回退）
├── config.py     # 配置管理
├── context.py    # 上下文压缩 + 系统提示词
├── session.py    # 对话历史持久化
├── mcp.py        # MCP 客户端
├── skills.py     # 自定义 Agent/Skill 加载
├── CLAUDE.md     # 项目开发指引
└── README.md     # 项目说明
```

## MCP 服务器

支持通过配置连接任意 MCP 工具服务器：

```json
{
  "mcp_servers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "ghp_xxx"}
    }
  }
}
```

## 许可证

MIT
