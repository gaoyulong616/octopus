# 知识库（WebUI）

WebUI 左侧"知识库"菜单下的关系图谱功能。基于 AntV G6 v5 可视化 `kb_directory` 下的 Obsidian/Markdown 文档：节点 = 文档，边 = `[[双链]]` 引用 + 共同 tag。

## 架构概览

```
┌─ 前端 (web/static/) ───────────────────────────────────┐
│  index.html        菜单项 + 视图容器 + 工具栏           │
│  style.css         知识库布局/主题样式                  │
│  app.js            nav 切换 / G6 渲染 / 交互 / 持久化   │
│  vendor/g6.min.js  AntV G6 v5.0.48（本地化）           │
└────────────────────────────────────────────────────────┘
                       ↑ fetch
┌─ 后端 (web/) ──────────────────────────────────────────┐
│  routes_kb.py      /api/kb/graph  /api/kb/doc          │
│  app.py            路由注册                             │
│  config.py         kb_directory 配置项                  │
└────────────────────────────────────────────────────────┘
                       ↓ 文件扫描
                kb_directory/*.md（Obsidian 库）
```

## 配置

`~/.octopus/config.json`：

```json
{
  "kb_directory": "/path/to/your/wiki"
}
```

- 设为 `null` 或目录不存在 → 前端显示 "kb_directory 未配置"
- 优先级同其他配置：环境变量 > `.octopus/config.local.json` > `.octopus/config.json` > `~/.octopus/config.json`

---

## 后端实现

### 文件：`web/routes_kb.py`

#### 路由

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/kb/graph` | 扫描目录，返回 G6 图数据 |
| GET | `/api/kb/doc?path=` | 取单个 md 原文（已剥离 frontmatter） |

#### 处理流程（`/api/kb/graph`）

```
_resolve_kb_root()
   → 读 config kb_directory，resolve() + is_dir 校验

_scan_documents(root)
   → rglob("*.md")，跳过 .开头 目录
   → 每文件：
       · 截断 1MB
       · _parse_frontmatter()  → (meta_dict, body)
       · _extract_title()      → frontmatter.title > H1 > stem
       · _extract_wiki_links() → 正则 [[xxx]]
       · _strip_md_for_summary() → 去标记取 240 字摘要
   → 返回 docs[]

_build_graph(docs)
   → 建索引：by_lower_title / by_stem
   → nodes 直接映射
   → edges 双源去重：
       · wiki: 双链 target 按标题/stem 匹配
       · tag:  同 tag 分组两两连边
       · 同一对节点（无向）只保留一条，wiki 优先于 tag
   → 返回 {nodes, edges}
```

#### 关键设计

- **节点 id = 文件相对路径**（如 `Concepts/酬金计提规则.md`），稳定且唯一
- **路径安全**：`_safe_join()` 强制 `resolve()` 后必须仍在 root 内，防 `../` 越界
- **大文件保护**：单文件 1MB 截断；总文件数 ≤ 500
- **frontmatter 容错**：YAML 解析失败 → 返回空 dict，不抛异常
- **同步扫描**：当前数据量（百级文件内）同步实现简单，无需缓存；如需支持大型库（>1000 文件）可加 mtime 缓存

### 文件：`web/app.py`

`create_app()` 中通过 `app.include_router(kb_router)` 注册。继承全局 middleware：所有 `/api/*` 需登录态。

### 文件：`config.py`

```python
"kb_directory": None,  # 知识库根目录（None=禁用）
```

默认 `None` 禁用，前端会显示配置提示。

---

## 前端实现

### HTML（`web/static/index.html`）

#### 菜单项（侧栏 nav）

```html
<div class="db-nav-item" id="nav-knowledge" data-view="knowledge">
  <i class="ti ti-sitemap"></i>知识库
</div>
```

位于"技能"下方、"文件"上方。`data-view="knowledge"` 用于 nav click 路由。

#### 视图容器（`.db-main` 内）

```html
<div id="knowledge-container">                <!-- 默认 display:none -->
  <div class="kb-header">                      <!-- 标题 + 工具栏 -->
    <div class="kb-title">…</div>
    <div class="kb-toolbar">
      <select id="kb-layout-select">…</select>          <!-- 布局切换 -->
      <button id="kb-refresh">…</button>                 <!-- 重新加载 -->
      <button id="kb-zoom-out">…</button>                <!-- 缩小 -->
      <button id="kb-fit">…</button>                     <!-- 适应画布 -->
      <button id="kb-zoom-in">…</button>                 <!-- 放大 -->
      <input  id="kb-search">                            <!-- 节点搜索 -->
      <button id="kb-toggle-detail">…</button>           <!-- 侧栏开关 -->
    </div>
  </div>
  <div class="kb-body">                        <!-- flex 容器 -->
    <div id="kb-graph"></div>                  <!-- G6 画布（flex:1, min-width:0）-->
    <div id="kb-resize-handle"></div>          <!-- 拖拽条 -->
    <div id="kb-detail">…</div>                <!-- 详情侧栏 -->
  </div>
</div>
```

### CSS（`web/static/style.css`）

关键样式（约 2212 行起）：

```css
#knowledge-container { flex: 1; display: none; flex-direction: column; }
#knowledge-container.active { display: flex; }

.kb-body { flex: 1; min-height: 0; display: flex; position: relative; }

#kb-graph {
  flex: 1; min-width: 0; min-height: 0;  /* ⚠️ min-width:0 是关键 */
  background: var(--bg);
}

