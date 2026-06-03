# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Python AI Agent（`octopus-agent` v2.0.0），基于 Anthropic SDK 的 tool-use 能力，让 LLM 通过工具调用执行编程任务。支持 Rich TUI 交互模式、单次任务模式、Web UI 模式。

## 开发环境

项目使用 `.venv` 下的虚拟环境（Python >= 3.12），始终使用 `.venv/bin/` 而非系统 Python（系统自带 3.9 不兼容）：

```bash
.venv/bin/python octopus.py          # 运行
.venv/bin/pip install -e ".[dev]"    # 安装依赖（含 dev）
.venv/bin/pytest tests/ -v           # 全量测试
.venv/bin/pytest tests/test_config.py::test_get_value -v  # 单个测试
.venv/bin/ruff check .               # Lint
.venv/bin/ruff check --fix .         # Lint 自动修复
```

构建系统：hatchling。Lint 规则见 `pyproject.toml [tool.ruff]`，line-length 120，target py312。

## 架构

### 核心流程

```
用户输入 → cli.py 分发 → agent.py 调用 Anthropic API (stream)
  → text_delta → tui.py 流式渲染
  → tool_use → tools/ 执行 → 结果回传 → 循环直到 end_turn
```

### 模块职责

| 模块 | 职责 |
|------|------|
| `octopus.py` | 入口：参数解析（--continue/--resume/-n/--web），分发到单次/交互/Web 模式 |
| `agent.py` | Agent 主循环：流式 API 调用、7 种事件类型（EVT_STREAM/THINKING/TOOL_CALL/TOOL_RESULT/RESPONSE/PROGRESS/ERROR）、重试退避、thinking 块、prompt cache、stop reason 处理、服务端工具探测（`_probe_server_tools`）、`server_tool_use`/`web_search_tool_result`/`web_fetch_tool_result` 块处理 |
| `cli.py` | CLI 交互层：slash 命令分发、权限确认（`[a]` 放行同类）、信号处理、Plan/Auto 模式切换 |
| `tui.py` | Rich TUI 渲染：StreamRenderer 流式输出 + Markdown 重渲染、会话选择器、token 费用追踪 |
| `commands.py` | Slash 命令注册表：`@_register` 装饰器注册，26 个命令 |
| `tools/` | 工具包（12 个子模块，见下方） |
| `context.py` | 上下文管理：`build_system_prompt()` 构建 system prompt、`compress_messages()` 渐进压缩、多级项目指令注入、`_load_memory()`/`save_memory()` 跨会话记忆 |
| `config.py` | 配置管理：三层配置（项目本地 > 项目 > 用户）+ 环境变量覆盖、`_DEFAULTS`/`_VALIDATORS`、Hooks 系统、细粒度权限规则、目录信任 |
| `session.py` | 会话管理：JSONL 追加存储、项目隔离、元数据索引、自动清理 |
| `mcp.py` | MCP 客户端：连接外部工具服务器、断连自动重连 |
| `skills.py` | 自定义 Agent/Skill 加载（`~/.agents/` `.agents/` `~/.skills/` `.skills/`） |
| `scheduler.py` | 定时调度器：一次性唤醒、周期性任务、cron 表达式解析 |
| `metrics.py` | Token 用量/延迟/成本持久化（`~/.octopus/metrics.jsonl`），多模型定价表 |
| `statusline.py` | TUI 状态栏渲染，模板占位符 `{model}` `{git_branch}` `{cwd}` `{tokens}` `{cost}` |
| `constants.py` | 共享常量（ANSI 颜色、文件大小限制、版本号） |
| `logger.py` | 轻量日志（`~/.octopus/octopus.log`） |
| `web/` | FastAPI Web UI：`app.py` 应用工厂 + token 认证、`agent_bridge.py` 同步 Agent→异步 WebSocket 桥接、`routes_api.py`/`routes_ws.py` 路由、`events.py` 事件序列化 |

### tools/ 包结构

工具已从单文件拆分为包，`tools/__init__.py` 重导出所有符号保持向后兼容：

