# Octopus Agent

Python AI Agent CLI，基于 LLM Provider 抽象层的 tool-use 能力，支持 Anthropic 原生 API 和 OpenAI 兼容 API（DeepSeek、GLM、Qwen、GPT 等），让 LLM 通过工具调用自主完成编程任务。

## 特性

### 核心能力
- **流式输出**：token 逐字实时渲染，最终以 Markdown 格式正确展示（代码高亮、标题、加粗等）
- **Token 费用追踪**：每轮显示 token 用量，会话累计追踪，持久化 metrics 记录（`~/.octopus/metrics.jsonl`）
- **TUI 界面**：Rich 渲染终端 UI，对话搜索，自动保存，任务进度展示
- **Web UI**：FastAPI + WebSocket 实时 Web 界面，支持多浏览器标签同时连接，Mermaid 图表渲染、ECharts 数据图表、交互式分页表格、视频/音频/图片播放展示（含灯箱动画）、语音输入、拖拽上传、会话导出（HTML/PDF）、会话置顶、Diff 渲染、生成文件下载卡片、外部下载链接卡片
- **多用户支持**：完整的用户注册/登录系统，JWT 认证，用户目录隔离，Bubblewrap 沙箱资源限制
- **Extended Thinking**：支持 Anthropic thinking 块，灰色折叠面板展示思考过程
- **多模态支持**：`read_image` 读取图片（PNG/JPG/GIF/WebP），发送给模型进行视觉分析
- **31 个内置工具**：bash、文件读写/编辑/多文件编辑/复制/移动/删除、目录浏览、文本搜索、Web 搜索/抓取、任务管理、Notebook 编辑、子 Agent、Worktree、检查点、定时调度、图片读取、用户交互、Skill 调用等

### Agent 能力
- **子 Agent 并行执行**：`sub_agent` 启动独立线程执行子任务
- **用户交互**：`ask_user_question` 让 Agent 主动向用户提问并等待回复
- **结构化任务管理**：`task_create/update/list/get` 创建带依赖关系的任务
- **Git Worktree**：创建隔离工作目录并行开发不同分支
- **Git 检查点**：破坏性操作前自动快照，可一键回滚
- **定时调度**：`schedule_wakeup` 一次性唤醒，`cron_create` 周期性任务
- **三档权限模式**：`Shift+Tab` 循环切换
  - **Plan**：完全只读分析，输出结构化实施计划，支持审批流程（`enter_plan_mode` + `submit_plan`）
  - **Accept Edits**（默认）：文件编辑自动放行；bash 命令/破坏性操作需用户确认
  - **Auto**：全自动执行（YOLO），仅建议在信任目录使用
- **Skill 调用**：`invoke_skill` 工具化加载 Skill 模板
- **ReAct 主循环健壮性**：迭代上限（默认 50，可配置）、max_tokens 截断自动续写（连续 3 次后停止）、refusal 立即终止、pause_turn 续写、tool 失败熔断（同一调用连续失败超阈值跳过）
- **Agent 人设追加层**：`/agent` 切换的人设作为独立 cache 块**追加**到 L1/L2/L3 三层之后，保留所有工具规范和记忆（不再像旧版替换主系统提示词导致行为规范丢失）

### 安全与配置
- **权限确认**：写入操作前确认，支持 `[a]` 一键放行同类工具
- **细粒度权限规则**：按工具名 + 正则模式配置 allow/deny（如允许 `npm test` 但拒绝 `npm publish`）
- **Hooks 系统**：工具执行前后触发自定义命令
- **三层配置层级**：项目本地级 > 项目级 > 用户级，环境变量覆盖
- **目录信任**：首次打开新目录提示确认，不信任则自动进入 Plan 模式
- **上下文管理**：双视图消息分离（UI 展示全量原始历史，LLM 接收压缩视图），分段压缩支持大尺度会话恢复，根据模型上下文窗口自动计算阈值
- **自适应 UI 输出**：Web UI 提示词声明 mermaid@11/markdown/monaco 支持，TUI 声明 Rich 渲染能力，LLM 按当前 UI 能力选择输出格式（图表/markdown/纯文本）
- **API 重试**：429 限速/500 错误自动重试，指数退避，401 友好提示
- **成本估算**：按模型定价自动估算每次调用和会话累计费用