.kb-detail {
  flex: 0 0 320px;       /* JS 用 inline flex 覆盖 */
  min-width: 220px;      /* 无 max-width，动态算 */
  /* … */
}

.kb-resize-handle {
  width: 4px; cursor: col-resize; flex-shrink: 0;
  /* hover/dragging → 蓝色高亮 */
}
```

#### 重要坑：`min-width: 0`

`#kb-graph` 必须 `min-width: 0`。否则 flex item 默认 `min-width: auto`，G6 canvas 渲染的固定宽度顶住容器，detail 即使设了 flex 也会被挤出可视区——表现是 toggle 状态切换正确但视觉"打不开"。

### JS（`web/static/app.js`）

#### 状态变量（顶部）

```js
let knowledgeMode = false;          // 当前是否在知识库视图
let kbGraphInstance = null;          // G6.Graph 实例
let kbCurrentData = null;            // 后端返回的 {nodes, edges}
let kbDetailWidth = …;               // 侧栏宽度（localStorage 持久化）
let kbDetailVisible = true;          // 侧栏可见性（仅会话内）
```

#### 函数组织

```
toggleKnowledgeBase(open)        视图切换（隐藏 chat/filebrowser，显示 kb）
 └→ applyKBDetailLayout()        应用侧栏宽度/可见性
 └→ setTimeout(initKnowledgeGraph, 50)   延迟以拿到正确尺寸

initKnowledgeGraph()  async      入口：清旧实例 → fetch → 渲染
 ├→ loadKBGraphFromServer()      GET /api/kb/graph
 ├→ kbShowStatus(msg, err)       loading/error 占位
 └→ renderKBGraph()              实际 G6 渲染

renderKBGraph()
 ├→ destroy 旧实例 + 清空容器
 ├→ nodes/edges 数据映射 + 样式（base opacity: 1 保证 state 切换干净）
 ├→ layoutMap[layoutType]        5 种布局参数
 ├→ new G6.Graph({ container, data, node, edge, layout, behaviors })
 │  └→ node.state: selected/hover/dim
 │  └→ edge.state: highlight/dim（含 labelOpacity）
 ├→ graph.on("node:click"…)      选中 + 详情
 ├→ graph.on("canvas:click")     清除选中
 ├→ graph.on("node:dblclick")    打开原文
 ├→ graph.on("node:mouseenter/leave") hover 状态
 └→ graph.render().then(fitView)

highlightNode(id)                节点高亮：先全清所有 state + updateItem 强设 opacity
                                 再重设，最后 refresh() + paint()
clearKBSelection()               清空 state + updateItem 恢复 opacity + refresh/paint
renderKBDetail(id)               渲染右侧详情（摘要/tags/元数据/关系）
openKBDoc(id)        async       GET /api/kb/doc → marked 渲染 md
kbSearchAndFocus(query)          标题/摘要/tag 模糊匹配 + 聚焦

toggleKBDetail()                 侧栏开关
applyKBDetailLayout()            同步 inline flex/display + G6 resize
initKBResize()                   拖拽条 mousedown → 全局 mousemove/up
zoomIn/zoomOut (click handler)   kbGraphInstance.zoomTo(zoom * 1.4 / 1.4, 限 0.1~5)
```

#### 节点样式（按 category 配色）

