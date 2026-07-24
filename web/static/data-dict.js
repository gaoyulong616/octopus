/* 数据字典前端 — 独立 IIFE，通过 localStorage token 调用 REST API */

(function () {
    "use strict";

    // ── 状态 ──
    let instances = [];
    let expandedMap = {};     // "instance-{id}" / "schema-{id}" → true/false
    let treeLoadMore = {};    // "instance-{id}" / "schema-{id}" → visibleCount (steps of PAGE_SIZE)
    let selectedPath = null;  // { type, id } — 当前选中的节点
    let currentTable = null;  // 展开中的表详情
    let currentTab = "columns";
    var deletedObjectMap = {};  // {type: {id: name}} 已删除对象，日志查询时补充
    let ddToken = "";
    let ddContainer = null;
    let ddTree = null;
    let ddPlaceholder = null;
    let ddDetailContent = null;
    let ddDetailHeader = null;
    let ddTabContent = null;
    let ddAddInstance = null;
    let ddTabBar = null;
    let ddEditMode = false;
    let ddInitialized = false;

    // ── 分页状态 ──
    let listPages = {
        allInstances: 1,
        instanceSchemas: 1,
        schemaTables: 1,
        columns: 1,
        indexes: 1,
        constraints: 1,
    };

    // ── 搜索状态 ──
    let isSearchMode = false;
    let searchResults = [];
    let searchTotal = 0;
    let searchPage = 1;
    let searchTotalPages = 0;
    let searchTimer = null;
    let currentSearchQuery = "";
    const SEARCH_PAGE_SIZE = 20;

    // ── 工具 ──
    function ddFetch(url, options = {}) {
        const token = ddToken || localStorage.getItem("octopus_auth_token") || sessionStorage.getItem("octopus_auth_token") || "";
        ddToken = token;
        const headers = options.headers || {};
        headers["Authorization"] = "Bearer " + token;
        if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
            headers["Content-Type"] = "application/json";
            options.body = JSON.stringify(options.body);
        }
        options.headers = headers;
        return fetch(url, options);
    }

    function escapeHtml(s) {
        if (s == null) return "";
        return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function logActionLabel(log) {
        var label = log.op_type === "insert" ? "创建" : "删除";
        var val = log.op_type === "insert" ? log.new_value : log.old_value;
        if (val && val !== "created" && val !== "deleted") label += "：" + escapeHtml(val);
        return label;
    }

    function showToast(msg, isError) {
        let el = document.querySelector(".fb-toast");
        if (!el) {
            el = document.createElement("div");
            el.className = "fb-toast";
            document.body.appendChild(el);
        }
        el.textContent = msg;
        el.classList.toggle("error", !!isError);
        el.classList.add("show");
        clearTimeout(el._hideTimer);
        el._hideTimer = setTimeout(function () { el.classList.remove("show"); }, 2000);
    }

    function ddE(tag, cls, html) {
        const el = document.createElement(tag);
        if (cls) el.className = cls;
        if (html != null) el.innerHTML = html;
        return el;
    }

    function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    function renderTags(tags) {
        if (!tags) return "";
        return tags.split(",").map(function (t) {
            var tag = t.trim();
            if (!tag) return "";
            return '<span class="dd-tag-chip">' + escapeHtml(tag) + "</span>";
        }).join("");
    }

    // ── 渲染：实例树 ──
    function renderTree(insts) {
        ddTree.innerHTML = "";
        if (!insts || insts.length === 0) {
            ddTree.innerHTML = '<div class="dd-tree-empty">暂无数据，点击上方 + 添加实例</div>';
            return;
        }
        insts.forEach(function (inst) {
            const item = renderTreeItem(inst, "instance", 0);
            ddTree.appendChild(item);
        });
    }

    function renderTreeItem(obj, type, depth) {
        const isInstance = type === "instance";
        const isSchema = type === "schema";
        const id = obj.id;
        const key = type + "-" + id;
        const expanded = !!expandedMap[key];
        const sel = selectedPath && selectedPath.type === type && selectedPath.id === id;

        // 收集子节点
        let children = [];
        if (isInstance) children = obj.schemas || [];
        else if (isSchema) children = obj.tables || [];

        const wrapper = ddE("div", "dd-tree-item");
        wrapper.dataset.type = type;
        wrapper.dataset.id = id;

        // 行（可悬停/选中区域）
        const row = ddE("div", "dd-tree-row" + (sel ? " sel" : ""));
        row.dataset.type = type;
        row.dataset.id = id;

        const icon = isInstance ? 'ti ti-server-2' : isSchema ? 'ti ti-database' : 'ti ti-table';
        const label = isInstance ? obj.instance_name : isSchema ? obj.schema_name : obj.table_name || obj.table_name;

        let html = "";
        if (children.length > 0) {
            html += '<span class="dd-tree-toggle' + (expanded ? ' expanded' : '') + '"><i class="ti ti-chevron-right"></i></span>';
        } else {
            html += '<span class="dd-tree-toggle" style="visibility:hidden"><i class="ti ti-chevron-right"></i></span>';
        }
        var sub = isInstance ? (obj.remark || "") : isSchema ? (obj.remark || "") : (obj.comment || "");
        html += '<i class="' + icon + '"></i>';
        html += '<span class="dd-tree-label" title="' + escapeHtml(label) + '">' + escapeHtml(label) + '</span>';
        if (sub) {
            html += '<span class="dd-tree-sub" title="' + escapeHtml(sub) + '">' + escapeHtml(sub) + '</span>';
        }

        const actions = [];
        if (isInstance) {
            actions.push({ icon: "ti ti-plus", title: "添加 Schema", action: "addSchema" });
            actions.push({ icon: "ti ti-edit", title: "编辑", action: "editInstance" });
            actions.push({ icon: "ti ti-trash", title: "删除", action: "deleteInstance" });
        } else if (isSchema) {
            actions.push({ icon: "ti ti-plus", title: "添加表", action: "addTable" });
            actions.push({ icon: "ti ti-edit", title: "编辑", action: "editSchema" });
            actions.push({ icon: "ti ti-trash", title: "删除", action: "deleteSchema" });
        } else {
            actions.push({ icon: "ti ti-edit", title: "编辑", action: "editTable" });
            actions.push({ icon: "ti ti-trash", title: "删除", action: "deleteTable" });
        }
        html += '<span class="dd-tree-actions">';
        actions.forEach(function (a) {
            html += '<button class="dd-edit-only" data-action="' + a.action + '" title="' + escapeHtml(a.title) + '"><i class="' + a.icon + '"></i></button>';
        });
        html += '</span>';

        row.innerHTML = html;
        wrapper.appendChild(row);

        // 子节点容器（与 row 同级）
        if (expanded && children.length > 0) {
            const childType = isInstance ? "schema" : "table";
            var visibleCount = treeLoadMore[key] || 20;
            var toShow = children.slice(0, visibleCount);
            const container = ddE("div", "dd-tree-children");
            toShow.forEach(function (child) {
                container.appendChild(renderTreeItem(child, childType, depth + 1));
            });
            if (visibleCount < children.length) {
                var moreEl = ddE("div", "dd-tree-more");
                moreEl.textContent = "点击查看更多（剩余 " + (children.length - visibleCount) + " 项）";
                moreEl.dataset.treeMore = key;
                container.appendChild(moreEl);
            }
            wrapper.appendChild(container);
        }

        // Click: select + toggle
        row.addEventListener("click", function (e) {
            const toggle = e.target.closest(".dd-tree-toggle");
            if (e.target.closest(".dd-tree-actions")) return;
            if (toggle) {
                if (expanded) {
                    delete treeLoadMore[key];
                } else {
                    treeLoadMore[key] = 20;
                }
                expandedMap[key] = !expanded;
                renderTree(instances);
                if (expandedMap[key]) {
                    if (isInstance) loadInstanceDetail(id);
                    else if (isSchema) loadSchemaDetail(id);
                }
                return;
            }
            selectTreeNode(type, id, obj);
        });

        // Double-click → 展开/折叠（下钻一层）
        row.addEventListener("dblclick", function (e) {
            if (children.length === 0) return;
            if (e.target.closest(".dd-tree-actions")) return;
            expandedMap[key] = !expanded;
            renderTree(instances);
            if (!expandedMap[key]) {
                delete treeLoadMore[key];
            } else {
                treeLoadMore[key] = 20;
                if (isInstance) loadInstanceDetail(id);
                else if (isSchema) loadSchemaDetail(id);
            }
        });

        return wrapper;
    }

    function selectTreeNode(type, id, obj) {
        selectedPath = { type: type, id: id };
        ddTree.querySelectorAll(".dd-tree-row.sel").forEach(function (el) { el.classList.remove("sel"); });
        var item = ddTree.querySelector('.dd-tree-row[data-type="' + type + '"][data-id="' + id + '"]');
        if (item) item.classList.add("sel");

        ddPlaceholder.classList.add("hidden");
        ddDetailContent.classList.remove("hidden");

        if (type === "instance") {
            loadAndRenderInstanceDetail(id);
        } else if (type === "schema") {
            loadAndRenderSchemaDetail(id);
        } else if (type === "table") {
            loadTableDetail(id);
        }
    }

    function renderTableHeader(tbl) {
        ddDetailHeader.innerHTML = '<i class="ti ti-table"></i> ' + escapeHtml(tbl.table_name)
            + ' <span class="dd-type-badge">' + escapeHtml(tbl.table_type) + "</span>"
            + (tbl.comment ? ' <span style="color:var(--text-dim);font-weight:400;font-size:12px">— ' + escapeHtml(tbl.comment) + "</span>" : "")
            + (tbl.tags ? ' ' + renderTags(tbl.tags) : "")
            + '<label class="dd-edit-toggle"><input type="checkbox" id="dd-edit-switch"' + (ddEditMode ? ' checked' : '') + '> 编辑</label>';
    }

    // ── Tab 切换 ──
    function switchTab(tab, page) {
        currentTab = tab;
        if (page != null) listPages[tab] = page;
        ddTabBar.querySelectorAll(".dd-tab").forEach(function (el) {
            el.classList.toggle("active", el.dataset.tab === tab);
        });
        if (!currentTable) return;
        switch (tab) {
            case "columns": renderColumns(listPages.columns || 1); break;
            case "indexes": renderIndexes(listPages.indexes || 1); break;
            case "constraints": renderConstraints(listPages.constraints || 1); break;
            case "logs": renderTableLogs(); break;
        }
        // 日志 Tab 是异步渲染，在此不处理高亮；其他 Tab 重新高亮
        if (currentSearchQuery && tab !== "logs") {
            applyDetailHighlights(currentSearchQuery);
        }
    }

    // ── 字段 Tab ──
    function renderColumns(page) {
        var cols = currentTable.columns || [];
        var sorted = cols.slice().sort(function (a, b) { return a.position - b.position; });
        var pageSize = 20;
        var total = sorted.length;
        var totalPages = Math.ceil(total / pageSize) || 1;
        var pg = page || 1;
        if (pg > totalPages) pg = totalPages;
        listPages.columns = pg;
        var start = (pg - 1) * pageSize;
        var pageItems = sorted.slice(start, start + pageSize);
        var html = '<table class="dd-table"><thead><tr>';
        html += "<th>序号</th><th>字段名</th><th>数据类型</th><th>完整类型</th><th>可空</th><th>枚举值</th><th>注释</th><th>标签</th><th>创建时间</th><th>更新时间</th><th></th>";
        html += "</tr></thead><tbody>";
        pageItems.forEach(function (col, i) {
            html += '<tr data-id="' + col.id + '">';
            html += '<td style="color:var(--text-dim)">' + (start + i + 1) + "</td>";
            html += '<td class="dd-editable" data-field="column_name">' + escapeHtml(col.column_name) + "</td>";
            html += '<td class="dd-editable" data-field="data_type">' + escapeHtml(col.data_type) + "</td>";
            html += '<td class="dd-editable" data-field="full_data_type">' + escapeHtml(col.full_data_type || "") + "</td>";
            html += '<td><span class="dd-nullable-text">' + (col.nullable ? "是" : "否") + '</span><span class="dd-edit-only"><input type="checkbox" class="dd-checkbox"' + (col.nullable ? " checked" : "") + " data-id='" + col.id + "'></span></td>";
            html += '<td data-field="enum_info">' + (col.enum_info ? '<button class="dd-btn dd-btn-xs dd-enum-btn" data-enum="' + escapeHtml(col.enum_info) + '">查看</button>' : '') + '</td>';
            html += '<td class="dd-editable" data-field="comment"><span class="dd-comment-text">' + escapeHtml(col.comment || "") + '</span></td>';
            html += '<td class="dd-tags-edit" data-tags="' + escapeHtml(col.tags || "") + '">' + renderTags(col.tags) + '</td>';
                        html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(col.create_time || "") + '</td>';
            html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(col.update_time || "") + '</td>';
            html += '<td><button class="dd-action-btn dd-edit-only" data-action="deleteColumn" data-id="' + col.id + '" title="删除"><i class="ti ti-trash"></i></button></td>';
            html += "</tr>";
        });
        // 添加行
        html += '<tr class="dd-row-add dd-edit-only" id="dd-add-column-row"><td colspan="12"><i class="ti ti-plus"></i> 添加字段</td></tr>';
        html += "</tbody></table>";
        html += renderPaginationBar(pg, totalPages, total, "col");
        ddTabContent.innerHTML = html;

        // 点击添加行
        var addRow = document.getElementById("dd-add-column-row");
        if (addRow) {
            addRow.addEventListener("click", function () {
                showColumnForm(null);
            });
        }

        // 可空复选框（仅编辑模式）
        ddTabContent.querySelectorAll(".dd-cell-nullable input").forEach(function (cb) {
            cb.addEventListener("change", function () {
                if (!ddEditMode) return;
                var colId = parseInt(this.dataset.id);
                updateColumn(colId, { nullable: this.checked });
            });
        });

        // 行内编辑（仅编辑模式）
        ddTabContent.querySelectorAll(".dd-editable").forEach(function (td) {
            td.addEventListener("dblclick", function () {
                if (!ddEditMode) return;
                if (this.querySelector("input")) return;
                var isComment = td.dataset.field === "comment";
                var textSpan = isComment ? td.querySelector(".dd-comment-text") : null;
                var val = textSpan ? textSpan.textContent.trim() : this.textContent.trim();
                var inp = document.createElement("input");
                inp.type = "text";
                inp.className = "dd-cell-edit";
                inp.value = val;
                if (textSpan) {
                    textSpan.textContent = "";
                    textSpan.appendChild(inp);
                } else {
                    this.textContent = "";
                    this.appendChild(inp);
                }
                inp.focus();
                inp.select();
                inp.addEventListener("blur", function () {
                    var newVal = inp.value.trim();
                    var colId = parseInt(td.closest("tr").dataset.id);
                    var field = td.dataset.field;
                    var data = {};
                    data[field] = newVal;
                    updateColumn(colId, data);
                    if (textSpan) {
                        inp.remove();
                        textSpan.textContent = newVal || "";
                    } else {
                        td.textContent = newVal || "";
                    }
                });
                inp.addEventListener("keydown", function (ev) {
                    if (ev.key === "Enter") inp.blur();
                    if (ev.key === "Escape") {
                        if (textSpan) {
                            inp.remove();
                            textSpan.textContent = val;
                        } else {
                            td.textContent = val;
                        }
                    }
                });
            });
        });

        // 标签行内编辑
        ddTabContent.querySelectorAll(".dd-tags-edit").forEach(function (span) {
            span.addEventListener("dblclick", function (e) {
                if (!ddEditMode) return;
                e.stopPropagation();
                if (this.querySelector("input")) return;
                var val = this.dataset.tags || "";
                var inp = document.createElement("input");
                inp.type = "text";
                inp.className = "dd-cell-edit";
                inp.value = val;
                inp.placeholder = "标签1,标签2,...";
                this.textContent = "";
                this.appendChild(inp);
                inp.focus();
                inp.select();
                var self = this;
                inp.addEventListener("blur", function () {
                    var newVal = inp.value.trim();
                    var colId = parseInt(self.closest("tr").dataset.id);
                    updateColumn(colId, { tags: newVal });
                    self.dataset.tags = newVal;
                    self.innerHTML = renderTags(newVal);
                });
                inp.addEventListener("keydown", function (ev) {
                    if (ev.key === "Enter") inp.blur();
                    if (ev.key === "Escape") {
                        self.innerHTML = renderTags(val);
                    }
                });
            });
        });

        // 删除按钮
        ddTabContent.querySelectorAll("[data-action=deleteColumn]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var colId = parseInt(this.dataset.id);
                if (confirm("确认删除此字段？")) deleteColumn(colId);
            });
        });

        // 枚举值查看按钮
        ddTabContent.querySelectorAll(".dd-enum-btn").forEach(function (btn) {
            btn.addEventListener("click", function (e) {
                e.stopPropagation();
                showEnumModal(this.dataset.enum);
            });
        });
    }

    // ── 索引 Tab ──
    function renderIndexes(page) {
        var idxs = currentTable.indexes || [];
        var cols = currentTable.columns || [];
        var pageSize = 20;
        var total = idxs.length;
        var totalPages = Math.ceil(total / pageSize) || 1;
        var pg = page || 1;
        if (pg > totalPages) pg = totalPages;
        listPages.indexes = pg;
        var start = (pg - 1) * pageSize;
        var pageItems = idxs.slice(start, start + pageSize);
        var html = "";
        if (idxs.length === 0) {
            html += '<div class="dd-log-empty">暂无索引</div>';
        } else {
            html += '<table class="dd-table"><thead><tr>';
            html += "<th>序号</th><th>索引名</th><th>类型</th><th>唯一</th><th>包含字段</th><th>创建时间</th><th>更新时间</th><th></th>";
            html += "</tr></thead><tbody>";
            pageItems.forEach(function (idx, i) {
                var fieldNames = (idx.column_ids || []).map(function (cid) {
                    var c = cols.find(function (x) { return x.id === cid; });
                    return c ? c.column_name : "?" + cid;
                }).join(", ");
                html += '<tr data-id="' + idx.id + '">';
                html += '<td style="color:var(--text-dim)">' + (start + i + 1) + '</td>';
                html += "<td>" + escapeHtml(idx.index_name) + "</td>";
                html += "<td>" + escapeHtml(idx.index_type) + "</td>";
                html += "<td>" + (idx.is_unique ? "是" : "否") + "</td>";
                html += "<td>" + escapeHtml(fieldNames) + "</td>";
                html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(idx.create_time || "") + '</td>';
                html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(idx.update_time || "") + '</td>';
                html += '<td><button class="dd-action-btn dd-edit-only" data-action="deleteIndex" data-id="' + idx.id + '" title="删除"><i class="ti ti-trash"></i></button></td>';
                html += "</tr>";
            });
            html += "</tbody></table>";
            html += renderPaginationBar(pg, totalPages, total, "idx");
        }
        html += '<div style="margin-top:8px"><button class="dd-btn dd-btn-sm dd-edit-only" id="dd-add-index-btn"><i class="ti ti-plus"></i> 添加索引</button></div>';
        ddTabContent.innerHTML = html;

        document.getElementById("dd-add-index-btn")?.addEventListener("click", function () {
            showIndexForm(null);
        });
        ddTabContent.querySelectorAll("[data-action=deleteIndex]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (confirm("确认删除此索引？")) {
                    deleteIndex(parseInt(this.dataset.id));
                }
            });
        });
    }

    // ── 约束 Tab ──
    function renderConstraints(page) {
        var cons = currentTable.constraints || [];
        var cols = currentTable.columns || [];
        var pageSize = 20;
        var total = cons.length;
        var totalPages = Math.ceil(total / pageSize) || 1;
        var pg = page || 1;
        if (pg > totalPages) pg = totalPages;
        listPages.constraints = pg;
        var start = (pg - 1) * pageSize;
        var pageItems = cons.slice(start, start + pageSize);
        var html = "";
        if (cons.length === 0) {
            html += '<div class="dd-log-empty">暂无约束</div>';
        } else {
            html += '<table class="dd-table"><thead><tr>';
            html += "<th>序号</th><th>约束名</th><th>类型</th><th>包含字段</th><th>外键目标表</th><th>On Delete</th><th>On Update</th><th>创建时间</th><th>更新时间</th><th></th>";
            html += "</tr></thead><tbody>";
            pageItems.forEach(function (con, i) {
                var fieldNames = (con.column_ids || []).map(function (cid) {
                    var c = cols.find(function (x) { return x.id === cid; });
                    return c ? c.column_name : "?" + cid;
                }).join(", ");
                html += '<tr data-id="' + con.id + '">';
                html += '<td style="color:var(--text-dim)">' + (start + i + 1) + '</td>';
                html += "<td>" + escapeHtml(con.constraint_name) + "</td>";
                html += "<td>" + escapeHtml(con.constraint_type) + "</td>";
                html += "<td>" + escapeHtml(fieldNames) + "</td>";
                html += "<td>" + escapeHtml(con.target_table_id ? String(con.target_table_id) : "") + "</td>";
                html += "<td>" + escapeHtml(con.on_delete || "") + "</td>";
                html += "<td>" + escapeHtml(con.on_update || "") + "</td>";
                html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(con.create_time || "") + '</td>';
                html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(con.update_time || "") + '</td>';
                html += '<td><button class="dd-action-btn dd-edit-only" data-action="deleteConstraint" data-id="' + con.id + '" title="删除"><i class="ti ti-trash"></i></button></td>';
                html += "</tr>";
            });
            html += "</tbody></table>";
            html += renderPaginationBar(pg, totalPages, total, "con");
        }
        html += '<div style="margin-top:8px"><button class="dd-btn dd-btn-sm dd-edit-only" id="dd-add-constraint-btn"><i class="ti ti-plus"></i> 添加约束</button></div>';
        ddTabContent.innerHTML = html;

        document.getElementById("dd-add-constraint-btn")?.addEventListener("click", function () {
            showConstraintForm(null);
        });
        ddTabContent.querySelectorAll("[data-action=deleteConstraint]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (confirm("确认删除此约束？")) {
                    deleteConstraint(parseInt(this.dataset.id));
                }
            });
        });
    }

    // ── 变更日志 Tab ──
    function renderTableLogs() {
        ddTabContent.innerHTML = '<div class="dd-log-empty">加载中...</div>';
        var tableId = currentTable.id;
        // 建立对象名称查找表
        var nameMap = {};
        nameMap["table-" + tableId] = currentTable.table_name || tableId;
        (currentTable.columns || []).forEach(function (c) { nameMap["column-" + c.id] = c.column_name; });
        (currentTable.indexes || []).forEach(function (i) { nameMap["index-" + i.id] = i.index_name; });
        (currentTable.constraints || []).forEach(function (c) { nameMap["constraint-" + c.id] = c.constraint_name; });
        // 补充已删除对象名称
        Object.keys(deletedObjectMap).forEach(function (type) {
            Object.keys(deletedObjectMap[type]).forEach(function (id) {
                nameMap[type + "-" + id] = deletedObjectMap[type][id];
            });
        });
        var fetchUrl = "/api/data-dict/tables/" + tableId + "/logs?page_size=20";
        // 表级日志用稍小的 id 容器，内联分页
        var container = ddTabContent;
        container.innerHTML = '<div class="dd-log-empty">加载中...</div>';
        var pageSize = 20;
        var state = { page: 1, total: 0, totalPages: 0, pageSize: pageSize };

        function loadLogPage(page) {
            container.innerHTML = '<div class="dd-log-empty">加载中...</div>';
            ddFetch(fetchUrl + "&page=" + page)
                .then(function (r) { return r.json(); })
                .then(function (res) {
                    state.total = res.total;
                    state.page = res.page;
                    state.totalPages = Math.ceil(res.total / res.page_size) || 1;
                    var items = res.items || [];
                    var html = '<div class="dd-log-list">';
                    if (items.length === 0) {
                        html = '<div class="dd-log-empty">暂无变更日志</div>';
                    } else {
                        items.forEach(function (log) {
                            var opLabel = { insert: "新增", update: "修改", delete: "删除" }[log.op_type] || log.op_type;
                            var objLabel = OBJECT_LABELS[log.object_type] || log.object_type;
                            var objName = nameMap ? nameMap[log.object_type + "-" + log.object_id] : null;
                            html += '<div class="dd-log-item">';
                            html += '<span class="dd-log-op ' + log.op_type + '">' + opLabel + "</span>";
                            html += '<div class="dd-log-body">';
                            if (objName) {
                                html += '<span class="dd-log-obj-name">' + escapeHtml(objName) + '</span> ';
                            }
                            if (log.field_name !== "*") {
                                html += '<span class="dd-log-field">' + escapeHtml(log.field_name) + "</span>";
                                if (log.old_value != null) {
                                    html += ': <span class="dd-log-value">' + escapeHtml(log.old_value) + "</span>";
                                    html += ' → <span class="dd-log-value">' + escapeHtml(log.new_value || "") + "</span>";
                                } else {
                                    html += ': <span class="dd-log-value">' + escapeHtml(log.new_value || "") + "</span>";
                                }
                            } else {
                                html += "<span>" + escapeHtml(objLabel) + " "
                                    + logActionLabel(log) + "</span>";
                            }
                            if (log._context) {
                                html += '<div class="dd-log-context">' + escapeHtml(log._context) + '</div>';
                            }
                            html += '<div class="dd-log-meta">';
                            html += "<span>" + escapeHtml(log.operator) + "</span>";
                            html += "<span>" + escapeHtml(log.create_at || "") + "</span>";
                            html += "</div>";
                            html += "</div></div>";
                        });
                        html += "</div>";
                        if (state.totalPages > 1) {
                            html += '<div class="dd-pagination">';
                            html += '<button class="dd-page-btn"' + (state.page <= 1 ? ' disabled' : '') + ' data-tpage="' + (state.page - 1) + '">上一页</button>';
                            html += '<span class="dd-page-info">第 ' + state.page + ' / ' + state.totalPages + ' 页（共 ' + state.total + ' 条）</span>';
                            html += '<button class="dd-page-btn"' + (state.page >= state.totalPages ? ' disabled' : '') + ' data-tpage="' + (state.page + 1) + '">下一页</button>';
                            html += '</div>';
                        }
                    }
                    container.innerHTML = html;
                    container.querySelectorAll("[data-tpage]").forEach(function (btn) {
                        btn.addEventListener("click", function () {
                            var p = parseInt(this.dataset.tpage);
                            if (p > 0 && p <= state.totalPages) loadLogPage(p);
                        });
                    });
                })
                .catch(function () {
                    container.innerHTML = '<div class="dd-log-empty">加载失败</div>';
                });
        }

        loadLogPage(1);
    }

    var OBJECT_LABELS = {
        instance: "数据库实例", schema: "Schema", table: "数据表",
        column: "字段", index: "索引", constraint: "约束",
    };

    function renderLogList(logs, container, nameMap) {
        if (!logs || logs.length === 0) {
            container.innerHTML = '<div class="dd-log-empty">暂无变更日志</div>';
            return;
        }
        var html = '<div class="dd-log-list">';
        logs.forEach(function (log) {
            var opLabel = { insert: "新增", update: "修改", delete: "删除" }[log.op_type] || log.op_type;
            var objLabel = OBJECT_LABELS[log.object_type] || log.object_type;
            var objName = nameMap ? nameMap[log.object_type + "-" + log.object_id] : null;
            html += '<div class="dd-log-item">';
            html += '<span class="dd-log-op ' + log.op_type + '">' + opLabel + "</span>";
            html += '<div class="dd-log-body">';
            if (objName) {
                html += '<span class="dd-log-obj-name">' + escapeHtml(objName) + '</span> ';
            }
            if (log.field_name !== "*") {
                html += '<span class="dd-log-field">' + escapeHtml(log.field_name) + "</span>";
                if (log.old_value != null) {
                    html += ': <span class="dd-log-value">' + escapeHtml(log.old_value) + "</span>";
                    html += ' → <span class="dd-log-value">' + escapeHtml(log.new_value || "") + "</span>";
                } else {
                    html += ': <span class="dd-log-value">' + escapeHtml(log.new_value || "") + "</span>";
                }
            } else {
                html += "<span>" + escapeHtml(objLabel) + " "
                    + logActionLabel(log) + "</span>";
            }
            if (log._context) {
                html += '<div class="dd-log-context">' + escapeHtml(log._context) + '</div>';
            }
            html += '<div class="dd-log-meta">';
            html += "<span>" + escapeHtml(log.operator) + "</span>";
            html += "<span>" + escapeHtml(log.create_at || "") + "</span>";
            html += "</div>";
            html += "</div></div>";
        });
        html += "</div>";
        container.innerHTML = html;
    }

    // ── 分页日志组件 ──
    function initLogPager(containerId, fetchUrl, nameMap, pageSize) {
        var container = document.getElementById(containerId);
        if (!container) return;
        var state = { page: 1, total: 0, totalPages: 0, pageSize: pageSize || 20 };

        function loadPage(page) {
            container.innerHTML = '<div class="dd-log-empty">加载中...</div>';
            var sep = fetchUrl.indexOf("?") === -1 ? "?" : "&";
            ddFetch(fetchUrl + sep + "page=" + page + "&page_size=" + state.pageSize)
                .then(function (r) { return r.json(); })
                .then(function (res) {
                    state.total = res.total;
                    state.page = res.page;
                    state.totalPages = Math.ceil(res.total / res.page_size) || 1;
                    var items = res.items || [];
                    var html = '<div class="dd-log-list">';
                    if (items.length === 0) {
                        html = '<div class="dd-log-empty">暂无变更日志</div>';
                    } else {
                        items.forEach(function (log) {
                            var opLabel = { insert: "新增", update: "修改", delete: "删除" }[log.op_type] || log.op_type;
                            var objLabel = OBJECT_LABELS[log.object_type] || log.object_type;
                            var objName = nameMap ? nameMap[log.object_type + "-" + log.object_id] : null;
                            html += '<div class="dd-log-item">';
                            html += '<span class="dd-log-op ' + log.op_type + '">' + opLabel + "</span>";
                            html += '<div class="dd-log-body">';
                            if (objName) {
                                html += '<span class="dd-log-obj-name">' + escapeHtml(objName) + '</span> ';
                            }
                            if (log.field_name !== "*") {
                                html += '<span class="dd-log-field">' + escapeHtml(log.field_name) + "</span>";
                                if (log.old_value != null) {
                                    html += ': <span class="dd-log-value">' + escapeHtml(log.old_value) + "</span>";
                                    html += ' → <span class="dd-log-value">' + escapeHtml(log.new_value || "") + "</span>";
                                } else {
                                    html += ': <span class="dd-log-value">' + escapeHtml(log.new_value || "") + "</span>";
                                }
                            } else {
                                html += "<span>" + escapeHtml(objLabel) + " "
                                    + logActionLabel(log) + "</span>";
                            }
                            if (log._context) {
                                html += '<div class="dd-log-context">' + escapeHtml(log._context) + '</div>';
                            }
                            html += '<div class="dd-log-meta">';
                            html += "<span>" + escapeHtml(log.operator) + "</span>";
                            html += "<span>" + escapeHtml(log.create_at || "") + "</span>";
                            html += "</div>";
                            html += "</div></div>";
                        });
                        html += "</div>";
                        // 分页控件
                        if (state.totalPages > 1) {
                            html += '<div class="dd-pagination">';
                            html += '<button class="dd-page-btn"' + (state.page <= 1 ? ' disabled' : '') + ' data-page="' + (state.page - 1) + '">上一页</button>';
                            html += '<span class="dd-page-info">第 ' + state.page + ' / ' + state.totalPages + ' 页（共 ' + state.total + ' 条）</span>';
                            html += '<button class="dd-page-btn"' + (state.page >= state.totalPages ? ' disabled' : '') + ' data-page="' + (state.page + 1) + '">下一页</button>';
                            html += '</div>';
                        }
                    }
                    container.innerHTML = html;
                    container.querySelectorAll("[data-page]").forEach(function (btn) {
                        btn.addEventListener("click", function () {
                            var p = parseInt(this.dataset.page);
                            if (p > 0 && p <= state.totalPages) loadPage(p);
                        });
                    });
                })
                .catch(function () {
                    container.innerHTML = '<div class="dd-log-empty">加载失败</div>';
                });
        }

        loadPage(1);
    }

    // ── CRUD 操作 ──

    // Instance
    function loadInstances(callback) {
        ddFetch("/api/data-dict/instances")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                instances = data || [];
                renderTree(instances);
                if (callback) callback();
            })
            .catch(function (e) {
                showToast("加载实例失败", true);
            });
    }

    function loadInstanceDetail(instanceId) {
        ddFetch("/api/data-dict/instances/" + instanceId)
            .then(function (r) { return r.json(); })
            .then(function (inst) {
                // Update the instances list with fresh schemas
                var found = false;
                for (var i = 0; i < instances.length; i++) {
                    if (instances[i].id === instanceId) {
                        instances[i].schemas = inst.schemas || [];
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    instances.push(inst);
                }
                renderTree(instances);
            })
            .catch(function () {
                showToast("加载实例详情失败", true);
            });
    }

    function showInstanceForm(instance) {
        var title = instance ? "编辑实例" : "添加实例";
        var name = instance ? instance.instance_name : "";
        var dbType = instance ? instance.db_type : "";
        var dsId = instance ? (instance.datasource_id || "") : "";
        var remark = instance ? (instance.remark || "") : "";
        var html = '<div class="dd-overlay" id="dd-overlay">';
        html += '<div class="dd-overlay-content">';
        html += "<h3>" + title + "</h3>";
        if (instance) {
            html += '<div class="dd-form-readonly"><span>ID: ' + instance.id + '</span><span>创建: ' + escapeHtml(instance.create_time || "") + '</span><span>更新: ' + escapeHtml(instance.update_time || "") + '</span></div>';
        }
        html += '<div class="dd-form-group"><label>实例名称 *</label><input id="dd-f-name" value="' + escapeHtml(name) + '"></div>';
        html += '<div class="dd-form-group"><label>数据库类型 *</label><div class="dd-combo"><input id="dd-f-dbtype" placeholder="请选择或输入" autocomplete="off"><i class="ti ti-chevron-down dd-combo-arrow" id="dd-combo-arrow"></i><div class="dd-combo-dropdown hidden" id="dd-combo-dropdown"></div></div></div>';
        html += '<div class="dd-form-group"><label>数据源ID</label><input id="dd-f-dsid" value="' + escapeHtml(dsId) + '"></div>';
        html += '<div class="dd-form-group"><label>备注</label><textarea id="dd-f-remark">' + escapeHtml(remark) + "</textarea></div>";
        html += '<div class="dd-overlay-actions">';
        html += '<button class="dd-btn-cancel" id="dd-overlay-cancel">取消</button>';
        html += '<button class="dd-btn-primary" id="dd-overlay-ok">确认</button>';
        html += "</div></div></div>";

        var div = ddE("div");
        div.innerHTML = html;
        document.body.appendChild(div.firstElementChild);

        var overlay = document.getElementById("dd-overlay");
        // 动态加载数据库类型选项
        ddFetch("/api/data-dict/db-types")
            .then(function (r) { return r.json(); })
            .then(function (types) {
                var input = document.getElementById("dd-f-dbtype");
                var dd = document.getElementById("dd-combo-dropdown");
                if (!input || !dd) return;
                dd.innerHTML = "";
                types.forEach(function (t) {
                    var item = document.createElement("div");
                    item.className = "dd-combo-option";
                    item.textContent = t;
                    item.dataset.value = t;
                    item.addEventListener("click", function (e) {
                        input.value = t;
                        dd.classList.add("hidden");
                        e.stopPropagation();
                    });
                    dd.appendChild(item);
                });
                if (dbType) input.value = dbType;
                // 箭头点击切换下拉
                var arrow = document.getElementById("dd-combo-arrow");
                if (arrow) {
                    arrow.addEventListener("click", function (e) {
                        dd.classList.toggle("hidden");
                        e.stopPropagation();
                    });
                }
                // 输入框聚焦显示下拉
                input.addEventListener("focus", function () { dd.classList.remove("hidden"); });
                // 点击外部关闭下拉
                document.addEventListener("click", function (e) {
                    var combo = input.closest(".dd-combo");
                    if (combo && !combo.contains(e.target)) {
                        dd.classList.add("hidden");
                    }
                });
            })
            .catch(function (e) { console.error("加载数据库类型失败", e); });
        document.getElementById("dd-overlay-cancel").addEventListener("click", function () { overlay.remove(); });
        document.getElementById("dd-overlay-ok").addEventListener("click", function () {
            var dbTypeVal = document.getElementById("dd-f-dbtype").value;
            if (!dbTypeVal) { showToast("请选择数据库类型", true); return; }
            var data = {
                instance_name: document.getElementById("dd-f-name").value.trim(),
                db_type: dbTypeVal,
                datasource_id: document.getElementById("dd-f-dsid").value.trim() || null,
                remark: document.getElementById("dd-f-remark").value.trim() || null,
            };
            if (!data.instance_name) { showToast("请输入实例名称", true); return; }
            if (instance) {
                updateInstance(instance.id, data);
            } else {
                createInstance(data);
            }
            overlay.remove();
        });
    }

    function createInstance(data) {
        ddFetch("/api/data-dict/instances", { method: "POST", body: data })
            .then(function (r) {
                if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "创建失败"); });
                return r.json();
            })
            .then(function () {
                showToast("创建成功");
                loadInstances(function () {
                    renderAllInstances();
                });
            })
            .catch(function (e) {
                showToast(e.message || "创建失败", true);
            });
    }

    function updateInstance(id, data) {
        ddFetch("/api/data-dict/instances/" + id, { method: "PUT", body: data })
            .then(function (r) { return r.json(); })
            .then(function () {
                showToast("更新成功");
                loadInstances(function () {
                    if (selectedPath && selectedPath.type === "instance" && selectedPath.id === id) {
                        loadAndRenderInstanceDetail(id);
                    } else if (selectedPath === null && !ddPlaceholder.classList.contains("hidden") === false) {
                        renderAllInstances();
                    }
                });
            })
            .catch(function () { showToast("更新失败", true); });
    }

    function deleteInstance(id) {
        // 记录已删除实例名，供日志 nameMap 使用
        var inst = instances.find(function (i) { return i.id === id; });
        if (inst) {
            if (!deletedObjectMap["instance"]) deletedObjectMap["instance"] = {};
            deletedObjectMap["instance"][id] = inst.instance_name;
        }
        if (!confirm("确认删除此实例？所有下层数据将被级联删除。")) return;
        ddFetch("/api/data-dict/instances/" + id, { method: "DELETE" })
            .then(function (r) { return r.json(); })
            .then(function () {
                showToast("删除成功");
                selectedPath = null;
                ddPlaceholder.classList.remove("hidden");
                ddDetailContent.classList.add("hidden");
                loadInstances();
            })
            .catch(function () { showToast("删除失败", true); });
    }

    // Schema
    function showSchemaForm(schema, instanceId) {
        var title = schema ? "编辑 Schema" : "添加 Schema";
        var name = schema ? schema.schema_name : "";
        var remark = schema ? (schema.remark || "") : "";
        var html = '<div class="dd-overlay" id="dd-overlay">';
        html += '<div class="dd-overlay-content">';
        html += "<h3>" + title + "</h3>";
        if (schema) {
            html += '<div class="dd-form-readonly"><span>ID: ' + schema.id + '</span><span>创建: ' + escapeHtml(schema.create_time || "") + '</span><span>更新: ' + escapeHtml(schema.update_time || "") + '</span></div>';
        }
        html += '<div class="dd-form-group"><label>Schema 名称 *</label><input id="dd-f-name" value="' + escapeHtml(name) + '"></div>';
        html += '<div class="dd-form-group"><label>备注</label><textarea id="dd-f-remark">' + escapeHtml(remark) + "</textarea></div>";
        html += '<div class="dd-overlay-actions">';
        html += '<button class="dd-btn-cancel" id="dd-overlay-cancel">取消</button>';
        html += '<button class="dd-btn-primary" id="dd-overlay-ok">确认</button>';
        html += "</div></div></div>";

        var div = ddE("div");
        div.innerHTML = html;
        document.body.appendChild(div.firstElementChild);

        var overlay = document.getElementById("dd-overlay");
        document.getElementById("dd-overlay-cancel").addEventListener("click", function () { overlay.remove(); });
        document.getElementById("dd-overlay-ok").addEventListener("click", function () {
            var data = {
                instance_id: instanceId,
                schema_name: document.getElementById("dd-f-name").value.trim(),
                remark: document.getElementById("dd-f-remark").value.trim() || null,
            };
            if (!data.schema_name) { showToast("请输入名称", true); return; }
            var refreshDetail = function () {
                if (selectedPath && selectedPath.type === "instance" && selectedPath.id === instanceId) {
                    loadAndRenderInstanceDetail(instanceId);
                }
                if (schema && selectedPath && selectedPath.type === "schema" && selectedPath.id === schema.id) {
                    loadAndRenderSchemaDetail(schema.id);
                }
            };
            if (schema) {
                ddFetch("/api/data-dict/schemas/" + schema.id, { method: "PUT", body: data })
                    .then(function (r) { return r.json(); })
                    .then(function () {
                        showToast("更新成功");
                        loadInstanceDetail(instanceId);
                        refreshDetail();
                        overlay.remove();
                    })
                    .catch(function () { showToast("更新失败", true); });
            } else {
                ddFetch("/api/data-dict/schemas", { method: "POST", body: data })
                    .then(function (r) { return r.json(); })
                    .then(function () {
                        showToast("创建成功");
                        loadInstanceDetail(instanceId);
                        refreshDetail();
                        overlay.remove();
                    })
                    .catch(function () { showToast("创建失败", true); });
            }
        });
    }

    function deleteSchema(id, instanceId) {
        // 记录已删除 Schema 名
        for (var si = 0; si < instances.length; si++) {
            var ss = instances[si].schemas || [];
            for (var sj = 0; sj < ss.length; sj++) {
                if (ss[sj].id === id) {
                    if (!deletedObjectMap["schema"]) deletedObjectMap["schema"] = {};
                    deletedObjectMap["schema"][id] = ss[sj].schema_name;
                    break;
                }
            }
        }
        if (!confirm("确认删除此 Schema？所有下层表将被级联删除。")) return;
        ddFetch("/api/data-dict/schemas/" + id, { method: "DELETE" })
            .then(function (r) { return r.json(); })
            .then(function () {
                showToast("删除成功");
                loadInstanceDetail(instanceId);
                if (selectedPath && selectedPath.type === "instance" && selectedPath.id === instanceId) {
                    loadAndRenderInstanceDetail(instanceId);
                }
            })
            .catch(function () { showToast("删除失败", true); });
    }

    function loadSchemaDetail(schemaId) {
        // Load tables for a schema - fetch from the instance we already have
        // We need to find which instance this schema belongs to
        for (var i = 0; i < instances.length; i++) {
            var schemas = instances[i].schemas || [];
            for (var j = 0; j < schemas.length; j++) {
                if (schemas[j].id === schemaId) {
                    ddFetch("/api/data-dict/schemas/" + schemaId + "/tables")
                        .then(function (r) { return r.json(); })
                        .then(function (tables) {
                            // Update local data and re-render
                            // First, update the tree data
                            schemas[j].tables = tables;
                            renderTree(instances);
                        })
                        .catch(function () { showToast("加载表列表失败", true); });
                    return;
                }
            }
        }
    }

    // ── 分页栏渲染 ──
    function renderPaginationBar(currentPage, totalPages, total, prefix) {
        if (totalPages <= 1) return '';
        var html = '<div class="dd-pagination">';
        html += '<button class="dd-page-btn"' + (currentPage <= 1 ? ' disabled' : '') + ' data-dd-page="' + prefix + '-' + (currentPage - 1) + '">上一页</button>';
        html += '<span class="dd-page-info">第 ' + currentPage + ' / ' + totalPages + ' 页（共 ' + total + ' 条）</span>';
        html += '<button class="dd-page-btn"' + (currentPage >= totalPages ? ' disabled' : '') + ' data-dd-page="' + prefix + '-' + (currentPage + 1) + '">下一页</button>';
        html += '</div>';
        return html;
    }

    // ── 搜索 ──
    function doSearch(query, page) {
        currentSearchQuery = query;
        ddTree.innerHTML = '<div class="dd-tree-empty">搜索中...</div>';
        var url = "/api/data-dict/search?q=" + encodeURIComponent(query) + "&page=" + (page || 1) + "&page_size=" + SEARCH_PAGE_SIZE;
        ddFetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                searchResults = data.items || [];
                searchTotal = data.total || 0;
                searchPage = data.page || 1;
                searchTotalPages = Math.ceil(searchTotal / SEARCH_PAGE_SIZE) || 1;
                showSearchResults(query);
            })
            .catch(function () {
                ddTree.innerHTML = '<div class="dd-tree-empty">搜索失败</div>';
            });
    }

    function showSearchResults(query) {
        isSearchMode = true;
        if (searchResults.length === 0) {
            ddTree.innerHTML = '<div class="dd-search-empty">未找到匹配 "' + escapeHtml(query) + '" 的结果</div>';
            return;
        }

        // 渲染列表（所有情况都渲染，1 条也渲染）
        var html = '<div class="dd-search-results">';
        searchResults.forEach(function (item, idx) {
            var path = escapeHtml(item.instance_name) + ' > ' + escapeHtml(item.schema_name) + ' > ' + escapeHtml(item.table_name);
            var meta = '';
            if (item.type === 'column') {
                meta = '字段: ' + escapeHtml(item.column_name);
            } else if (item.matched_field === 'table_name') {
                meta = '表名匹配';
            } else if (item.matched_field === 'table_comment') {
                meta = '注释匹配';
            } else if (item.matched_field === 'tags') {
                meta = '标签: ' + escapeHtml(item.column_tags || item.table_tags || '');
            } else {
                meta = '表名匹配';
            }
            var comment = item.table_comment ? escapeHtml(item.table_comment) : '';
            var showTags = '';
            if (item.matched_field === 'tags') {
                showTags = item.type === 'column' ? (item.column_tags || '') : (item.table_tags || '');
            }
            html += '<div class="dd-search-item' + (idx === 0 ? ' sel' : '') + '" data-table-id="' + item.table_id + '" data-schema-id="' + item.schema_id + '" data-instance-id="' + item.instance_id + '">';
            html += '<div class="dd-search-path">' + path + '</div>';
            if (showTags) html += '<div class="dd-search-tags">' + renderTags(showTags) + '</div>';
            html += '<div class="dd-search-meta">' + meta + '</div>';
            if (comment) html += '<div class="dd-search-comment">' + comment + '</div>';
            html += '</div>';
        });
        html += '</div>';

        // 分页
        if (searchTotalPages > 1) {
            html += '<div class="dd-pagination">';
            html += '<button class="dd-page-btn"' + (searchPage <= 1 ? ' disabled' : '') + ' data-search-page="' + (searchPage - 1) + '">上一页</button>';
            html += '<span class="dd-page-info">第 ' + searchPage + ' / ' + searchTotalPages + ' 页（共 ' + searchTotal + ' 条）</span>';
            html += '<button class="dd-page-btn"' + (searchPage >= searchTotalPages ? ' disabled' : '') + ' data-search-page="' + (searchPage + 1) + '">下一页</button>';
            html += '</div>';
        }

        ddTree.innerHTML = html;

        // 点击结果导航（不清空搜索，仅切换右侧详情）
        ddTree.querySelectorAll(".dd-search-item").forEach(function (el) {
            el.addEventListener("click", function () {
                navigateToResult({
                    table_id: parseInt(this.dataset.tableId),
                    schema_id: parseInt(this.dataset.schemaId),
                    instance_id: parseInt(this.dataset.instanceId),
                });
                ddTree.querySelectorAll(".dd-search-item.sel").forEach(function (s) { s.classList.remove("sel"); });
                this.classList.add("sel");
            });
        });

        // 搜索分页
        ddTree.querySelectorAll("[data-search-page]").forEach(function (btn) {
            btn.addEventListener("click", function (e) {
                var p = parseInt(this.dataset.searchPage);
                if (p > 0 && p <= searchTotalPages) {
                    var q = document.getElementById("dd-search-input");
                    if (q) doSearch(q.value, p);
                }
                e.stopPropagation();
            });
        });

        // 加载第 1 条结果的详情
        if (searchResults.length > 0) {
            loadTableDetail(searchResults[0].table_id);
        }
    }

    function navigateToResult(item) {
        // 不清空搜索，保持搜索结果可见 — 仅切换右侧详情
        loadTableDetail(item.table_id);
    }

    // ── 详情高亮 ──
    function removeDetailHighlights() {
        [ddDetailHeader, ddTabContent].forEach(function (container) {
            if (!container) return;
            container.querySelectorAll("mark").forEach(function (m) {
                m.replaceWith(document.createTextNode(m.textContent));
            });
            container.querySelectorAll("span.hl-wrap").forEach(function (s) {
                var parent = s.parentNode;
                while (s.firstChild) parent.insertBefore(s.firstChild, s);
                parent.removeChild(s);
            });
        });
    }

    function applyDetailHighlights(query) {
        removeDetailHighlights();
        if (!query) return;
        var escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        var regex = new RegExp("(" + escaped + ")", "gi");
        function highlightNode(node) {
            if (node.nodeType === 3) {
                var text = node.textContent;
                regex.lastIndex = 0;
                if (regex.test(text)) {
                    regex.lastIndex = 0;
                    var span = document.createElement("span");
                    span.className = "hl-wrap";
                    span.innerHTML = text.replace(regex, "<mark>$1</mark>");
                    node.parentNode.replaceChild(span, node);
                }
            } else if (node.nodeType === 1 && !/^(script|style|textarea|mark)$/i.test(node.tagName)) {
                Array.from(node.childNodes).forEach(highlightNode);
            }
        }
        highlightNode(ddDetailHeader);
        highlightNode(ddTabContent);
    }

    function restoreTree() {
        clearTimeout(searchTimer);
        isSearchMode = false;
        currentSearchQuery = "";
        removeDetailHighlights();
        var searchInput = document.getElementById("dd-search-input");
        if (searchInput) searchInput.value = "";
        var clearBtn = document.getElementById("dd-search-clear");
        if (clearBtn) clearBtn.classList.add("hidden");
        renderTree(instances);
        // 如果已有选中路径或正在查看表详情，保持右侧不变；否则显示占位
        if (!selectedPath && !currentTable) {
            ddPlaceholder.classList.remove("hidden");
            ddDetailContent.classList.add("hidden");
        }
    }

    // ── 实例/Schema 右侧详情 ──
    function loadAndRenderInstanceDetail(instanceId, page) {
        listPages.instanceSchemas = page || 1;
        ddFetch("/api/data-dict/instances/" + instanceId)
            .then(function (r) { return r.json(); })
            .then(function (inst) {
                // Update tree data
                for (var i = 0; i < instances.length; i++) {
                    if (instances[i].id === instanceId) {
                        instances[i].schemas = inst.schemas || [];
                        break;
                    }
                }
                renderInstanceDetail(inst, listPages.instanceSchemas);
            })
            .catch(function () {
                ddTabContent.innerHTML = '<div class="dd-log-empty">加载失败</div>';
            });
    }

    function renderInstanceDetail(inst, page) {
        listPages.instanceSchemas = page || 1;
        ddTabBar.classList.add("hidden");
        ddDetailHeader.innerHTML = '<i class="ti ti-server-2"></i> ' + escapeHtml(inst.instance_name)
            + ' <span class="dd-type-badge">' + escapeHtml(inst.db_type) + "</span>"
            + (inst.remark ? ' <span style="color:var(--text-dim);font-weight:400;font-size:12px">— ' + escapeHtml(inst.remark) + "</span>" : "")
            + '<label class="dd-edit-toggle"><input type="checkbox" id="dd-edit-switch"' + (ddEditMode ? ' checked' : '') + '> 编辑</label>';
        var instanceId = inst.id;
        var schemas = inst.schemas || [];
        // 分页
        var pageSize = 20;
        var total = schemas.length;
        var totalPages = Math.ceil(total / pageSize) || 1;
        var pg = listPages.instanceSchemas;
        if (pg > totalPages) pg = totalPages;
        listPages.instanceSchemas = pg;
        var start = (pg - 1) * pageSize;
        var pageItems = schemas.slice(start, start + pageSize);
        var html = '<div class="dd-detail-list" data-instance-id="' + instanceId + '"><div class="dd-detail-list-header">';
        html += '<span class="dd-detail-list-title">Schema 列表</span>';
        html += '<button class="dd-btn dd-btn-sm dd-edit-only" data-action="addSchemaFromInstance"><i class="ti ti-plus"></i> 添加 Schema</button>';
        html += '</div><table class="dd-table"><thead><tr><th>序号</th><th>名称</th><th>备注</th><th>表数量</th><th>创建时间</th><th>更新时间</th><th>操作</th></tr></thead><tbody>';
        if (schemas.length === 0) {
            html += '<tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:12px">暂无 Schema</td></tr>';
        } else {
            pageItems.forEach(function (s, i) {
                html += '<tr><td style="color:var(--text-dim)">' + (start + i + 1) + '</td>';
                html += '<td>' + escapeHtml(s.schema_name) + '</td>';
                html += '<td style="color:var(--text-dim)">' + escapeHtml(s.remark || "") + '</td>';
                html += '<td>' + ((s.tables || []).length) + '</td>';
                html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(s.create_time || "") + '</td>';
                html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(s.update_time || "") + '</td>';
                html += '<td>';
                html += '<button class="dd-action-btn dd-edit-only" data-action="editSchema" data-schema-id="' + s.id + '" title="编辑"><i class="ti ti-edit"></i></button> ';
                html += '<button class="dd-action-btn dd-edit-only" data-action="deleteSchema" data-schema-id="' + s.id + '" data-instance-id="' + instanceId + '" title="删除"><i class="ti ti-trash"></i></button>';
                html += '</td></tr>';
            });
        }
        html += '</tbody></table></div>';
        html += renderPaginationBar(pg, totalPages, total, "schema");
        // 变更日志
        html += '<div class="dd-detail-list" style="margin-top:12px"><div class="dd-detail-list-header">';
        html += '<span class="dd-detail-list-title">变更日志</span></div>';
        html += '<div id="dd-instance-logs" class="dd-log-empty">加载中...</div></div>';
        ddTabContent.innerHTML = html;

        // 构建 nameMap
        var nameMap = {};
        nameMap["instance-" + instanceId] = inst.instance_name;
        schemas.forEach(function (s) {
            nameMap["schema-" + s.id] = s.schema_name;
            (s.tables || []).forEach(function (t) {
                nameMap["table-" + t.id] = t.table_name;
            });
        });
        // 合并已删除对象
        Object.keys(deletedObjectMap).forEach(function (type) {
            Object.keys(deletedObjectMap[type]).forEach(function (id) {
                nameMap[type + "-" + id] = deletedObjectMap[type][id];
            });
        });
        initLogPager("dd-instance-logs", "/api/data-dict/instances/" + instanceId + "/logs", nameMap, 20);
    }

    function renderAllInstances(page) {
        listPages.allInstances = page || 1;
        ddTabBar.classList.add("hidden");
        ddDetailHeader.innerHTML = '<i class="ti ti-server-2"></i> 所有数据库实例'
            + '<label class="dd-edit-toggle"><input type="checkbox" id="dd-edit-switch"' + (ddEditMode ? ' checked' : '') + '> 编辑</label>';
        // 分页
        var pageSize = 20;
        var total = instances.length;
        var totalPages = Math.ceil(total / pageSize) || 1;
        var pg = listPages.allInstances;
        if (pg > totalPages) pg = totalPages;
        listPages.allInstances = pg;
        var start = (pg - 1) * pageSize;
        var pageItems = instances.slice(start, start + pageSize);
        var html = '<div class="dd-detail-list"><div class="dd-detail-list-header">';
        html += '<span class="dd-detail-list-title">实例列表</span>';
        html += '<button class="dd-btn dd-btn-sm dd-edit-only" id="dd-add-from-header"><i class="ti ti-plus"></i> 添加实例</button>';
        html += '</div><table class="dd-table"><thead><tr><th>序号</th><th>名称</th><th>类型</th><th>数据源ID</th><th>备注</th><th>Schema 数</th><th>创建时间</th><th>更新时间</th><th>操作</th></tr></thead><tbody>';
        if (instances.length === 0) {
            html += '<tr><td colspan="9" style="text-align:center;color:var(--text-dim);padding:12px">暂无实例</td></tr>';
        } else {
            pageItems.forEach(function (inst, i) {
                html += '<tr><td style="color:var(--text-dim)">' + (start + i + 1) + '</td>';
                html += '<td>' + escapeHtml(inst.instance_name) + '</td>';
                html += '<td>' + escapeHtml(inst.db_type) + '</td>';
                html += '<td style="color:var(--text-dim)">' + escapeHtml(inst.datasource_id || "") + '</td>';
                html += '<td style="color:var(--text-dim)">' + escapeHtml(inst.remark || "") + '</td>';
                html += '<td>' + ((inst.schemas || []).length) + '</td>';
                html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(inst.create_time || "") + '</td>';
                html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(inst.update_time || "") + '</td>';
                html += '<td>';
                html += '<button class="dd-action-btn dd-edit-only" data-action="editInstanceOverview" data-instance-id="' + inst.id + '" title="编辑"><i class="ti ti-edit"></i></button> ';
                html += '<button class="dd-action-btn dd-edit-only" data-action="deleteInstanceOverview" data-instance-id="' + inst.id + '" title="删除"><i class="ti ti-trash"></i></button>';
                html += '</td></tr>';
            });
        }
        html += '</tbody></table></div>';
        html += renderPaginationBar(pg, totalPages, total, "inst");
        // 变更日志
        html += '<div class="dd-detail-list" style="margin-top:12px"><div class="dd-detail-list-header">';
        html += '<span class="dd-detail-list-title">变更日志</span></div>';
        html += '<div id="dd-global-logs" class="dd-log-empty">加载中...</div></div>';
        ddTabContent.innerHTML = html;

        // 构建全局 nameMap
        var nameMap = {};
        instances.forEach(function (inst) {
            nameMap["instance-" + inst.id] = inst.instance_name;
            (inst.schemas || []).forEach(function (s) {
                nameMap["schema-" + s.id] = s.schema_name;
                (s.tables || []).forEach(function (t) {
                    nameMap["table-" + t.id] = t.table_name;
                });
            });
        });
        // 合并已删除对象
        Object.keys(deletedObjectMap).forEach(function (type) {
            Object.keys(deletedObjectMap[type]).forEach(function (id) {
                nameMap[type + "-" + id] = deletedObjectMap[type][id];
            });
        });
        initLogPager("dd-global-logs", "/api/data-dict/logs", nameMap, 20);

        var addBtn = document.getElementById("dd-add-from-header");
        if (addBtn) addBtn.addEventListener("click", function () { showInstanceForm(null); });
    }

    function loadAndRenderSchemaDetail(schemaId, page) {
        listPages.schemaTables = page || 1;
        // Find the schema in tree data and load its tables
        var foundSchema = null;
        for (var i = 0; i < instances.length; i++) {
            var ss = instances[i].schemas || [];
            for (var j = 0; j < ss.length; j++) {
                if (ss[j].id === schemaId) {
                    foundSchema = ss[j];
                    break;
                }
            }
            if (foundSchema) break;
        }
        if (!foundSchema) {
            ddTabContent.innerHTML = '<div class="dd-log-empty">Schema 未找到</div>';
            return;
        }
        // Fetch tables
        ddFetch("/api/data-dict/schemas/" + schemaId + "/tables")
            .then(function (r) { return r.json(); })
            .then(function (tables) {
                foundSchema.tables = tables;
                renderSchemaDetail(foundSchema, listPages.schemaTables);
                // Also update tree
                renderTree(instances);
            })
            .catch(function () {
                ddTabContent.innerHTML = '<div class="dd-log-empty">加载失败</div>';
            });
    }

    function renderSchemaDetail(schema, page) {
        listPages.schemaTables = page || 1;
        ddTabBar.classList.add("hidden");
        ddDetailHeader.innerHTML = '<i class="ti ti-database"></i> ' + escapeHtml(schema.schema_name)
            + (schema.remark ? ' <span style="color:var(--text-dim);font-weight:400;font-size:12px">— ' + escapeHtml(schema.remark) + "</span>" : "")
            + '<label class="dd-edit-toggle"><input type="checkbox" id="dd-edit-switch"' + (ddEditMode ? ' checked' : '') + '> 编辑</label>';
        var schemaId = schema.id;
        var instanceId = schema.instance_id;
        var tables = schema.tables || [];
        // 分页
        var pageSize = 20;
        var total = tables.length;
        var totalPages = Math.ceil(total / pageSize) || 1;
        var pg = listPages.schemaTables;
        if (pg > totalPages) pg = totalPages;
        listPages.schemaTables = pg;
        var start = (pg - 1) * pageSize;
        var pageItems = tables.slice(start, start + pageSize);
        var html = '<div class="dd-detail-list" data-schema-id="' + schemaId + '" data-instance-id="' + (instanceId || "") + '"><div class="dd-detail-list-header">';
        html += '<span class="dd-detail-list-title">数据表列表</span>';
        html += '<button class="dd-btn dd-btn-sm dd-edit-only" data-action="addTableFromSchema"><i class="ti ti-plus"></i> 添加表</button>';
        html += '</div><table class="dd-table"><thead><tr><th>序号</th><th>表名</th><th>类型</th><th>注释</th><th>标签</th><th>创建时间</th><th>更新时间</th><th>操作</th></tr></thead><tbody>';
        if (tables.length === 0) {
            html += '<tr><td colspan="8" style="text-align:center;color:var(--text-dim);padding:12px">暂无数据表</td></tr>';
        } else {
            pageItems.forEach(function (t, i) {
                html += '<tr><td style="color:var(--text-dim)">' + (start + i + 1) + '</td>';
                html += '<td>' + escapeHtml(t.table_name) + '</td>';
                html += '<td>' + escapeHtml(t.table_type) + '</td>';
                html += '<td style="color:var(--text-dim)">' + escapeHtml(t.comment || "") + '</td>';
				html += '<td>' + renderTags(t.tags) + '</td>';
                html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(t.create_time || "") + '</td>';
                html += '<td style="color:var(--text-dim);font-size:12px">' + escapeHtml(t.update_time || "") + '</td>';
                html += '<td>';
                html += '<button class="dd-action-btn dd-edit-only" data-action="editTableFromSchema" data-table-id="' + t.id + '" title="编辑"><i class="ti ti-edit"></i></button> ';
                html += '<button class="dd-action-btn dd-edit-only" data-action="deleteTableFromSchema" data-table-id="' + t.id + '" title="删除"><i class="ti ti-trash"></i></button>';
                html += '</td></tr>';
            });
        }
        html += '</tbody></table></div>';
        html += renderPaginationBar(pg, totalPages, total, "table");
        // 变更日志
        html += '<div class="dd-detail-list" style="margin-top:12px"><div class="dd-detail-list-header">';
        html += '<span class="dd-detail-list-title">变更日志</span></div>';
        html += '<div id="dd-schema-logs" class="dd-log-empty">加载中...</div></div>';
        ddTabContent.innerHTML = html;

        // 构建 nameMap
        var nameMap = {};
        nameMap["schema-" + schemaId] = schema.schema_name;
        tables.forEach(function (t) {
            nameMap["table-" + t.id] = t.table_name;
        });
        // 合并已删除对象
        Object.keys(deletedObjectMap).forEach(function (type) {
            Object.keys(deletedObjectMap[type]).forEach(function (id) {
                nameMap[type + "-" + id] = deletedObjectMap[type][id];
            });
        });
        initLogPager("dd-schema-logs", "/api/data-dict/schemas/" + schemaId + "/logs", nameMap, 20);
    }

    // ── 加载表详情（含 Tab 栏）──
    function loadTableDetail(tableId) {
        // Reset tab pagination when loading a new table
        listPages.columns = 1;
        listPages.indexes = 1;
        listPages.constraints = 1;
        ddFetch("/api/data-dict/tables/" + tableId)
            .then(function (r) { return r.json(); })
            .then(function (tbl) {
                currentTable = tbl;
                ddTabBar.classList.remove("hidden");
                ddPlaceholder.classList.add("hidden");
                ddDetailContent.classList.remove("hidden");
                renderTableHeader(tbl);
                switchTab(currentTab);
                if (currentSearchQuery) {
                    applyDetailHighlights(currentSearchQuery);
                }
            })
            .catch(function (e) {
                showToast("加载表详情失败", true);
            });
    }

    function showTableForm(table, schemaId) {
        var title = table ? "编辑表" : "添加表";
        var name = table ? table.table_name : "";
        var tableType = table ? table.table_type : "BASE TABLE";
        var comment = table ? (table.comment || "") : "";
        var tags = table ? (table.tags || "") : "";
        var html = '<div class="dd-overlay" id="dd-overlay">';
        html += '<div class="dd-overlay-content">';
        html += "<h3>" + title + "</h3>";
        if (table) {
            html += '<div class="dd-form-readonly"><span>ID: ' + table.id + '</span><span>创建: ' + escapeHtml(table.create_time || "") + '</span><span>更新: ' + escapeHtml(table.update_time || "") + '</span></div>';
        }
        html += '<div class="dd-form-group"><label>表名 *</label><input id="dd-f-name" value="' + escapeHtml(name) + '"></div>';
        html += '<div class="dd-form-group"><label>类型</label><select id="dd-f-type">';
        ["BASE TABLE", "VIEW"].forEach(function (t) {
            html += '<option value="' + t + '"' + (t === tableType ? " selected" : "") + ">" + t + "</option>";
        });
        html += "</select></div>";
        html += '<div class="dd-form-group"><label>标签</label><input id="dd-f-tags" value="' + escapeHtml(tags) + '" placeholder="逗号分隔，如 核心,用户"></div>';
        html += '<div class="dd-form-group"><label>注释</label><textarea id="dd-f-comment">' + escapeHtml(comment) + "</textarea></div>";
        html += '<div class="dd-overlay-actions">';
        html += '<button class="dd-btn-cancel" id="dd-overlay-cancel">取消</button>';
        html += '<button class="dd-btn-primary" id="dd-overlay-ok">确认</button>';
        html += "</div></div></div>";

        var div = ddE("div");
        div.innerHTML = html;
        document.body.appendChild(div.firstElementChild);

        var overlay = document.getElementById("dd-overlay");
        document.getElementById("dd-overlay-cancel").addEventListener("click", function () { overlay.remove(); });
        document.getElementById("dd-overlay-ok").addEventListener("click", function () {
            var data = {
                schema_id: schemaId,
                table_name: document.getElementById("dd-f-name").value.trim(),
                table_type: document.getElementById("dd-f-type").value,
                tags: document.getElementById("dd-f-tags").value.trim() || null,
                comment: document.getElementById("dd-f-comment").value.trim() || null,
            };
            if (!data.table_name) { showToast("请输入表名", true); return; }
            function refreshSchemaPanel() {
                if (selectedPath && selectedPath.type === "schema" && selectedPath.id === schemaId) {
                    loadAndRenderSchemaDetail(schemaId);
                }
            }
            if (table) {
                ddFetch("/api/data-dict/tables/" + table.id, { method: "PUT", body: data })
                    .then(function (r) { return r.json(); })
                    .then(function () {
                        showToast("更新成功");
                        var parent = findSchemaParent(schemaId);
                        if (parent) loadInstanceDetail(parent.instance_id);
                        refreshSchemaPanel();
                        overlay.remove();
                    })
                    .catch(function () { showToast("更新失败", true); });
            } else {
                ddFetch("/api/data-dict/tables", { method: "POST", body: data })
                    .then(function (r) { return r.json(); })
                    .then(function () {
                        showToast("创建成功");
                        var parent = findSchemaParent(schemaId);
                        if (parent) loadInstanceDetail(parent.instance_id);
                        refreshSchemaPanel();
                        overlay.remove();
                    })
                    .catch(function () { showToast("创建失败", true); });
            }
        });
    }

    function deleteTable(id) {
        // 查找所属 schema（在 currentTable 被清空前）
        var parentSchemaId = null;
        if (currentTable && currentTable.id === id) {
            if (!deletedObjectMap["table"]) deletedObjectMap["table"] = {};
            deletedObjectMap["table"][id] = currentTable.table_name;
            for (var di = 0; di < instances.length; di++) {
                var ds = instances[di].schemas || [];
                for (var dj = 0; dj < ds.length; dj++) {
                    var dt = ds[dj].tables || [];
                    for (var dk = 0; dk < dt.length; dk++) {
                        if (dt[dk].id === id) { parentSchemaId = ds[dj].id; break; }
                    }
                    if (parentSchemaId) break;
                }
                if (parentSchemaId) break;
            }
        }
        if (!confirm("确认删除此表？所有字段、索引、约束将被级联删除。")) return;
        ddFetch("/api/data-dict/tables/" + id, { method: "DELETE" })
            .then(function (r) { return r.json(); })
            .then(function () {
                showToast("删除成功");
                // Refresh tree
                var parent = findSchemaParentByTableId(id);
                if (parent) loadInstanceDetail(parent.instance_id);
                // 刷新右侧面板（如果正在查看所属 schema）
                if (parentSchemaId && selectedPath && selectedPath.type === "schema" && selectedPath.id === parentSchemaId) {
                    loadAndRenderSchemaDetail(parentSchemaId);
                } else {
                    selectedPath = null;
                    ddPlaceholder.classList.remove("hidden");
                    ddDetailContent.classList.add("hidden");
                }
            })
            .catch(function () { showToast("删除失败", true); });
    }

    function findSchemaParent(schemaId) {
        for (var i = 0; i < instances.length; i++) {
            var schemas = instances[i].schemas || [];
            for (var j = 0; j < schemas.length; j++) {
                if (schemas[j].id === schemaId) return { instance_id: instances[i].id, instance: instances[i] };
            }
        }
        return null;
    }

    function findSchemaParentByTableId(tableId) {
        if (!currentTable) return null;
        for (var i = 0; i < instances.length; i++) {
            var schemas = instances[i].schemas || [];
            for (var j = 0; j < schemas.length; j++) {
                var tables = schemas[j].tables || [];
                for (var k = 0; k < tables.length; k++) {
                    if (tables[k].id === tableId) return { instance_id: instances[i].id, instance: instances[i] };
                }
            }
        }
        return null;
    }

    function findSchemaById(schemaId) {
        for (var i = 0; i < instances.length; i++) {
            var ss = instances[i].schemas || [];
            for (var j = 0; j < ss.length; j++) {
                if (ss[j].id === schemaId) return ss[j];
            }
        }
        return null;
    }

    function findTableById(tableId) {
        if (currentTable && currentTable.id === tableId) return currentTable;
        for (var i = 0; i < instances.length; i++) {
            var ss = instances[i].schemas || [];
            for (var j = 0; j < ss.length; j++) {
                var tt = ss[j].tables || [];
                for (var k = 0; k < tt.length; k++) {
                    if (tt[k].id === tableId) return tt[k];
                }
            }
        }
        return null;
    }

    // Column
    function updateColumn(colId, data) {
        ddFetch("/api/data-dict/columns/" + colId, { method: "PUT", body: data })
            .then(function (r) { return r.json(); })
            .then(function (col) {
                // Reload current table
                if (currentTable) loadTableDetail(currentTable.id);
            })
            .catch(function () { showToast("更新字段失败", true); });
    }

    function deleteColumn(colId) {
        var col = (currentTable.columns || []).find(function (c) { return c.id === colId; });
        if (col) {
            if (!deletedObjectMap["column"]) deletedObjectMap["column"] = {};
            deletedObjectMap["column"][colId] = col.column_name;
        }
        ddFetch("/api/data-dict/columns/" + colId, { method: "DELETE" })
            .then(function (r) { return r.json(); })
            .then(function () {
                showToast("删除成功");
                if (currentTable) loadTableDetail(currentTable.id);
            })
            .catch(function () { showToast("删除失败", true); });
    }

    function showColumnForm(col) {
        var title = col ? "编辑字段" : "添加字段";
        var cname = col ? col.column_name : "";
        var dtype = col ? col.data_type : "varchar";
        var fullType = col ? (col.full_data_type || "") : "";
        var nullable = col ? col.nullable : false;
        var comment = col ? (col.comment || "") : "";
        var tags = col ? (col.tags || "") : "";
        var enumInfo = col ? (col.enum_info || "") : "";
        var pos = col ? col.position : ((currentTable.columns || []).length + 1);
        var html = '<div class="dd-overlay" id="dd-overlay">';
        html += '<div class="dd-overlay-content">';
        html += "<h3>" + title + "</h3>";
        if (col) {
            html += '<div class="dd-form-readonly"><span>ID: ' + col.id + '</span><span>创建: ' + escapeHtml(col.create_time || "") + '</span><span>更新: ' + escapeHtml(col.update_time || "") + '</span></div>';
        }
        html += '<div class="dd-form-group"><label>字段名 *</label><input id="dd-f-name" value="' + escapeHtml(cname) + '"></div>';
        html += '<div class="dd-form-group"><label>数据类型 *</label><input id="dd-f-dtype" value="' + escapeHtml(dtype) + '"></div>';
        html += '<div class="dd-form-group"><label>完整类型</label><input id="dd-f-ftype" value="' + escapeHtml(fullType) + '" placeholder="如 varchar(255)"></div>';
        html += '<div class="dd-form-group"><label>排序</label><input id="dd-f-pos" type="number" value="' + pos + '"></div>';
        html += '<div class="dd-form-group"><label><input type="checkbox" id="dd-f-nullable"' + (nullable ? " checked" : "") + "> 允许为空</label></div>";
        html += '<div class="dd-form-group"><label>标签</label><input id="dd-f-tags" value="' + escapeHtml(tags) + '" placeholder="逗号分隔，如 核心,用户"></div>';
        html += '<div class="dd-form-group"><label>枚举值</label><textarea id="dd-f-enum" placeholder="key:value,key:value">' + escapeHtml(enumInfo) + "</textarea></div>";
        html += '<div class="dd-form-group"><label>注释</label><textarea id="dd-f-comment">' + escapeHtml(comment) + "</textarea></div>";
        html += '<div class="dd-overlay-actions">';
        html += '<button class="dd-btn-cancel" id="dd-overlay-cancel">取消</button>';
        html += '<button class="dd-btn-primary" id="dd-overlay-ok">确认</button>';
        html += "</div></div></div>";

        var div = ddE("div");
        div.innerHTML = html;
        document.body.appendChild(div.firstElementChild);

        var overlay = document.getElementById("dd-overlay");
        document.getElementById("dd-overlay-cancel").addEventListener("click", function () { overlay.remove(); });
        document.getElementById("dd-overlay-ok").addEventListener("click", function () {
            var data = {
                table_id: currentTable ? currentTable.id : null,
                column_name: document.getElementById("dd-f-name").value.trim(),
                data_type: document.getElementById("dd-f-dtype").value.trim(),
                full_data_type: document.getElementById("dd-f-ftype").value.trim() || null,
                position: parseInt(document.getElementById("dd-f-pos").value) || 0,
                nullable: document.getElementById("dd-f-nullable").checked,
                tags: document.getElementById("dd-f-tags").value.trim() || null,
                enum_info: document.getElementById("dd-f-enum").value.trim() || null,
                comment: document.getElementById("dd-f-comment").value.trim() || null,
            };
            if (!data.column_name || !data.data_type) { showToast("请填写必填字段", true); return; }
            if (col) {
                ddFetch("/api/data-dict/columns/" + col.id, { method: "PUT", body: data })
                    .then(function (r) { return r.json(); })
                    .then(function () {
                        showToast("更新成功");
                        if (currentTable) loadTableDetail(currentTable.id);
                        overlay.remove();
                    })
                    .catch(function () { showToast("更新失败", true); });
            } else {
                ddFetch("/api/data-dict/columns", { method: "POST", body: data })
                    .then(function (r) { return r.json(); })
                    .then(function () {
                        showToast("创建成功");
                        if (currentTable) loadTableDetail(currentTable.id);
                        overlay.remove();
                    })
                    .catch(function () { showToast("创建失败", true); });
            }
        });
    }

    // Index
    function showIndexForm(idx) {
        var title = idx ? "编辑索引" : "添加索引";
        var iname = idx ? idx.index_name : "";
        var itype = idx ? idx.index_type : "btree";
        var iunique = idx ? idx.is_unique : false;
        var cols = currentTable ? (currentTable.columns || []) : [];
        var selectedIds = idx ? (idx.column_ids || []) : [];
        var html = '<div class="dd-overlay" id="dd-overlay">';
        html += '<div class="dd-overlay-content">';
        html += "<h3>" + title + "</h3>";
        if (idx) {
            html += '<div class="dd-form-readonly"><span>ID: ' + idx.id + '</span><span>创建: ' + escapeHtml(idx.create_time || "") + '</span><span>更新: ' + escapeHtml(idx.update_time || "") + '</span></div>';
        }
        html += '<div class="dd-form-group"><label>索引名 *</label><input id="dd-f-name" value="' + escapeHtml(iname) + '"></div>';
        html += '<div class="dd-form-group"><label>类型</label><select id="dd-f-type">';
        ["btree", "gin", "hash", "gist", "brin"].forEach(function (t) {
            html += '<option value="' + t + '"' + (t === itype ? " selected" : "") + ">" + t + "</option>";
        });
        html += "</select></div>";
        html += '<div class="dd-form-group"><label><input type="checkbox" id="dd-f-unique"' + (iunique ? " checked" : "") + "> 唯一索引</label></div>";
        html += '<div class="dd-form-group"><label>包含字段</label>';
        html += '<div class="dd-checkbox-list">';
        cols.forEach(function (c) {
            var checked = selectedIds.indexOf(c.id) !== -1;
            html += '<div class="dd-checkbox-item">';
            html += '<label class="dd-cb-wrap"><input type="checkbox" class="dd-col-cb" value="' + c.id + '"' + (checked ? " checked" : "") + '><span class="dd-cb-visual"></span></label>';
            html += '<span>' + escapeHtml(c.column_name) + " (" + escapeHtml(c.data_type) + ")</span></div>";
        });
        html += "</div></div>";
        html += '<div class="dd-overlay-actions">';
        html += '<button class="dd-btn-cancel" id="dd-overlay-cancel">取消</button>';
        html += '<button class="dd-btn-primary" id="dd-overlay-ok">确认</button>';
        html += "</div></div></div>";

        var div = ddE("div");
        div.innerHTML = html;
        document.body.appendChild(div.firstElementChild);

        var overlay = document.getElementById("dd-overlay");
        document.getElementById("dd-overlay-cancel").addEventListener("click", function () { overlay.remove(); });
        document.getElementById("dd-overlay-ok").addEventListener("click", function () {
            var cbx = overlay.querySelectorAll(".dd-col-cb:checked");
            var colIds = Array.from(cbx).map(function (c) { return parseInt(c.value); });
            var data = {
                table_id: currentTable ? currentTable.id : null,
                index_name: document.getElementById("dd-f-name").value.trim(),
                index_type: document.getElementById("dd-f-type").value,
                is_unique: document.getElementById("dd-f-unique").checked,
                column_ids: colIds,
            };
            if (!data.index_name) { showToast("请输入索引名", true); return; }
            if (idx) {
                ddFetch("/api/data-dict/indexes/" + idx.id, { method: "PUT", body: data })
                    .then(function (r) { return r.json(); })
                    .then(function () {
                        showToast("更新成功");
                        if (currentTable) loadTableDetail(currentTable.id);
                        overlay.remove();
                    })
                    .catch(function () { showToast("更新失败", true); });
            } else {
                ddFetch("/api/data-dict/indexes", { method: "POST", body: data })
                    .then(function (r) { return r.json(); })
                    .then(function () {
                        showToast("创建成功");
                        if (currentTable) loadTableDetail(currentTable.id);
                        overlay.remove();
                    })
                    .catch(function () { showToast("创建失败", true); });
            }
        });
    }

    function deleteIndex(id) {
        var idx = (currentTable.indexes || []).find(function (i) { return i.id === id; });
        if (idx) {
            if (!deletedObjectMap["index"]) deletedObjectMap["index"] = {};
            deletedObjectMap["index"][id] = idx.index_name;
        }
        ddFetch("/api/data-dict/indexes/" + id, { method: "DELETE" })
            .then(function (r) { return r.json(); })
            .then(function () {
                showToast("删除成功");
                if (currentTable) loadTableDetail(currentTable.id);
            })
            .catch(function () { showToast("删除失败", true); });
    }

    // Constraint
    function showConstraintForm(con) {
        var title = con ? "编辑约束" : "添加约束";
        var cname = con ? con.constraint_name : "";
        var ctype = con ? con.constraint_type : "primary";
        var onDel = con ? (con.on_delete || "") : "";
        var onUp = con ? (con.on_update || "") : "";
        var cols = currentTable ? (currentTable.columns || []) : [];
        var selectedIds = con ? (con.column_ids || []) : [];
        var html = '<div class="dd-overlay" id="dd-overlay">';
        html += '<div class="dd-overlay-content">';
        html += "<h3>" + title + "</h3>";
        if (con) {
            html += '<div class="dd-form-readonly"><span>ID: ' + con.id + '</span><span>创建: ' + escapeHtml(con.create_time || "") + '</span><span>更新: ' + escapeHtml(con.update_time || "") + '</span></div>';
        }
        html += '<div class="dd-overlay-content">';
        html += "<h3>" + title + "</h3>";
        html += '<div class="dd-form-group"><label>约束名 *</label><input id="dd-f-name" value="' + escapeHtml(cname) + '"></div>';
        html += '<div class="dd-form-group"><label>类型</label><select id="dd-f-type">';
        ["primary", "foreign", "unique"].forEach(function (t) {
            html += '<option value="' + t + '"' + (t === ctype ? " selected" : "") + ">" + t + "</option>";
        });
        html += "</select></div>";
        html += '<div class="dd-form-group"><label>包含字段</label>';
        html += '<div class="dd-checkbox-list">';
        cols.forEach(function (c) {
            var checked = selectedIds.indexOf(c.id) !== -1;
            html += '<div class="dd-checkbox-item">';
            html += '<label class="dd-cb-wrap"><input type="checkbox" class="dd-col-cb" value="' + c.id + '"' + (checked ? " checked" : "") + '><span class="dd-cb-visual"></span></label>';
            html += '<span>' + escapeHtml(c.column_name) + " (" + escapeHtml(c.data_type) + ")</span></div>";
        });
        html += "</div></div>";
        html += '<div class="dd-form-group" id="dd-fk-group"' + (ctype !== "foreign" ? ' style="display:none"' : "") + ">";
        html += '<div class="dd-form-group"><label>目标表ID</label><input id="dd-f-target-table" value="' + (con && con.target_table_id || "") + '"></div>';
        html += '<div class="dd-form-group"><label>On Delete</label><input id="dd-f-on-del" value="' + escapeHtml(onDel) + '"></div>';
        html += '<div class="dd-form-group"><label>On Update</label><input id="dd-f-on-up" value="' + escapeHtml(onUp) + '"></div>';
        html += "</div>";
        html += '<div class="dd-overlay-actions">';
        html += '<button class="dd-btn-cancel" id="dd-overlay-cancel">取消</button>';
        html += '<button class="dd-btn-primary" id="dd-overlay-ok">确认</button>';
        html += "</div></div></div>";

        var div = ddE("div");
        div.innerHTML = html;
        document.body.appendChild(div.firstElementChild);

        var overlay = document.getElementById("dd-overlay");
        document.getElementById("dd-f-type").addEventListener("change", function () {
            var g = document.getElementById("dd-fk-group");
            if (g) g.style.display = this.value === "foreign" ? "" : "none";
        });
        document.getElementById("dd-overlay-cancel").addEventListener("click", function () { overlay.remove(); });
        document.getElementById("dd-overlay-ok").addEventListener("click", function () {
            var cbx = overlay.querySelectorAll(".dd-col-cb:checked");
            var colIds = Array.from(cbx).map(function (c) { return parseInt(c.value); });
            var data = {
                table_id: currentTable ? currentTable.id : null,
                constraint_name: document.getElementById("dd-f-name").value.trim(),
                constraint_type: document.getElementById("dd-f-type").value,
                column_ids: colIds,
            };
            if (data.constraint_type === "foreign") {
                data.target_table_id = parseInt(document.getElementById("dd-f-target-table").value) || null;
                data.on_delete = document.getElementById("dd-f-on-del").value.trim() || null;
                data.on_update = document.getElementById("dd-f-on-up").value.trim() || null;
                data.target_column_ids = colIds;
            }
            if (!data.constraint_name) { showToast("请输入约束名", true); return; }
            if (con) {
                ddFetch("/api/data-dict/constraints/" + con.id, { method: "PUT", body: data })
                    .then(function (r) { return r.json(); })
                    .then(function () {
                        showToast("更新成功");
                        if (currentTable) loadTableDetail(currentTable.id);
                        overlay.remove();
                    })
                    .catch(function () { showToast("更新失败", true); });
            } else {
                ddFetch("/api/data-dict/constraints", { method: "POST", body: data })
                    .then(function (r) { return r.json(); })
                    .then(function () {
                        showToast("创建成功");
                        if (currentTable) loadTableDetail(currentTable.id);
                        overlay.remove();
                    })
                    .catch(function () { showToast("创建失败", true); });
            }
        });
    }

    function deleteConstraint(id) {
        var con = (currentTable.constraints || []).find(function (c) { return c.id === id; });
        if (con) {
            if (!deletedObjectMap["constraint"]) deletedObjectMap["constraint"] = {};
            deletedObjectMap["constraint"][id] = con.constraint_name;
        }
        ddFetch("/api/data-dict/constraints/" + id, { method: "DELETE" })
            .then(function (r) { return r.json(); })
            .then(function () {
                showToast("删除成功");
                if (currentTable) loadTableDetail(currentTable.id);
            })
            .catch(function () { showToast("删除失败", true); });
    }

    // ── 树操作的事件委托 ──
    function handleTreeAction(e) {
        var more = e.target.closest(".dd-tree-more");
        if (more) {
            var key = more.dataset.treeMore;
            if (key) {
                treeLoadMore[key] = (treeLoadMore[key] || 20) + 20;
                renderTree(instances);
            }
            return;
        }
        var btn = e.target.closest("[data-action]");
        if (!btn) return;
        var action = btn.dataset.action;
        var item = btn.closest(".dd-tree-item");
        if (!item) return;
        var type = item.dataset.type;
        var id = parseInt(item.dataset.id);

        if (action === "addSchema") showSchemaForm(null, id);
        else if (action === "editInstance") {
            var inst = instances.find(function (i) { return i.id === id; });
            if (inst) showInstanceForm(inst);
        } else if (action === "deleteInstance") deleteInstance(id);
        else if (action === "addTable") showTableForm(null, id);
        else if (action === "editSchema") {
            for (var i = 0; i < instances.length; i++) {
                var ss = instances[i].schemas || [];
                for (var j = 0; j < ss.length; j++) {
                    if (ss[j].id === id) {
                        showSchemaForm(ss[j], instances[i].id);
                        return;
                    }
                }
            }
        } else if (action === "deleteSchema") {
            for (var i = 0; i < instances.length; i++) {
                var ss = instances[i].schemas || [];
                for (var j = 0; j < ss.length; j++) {
                    if (ss[j].id === id) {
                        deleteSchema(id, instances[i].id);
                        return;
                    }
                }
            }
        } else if (action === "editTable") {
            // Find the table
            for (var i = 0; i < instances.length; i++) {
                var ss = instances[i].schemas || [];
                for (var j = 0; j < ss.length; j++) {
                    var tt = ss[j].tables || [];
                    for (var k = 0; k < tt.length; k++) {
                        if (tt[k].id === id) {
                            // Need schema_id for update
                            showTableForm(tt[k], ss[j].id);
                            return;
                        }
                    }
                }
            }
        } else if (action === "deleteTable") {
            if (confirm("确认删除此表？")) {
                deleteTable(id);
            }
        }
    }

    // ── 点击树外区域关闭 overlay ──
    document.addEventListener("click", function (e) {
        if (e.target.classList.contains("dd-overlay")) {
            e.target.remove();
        }
    });

    // ── 初始化 ──
    function init() {
        ddContainer = document.getElementById("data-dict-container");
        if (!ddContainer) return;
        ddTree = document.getElementById("dd-tree");
        ddPlaceholder = document.getElementById("dd-placeholder");
        ddDetailContent = document.getElementById("dd-detail-content");
        ddDetailHeader = document.getElementById("dd-detail-header");
        ddTabContent = document.getElementById("dd-tab-content");
        ddAddInstance = document.getElementById("dd-add-instance");
        ddTabBar = document.getElementById("dd-tab-bar");

        if (!ddTree || !ddPlaceholder) return;

        // 编辑开关
        ddContainer.addEventListener("change", function (e) {
            if (e.target.id === "dd-edit-switch") {
                ddEditMode = e.target.checked;
                ddContainer.classList.toggle("dd-editing", ddEditMode);
            }
        });

        // 点击顶栏"数据库实例"显示所有实例列表
        var ddHeaderTitle = ddContainer.querySelector(".dd-header-title");
        if (ddHeaderTitle) {
            ddHeaderTitle.addEventListener("click", function () {
                selectedPath = null;
                ddTree.querySelectorAll(".dd-tree-row.sel").forEach(function (el) { el.classList.remove("sel"); });
                ddPlaceholder.classList.add("hidden");
                ddDetailContent.classList.remove("hidden");
                renderAllInstances();
            });
        }

        // 添加实例
        if (ddAddInstance) {
            ddAddInstance.addEventListener("click", function () { showInstanceForm(null); });
        }

        // Tab 切换
        if (ddTabBar) {
            ddTabBar.addEventListener("click", function (e) {
                var tab = e.target.closest(".dd-tab");
                if (!tab) return;
                switchTab(tab.dataset.tab);
            });
        }

        // 树操作代理
        ddTree.addEventListener("click", handleTreeAction);

        // ── 搜索 ──
        var searchInput = document.getElementById("dd-search-input");
        var searchClear = document.getElementById("dd-search-clear");

        if (searchInput) {
            searchInput.addEventListener("input", function () {
                var val = this.value.trim();
                var clearBtn = document.getElementById("dd-search-clear");
                if (clearBtn) clearBtn.classList.toggle("hidden", val.length === 0);
                clearTimeout(searchTimer);
                if (val.length === 0) { restoreTree(); return; }
                searchTimer = setTimeout(function () {
                    doSearch(val, 1);
                }, 300);
            });

            searchInput.addEventListener("keydown", function (e) {
                if (e.key === "Escape") {
                    this.value = "";
                    restoreTree();
                    this.blur();
                }
            });
        }

        if (searchClear) {
            searchClear.addEventListener("click", function () {
                var inp = document.getElementById("dd-search-input");
                if (inp) {
                    inp.value = "";
                    inp.focus();
                }
                restoreTree();
            });
        }

        // 右侧详情面板操作代理
        ddTabContent.addEventListener("click", function (e) {
            var pageBtn = e.target.closest("[data-dd-page]");
            if (pageBtn) {
                var val = pageBtn.dataset.ddPage;
                var parts = val.split("-");
                var prefix = parts.slice(0, -1).join("-");
                var page = parseInt(parts[parts.length - 1]);
                if (page < 1) return;
                if (prefix === "inst") renderAllInstances(page);
                else if (prefix === "schema") {
                    var list = pageBtn.closest(".dd-detail-list");
                    var instanceId = parseInt(list ? list.dataset.instanceId : "0");
                    if (instanceId) loadAndRenderInstanceDetail(instanceId, page);
                } else if (prefix === "table") {
                    var list = pageBtn.closest(".dd-detail-list");
                    var schemaId = parseInt(list ? list.dataset.schemaId : "0");
                    if (schemaId) loadAndRenderSchemaDetail(schemaId, page);
                } else if (prefix === "col") switchTab("columns", page);
                else if (prefix === "idx") switchTab("indexes", page);
                else if (prefix === "con") switchTab("constraints", page);
                return;
            }
            var btn = e.target.closest("[data-action]");
            if (!btn) return;
            var action = btn.dataset.action;
            if (action === "editInstanceDetail") {
                var inst = instances.find(function (i) { return selectedPath && i.id === selectedPath.id; });
                if (inst) showInstanceForm(inst);
            } else if (action === "deleteInstanceDetail") {
                if (selectedPath && confirm("确认删除此实例？所有下层数据将被级联删除。")) deleteInstance(selectedPath.id);
            } else if (action === "addSchemaFromInstance") {
                var list = btn.closest(".dd-detail-list");
                var instanceId = parseInt(list ? list.dataset.instanceId : "0");
                if (instanceId) showSchemaForm(null, instanceId);
            } else if (action === "editSchema") {
                var schemaId = parseInt(btn.dataset.schemaId);
                var s = findSchemaById(schemaId);
                if (s) showSchemaForm(s, s.instance_id);
            } else if (action === "deleteSchema") {
                var schemaId = parseInt(btn.dataset.schemaId);
                var instanceId = parseInt(btn.dataset.instanceId);
                if (confirm("确认删除此 Schema？")) deleteSchema(schemaId, instanceId);
            } else if (action === "addTableFromSchema") {
                var list = btn.closest(".dd-detail-list");
                var schemaId = parseInt(list ? list.dataset.schemaId : "0");
                if (schemaId) showTableForm(null, schemaId);
            } else if (action === "editTableFromSchema") {
                var tableId = parseInt(btn.dataset.tableId);
                var t = findTableById(tableId);
                if (t) showTableForm(t, t.schema_id || 0);
            } else if (action === "deleteTableFromSchema") {
                var tableId = parseInt(btn.dataset.tableId);
                if (confirm("确认删除此表？")) deleteTable(tableId);
            } else if (action === "editInstanceOverview") {
                var instId = parseInt(btn.dataset.instanceId);
                var inst = instances.find(function (i) { return i.id === instId; });
                if (inst) showInstanceForm(inst);
            } else if (action === "deleteInstanceOverview") {
                var instId = parseInt(btn.dataset.instanceId);
                if (confirm("确认删除此实例？")) deleteInstance(instId);
            }
        });

        // 点击树空白区域释放选中
        ddTree.addEventListener("click", function (e) {
            if (e.target === ddTree || e.target.classList.contains("dd-tree-empty")) {
                selectedPath = null;
                ddTree.querySelectorAll(".dd-tree-row.sel").forEach(function (el) { el.classList.remove("sel"); });
                ddPlaceholder.classList.remove("hidden");
                ddDetailContent.classList.add("hidden");
            }
        });

        // 首次加载回调：默认显示实例列表
        function showInstancesOnFirstLoad() {
            selectedPath = null;
            ddPlaceholder.classList.add("hidden");
            ddDetailContent.classList.remove("hidden");
            renderAllInstances();
        }

        // 切换数据字典视图时自动加载
        var observer = new MutationObserver(function () {
            if (ddContainer.classList.contains("active") && !ddInitialized) {
                ddInitialized = true;
                loadInstances(showInstancesOnFirstLoad);
            } else if (!ddContainer.classList.contains("active")) {
                // 离开时重置
                ddInitialized = false;
            }
        });
        observer.observe(ddContainer, { attributes: true, attributeFilter: ["class"] });

        // 如果已经 active（比如页面加载后直接显示），立即加载
        if (ddContainer.classList.contains("active")) {
            ddInitialized = true;
            loadInstances(showInstancesOnFirstLoad);
        }

        // 监听第一次打开
        var navItem = document.getElementById("nav-datadict");
        if (navItem && !ddInitialized) {
            navItem.addEventListener("click", function () {
                setTimeout(function () {
                    if (ddContainer.classList.contains("active") && !ddInitialized) {
                        ddInitialized = true;
                        loadInstances(showInstancesOnFirstLoad);
                    }
                }, 100);
            });
        }
    }

    // ── 枚举值弹窗 ──
    function showEnumModal(enumStr) {
        if (!enumStr) return;
        var rows = enumStr.split(",").map(function (pair) {
            var idx = pair.indexOf(":");
            if (idx === -1) return { k: pair.trim(), v: "" };
            return { k: pair.substring(0, idx).trim(), v: pair.substring(idx + 1).trim() };
        });

        var pageSize = 20;
        var total = rows.length;
        var totalPages = Math.ceil(total / pageSize) || 1;
        var curPage = 1;

        var overlay = document.createElement("div");
        overlay.className = "dd-enum-modal";

        function renderTable(page) {
            var start = (page - 1) * pageSize;
            var pageItems = rows.slice(start, start + pageSize);
            var html = '<table class="dd-enum-table"><thead><tr><th>枚举值</th><th>解释</th></tr></thead><tbody>';
            pageItems.forEach(function (r) {
                html += "<tr><td>" + escapeHtml(r.k) + "</td><td>" + escapeHtml(r.v) + "</td></tr>";
            });
            if (pageItems.length === 0) {
                html += '<tr><td colspan="2" style="text-align:center;color:var(--text-dim);padding:12px">无数据</td></tr>';
            }
            html += "</tbody></table>";

            if (totalPages > 1) {
                html += '<div style="display:flex;align-items:center;justify-content:center;gap:8px;padding:8px 0 0;font-size:12px">';
                html += '<button class="dd-page-btn" data-ep="prev" style="padding:2px 8px;border:1px solid var(--border);border-radius:3px;background:var(--bg-card);cursor:pointer">&lsaquo; 上一页</button>';
                html += '<span style="color:var(--text-dim)">' + page + '/' + totalPages + '</span>';
                html += '<button class="dd-page-btn" data-ep="next" style="padding:2px 8px;border:1px solid var(--border);border-radius:3px;background:var(--bg-card);cursor:pointer">下一页 &rsaquo;</button>';
                html += '</div>';
            }

            var body = overlay.querySelector(".dd-enum-modal-body");
            if (body) body.innerHTML = html;

            // page btn events
            overlay.querySelectorAll(".dd-page-btn").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    var next = this.dataset.ep === "prev" ? curPage - 1 : curPage + 1;
                    if (next < 1 || next > totalPages) return;
                    curPage = next;
                    renderTable(curPage);
                });
            });
        }

        overlay.innerHTML =
            '<div class="dd-enum-modal-content">'
            + '<div class="dd-enum-modal-header">'
            + '<span>枚举值定义 <span style="font-weight:400;color:var(--text-dim);font-size:12px">共' + total + '项</span></span>'
            + '<span class="dd-enum-modal-close">&times;</span>'
            + '</div>'
            + '<div class="dd-enum-modal-body"></div>'
            + '</div>';

        document.body.appendChild(overlay);
        renderTable(1);

        var closeBtn = overlay.querySelector(".dd-enum-modal-close");
        closeBtn.addEventListener("click", function () { overlay.remove(); });
        overlay.addEventListener("click", function (e) {
            if (e.target === overlay) overlay.remove();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
