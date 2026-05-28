# Octopus Agent

类似 Claude Code 的 Python AI Agent，基于 Anthropic SDK 的 tool-use 能力，让 LLM 通过工具调用自主完成编程任务。

## 特性

- **8 个内置工具**：bash、文件读写/编辑、目录浏览、文本搜索、Web 搜索/抓取
- **上下文管理**：长对话自动摘要压缩，不丢关键信息
- **对话持久化**：保存/加载 session，跨会话延续上下文
- **权限安全**：危险操作确认机制（rm -rf、git push --force 等）
- **MCP 支持**：连接外部工具服务器，无限扩展能力
- **项目记忆**：自动读取 OCTOPUS.md / CLAUDE.md 作为项目指令
- **Slash 命令**：交互模式下的快捷操作

## 快速开始

```bash
# 安装依赖
pip install anthropic

# 设置 API key
export OCTOPUS_API_KEY=sk-your-key

# 交互模式
python octopus.py

# 单次任务
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
| `/config [key=val]` | 查看/修改配置 |
| `/cwd` | 显示工作目录 |
| `/quit` | 退出 |

## 项目结构

```
octopus_cli/
├── octopus.py    # 主入口
├── agent.py      # Agent 主循环
├── tools.py      # 工具定义与执行器
├── cli.py        # 交互式 CLI
├── config.py     # 配置管理
├── context.py    # 上下文压缩 + 系统提示词
├── session.py    # 对话历史持久化
├── mcp.py        # MCP 客户端
└── CLAUDE.md     # 项目开发指引
```

## MCP 服务器

支持通过配置连接任意 MCP 工具服务器，其提供的工具会自动合并到 Agent 可用列表中：

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
