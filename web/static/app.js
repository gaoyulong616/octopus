/* Octopus Web UI — Frontend Logic (豆包风格) */

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
    let confirmQueue = [];
    let lastTask = null;
    let commands = {};
    let trusted = true;
    let modelsMap = {};
    let deleteMode = false;
    let selectedSessions = new Set();
    let darkMode = false;
    let showThinking = true;
    let terminalOpen = false;
    let terminalInstance = null;
    let terminalFit = null;
    let terminalWS = null;
    let _savedTitle = "Octopus";
    let fileBrowserMode = false;
    let fbCurrentPath = "";
    let fbEntries = [];
    let fbNodeCache = {};
    let monacoEditor = null;
    let monacoLoaded = false;
    let fbDirty = false;
    let fbActiveFilePath = "";

    let sessionTokens = { input: 0, output: 0 };

    // ── DOM ──
    const $chatScroll = document.getElementById("chat-scroll");
    const $messages = document.getElementById("messages");
    const $welcomePanel = document.getElementById("welcome-panel");
    const $input = document.getElementById("input");
    const $micBtn = document.getElementById("mic-btn");
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
    const $modelBtnText = document.getElementById("model-btn-text");
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
    const $sidebar = document.getElementById("sidebar");
    const $sidebarToggle = document.getElementById("sidebar-toggle");
    const $sidebarExpand = document.getElementById("sidebar-expand");
    const $themeToggle = document.getElementById("theme-toggle");
    const $uploadBtn = document.getElementById("upload-btn");
    const $fileInput = document.getElementById("file-input");
    const $exportBtn = document.getElementById("export-btn");
    const $exportMenu = document.getElementById("export-menu");
    const $sessionTitle = document.getElementById("session-title");
    const $sessionSearch = document.getElementById("session-search");
    const $userAvatar = document.getElementById("user-avatar");
    const $terminalBtn = document.getElementById("terminal-btn");
    const $terminalContainer = document.getElementById("terminal-container");
    const $xtermEl = document.getElementById("xterm");
    const $inputBox = document.querySelector(".db-input-box");
    const $fbSection = document.getElementById("fb-section");
    const $fbTree = document.getElementById("fb-tree");
    const $fbCurrentPath = document.getElementById("fb-current-path");
    const $fbRefresh = document.getElementById("fb-refresh");
    const $editorContainer = document.getElementById("editor-container");
    const $monacoEl = document.getElementById("monaco-editor");
    const $editorFilepath = document.getElementById("editor-filepath");
    const $editorStatus = document.getElementById("editor-status");
    const $editorSaveBtn = document.getElementById("editor-save-btn");
    const $navSkills = document.getElementById("nav-skills");
    const $navSkillsSub = document.getElementById("nav-skills-sub");
    const $navSkillsArrow = document.getElementById("nav-skills-arrow");

    // ── 图片灯箱 ──
    function openLightbox(src) {
        const $lightbox = document.getElementById("image-lightbox");
        const $img = $lightbox.querySelector(".lightbox-img");
        $img.src = src;
        $lightbox.classList.remove("hidden");
    }

    function closeLightbox() {
        const $lightbox = document.getElementById("image-lightbox");
        $lightbox.classList.add("hidden");
        $lightbox.querySelector(".lightbox-img").src = "";
    }

    window._openLightbox = openLightbox;

    // ── 欢迎面板 ──
    function hideWelcome() {
        if ($welcomePanel) $welcomePanel.classList.add("hidden");
    }

    function showWelcomePanel() {
        if ($welcomePanel) $welcomePanel.classList.remove("hidden");
    }

    // ── 初始化 ──
    function init() {
        if (window.mermaid) mermaid.initialize({ startOnLoad: false, theme: "default" });
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

        document.addEventListener("paste", handlePaste);
        const $inputArea = document.querySelector(".db-input-wrap");
        if ($inputArea) {
            $inputArea.addEventListener("dragover", (e) => { e.preventDefault(); e.stopPropagation(); });
            $inputArea.addEventListener("drop", handleDrop);
        }

        $modeIndicator.addEventListener("click", toggleMode);
        $modelBtn.addEventListener("click", toggleModelSelector);
        $deleteModeBtn.addEventListener("click", toggleDeleteMode);
        $deleteSelectAllBtn.addEventListener("click", deleteSelectAll);
        $deleteConfirmBtn.addEventListener("click", deleteSelected);
        $deleteCancelBtn.addEventListener("click", exitDeleteMode);

        // 上传按钮
        if ($uploadBtn && $fileInput) {
            $uploadBtn.addEventListener("click", () => $fileInput.click());
            $fileInput.addEventListener("change", () => {
                for (const file of $fileInput.files) handleImageFile(file);
                $fileInput.value = "";
            });
        }

        // 导出按钮 - 弹出格式选择菜单
        if ($exportBtn && $exportMenu) {
            $exportBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                $exportMenu.classList.toggle("hidden");
            });
            $exportMenu.querySelectorAll(".db-export-item").forEach(item => {
                item.addEventListener("click", (e) => {
                    e.stopPropagation();
                    const fmt = item.dataset.fmt;
                    $exportMenu.classList.add("hidden");
                    if (fmt === "md") {
                        sendJSON({ action: "slash", text: "/export" });
                    } else if (fmt === "html") {
                        exportAsHTML();
                    } else if (fmt === "pdf") {
                        exportAsPDF();
                    }
                });
            });
        }

        // 会话搜索
        if ($sessionSearch) {
            $sessionSearch.addEventListener("input", () => {
                const q = $sessionSearch.value.toLowerCase();
                $sessionList.querySelectorAll(".db-hist").forEach(el => {
                    const name = (el._sessionName || "").toLowerCase();
                    el.style.display = name.includes(q) ? "" : "none";
                });
            });
        }

        // 建议卡片
        document.querySelectorAll(".db-sugg-card").forEach(card => {
            card.addEventListener("click", () => {
                const prompt = card.dataset.prompt || "";
                $input.value = prompt;
                $input.focus();
                autoResize();
            });
        });

        // 侧边栏导航项
        document.querySelectorAll(".db-nav-item").forEach(item => {
            item.addEventListener("click", function () {
                if (this.id === "nav-skills") {
                    $navSkillsSub.classList.toggle("hidden");
                    if ($navSkillsArrow) $navSkillsArrow.classList.toggle("open");
                    return;
                }
                document.querySelectorAll(".db-nav-item").forEach(el => el.classList.remove("act"));
                this.classList.add("act");
                $navSkillsSub.classList.add("hidden");
                if ($navSkillsArrow) $navSkillsArrow.classList.remove("open");
            });
        });
        // 子菜单项
        document.querySelectorAll(".db-nav-sub-item").forEach(item => {
            item.addEventListener("click", function () {
                const view = this.dataset.view;
                document.querySelectorAll(".db-nav-sub-item").forEach(el => el.classList.remove("active"));
                this.classList.add("active");
                if (view === "filebrowser") {
                    toggleFileBrowser(true);
                }
            });
        });

        updateModeDisplay();

        // 主题初始化
        const savedTheme = localStorage.getItem("octopus_theme");
        if (savedTheme === "dark" || savedTheme === "light") {
            darkMode = savedTheme === "dark";
        } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
            darkMode = true;
        }
        applyTheme();
        if ($themeToggle) $themeToggle.addEventListener("click", toggleTheme);
        if ($terminalBtn) $terminalBtn.addEventListener("click", toggleTerminal);
        if ($editorSaveBtn) $editorSaveBtn.addEventListener("click", saveFile);

        // 点击外部关闭弹出菜单
        document.addEventListener("click", (e) => {
            if (!$modelBtn.contains(e.target) && !$modelSelector.contains(e.target)) {
                $modelSelector.classList.add("hidden");
            }
            if ($exportBtn && $exportMenu && !$exportBtn.contains(e.target) && !$exportMenu.contains(e.target)) {
                $exportMenu.classList.add("hidden");
            }
        });

        // 图片灯箱关闭事件
        const $lightbox = document.getElementById("image-lightbox");
        if ($lightbox) {
            $lightbox.querySelector(".lightbox-backdrop").addEventListener("click", closeLightbox);
            $lightbox.querySelector(".lightbox-close").addEventListener("click", closeLightbox);
            document.addEventListener("keydown", (e) => {
                if (e.key === "Escape" && !$lightbox.classList.contains("hidden")) {
                    closeLightbox();
                }
            });
        }
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
                pendingToolCalls = [];
                confirmQueue = [];
                streamBuffer = "";
                currentAssistantEl = null;
                if (pendingConfirmId) {
                    pendingConfirmId = null;
                    pendingConfirmTool = null;
                    $confirmDialog.classList.add("hidden");
                    showSystem("之前的确认已失效");
                }
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
                if (meta.messages && meta.messages.length > 0) {
                    hideWelcome();
                    renderHistoryMessages(meta.messages);
                    const firstUser = meta.messages.find(m => m.role === "user");
                    if (firstUser) {
                        const txt = firstUser.blocks.filter(b => b.type === "text").map(b => b.text).join(" ").slice(0, 40);
                        updateSessionTitle(txt || "Octopus");
                    }
                } else {
                    $messages.innerHTML = "";
                    showWelcomePanel();
                    updateSessionTitle("Octopus");
                }
                loadSessions();
                break;

            case "stream":
                thinkingEl = null;
                hideWelcome();
                streamBuffer += text;
                scheduleRender();
                break;

            case "thinking":
                const thinkBeforeEl = currentAssistantEl;
                flushStream();
                hideWelcome();
                if (text) appendThinking(text, thinkBeforeEl);
                break;

            case "wakeup":
                flushStream();
                hideWelcome();
                appendWakeup(text);
                break;

            case "tool_call":
                thinkingEl = null;
                flushStream();
                hideWelcome();
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
                updateToolResult(text, meta.rejected || false, meta.tool || "", meta.tool_id || "");
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
                hideWelcome();
                appendError(text);
                break;

            case "progress":
                break;

            case "confirm_request":
                showConfirmDialog(meta.confirm_id, meta.tool_name, meta.tool_summary);
                const needConfirmDiv = document.createElement("div");
                needConfirmDiv.className = "system-message confirm-notice";
                needConfirmDiv.textContent = `⏳ ${meta.tool_name} 需要你的确认 — 请操作下方对话框`;
                $messages.appendChild(needConfirmDiv);
                scrollToBottom(true);
                break;

            case "done":
                flushStream();
                busy = false;
                updateButtons();
                loadSessions();
                break;

            case "slash_result":
                if (text && text !== "__QUIT__") {
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
                showWelcomePanel();
                updateSessionTitle("Octopus");
                showSystem(text);
                break;

            case "session_resumed":
                sessionId = meta.session_id;
                $messages.innerHTML = "";
                hideWelcome();
                if (meta.messages && meta.messages.length > 0) {
                    renderHistoryMessages(meta.messages);
                    const firstUser = meta.messages.find(m => m.role === "user");
                    if (firstUser) {
                        const txt = firstUser.blocks.filter(b => b.type === "text").map(b => b.text).join(" ").slice(0, 40);
                        updateSessionTitle(txt || "Octopus");
                    }
                } else {
                    showWelcomePanel();
                    updateSessionTitle("Octopus");
                }
                showSystem(`已恢复会话，${meta.message_count} 条历史消息`);
                loadSessions();
                break;

            case "session_created":
                sessionId = meta.session_id;
                $messages.innerHTML = "";
                showWelcomePanel();
                updateSessionTitle("Octopus");
                loadSessions();
                break;

            case "mode_changed":
                planMode = text === "plan";
                updateModeDisplay();
                if (meta.note) {
                    showSystem(meta.note);
                } else {
                    showSystem(planMode ? "已切换到 Plan 模式（只读，不会修改文件）" : "已切换到 Auto 模式（可执行所有操作）");
                }
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
                hideWelcome();
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
        scrollToBottom(true);
        highlightCode(container);
        renderMermaid(container);
    }

    function approvePlan(approved) {
        sendJSON({ action: approved ? "plan_approve" : "plan_reject" });
        if (approved) planMode = false;
        updateModeDisplay();
        document.querySelectorAll(".plan-actions").forEach(el => el.innerHTML = approved
            ? '<span style="color:var(--accent-green)">✓ 计划已批准，已切换到 Auto 模式</span>'
            : '<span style="color:var(--accent-yellow)">计划未批准，仍处于 Plan 模式</span>');
    }
    window.approvePlan = approvePlan;

    // ── 终端 ──
    function toggleTerminal() {
        terminalOpen = !terminalOpen;
        $terminalContainer.classList.toggle("active", terminalOpen);
        $chatScroll.classList.toggle("hidden", terminalOpen);
        $terminalBtn.classList.toggle("active", terminalOpen);
        if ($inputBox) $inputBox.classList.toggle("hidden", terminalOpen);
        if ($exportBtn) $exportBtn.classList.toggle("hidden", terminalOpen);
        if (terminalOpen) {
            _savedTitle = $sessionTitle.textContent;
            $sessionTitle.textContent = "终端";
            if (!terminalInstance) {
                initTerminal();
            } else {
                terminalFit.fit();
                terminalInstance.focus();
                connectTerminalWS();
            }
        } else {
            $sessionTitle.textContent = _savedTitle || "Octopus";
            disconnectTerminalWS();
        }
    }

    function initTerminal() {
        // xterm UMD 将导出对象设为全局，取 .Terminal / .FitAddon
        const TerminalCtor = typeof Terminal !== "undefined" ? Terminal : null;
        const FitAddonCtor = typeof FitAddon !== "undefined" ? (FitAddon.FitAddon || FitAddon) : null;
        if (!TerminalCtor || !FitAddonCtor) {
            $xtermEl.textContent = "终端加载失败: xterm.js 未正确加载";
            return;
        }
        $xtermEl.textContent = "";
        const isDark = document.documentElement.getAttribute("data-theme") === "dark";
        terminalInstance = new TerminalCtor({
            cursorBlink: true,
            fontSize: 14,
            fontFamily: "'SF Mono', 'Fira Code', 'Courier New', monospace",
            theme: {
                background: isDark ? "#1e1e32" : "#ffffff",
                foreground: isDark ? "#e0e0e0" : "#1a1a1a",
                cursor: isDark ? "#e0e0e0" : "#1a1a1a",
                selectionBackground: isDark ? "#3a3a5e" : "#d0d0f0",
                black: "#1a1a1a", red: "#e34c4c", green: "#6bbf4a", yellow: "#dbb33d",
                blue: "#4a6ff5", magenta: "#c04ad0", cyan: "#3bc7b8", white: "#d0d0d0",
                brightBlack: "#666", brightRed: "#f07070",
                brightGreen: "#80d070", brightYellow: "#e0c050",
                brightBlue: "#7080f0", brightMagenta: "#d070e0",
                brightCyan: "#60d0c0", brightWhite: "#f0f0f0",
            },
        });
        terminalFit = new FitAddonCtor();
        terminalInstance.loadAddon(terminalFit);
        terminalInstance.open($xtermEl);
        terminalFit.fit();
        terminalInstance.onData(data => {
            if (terminalWS && terminalWS.readyState === WebSocket.OPEN) {
                terminalWS.send(JSON.stringify({ action: "input", data }));
            }
        });
        terminalInstance.onResize(({ cols, rows }) => {
            if (terminalWS && terminalWS.readyState === WebSocket.OPEN) {
                terminalWS.send(JSON.stringify({ action: "resize", rows, cols }));
            }
        });
        connectTerminalWS();
    }

    function connectTerminalWS() {
        if (terminalWS) disconnectTerminalWS();
        const token = sessionStorage.getItem("octopus_token") || "";
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        terminalWS = new WebSocket(`${proto}//${location.host}/ws/pty?token=${token}`);
        terminalWS.binaryType = "arraybuffer";
        terminalWS.onopen = () => {
            if (!terminalInstance) return;
            terminalInstance.focus();
            // 发送初始 resize
            const { cols, rows } = terminalInstance;
            terminalWS.send(JSON.stringify({ action: "resize", rows, cols }));
        };
        terminalWS.onmessage = (e) => {
            if (!terminalInstance) return;
            const arr = new Uint8Array(e.data);
            terminalInstance.write(arr);
        };
        terminalWS.onclose = () => {
            terminalWS = null;
        };
        terminalWS.onerror = () => {};
    }

    function disconnectTerminalWS() {
        if (terminalWS) {
            terminalWS.onclose = null;
            terminalWS.close();
            terminalWS = null;
        }
    }

    // ── 文件浏览器 ──
    function toggleFileBrowser(open) {
        fileBrowserMode = open;
        if (open) {
            document.querySelectorAll(".db-nav-item").forEach(el => el.classList.remove("act"));
            document.querySelectorAll(".db-nav-sub-item").forEach(el => el.classList.remove("active"));
            const subItems = document.querySelectorAll('.db-nav-sub-item[data-view="filebrowser"]');
            subItems.forEach(el => el.classList.add("active"));

            $chatScroll.classList.add("hidden");
            $terminalContainer.classList.remove("active");
            $editorContainer.classList.add("active");
            if ($inputBox) $inputBox.classList.add("hidden");
            if ($exportBtn) $exportBtn.classList.add("hidden");
            if (terminalOpen) {
                terminalOpen = false;
                $terminalBtn.classList.remove("active");
                disconnectTerminalWS();
            }
            $sessionTitle.textContent = "文件编辑器";

            // 隐藏会话列表，显示文件浏览器
            const $sectionLabel = document.querySelector(".db-section-label");
            if ($sectionLabel) $sectionLabel.style.display = "none";
            $sessionList.style.display = "none";
            $deleteBar.style.display = "none";
            $fbSection.classList.remove("hidden");

            initMonaco();
            if (!fbCurrentPath && cwd) {
                fbCurrentPath = cwd;
                loadFileTree(cwd);
            } else if (fbCurrentPath) {
                loadFileTree(fbCurrentPath);
            }
        } else {
            $editorContainer.classList.remove("active");
            $chatScroll.classList.remove("hidden");
            if ($inputBox) $inputBox.classList.remove("hidden");
            if ($exportBtn) $exportBtn.classList.remove("hidden");
            $sessionTitle.textContent = _savedTitle || "Octopus";

            const $sectionLabel = document.querySelector(".db-section-label");
            if ($sectionLabel) $sectionLabel.style.display = "";
            $sessionList.style.display = "";
            $deleteBar.style.display = "";
            $fbSection.classList.add("hidden");

            document.querySelectorAll(".db-nav-sub-item").forEach(el => el.classList.remove("active"));
        }
    }

    function loadFileTree(dirPath) {
        fbCurrentPath = dirPath;
        $fbCurrentPath.textContent = dirPath;
        $fbTree.innerHTML = '<div class="fb-loading">加载中...</div>';
        fbNodeCache = {};

        const token = sessionStorage.getItem("octopus_token");
        fetch(`/api/files?path=${encodeURIComponent(dirPath)}&token=${token}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    $fbTree.innerHTML = `<div class="fb-error">${escapeHtml(data.error)}</div>`;
                    return;
                }
                fbEntries = data.entries || [];
                renderFileTree(data.entries, $fbTree, 0);
            })
            .catch(err => {
                $fbTree.innerHTML = `<div class="fb-error">加载失败: ${escapeHtml(err.message)}</div>`;
            });
    }

    function renderFileTree(entries, container, depth) {
        container.innerHTML = "";
        if (!entries || entries.length === 0) {
            container.innerHTML = '<div class="fb-empty">空目录</div>';
            return;
        }
        // Add ".." for parent dir if depth === 0
        if (depth === 0 && fbCurrentPath !== "/") {
            const parentEl = createFileNode({
                name: "..",
                path: parentPath(fbCurrentPath),
                type: "dir",
                size: 0,
            }, depth);
            container.appendChild(parentEl);
        }
        entries.forEach(entry => {
            const node = createFileNode(entry, depth);
            container.appendChild(node);
        });
    }

    function parentPath(path) {
        const idx = path.lastIndexOf("/");
        if (idx <= 0) return "/";
        return path.slice(0, idx);
    }

    function createFileNode(entry, depth) {
        const div = document.createElement("div");
        div.className = "fb-node" + (entry.type === "dir" ? " fb-dir" : " fb-file");
        div.style.paddingLeft = (12 + depth * 16) + "px";
        div.dataset.path = entry.path;

        const toggle = document.createElement("span");
        toggle.className = "fb-toggle";
        if (entry.type === "dir") {
            toggle.innerHTML = '<i class="ti ti-chevron-right"></i>';
        }
        div.appendChild(toggle);

        const icon = document.createElement("span");
        icon.className = "fb-icon";
        if (entry.type === "dir") {
            icon.innerHTML = '<i class="ti ti-folder"></i>';
        } else {
            const ext = (entry.name || "").split(".").pop().toLowerCase();
            const iconMap = {
                py: "ti ti-brand-python", js: "ti ti-brand-javascript", ts: "ti ti-brand-typescript",
                html: "ti ti-brand-html5", css: "ti ti-brand-css3", json: "ti ti-file-code",
                md: "ti ti-markdown", yaml: "ti ti-file-code", yml: "ti ti-file-code",
                toml: "ti ti-file-code", txt: "ti ti-file-text", gitignore: "ti ti-file-code",
                svg: "ti ti-file-code", png: "ti ti-file-photo", jpg: "ti ti-file-photo",
                jpeg: "ti ti-file-photo", gif: "ti ti-file-photo",
            };
            const iconClass = iconMap[ext] || "ti ti-file";
            icon.innerHTML = `<i class="${iconClass}"></i>`;
        }
        div.appendChild(icon);

        const name = document.createElement("span");
        name.className = "fb-name";
        name.textContent = entry.name;
        div.appendChild(name);

        if (entry.type === "dir") {
            const childrenContainer = document.createElement("div");
            childrenContainer.className = "fb-children";
            childrenContainer.dataset.loaded = "false";
            div.appendChild(childrenContainer);

            div.addEventListener("click", (e) => {
                e.stopPropagation();
                const isOpen = toggle.classList.toggle("open");
                childrenContainer.classList.toggle("open");
                if (isOpen && childrenContainer.dataset.loaded === "false") {
                    loadDirChildren(entry.path, childrenContainer, depth + 1, toggle, childrenContainer);
                }
            });
        } else {
            div.addEventListener("click", (e) => {
                e.stopPropagation();
                document.querySelectorAll(".fb-node.active").forEach(el => el.classList.remove("active"));
                div.classList.add("active");
                openFileInEditor(entry.path);
            });
        }

        return div;
    }

    function loadDirChildren(dirPath, container, depth, toggleEl, childrenContainer) {
        container.innerHTML = '<div class="fb-loading">...</div>';
        container.classList.add("open");

        const token = sessionStorage.getItem("octopus_token");
        fetch(`/api/files?path=${encodeURIComponent(dirPath)}&token=${token}`)
            .then(r => r.json())
            .then(data => {
                container.dataset.loaded = "true";
                if (data.error) {
                    container.innerHTML = `<div class="fb-error">${escapeHtml(data.error)}</div>`;
                    return;
                }
                container.innerHTML = "";
                (data.entries || []).forEach(entry => {
                    const node = createFileNode(entry, depth);
                    container.appendChild(node);
                });
                if (!data.entries || data.entries.length === 0) {
                    container.innerHTML = '<div class="fb-empty">空目录</div>';
                }
            })
            .catch(err => {
                container.innerHTML = `<div class="fb-error">加载失败</div>`;
            });
    }

    // ── Monaco Editor ──
    function initMonaco() {
        if (monacoEditor) return;
        if (typeof monaco !== "undefined" && monaco.editor) {
            createMonacoEditor();
            return;
        }
        try {
            require.config({
                paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs" }
            });
            require(["vs/editor/editor.main"], function () {
                createMonacoEditor();
            });
        } catch (e) {
            $editorFilepath.textContent = "Monaco Editor 加载失败: " + e.message;
        }
    }

    function createMonacoEditor() {
        if (monacoEditor) return;
        if (typeof monaco === "undefined" || !monaco.editor) return;
        monacoLoaded = true;
        const isDark = document.documentElement.getAttribute("data-theme") === "dark";
        monacoEditor = monaco.editor.create($monacoEl, {
            value: "",
            language: "plaintext",
            theme: isDark ? "vs-dark" : "vs",
            automaticLayout: true,
            fontSize: 14,
            fontFamily: "'SF Mono', 'Fira Code', 'Courier New', monospace",
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: "on",
            tabSize: 4,
            renderWhitespace: "selection",
        });
        monacoEditor.onDidChangeModelContent(function () {
            if (fbActiveFilePath) {
                if (!fbDirty) {
                    fbDirty = true;
                    $editorStatus.textContent = "● 未保存";
                    $editorStatus.className = "editor-status dirty";
                }
            }
        });
        $editorStatus.textContent = "就绪";
        $editorStatus.className = "editor-status";
    }

    function openFileInEditor(filePath) {
        fbActiveFilePath = filePath;
        fbDirty = false;
        if ($editorSaveBtn) $editorSaveBtn.classList.remove("hidden");

        const token = sessionStorage.getItem("octopus_token");
        $editorFilepath.textContent = filePath;
        $editorStatus.textContent = "加载中...";
        $editorStatus.className = "editor-status";

        fetch(`/api/file?path=${encodeURIComponent(filePath)}&token=${token}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    $editorStatus.textContent = "错误: " + data.error;
                    $editorStatus.className = "editor-status error";
                    return;
                }
                if (monacoEditor) {
                    const lang = guessMonacoLang(filePath);
                    monaco.editor.setModelLanguage(monacoEditor.getModel(), lang);
                    monacoEditor.setValue(data.content || "");
                    monacoEditor.focus();
                }
                fbDirty = false;
                $editorStatus.textContent = "已加载";
                $editorStatus.className = "editor-status ok";
            })
            .catch(err => {
                $editorStatus.textContent = "加载失败";
                $editorStatus.className = "editor-status error";
            });
    }

    function guessMonacoLang(filePath) {
        const ext = (filePath || "").split(".").pop().toLowerCase();
        const map = {
            py: "python", js: "javascript", ts: "typescript", jsx: "javascript", tsx: "typescript",
            json: "json", html: "html", css: "css", scss: "scss", less: "less",
            md: "markdown", yaml: "yaml", yml: "yaml", xml: "xml", toml: "ini",
            sh: "shell", bash: "shell", zsh: "shell",
            c: "c", h: "c", cpp: "cpp", cc: "cpp", hpp: "cpp", java: "java",
            go: "go", rs: "rust", rb: "ruby", php: "php", sql: "sql",
            swift: "swift", kt: "kotlin", dart: "dart", lua: "lua", r: "r",
            graphql: "graphql", gql: "graphql", dockerfile: "dockerfile",
        };
        if ((filePath || "").split("/").pop() === "Dockerfile") return "dockerfile";
        return map[ext] || "plaintext";
    }

    function saveFile() {
        if (!fbActiveFilePath || !monacoEditor) return;
        const content = monacoEditor.getValue();
        const token = sessionStorage.getItem("octopus_token");
        $editorStatus.textContent = "保存中...";
        $editorStatus.className = "editor-status";

        fetch("/api/file?token=" + token, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: fbActiveFilePath, content: content }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    fbDirty = false;
                    $editorStatus.textContent = "已保存";
                    $editorStatus.className = "editor-status ok";
                    // 刷新文件树中对应文件条目
                } else {
                    $editorStatus.textContent = "保存失败: " + (data.error || "");
                    $editorStatus.className = "editor-status error";
                }
            })
            .catch(err => {
                $editorStatus.textContent = "保存失败";
                $editorStatus.className = "editor-status error";
            });
    }

    // ── 文件浏览器快捷键 ──
    document.addEventListener("keydown", function (e) {
        if (!fileBrowserMode || !monacoEditor) return;
        if ((e.ctrlKey || e.metaKey) && e.key === "s") {
            e.preventDefault();
            saveFile();
        }
    });

    // ── 流式渲染 ──
    function scheduleRender() {
        if (renderTimer) return;
        renderTimer = setTimeout(() => { renderTimer = null; renderStreamBuffer(); }, 200);
    }

    function renderStreamBuffer() {
        if (!streamBuffer) return;
        if (!currentAssistantEl) currentAssistantEl = appendAssistantMessage();
        const contentEl = currentAssistantEl.querySelector(".message-content");
        const prevCodeCount = contentEl.querySelectorAll("pre code").length;
        contentEl.innerHTML = renderMarkdown(streamBuffer);
        const allCode = contentEl.querySelectorAll("pre code");
        for (let i = prevCodeCount; i < allCode.length; i++) {
            try { hljs.highlightElement(allCode[i]); } catch (e) {}
        }
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
            renderMermaid(contentEl);
            const indicator = contentEl.querySelector(".streaming-indicator");
            if (indicator) indicator.remove();
            streamBuffer = "";
            currentAssistantEl = null;
            scrollToBottom();
        }
    }

    // ── Markdown 渲染 ──
    function renderMarkdown(text) {
        text = text.replace(/^(\s*)- \[([ xX])\] (.*)$/gm, function (_, indent, checked, content) {
            const icon = checked.toLowerCase() === 'x' ? '✔' : '◻';
            const style = checked.toLowerCase() === 'x' ? 'color:var(--accent-green)' : 'color:var(--text-dim)';
            return `${indent}<span style="${style}">${icon}</span> ${content}`;
        });
        const html = marked.parse(text);
        if (typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(html);
        }
        return escapeHtml(text);
    }

    function highlightCode(el) {
        el.querySelectorAll("pre code").forEach((block) => {
            hljs.highlightElement(block);
        });
    }

    function renderMermaid(container) {
        if (!window.mermaid) return;
        // marked 输出 <pre><code class="language-mermaid"> → 转为 mermaid 期望的 <pre class="mermaid">
        container.querySelectorAll("pre code.language-mermaid").forEach(code => {
            const pre = code.parentElement;
            pre.className = "mermaid";
            pre.textContent = code.textContent;
        });
        const nodes = container.querySelectorAll(".mermaid:not([data-processed])");
        if (nodes.length > 0) {
            mermaid.run({ nodes: [...nodes] });
        }
    }

    // ── DOM 操作 ──
    function appendUserMessage(text) {
        hideWelcome();
        const div = document.createElement("div");
        div.className = "message message-user";
        div.innerHTML = `<div class="message-content">${escapeHtml(text)}</div>`;
        $messages.appendChild(div);
        scrollToBottom();
    }

    function appendUserMessageWithImages(text, imageDataUrls) {
        hideWelcome();
        const div = document.createElement("div");
        div.className = "message message-user";
        let imagesHtml = "";
        if (imageDataUrls && imageDataUrls.length > 0) {
            imagesHtml = '<div class="user-images">';
            for (const url of imageDataUrls) {
                imagesHtml += `<img src="${url}" class="user-image-thumb" onclick="window._openLightbox(this.src)">`;
            }
            imagesHtml += "</div>";
        }
        div.innerHTML = `<div class="message-content">${escapeHtml(text)}${imagesHtml}</div>`;
        $messages.appendChild(div);
        scrollToBottom();
    }

    function appendAssistantMessage() {
        hideWelcome();
        const div = document.createElement("div");
        div.className = "message message-assistant";
        div.innerHTML = `<div class="message-content"></div>`;
        $messages.appendChild(div);
        scrollToBottom();
        return div;
    }

    let thinkingEl = null;

    function appendThinkingBlock(text) {
        hideWelcome();
        const div = document.createElement("div");
        div.className = "thinking-block";
        div.addEventListener("click", () => div.classList.toggle("expanded"));
        div.textContent = "💭 " + text;
        $messages.appendChild(div);
        scrollToBottom();
    }

    function appendThinking(text, beforeEl) {
        if (!showThinking) return;
        hideWelcome();
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
        hideWelcome();
        const div = document.createElement("div");
        div.className = "thinking-block expanded";
        div.textContent = "⏰ " + text;
        $messages.appendChild(div);
        scrollToBottom();
    }

    let pendingToolCalls = [];

    function appendToolCall(tool, summary, input) {
        hideWelcome();
        const div = document.createElement("div");
        div.className = "tool-call tool-pending";
        const summaryHtml = summary ? ` <span class="tool-sep">·</span> <span class="tool-summary">${escapeHtml(summary)}</span>` : "";
        div.innerHTML = `<span class="tool-spinner"></span><span class="tool-name">${escapeHtml(tool)}</span>${summaryHtml}<span class="tool-status"></span>`;
        div._input = input || {};
        div._tool = tool;
        div._toolId = (arguments[3]) || "";
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
        hideWelcome();
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
                return;
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
        const toolId = (arguments[3]) || "";
        let idx = -1;
        if (toolId) {
            for (let i = 0; i < pendingToolCalls.length; i++) {
                if (pendingToolCalls[i]._toolId === toolId) {
                    idx = i;
                    break;
                }
            }
        }
        if (idx === -1) {
            for (let i = 0; i < pendingToolCalls.length; i++) {
                if (pendingToolCalls[i]._tool === tool) {
                    idx = i;
                    break;
                }
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
            if (text && !["read_file", "list_files", "grep_search", "web_search", "web_fetch"].includes(tool)) {
                const preview = document.createElement("span");
                preview.className = "tool-result-preview";
                const p = text.replace(/\n/g, " ");
                preview.textContent = p.length > 100 ? p.slice(0, 100) + "..." : p;
                div.appendChild(preview);
            }
        }
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
        setTimeout(() => { div.style.opacity = "0.4"; }, 5000);
    }

    function appendError(text) {
        hideWelcome();
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

    let _scrollPending = false;
    let _userScrolledUp = false;
    function scrollToBottom(force = false) {
        if (_scrollPending) return;
        // 用户向上滚动查看历史时，不强制滚动到底部
        if (!force && _userScrolledUp) return;
        _scrollPending = true;
        requestAnimationFrame(() => { _scrollPending = false; if ($chatScroll) $chatScroll.scrollTop = $chatScroll.scrollHeight; });
    }

    const $scrollBottomBtn = document.getElementById("scroll-bottom-btn");
    if ($scrollBottomBtn && $chatScroll) {
        $scrollBottomBtn.addEventListener("click", () => scrollToBottom(true));
        $chatScroll.addEventListener("scroll", () => {
            const atBottom = $chatScroll.scrollHeight - $chatScroll.scrollTop - $chatScroll.clientHeight < 80;
            _userScrolledUp = !atBottom;
            $scrollBottomBtn.classList.toggle("hidden", atBottom);
        });
    }

    // ── 发送 ──
    function sendTask() {
        const text = $input.value.trim();
        const hasImages = pendingImages.length > 0;

        if (!text && !hasImages) return;

        if (text.startsWith("/") && !hasImages) {
            sendJSON({ action: "slash", text: text });
            $input.value = "";
            autoResize();
            hideAutocomplete();
            return;
        }

        if (hasImages) {
            for (const img of pendingImages) {
                const base64 = img.dataUrl.split(",")[1];
                sendJSON({
                    action: "send_image",
                    image: base64,
                    media_type: img.mediaType,
                });
            }
        }

        appendUserMessageWithImages(text, pendingImages.map(i => i.dataUrl));

        lastTask = text || "(图片)";
        // 新会话时，用第一条消息作为标题
        if (sessionTitle === "Octopus" && text) {
            updateSessionTitle(text.slice(0, 40));
        }
        busy = true;
        _userScrolledUp = false;
        updateButtons();
        $input.value = "";
        autoResize();
        hideAutocomplete();
        pendingImages = [];
        const previewBar = document.getElementById("image-preview-bar");
        if (previewBar) previewBar.innerHTML = "";
        sendJSON({ action: "task", text: text || "请查看我发送的图片" });
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
        updateButtons();
    }

    function autoResize() {
        $input.style.height = "auto";
        $input.style.height = Math.min($input.scrollHeight, 140) + "px";
    }

    function updateButtons() {
        const hasText = $input.value.trim().length > 0;
        $micBtn.classList.toggle("hidden", hasText || busy);
        $sendBtn.classList.toggle("hidden", busy || !hasText);
        $stopBtn.classList.toggle("hidden", !busy);
        $input.disabled = busy;
        $input.placeholder = busy ? "Agent 执行中..." : "输入任务或 / 命令...";
    }

    // ── 确认对话框（支持并发队列） ──
    function showConfirmDialog(confirmId, toolName, toolSummary) {
        if (pendingConfirmId) {
            confirmQueue.push({ confirmId, toolName, toolSummary });
            return;
        }
        pendingConfirmId = confirmId;
        pendingConfirmTool = toolName;
        $confirmTool.textContent = "🔧 " + toolName;
        $confirmInput.textContent = toolSummary || "";
        $confirmApproveAll.textContent = "允许所有 " + toolName;
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
        scrollToBottom(true);
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
        scrollToBottom(true);

        container.querySelectorAll(".ask-options .btn-approve").forEach(btn => {
            btn.addEventListener("click", () => {
                const label = options[parseInt(btn.dataset.idx)].label;
                resolveAsk(label);
                container.remove();
            });
        });
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
        $modeIndicator.textContent = planMode ? "plan" : "auto";
        $modeIndicator.className = "db-tool-btn" + (planMode ? " active" : "");
        $modeIndicator.title = "点击切换 Plan/Auto 模式";
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
                const images = blocks.filter(b => b.type === "image" && b.data_url).map(b => b.data_url);
                if (texts || images.length > 0) {
                    appendUserMessageWithImages(texts, images);
                }
            } else if (role === "assistant") {
                let currentTexts = [];
                blocks.forEach(block => {
                    try {
                        if (block.type === "thinking") {
                            if (currentTexts.length > 0) {
                                const el = appendAssistantMessage();
                                el.querySelector(".message-content").innerHTML = renderMarkdown(currentTexts.join("\n\n"));
                                highlightCode(el.querySelector(".message-content"));
                                renderMermaid(el.querySelector(".message-content"));
                                currentTexts = [];
                            }
                            appendThinkingBlock(block.thinking || "");
                        } else if (block.type === "text") {
                            currentTexts.push(block.text);
                        } else if (block.type === "tool_use") {
                            if (currentTexts.length > 0) {
                                const el = appendAssistantMessage();
                                el.querySelector(".message-content").innerHTML = renderMarkdown(currentTexts.join("\n\n"));
                                highlightCode(el.querySelector(".message-content"));
                                renderMermaid(el.querySelector(".message-content"));
                                currentTexts = [];
                            }
                            if (block.name === "edit_file" && block.input) {
                                appendEditDiff(block.input);
                            } else if (block.name === "multi_edit" && block.input) {
                                const edits = block.input.edits || [];
                                edits.forEach(edit => appendEditDiff(edit));
                            } else {
                                const div = appendToolCall(block.name || "", "", block.input || {}, block.tool_id || "");
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
                                    const details = document.createElement("div");
                                    details.className = "tool-details";
                                    details.style.display = "none";
                                    details.innerHTML =
                                        "<b>Input:</b>\n" + escapeHtml(JSON.stringify(block.input || {}, null, 2)) +
                                        "\n\n<b>Result:</b>\n" + escapeHtml(block.result || "(empty)") +
                                        "\n\n<i>Click to collapse</i>";
                                    div.appendChild(details);
                                    pendingToolCalls = pendingToolCalls.filter(el => el !== div);
                                }
                            }
                        }
                    } catch (e) {
                        console.warn("renderHistoryMessages block error:", e);
                    }
                });
                if (currentTexts.length > 0) {
                    const el = appendAssistantMessage();
                    el.querySelector(".message-content").innerHTML = renderMarkdown(currentTexts.join("\n\n"));
                    highlightCode(el.querySelector(".message-content"));
                    renderMermaid(el.querySelector(".message-content"));
                    currentTexts = [];
                }
            }
        });
        pendingToolCalls = [];
        scrollToBottom(true);
    }

    function renderSessions(sessions) {
        $sessionList.innerHTML = "";
        if (!sessions || !sessions.length) {
            $sessionList.innerHTML = '<div style="padding:12px;font-size:12px;color:var(--text-dim);text-align:center;">暂无会话</div>';
            return;
        }
        sessions = sessions.filter(s => s.name || s.first_message);
        sessions.forEach((s) => {
            const div = document.createElement("div");
            const isSelected = selectedSessions.has(s.session_id);
            div.className = "db-hist" +
                (s.session_id === sessionId ? " active" : "") +
                (isSelected ? " selected" : "");

            const name = s.name || s.first_message || s.session_id.slice(0, 8);
            div._sessionName = name;

            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.className = "db-hist-checkbox";
            cb.checked = isSelected;
            cb.addEventListener("click", (e) => {
                e.stopPropagation();
                if (cb.checked) selectedSessions.add(s.session_id);
                else selectedSessions.delete(s.session_id);
                updateDeleteCount();
            });

            const icon = document.createElement("i");
            icon.className = "ti ti-message";

            const textSpan = document.createElement("span");
            textSpan.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
            textSpan.textContent = name;

            div.appendChild(cb);
            div.appendChild(icon);
            div.appendChild(textSpan);

            if (!deleteMode) {
                div.addEventListener("click", () => resumeSession(s.session_id));
            }

            $sessionList.appendChild(div);
        });

        if (deleteMode) {
            $sessionList.classList.add("delete-mode");
        } else {
            $sessionList.classList.remove("delete-mode");
        }
    }

    function highlightSidebar() {
        $sessionList.querySelectorAll(".db-hist").forEach(el => el.style.background = "rgba(74,158,255,0.1)");
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
        if (ids.includes(sessionId)) {
            sendJSON({ action: "new_session", skip_save: true });
        }
        loadSessions();
    }

    // ── 会话标题 ──
    let sessionTitle = "Octopus";

    function updateSessionTitle(title) {
        if (title) sessionTitle = title;
        if ($sessionTitle) $sessionTitle.textContent = sessionTitle;
    }

    // ── 构建导出 HTML（HTML/PDF 共用） ──
    async function buildExportHTML() {
        const title = sessionTitle || "Octopus Session";
        const theme = document.documentElement.getAttribute("data-theme") || "light";

        let mainCSS = "";
        try {
            const resp = await fetch("/static/style.css?v=14");
            mainCSS = await resp.text();
        } catch (e) { /* ignore */ }

        const hlLight = document.getElementById("highlight-css-light");
        const hlDark = document.getElementById("highlight-css-dark");
        const hlLightHref = hlLight ? hlLight.href : "";
        const hlDarkHref = hlDark ? hlDark.href : "";

        const messagesHTML = $messages.innerHTML;

        return `<!DOCTYPE html>
<html lang="zh-CN"${theme === "dark" ? ' data-theme="dark"' : ""}>
<head>
<meta charset="UTF-8">
<title>${escapeHtml(title)}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.19.0/dist/tabler-icons.min.css">
<link rel="stylesheet" href="${hlLightHref}">
<link rel="stylesheet" href="${hlDarkHref}" disabled>
<style>${mainCSS}</style>
<style>
  html, body { height: auto !important; overflow: visible !important; }
  .db-root { height: auto !important; }
  .db-main { background: var(--bg-main); overflow: visible !important; }
  .db-chat { overflow: visible !important; max-height: none !important; flex: auto !important; }
  .db-welcome { display: none !important; }
</style>
</head>
<body>
<div class="db-root">
  <div class="db-main">
    <div class="db-chat">
      <div id="messages">${messagesHTML}</div>
    </div>
  </div>
</div>
</body>
</html>`;
    }

    // ── 导出 HTML ──
    async function exportAsHTML() {
        const html = await buildExportHTML();
        downloadFile(html, `session_${sessionId ? sessionId.slice(0, 8) : "export"}.html`, "text/html");
    }

    // ── 导出 PDF（隐藏 iframe 直接打印） ──
    async function exportAsPDF() {
        const html = await buildExportHTML();
        const iframe = document.createElement("iframe");
        iframe.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;border:none;z-index:9999;";
        // 临时设为可见以确保 print 能正确渲染
        document.body.appendChild(iframe);
        iframe.srcdoc = html;
        iframe.addEventListener("load", () => {
            try {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
            } catch (e) {
                showSystem("PDF 导出失败: " + e.message);
            }
            // 打印对话框关闭后移除 iframe
            setTimeout(() => {
                document.body.removeChild(iframe);
            }, 1000);
        });
    }

    // ── 文件下载 ──
    function downloadFile(content, filename, mimeType = "text/plain;charset=utf-8") {
        const blob = new Blob([content], { type: mimeType });
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
        // $modelInfo 是左下角用户名，不覆盖
        if ($modelBtnText) $modelBtnText.textContent = model || "选择模型";
        $modelBtn.title = "切换模型: " + model;
        if ($agentLabel) $agentLabel.textContent = currentAgent ? `· ${currentAgent}` : "";
    }

    function updateTokenBar(usage) {
        const turnTotal = (usage.input_tokens || 0) + (usage.output_tokens || 0);
        const sessionTotal = sessionTokens.input + sessionTokens.output;
        $tokenBar.textContent = `Tokens: ↑${usage.output_tokens || 0} ↓${usage.input_tokens || 0} · ${turnTotal} turn · ${sessionTotal} session`;
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

    // ── 图片附件 ──

    let pendingImages = [];

    function handleImageFile(file) {
        if (!file.type.startsWith("image/")) {
            showSystem("仅支持图片文件");
            return;
        }
        if (file.size > 20 * 1024 * 1024) {
            showSystem("图片不能超过 20MB");
            return;
        }
        const reader = new FileReader();
        reader.onload = (e) => {
            const dataUrl = e.target.result;
            pendingImages.push({ dataUrl, mediaType: file.type || "image/png" });
            renderImagePreview();
        };
        reader.readAsDataURL(file);
    }

    function handlePaste(e) {
        const items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith("image/")) {
                e.preventDefault();
                const file = item.getAsFile();
                if (file) handleImageFile(file);
                return;
            }
        }
    }

    function handleDrop(e) {
        e.preventDefault();
        e.stopPropagation();
        const files = e.dataTransfer && e.dataTransfer.files;
        if (!files) return;
        for (const file of files) {
            if (file.type.startsWith("image/")) {
                handleImageFile(file);
            }
        }
    }

    function renderImagePreview() {
        let container = document.getElementById("image-preview-bar");
        if (!container) return;
        container.innerHTML = "";
        pendingImages.forEach((img, idx) => {
            const thumb = document.createElement("div");
            thumb.className = "preview-thumb";
            thumb.innerHTML = `<img src="${img.dataUrl}">
                <button class="preview-remove" data-idx="${idx}">✕</button>`;
            thumb.querySelector("button").addEventListener("click", () => {
                pendingImages.splice(idx, 1);
                renderImagePreview();
            });
            container.appendChild(thumb);
        });
    }

    // ── 主题 ──
    function applyTheme() {
        document.documentElement.setAttribute("data-theme", darkMode ? "dark" : "light");
        const lightCss = document.getElementById("highlight-css-light");
        const darkCss = document.getElementById("highlight-css-dark");
        if (lightCss) lightCss.disabled = darkMode;
        if (darkCss) darkCss.disabled = !darkMode;
        if ($themeToggle) {
            const icon = $themeToggle.querySelector("i");
            if (icon) {
                icon.className = darkMode ? "ti ti-moon" : "ti ti-sun";
            }
        }
        // Monaco 主题跟随
        if (monacoEditor && typeof monaco !== "undefined" && monaco.editor) {
            monaco.editor.setTheme(darkMode ? "vs-dark" : "vs");
        }
        // 终端主题跟随
        if (terminalInstance) {
            const isDark = darkMode;
            terminalInstance.options.theme = {
                background: isDark ? "#1e1e32" : "#ffffff",
                foreground: isDark ? "#e0e0e0" : "#1a1a1a",
                cursor: isDark ? "#e0e0e0" : "#1a1a1a",
                selectionBackground: isDark ? "#3a3a5e" : "#d0d0f0",
                black: "#1a1a1a", red: "#e34c4c", green: "#6bbf4a", yellow: "#dbb33d",
                blue: "#4a6ff5", magenta: "#c04ad0", cyan: "#3bc7b8", white: "#d0d0d0",
                brightBlack: "#666", brightRed: "#f07070",
                brightGreen: "#80d070", brightYellow: "#e0c050",
                brightBlue: "#7080f0", brightMagenta: "#d070e0",
                brightCyan: "#60d0c0", brightWhite: "#f0f0f0",
            };
        }
    }

    function toggleTheme() {
        darkMode = !darkMode;
        localStorage.setItem("octopus_theme", darkMode ? "dark" : "light");
        applyTheme();
    }

    // ── 侧边栏折叠 ──
    function toggleSidebar() {
        $sidebar.classList.toggle("collapsed");
        $sidebarExpand.classList.toggle("hidden", !$sidebar.classList.contains("collapsed"));
    }

    // ── 启动 ──
    document.addEventListener("DOMContentLoaded", () => {
        init();
        if ($sidebarToggle) $sidebarToggle.addEventListener("click", toggleSidebar);
        if ($sidebarExpand) $sidebarExpand.addEventListener("click", toggleSidebar);
        window.addEventListener("beforeunload", () => {
            if (ws) ws.close(1000, "page unload");
        });
    });
})();
