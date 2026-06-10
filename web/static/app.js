/* Octopus Web UI — Frontend Logic (full feature parity with TUI) */

(function () {
    "use strict";

    // ── 状态 ──
    let ws = null;
    let sessionId = null;
    let model = "";
    let cwd = "";
    let busy = false;
    let planMode = false;
    let currentAgent = null;
    let streamBuffer = "";
    let currentAssistantEl = null;
    let renderTimer = null;
    let pendingConfirmId = null;
    let pendingConfirmTool = null;
    let confirmQueue = [];  // 并发 confirm 队列，逐个显示
    let lastTask = null;
    let commands = {};   // slash 命令列表 {"/help": "desc", ...}
    let trusted = true;
    let modelsMap = {};  // {model_name: provider_name}
    let deleteMode = false;
    let selectedSessions = new Set();
    let darkMode = false;
    let showThinking = true;  // 默认展示 thinking

    // Token 统计
    let sessionTokens = { input: 0, output: 0 };

    // ── DOM ──
    const $messages = document.getElementById("messages");
    const $input = document.getElementById("input");
    const $sendBtn = document.getElementById("send-btn");
    const $stopBtn = document.getElementById("stop-btn");
    const $sessionList = document.getElementById("session-list");
    const $confirmDialog = document.getElementById("confirm-dialog");
    const $confirmTool = document.getElementById("confirm-tool");
    const $confirmInput = document.getElementById("confirm-input");
    const $confirmApprove = document.getElementById("confirm-approve");
    const $confirmReject = document.getElementById("confirm-reject");
    const $confirmApproveAll = document.getElementById("confirm-approve-all");
    const $modeIndicator = document.getElementById("mode-indicator");
    const $tokenBar = document.getElementById("token-bar");
    const $modelInfo = document.getElementById("model-info");
    const $newSessionBtn = document.getElementById("new-session-btn");
    const $agentLabel = document.getElementById("agent-label");
    const $trustDialog = document.getElementById("trust-dialog");
    const $trustBtn = document.getElementById("trust-btn");
    const $trustSkipBtn = document.getElementById("trust-skip-btn");
    const $autocomplete = document.getElementById("autocomplete");
    const $modelBtn = document.getElementById("model-btn");
    const $modelSelector = document.getElementById("model-selector");
    const $deleteModeBtn = document.getElementById("delete-mode-btn");
    const $deleteBar = document.getElementById("delete-bar");
    const $deleteSelectAllBtn = document.getElementById("delete-select-all-btn");
    const $deleteCount = document.getElementById("delete-count");
    const $deleteConfirmBtn = document.getElementById("delete-confirm-btn");
    const $deleteCancelBtn = document.getElementById("delete-cancel-btn");
    const $generalConfirm = document.getElementById("general-confirm-dialog");
    const $confirmTitle = document.getElementById("confirm-title");
    const $confirmMessage = document.getElementById("confirm-message");
    const $confirmOkBtn = document.getElementById("confirm-ok-btn");
    const $confirmCancelBtn = document.getElementById("confirm-cancel-btn");

    // ── 初始化 ──
    function init() {
        const params = new URLSearchParams(window.location.search);
        const token = params.get("token") || "";
        if (!token) {
            showSystem("缺少认证 token。请从终端获取完整 URL。");
            return;
        }
        sessionStorage.setItem("octopus_token", token);
        connectWS(token);
        loadSessions();
        loadCommands();
        loadModels();

        $sendBtn.addEventListener("click", sendTask);
        $stopBtn.addEventListener("click", sendInterrupt);
        $input.addEventListener("keydown", onInputKeydown);
        $input.addEventListener("input", onInputChange);
        $confirmApprove.addEventListener("click", () => resolveConfirm(true, false));
        $confirmReject.addEventListener("click", () => resolveConfirm(false, false));
        $confirmApproveAll.addEventListener("click", () => resolveConfirm(true, true));
        $newSessionBtn.addEventListener("click", confirmNewSession);
        if ($trustBtn) $trustBtn.addEventListener("click", trustDirectory);
        if ($trustSkipBtn) $trustSkipBtn.addEventListener("click", skipTrust);

        $modeIndicator.addEventListener("click", toggleMode);
        $modelBtn.addEventListener("click", toggleModelSelector);
        $deleteModeBtn.addEventListener("click", toggleDeleteMode);
        $deleteSelectAllBtn.addEventListener("click", deleteSelectAll);
        $deleteConfirmBtn.addEventListener("click", deleteSelected);
        $deleteCancelBtn.addEventListener("click", exitDeleteMode);

        updateModeDisplay();

        // 主题初始化
        const savedTheme = localStorage.getItem("octopus_theme");
        if (savedTheme === "dark" || savedTheme === "light") {
            darkMode = savedTheme === "dark";
        } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
            darkMode = true;
        }
        applyTheme();
        document.getElementById("theme-toggle").addEventListener("click", toggleTheme);

        // 点击外部关闭模型选择器
        document.addEventListener("click", (e) => {
            if (!$modelBtn.contains(e.target) && !$modelSelector.contains(e.target)) {
                $modelSelector.classList.add("hidden");
            }
        });
    }

    // ── WebSocket ──
    let wsToken = "";
    let wsReconnectTimer = null;
    let wsReconnectDelay = 1000;

    function connectWS(token) {
        wsToken = token;
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        ws = new WebSocket(`${proto}//${location.host}/ws?token=${token}`);

        ws.onopen = () => {
            if (wsReconnectTimer) {
                showSystem("已重新连接");
                // 重连时清空旧状态
                pendingToolCalls = [];
                confirmQueue = [];
                streamBuffer = "";
                currentAssistantEl = null;
                // 通知服务端恢复之前的 session（B6）
                if (sessionId) {
                    sendJSON({ action: "resume", session_id: sessionId });
                }
            }
            wsReconnectTimer = null;
            wsReconnectDelay = 1000;
        };
        ws.onmessage = (evt) => {
            try { handleEvent(JSON.parse(evt.data)); }
            catch (e) { console.warn("Failed to parse WebSocket message:", e); }
        };
        ws.onclose = () => {
            showSystem(`连接已断开，${Math.round(wsReconnectDelay/1000)}秒后重连...`);
            busy = false;
            updateButtons();
            wsReconnectTimer = setTimeout(() => connectWS(wsToken), wsReconnectDelay);
            wsReconnectDelay = Math.min(wsReconnectDelay * 2, 30000);
        };
        ws.onerror = () => {};
    }

    function sendJSON(obj) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(obj));
        } else {
            console.warn("sendJSON: WebSocket not open, message dropped", obj.action);
        }
    }

    // ── 事件处理 ──
    function handleEvent(data) {
        const type = data.type;
        const text = data.text || "";
        const meta = data.meta || {};

        switch (type) {
            case "connected":
                sessionId = meta.session_id;
                model = meta.model || "";
                cwd = meta.cwd || "";
                trusted = meta.trusted !== false;
                updateModelInfo();
                if (!trusted) showTrustDialog();
                // 渲染恢复的历史消息
                if (meta.messages && meta.messages.length > 0) {
                    renderHistoryMessages(meta.messages);
                } else {
                    showWelcome();
                }
                loadSessions();
                break;

            case "stream":
                thinkingEl = null;
                streamBuffer += text;
                scheduleRender();
                break;

            case "thinking":
                const thinkBeforeEl = currentAssistantEl;
                flushStream();
                if (text) appendThinking(text, thinkBeforeEl);
                break;

            case "wakeup":
                flushStream();
                appendWakeup(text);
                break;

            case "tool_call":
                thinkingEl = null;
                flushStream();
                if (meta.tool === "edit_file" && meta.input) {
                    appendEditDiff(meta.input);
                } else if (meta.tool === "multi_edit" && meta.input) {
                    const edits = meta.input.edits || [];
                    edits.forEach(edit => appendEditDiff(edit));
                } else {
                    appendToolCall(meta.tool || "", text, meta.input || {});
                }
                break;

            case "tool_result":
                updateToolResult(text, meta.rejected || false, meta.tool || "");
                break;

            case "background_task":
                {
                    const status = meta.status || "";
                    const cmd = meta.command || "";
                    const exitCode = meta.exit_code;
                    let msg = "";
                    let cls = "";
                    if (status === "completed") {
                        msg = (exitCode === 0 ? "✓" : "✗") + " 后台任务完成: " + cmd + " (exit: " + exitCode + ")";
                        cls = exitCode === 0 ? "bg-task-success" : "bg-task-warn";
                    } else if (status === "timeout") {
                        msg = "⏱ 后台任务超时: " + cmd;
                        cls = "bg-task-error";
                    } else {
                        msg = "✗ 后台任务错误: " + cmd;
                        cls = "bg-task-error";
                    }
                    appendBackgroundTask(msg, cls);
                }
                break;

            case "response":
                flushStream();
                if (meta.usage) {
                    sessionTokens.input += meta.usage.input_tokens || 0;
                    sessionTokens.output += meta.usage.output_tokens || 0;
                    updateTokenBar(meta.usage);
                }
                busy = false;
                updateButtons();
                break;

            case "error":
                flushStream();
                appendError(text);
                break;

            case "progress":
                break;

            case "confirm_request":
                showConfirmDialog(meta.confirm_id, meta.tool_name, meta.tool_summary);
                // 消息区添加提示
                const needConfirmDiv = document.createElement("div");
                needConfirmDiv.className = "system-message confirm-notice";
                needConfirmDiv.textContent = `⏳ ${meta.tool_name} 需要你的确认 — 请操作下方对话框`;
                $messages.appendChild(needConfirmDiv);
                scrollToBottom();
                break;

            case "done":
                flushStream();
                busy = false;
                updateButtons();
                loadSessions();
                break;

            case "slash_result":
                if (text && text !== "__QUIT__") {
                    // 检测 agent 切换
                    const agentMatch = text.match(/已切换 agent:\s*(\S+)/);
                    if (agentMatch) {
                        currentAgent = agentMatch[1];
                        updateModelInfo();
                    }
                    const agentDefault = text.match(/已切换回默认 agent/);
                    if (agentDefault) {
                        currentAgent = null;
                        updateModelInfo();
                    }
                    // 检测模型切换
                    const modelMatch = text.match(/(?:已切换|切换).*模型.*?[→:]\s*(\S+)/);
                    if (modelMatch) {
                        model = modelMatch[1];
                        updateModelInfo();
                    }
                    showSystem(text);
                }
                break;

            case "model_changed":
                model = meta.model || text;
                updateModelInfo();
                renderModelSelector();
                showSystem("模型已切换: " + model);
                break;

            case "messages_cleared":
                $messages.innerHTML = "";
                showSystem(text);
                break;

            case "session_resumed":
                sessionId = meta.session_id;
                $messages.innerHTML = "";
                if (meta.messages && meta.messages.length > 0) {
                    renderHistoryMessages(meta.messages);
                }
                showSystem(`已恢复会话，${meta.message_count} 条历史消息`);
                loadSessions();
                break;

            case "session_created":
                sessionId = meta.session_id;
                $messages.innerHTML = "";
                showWelcome();
                loadSessions();
                break;

            case "mode_changed":
                planMode = text === "plan";
                updateModeDisplay();
                break;

            case "info":
                showSystem(text);
                break;

            case "show_session_picker":
                highlightSidebar();
                break;

            case "export_data":
                downloadFile(text, meta.filename || "export.txt");
                break;

            case "ask_user_question":
                showAskDialog(meta.ask_id, meta.header, text, meta.options || [], meta.multi_select || false);
                break;

            case "plan_submitted":
                flushStream();
                showPlanReview(text);
                break;

            case "plan_mode_entered":
                showSystem(text || "已进入 Plan 模式（只读规划）");
                updateModeDisplay();
                break;
        }
    }

    // ── Plan 审批 ──
    function showPlanReview(planText) {
        const container = document.createElement("div");
        container.className = "message message-plan";
        container.innerHTML = `
            <div class="role-label" style="color:var(--accent-cyan)">📋 实施计划</div>
            <div class="message-content" style="margin:8px 0">${renderMarkdown(planText)}</div>
            <div class="plan-actions" style="display:flex;gap:8px;margin-top:12px">
                <button class="btn-approve" onclick="approvePlan(true)">✅ 批准并执行</button>
                <button class="btn-reject" onclick="approvePlan(false)" style="background:var(--bg-tool);border:1px solid var(--border);border-radius:6px;padding:8px 16px;cursor:pointer">❌ 拒绝</button>
            </div>`;
        $messages.appendChild(container);
        scrollToBottom();
        highlightCode(container);
    }

    function approvePlan(approved) {
        sendJSON({ action: approved ? "plan_approve" : "plan_reject" });
        if (approved) planMode = false;
        updateModeDisplay();
        document.querySelectorAll(".plan-actions").forEach(el => el.innerHTML = approved
            ? '<span style="color:var(--accent-green)">✓ 计划已批准，已切换到 Auto 模式</span>'
            : '<span style="color:var(--accent-yellow)">计划未批准，仍处于 Plan 模式</span>');
    }

    // ── 流式渲染 ──
    function scheduleRender() {
        if (renderTimer) return;
        renderTimer = setTimeout(() => { renderTimer = null; renderStreamBuffer(); }, 80);
    }

    function renderStreamBuffer() {
        if (!streamBuffer) return;
        if (!currentAssistantEl) currentAssistantEl = appendAssistantMessage();
        const contentEl = currentAssistantEl.querySelector(".message-content");
        contentEl.innerHTML = renderMarkdown(streamBuffer);
        highlightCode(contentEl);
        let indicator = contentEl.querySelector(".streaming-indicator");
        if (!indicator) {
            indicator = document.createElement("span");
            indicator.className = "streaming-indicator";
            indicator.textContent = " ▌";
            contentEl.appendChild(indicator);
        }
        scrollToBottom();
    }

    function flushStream() {
        if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
        if (streamBuffer) {
            if (!currentAssistantEl) currentAssistantEl = appendAssistantMessage();
            const contentEl = currentAssistantEl.querySelector(".message-content");
            contentEl.innerHTML = renderMarkdown(streamBuffer);
            highlightCode(contentEl);
            const indicator = contentEl.querySelector(".streaming-indicator");
            if (indicator) indicator.remove();
            streamBuffer = "";
            currentAssistantEl = null;
            scrollToBottom();
        }
    }

    // ── Markdown 渲染 ──
    function renderMarkdown(text) {
        // 任务列表渲染（✔/◻ checkbox）
        text = text.replace(/^(\s*)- \[([ xX])\] (.*)$/gm, function (_, indent, checked, content) {
            const icon = checked.toLowerCase() === 'x' ? '✔' : '◻';
            const style = checked.toLowerCase() === 'x' ? 'color:var(--accent-green)' : 'color:var(--text-dim)';
            return `${indent}<span style="${style}">${icon}</span> ${content}`;
        });
        const html = marked.parse(text);
        return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
    }

    function highlightCode(el) {
        el.querySelectorAll("pre code").forEach((block) => {
            hljs.highlightElement(block);
        });
    }

    // ── DOM 操作 ──
    function appendUserMessage(text) {
        const div = document.createElement("div");
        div.className = "message message-user";
        div.innerHTML = `<div class="role-label">You</div><div class="message-content">${escapeHtml(text)}</div>`;
        $messages.appendChild(div);
        scrollToBottom();
    }

    function appendAssistantMessage() {
        const div = document.createElement("div");
        div.className = "message message-assistant";
        const agentText = currentAgent ? ` · ${currentAgent}` : "";
        div.innerHTML = `<div class="role-label">Octopus${agentText}</div><div class="message-content"></div>`;
        $messages.appendChild(div);
        scrollToBottom();
        return div;
    }

    let thinkingEl = null;

    function appendThinkingBlock(text) {
        const div = document.createElement("div");
        div.className = "thinking-block";
        div.addEventListener("click", () => div.classList.toggle("expanded"));
        div.textContent = "💭 " + text;
        $messages.appendChild(div);
        scrollToBottom();
    }

    function appendThinking(text, beforeEl) {
        if (!showThinking) return;
        if (thinkingEl) {
            thinkingEl.textContent = "💭 " + text;
        } else {
            const div = document.createElement("div");
            div.className = "thinking-block";
            div.addEventListener("click", () => div.classList.toggle("expanded"));
            div.textContent = "💭 " + text;
            if (beforeEl) {
                $messages.insertBefore(div, beforeEl);
            } else {
                $messages.appendChild(div);
            }
            thinkingEl = div;
            scrollToBottom();
        }
    }

    function appendWakeup(text) {
        const div = document.createElement("div");
        div.className = "thinking-block expanded";
        div.textContent = "⏰ " + text;
        $messages.appendChild(div);
        scrollToBottom();
    }

    // 等待结果的工具调用队列（FIFO 匹配，服务端工具可能有多个同名调用）
    let pendingToolCalls = [];

    function appendToolCall(tool, summary, input) {
        const div = document.createElement("div");
        div.className = "tool-call tool-pending";
        const summaryHtml = summary ? ` <span class="tool-sep">·</span> <span class="tool-summary">${escapeHtml(summary)}</span>` : "";
        div.innerHTML = `<span class="tool-spinner"></span><span class="tool-name">${escapeHtml(tool)}</span>${summaryHtml}<span class="tool-status"></span>`;
        div._input = input || {};
        div._tool = tool;
        div._result = null;
        div._rejected = false;
        div.addEventListener("click", () => div.classList.toggle("tool-expanded"));
        $messages.appendChild(div);
        scrollToBottom();
        pendingToolCalls.push(div);
        return div;
    }

    function langFromPath(path) {
        const ext = (path || "").split(".").pop().toLowerCase();
        const map = {
            py: "python", js: "javascript", ts: "typescript", jsx: "javascript", tsx: "typescript",
            json: "json", html: "html", css: "css", scss: "scss", md: "markdown",
            yaml: "yaml", yml: "yaml", xml: "xml", toml: "ini", sh: "bash", bash: "bash",
            c: "c", h: "c", cpp: "cpp", cc: "cpp", java: "java", go: "go", rs: "rust",
            rb: "ruby", php: "php", sql: "sql",
        };
        return map[ext] || "";
    }

    function highlightLine(line, lang) {
        if (!line) return escapeHtml(line);
        if (lang && hljs.getLanguage(lang)) {
            const result = hljs.highlight(line, {language: lang, ignoreIllegals: true});
            return result.value;
        }
        return escapeHtml(line);
    }

    function appendEditDiff(input) {
        const container = document.createElement("div");
        container.className = "tool-call edit-diff";
        const path = input.path || "";
        const oldText = input.old_string || "";
        const newText = input.new_string || "";
        const lang = langFromPath(path);

        container.innerHTML = `<span class="tool-name">edit_file</span><span class="tool-summary">${escapeHtml(path)}</span>`;

        const diffEl = document.createElement("div");
        diffEl.className = "diff-view";

        const oldLines = oldText.split("\n");
        const newLines = newText.split("\n");
        const ops = computeDiffOps(oldLines, newLines);
        const lw = Math.max(2, String(Math.max(oldLines.length, newLines.length)).length);

        ops.forEach(op => {
            const row = document.createElement("div");
            if (op.type === "equal") {
                return;  // 无上下文，与旧风格一致
            } else if (op.type === "remove") {
                row.className = "diff-line diff-removed";
                const ln = String(op.lineNum).padStart(lw);
                row.innerHTML = `<span class="diff-ln">${ln}</span><span class="diff-prefix">-</span><span class="diff-text">${highlightLine(op.line, lang)}</span>`;
            } else {
                row.className = "diff-line diff-added";
                const ln = String(op.lineNum).padStart(lw);
                row.innerHTML = `<span class="diff-ln">${ln}</span><span class="diff-prefix">+</span><span class="diff-text">${highlightLine(op.line, lang)}</span>`;
            }
            diffEl.appendChild(row);
        });

        container.appendChild(diffEl);
        $messages.appendChild(container);
        scrollToBottom();
    }

    function computeDiffOps(oldLines, newLines) {
        const m = oldLines.length, n = newLines.length;
        if (m * n > 10000) {
            const ops = [];
            oldLines.forEach((l, i) => ops.push({type: "remove", line: l, lineNum: i + 1}));
            newLines.forEach((l, i) => ops.push({type: "add", line: l, lineNum: i + 1}));
            return ops;
        }
        const dp = Array.from({length: m + 1}, () => new Uint16Array(n + 1));
        for (let i = 1; i <= m; i++) {
            for (let j = 1; j <= n; j++) {
                if (oldLines[i - 1] === newLines[j - 1]) {
                    dp[i][j] = dp[i - 1][j - 1] + 1;
                } else {
                    dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
                }
            }
        }
        const ops = [];
        let i = m, j = n;
        while (i > 0 || j > 0) {
            if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
                ops.unshift({type: "equal", line: oldLines[i - 1], lineNum: i});
                i--; j--;
            } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
                ops.unshift({type: "add", line: newLines[j - 1], lineNum: j});
                j--;
            } else {
                ops.unshift({type: "remove", line: oldLines[i - 1], lineNum: i});
                i--;
            }
        }
        return ops;
    }

    function updateToolResult(text, rejected, tool) {
        // FIFO 匹配：找第一个名字匹配的待处理工具调用
        let idx = -1;
        for (let i = 0; i < pendingToolCalls.length; i++) {
            if (pendingToolCalls[i]._tool === tool) {
                idx = i;
                break;
            }
        }
        if (idx === -1) {
            if (rejected) {
                const d = document.createElement("div");
                d.className = "tool-result rejected";
                d.textContent = "✗ Denied";
                $messages.appendChild(d);
            }
            scrollToBottom();
            return;
        }
        const div = pendingToolCalls[idx];
        pendingToolCalls.splice(idx, 1);
        div._result = text;
        div._rejected = rejected;
        div.classList.remove("tool-pending");
        const statusEl = div.querySelector(".tool-status");
        if (rejected) {
            div.classList.add("tool-denied");
            statusEl.textContent = "✗";
            statusEl.className = "tool-status tool-status-denied";
        } else {
            div.classList.add("tool-done");
            statusEl.textContent = "✓";
            statusEl.className = "tool-status tool-status-ok";
            // 写入类工具显示结果摘要
            if (text && !["read_file", "list_files", "grep_search", "web_search", "web_fetch"].includes(tool)) {
                const preview = document.createElement("span");
                preview.className = "tool-result-preview";
                const p = text.replace(/\n/g, " ");
                preview.textContent = p.length > 100 ? p.slice(0, 100) + "..." : p;
                div.appendChild(preview);
            }
        }
        // 添加展开详情区
        const details = document.createElement("div");
        details.className = "tool-details";
        details.style.display = "none";
        details.innerHTML =
            "<b>Input:</b>\n" + escapeHtml(JSON.stringify(div._input, null, 2)) +
            "\n\n<b>Result:</b>\n" + escapeHtml(text || "(empty)") +
            "\n\n<i>Click to collapse</i>";
        div.appendChild(details);
        scrollToBottom();
    }

    function appendBackgroundTask(text, cls) {
        const div = document.createElement("div");
        div.className = "bg-task-notification " + (cls || "");
        div.textContent = text;
        $messages.appendChild(div);
        scrollToBottom();
        // 5秒后自动淡化
        setTimeout(() => { div.style.opacity = "0.4"; }, 5000);
    }

    function appendError(text) {
        const div = document.createElement("div");
        div.className = "error-block";
        div.textContent = "⚠ " + text;
        $messages.appendChild(div);
        scrollToBottom();
    }

    function showSystem(text) {
        const div = document.createElement("div");
        div.className = "system-message";
        div.textContent = text;
        $messages.appendChild(div);
        scrollToBottom();
    }

    function showWelcome() {
        const shortCwd = cwd.replace(/^\/Users\/[^/]+/, "~");
        const div = document.createElement("div");
        div.className = "welcome-panel";
        div.innerHTML = `
            <div class="welcome-content">
                <div class="welcome-logo">🐙</div>
                <div class="welcome-info">${escapeHtml(model)}<br>${escapeHtml(shortCwd)}</div>
            </div>`;
        $messages.appendChild(div);
        scrollToBottom();
    }

    let _scrollPending = false;
    function scrollToBottom() {
        if (_scrollPending) return;
        _scrollPending = true;
        requestAnimationFrame(() => { _scrollPending = false; $messages.scrollTop = $messages.scrollHeight; });
    }

    // ── 发送 ──
    function sendTask() {
        const text = $input.value.trim();
        if (!text) return;

        if (text.startsWith("/")) {
            sendJSON({ action: "slash", text: text });
            $input.value = "";
            autoResize();
            hideAutocomplete();
            return;
        }

        appendUserMessage(text);
        lastTask = text;
        busy = true;
        updateButtons();
        $input.value = "";
        autoResize();
        hideAutocomplete();
        sendJSON({ action: "task", text: text });
    }

    function sendInterrupt() {
        sendJSON({ action: "interrupt" });
    }

    function onInputKeydown(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendTask();
        }
        if (e.key === "Escape") {
            hideAutocomplete();
            $modelSelector.classList.add("hidden");
        }
        if (e.key === "Tab") {
            const ac = $autocomplete;
            if (ac && !ac.classList.contains("hidden")) {
                e.preventDefault();
                const first = ac.querySelector(".ac-item");
                if (first) {
                    $input.value = first.dataset.value + " ";
                    hideAutocomplete();
                    autoResize();
                }
            }
        }
    }

    function onInputChange() {
        autoResize();
        updateAutocomplete();
    }

    function autoResize() {
        $input.style.height = "auto";
        $input.style.height = Math.min($input.scrollHeight, 160) + "px";
    }

    function updateButtons() {
        $sendBtn.classList.toggle("hidden", busy);
        $stopBtn.classList.toggle("hidden", !busy);
        $input.disabled = busy;
        $input.placeholder = busy ? "Agent 执行中..." : "输入任务或 / 命令...";
    }

    // ── 确认对话框（支持并发队列） ──
    function showConfirmDialog(confirmId, toolName, toolSummary) {
        // 如果当前已有 confirm 在显示，排队等待
        if (pendingConfirmId) {
            confirmQueue.push({ confirmId, toolName, toolSummary });
            return;
        }
        pendingConfirmId = confirmId;
        pendingConfirmTool = toolName;
        $confirmTool.textContent = "🔧 " + toolName;
        $confirmInput.textContent = toolSummary || "";
        // 按钮文本带上工具名，让用户清楚适用范围
        $confirmApproveAll.textContent = "允许所有 " + toolName;
        // 标记对应 tool call 为"等待确认"而非"执行中"
        for (let i = pendingToolCalls.length - 1; i >= 0; i--) {
            if (pendingToolCalls[i]._tool === toolName) {
                pendingToolCalls[i].classList.add("tool-waiting");
                pendingToolCalls[i].classList.remove("tool-pending");
                const st = pendingToolCalls[i].querySelector(".tool-status");
                if (st) st.textContent = "⏳";
                break;
            }
        }
        $confirmDialog.classList.remove("hidden");
        scrollToBottom();
    }

    function resolveConfirm(approved, approveAll) {
        if (pendingConfirmId) {
            sendJSON({
                action: "confirm",
                confirm_id: pendingConfirmId,
                approved: approved,
                approve_all: approveAll,
            });
            if (approveAll && approved) {
                showSystem(`${pendingConfirmTool}: 本次会话允许所有`);
            }
            pendingConfirmId = null;
            pendingConfirmTool = null;
        }
        $confirmDialog.classList.add("hidden");
        // 处理队列中下一个 confirm
        if (confirmQueue.length > 0) {
            const next = confirmQueue.shift();
            showConfirmDialog(next.confirmId, next.toolName, next.toolSummary);
        }
    }

    // ── ask_user_question 对话框 ──
    let pendingAskId = null;

    function showAskDialog(askId, header, question, options, multiSelect) {
        pendingAskId = askId;
        const container = document.createElement("div");
        container.className = "message message-user";
        container.id = "ask-dialog-" + askId;
        let optionsHtml = options.map((opt, i) =>
            `<button class="btn-approve" style="margin:4px" data-idx="${i}">${escapeHtml(opt.label)}</button>`
        ).join("");
        container.innerHTML = `
            <div class="role-label" style="color:var(--accent-cyan)">${escapeHtml(header || "问题")}</div>
            <div class="message-content" style="margin:8px 0">${escapeHtml(question)}</div>
            <div class="ask-options">${optionsHtml}</div>
            <div style="margin-top:8px">
                <input id="ask-input-${askId}" type="text" placeholder="或输入自定义回答..." style="width:70%;padding:6px 10px;border:1px solid var(--border);border-radius:4px;font-size:13px">
                <button class="btn-approve" id="ask-submit-${askId}" style="margin-left:4px">提交</button>
            </div>`;
        $messages.appendChild(container);
        scrollToBottom();

        // 绑定选项按钮
        container.querySelectorAll(".ask-options .btn-approve").forEach(btn => {
            btn.addEventListener("click", () => {
                const label = options[parseInt(btn.dataset.idx)].label;
                resolveAsk(label);
                container.remove();
            });
        });
        // 绑定提交按钮
        const submitBtn = document.getElementById("ask-submit-" + askId);
        const inputEl = document.getElementById("ask-input-" + askId);
        if (submitBtn && inputEl) {
            submitBtn.addEventListener("click", () => {
                const val = inputEl.value.trim();
                resolveAsk(val || "(未回答)");
                container.remove();
            });
            inputEl.addEventListener("keydown", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    submitBtn.click();
                }
            });
        }
    }

    function resolveAsk(answer) {
        if (pendingAskId) {
            sendJSON({ action: "ask_response", ask_id: pendingAskId, answer: answer });
            pendingAskId = null;
        }
    }

    // ── 通用确认 ──
    function showConfirm(title, message) {
        return new Promise((resolve) => {
            $confirmTitle.textContent = title;
            $confirmMessage.textContent = message;
            $generalConfirm.classList.remove("hidden");

            const onOk = () => { cleanup(); resolve(true); };
            const onCancel = () => { cleanup(); resolve(false); };
            const cleanup = () => {
                $generalConfirm.classList.add("hidden");
                $confirmOkBtn.removeEventListener("click", onOk);
                $confirmCancelBtn.removeEventListener("click", onCancel);
            };

            $confirmOkBtn.addEventListener("click", onOk);
            $confirmCancelBtn.addEventListener("click", onCancel);
        });
    }

    // ── 目录信任 ──
    function showTrustDialog() {
        const trustCwd = document.getElementById("trust-cwd");
        if (trustCwd) trustCwd.textContent = cwd;
        if ($trustDialog) $trustDialog.classList.remove("hidden");
    }

    function trustDirectory() {
        sendJSON({ action: "trust_dir" });
        if ($trustDialog) $trustDialog.classList.add("hidden");
    }

    function skipTrust() {
        sendJSON({ action: "set_mode", mode: "plan" });
        planMode = true;
        updateModeDisplay();
        if ($trustDialog) $trustDialog.classList.add("hidden");
        showSystem("以 Plan 模式启动（只读）");
    }

    // ── Plan/Auto 切换 ──
    function toggleMode() {
        planMode = !planMode;
        sendJSON({ action: "set_mode", mode: planMode ? "plan" : "auto" });
        updateModeDisplay();
    }

    function updateModeDisplay() {
        $modeIndicator.textContent = planMode ? "PLAN" : "AUTO";
        $modeIndicator.className = planMode ? "plan" : "";
        $modeIndicator.title = "点击切换 Plan/Auto 模式";
        $modeIndicator.style.cursor = "pointer";
    }

    // ── 模型选择器 ──
    async function loadModels() {
        const token = sessionStorage.getItem("octopus_token");
        try {
            const resp = await fetch(`/api/models?token=${token}`);
            const data = await resp.json();
            modelsMap = data.models || {};
            renderModelSelector();
        } catch (e) { /* ignore */ }
    }

    function renderModelSelector() {
        $modelSelector.innerHTML = "";
        const modelNames = Object.keys(modelsMap);
        if (!modelNames.length) {
            const div = document.createElement("div");
            div.className = "model-option";
            div.style.color = "var(--text-dim)";
            div.textContent = "未配置模型";
            $modelSelector.appendChild(div);
            return;
        }
        modelNames.forEach(modelName => {
            const provider = modelsMap[modelName];
            const div = document.createElement("div");
            div.className = "model-option" + (modelName === model ? " current" : "");
            const providerHtml = provider ? `<span class="model-provider">${escapeHtml(provider)}</span>` : '';
            div.innerHTML = `<span class="model-name">${escapeHtml(modelName)}</span>` +
                providerHtml +
                (modelName === model ? '<span class="model-check">✓</span>' : '');
            div.addEventListener("click", (e) => {
                e.stopPropagation();
                sendJSON({ action: "switch_model", model: modelName });
                $modelSelector.classList.add("hidden");
            });
            $modelSelector.appendChild(div);
        });
    }

    function toggleModelSelector(e) {
        e.stopPropagation();
        if ($modelSelector.classList.contains("hidden")) {
            renderModelSelector();
            $modelSelector.classList.remove("hidden");
        } else {
            $modelSelector.classList.add("hidden");
        }
    }

    // ── Slash 命令自动补全 ──
    function updateAutocomplete() {
        const text = $input.value;
        if (!text.startsWith("/")) { hideAutocomplete(); return; }

        const parts = text.split(/\s+/);
        const cmdPart = parts[0].toLowerCase();

        if (parts.length === 1) {
            const matches = Object.keys(commands).filter(c => c.startsWith(cmdPart));
            if (matches.length === 0 || (matches.length === 1 && matches[0] === cmdPart)) {
                hideAutocomplete();
                return;
            }
            showAutocomplete(matches.map(c => ({
                value: c,
                label: c,
                desc: commands[c],
            })));
        } else {
            hideAutocomplete();
        }
    }

    function showAutocomplete(items) {
        const ac = $autocomplete;
        ac.innerHTML = "";
        items.slice(0, 10).forEach(item => {
            const div = document.createElement("div");
            div.className = "ac-item";
            div.dataset.value = item.value;
            div.innerHTML = `<span class="ac-label">${escapeHtml(item.label)}</span><span class="ac-desc">${escapeHtml(item.desc)}</span>`;
            div.addEventListener("mousedown", (e) => {
                e.preventDefault();
                $input.value = item.value + " ";
                hideAutocomplete();
                autoResize();
                $input.focus();
            });
            ac.appendChild(div);
        });
        ac.classList.remove("hidden");
    }

    function hideAutocomplete() {
        if ($autocomplete) $autocomplete.classList.add("hidden");
    }

    // ── 会话管理 ──
    async function loadSessions() {
        const token = sessionStorage.getItem("octopus_token");
        try {
            const resp = await fetch(`/api/sessions?token=${token}`);
            const sessions = await resp.json();
            renderSessions(sessions);
        } catch (e) { /* ignore */ }
    }

    function renderHistoryMessages(messages) {
        messages.forEach(msg => {
            const role = msg.role;
            const blocks = msg.blocks;
            if (!blocks || !blocks.length) return;

            if (role === "user") {
                const texts = blocks.filter(b => b.type === "text").map(b => b.text).join("\n");
                if (texts) appendUserMessage(texts);
            } else if (role === "assistant") {
                blocks.forEach(block => {
                    if (block.type === "thinking") {
                        appendThinkingBlock(block.thinking || "");
                    } else if (block.type === "text") {
                        const el = appendAssistantMessage();
                        el.querySelector(".message-content").innerHTML = renderMarkdown(block.text);
                        highlightCode(el.querySelector(".message-content"));
                    } else if (block.type === "tool_use") {
                        if (block.name === "edit_file" && block.input) {
                            appendEditDiff(block.input);
                        } else if (block.name === "multi_edit" && block.input) {
                            const edits = block.input.edits || [];
                            edits.forEach(edit => appendEditDiff(edit));
                        } else {
                            const div = appendToolCall(block.name || "", "", block.input || {});
                            if (block.done) {
                                div.classList.remove("tool-pending");
                                div.classList.add("tool-done");
                                div._result = block.result || "";
                                const statusEl = div.querySelector(".tool-status");
                                statusEl.textContent = "✓";
                                statusEl.className = "tool-status tool-status-ok";
                                if (block.result) {
                                    const preview = document.createElement("span");
                                    preview.className = "tool-result-preview";
                                    const p = block.result.replace(/\n/g, " ");
                                    preview.textContent = p.length > 100 ? p.slice(0, 100) + "..." : p;
                                    div.appendChild(preview);
                                }
                                // 可展开详情
                                const details = document.createElement("div");
                                details.className = "tool-details";
                                details.style.display = "none";
                                details.innerHTML =
                                    "<b>Input:</b>\n" + escapeHtml(JSON.stringify(block.input || {}, null, 2)) +
                                    "\n\n<b>Result:</b>\n" + escapeHtml(block.result || "(empty)") +
                                    "\n\n<i>Click to collapse</i>";
                                div.appendChild(details);
                                // 从 pendingToolCalls 中移除，避免干扰后续实时工具调用匹配
                                pendingToolCalls = pendingToolCalls.filter(el => el !== div);
                            }
                        }
                    }
                });
            }
        });
        // 确保历史消息渲染后 pendingToolCalls 干净
        pendingToolCalls = [];
        scrollToBottom();
    }

    function renderSessions(sessions) {
        $sessionList.innerHTML = "";
        if (!sessions || !sessions.length) {
            $sessionList.innerHTML = '<div class="session-empty">暂无会话</div>';
            return;
        }
        sessions.forEach((s) => {
            const div = document.createElement("div");
            const isSelected = selectedSessions.has(s.session_id);
            div.className = "session-item" +
                (s.session_id === sessionId ? " active" : "") +
                (isSelected ? " selected" : "");

            // 复选框
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.className = "session-checkbox";
            cb.checked = isSelected;
            cb.addEventListener("click", (e) => {
                e.stopPropagation();
                if (cb.checked) {
                    selectedSessions.add(s.session_id);
                } else {
                    selectedSessions.delete(s.session_id);
                }
                updateDeleteCount();
            });

            // 内容
            const content = document.createElement("div");
            content.className = "session-item-content";
            const name = s.name || s.first_message || s.session_id.slice(0, 8);
            const time = formatTime(s.updated_at);
            content.innerHTML = `<div class="session-name">${escapeHtml(name)}</div><div class="session-meta">${time} · ${s.message_count || 0} 条</div>`;

            if (!deleteMode) {
                content.addEventListener("click", () => resumeSession(s.session_id));
            }

            div.appendChild(cb);
            div.appendChild(content);
            $sessionList.appendChild(div);
        });

        // 删除模式下添加 class
        if (deleteMode) {
            $sessionList.classList.add("delete-mode");
        } else {
            $sessionList.classList.remove("delete-mode");
        }
    }

    function highlightSidebar() {
        $sessionList.querySelectorAll(".session-item").forEach(el => el.style.background = "rgba(74,158,255,0.1)");
        showSystem("点击左侧会话列表选择要恢复的会话");
    }

    async function confirmNewSession() {
        const ok = await showConfirm("新建会话", "当前会话将保存，是否创建新会话？");
        if (ok) {
            sendJSON({ action: "new_session" });
        }
    }

    function resumeSession(sid) {
        if (deleteMode) return;
        sendJSON({ action: "resume", session_id: sid });
    }

    // ── 批量删除 ──
    function toggleDeleteMode() {
        deleteMode = !deleteMode;
        selectedSessions.clear();
        $deleteModeBtn.classList.toggle("active", deleteMode);
        $deleteBar.classList.toggle("hidden", !deleteMode);
        updateDeleteCount();
        loadSessions();
    }

    function exitDeleteMode() {
        deleteMode = false;
        selectedSessions.clear();
        $deleteModeBtn.classList.remove("active");
        $deleteBar.classList.add("hidden");
        loadSessions();
    }

    function deleteSelectAll() {
        const token = sessionStorage.getItem("octopus_token");
        fetch(`/api/sessions?token=${token}`)
            .then(r => r.json())
            .then(sessions => {
                if (selectedSessions.size === sessions.length) {
                    selectedSessions.clear();
                } else {
                    sessions.forEach(s => selectedSessions.add(s.session_id));
                }
                updateDeleteCount();
                loadSessions();
            })
            .catch(err => console.warn("deleteSelectAll fetch failed:", err));
    }

    function updateDeleteCount() {
        $deleteCount.textContent = `已选 ${selectedSessions.size} 个`;
    }

    async function deleteSelected() {
        if (selectedSessions.size === 0) {
            showSystem("未选择任何会话");
            return;
        }
        const count = selectedSessions.size;
        const ok = await showConfirm("删除会话", `确定删除 ${count} 个会话？此操作不可撤销。`);
        if (!ok) return;

        const token = sessionStorage.getItem("octopus_token");
        const ids = [...selectedSessions];
        let deleted = 0;
        for (const sid of ids) {
            try {
                const resp = await fetch(`/api/sessions/${sid}?token=${token}`, { method: "DELETE" });
                if (resp.ok) deleted++;
            } catch (e) { /* ignore */ }
        }
        showSystem(`已删除 ${deleted} 个会话`);
        selectedSessions.clear();
        exitDeleteMode();
        // 如果删除了当前会话，创建新会话（跳过保存已删除的旧会话）
        if (ids.includes(sessionId)) {
            sendJSON({ action: "new_session", skip_save: true });
        }
        loadSessions();
    }

    // ── 文件下载 ──
    function downloadFile(content, filename) {
        const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showSystem(`已导出: ${filename}`);
    }

    // ── 工具函数 ──
    async function loadCommands() {
        const token = sessionStorage.getItem("octopus_token");
        try {
            const resp = await fetch(`/api/commands?token=${token}`);
            commands = await resp.json();
        } catch (e) { /* ignore */ }
    }

    function updateModelInfo() {
        const provider = modelsMap[model] || "";
        const display = provider ? `${model} ${provider}` : model;
        $modelInfo.textContent = display;
        $modelBtn.textContent = display;
        $modelBtn.title = "切换模型: " + model;
        if ($agentLabel) $agentLabel.textContent = currentAgent ? ` · ${currentAgent}` : "";
    }

    function updateTokenBar(usage) {
        const turnTotal = (usage.input_tokens || 0) + (usage.output_tokens || 0);
        const sessionTotal = sessionTokens.input + sessionTokens.output;
        $tokenBar.textContent = `tokens: ↑${usage.output_tokens || 0} ↓${usage.input_tokens || 0}  ·  ${turnTotal} turn  ·  ${sessionTotal} session`;
    }

    function formatTime(isoStr) {
        if (!isoStr) return "";
        try {
            const d = new Date(isoStr);
            const diff = (Date.now() - d) / 1000;
            if (diff < 60) return "刚刚";
            if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
            if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
            return d.toLocaleDateString("zh-CN");
        } catch { return isoStr.slice(0, 10); }
    }

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    // ── 主题 ──
    function applyTheme() {
        document.documentElement.setAttribute("data-theme", darkMode ? "dark" : "light");
        const lightCss = document.getElementById("highlight-css-light");
        const darkCss = document.getElementById("highlight-css-dark");
        if (lightCss) lightCss.disabled = darkMode;
        if (darkCss) darkCss.disabled = !darkMode;
    }

    function toggleTheme() {
        darkMode = !darkMode;
        localStorage.setItem("octopus_theme", darkMode ? "dark" : "light");
        applyTheme();
    }

    // ── 侧边栏折叠 ──
    const $sidebar = document.getElementById("sidebar");
    const $sidebarToggle = document.getElementById("sidebar-toggle");
    const $sidebarExpand = document.getElementById("sidebar-expand");

    function toggleSidebar() {
        $sidebar.classList.toggle("collapsed");
        $sidebarToggle.classList.toggle("collapsed", $sidebar.classList.contains("collapsed"));
        $sidebarExpand.classList.toggle("hidden", !$sidebar.classList.contains("collapsed"));
    }

    // ── 启动 ──
    document.addEventListener("DOMContentLoaded", () => {
        init();
        $sidebarToggle.addEventListener("click", toggleSidebar);
        $sidebarExpand.addEventListener("click", toggleSidebar);
        // 页面关闭前优雅关闭 WebSocket
        window.addEventListener("beforeunload", () => {
            if (ws) ws.close(1000, "page unload");
        });
    });
})();
