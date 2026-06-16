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

### 上下文管理

- **双视图分离**：外部 `messages`（全量，用于持久化和 UI 展示）与 agent 内部 `llm_messages`（可被压缩，仅用于 LLM API 调用）。`run_agent` 通过顶层浅拷贝初始化 `llm_messages = list(messages)`，compress 仅作用于 `llm_messages`，外部 messages 只追加新消息永不覆盖
- 上下文压缩阈值根据模型自动计算：`context_window × 3 chars/token × 0.7 安全余量`
- `context_threshold` 配置项保留为手动覆盖（设为 `null` 自动计算，默认）
- 模型的 `context_window` 在 providers 的 models 对象格式中配置
- **分段压缩**：`_segmented_compress` 把低重要性消息按字符上限（`max(8000, context_window × 3 × 0.4)`）切分为多段，每段单独 LLM 摘要；段数 > 3 时对所有段摘要做二次合并，避免单次输入超 context window
- **`/compact` 命令**：不再覆盖 messages，改为在 state 中设 `_force_compact_next` 标记，下次 `run_agent` 通过 `force_compact=True` 仅在第一次迭代强制压缩 `llm_messages`

### ReAct 主循环（agent.py）

- **迭代上限**：默认 50，可通过 `max_iterations` 配置。LLM 陷入 tool→result→tool 死循环时强制停止，emit `EVT_ERROR` + `EVT_RESPONSE` 后返回 `(达到迭代上限 N 轮)`
- **stop_reason 完整处理**：
  - `end_turn` → 正常返回最终文本
  - `tool_use` → 执行工具后继续循环
  - `max_tokens` → 截断处理（见下）
  - `refusal` → emit `EVT_ERROR` + `EVT_RESPONSE` 立即返回拒绝文本
  - `pause_turn` → 追加 "请继续" 续写
- **max_tokens 截断自动续写**：追加 user "请继续" 让 LLM 接着写，连续 3 次截断后第 4 次停止（emit `EVT_ERROR`），防止无限续写消耗 token
- **截断时精准跳过最后一个 tool_use**：API 保证 content_blocks 中 tool_use 都是合法 JSON，但 max_tokens 截断时最后一个 block 若为 tool_use，其 input 字段可能不完整。`last_block_is_truncated_tool_use` 判定后跳过执行，返回 `[回复被截断，最后一个 tool_use 不完整]`，前面的 tool_use 正常执行
- **tool 失败熔断**：用 `hashlib.md5(tool+input)` 作 key 计数，同一调用连续失败超 `tool_failure_threshold`（默认 3）后直接返回 `[已熔断]` 跳过，避免 LLM 反复重试同一失败调用；成功后清零
- **流式重试回滚**：`_stream_with_retry` 在重试前 emit `EVT_STREAM_REWIND`，UI 清空已累积的 stream buffer，避免上一次失败输出的残片混入重试后的输出
- **专用事件类型**：`EVT_TRUNCATED`（截断信息，区别于 `EVT_ERROR`）、`EVT_STREAM_REWIND`（重试前回滚信号）。`_make_print_event` 也已兼容这两个事件

### System Prompt 分层追加（agent.py）

`run_agent` 接受三个独立参数控制 system prompt，按"追加 vs 替换"语义区分：

- `system_prompt_override`（替换）：**仅** Plan 模式等特殊场景使用，完全替换 L1/L2/L3 三层，丢失所有工具规范/记忆/项目指令。慎用
- `ui_capabilities`（追加）：前端 UI 能力描述（`constants.UI_CAPABILITIES_WEB/TUI/CLI`）。告诉 LLM 当前 UI 支持哪些渲染能力（Web 支持 mermaid@11/markdown/monaco；TUI 仅 Rich markdown；CLI 纯文本）。作为独立 cache 块追加在 L1/L2/L3 之后，让 LLM 自适应输出格式
- `agent_persona`（追加）：`/agent` 切换的人设追加层。来自 `.agents/<name>.md` 的正文（frontmatter 已剥离），不替换主系统提示词，保留所有工具规范和记忆。人设与默认规范冲突时默认规范优先

三端调用：
- **TUI**（`tui.py`）：`UI_CAPABILITIES_TUI` + agent_persona + Plan hint（叠加为 persona）
- **Web**（`web/agent_bridge.py`）：`UI_CAPABILITIES_WEB` + agent_persona + Plan hint
- **CLI**（`cli.py`）：`UI_CAPABILITIES_CLI` + agent_persona

每块各自带 `cache_control: ephemeral`，切换 agent/Plan 模式只让人设块失效，L1/L2/L3 主三层缓存仍命中。

### 系统提示词三层架构

系统提示词分为三个独立缓存块，各自带 `cache_control: ephemeral` 最大化 API 缓存命中率：

