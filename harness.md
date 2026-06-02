# Harness 思想在 Octopus CLI 中的实践

> 作者：高玉龙
> 版本：v2.0 · 2026-06

---

## 一、程序介绍

**Octopus CLI** 是一个基于 Anthropic SDK 的 AI Agent 命令行工具。它不是简单的 "LLM 调用封装"，而是 **harness 思想的一次完整实践**。

所谓 **harness（运行时框架）**，指的是包裹在 LLM 周围、把"语言模型"变成"能干活的 Agent"的所有外围基础设施 —— 工具循环、权限边界、记忆系统、会话持久化、观测能力、扩展机制等等。模型本身只负责"想"，harness 负责"做"和"管"。

```
用户 ──┐
        ▼
┌─────────────────────────────────────┐
│   TUI / CLI 输入层（Rich 渲染）       │
└───────────────┬─────────────────────┘
                ▼
┌─────────────────────────────────────┐
│   Slash 命令 / 权限确认 / 信号处理     │
└───────────────┬─────────────────────┘
                ▼
┌─────────────────────────────────────┐
│   Agent 主循环                        │
│   ┌─────────────────────────────┐    │
│   │ 流式 LLM → 工具调用 → 结果   │    │
│   │ Hooks / Metrics / 重试       │    │
│   └─────────────────────────────┘    │
└───────────────┬─────────────────────┘
                ▼
┌─────────────────────────────────────┐
│   工具层（28 个内置 + MCP 外接）       │
│   bash / 文件 / Web / 子 Agent / 调度 │
└─────────────────────────────────────┘
```

**核心数据**：13 个 Python 模块（去注释约 6000 行），28 个工具，145 个测试用例。

---

## 二、Harness 实践

下面按 15 个维度展开，每个维度配关键代码示例。这些维度不是孤立的，而是层层叠加：缺了 Hooks，其他模块就缺少可扩展点；缺了 Memory，跨会话学习就无从谈起；缺了 Permissions，Agent 就不敢动手做事。

### 1. 事件驱动的 Hooks 系统

**思想**：harness 的每个生命周期节点都应该是"可插拔"的。Claude Code 有 8 类标准事件，我们完全对齐。

```python
# config.py
HOOK_EVENTS = (
    "SessionStart",       # 会话启动
    "UserPromptSubmit",   # 用户提交前
    "PreToolUse",         # 工具调用前（可阻止）
    "PostToolUse",        # 工具调用后
    "Notification",       # 系统通知
    "Stop",               # 主 Agent 完成回复
    "SubagentStop",       # 子 Agent 完成
    "PreCompact",         # 上下文压缩前
)
```

**触发示例**（agent.py）：

```python
# 用户提交输入前 — 外部可拦截或注入上下文
run_hooks("UserPromptSubmit", {"prompt": user_task[:500]})

# 工具调用前 — 外部可阻止危险操作
hook_results = run_hooks("PreToolUse", {
    "tool": tool_name,
    "input": json.dumps(tool_input)[:500],
})

# 一次完整回复后 — 触发通知或日志归档
run_hooks("Stop", {"iterations": str(iteration), "final_text": final_text[:500]})
```

**用户配置**：

```json
{
  "hooks": {
    "SessionStart": ["echo '开始会话: $(date)'"],
    "PreToolUse": ["python ~/.octopus/audit.py"],
    "PreCompact": ["slack-notify '上下文已压缩'"]
  }
}
```

### 2. 按需调度的 Skills 系统

**思想**：Skill 不应该只在用户显式输入 `/skill <name>` 时才生效。系统提示词里只列出 *name + description*，模型自己决定何时调用，调用时才加载完整内容，节省上下文。

```python
# context.py — 系统提示词自动注入 skill 索引
from skills import load_skills
skills = load_skills()
if skills:
    lines = ["## 可用 Skills（通过 invoke_skill 工具按需加载）"]
    for s_name, s_def in sorted(skills.items()):
        lines.append(f"- **{s_name}**: {s_def.description}")
```

