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
    let lastTask = null;
    let commands = {};   // slash 命令列表 {"/help": "desc", ...}
    let trusted = true;

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

        $sendBtn.addEventListener("click", sendTask);
        $stopBtn.addEventListener("click", sendInterrupt);
        $input.addEventListener("keydown", onInputKeydown);
        $input.addEventListener("input", onInputChange);
        $confirmApprove.addEventListener("click", () => resolveConfirm(true, false));
        $confirmReject.addEventListener("click", () => resolveConfirm(false, false));
        $confirmApproveAll.addEventListener("click", () => resolveConfirm(true, true));
        $newSessionBtn.addEventListener("click", newSession);
        if ($trustBtn) $trustBtn.addEventListener("click", trustDirectory);
        if ($trustSkipBtn) $trustSkipBtn.addEventListener("click", skipTrust);

        $modeIndicator.addEventListener("click", toggleMode);
        updateModeDisplay();
    }

    // ── WebSocket ──
    let wsToken = "";
    let wsReconnectTimer = null;

    function connectWS(token) {
        wsToken = token;
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        ws = new WebSocket(`${proto}//${location.host}/ws?token=${token}`);

        ws.onopen = () => {
            if (wsReconnectTimer) { showSystem("已重新连接"); }
            wsReconnectTimer = null;
        };
        ws.onmessage = (evt) => {
            try { handleEvent(JSON.parse(evt.data)); }
            catch (e) { /* ignore parse errors */ }
        };
        ws.onclose = () => {
            showSystem("连接已断开，3秒后重连...");
            busy = false;
            updateButtons();
            wsReconnectTimer = setTimeout(() => connectWS(wsToken), 3000);
        };
        ws.onerror = () => {};
    }

    function sendJSON(obj) {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
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
                showWelcome();
                break;

            case "stream":
                streamBuffer += text;
                scheduleRender();
                break;

            case "thinking":
                flushStream();
                if (text) appendThinking(text);
                break;

            case "tool_call":
                flushStream();
                if (meta.tool === "edit_file" && meta.input) {
                    appendEditDiff(meta.input);
                } else {
                    appendToolCall(meta.tool || "", text, meta.input || {});
                }
                break;

            case "tool_result":
                appendToolResult(text, meta.rejected || false, meta.tool || "");
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
                showConfirmDialog(meta.confirm_id, meta.tool_name, meta.tool_input);
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
                    showSystem(text);
                }
                break;

            case "messages_cleared":
                $messages.innerHTML = "";
                showSystem(text);
                break;

            case "session_resumed":
                sessionId = meta.session_id;
                $messages.innerHTML = "";
                showSystem(`已恢复会话，${meta.message_count} 条历史消息`);
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
        }
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
        // 后续高亮会在 DOM 插入后处理
        return html;
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

    function appendThinking(text) {
        const div = document.createElement("div");
        div.className = "thinking-block";
        const display = text.length > 500 ? text.slice(0, 500) + "..." : text;
        div.textContent = "💭 " + display;
        $messages.appendChild(div);
        scrollToBottom();
    }

    function appendToolCall(tool, summary, input) {
        const div = document.createElement("div");
        div.className = "tool-call";
        div.innerHTML = `<span class="tool-name">${escapeHtml(tool)}</span><span class="tool-summary">${escapeHtml(summary)}</span>`;
        if (input && Object.keys(input).length > 0) {
            const details = document.createElement("div");
            details.className = "tool-details-toggle";
            details.textContent = "▶ 详情";
            const content = document.createElement("pre");
            content.className = "tool-details-content";
            content.textContent = JSON.stringify(input, null, 2);
            details.addEventListener("click", () => {
                const open = content.style.display !== "none";
                content.style.display = open ? "none" : "block";
                details.textContent = open ? "▶ 详情" : "▼ 详情";
            });
            div.appendChild(details);
            div.appendChild(content);
        }
        $messages.appendChild(div);
        scrollToBottom();
    }

    function appendEditDiff(input) {
        const container = document.createElement("div");
        container.className = "tool-call edit-diff";
        const path = input.path || "";
        const oldText = input.old_string || "";
        const newText = input.new_string || "";

        container.innerHTML = `<span class="tool-name">edit_file</span><span class="tool-summary">${escapeHtml(path)}</span>`;

        const diffEl = document.createElement("div");
        diffEl.className = "diff-view";

        const oldLines = oldText.split("\n");
        const newLines = newText.split("\n");

        // Simple diff display
        oldLines.forEach(line => {
            const row = document.createElement("div");
            row.className = "diff-line diff-removed";
            row.textContent = "- " + line;
            diffEl.appendChild(row);
        });
        newLines.forEach(line => {
            const row = document.createElement("div");
            row.className = "diff-line diff-added";
            row.textContent = "+ " + line;
            diffEl.appendChild(row);
        });

        container.appendChild(diffEl);
        $messages.appendChild(container);
        scrollToBottom();
    }

    function appendToolResult(text, rejected, tool) {
        const div = document.createElement("div");
        div.className = "tool-result" + (rejected ? " rejected" : "");
        div.textContent = rejected ? "✗ 已拒绝" : "→ " + text;
        $messages.appendChild(div);
        scrollToBottom();
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
                <div class="welcome-left">
                    <pre class="welcome-logo">     _
    (o o)
   //|||\\\\</pre>
                    <div class="welcome-info">${escapeHtml(model)}<br>${escapeHtml(shortCwd)}</div>
                </div>
                <div class="welcome-right">
                    <div class="welcome-tips">
                        <strong>Tips</strong>
                        /help — 查看所有命令
                        /agents — 切换 agent
                        /skills — 执行 skill
                        /plan — 只读模式
                        /quit — 退出
                    </div>
                </div>
            </div>`;
        $messages.appendChild(div);
        scrollToBottom();
    }

    function scrollToBottom() {
        requestAnimationFrame(() => { $messages.scrollTop = $messages.scrollHeight; });
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

    // ── 确认对话框 ──
    function showConfirmDialog(confirmId, toolName, toolInput) {
        pendingConfirmId = confirmId;
        pendingConfirmTool = toolName;
        $confirmTool.textContent = "🔧 " + toolName;
        $confirmInput.textContent = JSON.stringify(toolInput, null, 2);
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

    // ── Slash 命令自动补全 ──
    function updateAutocomplete() {
        const text = $input.value;
        if (!text.startsWith("/")) { hideAutocomplete(); return; }

        const parts = text.split(/\s+/);
        const cmdPart = parts[0].toLowerCase();

        if (parts.length === 1) {
            // 命令补全
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

    function renderSessions(sessions) {
        $sessionList.innerHTML = "";
        if (!sessions || !sessions.length) {
            $sessionList.innerHTML = '<div class="session-empty">暂无会话</div>';
            return;
        }
        sessions.forEach((s) => {
            const div = document.createElement("div");
            div.className = "session-item" + (s.session_id === sessionId ? " active" : "");
            const name = s.name || s.first_message || s.session_id.slice(0, 8);
            const time = formatTime(s.updated_at);
            div.innerHTML = `<div class="session-name">${escapeHtml(name)}</div><div class="session-meta">${time} · ${s.message_count || 0} 条</div>`;
            div.addEventListener("click", () => resumeSession(s.session_id));
            $sessionList.appendChild(div);
        });
    }

    function highlightSidebar() {
        $sessionList.querySelectorAll(".session-item").forEach(el => el.style.background = "rgba(74,158,255,0.1)");
        showSystem("点击左侧会话列表选择要恢复的会话");
    }

    function newSession() {
        // 清空后重连
        location.reload();
    }

    function resumeSession(sid) {
        sendJSON({ action: "resume", session_id: sid });
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
        $modelInfo.textContent = model;
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

    // ── 启动 ──
    document.addEventListener("DOMContentLoaded", init);
})();