- **L1（极稳定）**: 身份 + 行为规范（文本输出规则、上下文管理、工具策略、代码质量、安全、任务判断、执行谨慎性分级、输出风格）。仅在 cwd 变化或 force_refresh 时重建，会话内缓存命中率接近 100%
- **L2（半稳定）**: 记忆索引 + 记忆使用指导 + 项目指令 + Skills 列表。由指令文件 mtime 变化驱动刷新
- **L3（动态）**: 日期 + cwd + 平台/Shell/OS/Python 版本 + Git 状态 + 目录列表。30s TTL 自动刷新

此外：
- Skill 描述动态注入到 `invoke_skill` 工具的 description 字段，不占 system prompt 空间
- 工具描述采用"行为导向"风格（何时用这个 vs 那个），不只是"做什么"
- 子目录 OCTOPUS.md 在文件操作时自动注入（`tools/file_ops.py` 的 `_try_inject_subdir_instruction`）
- 上下文压缩支持消息重要性分级（编辑操作 > 错误记录 > 读取操作 > 问答对话）
- `/cache-stats` 命令展示 prompt cache 命中率，量化分层缓存效果

### 斜杠命令

在 `commands.py` 中通过 `@_register("/name", "desc")` 装饰器注册，返回 `CommandResult`。

## 关键约定

- **Python >= 3.12**，行长度 120，使用 ruff
- 导入使用项目根目录的绝对导入（`from tools import execute_tool`），不用相对导入
- agent.py 中的 `EVT_*` 事件类型常量是 UI 层的输出契约，修改需同步所有消费端
- 文件大小限制：读 >1MB 截断，写 >1MB 拒绝（`constants.MAX_FILE_SIZE`）；图片 20MB（`constants.MAX_IMAGE_SIZE`）
- bash 工具维护全局 `_cwd`，所有文件操作以此为基准
- agent 缓存 anthropic client（`_get_client()`），配置变更时自动重建
- 配置文件有 mtime 缓存检测（`config._config_cache`）
- **UI 层修改 `bridge.messages` 前必须检查 `task_lock`**（`/clear`、`/init`、`/resume` 等）。否则 agent 线程仍在 append 时清空会让后续消息前文丢失，且 `save_session` 序列化的对话历史断裂
- **scheduler 锁用 `threading.RLock`**：`schedule_once`/`schedule_recurring` 在持锁时调用 `self.cancel(name)` 重入。普通 `Lock` 不可重入会死锁
- **subprocess kill 后必须 wait**（`terminate()` 超时回退到 `kill()` 时也要 `wait(timeout=N)`），否则子进程对象被 GC 后变 zombie，长期运行累积
- **MCP `_send_request` 限制跳过通知次数**：服务器只发通知时会死循环，必须有 max_skip 兜底
- **`dispatch_command` 必须 catch 异常**：单个 `cmd_*` 异常不应让整个交互循环崩溃
- **tool_result 必须校验 `tool_use_id`**：序列化/反序列化/压缩/`_finalize_pending_tool_uses` 四处都要跳过无效 tool_use_id（None/空字符串），否则 API 返回 400 `missing field tool_use_id`
- **`_finalize_orphan_tool_uses` 必须用 `_block_type`/`_block_id` 兼容 SDK 对象**：assistant content 可能是 SDK 对象 list（`agent.py` 直接 `append final_message.content`），不能用 `isinstance(block, dict)` 判断。否则 SDK 形式的 tool_use 不会被收集到 `all_tool_use_ids`，引用其 id 的 dict tool_result 被误判孤儿丢弃，留下连续 assistant(tool_use) 触发 API 400 `tool_use without tool_result`
- **`run_agent` 入口处调用 `_finalize_orphan_tool_uses(messages)` 兜底**：多轮对话中前一轮异常退出可能残留孤儿 tool_use，下次调用直接 400。`_finalize_orphan_tool_uses` 是幂等的，对正常 messages 无副作用
- **Web 文件下载的两段约定**：(1) 后端 `/api/file/download?path=` 必须做 `is_sensitive_path` 双重校验（原始路径 + resolve 后路径）+ 200MB 上限 + `FileResponse` 流式 + 用户 token 校验，否则任意登录用户能下载 `~/.ssh/id_rsa`、`.env` 等敏感文件；(2) 前端 `renderDownloadLinks` 识别 markdown 链接 `a[href^='/dl/']`，提取 `/dl/` 后的路径（加前导 `/`）替换为下载卡片，调 `downloadFile()` 走 `/api/file/download`。LLM 由 `UI_CAPABILITIES_WEB` 提示词驱动：用户有导出/生成/下载意图时，先 `write_file` 写盘，再在**最终回复正文**里输出 `[文件名](/dl/绝对路径去前导斜杠)`，**不要**贴文件内容到正文、**不要**额外提示"已保存到 XX 路径"

## 添加新工具的步骤

1. `tools/` 下新建文件实现工具函数
2. `tools/__init__.py` 导出
3. `tools/registry.py` 的 `TOOL_HANDLERS` 注册
4. `tools/schemas.py` 添加 Schema
5. `tools/permissions.py` 更新工具分类（如需要）
6. `tests/` 下添加测试