```python
# tools/registry.py — 模型主动调用时才加载完整内容
def _invoke_skill(name: str, args: dict) -> str:
    skills = load_skills()
    if name not in skills:
        return f"[错误] 未找到 skill '{name}'"
    skill = skills[name]
    rendered = render_skill(skill, str_args)
    return f"[Skill: {name}]\n{rendered}"
```

### 3. 类型化的跨会话记忆

**思想**：单一 `memory.md` 文件无法区分用户偏好、项目背景、反馈规则、外部引用。Claude Code 的方案是按类型分文件 + 索引。

```
~/.octopus/memory/
├── MEMORY.md           # 索引（每行 ≤150 字符）
├── user/
│   └── terse-style.md  # name/description/type frontmatter + 正文
├── feedback/
│   └── no-summarize.md
├── project/
│   └── auth-refactor.md
└── reference/
    └── grafana-urls.md
```

```python
# context.py
MEMORY_TYPES = ("user", "feedback", "project", "reference")

def save_memory(text: str, mtype: str = "user",
                name: str | None = None, description: str | None = None) -> str:
    """每条记忆写入独立文件，自动更新 MEMORY.md 索引。"""
    type_dir = os.path.join(_MEMORY_DIR, mtype)
    target = os.path.join(type_dir, f"{_slugify(name)}.md")
    frontmatter = (
        f"---\nname: {name}\ndescription: {desc}\n"
        f"type: {mtype}\ncreated: {datetime.now().isoformat()}\n---\n\n"
    )
    with open(target, "w") as f:
        f.write(frontmatter + text)
    _write_index(_scan_memory_dir())  # 重建索引
```

**用户使用**：

```
/remember feedback: 不要每次都总结
/remember project: 重构 auth 中间件
/memory            # 查看所有
/forget terse      # 按名删除
```

### 4. Plan 模式 + 提交审批工作流

**思想**：Plan 模式不是"只读模式"这么简单，它需要一个 *提交 → 审批 → 切换* 的完整工作流。Claude Code 用 `ExitPlanMode` 工具，我们用 `submit_plan`。

```python
# tools/registry.py
def _submit_plan(plan: str) -> str:
    """提交实施计划给用户审批。"""
    get_state().pending_plan = plan
    return "已提交计划，等待用户审批。"
```

```python
# tui.py — 在 run_agent 返回后检查 pending_plan
pending = get_state().pending_plan
if pending:
    get_state().pending_plan = None
    approved = _review_plan(pending)  # 渲染 markdown + [y/n] 输入
    if approved:
        state["plan_mode"] = False    # 自动切到 Auto
```

LLM 在 Plan 模式下被指示 "**必须**调用 submit_plan 工具提交计划"，TUI 拦截后弹审批 UI。

### 5. 子 Agent 隔离粒度

**思想**：sub_agent 不只是开线程跑，要明确权限边界。读取类子任务不应能写入；写入类并行任务应进独立 worktree。

```python
# tools/agent_tools.py
_RESTRICTED_TOOLS = {
    "read-only": {
        "bash", "write_file", "edit_file",
        "copy_file", "move_file", "delete_file",
        "notebook_edit", "worktree_create", "checkpoint_rollback",
    },
}

def run_sub_agent(task: str, isolation: str | None = None):
    if isolation == "worktree":
        wt_result = run_worktree_create(f"subagent-{threading.get_ident()}")
        worktree_path = _extract_path(wt_result)
    # 子 agent 跑在受限 confirm_fn 下
    if isolation in _RESTRICTED_TOOLS:
        kwargs["confirm_fn"] = _make_restricted_confirm(isolation)
    ...
    run_hooks("SubagentStop", {"isolation": isolation, "result_preview": result[:200]})
```

### 6. 总结式上下文压缩 + PreCompact Hook

**思想**：达到阈值时不是粗暴截断 tool_result（会丢失语义），而是用 LLM 生成摘要替换前 N 轮。压缩前触发 hook 让外部介入。

