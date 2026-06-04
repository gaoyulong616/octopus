# Octopus Agent

Python AI Agent，基于 Anthropic SDK 的 tool-use 能力，让 LLM 通过工具调用自主完成编程任务。

## 特性

### 核心能力
- **流式输出**：token 逐字实时渲染，最终以 Markdown 格式正确展示（代码高亮、标题、加粗等）
- **Token 费用追踪**：每轮显示 token 用量，会话累计追踪
- **TUI 界面**：Rich 渲染终端 UI，对话搜索，自动保存，任务进度展示
- **Extended Thinking**：支持 Anthropic thinking 块，灰色折叠面板展示思考过程
- **多模态支持**：`read_image` 读取图片（PNG/JPG/GIF/WebP），发送给模型进行视觉分析
- **21 个内置工具**：bash、文件读写/编辑/复制/移动/删除、目录浏览、文本搜索、Web 搜索/抓取、任务管理、Notebook 编辑、子 Agent、Worktree、检查点、定时调度、图片读取

### Agent 能力
- **子 Agent 并行执行**：`sub_agent` 启动独立线程执行子任务
- **结构化任务管理**：`task_create/update/list/get` 创建带依赖关系的任务
- **Git Worktree**：创建隔离工作目录并行开发不同分支
- **Git 检查点**：破坏性操作前自动快照，可一键回滚
- **定时调度**：`schedule_wakeup` 一次性唤醒，`cron_create` 周期性任务
- **Plan/Auto 模式**：`Shift+Tab` 切换，Plan 模式结构化输出实施计划
- **Stop Reason 处理**：检测 max_tokens 截断并提示用户

### 安全与配置
- **权限确认**：写入操作前确认，支持 `[a]` 一键放行同类工具
- **细粒度权限规则**：按工具名 + 正则模式配置 allow/deny（如允许 `npm test` 但拒绝 `npm publish`）
- **Hooks 系统**：工具执行前后触发自定义命令
- **三层配置层级**：项目本地级 > 项目级 > 用户级，环境变量覆盖
- **目录信任**：首次打开新目录提示确认，不信任则自动进入 Plan 模式
- **上下文管理**：长对话自动摘要压缩，渐进截断过长 tool_result
- **API 重试**：429 限速/500 错误自动重试，指数退避，401 友好提示

### 交互体验
- **Bash 实时流式**：长命令逐行实时输出，不等完成
- **文件保护**：读取 >1MB 文件自动截断，写入限制大小
- **Diff 视图**：`edit_file` 操作显示 `+` 绿底/`-` 红底的代码变更 diff
- **任务进度**：LLM 规划任务列表，✔/◻ 彩色状态指示器实时展示
- **补全系统**：Tab 补全 slash 命令和文件路径，匹配字符蓝色高亮
- **输入历史**：自动保存命令历史，上下箭头浏览
- **任务暂停**：`Ctrl+C` 暂停任务，随时旁问，`/continue` 恢复

### 扩展性
- **自定义 Agents**：`~/.agents/` 或 `.agents/` 放 Markdown 文件定义 Agent 人设
- **自定义 Skills**：`~/.skills/` 或 `.skills/` 放 Markdown 模板定义快捷指令
- **MCP 支持**：连接外部工具服务器，断连自动重连
- **多模型支持**：多提供商配置，`/model <模型名>` 或 `/model <提供商>/<模型名>` 快速切换
- **多级项目指令**：个人级 (`~/.octopus/`)、项目级、子目录级指令自动加载
- **跨会话记忆**：`/remember` 持久化记忆，重启后自动加载

## 快速开始

```bash
# 安装依赖
pip install -e .

# 配置文件（必配项：api_key、base_url、model）
mkdir -p ~/.octopus
# 将下方配置示例写入 ~/.octopus/config.json

# 交互模式（Rich TUI）
python octopus.py

# 单次任务（纯文本输出）
python octopus.py "帮我写一个 Python 斐波那契函数"

# 恢复最近会话
python octopus.py -c

# 交互式选择会话恢复
python octopus.py --resume

# 指定新会话名称
python octopus.py -n "重构任务"

# 管道输入
cat file.py | python octopus.py "review this"
```

## 配置

