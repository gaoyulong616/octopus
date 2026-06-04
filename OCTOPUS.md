# Octopus Agent 项目指令

> Python AI Agent CLI — 基于 Anthropic SDK tool-use 能力，让 LLM 通过工具调用自主完成编程任务。
>
> 版本: 2.0.0 | Python >= 3.12

---

## 目录

1. [项目概述](#项目概述)
2. [快速开始](#快速开始)
3. [项目架构](#项目架构)
4. [核心模块说明](#核心模块说明)
5. [运行方式](#运行方式)
6. [配置管理](#配置管理)
7. [工具列表](#工具列表)
8. [Slash 命令](#slash-命令)
9. [开发指南](#开发指南)
10. [测试](#测试)
11. [关键规范](#关键规范)

---

## 项目概述

Octopus Agent 是一个运行在终端中的 AI 编程助手，类似于 Claude Code。它通过 Anthropic SDK 的 tool-use 能力，让大语言模型自主调用工具完成编程任务。

### 核心特性

| 特性 | 说明 |
|------|------|
| **流式输出** | Token 逐字实时渲染，Markdown 正确展示（代码高亮、标题、加粗等） |
| **Token 费用追踪** | 每轮显示 token 用量，会话累计追踪和持久化 |
| **Rich TUI** | 终端 UI，对话搜索、自动保存、任务进度展示 |
| **Extended Thinking** | Anthropic thinking 块，灰色折叠面板展示思考过程 |
| **多模态支持** | `read_image` 读取图片（PNG/JPG/GIF/WebP）进行视觉分析 |
| **多模型支持** | 配置模型别名，`/model <别名>` 快速切换，多提供商支持 |
| **子 Agent 并行** | `sub_agent` 启动独立线程/工作目录并行执行子任务 |
| **Plan/Auto 模式** | Plan 模式输出结构化实施计划，审批后自动切换到 Auto 执行 |
| **MCP 支持** | 连接外部 MCP 工具服务器，断连自动重连 |
| **Git 集成** | Worktree 隔离并行开发、检查点自动快照/回滚 |
| **定时调度** | 一次性唤醒 + 周期性 cron 任务 |
| **上下文管理** | 长对话自动压缩，渐进截断过长 tool_result |
| **会话管理** | JSONL 持久化，按项目隔离，交互式恢复 |
| **多级配置** | 项目本地级 > 项目级 > 用户级 + 环境变量覆盖 |
| **权限管理** | 细粒度规则（工具名 + 正则模式）、危险操作检测 |
| **Hooks 系统** | 工具调用前后触发自定义命令 |
| **自定义扩展** | 自定义 Agents、Skills、项目指令文件 |

---

## 快速开始

### 安装

```bash
# 安装依赖
pip install -e .

# 安装开发依赖（测试、代码检查）
pip install -e ".[dev]"
```

### 配置

**必配项**：`api_key`、`base_url`、`model`

```bash
mkdir -p ~/.octopus
```

写入 `~/.octopus/config.json`（示例）：

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

### 运行

```bash
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

# 安全模式（仅读取类工具）
python octopus.py "分析代码" --safe

# Web UI 模式
python octopus.py --web --port 8765

# 从 stdin 读取
cat requirements.txt | python octopus.py --stdin "安装这些依赖"
```

---

## 项目架构

```
octopus_cli/
├── octopus.py          # 主入口：参数解析、会话恢复、模式分发
├── tui.py              # Rich TUI（流式渲染、会话选择器、状态栏、任务追踪）
├── cli.py              # CLI 交互循环、权限确认、信号处理
├── agent.py            # Agent 主循环：LLM 流式调用、工具执行、重试
├── commands.py         # Slash 命令注册表（25+ 命令，装饰器注册）
│
├── config.py           # 配置管理（三层层级 + 环境变量）、Hooks 系统、权限规则
├── context.py          # 系统提示词构建、上下文压缩、多级指令加载、记忆管理
├── session.py          # 会话持久化（JSONL）、索引、清理
├── skills.py           # 自定义 Agent/Skill 加载、解析、渲染
│
├── tools/              # 工具实现包（21+ 个工具）
│   ├── __init__.py     # 向后兼容导出所有工具函数
│   ├── schemas.py      # 工具 Schema 定义（服务端/客户端双版本）
│   ├── registry.py     # 工具注册表 + execute_tool 执行器
│   ├── bash.py         # bash 工具 + 工作目录管理
│   ├── file_ops.py     # 读写/编辑/复制/移动/删除/搜索/图片
│   ├── web_tools.py    # web_search / web_fetch
│   ├── notebook.py     # Jupyter Notebook 编辑
│   ├── agent_tools.py  # sub_agent / ask_user_question
│   ├── git_tools.py    # worktree_create/remove / checkpoint_create/rollback
│   ├── sched_tools.py  # schedule_wakeup / cron_create/delete/list
│   ├── permissions.py  # 权限常量 + 工具摘要
│   ├── exceptions.py   # ToolError 异常
│   ├── security.py     # 安全检查
│   └── state.py        # AgentState（任务管理）
│
├── mcp.py              # MCP 客户端（stdio/HTTP 传输，自动重连）
├── scheduler.py        # 定时调度器（持久化、线程安全）
├── metrics.py          # Token 用量持久化 + 成本估算
│
├── logger.py           # 轻量级日志（~/.octopus/octopus.log）
├── statusline.py       # 状态栏模板渲染
├── constants.py        # 共享常量：ANSI 颜色、文件限制、版本号
│
├── web/                # Web UI 模块
│   ├── app.py          # FastAPI 启动
│   ├── agent_bridge.py # Web ↔ Agent 桥接
│   ├── events.py       # SSE 事件
│   ├── routes_api.py   # REST API 路由
│   ├── routes_ws.py    # WebSocket 路由
│   └── static/         # 前端静态文件
│
├── tests/              # 测试套件（94+ 测试用例）
│   ├── test_config.py
│   ├── test_config_safety.py
│   ├── test_agent_hooks.py
│   ├── test_session.py
│   ├── test_tools.py
│   ├── test_context.py
│   ├── test_security.py
│   ├── test_skills.py
│   ├── test_scheduler.py
│   ├── test_metrics.py
│   ├── test_statusline.py
│   └── test_builtin_permissions.py
│
├── pyproject.toml      # 项目元数据、依赖、工具配置
├── README.md           # 项目说明
└── OCTOPUS.md          # 本文件：项目指令（AI 读取）
```

### 核心调用流程

```
用户输入
  │
  ▼
octopus.py (入口)
  │
  ├── 单次任务 → agent.run_agent()
  ├── 交互模式 → cli.interactive_mode() → tui.interactive_mode()
  └── Web 模式 → web.app.launch_web()
                    │
                    ▼
              agent.py (主循环)
                    │
                    ├── 构建 system prompt (context.build_system_prompt)
                    ├── 构建 tool schema (tools.schemas.build_tools)
                    ├── 流式调用 LLM (anthropic SDK stream)
                    │     ├── 实时输出 token (EVT_STREAM)
                    │     ├── 输出 thinking (EVT_THINKING)
                    │     └── 处理工具调用 (EVT_TOOL_CALL)
                    │
                    ├── 执行工具 (tools.registry.execute_tool)
                    │     ├── 内置工具 → 直接调用 handler
                    │     ├── MCP 工具 → mcp.call_tool()
                    │     └── 结果回传给 LLM
                    │
                    ├── 上下文压缩 (context.compress_messages)
                    ├── 会话保存 (session.save_session)
                    └── 重复直到无工具调用
```

---

## 核心模块说明

### 1. `octopus.py` — 主入口

命令行参数解析，支持：
- **单次任务**：直接传入 `"任务描述"`，输出纯文本
- **交互模式**：无参数启动 Rich TUI
- **会话恢复**：`-c` 恢复最近、`--resume` 交互选择
- **管道输入**：自动检测 `stdin` 非 tty
- **Web UI**：`--web` 启动 FastAPI Web 服务
- **安全模式**：`--safe` 仅允许读取类工具

### 2. `agent.py` — Agent 主循环

核心职责：
- **Client 单例**：配置不变时复用 anthropic client
- **服务端工具探测**：自动检测 API 提供商是否支持 `web_search`/`web_fetch` 服务端工具
- **流式重试**：429/500/网络错误自动重试（指数退避，最多 3 次）
- **事件驱动**：通过 `output_fn` 回调输出 `EVT_STREAM`/`EVT_THINKING`/`EVT_TOOL_CALL` 等事件
- **多轮循环**：LLM 返回工具调用 → 执行工具 → 结果回传 → 继续循环，直到返回纯文本
- **Hooks 触发**：PreToolUse、PostToolUse、PreCompact、PostCompact、Stop
- **安全模式**：只允许 `_READ_TOOLS` 内的工具

### 3. `tui.py` — Rich TUI

Rich 渲染的终端 UI：
- **流式渲染**：`Live` 面板实时刷新 markdown/text
- **Thinking 折叠**：灰色面板展示思考过程
- **Token 追踪**：每轮显示用量，会话累计
- **Task 进度**：任务列表 ✔/◻ 彩色状态指示器
- **状态栏**：可配置模板（模型、分支、路径、token 数）
- **会话选择器**：↑↓ 导航、搜索过滤、摘要预览
- **补全系统**：Tab 补全 slash 命令和文件路径
- **快捷键**：`Shift+Tab` 切模式、`Ctrl+C` 暂停/中断

### 4. `cli.py` — CLI 逻辑

交互式 CLI 回退方案（无 Rich 时）：
- **权限确认**：四档选择（执行/会话放行/永久放行/拒绝）
- **信号处理**：首次 `Ctrl+C` 中断，再次强制退出
- **Session 放行**：`[s/a]` 本次会话放行某工具

### 5. `config.py` — 配置管理

**三层层级**（高优先级覆盖低）：
1. `.octopus/config.local.json` — 项目本地（gitignored，机器特定）
2. `.octopus/config.json` — 项目级
3. `~/.octopus/config.json` — 用户级
4. 环境变量 — 最高优先级

**环境变量**：
- `OCTOPUS_API_KEY`、`OCTOPUS_BASE_URL`、`OCTOPUS_MODEL`
- `OCTOPUS_MAX_TOKENS`、`OCTOPUS_MAX_ITERATIONS`、`OCTOPUS_PERMISSIONS`

**多提供商支持**：通过 `providers` 和 `provider` 字段按名称切换 API 凭据。

**细粒度权限规则**：`permission_rules` 数组，按工具名 + 正则匹配 allow/deny。

**危险操作检测**：内置危险命令列表，支持绕过检测（引号、子shell、管道注入等）。

**Hooks 系统**：6 个事件点（SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、Stop、PreCompact），支持自定义 shell 命令。

**目录信任**：首次打开新目录提示确认，不信任则自动进入 Plan 模式。

### 6. `context.py` — 上下文管理

- **系统提示词**：构建 system prompt（项目指令 + 工具列表 + 记忆 + Plan/Auto 模式约束）
- **上下文压缩**：超过 `context_threshold`（默认 120K tokens）时自动压缩历史摘要
- **多级指令**：个人级 → 项目级 → 子目录级
- **记忆系统**：类型化（user/feedback/project/reference），持久化到 `~/.octopus/memory/`
- **跨会话记忆**：`/remember` 保存，重启后自动加载

### 7. `session.py` — 会话管理

- **存储格式**：JSONL 追加写，每条消息一行 JSON
- **路径**：`~/.octopus/projects/<编码路径>/<id>.jsonl`，按项目隔离
- **Crash-safe**：损坏行自动跳过
- **元数据索引**：内存缓存 + 文件索引，支持按名称/ID 搜索
- **自动清理**：超过 `cleanup_period_days`（默认 30 天）自动删除

### 8. `tools/` — 工具实现

每个工具独立一个文件，通过 `registry.py` 注册到 `TOOL_HANDLERS` 字典。

#### 工具分类

| 分类 | 工具 | 说明 |
|------|------|------|
| **Bash** | `bash` | shell 命令执行，工作目录持久化，实时流式输出 |
| **文件读取** | `read_file` | 支持 offset/limit，>1MB 自动截断 |
| | `read_image` | 读取图片（PNG/JPG/GIF/WebP） |
| | `list_files` | 目录列表，支持 glob 和递归 |
| | `grep_search` | 正则文本搜索 |
| **文件写入** | `write_file` | 覆盖/追加，>1MB 拒绝 |
| | `edit_file` | 精确字符串替换，显示 diff |
| | `multi_edit` | 批量多文件编辑 |
| **文件操作** | `copy_file` | 复制文件，保留元数据 |
| | `move_file` | 移动/重命名 |
| | `delete_file` | 删除文件 |
| **Web** | `web_search` | 互联网搜索（DuckDuckGo + Wikipedia） |
| | `web_fetch` | 网页内容抓取 |
| **任务管理** | `task_create` / `task_update` / `task_list` / `task_get` | 带依赖关系的结构化任务 |
| **子 Agent** | `sub_agent` | 并行执行独立子任务 |
| **Git** | `worktree_create` / `worktree_remove` | 隔离工作目录并行开发 |
| | `checkpoint_create` / `checkpoint_rollback` | 检查点快照 / 回滚 |
| **定时调度** | `schedule_wakeup` | 一次性唤醒（60-3600 秒） |
| | `cron_create` / `cron_delete` / `cron_list` | 周期性 cron 任务 |
| **Notebook** | `notebook_edit` | 编辑 Jupyter Notebook 单元格 |
| **其他** | `ask_user_question` | 向用户提问并获取选择 |
| | `invoke_skill` | 按需加载执行 Skill |
| | `submit_plan` | Plan 模式下提交实施计划 |

### 9. `mcp.py` — MCP 客户端

- 支持 **stdio**（子进程 stdin/stdout）和 **HTTP** 传输
- 断连自动重连
- 线程安全，支持并发调用
- 与内置工具统一路由（`mcp.has_tool()` → `mcp.call_tool()`）

### 10. `scheduler.py` — 定时调度器

- **一次性唤醒**：`schedule_wakeup`，指定延迟秒数后触发
- **周期性任务**：`cron_create`，标准 cron 表达式
- **持久化**：任务保存到 `~/.octopus/scheduled_jobs.json`，重启自动恢复
- **线程安全**：`threading.Lock` 保护

### 11. `metrics.py` — Token 用量追踪

- **持久化**：`~/.octopus/metrics.jsonl`，每行一条 JSON
- **成本估算**：内置 Claude 4.x/3.x + DeepSeek 系列价格
- **聚合查询**：按 session/model/时间范围聚合
- **上下文管理器**：`metrics.timer()` 方便 agent.py 中包裹 API 调用

### 12. `web/` — Web UI

基于 FastAPI + WebSocket/SSE：
- **REST API**：会话管理、配置管理
- **WebSocket**：实时流式输出
- **Agent Bridge**：Web 请求 ↔ Agent 调用适配

---

## 运行方式

### 交互模式（推荐）

```bash
python octopus.py
```

Rich TUI 界面，支持：
- `Tab` — 补全 slash 命令/文件路径
- `Shift+Tab` — 切换 Plan/Auto 模式
- `Ctrl+C` — 暂停/中断当前任务
- `↑↓` — 浏览输入历史
- `/help` — 查看全部命令

### 单次任务模式

```bash
# 简单任务
python octopus.py "列出当前目录下的 Python 文件"

# 管道输入
curl -s https://example.com/api | python octopus.py "分析这个 JSON"

# 安全模式（只读）
python octopus.py --safe "分析项目结构"
```

### 会话恢复

```bash
# 恢复最近会话
python octopus.py -c

# 交互式选择
python octopus.py --resume

# 按名称恢复
python octopus.py --resume my-session-name
```

### Web UI 模式

```bash
python octopus.py --web --port 8765
# 浏览器打开 http://localhost:8765
```

---

## 配置管理

### 配置层级（优先级从高到低）

| 层级 | 路径 | 说明 |
|------|------|------|
| 环境变量 | `OCTOPUS_*` | 最高优先级 |
| 项目本地 | `.octopus/config.local.json` | 机器特定，gitignored |
| 项目级 | `.octopus/config.json` | 项目共享配置 |
| 用户级 | `~/.octopus/config.json` | 全局默认配置 |

### 权限模式

| 模式 | 行为 |
|------|------|
| `auto-approve` | 所有操作自动执行 |
| `confirm`（默认） | 危险操作需确认（rm -rf、git push -f 等） |
| `deny` | 禁止危险操作 |

### 细粒度权限规则

```json
{
  "permission_rules": [
    {"tool": "bash", "pattern": "npm test", "action": "allow"},
    {"tool": "bash", "pattern": "npm publish", "action": "deny"},
    {"tool": "write_file", "pattern": "src/.*", "action": "allow"}
  ]
}
```

### Hooks 系统

支持的事件点：

| 事件 | 触发时机 | 环境变量 |
|------|----------|----------|
| `SessionStart` | 会话启动 | `OCTOPUS_HOOK_SESSION_ID`, `OCTOPUS_HOOK_CWD`, `OCTOPUS_HOOK_MODEL` |
| `UserPromptSubmit` | 用户提交输入前 | `OCTOPUS_HOOK_PROMPT` |
| `PreToolUse` | 工具调用前 | `OCTOPUS_HOOK_TOOL`, `OCTOPUS_HOOK_INPUT` |
| `PostToolUse` | 工具调用后 | `OCTOPUS_HOOK_TOOL`, `OCTOPUS_HOOK_RESULT_PREVIEW` |
| `Stop` | 一次回复完成 | `OCTOPUS_HOOK_ITERATIONS`, `OCTOPUS_HOOK_FINAL_TEXT` |
| `PreCompact` | 上下文压缩前 | `OCTOPUS_HOOK_MESSAGE_COUNT` |

### MCP 服务器配置

```json
{
  "mcp_servers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "ghp_xxx"}
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed"]
    }
  }
}
```

---

## 工具列表

完整的 26 个内置工具（按分类）：

### 执行类
- **`bash`** — shell 命令执行，流式实时输出，支持超时

### 文件读取
- **`read_file`** — 读取文件，支持 offset/limit，>1MB 自动截断
- **`read_image`** — 读取图片（PNG/JPG/GIF/WebP），base64 编码返回
- **`list_files`** — 目录列表，glob + 递归
- **`grep_search`** — 正则文本搜索

### 文件写入
- **`write_file`** — 写入文件（覆盖/追加），>1MB 拒绝
- **`edit_file`** — 精确字符串替换，显示 diff 视图
- **`multi_edit`** — 批量编辑多个文件

### 文件操作
- **`copy_file`** — 复制文件，保留元数据
- **`move_file`** — 移动/重命名文件
- **`delete_file`** — 删除文件

### 网络
- **`web_search`** — 互联网搜索（DuckDuckGo + Wikipedia）
- **`web_fetch`** — 网页内容抓取

### 任务管理
- **`task_create`** — 创建结构化任务（支持依赖关系）
- **`task_update`** — 更新任务状态/标题/依赖
- **`task_list`** — 列出所有任务
- **`task_get`** — 获取任务详情

### Agent
- **`sub_agent`** — 启动子 Agent 并行执行子任务
- **`invoke_skill`** — 按需加载执行 Skill
- **`ask_user_question`** — 向用户提问并选择

### Git
- **`worktree_create`** — 创建 git worktree 隔离并行开发
- **`worktree_remove`** — 删除 git worktree
- **`checkpoint_create`** — 创建 git 检查点（自动 commit）
- **`checkpoint_rollback`** — 回滚到上一个检查点

### 定时调度
- **`schedule_wakeup`** — 定时唤醒（60-3600 秒）
- **`cron_create`** — 创建周期性定时任务
- **`cron_delete`** — 取消定时任务
- **`cron_list`** — 列出所有定时任务

### Notebook
- **`notebook_edit`** — 编辑 Jupyter Notebook 单元格（code/markdown 模式）

### Plan
- **`submit_plan`** — Plan 模式下提交结构化实施计划

---

## Slash 命令

共 25+ 个 `/` 命令，通过 `commands.py` 的装饰器 `@_register(name, desc)` 注册：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/init` | 生成项目指令文件 (CLAUDE.md/OCTOPUS.md) |
| `/clear` | 清除对话历史 |
| `/resume [name]` | 交互式选择器切换会话 |
| `/rename <名称>` | 重命名当前会话 |
| `/export [file]` | 导出对话为文本文件 |
| `/search <关键词>` | 搜索当前对话内容 |
| `/model [alias/name]` | 查看/切换模型 |
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

---

## 开发指南

### 代码风格

- **Python >= 3.12**：充分利用新语法特性
- **行长度**：120 字符
- **类型注解**：重要函数需类型标注
- **代码检查**：使用 ruff（配置见 pyproject.toml）
  ```bash
  ruff check .
  ruff format .
  ```

### 添加新工具

1. 在 `tools/` 目录下创建新文件，实现工具函数
2. 在 `tools/__init__.py` 中导出
3. 在 `tools/registry.py` 的 `TOOL_HANDLERS` 字典中注册
4. 在 `tools/schemas.py` 中添加工具 Schema 定义
5. 在 `tools/permissions.py` 中更新 `READ_TOOLS`/`WRITE_TOOLS`（如需要）
6. 在 `README.md` 和 `OCTOPUS.md` 中更新工具列表
7. 在 `tests/` 下添加测试用例

### 添加新 Slash 命令

1. 在 `commands.py` 中使用 `@_register("/命令名", "描述")` 装饰器注册处理函数
2. 函数签名：`def cmd_xxx(cmd: str, messages: list[dict], state: dict) -> CommandResult`
3. 在 `README.md` 和 `OCTOPUS.md` 中更新命令列表

### 添加新配置项

1. 在 `config.py` 的 `_DEFAULTS` 字典中添加默认值
2. 在 `_VALIDATORS` 中添加校验器（可选）
3. 在 `_setup_validators()` 中添加校验逻辑

### 测试

```bash
# 运行全部测试
pytest tests/ -v

# 带覆盖率
pytest tests/ --cov=. --cov-report=term-missing

# 运行单个测试文件
pytest tests/test_config.py -v

# 跳过网络相关测试
pytest tests/ -v -k "not web"
```

### 构建

```bash
# 构建分发版本
python -m build

# 发布到 PyPI
twine upload dist/*
```

### 注意事项

- **配置兼容性**：修改 `_DEFAULTS` 时注意向后兼容
- **事件类型**：agent.py 中的事件类型常量（`EVT_*`）是 TUI/CLI/Web 的输出契约，修改需同步更新所有消费端
- **文件大小限制**：读取 >1MB 自动截断、写入 >1MB 拒绝（`constants.MAX_FILE_SIZE`）
- **CWD 持久化**：`tools.bash` 中维护全局 `_cwd`，所有文件操作相对此路径
- **Client 单例**：`agent._get_client()` 缓存 anthropic client，配置变更时自动重建
- **配置文件缓存**：`config._config_cache` 自动检测 mtime 变化刷新
- **MCP 重连**：`mcp.py` 中自动重试断开连接

---

## 关键规范

### 导入路径

所有模块通过相对项目根目录的绝对导入：

```python
# 正确
from tools import execute_tool
from agent import run_agent
from config import get

# 避免
from .tools import execute_tool  # 包内相对导入可能引起问题
```

### 事件协议

agent.py 通过 `output_fn` 回调输出事件，TUI/CLI/Web 各自消费：

```python
output_fn(event_type, text, metadata)
```

| 事件类型 | 触发时机 | metadata |
|----------|----------|----------|
| `EVT_STREAM` | LLM 输出 token | — |
| `EVT_THINKING` | Extended thinking | — |
| `EVT_TOOL_CALL` | 工具调用 | `{"tool", "input", "tool_id"}` |
| `EVT_TOOL_RESULT` | 工具返回 | `{"tool", "full_result"}` |
| `EVT_RESPONSE` | 最终回复 | `{"usage"}` |
| `EVT_PROGRESS` | 进度信息 | `{"label"}` |
| `EVT_ERROR` | 错误信息 | — |

### 测试策略

- 配置文件测试使用临时目录隔离
- 工具测试需要 mock `anthropic` SDK
- 会话测试使用临时 JSONL 文件
- 不依赖外部网络（mock web 工具）

---

*此文件由 `/init` 命令生成，作为 AI Agent 的项目指令。AI 在首次进入项目时会自动读取此文件了解项目结构和规范。*