```python
# context.py
def compress_messages(client, messages, model, force=False):
    chars = _estimate_chars(messages)
    threshold = get("context_threshold", 120_000)
    if not force and chars < threshold:
        return messages

    # PreCompact hook：让外部记录或阻止
    run_hooks("PreCompact", {
        "messages": str(len(messages)),
        "chars": str(chars),
        "threshold": str(threshold),
    })

    # 让 LLM 总结旧对话
    old_messages = messages[:-keep_recent]
    summary_prompt = "请将以下对话历史压缩为一段简洁的摘要..."
    resp = client.messages.create(model=model, max_tokens=1024,
                                   messages=[{"role": "user", "content": summary_prompt}])
    summary = next(b.text for b in resp.content if b.type == "text")
    return [{"role": "user", "content": f"[上下文摘要] {summary}"},
            {"role": "assistant", "content": "收到，我已了解之前的上下文。"}] + recent
```

### 7. MCP 多传输抽象

**思想**：MCP 规范定义了 stdio / HTTP / SSE / WebSocket 四种传输。把传输抽出来，新增协议只是新增 Transport 子类。

```python
# mcp.py
class TransportBase:
    def send_message(self, message: dict) -> None: ...
    def read_message(self) -> dict: ...
    def is_alive(self) -> bool: ...
    def close(self) -> None: ...

class StdioTransport(TransportBase):
    """通过子进程 stdin/stdout（Content-Length 分帧）。"""
    ...

class HTTPTransport(TransportBase):
    """通过 HTTP POST，每次请求独立（无状态服务端）。"""
    def read_message(self) -> dict:
        req = Request(self.url, data=json.dumps(self._pending).encode(),
                      headers=self.headers)
        with urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())
```

```python
class MCPServer:
    def __init__(self, name, transport="stdio", **kwargs):
        if transport == "stdio":
            self._transport = StdioTransport(**kwargs)
        elif transport == "http":
            self._transport = HTTPTransport(**kwargs)
```

### 8. 持久化的调用指标（Metrics）

**思想**：每次 LLM 调用都记录 token 用量、延迟、估算成本，落到本地 JSONL 供分析。这是 harness 的"可观测性"基线。

```python
# metrics.py
_PRICING_USD_PER_MTOKEN = {
    "claude-opus-4":   {"input": 15.0, "output": 75.0, "cache_read": 1.5},
    "claude-sonnet-4": {"input":  3.0, "output": 15.0, "cache_read": 0.3},
    # ...
}

def record_call(session_id, model, input_tokens, output_tokens,
                cache_read=0, cache_write=0, latency_ms=0.0):
    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "session": (session_id or "")[:12],
        "model": model,
        "input": int(input_tokens), "output": int(output_tokens),
        "cache_read": int(cache_read), "cache_write": int(cache_write),
        "latency_ms": int(latency_ms),
        "cost_usd": estimate_cost_usd(model, input_tokens, output_tokens,
                                       cache_read, cache_write),
    }
    with open(_METRICS_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
```

**agent.py 集成**（每次调用 LLM 自动记录）：

```python
t0 = time.monotonic()
final_message = _stream_with_retry(...)
latency_ms = (time.monotonic() - t0) * 1000

metrics.record_call(
    session_id=session_id, model=model,
    input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
    cache_read=cache_read, cache_write=cache_creation,
    latency_ms=latency_ms,
)
```

**用户使用**：`/stats` 查看本期累计，`/stats session` 看本会话。

### 9. 测试覆盖 + CI

**思想**：harness 是基础设施，没有测试就不敢改。Mock SDK 测 agent 循环，本地 echo server 测 MCP，console record 测 TUI。

```python
# tests/test_agent_hooks.py — mock _stream_with_retry 验证 hook 触发
@pytest.fixture(autouse=True)
def stub_dependencies(monkeypatch):
    final_msg = _make_final_message()
    monkeypatch.setattr(agent, "_stream_with_retry", lambda *a, **kw: final_msg)
    monkeypatch.setattr(metrics, "record_call", lambda **kw: {})

def test_user_prompt_submit_hook_called(monkeypatch):
    captured = []
    monkeypatch.setattr(agent, "run_hooks",
                        lambda e, ctx=None: captured.append((e, ctx)) or [])
    agent.run_agent("hello", output_fn=lambda *a: None, max_iterations=1)
    assert any(e == "UserPromptSubmit" for e, _ in captured)
```

