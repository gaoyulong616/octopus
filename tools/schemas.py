"""工具 Schema 定义：动态选择服务端/客户端工具版本。"""

# ── 服务端工具 schema（由 API 提供商执行） ──

_SERVER_TOOL_SCHEMAS: dict[str, dict] = {
    "web_search": {
        "type": "web_search_20260209",
        "name": "web_search",
    },
    "web_fetch": {
        "type": "web_fetch_20260209",
        "name": "web_fetch",
    },
}

# ── 客户端工具 schema（由 run_web_search / run_web_fetch 本地执行） ──

_CLIENT_TOOL_SCHEMAS: dict[str, dict] = {
    "web_search": {
        "name": "web_search",
        "description": "搜索互联网，返回相关网页的标题、摘要和链接。"
                       "适合查询最新信息、文档、API 参考等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "最大返回结果数，默认10", "default": 10},
            },
            "required": ["query"],
        },
    },
    "web_fetch": {
        "name": "web_fetch",
        "description": "抓取指定 URL 的网页内容，返回纯文本。"
                       "可用于阅读搜索结果中的链接详情。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的网页 URL"},
                "max_length": {"type": "integer", "description": "返回内容的最大字符数，默认5000", "default": 5000},
            },
            "required": ["url"],
        },
    },
}

# ── 基础工具（始终使用客户端 schema） ──

