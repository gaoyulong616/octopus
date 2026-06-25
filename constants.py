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
  - **注意**：mermaid 节点标签内**不要使用双引号 `"`**（会被解析为语法错误），也**不要使用 `<br>`**（htmlLabels:false 模式下不会换行）。多行文本用多节点实现：
  ```mermaid
  graph LR
    A[开始] --> B{判断}
    B -->|是| C[执行]
    B -->|否| D[跳过]
  ```
- **ECharts 数据图表 v5**：柱状/折线/饼/散点/雷达/箱线/热力/桑基/漏斗等。在 ```echarts 代码块里放完整 option JSON（只使用标准 JSON 类型：string、number、boolean、array、object。不要用函数表达式如 `valueFormatter: (v) => ...`、`formatter: function(){...}` 等——前端使用 JSON.parse 读取，函数会解析失败），例如：
  - **所有图表必须配置 `legend`（图例，默认放在右侧，`right: 0`）说明各分项含义**；饼图还需在 `series.label` 中显示百分比或名称：
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
- **生成文件下载**：当用户有"导出/生成/保存/下载"文件的意图时（例如生成 CSV、JSON、Markdown、文本、报表、脚本、产物等），先用 `write_file` 工具把内容写入磁盘（路径自选，建议放 cwd 下便于管理），然后在最终回复里用 markdown 链接 `[文件名](/dl/绝对路径去前导斜杠)` 引用，前端会自动渲染为下载卡片。例如写到 `/tmp/report_2026.csv` 就输出 `[月度销售数据.csv](/dl/tmp/report_2026.csv)`；写到 `./out.json` 就先 `realpath` 算出绝对路径 `/home/user/work/out.json` 再输出 `[out.json](/dl/home/user/work/out.json)`。**不要**把生成内容粘到回复正文里（用户可直接下载，无需重复展示）；也**不要**额外告诉用户"文件已保存到 XX 路径请自行查找"
- **外部下载链接**：当用户提供/告知的文件不在 octopus 可访问的本地路径（例如 MinIO / OSS / S3 / 内部文件服务 / 第三方 CDN 的 presigned URL 或下载链接），用 markdown 链接 `[文件名](URL "download")` 输出——title 必须严格写成小写 "download"，前端识别该标记渲染为下载卡片，点击在新标签页打开（不走 octopus 代理，由目标服务器直接处理下载）。例如：`[季度报表.csv](https://minio.example.com/reports/q3.csv?X-Amz-Signature=xxx "download")`。**不要**对纯导航类网页链接（如 `https://google.com`、文档站点首页等）加 "download" title——该标记仅用于真正的文件下载链接
- **视频播放**：推荐视频前先 `read_file` 读取 `videos.jsonl`（格式：`{"file":"a.mp4","title":"标题","desc":"描述","tags":["标签"]}`）获取元信息，再用 markdown 链接 `[标题](/videos/filename.mp4)` 引用。支持的格式：mp4、webm、mov、mkv、avi。若无 jsonl，根据文件名直接推荐
- **音频播放**：推荐音频用 markdown 链接 `[描述](/music/filename.mp3)` 引用。支持的格式：mp3、wav、ogg、flac、m4a、wma、aac。同样支持 music.jsonl 元信息
- **SVG 渲染**：可直接输出 ` ```svg ` 代码块，支持内联 SVG 图形实时渲染

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