### 配置层级

1. `.octopus/config.local.json`（项目本地级，gitignored）
2. `.octopus/config.json`（项目级）
3. `~/.octopus/config.json`（用户级）
4. 环境变量（最高优先级）

### 配置文件示例

```json
{
  "api_key": "sk-b1a1...c5d4",
  "base_url": "https://api.deepseek.com/anthropic",
  "model": "deepseek-v4-flash",
  "provider": "deepseek",
  "providers": {
    "deepseek": {
      "base_url": "https://api.deepseek.com/anthropic",
      "api_key": "sk-b1a1...c5d4",
      "models": ["deepseek-v4-flash", "deepseek-v4-pro"]
    },
    "zhipu": {
      "base_url": "https://open.bigmodel.cn/api/anthropic",
      "api_key": "sk-zhipu...",
      "models": ["glm-5.1"]
    }
  },
  "max_iterations": 20,
  "permissions": "confirm",
  "mcp_servers": {},
  "cleanup_period_days": 30,
  "hooks": {
    "pre_tool_call": ["echo 'About to call $OCTOPUS_HOOK_TOOL'"],
    "post_tool_call": ["echo 'Tool $OCTOPUS_HOOK_TOOL completed'"]
  },
  "permission_rules": [
    {"tool": "bash", "pattern": "npm test", "action": "allow"},
    {"tool": "bash", "pattern": "npm publish", "action": "deny"}
  ]
}
```

`api_key`、`base_url`、`model` 为必配项。

### 环境变量

| 变量 | 说明 |
|------|------|
| `OCTOPUS_API_KEY` | 覆盖 `api_key` |
| `OCTOPUS_BASE_URL` | 覆盖 `base_url` |
| `OCTOPUS_MODEL` | 覆盖 `model` |
| `OCTOPUS_MAX_TOKENS` | 覆盖 `max_tokens`（需为整数） |
| `OCTOPUS_MAX_ITERATIONS` | 覆盖 `max_iterations`（需为整数） |
| `OCTOPUS_PERMISSIONS` | 覆盖 `permissions` |

### 权限模式

- `auto-approve` — 所有操作自动执行
- `confirm` — 危险操作（rm -rf、git push -f 等）需要确认
- `deny` — 禁止危险操作

细粒度权限通过 `permission_rules` 配置，按工具名 + 正则模式 allow/deny。

## 工具列表

| 工具 | 说明 |
|------|------|
| `bash` | 执行 shell 命令，工作目录持久化，实时流式输出 |
| `read_file` | 读取文件内容，支持 offset/limit 按行号范围读取，>1MB 自动截断 |
| `write_file` | 写入文件（覆盖/追加），>1MB 拒绝 |
| `edit_file` | 精确字符串替换编辑，显示 diff 视图 |
| `list_files` | 目录列表，支持 glob 模式和递归 |
| `grep_search` | 正则文本搜索 |
| `web_search` | 搜索互联网（DuckDuckGo + Wikipedia 多源搜索） |
| `web_fetch` | 抓取网页内容，返回纯文本 |
| `copy_file` | 复制文件，保留元数据 |
| `move_file` | 移动或重命名文件 |
| `delete_file` | 删除文件 |
| `task_create` | 创建结构化任务（支持依赖关系） |
| `task_update` | 更新任务状态/标题/依赖 |
| `task_list` | 列出所有任务 |
| `task_get` | 获取任务详情 |
| `notebook_edit` | 编辑 Jupyter Notebook 单元格 |
| `sub_agent` | 启动子 Agent 并行执行独立任务 |
| `worktree_create` | 创建 git worktree 隔离并行开发 |
| `worktree_remove` | 删除 git worktree |
| `checkpoint_create` | 创建 git 检查点（自动 commit） |
| `checkpoint_rollback` | 回滚到上一个检查点 |
| `schedule_wakeup` | 定时唤醒（60-3600 秒） |
| `cron_create` | 创建周期性定时任务（支持 cron 表达式） |
| `cron_delete` | 取消定时任务 |
| `cron_list` | 列出所有定时任务 |
| `read_image` | 读取图片文件（PNG/JPG/GIF/WebP） |