_BASE_TOOLS: list[dict] = [
    {
        "name": "bash",
        "description": "在 shell 中执行命令。工作目录在调用间持久化。"
                       "何时用：运行程序/测试、安装包、git 操作、需要管道/重定向/环境变量、串联多条命令（用 &&）。"
                       "何时不用：读文件用 read_file（更安全、有 offset/limit）；编辑文件用 edit_file；"
                       "搜索代码用 grep_search。避免用 cat/head/tail/sed 替代专用工具。"
                       "提交 git 时绝不跳过 hooks（--no-verify）除非用户明确要求。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "timeout": {"type": "integer", "description": "超时秒数，默认120", "default": 120},
                "run_in_background": {"type": "boolean", "description": "后台执行，不等待结果。完成后通知。默认 false", "default": False},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "读取本地文件内容，支持文本文件和图片。可通过 offset/limit 按行号范围读取大文件。"
                       "何时用：已知文件路径，需要查看内容。优先于 bash 的 cat/head/tail。"
                       "大文件（>500行）用 offset+limit 分段读，不要一次加载。"
                       "编辑前先 read_file 确认上下文，再做 edit_file。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "encoding": {"type": "string", "description": "编码，默认utf-8", "default": "utf-8"},
                "offset": {"type": "integer", "description": "起始行号（从1开始），默认读取全文", "default": None},
                "limit": {"type": "integer", "description": "读取的最大行数，默认不限", "default": None},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "将内容写入本地文件。目录不存在时自动创建。"
                       "何时用：创建新文件，或需要完全重写已有文件（如从模板生成）。"
                       "何时不用：编辑已有文件应该用 edit_file（精准替换，不会误删其他内容）。"
                       "只有文件大部分内容都要改、或用户明确要求重写时才用 write_file。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "写入内容"},
                "mode": {"type": "string", "description": "'w'覆盖(默认) 或 'a'追加", "default": "w"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "对文件进行精确的字符串替换编辑。通过 old_string 定位要修改的位置，替换为 new_string。"
                       "何时用：编辑已有文件的首选工具（优先于 write_file）。"
                       "old_string 必须精确匹配；若出现多次，提供更多上下文使其唯一，或设 replace_all=true。"
                       "修改前先 read_file 确认上下文。一处改动用 edit_file；"
                       "多处改动（可能跨文件）用 multi_edit 减少 API 往返。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "old_string": {"type": "string", "description": "要被替换的原始文本（必须精确匹配）"},
                "new_string": {"type": "string", "description": "替换后的新文本"},
                "replace_all": {"type": "boolean", "description": "是否替换所有匹配项，默认false", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_files",
        "description": "列出目录中的文件和子目录，支持 glob 模式匹配和递归搜索。"
                       "何时用：了解项目结构、确认文件是否存在、浏览目录内容。"
                       "何时不用：已知文件路径要读内容用 read_file；搜代码内容用 grep_search。"
                       "递归搜索大目录时注意结果可能很多，先用 pattern 过滤。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径，默认为当前工作目录", "default": "."},
                "pattern": {"type": "string", "description": "glob 匹配模式，如 '*.py'、'**/*.js'。不设置则列出所有文件", "default": ""},
                "recursive": {"type": "boolean", "description": "是否递归搜索子目录，默认false", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "grep_search",
        "description": "在文件中搜索文本或正则表达式，返回匹配的文件名、行号和匹配内容。"
                       "何时用：查找函数/类/变量定义、查找引用、定位代码位置、按内容搜索未知文件。"
                       "何时不用：已知文件路径要读内容用 read_file；找文件名用 list_files。"
                       "搜索整个符号时 include 过滤文件类型能提速（如 '*.py'）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索模式（文本或正则表达式）"},
                "path": {"type": "string", "description": "搜索路径，默认为当前工作目录", "default": "."},
                "include": {"type": "string", "description": "只搜索匹配此 glob 模式的文件，如 '*.py'", "default": ""},
                "max_results": {"type": "integer", "description": "最大返回结果数，默认50", "default": 50},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "copy_file",
        "description": "复制文件。自动保留文件元数据（修改时间等）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源文件路径"},
                "destination": {"type": "string", "description": "目标文件路径"},
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "move_file",
        "description": "移动或重命名文件。",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源文件路径"},
                "destination": {"type": "string", "description": "目标文件路径"},
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "delete_file",
        "description": "删除文件（不能删除目录）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要删除的文件路径"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "task_create",
        "description": "创建一个结构化任务，用于跟踪多步骤工作的进度。",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "任务标题"},
                "description": {"type": "string", "description": "任务详细描述", "default": ""},
                "activeForm": {"type": "string", "description": "进行中时的显示文本", "default": ""},
            },
            "required": ["subject"],
        },
    },
    {
        "name": "task_update",
        "description": "更新任务状态、标题、描述等属性。status 可选: pending/in_progress/completed/deleted。",
        "input_schema": {
            "type": "object",
            "properties": {
                "taskId": {"type": "integer", "description": "任务 ID"},
                "status": {"type": "string", "description": "新状态: pending/in_progress/completed/deleted"},
                "subject": {"type": "string", "description": "新标题"},
                "description": {"type": "string", "description": "新描述"},
                "addBlocks": {"type": "array", "items": {"type": "integer"}, "description": "此任务阻塞的任务 ID"},
                "addBlockedBy": {"type": "array", "items": {"type": "integer"}, "description": "阻塞此任务的任务 ID"},
            },
            "required": ["taskId"],
        },
    },
    {
        "name": "task_list",
        "description": "列出所有任务及其状态。",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "task_get",
        "description": "获取指定任务的详细信息。",
        "input_schema": {
            "type": "object",
            "properties": {
                "taskId": {"type": "integer", "description": "任务 ID"},
            },
            "required": ["taskId"],
        },
    },
    {
        "name": "notebook_edit",
        "description": "编辑 Jupyter Notebook (.ipynb) 文件的单元格。",
        "input_schema": {
            "type": "object",
            "properties": {
                "notebook_path": {"type": "string", "description": "Notebook 文件路径（必须为绝对路径）"},
                "cell_id": {"type": "string", "description": "要编辑的单元格 ID"},
                "new_source": {"type": "string", "description": "单元格新内容"},
                "cell_type": {"type": "string", "description": "单元格类型: code 或 markdown。省略时保留原类型（replace 模式）或默认 code（insert 模式）", "default": None},
                "edit_mode": {"type": "string", "description": "编辑模式: replace/insert/delete", "default": "replace"},
            },
            "required": ["notebook_path", "new_source"],
        },
    },
    {
        "name": "sub_agent",
        "description": "启动一个子 Agent 并行执行独立的子任务。子 Agent 有独立上下文，完成后返回结果。"
                       "何时用：并行执行多个独立任务（同时搜索多个目录、读多个文件分析）；"
                       "把噪音大的搜索/分析隔离到子 Agent 避免污染主上下文。"
                       "何时不用：有依赖关系的串行任务；简单单步操作直接用对应工具更快。"
                       "子 Agent 无当前对话上下文，任务描述要自包含。",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "子任务描述（自包含，子 Agent 看不到当前对话）"},
                "description": {"type": "string", "description": "简短任务摘要（3-5字）", "default": ""},
                "isolation": {
                    "type": "string",
                    "enum": ["read-only", "worktree"],
                    "description": "隔离粒度。read-only=仅允许读取工具；worktree=独立 git worktree（推荐用于并行写入）。"
                                   "省略则使用完整工具集（与主 agent 等价权限）。",
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "worktree_create",
        "description": "创建一个 git worktree（隔离工作目录），用于并行开发不同分支。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "worktree 名称（也是分支名）"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "worktree_remove",
        "description": "删除一个 git worktree。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "worktree 路径"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "checkpoint_create",
        "description": "创建一个 git 检查点（自动 commit），用于后续回滚。"
                       "在执行破坏性操作前自动调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "检查点描述", "default": "auto checkpoint"},
            },
            "required": [],
        },
    },
    {
        "name": "checkpoint_rollback",
        "description": "回滚到上一个检查点（git reset --soft HEAD~1）。",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "schedule_wakeup",
        "description": "安排一个定时唤醒。在指定秒数后自动触发任务继续执行。"
                       "适用于需要等待异步操作完成的场景。",
        "input_schema": {
            "type": "object",
            "properties": {
                "delay_seconds": {"type": "integer", "description": "等待秒数（60-3600）"},
                "reason": {"type": "string", "description": "等待原因", "default": ""},
                "prompt": {"type": "string", "description": "唤醒后执行的任务", "default": ""},
            },
            "required": ["delay_seconds"],
        },
    },
    {
        "name": "cron_create",
        "description": "创建一个周期性定时任务。"
                       "支持标准的 cron 表达式（分 时 日 月 周）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "cron": {"type": "string", "description": "cron 表达式，如 '*/5 * * * *'（每5分钟）"},
                "prompt": {"type": "string", "description": "每次触发时执行的任务"},
                "name": {"type": "string", "description": "任务名称"},
                "recurring": {"type": "boolean", "description": "是否周期性执行", "default": True},
            },
            "required": ["cron", "prompt", "name"],
        },
    },
    {
        "name": "cron_delete",
        "description": "取消一个定时任务。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "任务名称"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "cron_list",
        "description": "列出所有定时任务。",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "read_image",
        "description": "读取图片文件并返回 base64 编码。支持 PNG、JPG、JPEG、GIF、WebP 格式。"
                       "用于让 LLM 分析图片内容。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图片文件路径"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "invoke_skill",
        "description": "按需加载并执行一个 Skill（来自 ~/.skills/ 或 .skills/ 目录）。"
                       "Skill 是预定义的 markdown 模板，可用作特定任务的专家指引或工作流脚手架。"
                       "参数可作为字典传入，会替换模板中的 {{key}} 占位符。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill 名称"},
                "args": {
                    "type": "object",
                    "description": "传给 skill 的参数（替换模板中的 {{key}}）",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "multi_edit",
        "description": "对多个文件执行批量编辑，一次调用修改多处内容，减少 API 往返。"
                       "何时用：一处改动涉及多个文件、或一个文件内多处不连续改动。"
                       "何时不用：单文件单处改动用 edit_file 更简单。"
                       "所有改动应相关（如重命名一个函数的所有调用点）；不相关改动分开调用更安全。",
        "input_schema": {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "文件路径"},
                            "old_string": {"type": "string", "description": "要被替换的原始文本"},
                            "new_string": {"type": "string", "description": "替换后的新文本"},
                            "replace_all": {"type": "boolean", "description": "是否替换所有匹配，默认false", "default": False},
                        },
                        "required": ["path", "old_string", "new_string"],
                    },
                    "description": "编辑操作列表",
                },
            },
            "required": ["edits"],
        },
    },
    {
        "name": "ask_user_question",
        "description": "向用户提出一个问题，提供 2-4 个选项让用户选择。"
                       "用于在执行任务前确认需求、选择方案或获取偏好。"
                       "每次调用最多 4 个选项，每个选项有 label 和 description。"
                       "用户也可以选择 'Other' 提供自由文本输入。",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要问用户的问题"},
                "header": {"type": "string", "description": "简短标签（最多 12 字符），如 'Auth method', 'Library'"},
                "options": {
                    "type": "array",
                    "description": "2-4 个选项",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "选项显示文字（1-5 字）"},
                            "description": {"type": "string", "description": "选项解释说明"},
                        },
                        "required": ["label", "description"],
                    },
                    "minItems": 2,
                    "maxItems": 4,
                },
                "multiSelect": {"type": "boolean", "description": "是否允许多选，默认 false", "default": False},
            },
            "required": ["question", "header", "options"],
        },
    },
    {
        "name": "submit_plan",
        "description": "在 Plan 模式下提交实施计划给用户审批。"
                       "调用此工具后用户会看到计划并选择批准或拒绝；批准后会自动切换到 Auto 模式执行。"
                       "计划内容应为详细的步骤说明（推荐 markdown 列表），包括：要修改的文件、"
                       "改动思路、验证方式。仅在 Plan 模式下可用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "完整的实施计划文本（markdown）"},
            },
            "required": ["plan"],
        },
    },
    {
        "name": "enter_plan_mode",
        "description": "进入 Plan 模式（只读规划）。当任务复杂需要先设计方案时调用此工具。"
                       "进入后写入类工具将被限制，须先通过 submit_plan 提交计划并获得用户批准后才能执行。",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def build_tools(server_side_tools: set[str] | None = None) -> list[dict]:
    """构建工具 schema 列表。

    Args:
        server_side_tools: 使用服务端版本的工具名集合（如 {"web_search", "web_fetch"}）。
            不在集合中的工具使用客户端 schema。为 None 则全部使用客户端版本。
    """
    tools = []
    # 先插入 web_search 和 web_fetch（保持原有顺序）
    for name in ("web_search", "web_fetch"):
        if server_side_tools and name in server_side_tools:
            tools.append(_SERVER_TOOL_SCHEMAS[name])
        else:
            tools.append(_CLIENT_TOOL_SCHEMAS[name])
    tools.extend(_BASE_TOOLS)

    # P4: 动态注入 skill 描述到 invoke_skill 工具的 description 中
    invoke_idx = next((i for i, t in enumerate(tools) if t.get("name") == "invoke_skill"), None)
    if invoke_idx is not None:
        try:
            from skills import load_skills
            skills = load_skills()
            if skills:
                desc_lines = [tools[invoke_idx]["description"]]
                desc_lines.append("可用 Skills:")
                for s_name in sorted(skills.keys()):
                    s_def = skills[s_name]
                    desc = s_def.description or "(无描述)"
                    if len(desc) > 200:
                        desc = desc[:197] + "..."
                    desc_lines.append(f"  - {s_name}: {desc}")
                tools[invoke_idx] = {**tools[invoke_idx], "description": " ".join(desc_lines)}
        except Exception:
            pass

    return tools


# 向后兼容：默认全客户端版本
TOOLS: list[dict] = build_tools()