**CI**（`.github/workflows/ci.yml`）：Python 3.12/3.13 + ruff lint + pytest + coverage。

### 10. 工程化（lint、格式化、CI）

**思想**：用工具兜底代码质量，让人专注于设计。

```toml
# pyproject.toml
[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]
ignore = ["E501", "B008"]
```

### 11. 危险命令检测加固

**思想**：黑名单会被多空格、引号、变量展开绕过。检测前先归一化。

```python
# config.py
def _normalize(s): return re.sub(r'\s+', ' ', s).strip()

def _check(text):
    text = _normalize(text).lower()
    text = re.sub(r'["\']+', '', text)  # 剥离引号
    text = re.sub(r'\s+', ' ', text).strip()
    for p in dangerous_patterns:
        if text.startswith(p + " ") or (" " + p) in text:
            return True
    return False
```

### 12. 网络/文件安全边界

**思想**：默认拒绝访问内网（SSRF 防护）；默认拒绝读取 SSH keys、云凭证、`.env`。

```python
# tools/security.py
_SENSITIVE_PATH_PATTERNS = [
    ".ssh/", ".gnupg/", ".aws/", ".azure/", ".gcp/",
    ".env", ".npmrc", ".docker/", ".netrc",
]

def is_sensitive_path(path: str) -> bool:
    real = os.path.realpath(os.path.expanduser(path)).lower()
    home = os.path.expanduser("~").lower()
    base = os.path.basename(real)
    if base in _SENSITIVE_FILE_NAMES:  # id_rsa, credentials.json, ...
        return True
    if real.startswith(home + os.sep):
        for pat in _SENSITIVE_PATH_PATTERNS:
            if pat in real:
                # 允许 .env.example 等样板文件
                if pat == ".env" and real.endswith((".env.example", ".env.template")):
                    continue
                return True
    return False
```

### 13. 三档权限模型

**思想**：confirm/deny 二档太粗糙。Approve once / session / permanent 才符合实际开发节奏。

```python
# cli.py
print(f"  [y]once  [s]session  [p]permanent  [n]拒绝")
choice = input("  选择: ").strip().lower()

if choice == "p":
    _add_permanent_permission(tool_name, tool_input)  # 写入 permission_rules
    return True
if choice in ("s", "a"):
    auto_tools.add(tool_name)  # 仅本会话有效
    return True
return choice in ("y", "yes", "o")  # once
```

`_add_permanent_permission` 会推断最小匹配 pattern（bash 取首词；文件取目录），写入 `~/.octopus/config.json`。

### 14. 可配置的 Statusline

**思想**：每个团队关注的状态不同。把状态栏做成模板，让用户自定义。

```python
# statusline.py
def render_statusline(state: dict) -> str:
    template = get("statusline", "")
    fields = {
        "model": get("model") or "?",
        "cwd": _shorten_cwd(get_cwd()),
        "git_branch": _get_git_branch(get_cwd()),
        "tokens": tokens_total,
        "session_id": (state.get("session_id") or "")[:8],
        "cost": f"{state.get('session_cost_usd', 0.0):.4f}",
    }
    return template.format_map(_SafeDict(fields))  # 缺失字段不抛错
```

**配置**：

```json
{
  "statusline": "{model}  |  {git_branch}  |  {cwd}  |  {tokens} tokens  |  ${cost}"
}
```

### 15. 配置校验

**思想**：错配应该启动时就发现，而不是等到运行时崩。