### 交互体验
- **Bash 实时流式**：长命令逐行实时输出，不等完成
- **文件保护**：读取 >1MB 文件自动截断，写入限制大小
- **Diff 视图**：`edit_file` 操作显示 `+` 绿底/`-` 红底的代码变更 diff
- **多文件编辑**：`multi_edit` 一次调用编辑多个位置
- **任务进度**：LLM 规划任务列表，✔/◻ 彩色状态指示器实时展示
- **补全系统**：Tab 补全 slash 命令和文件路径，匹配字符蓝色高亮
- **输入历史**：自动保存命令历史，上下箭头浏览
- **任务暂停**：`Ctrl+C` 暂停任务，随时旁问，`/continue` 恢复
- **Statusline**：可自定义模板的顶部/底部状态栏（显示模型、分支、目录、token、费用等）

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

# Web UI 模式
python octopus.py --web
# 浏览器访问 http://localhost:8765
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
  "host": "api.deepseek.com",
  "providers": {
    "deepseek": {
      "base_url": "https://api.deepseek.com/anthropic",
      "api_key": "sk-b1a1...c5d4",
      "host": "api.deepseek.com",
      "models": [
        {"name": "deepseek-v4-flash", "context_window": 1000000},
        {"name": "deepseek-v4-pro", "context_window": 1000000}
      ]
    },
    "zhipu": {
      "base_url": "https://open.bigmodel.cn/api/anthropic",
      "api_key": "sk-zhipu...",
      "host": "open.bigmodel.cn",
      "models": [
        {"name": "glm-5.1", "context_window": 200000}
      ]
    },
    "ds_openai": {
      "type": "openai",
      "base_url": "https://api.deepseek.com",
      "api_key": "sk-b1a1...c5d4",
      "host": "api.deepseek.com",
      "models": [
        {"name": "deepseek-chat", "context_window": 64000}
      ]
    }
  },
  "permissions": "confirm",
  "mcp_servers": {},
  "video_directory": "/home/user/videos",
  "music_directory": "/home/user/music",
  "image_directory": "/home/user/images",
  "cleanup_period_days": 30,
  "statusline": "{model}  |  {git_branch}  |  {cwd}  |  {tokens} tokens  |  ${cost}",
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

### Provider 抽象层

支持多 Provider 架构，内部统一使用 Anthropic 风格 content blocks，只在 API 边界做格式转换：

- **Anthropic Provider**（默认）：直连 Anthropic 原生 API，支持 cache_control / Extended Thinking / 服务端工具
- **OpenAI Provider**：兼容 OpenAI API 格式的各种服务（DeepSeek、GPT、GLM、Qwen 等），自动转换消息和工具调用格式
- **Provider 名称映射**：`"provider": "ds_openai"` 自动使用 `OpenAIProvider`，也可在 provider 配置中设置 `"type": "openai"` 指定
- **模型自动检测**：模型名含 `gpt`/`o1`/`deepseek`/`glm`/`qwen` 等关键字时自动推断为 openai 类型

`api_key`、`base_url` 按活跃 provider 自动切换：
```json
{
  "provider": "ds_openai",
  "providers": {
    "ds_openai": {
      "base_url": "https://api.deepseek.com",
      "api_key": "sk-deepseek..."
    }
  }
}
```

### 环境变量

| 变量 | 说明 |
|------|------|
| `OCTOPUS_API_KEY` | 覆盖 `api_key` |
| `OCTOPUS_BASE_URL` | 覆盖 `base_url` |
| `OCTOPUS_HOST` | 覆盖 `host`（自定义 HTTP Host header） |
| `OCTOPUS_MODEL` | 覆盖 `model` |
| `OCTOPUS_MAX_TOKENS` | 覆盖 `max_tokens`（需为整数） |
| `OCTOPUS_PERMISSIONS` | 覆盖 `permissions` |

### 权限模式