| 子模块 | 内容 |
|--------|------|
| `schemas.py` | 工具 Schema 定义：`build_tools(server_side_tools)` 动态构建（服务端/客户端自动切换），`_BASE_TOOLS` 固定工具 + `_SERVER_TOOL_SCHEMAS`/`_CLIENT_TOOL_SCHEMAS` 双版本 |
| `registry.py` | `TOOL_HANDLERS` 注册表 + `execute_tool()` 执行器 + `_submit_plan()`/`_invoke_skill()` |
| `state.py` | `AgentState`：工作目录追踪、任务管理（create/update/list/get）、`pending_plan` |
| `bash.py` | `run_bash()`：实时流式输出、`output_fn` 回调、cd 追踪 |
| `file_ops.py` | 文件读写/编辑/复制/移动/删除/目录列表/文本搜索/图片读取 |
| `web_tools.py` | `run_web_search()`（DuckDuckGo+Wikipedia）、`run_web_fetch()` — 客户端降级实现，当 API 提供商不支持服务端工具时使用 |
| `agent_tools.py` | `run_sub_agent()`：独立线程运行子任务 |
| `git_tools.py` | Git Worktree 创建/删除、检查点创建/回滚 |
| `sched_tools.py` | 定时唤醒、cron 创建/删除/列表 |
| `notebook.py` | Jupyter Notebook 单元格编辑 |
| `security.py` | 路径验证、SSRF 防护（`is_internal_url()`）、敏感文件检测（`is_sensitive_path()`） |
| `exceptions.py` | `ToolError`：统一错误类型，由 `execute_tool` 捕获 |

### Web UI 架构

```
用户浏览器 --WebSocket--> routes_ws.py --queue--> agent_bridge.py (后台线程运行 agent.py)
                     <--events--- events.py <--serialize--- agent.py emit
用户浏览器 --HTTP API--> routes_api.py (查询会话/模型等)
```

Web UI 功能：浅色主题、侧边栏折叠、模型选择器（pill 按钮切换）、会话批量删除、新建会话确认、页面刷新自动恢复最新会

## 运行方式

必配项：`api_key`、`base_url`、`model`，在 `~/.octopus/config.json` 或环境变量 `OCTOPUS_API_KEY`/`OCTOPUS_BASE_URL`/`OCTOPUS_MODEL` 中设置。

```bash
.venv/bin/python octopus.py                              # 交互模式（Rich TUI）
.venv/bin/python octopus.py "任务描述"                     # 单次任务
.venv/bin/python octopus.py -c                            # 恢复最近会话
.venv/bin/python octopus.py --resume                      # 交互式选择会话
.venv/bin/python octopus.py -n "会话名"                    # 指定会话名称
.venv/bin/python octopus.py --web                         # Web UI 模式
.venv/bin/python octopus.py --web --port 9000             # Web UI 指定端口
```

## 配置

配置层级（高优先级覆盖低优先级）：`.octopus/config.local.json` > `.octopus/config.json` > `~/.octopus/config.json` > 环境变量

权限模式：`auto-approve`（全部自动）、`confirm`（危险操作确认）、`deny`（禁止危险操作）

新增配置项：在 `config.py` 的 `_DEFAULTS` 中添加，如需校验在 `_VALIDATORS` 中添加。`set_value()` 自动持久化到配置文件。

## 开发指南

### 新增工具

1. 在 `tools/schemas.py` 的 `_BASE_TOOLS` 列表添加 JSON Schema（如有服务端版本，同时添加到 `_SERVER_TOOL_SCHEMAS` 和 `_CLIENT_TOOL_SCHEMAS`）
2. 在对应的 `tools/` 子模块中实现 `run_xxx()` 函数，错误时 `raise ToolError("消息")`
3. 在 `tools/registry.py` 的 `TOOL_HANDLERS` 中注册

### 新增 Slash 命令

在 `commands.py` 用 `@_register("/name", "描述")` 装饰器注册，实现 `cmd_xxx` 函数，返回 `CommandResult`。

### 关键实现细节

- **Agent 事件流**：`agent.py` 通过 `emit_fn` 回调向 TUI/Web UI 发送事件，token 用量从 `final_message.usage` 获取
- **TUI 流式渲染**：`StreamRenderer` 先 `sys.stdout.write()` 实时输出，`\033[{n}A\033[J` 回退后用 Rich Markdown 重渲染
- **权限确认**：`_confirm_action()` 支持 `[a]` 放行同类工具；`check_permission_rule()` 按 tool+pattern 正则匹配 allow/deny
- **Plan 模式**：写入类工具自动拒绝，`submit_plan` 工具提交计划到 `state.pending_plan`，用户确认后切 /auto 执行
- **Prompt Cache**：system prompt 用 `cache_control: {"type": "ephemeral"}` 标记
- **上下文压缩**：`compress_messages()` 渐进截断过长 tool_result，`/compact` 手动触发
- **会话序列化**：thinking 块保存 `block.thinking` 但加载时跳过（临时推理内容不回传 API）
- **安全**：`tools/security.py` 提供 SSRF 防护、敏感路径检测；`config.py` 维护 `dangerous_commands` 列表
- **服务端工具**：`agent.py` 启动时 `_probe_server_tools()` 探测 API 提供商是否支持 `web_search_20260209`/`web_fetch_20260209`，支持则使用服务端版本（零额外往返、SPA 渲染），不支持则降级到客户端 `run_web_search()`/`run_web_fetch()`。探测结果按 `(base_url, api_key)` 缓存，切换提供商自动重新探测