```js
const palette = {
  concepts: "#3b82f6",   // 蓝
  topics:   "#10b981",   // 绿
  entities: "#f59e0b",   // 橙
  index:    "#06b6d4",   // 青
  log:      "#6b7280",   // 灰
  // …
};
```

#### 布局参数（当前）

```js
const layoutMap = {
  force:      { type: "fruchterman", maxIteration: 500, gravity: 3, speed: 10 },
  dagre:      { type: "dagre",       rankdir: "LR", nodesep: 50, ranksep: 120 },
  radial:     { type: "radial",      unitRadius: 300, preventOverlap: true, nodeSize: 60, nodeSpacing: 30 },
  grid:       { type: "grid",        preventOverlap: true, nodeSize: 60 },
  concentric: { type: "concentric",  minNodeSpacing: 100 },
};
```

#### 交互

| 触发 | 行为 |
|---|---|
| 单击节点 | 高亮节点 + 关联边，其他变 dim；右侧详情 |
| 双击节点 | 详情侧栏内打开 md 原文（marked 渲染） |
| 单击关系项 | 跳转到对端节点 |
| 点画布空白 | 清除选中 + updateItem 强设 opacity + refresh/paint |
| 按 ESC | 清除选中（仅知识库视图激活时） |
| 拖拽 handle | 实时改侧栏宽度 + G6 resize |
| 点 toggle 按钮 | 切换侧栏显示 |
| 搜索框 input | 模糊匹配 + 自动聚焦 |
| 切换布局 select | 仅本地重新渲染（不重新 fetch） |
| 点 refresh | 清缓存 + 重新 fetch |
| 点放大 (+) | zoomTo(zoom × 1.4)，上限 5x |
| 点缩小 (−) | zoomTo(zoom / 1.4)，下限 0.1x |
| 滚轮缩放 | 缩放画布 |
| 拖拽节点 | drag-element 标准拖拽 |
| 拖拽画布 | 平移视图 |

#### 持久化

- `localStorage.kb_detail_width`：侧栏宽度（220 ~ 动态上限）
- 侧栏可见性**不持久化**：每次进入知识库默认显示，避免上次关闭后被锁住

#### 拖拽宽度上限

```js
const bodyWidth = $kbDetail.parentElement?.clientWidth || window.innerWidth;
const maxW = Math.max(220, bodyWidth - 240 - 4);   // 给 graph 至少留 240px
w = Math.max(220, Math.min(maxW, w));
```

---

## 数据契约

### 节点（node）

```ts
{
  id: string;          // 文件相对路径
  label: string;       // 显示名
  category: string;    // 配色分类
  tags: string[];
  status?: string;
  updated?: string;
  summary: string;
  path: string;        // 同 id
  size: number;        // bytes
}
```

### 边（edge）

```ts
{
  source: string;      // node.id
  target: string;
  kind: "wiki" | "tag";
  label: string;       // "引用" 或 "#tag"
}
```

### 边 id 规则

**前端**生成：`e{index}-{source}-{target}`

加 index 后缀防止后端某种情况下产生 source-target 相同的边导致 G6 v5 报 `Edge already exists`。

---

## 调试入口

`window` 上暴露（仅开发用）：

```js
__kbToggle()      // 手动触发侧栏切换
__kbState()       // 查看当前状态：{ kbDetailVisible, kbDetailWidth, hasBtn, hasDetail }
```

---

## 扩展接口（未实现）

| 接口 | 用途 | 何时需要 |
|---|---|---|
| `PATCH /api/kb/doc?path=` | 编辑 md（保留 frontmatter） | 加 in-place 编辑 |
| `POST /api/kb/doc` | 新建文档 | 加创建入口 |
| `GET /api/kb/search?q=` | 服务端全文搜索 | 库变大后客户端搜索不够 |
| `GET /api/kb/stats` | category 分布、tag 频次、孤立节点 | 加统计页 |
| LLM 实体抽取 | 让 LLM 跨文档抽实体作为额外节点 | 节点从"文档"升级到"概念" |

---

## 静态资源版本号

修改 `web/static/{index.html,style.css,app.js}` 后需 bump `index.html` 里的 `?v=N` 查询串避免缓存。当前最新：

- `style.css?v=138`
- `app.js?v=167`
- `g6.min.js?v=1`

vendor 文件（G6/mermaid/...）改了也要 bump。