## Slash 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/init` | 生成项目指令文件 (CLAUDE.md/OCTOPUS.md) |
| `/clear` | 清除对话历史 |
| `/resume [name]` | 交互式选择器切换会话（↑↓ 搜索、摘要预览） |
| `/rename <名称>` | 重命名当前会话 |
| `/export [file]` | 导出对话为文本文件 |
| `/search <关键词>` | 搜索当前对话内容 |
| `/model [model_name]` | 查看/切换模型（`/model <模型名>` 或 `/model <提供商>/<模型名>`） |
| `/models` | 列出已配置的模型 |
| `/agents` | 列出可用 agents |
| `/agent [name]` | 查看/切换当前 agent |
| `/skills` | 列出可用 skills |
| `/skill <name>` | 执行 skill |
| `/config [key=val]` | 查看/修改配置（自动持久化、校验） |
| `/plan` | 切换到 Plan 模式（只读，输出结构化计划） |
| `/auto` | 切换到 Auto 模式（全自动） |
| `/continue` | 继续上次中断的任务 |
| `/review` | 审查当前分支的代码变更 |
| `/compact` | 手动压缩对话上下文 |
| `/remember <内容>` | 保存长期记忆 |
| `/forget` | 清除所有记忆 |
| `/cwd` | 显示工作目录 |
| `/quit` | 退出 |

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Tab` | 触发补全（slash 命令 / 文件路径） |
| `Shift+Tab` | 切换 Plan/Auto 模式 |
| `↑↓` | 浏览输入历史 |
| `Esc + Enter` | 插入换行（多行输入） |
| `Ctrl+C` | 暂停当前任务（可 `/continue` 恢复） |
| `Ctrl+L` | 清屏 |

## 会话管理

参照 Claude Code 的会话管理实现：

- **存储**：JSONL 追加格式，`~/.octopus/projects/<项目路径>/<id>.jsonl`，按项目隔离
- **自动保存**：每轮对话自动追加，crash-safe（损坏行跳过）
- **恢复**：`-c` 恢复最近会话，`--resume` 交互式选择器（↑↓ 导航、搜索过滤、摘要预览）
- **命名**：`-n` 启动时指定，`/rename` 会话内修改
- **导出**：`/export` 导出为纯文本文件
- **清理**：超过 `cleanup_period_days`（默认 30 天）自动删除

## 项目指令

多级加载，优先 `OCTOPUS.md`，无则 fallback 到 `CLAUDE.md`：

1. **个人级** — `~/.octopus/OCTOPUS.md` 或 `~/.claude/CLAUDE.md`
2. **项目级** — 当前目录的 `OCTOPUS.md` 或 `CLAUDE.md`
3. **子目录级** — 各代码模块目录下的指令文件（如 `src/OCTOPUS.md`）

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

## MCP 服务器

支持通过配置连接任意 MCP 工具服务器，断连自动重连：

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

## 项目结构

```
octopus_cli/
├── octopus.py      # 主入口（命令行参数、会话恢复）
├── tui.py          # Rich TUI（流式渲染、会话选择器、token 追踪）
├── commands.py     # Slash 命令注册表（25 个命令）
├── cli.py          # CLI 逻辑（命令分发、权限确认、细粒度规则）
├── agent.py        # Agent 主循环（流式 API、重试、hooks、多模态）
├── tools.py        # 21 个工具 + 执行器 + 任务管理 + Worktree + 检查点 + 调度
├── constants.py    # 共享常量（颜色、版本、限制）
├── config.py       # 配置管理 + Hooks + 细粒度权限 + 三层层级 + 校验
├── context.py      # 上下文压缩（渐进截断）+ 多级指令 + 记忆
├── session.py      # 会话管理（JSONL、索引、清理）
├── mcp.py          # MCP 客户端（自动重连）
├── skills.py       # 自定义 Agent/Skill 加载
├── scheduler.py    # 定时调度器（一次性/周期性唤醒）
├── logger.py       # 轻量级日志基础设施
├── tests/          # 测试套件（94 个测试用例）
├── pyproject.toml  # 项目元数据和依赖
├── CLAUDE.md       # 项目开发指引
└── README.md       # 项目说明
```

## 测试

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## 许可证

MIT