```python
# config.py
def resolve_model(name, max_depth=3):
    """别名解析，防御 A→B→A 循环。"""
    visited = [name]
    for _ in range(max_depth):
        if name not in models: break
        nxt = models[name]
        if nxt in visited: break  # 循环
        visited.append(nxt); name = nxt
    return name

def validate_config():
    issues = []
    # 别名循环
    for alias in models:
        seen = [alias]
        for _ in range(10):
            ...
            if nxt in seen:
                issues.append(f"  models: 检测到别名循环 {' → '.join(seen)}")
                break
    # MCP command 存在性
    for sname, scfg in mcp_servers.items():
        if not shutil.which(scfg.get("command", "")):
            issues.append(f"  mcp_servers.{sname}: command 不在 PATH 中")
    return issues
```

---

## 三、设计原则总结

整个 harness 实现贯彻了以下五条原则：

| 原则 | 体现 |
|------|------|
| **可插拔** | Hooks / Skills / MCP 都是装饰器或注册表机制，添加新行为不改核心循环 |
| **可观测** | Metrics 持久化、logger.py、statusline、/stats 命令，让每次调用可量化 |
| **可隔离** | 子 Agent 三档隔离、worktree、Plan 模式，让"实验"和"执行"有边界 |
| **可记忆** | 类型化 Memory + 自动索引 + 跨会话注入，让 Agent 越用越懂你 |
| **可信任** | 三档权限、敏感路径防护、危险命令检测、目录信任机制，让 Agent 敢动手但不越界 |

---

## 四、未来展望

Harness 的演进没有止境。以下是 Octopus CLI 接下来值得继续探索的方向：

### 4.1 更智能的上下文管理
- **分层 cache**：CLAUDE.md / 系统提示词 / 工具结果分别打不同 TTL 的 cache_control
- **自动 /compact**：达到 0.8 阈值时主动触发压缩，而不是等到溢出
- **记忆主动检索**：当前是把所有 memory 索引塞进 prompt；改为向量检索按需召回

### 4.2 更强的可观测性
- **OpenTelemetry 集成**：把 metrics 导到 Jaeger/Grafana，跨会话聚合
- **回放模式**：`octopus --replay <session>` 把会话按时间轴重演，方便演示和复盘
- **A/B 测试框架**：同一任务跑多个模型，自动比较输出质量

### 4.3 更细的权限边界
- **macOS sandbox-exec / Linux bwrap**：bash 工具写入类命令默认沙箱执行
- **能力声明**：每个工具声明所需能力（filesystem.read / filesystem.write / network），用户按能力授权
- **审计日志**：所有工具调用写入不可变日志文件（合规场景）

### 4.4 更丰富的协作
- **多 Agent 调度**：基于 sub_agent + worktree 的并行任务编排，类似 Claude Code 的 Explore/Plan/Review 子代理
- **共享 Memory**：团队级 memory 仓库（git 同步），让团队成员共享项目知识
- **MCP 服务器生态**：内置常用 MCP 适配器（GitHub、Linear、Slack），一键接入

### 4.5 更友好的开发体验
- **Web UI**：FastAPI + WebSocket 提供 browser 端的会话视图（已有依赖）
- **VSCode 插件**：把 statusline / slash 命令搬进 IDE
- **可视化的 hook/skill/memory 管理 UI**

### 4.6 工程化纵深
- **覆盖率到 80%+**：当前 145 测试覆盖核心模块，目标补齐 tui.py 和 mcp.py
- **性能基准**：建立启动时间、单轮 LLM 调用延迟、内存占用基线，回归告警
- **版本发布自动化**：GitHub Release + CHANGELOG 自动生成

---

## 五、结语

Harness 不是某一个具体功能，而是 **"让 LLM 真正能干活"的所有隐形基础设施**。

模型每年都会换代，但 harness 的设计原则 —— 可插拔、可观测、可隔离、可记忆、可信任 —— 是持久的。希望这份实践记录能帮团队成员快速建立对 harness 的整体认知，也欢迎大家在自己的项目里借鉴、改进、反馈。

> "We shape our tools, and thereafter our tools shape us." —— Marshall McLuhan

---

*本文档随项目演进持续更新。如需查阅最新实现，请直接打开对应模块的源码。*