- `auto-approve` — 所有操作自动执行
- `confirm` — 危险操作（rm -rf、git push -f 等）需要确认
- `deny` — 禁止危险操作

细粒度权限通过 `permission_rules` 配置，按工具名 + 正则模式 allow/deny。

## 工具列表

| 工具 | 说明 |
|------|------|
| `bash` | 执行 shell 命令，工作目录持久化，支持后台运行和实时流式输出 |
| `read_file` | 读取文件内容，支持 offset/limit 按行号范围读取，>1MB 自动截断 |
| `write_file` | 写入文件（覆盖/追加），>1MB 拒绝 |
| `edit_file` | 精确字符串替换编辑，显示 diff 视图 |
| `multi_edit` | 一次调用编辑多个位置 |
| `list_files` | 目录列表，支持 glob 模式和递归 |
| `grep_search` | 正则文本搜索 |
| `web_search` | 搜索互联网（DuckDuckGo + Wikipedia 多源搜索） |
| `web_fetch` | 抓取网页内容，返回纯文本 |
| `copy_file` | 复制文件，保留元数据 |
| `move_file` | 移动或重命名文件 |
| `delete_file` | 删除文件 |
| `ask_user_question` | 向用户提问并等待回复（支持选项列表） |
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
| `read_image` | 读取图片文件（PNG/JPG/GIF/WebP，最大 20MB） |
| `invoke_skill` | 加载并渲染 Skill 模板 |
| `enter_plan_mode` | 请求进入 Plan 模式 |
| `submit_plan` | 提交实施计划供用户审批 |

