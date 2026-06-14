"""共享常量：ANSI 颜色、文件限制、版本号。"""

# ── 版本 ──
VERSION = "2.0.0"

# ── ANSI 转义序列 ──
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"

# ── 文件大小限制 ──
MAX_FILE_SIZE = 1 * 1024 * 1024       # 文本文件：1MB（读截断，写拒绝）
MAX_IMAGE_SIZE = 20 * 1024 * 1024     # 图片文件：20MB（Anthropic API 支持最大 8000×8000px）

# ── 前端 UI 能力描述（注入 system prompt，让 LLM 自适应输出格式） ──

UI_CAPABILITIES_WEB = """## 前端渲染能力（Web 浏览器界面）

你的回复会被渲染到浏览器界面，支持的渲染能力：
- **完整 GitHub-flavored Markdown**：表格、任务列表、删除线、代码块（带语法高亮，highlight.js）
- **Mermaid 图表 v11**：流程图、时序图、甘特图、类图、状态图、饼图等。需要可视化时优先用 mermaid 代码块输出，例如：
  ```mermaid
  graph LR
    A[开始] --> B{判断}
    B -->|是| C[执行]
    B -->|否| D[跳过]
  ```
- **ECharts 数据图表 v5**：柱状/折线/饼/散点/雷达/箱线/热力/桑基/漏斗等。在 ```echarts 代码块里放完整 option JSON（不要包含 `_height` 之外的下划线字段），例如：
  ```echarts
  {
    "_height": 320,
    "title": { "text": "近 7 天提交数" },
    "tooltip": { "trigger": "axis" },
    "xAxis": { "type": "category", "data": ["周一","周二","周三","周四","周五","周六","周日"] },
    "yAxis": { "type": "value" },
    "series": [{ "type": "line", "data": [12, 18, 9, 23, 17, 6, 11], "smooth": true }]
  }
  ```
- **分页表格**：**仅在用户明确要求分页/可排序/可筛选表格时**才输出 ```table 代码块。在 ```table 里放 JSON 配置（`columns` + `data`），例如：
  ```table
  {
    "title": "团队成员",
    "_pageSize": 20,
    "columns": [
      { "field": "name", "title": "姓名", "sortable": true },
      { "field": "age", "title": "年龄", "sortable": true, "align": "right" },
      { "field": "role", "title": "角色" }
    ],
    "data": [
      { "name": "张三", "age": 28, "role": "开发" },
      { "name": "李四", "age": 34, "role": "测试" }
    ]
  }
  ```
  字段说明：`title` 可选（表格标题，展示在表格上方）；`column.sortable=true` 让列可点排序；`column.align` 可选 left/right/center（控制列对齐，表头同数据行）；`column.width` 可选（如 `"120px"`/`"30%"`）；`_pageSize` 可选，默认 20。
- **代码块**：所有语言都有语法高亮，可放心输出长代码
- **数学公式**：暂不支持 LaTeX 渲染，复杂数学用代码块或纯文本表达
- **图片**：可直接用 markdown 图片语法 `![](url)` 引用

何时用 mermaid：
- 解释系统架构、调用链、状态转换时
- 用户明确要求"图示"、"流程图"、"架构图"时
- 比纯文字更清晰的复杂关系

何时用 echarts：
- 展示数值/统计数据（柱状、折线、饼、雷达等）
- 用户给出一组数据希望可视化对比时
- 时间序列、趋势、占比分布

何时用 table：
- **仅当用户明确要求**「分页表格」「可排序表格」「可筛选表格」时
- 数据行数较多且用户希望交互浏览时

不用 mermaid/echarts/table 的场景：
- 简单 2-3 步流程（用编号列表即可）
- 普通表格数据（用 markdown 表格即可，不要主动升级为 ```table）
- 纯文本就能讲清的逻辑"""

UI_CAPABILITIES_TUI = """## 前端渲染能力（Rich 终端 UI）

你的回复会被 Rich 终端库渲染，支持的渲染能力：
- **GitHub-flavored Markdown**：标题、列表、表格、加粗、代码块（带语法高亮）
- **代码块**：支持语法高亮，长代码可放心输出
- **不支持 mermaid**：需要图示时用 ASCII art 或缩进文本表达
- **不支持 LaTeX 数学公式**：用代码块或纯文本表达

图示替代方案（无 mermaid 时）：
- 流程：用编号列表或 ASCII 箭头（`A -> B -> C`）
- 树状结构：用缩进 + `├──` `└──` 等字符
- 时序：用编号步骤说明交互顺序"""

UI_CAPABILITIES_CLI = """## 前端渲染能力（纯文本终端）

你的回复会以纯文本输出，无任何 markdown 渲染：
- 不要输出 markdown 表格、标题井号、加粗符号等（会原样显示）
- 代码块用缩进表示即可
- 不支持 mermaid、LaTeX、图片"""
