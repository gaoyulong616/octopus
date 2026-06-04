# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 常用命令

```bash
# 安装（开发模式）
pip install -e ".[dev]"

# 运行测试（使用 venv）
.venv/bin/pytest tests/ -v

# 单个测试文件
.venv/bin/pytest tests/test_tools.py -v

# 跳过网络测试
.venv/bin/pytest tests/ -v -k "not web"

# 覆盖率
.venv/bin/pytest tests/ --cov=. --cov-report=term-missing

# 代码检查 & 格式化
.venv/bin/ruff check .
.venv/bin/ruff format .

# 构建
.venv/bin/python -m build
```

## 架构概览

这是一个 Python AI Agent CLI 工具（类似 Claude Code），通过 Anthropic SDK tool-use 让 LLM 自主调用工具完成编程任务。

### 核心调用链

```
octopus.py (入口/参数解析)
  → agent.py (LLM 主循环：流式调用 + 工具执行 + 重试)
    → tools/registry.py (工具路由) → 各 tools/*.py (具体实现)
    → context.py (system prompt 构建 + 上下文压缩)
    → session.py (JSONL 持久化)
```

### 三套 UI，共享 agent 核心

- **tui.py** — Rich TUI（交互模式默认），事件驱动渲染
- **cli.py** — CLI 回退（无 Rich 时）
- **web/** — FastAPI + WebSocket Web UI

agent.py 通过 `output_fn(event_type, text, metadata)` 回调向 UI 层推送事件（`EVT_STREAM`、`EVT_TOOL_CALL`、`EVT_TOOL_RESULT` 等）。

### 工具系统

- 工具在 `tools/` 目录下各自独立文件，通过 `registry.py` 的 `TOOL_HANDLERS` 字典注册
- Schema 定义在 `tools/schemas.py`（客户端版 + 服务端版）
- 权限分类：`READ_TOOLS` / `WRITE_TOOLS` / `DANGEROUS_PATTERNS`（`tools/permissions.py`）
- 安全检查在 `tools/security.py`

### 配置三层优先级

环境变量 > `.octopus/config.local.json` > `.octopus/config.json` > `~/.octopus/config.json`

### 斜杠命令

在 `commands.py` 中通过 `@_register("/name", "desc")` 装饰器注册，返回 `CommandResult`。

## 关键约定

- **Python >= 3.12**，行长度 120，使用 ruff
- 导入使用项目根目录的绝对导入（`from tools import execute_tool`），不用相对导入
- agent.py 中的 `EVT_*` 事件类型常量是 UI 层的输出契约，修改需同步所有消费端
- 文件大小限制：读 >1MB 截断，写 >1MB 拒绝（`constants.MAX_FILE_SIZE`）
- bash 工具维护全局 `_cwd`，所有文件操作以此为基准
- agent 缓存 anthropic client（`_get_client()`），配置变更时自动重建
- 配置文件有 mtime 缓存检测（`config._config_cache`）

## 添加新工具的步骤

1. `tools/` 下新建文件实现工具函数
2. `tools/__init__.py` 导出
3. `tools/registry.py` 的 `TOOL_HANDLERS` 注册
4. `tools/schemas.py` 添加 Schema
5. `tools/permissions.py` 更新工具分类（如需要）
6. `tests/` 下添加测试