## Slash 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/init` | 生成精简 AI 协作指令 (OCTOPUS.md，对标 CLAUDE.md 30-80 行) |
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
| `/accept-edits` | 切换到 Accept Edits 模式（默认；编辑自动，命令/破坏性操作需确认） |
| `/auto` | 切换到 Auto 模式（全自动） |
| `/continue` | 继续上次中断的任务 |
| `/review` | 按严重度分级审查代码变更（🔴阻断/🟠重要/🟡次要/❓提问） |
| `/diff` | 查看当前未提交的变更 |
| `/context` | 查看当前上下文信息（消息数、token 估算等） |
| `/thinking` | 切换 Extended Thinking 开关 |
| `/compact` | 手动压缩对话上下文 |
| `/remember <内容>` | 保存长期记忆 |
| `/forget` | 清除所有记忆 |
| `/memory` | 查看已保存的记忆 |
| `/permissions` | 查看当前权限配置 |
| `/stats` | 查看当前会话统计（token 用量、费用等） |
| `/cwd` | 显示工作目录 |
| `/quit` | 退出 |

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Tab` | 触发补全（slash 命令 / 文件路径） |
| `Shift+Tab` | 循环切换权限模式：Plan → Accept Edits → Auto |
| `↑↓` | 浏览输入历史 |
| `Esc + Enter` | 插入换行（多行输入） |
| `Ctrl+C` | 暂停当前任务（可 `/continue` 恢复） |
| `Ctrl+L` | 清屏 |

## 会话管理

- **存储**：JSONL 追加格式，`~/.octopus/projects/<项目路径>/<id>.jsonl`，按项目隔离
- **自动保存**：每轮对话自动追加，crash-safe（损坏行跳过）
- **保存去重**：基于 messages 内容 hash 缓存，刷新页面 / 切换会话时若内容未变自动跳过写盘
- **空会话丢弃**：用户未发任何消息就刷新或切换，session 不写盘、不留空文件
- **恢复**：`-c` 恢复最近会话，`--resume` 交互式选择器（↑↓ 导航、搜索过滤、摘要预览）
- **命名**：`-n` 启动时指定，`/rename` 会话内修改
- **导出**：`/export` 导出为纯文本文件
- **清理**：超过 `cleanup_period_days`（默认 30 天）自动删除

## Metrics

每次 API 调用自动记录到 `~/.octopus/metrics.jsonl`，包含：
- Token 用量（input / output / cache read / cache write）
- 调用延迟
- 按模型定价估算费用
- 模型名称和时间戳

通过 `/stats` 查看当前会话的累计统计。

## Statusline

通过 `config.json` 的 `statusline` 字段配置底部状态栏模板：

```
"statusline": "{model}  |  {git_branch}  |  {cwd}  |  {tokens} tokens  |  ${cost}"
```

可用占位符：`{model}`、`{cwd}`、`{cwd_full}`、`{git_branch}`、`{tokens}`、`{session_id}`、`{cost}`

## 项目指令

多级加载 `OCTOPUS.md`：

1. **个人级** — `~/.octopus/OCTOPUS.md`
2. **项目级** — 当前目录的 `OCTOPUS.md`
3. **子目录级** — 各代码模块目录下的指令文件

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

## Web UI

内置 FastAPI + WebSocket Web 界面：

```bash
python octopus.py --web
# 访问 http://localhost:8765
```

特性：
- 实时流式对话渲染
- 内置 Web 终端（基于 xterm.js + PTY，浏览器内直接使用 shell）
- 内置文件浏览器（Monaco Editor + 文件树，双击编辑，支持二进制检测、Ctrl+S 保存）
- 工具调用展示和权限确认对话框
- 任务进度显示
- Mermaid 图表渲染（支持时序图、流程图、甘特图等，svg 高度自适应封顶 500px 避免过度占用消息区）
- ECharts 数据图表（柱状/折线/饼/散点/雷达/热力等，支持全屏 FLIP 动画）
- 交互式分页表格（排序、筛选、分页）
- 视频播放（自动检测 `/videos/` 链接，替换为 `<video>` 播放器，支持 HTTP Range 流式播放）
- 音频播放（自动检测 `/music/` 链接，替换为 `<audio>` 播放器）
- 图片展示（自动检测 `/images/` 链接，替换为 `<img>` 自适应页面宽度，支持子目录，历史会话恢复时同样正确渲染预览）
- 图片灯箱（点击放大全屏，淡入淡出 + 弹性缩放动画，支持下载）
- 文档预览（jit-viewer 内嵌渲染 PDF/DOCX/XLSX/PPT/图片/文本/音视频，链接可点击展开，支持缩放/全屏/旋转/下载/打印。LLM 引用规则：列表场景纯文本列文件名不加链接；推荐场景纯文本列候选后**整次回复最多 1 条** `/docs/` 链接，避免卡片塞满界面）
- 生成文件下载（LLM 在最终回复正文里输出 `[文件名](/dl/绝对路径去前导斜杠)` markdown 链接，前端自动渲染为带图标和强调色边框的下载卡片，点击通过 `/api/file/download` 流式下载。后端带敏感路径黑名单 + 用户隔离 + 200MB 上限）
- 外部下载链接（MinIO / OSS / S3 / 内部文件服务 / 第三方 CDN 等不在 octopus 本地可访问的下载链接）：LLM 输出 `[文件名](URL "download")`——title 必须严格小写 `download`，前端识别该标记渲染为与本地下载一致的卡片，点击 `window.open(href, "_blank", "noopener,noreferrer")` 在新标签页打开，不走 octopus 代理、不经敏感路径校验，由目标服务器直接处理下载）
- 会话置顶（Pin/取消置顶，图标旋转弹跳 + 行高亮闪现 + 置顶常驻微光动画）
- 语音输入（基于 Web Speech API，录音中按钮红色脉冲动画，结果追加到输入框）
- 拖拽上传（拖拽图片/文本文件到对话区或输入框自动处理，文本文件转代码块拼入输入框）
- Diff 渲染（自动检测 `diff` 代码块，绿色添加行 / 红色删除行内渲染）
- HTML/PDF 导出（保留气泡效果、ECharts 图表转 PNG 嵌入、表格全量展开、图片 data URL 嵌入、灯箱效果）
- 媒体元信息：各目录下可放置 JSONL 文件（`videos.jsonl` / `music.jsonl` / `images.jsonl`），格式 `{"file":"文件名","title":"标题","desc":"描述"}`，LLM 可读取后推荐
- 会话右键菜单：重命名（行内编辑）/ 删除 / 断开会话 / 恢复会话，菜单项根据会话状态自动禁用。左键点击活跃会话直接断开
- 多浏览器标签同时连接（per-connection 状态隔离）

## 项目结构

```
octopus_cli/
├── octopus.py          # 主入口（命令行参数、会话恢复）
├── tui.py              # Rich TUI（流式渲染、会话选择器、token 追踪）
├── commands.py         # Slash 命令注册表（29 个命令）
├── cli.py              # CLI 逻辑（命令分发、权限确认、细粒度规则）
├── agent.py            # Agent 主循环（流式 API、重试、hooks、多模态）
├── context.py          # 上下文压缩（模型自适应阈值）+ 多级指令 + 记忆
├── config.py           # 配置管理 + Hooks + 细粒度权限 + 三层层级 + 校验
├── session.py          # 会话管理（JSONL、索引、清理）+ 用户目录隔离
├── mcp.py              # MCP 客户端（自动重连）
├── skills.py           # 自定义 Agent/Skill 加载
├── scheduler.py        # 定时调度器（一次性/周期性唤醒）
├── metrics.py          # API 调用 metrics 持久化（token、延迟、费用）
├── statusline.py       # 可配置状态栏模板渲染
├── logger.py           # 轻量级日志基础设施
├── constants.py        # 共享常量（颜色、版本、限制）
├── server/             # 服务器端模块
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── user.py     # 用户数据模型（SQLAlchemy ORM）
│   ├── database.py     # SQLite 连接管理
│   └── auth.py         # JWT 签发/验证、密码哈希
├── tools/
│   ├── registry.py     # 工具注册表和执行器（31 个工具）
│   ├── schemas.py      # 工具 Schema 定义
│   ├── permissions.py  # 工具权限分类（READ/WRITE/DANGEROUS）
│   ├── security.py     # 安全检查
│   ├── state.py        # Per-connection Agent 状态
│   ├── bash.py         # Shell 命令执行 + Bubblewrap 沙箱
│   ├── file_ops.py     # 文件读写/编辑/搜索/图片读取
│   ├── web_tools.py    # Web 搜索和抓取
│   ├── notebook.py     # Jupyter Notebook 编辑
│   ├── agent_tools.py  # 子 Agent 和用户交互
│   ├── git_tools.py    # Worktree 和检查点
│   ├── sched_tools.py  # 定时调度
│   ├── cgroup.py       # cgroup 资源限制（CPU/内存）
│   └── exceptions.py   # 工具异常
├── providers/
│   ├── __init__.py      # Provider 工厂（自动按配置/模型名创建实例）
│   ├── base.py          # LLMProvider 抽象基类 + 标准化事件/响应 dataclass
│   ├── anthropic_provider.py  # Anthropic 原生 API（cache_control/thinking/服务端工具）
│   └── openai_provider.py    # OpenAI 兼容 API（GPT/DeepSeek/GLM/Qwen 等）
├── web/
│   ├── app.py          # FastAPI 应用 + JWT 认证中间件
│   ├── routes_api.py   # REST API 路由（含文件浏览/读写）
│   ├── routes_ws.py    # WebSocket 路由
│   ├── routes_pty.py   # PTY WebSocket 终端端点
│   ├── routes_auth.py  # 认证 API（注册/登录/用户信息/修改密码）
│   ├── pty_manager.py  # PTY 进程管理（pty.fork + shell）
│   ├── events.py       # 事件类型定义
│   ├── agent_bridge.py # Agent 桥接（共享 agent 核心）
│   └── static/         # 前端静态文件（HTML/CSS/JS）
│       ├── vendor/     # 第三方库（xterm.js + monaco-editor + jit-viewer + mermaid + echarts）
├── tests/              # 测试套件（311 个测试用例）
├── pyproject.toml      # 项目元数据和依赖
├── OCTOPUS.md          # 项目开发指引
└── README.md           # 项目说明
```

## 测试

```bash
pip install -e ".[dev]"
pytest tests/ -v

# 跳过网络测试
pytest tests/ -v -k "not web"

# 覆盖率
pytest tests/ --cov=. --cov-report=term-missing
```

## 许可证

Apache 2.0
