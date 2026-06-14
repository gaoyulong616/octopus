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
    let showThinking = false;
    let showTools = false;
    let terminalOpen = false;
    let terminalInstance = null;
    let terminalFit = null;
    let terminalWS = null;
    let _savedTitle = "Octopus";
    let fileBrowserMode = false;
    let fbCurrentPath = "";
    let monacoEditor = null;
    let monacoLoaded = false;
    let fbPendingOpenQueue = [];
    let fbSelectedPaths = new Set();
    let fbLastClickedPath = "";

    function fbClearSelection() {
        document.querySelectorAll(".fb-tree .fb-node.active").forEach(el => el.classList.remove("active"));
        fbSelectedPaths.clear();
    }
    function fbSelectNode(node) {
        node.classList.add("active");
        fbSelectedPaths.add(node.dataset.path);
    }
    function fbDeselectNode(node) {
        node.classList.remove("active");
        fbSelectedPaths.delete(node.dataset.path);
    }
    function fbGetSiblingNodes(scopeNode) {
        // Get all visible fb-node siblings in the same container
        const parent = scopeNode.parentElement;
        if (!parent) return [];
        return Array.from(parent.querySelectorAll(":scope > .fb-node"));
    }
    function fbShiftSelect(fromPath, toPath, container) {
        // Find nodes between fromPath and toPath within container
        const allNodes = container
            ? Array.from(container.querySelectorAll(".fb-node"))
            : Array.from($fbTree.querySelectorAll(".fb-node"));
        const fromIdx = allNodes.findIndex(n => n.dataset.path === fromPath);
        const toIdx = allNodes.findIndex(n => n.dataset.path === toPath);
        if (fromIdx < 0 || toIdx < 0) return;
        const start = Math.min(fromIdx, toIdx);
        const end = Math.max(fromIdx, toIdx);
        for (let i = start; i <= end; i++) {
            fbSelectNode(allNodes[i]);
        }
    }

    // ── Tab 系统 ──
    let fbOpenTabs = []; // [{ path, name, content, language, dirty, encoding, eol, viewState, size }]
    let fbActiveTabIndex = -1;
    let suppressDirtyCheck = false;
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
    const $thinkingToggle = document.getElementById("thinking-toggle");
    const $toolsToggle = document.getElementById("tools-toggle");
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
    const $fbRefresh = document.getElementById("fb-refresh");
    const $fbReset = document.getElementById("fb-reset");
    const $editorContainer = document.getElementById("editor-container");
    const $monacoEl = document.getElementById("monaco-editor");
    const $editorTabsBar = document.getElementById("editor-tabs-bar");
    const $editorTabsScroll = document.getElementById("editor-tabs-scroll");
    const $resizeHandle = document.getElementById("sidebar-resize-handle");

    // 编辑器工具栏 DOM
    const $edSave = document.getElementById("ed-save");
    const $edUndo = document.getElementById("ed-undo");
    const $edRedo = document.getElementById("ed-redo");
    const $edLangBtn = document.getElementById("ed-lang-btn");
    const $edLangLabel = document.getElementById("ed-lang-label");
    const $edLangMenu = document.getElementById("ed-lang-menu");
    const $edFormat = document.getElementById("ed-format");
    const $edMinimap = document.getElementById("ed-minimap");
    const $edFontUp = document.getElementById("ed-font-up");
    const $edFontDown = document.getElementById("ed-font-down");
    const $edTabsizeBtn = document.getElementById("ed-tabsize-btn");
    const $edTabsizeLabel = document.getElementById("ed-tabsize-label");
    const $edTabsizeMenu = document.getElementById("ed-tabsize-menu");
    const $edEncodingBtn = document.getElementById("ed-encoding-btn");
    const $edEncodingLabel = document.getElementById("ed-encoding-label");
    const $edEncodingMenu = document.getElementById("ed-encoding-menu");
    const $edEolBtn = document.getElementById("ed-eol-btn");
    const $edEolLabel = document.getElementById("ed-eol-label");
    const $edEolMenu = document.getElementById("ed-eol-menu");
    const $edFind = document.getElementById("ed-find");
    const $edReplace = document.getElementById("ed-replace");
    const $edWordwrap = document.getElementById("ed-wordwrap");
    const $edColumn = document.getElementById("ed-column");
    const $edGotoline = document.getElementById("ed-gotoline");
    const $edComment = document.getElementById("ed-comment");
    const $edCaseBtn = document.getElementById("ed-case-btn");
    const $edCaseMenu = document.getElementById("ed-case-menu");
    const $edTabLeft = document.getElementById("ed-tab-left");
    const $edTabRight = document.getElementById("ed-tab-right");
    // 状态栏 DOM
    const $sbCursor = document.getElementById("sb-cursor");
    const $sbSelection = document.getElementById("sb-selection");
    const $sbEncoding = document.getElementById("sb-encoding");
    const $sbEol = document.getElementById("sb-eol");
    const $sbLang = document.getElementById("sb-lang");
    const $sbIndent = document.getElementById("sb-indent");
    const $sbSize = document.getElementById("sb-size");

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
        $thinkingToggle.addEventListener("click", () => {
            showThinking = !showThinking;
            $thinkingToggle.classList.toggle("active", showThinking);
            document.querySelectorAll(".thinking-block").forEach(el => {
                el.style.display = showThinking ? "" : "none";
            });
        });
        $toolsToggle.addEventListener("click", () => {
            showTools = !showTools;
            $toolsToggle.classList.toggle("active", showTools);
            document.querySelectorAll(".tool-call, .edit-diff").forEach(el => {
                el.style.display = showTools ? "" : "none";
            });
        });
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
                const view = this.dataset.view;
                const isChat = this.id === "nav-chat";
                if (view === "filebrowser") {
                    // 文件浏览器：切换模式
                    if (!fileBrowserMode) {
                        document.querySelectorAll(".db-nav-item").forEach(el => el.classList.remove("act"));
                        this.classList.add("act");
                        toggleFileBrowser(true);
                    }
                    return;
                }
                // 非文件：关闭文件浏览器模式
                if (fileBrowserMode) toggleFileBrowser(false);
                document.querySelectorAll(".db-nav-item").forEach(el => el.classList.remove("act"));
                this.classList.add("act");
                // 只有"对话"模式下启用新对话和搜索
                updateChatControlsState(isChat);
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
        if ($fbRefresh) $fbRefresh.addEventListener("click", () => { if (fbCurrentPath) loadFileTree(fbCurrentPath); });
        if ($fbReset) $fbReset.addEventListener("click", () => { if (cwd) { fbCurrentPath = ""; loadFileTree(cwd); } });
        // 编辑器工具栏事件
        const $edNew = document.getElementById("ed-new");
        const $edOpen = document.getElementById("ed-open");
        if ($edNew) $edNew.addEventListener("click", createUntitledTab);
        if ($edOpen) $edOpen.addEventListener("click", showOpenFileDialog);
        if ($edSave) $edSave.addEventListener("click", saveCurrentFile);
        const $edSaveAs = document.getElementById("ed-saveas");
        if ($edSaveAs) $edSaveAs.addEventListener("click", () => {
            const tab = getActiveTab();
            if (!tab || !monacoEditor) return;
            tab.content = monacoEditor.getValue();
            showSaveAsDialog(tab, getActiveDirPath() || cwd || "");
        });
        if ($edUndo) $edUndo.addEventListener("click", () => { if (monacoEditor) monacoEditor.trigger("toolbar", "undo"); });
        if ($edRedo) $edRedo.addEventListener("click", () => { if (monacoEditor) monacoEditor.trigger("toolbar", "redo"); });
        if ($edFormat) $edFormat.addEventListener("click", formatDocument);
        if ($edMinimap) $edMinimap.addEventListener("click", toggleMinimap);
        if ($edFontUp) $edFontUp.addEventListener("click", () => changeFontSize(1));
        if ($edFontDown) $edFontDown.addEventListener("click", () => changeFontSize(-1));
        if ($edFind) $edFind.addEventListener("click", () => { if (monacoEditor) monacoEditor.trigger("toolbar", "actions.find"); });
        if ($edReplace) $edReplace.addEventListener("click", () => { if (monacoEditor) monacoEditor.trigger("toolbar", "editor.action.startFindReplaceAction"); });
        if ($edComment) $edComment.addEventListener("click", () => { if (monacoEditor) monacoEditor.trigger("toolbar", "editor.action.commentLine"); });
        if ($edCaseBtn && $edCaseMenu) setupDropdown($edCaseBtn, $edCaseMenu, onCaseSelect);
        if ($edWordwrap) $edWordwrap.addEventListener("click", toggleWordWrap);
        if ($edColumn) $edColumn.addEventListener("click", toggleColumnMode);
        if ($edGotoline) $edGotoline.addEventListener("click", showGoToLine);
        const $edDiff = document.getElementById("ed-diff");
        if ($edDiff) $edDiff.addEventListener("click", toggleDiffView);
        const $edCloseAll = document.getElementById("ed-close-all");
        if ($edCloseAll) $edCloseAll.addEventListener("click", closeAllTabs);
        if ($edTabLeft) $edTabLeft.addEventListener("click", () => $editorTabsScroll.scrollBy({ left: -150, behavior: "smooth" }));
        if ($edTabRight) $edTabRight.addEventListener("click", () => $editorTabsScroll.scrollBy({ left: 150, behavior: "smooth" }));
        // 下拉菜单
        setupDropdown($edLangBtn, $edLangMenu, onLangSelect);
        setupDropdown($edTabsizeBtn, $edTabsizeMenu, onTabSizeSelect);
        setupDropdown($edEncodingBtn, $edEncodingMenu, onEncodingSelect);
        setupDropdown($edEolBtn, $edEolMenu, onEolSelect);
        // Tab 栏滚动检测
        if ($editorTabsScroll) {
            $editorTabsScroll.addEventListener("scroll", updateTabArrows);
            new ResizeObserver(updateTabArrows).observe($editorTabsScroll);
        }

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
                removeLoadingDots();
                streamBuffer += text;
                scheduleRender();
                break;

            case "thinking":
                const thinkBeforeEl = currentAssistantEl;
                flushStream();
                hideWelcome();
                if (text) { appendThinking(text, thinkBeforeEl); showLoadingDots(); }
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
                showLoadingDots();
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
                removeLoadingDots();
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
                removeLoadingDots();
                hideWelcome();
                appendError(text);
                break;

            case "truncated":
                flushStream();
                showSystem("✂️ " + text);
                break;

            case "stream_rewind":
                flushStream();
                streamBuffer = "";
                showSystem("↻ " + (text || "重试中，清空之前的输出"));
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
                    showSystem(text);
                }
                break;

            case "agent_changed":
                currentAgent = (meta.name && meta.name !== "default") ? meta.name : null;
                updateModelInfo();
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
                currentAgent = (meta.agent && meta.agent !== "default") ? meta.agent : null;
                updateModelInfo();
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
                exportFile(text, meta.filename || "export.txt");
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
        const $topbar = document.querySelector(".db-topbar");
        const $inputArea = document.querySelector(".db-input-area");
        if (open) {
            if (!_savedTitle || _savedTitle === "Octopus") {
                _savedTitle = $sessionTitle.textContent;
            }

            $chatScroll.classList.add("hidden");
            $terminalContainer.classList.remove("active");
            $editorContainer.classList.add("active");
            if ($topbar) $topbar.style.display = "none";
            if ($inputArea) $inputArea.classList.add("hidden");
            if ($terminalBtn) $terminalBtn.classList.add("hidden");
            if (terminalOpen) {
                terminalOpen = false;
                $terminalBtn.classList.remove("active");
                disconnectTerminalWS();
            }

            // 隐藏会话列表，显示文件浏览器
            const $sectionLabel = document.querySelector(".db-section-label");
            if ($sectionLabel) $sectionLabel.style.display = "none";
            $sessionList.style.display = "none";
            $deleteBar.style.display = "none";
            $fbSection.classList.remove("hidden");

            // 禁用新对话和搜索
            updateChatControlsState(false);

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
            if ($topbar) $topbar.style.display = "";
            if ($inputArea) $inputArea.classList.remove("hidden");
            if ($terminalBtn) $terminalBtn.classList.remove("hidden");
            $sessionTitle.textContent = _savedTitle || "Octopus";
            $sessionTitle.classList.remove("multi");

            const $sectionLabel = document.querySelector(".db-section-label");
            if ($sectionLabel) $sectionLabel.style.display = "";
            $sessionList.style.display = "";
            $deleteBar.style.display = "";
            $fbSection.classList.add("hidden");

            // 启用新对话和搜索
            updateChatControlsState(true);
        }
    }

    function updateChatControlsState(enabled) {
        if ($newSessionBtn) {
            $newSessionBtn.disabled = !enabled;
            $newSessionBtn.style.opacity = enabled ? "" : "0.4";
            $newSessionBtn.style.pointerEvents = enabled ? "" : "none";
        }
        if ($sessionSearch) {
            $sessionSearch.disabled = !enabled;
            $sessionSearch.style.opacity = enabled ? "" : "0.4";
            $sessionSearch.style.pointerEvents = enabled ? "" : "none";
        }
    }

    function updateFileBrowserTitle() {
        // 顶栏已隐藏，标题行由编辑器自身显示
    }

    let fbAnimating = false;
    function loadFileTree(dirPath, callback, direction) {
        updateFileBrowserTitle();
        fbCurrentPath = dirPath;
        fbClearSelection();
        fbLastClickedPath = "";

        if (direction && $fbTree && !fbAnimating) {
            // 翻页动画
            fbAnimating = true;
            const outClass = direction === "left" ? "fb-slide-out-left" : "fb-slide-out-right";
            const inClass  = direction === "left" ? "fb-slide-in-right" : "fb-slide-in-left";
            $fbTree.classList.add(outClass);
            $fbTree.addEventListener("animationend", function handler() {
                $fbTree.removeEventListener("animationend", handler);
                $fbTree.classList.remove(outClass);
                // 加载新内容
                doLoadTree(dirPath, callback, () => {
                    $fbTree.classList.add(inClass);
                    $fbTree.addEventListener("animationend", function h2() {
                        $fbTree.removeEventListener("animationend", h2);
                        $fbTree.classList.remove(inClass);
                        fbAnimating = false;
                    });
                });
            });
        } else {
            $fbTree.innerHTML = '<div class="fb-loading">加载中...</div>';
            doLoadTree(dirPath, callback, null);
        }
    }
    function doLoadTree(dirPath, callback, onReady) {
        const token = sessionStorage.getItem("octopus_token");
        fetch(`/api/files?path=${encodeURIComponent(dirPath)}&token=${token}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    $fbTree.innerHTML = `<div class="fb-error">${escapeHtml(data.error)}</div>`;
                    fbAnimating = false;
                    return;
                }
                renderFileTree(data.entries, $fbTree, 0);
                if (onReady) onReady();
                if (callback) callback();
            })
            .catch(err => {
                $fbTree.innerHTML = `<div class="fb-error">加载失败: ${escapeHtml(err.message)}</div>`;
                fbAnimating = false;
            });
    }

    // 展开指定父目录的节点，并选中指定的子路径
    function expandAndSelect(parentDirPath, targetPath) {
        const dirNode = $fbTree.querySelector(`.fb-node[data-path="${CSS.escape(parentDirPath)}"]`);
        if (!dirNode) {
            // 父目录节点不在 DOM 中，尝试先加载并展开其父级
            const grandParent = parentDirPath.substring(0, parentDirPath.lastIndexOf("/"));
            if (grandParent) {
                expandAndSelect(grandParent, parentDirPath);
                // 等待异步加载后重试
                setTimeout(() => expandAndSelect(parentDirPath, targetPath), 500);
            }
            return;
        }
        const children = dirNode.querySelector(".fb-children");
        if (!children) return;
        // 展开父目录
        children.classList.add("open");
        children.dataset.loaded = "true";
        const toggle = dirNode.querySelector(".fb-toggle");
        if (toggle) toggle.classList.add("open");
        // 加载子项（如果还没加载）
        const token = sessionStorage.getItem("octopus_token");
        fetch(`/api/files?path=${encodeURIComponent(parentDirPath)}&token=${token}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) return;
                children.innerHTML = "";
                const depth = (parseInt((dirNode.style.paddingLeft || "12").replace("px", "")) - 12) / 16 + 1;
                (data.entries || []).forEach(entry => {
                    const node = createFileNode(entry, depth);
                    children.appendChild(node);
                    // 选中新创建的项
                    if (entry.path === targetPath) {
                        fbClearSelection();
                        fbSelectNode(node);
                        fbLastClickedPath = targetPath;
                        node.scrollIntoView({ behavior: "smooth", block: "nearest" });
                    }
                });
            });
    }

    function renderFileTree(entries, container, depth) {
        container.innerHTML = "";
        if (!entries || entries.length === 0) {
            container.innerHTML = '<div class="fb-empty">空目录</div>';
            return;
        }
        // Add ".." for parent dir — 导航到上级，不是展开
        if (depth === 0 && fbCurrentPath !== "/") {
            const up = document.createElement("div");
            up.className = "fb-node fb-dir";
            up.style.paddingLeft = (12 + depth * 16) + "px";
            const parentName = fbCurrentPath.split("/").filter(Boolean).pop() || "/";
            up.innerHTML = '<span class="fb-toggle" style="width:14px;flex-shrink:0;display:inline-block"></span><span class="fb-icon" style="color:var(--accent-yellow);font-weight:600;font-size:13px">.. <span style="color:var(--text-dim);font-weight:400;font-size:11px">(' + escapeHtml(parentName) + ')</span></span>';
            up.addEventListener("dblclick", function (e) {
                e.stopPropagation();
                loadFileTree(parentPath(fbCurrentPath), null, "right");
            });
            container.appendChild(up);
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
                if (div.dataset.renaming === "true") return;
                e.stopPropagation();
                if (e.ctrlKey || e.metaKey) {
                    // Ctrl/Cmd: toggle selection without affecting others, don't toggle expand
                    if (div.classList.contains("active")) {
                        fbDeselectNode(div);
                    } else {
                        fbSelectNode(div);
                    }
                    fbLastClickedPath = entry.path;
                } else if (e.shiftKey && fbLastClickedPath) {
                    // Shift: range select, don't toggle expand
                    fbClearSelection();
                    fbShiftSelect(fbLastClickedPath, entry.path, null);
                    fbLastClickedPath = entry.path;
                } else {
                    // Normal: toggle expand and single select
                    fbClearSelection();
                    const isOpen = toggle.classList.toggle("open");
                    childrenContainer.classList.toggle("open");
                    if (isOpen) {
                        fbSelectNode(div);
                        if (childrenContainer.dataset.loaded === "false") {
                            loadDirChildren(entry.path, childrenContainer, depth + 1);
                        }
                    }
                    fbLastClickedPath = entry.path;
                }
            });
            div.addEventListener("dblclick", (e) => {
                e.stopPropagation();
                loadFileTree(entry.path, null, "left");
            });
            div.addEventListener("contextmenu", (e) => {
                if (div.dataset.renaming === "true") return;
                e.preventDefault();
                e.stopPropagation();
                hideContextMenu();
                if (!div.classList.contains("active")) return; // 未选中不弹菜单
                // 多选状态：只弹出批量删除
                if (fbSelectedPaths.size > 1) {
                    const names = Array.from(document.querySelectorAll(".fb-tree .fb-node.active"))
                        .map(n => n.querySelector(".fb-name")?.textContent || n.dataset.path.split("/").pop())
                        .filter(Boolean);
                    const label = names.length <= 3
                        ? names.map(n => `「${n}」`).join("、")
                        : `「${names[0]}」等 ${names.length} 个`;
                    showContextMenu([
                        { label: `删除 ${label}`, icon: "ti ti-trash", danger: true, action: () => batchDelete() },
                    ], e.clientX, e.clientY);
                    return;
                }
                const items = [
                    { label: "新文件", icon: "ti ti-file-plus", action: () => createNewEntry(entry.path, "file") },
                    { label: "新文件夹", icon: "ti ti-folder-plus", action: () => createNewEntry(entry.path, "dir") },
                    { separator: true },
                    { label: "上传", icon: "ti ti-upload", action: () => uploadToDir(entry.path) },
                    { label: "重命名", icon: "ti ti-typography", action: () => renameNode(div, entry) },
                    { separator: true },
                    { label: "删除", icon: "ti ti-trash", danger: true, action: () => deletePath(entry.path, entry.name, true) },
                ];
                showContextMenu(items, e.clientX, e.clientY);
            });
        } else {
            // 单击选中，双击打开
            div.addEventListener("click", (e) => {
                if (div.dataset.renaming === "true") return;
                e.stopPropagation();
                if (e.ctrlKey || e.metaKey) {
                    // Ctrl/Cmd: toggle
                    if (div.classList.contains("active")) {
                        fbDeselectNode(div);
                    } else {
                        fbSelectNode(div);
                    }
                    fbLastClickedPath = entry.path;
                } else if (e.shiftKey && fbLastClickedPath) {
                    // Shift: range select
                    fbClearSelection();
                    fbShiftSelect(fbLastClickedPath, entry.path, null);
                    fbLastClickedPath = entry.path;
                } else {
                    // Normal: single select
                    fbClearSelection();
                    fbSelectNode(div);
                    fbLastClickedPath = entry.path;
                }
            });
            div.addEventListener("dblclick", (e) => {
                e.stopPropagation();
                openFileInEditor(entry.path);
            });
            div.addEventListener("contextmenu", (e) => {
                if (div.dataset.renaming === "true") return;
                e.preventDefault();
                e.stopPropagation();
                hideContextMenu();
                if (!div.classList.contains("active")) return; // 未选中不弹菜单
                // 多选状态：只弹出批量删除
                if (fbSelectedPaths.size > 1) {
                    const names = Array.from(document.querySelectorAll(".fb-tree .fb-node.active"))
                        .map(n => n.querySelector(".fb-name")?.textContent || n.dataset.path.split("/").pop())
                        .filter(Boolean);
                    const label = names.length <= 3
                        ? names.map(n => `「${n}」`).join("、")
                        : `「${names[0]}」等 ${names.length} 个`;
                    showContextMenu([
                        { label: `删除 ${label}`, icon: "ti ti-trash", danger: true, action: () => batchDelete() },
                    ], e.clientX, e.clientY);
                    return;
                }
                const items = [
                    { label: "下载", icon: "ti ti-download", action: () => downloadFile(entry.path) },
                    { label: "编辑", icon: "ti ti-edit", action: () => editFileConfirm(entry) },
                    { label: "重命名", icon: "ti ti-typography", action: () => renameNode(div, entry) },
                    { separator: true },
                    { label: "删除", icon: "ti ti-trash", danger: true, action: () => deletePath(entry.path, entry.name, false) },
                ];
                showContextMenu(items, e.clientX, e.clientY);
            });
        }

        return div;
    }

    function loadDirChildren(dirPath, container, depth) {
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

    // ── 文件浏览器右键菜单与操作 ──
    let fbContextMenu = null;

    function showContextMenu(items, x, y) {
        hideContextMenu();
        // 同时关闭编辑器下拉菜单
        document.querySelectorAll(".ed-dropdown").forEach(m => m.classList.add("hidden"));
        const menu = document.createElement("div");
        menu.className = "fb-context-menu";
        items.forEach(item => {
            if (item.separator) {
                const sep = document.createElement("div");
                sep.className = "fb-context-menu-sep";
                menu.appendChild(sep);
            } else {
                const el = document.createElement("div");
                el.className = "fb-context-menu-item" + (item.danger ? " danger" : "");
                el.innerHTML = `<i class="${item.icon}"></i>${item.label}`;
                el.addEventListener("click", (e) => {
                    e.stopPropagation();
                    hideContextMenu();
                    item.action();
                });
                menu.appendChild(el);
            }
        });
        document.body.appendChild(menu);
        // Position — keep within viewport
        requestAnimationFrame(() => {
            const rect = menu.getBoundingClientRect();
            menu.style.left = Math.min(x, window.innerWidth - rect.width - 10) + "px";
            menu.style.top = Math.min(y, window.innerHeight - rect.height - 10) + "px";
        });
        fbContextMenu = menu;
    }

    function hideContextMenu() {
        if (fbContextMenu) {
            fbContextMenu.remove();
            fbContextMenu = null;
        }
    }

    function showToast(msg) {
        let el = document.querySelector(".fb-toast");
        if (!el) {
            el = document.createElement("div");
            el.className = "fb-toast";
            document.body.appendChild(el);
        }
        el.textContent = msg;
        el.classList.add("show");
        clearTimeout(el._hideTimer);
        el._hideTimer = setTimeout(() => el.classList.remove("show"), 2000);
    }

    function showGeneralConfirm(title, message, onOk) {
        $confirmTitle.textContent = title;
        $confirmMessage.textContent = message;
        $generalConfirm.classList.remove("hidden");
        const cleanup = () => { $generalConfirm.classList.add("hidden"); };
        const handleOk = () => { cleanup(); if (onOk) onOk(); };
        const handleCancel = () => { cleanup(); };
        $confirmOkBtn.onclick = handleOk;
        $confirmCancelBtn.onclick = handleCancel;
    }

    function downloadFile(path) {
        showToast("下载: " + path);
        const token = sessionStorage.getItem("octopus_token");
        const filename = path.split("/").pop() || "file";
        // 使用 fetch 获取 blob，创建 object URL 触发下载
        fetch(`/api/file/download?path=${encodeURIComponent(path)}&token=${token}`)
            .then(r => {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.blob();
            })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                a.remove();
                // 不释放 URL，让浏览器完成下载后再由 GC 回收
            })
            .catch(err => {
                showToast("下载失败: " + err.message);
            });
    }

    function deletePath(path, name, isDir) {
        const label = isDir ? "删除目录" : "删除文件";
        const msg = isDir
            ? `确定要永久删除目录「${name}」及其所有内容吗？此操作不可撤销。`
            : `确定要永久删除「${name}」吗？此操作不可撤销。`;

        showConfirm(label, msg).then(ok => {
            if (!ok) return;
            const token = sessionStorage.getItem("octopus_token");
            $fbTree.innerHTML = '<div class="fb-loading">删除中...</div>';
            fetch(`/api/file?path=${encodeURIComponent(path)}&token=${token}`, { method: "DELETE" })
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        showToast("删除失败: " + data.error);
                        loadFileTree(fbCurrentPath);
                        return;
                    }
                    closeTabsForDeletedPath(path);
                    loadFileTree(fbCurrentPath);
                })
                .catch(err => {
                    showToast("删除失败: " + err.message);
                    loadFileTree(fbCurrentPath);
                });
        });
    }

    // 关闭被删除路径关联的编辑器 Tab
    function closeTabsForDeletedPath(deletedPath) {
        const toClose = [];
        fbOpenTabs.forEach((tab, idx) => {
            if (tab.path && (tab.path === deletedPath || tab.path.startsWith(deletedPath + "/"))) {
                toClose.push(idx);
            }
        });
        // 从后往前关闭，避免索引偏移；脏 tab 标记为不脏（文件已删除，无需保存）
        for (let i = toClose.length - 1; i >= 0; i--) {
            const tab = fbOpenTabs[toClose[i]];
            if (tab) tab.dirty = false;
            doCloseTab(toClose[i]);
        }
    }

    function batchDelete() {
        const activeNodes = Array.from(document.querySelectorAll(".fb-tree .fb-node.active"));
        if (activeNodes.length === 0) return;
        // 收集路径，过滤掉是其他选中项子路径的项（避免重复删除）
        let paths = activeNodes.map(n => n.dataset.path);
        paths = paths.filter(p => !paths.some(other => other !== p && p.startsWith(other + "/")));
        const names = paths.map(p => p.split("/").pop());
        const label = names.length <= 3
            ? names.map(n => `「${n}」`).join("、")
            : `「${names[0]}」等 ${names.length} 个`;
        showConfirm("批量删除", `确定要永久删除 ${label} 吗？此操作不可撤销。`).then(ok => {
            if (!ok) return;
            const token = sessionStorage.getItem("octopus_token");
            $fbTree.innerHTML = '<div class="fb-loading">删除中...</div>';
            // 按路径深度降序排列（深层优先），串行删除避免并发冲突
            paths.sort((a, b) => b.split("/").length - a.split("/").length);
            const deletedPaths = [];
            let errorCount = 0;
            paths.reduce((prev, path) =>
                prev.then(() =>
                    fetch(`/api/file?path=${encodeURIComponent(path)}&token=${token}`, { method: "DELETE" })
                        .then(r => r.json())
                        .then(data => {
                            if (data.error) { errorCount++; }
                            else { deletedPaths.push(path); }
                        })
                ),
                Promise.resolve()
            ).then(() => {
                if (errorCount > 0) showToast(`${errorCount} 项删除失败`);
                fbClearSelection();
                deletedPaths.forEach(p => closeTabsForDeletedPath(p));
                loadFileTree(fbCurrentPath);
            }).catch(() => {
                showToast("批量删除失败");
                deletedPaths.forEach(p => closeTabsForDeletedPath(p));
                loadFileTree(fbCurrentPath);
            });
        });
    }

    function editFileConfirm(entry) {
        openFileInEditor(entry.path);
    }

    function renameNode(node, entry) {
        const nameSpan = node.querySelector(".fb-name");
        if (!nameSpan) return;
        const oldName = entry.name;
        const oldPath = entry.path;

        const input = document.createElement("input");
        input.type = "text";
        input.className = "fb-rename-input";
        input.value = oldName;
        input.setSelectionRange(0, oldName.lastIndexOf(".") >= 0 ? oldName.lastIndexOf(".") : oldName.length);

        nameSpan.replaceWith(input);
        input.focus();
        node.dataset.renaming = "true";

        function cancelRename() {
            const span = document.createElement("span");
            span.className = "fb-name";
            span.textContent = oldName;
            input.replaceWith(span);
            delete node.dataset.renaming;
        }

        function submitRename() {
            const newName = input.value.trim();
            if (!newName || newName === oldName) {
                cancelRename();
                return;
            }
            if (/[/\\]/.test(newName)) {
                showToast("名称不能包含 / 或 \\");
                return;
            }
            const token = sessionStorage.getItem("octopus_token");
            fetch(`/api/file/rename?token=${token}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: oldPath, name: newName })
            })
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        showToast("重命名失败: " + data.error);
                        cancelRename();
                        return;
                    }
                    const span = document.createElement("span");
                    span.className = "fb-name";
                    span.textContent = newName;
                    input.replaceWith(span);
                    node.dataset.path = data.path;
                    entry.name = newName;
                    entry.path = data.path;
                    delete node.dataset.renaming;
                    // 更新已打开的编辑器 Tab 路径
                    fbOpenTabs.forEach(tab => {
                        if (tab.path === oldPath) {
                            tab.path = data.path;
                            tab.name = newName;
                            tab.language = guessMonacoLang(newName);
                            // 如果是当前活动 tab，同步更新编辑器和工具栏
                            const idx = fbOpenTabs.indexOf(tab);
                            if (idx === fbActiveTabIndex) {
                                if (monacoEditor) monaco.editor.setModelLanguage(monacoEditor.getModel(), tab.language);
                                populateLangMenu(tab.language);
                                updateToolbarFromTab(tab);
                                updateStatusBar(tab);
                            }
                        } else if (tab.path.startsWith(oldPath + "/")) {
                            tab.path = data.path + tab.path.substring(oldPath.length);
                        }
                    });
                    renderTabs();
                    // 更新当前根路径
                    if (oldPath === fbCurrentPath) {
                        fbCurrentPath = data.path;
                    }
                    // 清除目录子项缓存
                    if (entry.type === "dir") {
                        const children = node.querySelector(".fb-children");
                        if (children) {
                            children.innerHTML = "";
                            children.dataset.loaded = "false";
                            children.classList.remove("open");
                            const toggle = node.querySelector(".fb-toggle");
                            if (toggle) toggle.classList.remove("open");
                        }
                    }
                })
                .catch(err => {
                    showToast("重命名失败: " + err.message);
                    cancelRename();
                });
        }

        input.addEventListener("keydown", (e) => {
            e.stopPropagation();
            if (e.key === "Enter") { input.blur(); }
            else if (e.key === "Escape") { cancelRename(); }
        });
        input.addEventListener("blur", submitRename);
    }

    function uploadToDir(dirPath) {
        const fileInput = document.createElement("input");
        fileInput.type = "file";
        fileInput.multiple = true;
        fileInput.style.display = "none";
        document.body.appendChild(fileInput);

        fileInput.addEventListener("change", function () {
            const files = Array.from(this.files);
            if (files.length === 0) { fileInput.remove(); return; }

            const token = sessionStorage.getItem("octopus_token");
            $fbTree.innerHTML = '<div class="fb-loading">上传中...</div>';

            // 逐个上传所有文件
            let failCount = 0;
            const lastFilePath = dirPath + "/" + files[files.length - 1].name;
            files.reduce((prev, file) =>
                prev.then(() => {
                    const formData = new FormData();
                    formData.append("file", file);
                    return fetch(`/api/file/upload?dir=${encodeURIComponent(dirPath)}&token=${token}`, {
                        method: "POST",
                        body: formData
                    }).then(r => r.json()).then(data => {
                        if (data.error) failCount++;
                    });
                }),
                Promise.resolve()
            ).then(() => {
                fileInput.remove();
                const msg = failCount > 0
                    ? `${failCount} 个文件上传失败`
                    : `${files.length} 个文件上传成功`;
                // 刷新树后展开目标文件夹并选中最后一个上传的文件
                loadFileTree(fbCurrentPath, () => {
                    expandAndSelect(dirPath, lastFilePath);
                });
                setTimeout(() => showToast(msg), 100);
            }).catch(err => {
                fileInput.remove();
                loadFileTree(fbCurrentPath);
                setTimeout(() => showToast("上传失败: " + err.message), 100);
            });
        });

        fileInput.click();
    }

    // ── Monaco Editor ──
    let edFontSize = 14;
    let edMinimap = false;
    let edWordWrap = true;
    let edColumnMode = false;     // 按钮持久开关
    let edColumnAltActive = false; // Alt 临时激活

    function initMonaco() {
        if (monacoEditor) return;
        if (typeof monaco !== "undefined" && monaco.editor) {
            createMonacoEditor();
            return;
        }
        try {
            require.config({
                paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs" },
                "vs/nls": { availableLanguages: { "*": "zh-cn" } },
            });
            require(["vs/editor/editor.main"], function () {
                createMonacoEditor();
            });
        } catch (e) {
            // Monaco CDN 加载失败
            if ($monacoEl) {
                $monacoEl.innerHTML = '<div style="padding:24px;color:var(--text-dim);text-align:center;font-size:13px;">编辑器加载失败：Monaco CDN 不可用，请检查网络连接后刷新页面重试。</div>';
            }
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
            fontSize: edFontSize,
            fontFamily: "'SF Mono', 'Fira Code', 'Courier New', monospace",
            fontLigatures: true,
            minimap: { enabled: edMinimap },
            scrollBeyondLastLine: false,
            smoothScrolling: true,
            cursorSmoothCaretAnimation: "on",
            cursorBlinking: "smooth",
            wordWrap: edWordWrap ? "on" : "off",
            wrappingIndent: "indent",
            wrappingStrategy: "advanced",
            tabSize: 4,
            renderWhitespace: "selection",
            renderLineHighlight: "all",
            padding: { top: 8, bottom: 8 },
            "bracketPairColorization.enabled": true,
            "bracketPairColorization.independentColorPoolPerBracketType": true,
            guides: { indentation: true, bracketPairs: true, highlightActiveIndentation: true },
            stickyScroll: { enabled: true, maxLineCount: 5 },
            autoClosingBrackets: "always",
            autoClosingQuotes: "always",
            autoClosingDelete: "always",
            autoIndent: "full",
            linkedEditing: true,
            folding: true,
            foldingStrategy: "auto",
            showFoldingControls: "mouseover",
            foldingHighlight: true,
            foldingImportsByDefault: true,
            parameterHints: { enabled: true },
            codeLens: true,
            multiCursorPaste: "full",
            colorDecorators: true,
            formatOnPaste: true,
            formatOnType: true,
            showUnused: true,
            showDeprecated: true,
            inlayHints: { enabled: "on" },
            unicodeHighlight: {
                ambiguousCharacters: true,
                invisibleCharacters: true,
                nonBasicASCII: false,
            },
            dragAndDrop: true,
            mouseWheelZoom: true,
            cursorSurroundingLines: 3,
            emptySelectionClipboard: true,
            copyWithSyntaxHighlighting: true,
            trimWhitespaceOnDelete: true,
            suggest: {
                showSnippets: true,
                snippetsPreventQuickSuggestions: false,
            },
            readOnly: true,
            domReadOnly: true,
        });
        // 内容变化 → 标记 dirty
        monacoEditor.onDidChangeModelContent(function () {
            if (suppressDirtyCheck) return;
            const tab = getActiveTab();
            if (tab && !tab.dirty) {
                tab.dirty = true;
                tab.content = monacoEditor.getValue();
                renderTabs();
            } else if (tab) {
                tab.content = monacoEditor.getValue();
            }
        });
        // 光标变化 → 更新状态栏
        monacoEditor.onDidChangeCursorPosition(function (e) {
            if ($sbCursor) $sbCursor.textContent = `Ln ${e.position.lineNumber}, Col ${e.position.column}`;
        });
        // 选区变化
        monacoEditor.onDidChangeCursorSelection(function (e) {
            const sel = monacoEditor.getSelection();
            if (sel && !sel.isEmpty()) {
                const lines = Math.abs(sel.endLineNumber - sel.startLineNumber) + 1;
                const chars = Math.abs(sel.endColumn - sel.startColumn);
                if ($sbSelection) {
                    $sbSelection.textContent = `(${lines > 1 ? lines + ' 行' : chars + ' 字符'}已选择)`;
                    $sbSelection.classList.remove("hidden");
                }
            } else {
                if ($sbSelection) $sbSelection.classList.add("hidden");
            }
        });
        // 注册编辑器右键菜单
        registerEditorActions();
        // 注册自定义代码片段
        registerSnippets();
        renderTabs();
        // 预填充语言下拉菜单
        populateLangMenu("plaintext");
        // Monaco 就绪后检查是否有待打开的文件
        if (fbPendingOpenQueue.length > 0) {
            const paths = fbPendingOpenQueue.splice(0);
            paths.forEach(p => openFileInEditor(p));
        }
    }

    // ── 自定义代码片段 ──
    function registerSnippets() {
        if (typeof monaco === "undefined" || !monaco.languages) return;
        const snippets = {
            javascript: [
                { prefix: "clg", body: "console.log($1);", label: "console.log" },
                { prefix: "fn", body: "function ${1:name}(${2:params}) {\n\t$0\n}", label: "function" },
                { prefix: "afn", body: "const ${1:name} = (${2:params}) => {\n\t$0\n};", label: "arrow function" },
                { prefix: "ife", body: "if (${1:condition}) {\n\t$0\n} else {\n\t\n}", label: "if...else" },
                { prefix: "tc", body: "try {\n\t$0\n} catch (${1:error}) {\n\tconsole.error($1);\n}", label: "try...catch" },
                { prefix: "imp", body: "import { $2 } from '${1:module}';", label: "import" },
                { prefix: "exp", body: "export default ${1:name};", label: "export default" },
                { prefix: "forof", body: "for (const ${1:item} of ${2:array}) {\n\t$0\n}", label: "for...of" },
            ],
            typescript: [
                { prefix: "clg", body: "console.log($1);", label: "console.log" },
                { prefix: "fn", body: "function ${1:name}(${2:params}): ${3:returnType} {\n\t$0\n}", label: "function" },
                { prefix: "afn", body: "const ${1:name} = (${2:params}): ${3:returnType} => {\n\t$0\n};", label: "arrow function" },
                { prefix: "int", body: "interface ${1:Name} {\n\t$0\n}", label: "interface" },
                { prefix: "tp", body: "type ${1:Name} = {\n\t$0\n};", label: "type" },
                { prefix: "imp", body: "import { $2 } from '${1:module}';", label: "import" },
                { prefix: "exp", body: "export default ${1:name};", label: "export default" },
            ],
            python: [
                { prefix: "def", body: "def ${1:name}(${2:params}):\n\t\"\"\"$3\"\"\"\n\t$0", label: "def" },
                { prefix: "cls", body: "class ${1:Name}:\n\tdef __init__(self${2:, params}):\n\t\t$0", label: "class" },
                { prefix: "imp", body: "import ${1:module}", label: "import" },
                { prefix: "fim", body: "from ${1:module} import ${2:name}", label: "from...import" },
                { prefix: "if", body: "if ${1:condition}:\n\t$0", label: "if" },
                { prefix: "ife", body: "if ${1:condition}:\n\t$0\nelse:\n\t", label: "if...else" },
                { prefix: "for", body: "for ${1:item} in ${2:iterable}:\n\t$0", label: "for...in" },
                { prefix: "try", body: "try:\n\t$0\nexcept ${1:Exception} as e:\n\tprint(e)", label: "try...except" },
                { prefix: "lam", body: "lambda ${1:x}: ${2:x}", label: "lambda" },
                { prefix: "pd", body: "import pandas as pd", label: "import pandas" },
                { prefix: "np", body: "import numpy as np", label: "import numpy" },
            ],
            html: [
                { prefix: "!", body: "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n\t<meta charset=\"UTF-8\">\n\t<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n\t<title>$1</title>\n</head>\n<body>\n\t$0\n</body>\n</html>", label: "HTML5 boilerplate" },
                { prefix: "div", body: "<div${1: class=\"$2\"}>\n\t$0\n</div>", label: "div" },
                { prefix: "a", body: "<a href=\"${1:#}\">$0</a>", label: "a" },
                { prefix: "btn", body: "<button type=\"button\">$0</button>", label: "button" },
            ],
            css: [
                { prefix: "flex", body: "display: flex;\njustify-content: ${1:center};\nalign-items: ${2:center};", label: "flex center" },
                { prefix: "grid", body: "display: grid;\ngrid-template-columns: ${1:repeat(3, 1fr)};\ngap: ${2:16px};", label: "grid" },
                { prefix: "media", body: "@media (max-width: ${1:768px}) {\n\t$0\n}", label: "media query" },
            ],
            json: [
                { prefix: "key", body: "\"${1:key}\": \"${2:value}\",", label: "key-value pair" },
            ],
            markdown: [
                { prefix: "h1", body: "# $0", label: "Heading 1" },
                { prefix: "h2", body: "## $0", label: "Heading 2" },
                { prefix: "h3", body: "### $0", label: "Heading 3" },
                { prefix: "code", body: "```${1:lang}\n$0\n```", label: "code block" },
                { prefix: "link", body: "[$1]($2)", label: "link" },
                { prefix: "img", body: "![$1]($2)", label: "image" },
                { prefix: "table", body: "| ${1:Header} | ${2:Header} |\n| --- | --- |\n| $0 | |", label: "table" },
            ],
            shell: [
                { prefix: "if", body: "if [ ${1:condition} ]; then\n\t$0\nfi", label: "if" },
                { prefix: "for", body: "for ${1:item} in ${2:list}; do\n\t$0\ndone", label: "for" },
                { prefix: "fn", body: "${1:name}() {\n\t$0\n}", label: "function" },
            ],
        };
        for (const [lang, items] of Object.entries(snippets)) {
            try {
                monaco.languages.registerCompletionItemProvider(lang, {
                    triggerCharacters: [],
                    provideCompletionItems: (model, position) => {
                        const word = model.getWordUntilPosition(position);
                        const range = {
                            startLineNumber: position.lineNumber,
                            endLineNumber: position.lineNumber,
                            startColumn: word.startColumn,
                            endColumn: word.endColumn,
                        };
                        const line = model.getLineContent(position.lineNumber);
                        const prefix = line.substring(0, position.column - 1).match(/\S+$/);
                        if (!prefix) return { suggestions: [] };
                        const text = prefix[0];
                        const matched = items.filter(s =>
                            s.prefix.startsWith(text) || s.label.toLowerCase().includes(text.toLowerCase())
                        );
                        return {
                            suggestions: matched.map(s => ({
                                label: s.prefix,
                                kind: monaco.languages.CompletionItemKind.Snippet,
                                insertText: s.body,
                                insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                                detail: s.label,
                                range: range,
                            })),
                        };
                    },
                });
            } catch (_) { /* language may not be registered */ }
        }
    }

    // ── Diff Editor（差异对比）──
    let diffEditor = null;
    let diffVisible = false;

    function toggleDiffView() {
        if (diffVisible) {
            closeDiffView();
        } else {
            openDiffView();
        }
    }

    function openDiffView() {
        const tab = getActiveTab();
        if (!tab || tab.untitled || !tab.path) {
            showToast("需要先保存文件才能对比差异");
            return;
        }
        if (tab.loading) {
            showToast("文件正在加载中，请稍后再试");
            return;
        }
        // 保存当前内容
        const modified = monacoEditor.getValue();
        const token = sessionStorage.getItem("octopus_token");
        // 获取磁盘上的原始内容
        fetch("/api/file?token=" + token + "&path=" + encodeURIComponent(tab.path) + "&encoding=" + (tab.encoding || "utf-8"))
            .then(r => r.json())
            .then(data => {
                if (data.error) { showToast(data.error); return; }
                const diskContent = data.content || "";
                // 隐藏主编辑器，显示 diff
                $monacoEl.style.display = "none";
                let diffEl = document.getElementById("monaco-diff");
                if (!diffEl) {
                    diffEl = document.createElement("div");
                    diffEl.id = "monaco-diff";
                    diffEl.style.cssText = "width:100%;height:100%;";
                    $monacoEl.parentNode.insertBefore(diffEl, $monacoEl.nextSibling);
                }
                diffEl.style.display = "block";
                const isDark = document.documentElement.getAttribute("data-theme") === "dark";
                if (diffEditor) diffEditor.dispose();
                diffEditor = monaco.editor.createDiffEditor(diffEl, {
                    theme: isDark ? "vs-dark" : "vs",
                    automaticLayout: true,
                    readOnly: true,
                    renderSideBySide: true,
                    fontSize: edFontSize,
                });
                const lang = tab.language || "plaintext";
                // 左侧：当前编辑器内容（新版），右侧：磁盘文件（原版）
                const currentModel = monaco.editor.createModel(modified, lang);
                const diskModel = monaco.editor.createModel(diskContent, lang);
                diffEditor.setModel({ original: currentModel, modified: diskModel });
                diffVisible = true;
                // 高亮工具栏 diff 按钮表示当前处于 diff 模式
                const $edDiff = document.getElementById("ed-diff");
                if ($edDiff) $edDiff.classList.add("active");
            });
    }

    function closeDiffView() {
        if (diffEditor) {
            // 释放 diff 模型防止内存泄漏
            const model = diffEditor.getModel();
            if (model) {
                if (model.original) model.original.dispose();
                if (model.modified) model.modified.dispose();
            }
            diffEditor.dispose();
            diffEditor = null;
        }
        const diffEl = document.getElementById("monaco-diff");
        if (diffEl) diffEl.style.display = "none";
        $monacoEl.style.display = "";
        diffVisible = false;
        // 取消工具栏 diff 按钮高亮
        const $edDiff = document.getElementById("ed-diff");
        if ($edDiff) $edDiff.classList.remove("active");
        if (monacoEditor) monacoEditor.focus();
    }

    // ── 编辑器右键菜单 ──
    function registerEditorActions() {
        if (!monacoEditor) return;
        monacoEditor.addAction({
            id: "octopus-copy-path",
            label: "复制文件路径",
            keybindings: [],
            contextMenuGroupId: "9_octopus",
            run: function () {
                const tab = getActiveTab();
                if (tab) { navigator.clipboard.writeText(tab.path).then(() => showToast("已复制路径")); }
            }
        });
        monacoEditor.addAction({
            id: "octopus-copy-relpath",
            label: "复制相对路径",
            keybindings: [],
            contextMenuGroupId: "9_octopus",
            run: function () {
                const tab = getActiveTab();
                if (tab && cwd) {
                    const prefix = cwd.endsWith("/") ? cwd : cwd + "/";
                    const rel = tab.path.startsWith(prefix) ? tab.path.slice(prefix.length) : tab.path;
                    navigator.clipboard.writeText(rel).then(() => showToast("已复制相对路径"));
                }
            }
        });
        monacoEditor.addAction({
            id: "octopus-format",
            label: "格式化文档",
            keybindings: [monaco.KeyMod.Shift | monaco.KeyMod.Alt | monaco.KeyCode.KeyF],
            contextMenuGroupId: "1_octopus",
            run: function () { formatDocument(); }
        });
        monacoEditor.addAction({
            id: "octopus-gotoline",
            label: "跳转到行...",
            keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyG],
            contextMenuGroupId: "1_octopus",
            run: function () { showGoToLine(); }
        });
        monacoEditor.addAction({
            id: "octopus-diff",
            label: "与磁盘文件对比差异",
            contextMenuGroupId: "1_octopus",
            run: function () { toggleDiffView(); }
        });
    }

    // ── Tab 管理 ──
    function getActiveTab() {
        return fbActiveTabIndex >= 0 && fbActiveTabIndex < fbOpenTabs.length ? fbOpenTabs[fbActiveTabIndex] : null;
    }

    // 获取左侧文件树中当前选中的文件夹路径（仅文件夹，文件不算）
    function getActiveDirPath() {
        // 优先找选中的文件夹
        const activeDir = document.querySelector(".fb-tree .fb-node.active.fb-dir");
        if (activeDir) return activeDir.dataset.path || null;
        // 其次找选中的文件，取其父目录
        const activeFile = document.querySelector(".fb-tree .fb-node.active.fb-file");
        if (activeFile && activeFile.dataset.path) {
            const parentPath = activeFile.dataset.path.substring(0, activeFile.dataset.path.lastIndexOf("/"));
            return parentPath || null;
        }
        // 最后回退到当前浏览的目录
        return fbCurrentPath || null;
    }

    function getSelectedPaths() {
        return Array.from(fbSelectedPaths);
    }

    function findTabByPath(path) {
        return fbOpenTabs.findIndex(t => t.path === path);
    }

    function showOpenFileDialog() {
        let dialog = document.getElementById("openfile-dialog");
        if (dialog) dialog.remove();
        dialog = document.createElement("div");
        dialog.id = "openfile-dialog";
        dialog.innerHTML = `<div class="unsaved-content">
            <h3 style="margin-bottom:12px">打开文件/文件夹</h3>
            <div id="openfile-dir-browser" style="flex:1;min-height:0;display:flex;flex-direction:column"></div>
            <div class="unsaved-actions" style="margin-top:16px">
                <button class="btn-approve" data-action="open">打开</button>
                <button class="btn-reject" style="background:var(--bg-card);border-color:var(--border)" data-action="cancel">取消</button>
            </div>
        </div>`;
        document.body.appendChild(dialog);

        const browserContainer = dialog.querySelector("#openfile-dir-browser");
        const dirBrowser = createDirBrowser(cwd || "/", { mode: "open" });
        browserContainer.appendChild(dirBrowser);

        const close = () => { dialog.remove(); if (monacoEditor) monacoEditor.focus(); };

        function openSelected() {
            const path = dirBrowser.getSelectedPath();
            if (!path) { showToast("请先选择一个文件或文件夹"); return; }
            close();
            const isDir = dirBrowser.getSelectedIsDir();
            if (isDir) {
                loadFileTree(path);
            } else {
                openFileInEditor(path);
            }
        }

        dirBrowser.addEventListener("file-selected", (e) => {
            close();
            openFileInEditor(e.detail);
        });

        dialog.querySelector('[data-action="cancel"]').addEventListener("click", close);
        dialog.querySelector('[data-action="open"]').addEventListener("click", openSelected);
        dialog.addEventListener("keydown", (e) => {
            e.stopPropagation();
            if (e.key === "Escape") close();
        });
    }

    let untitledCounter = 1;
    function createUntitledTab() {
        const tab = {
            path: "",
            name: "未命名-" + untitledCounter++,
            content: "",
            language: "plaintext",
            dirty: false,
            encoding: "utf-8",
            eol: "lf",
            viewState: null,
            size: 0,
            untitled: true,
        };
        fbOpenTabs.push(tab);
        switchToTab(fbOpenTabs.length - 1);
    }

    function openFileInEditor(filePath) {
        // 已打开则切换
        const existingIdx = findTabByPath(filePath);
        if (existingIdx >= 0) {
            switchToTab(existingIdx);
            return;
        }
        // Monaco 还没加载完
        if (!monacoEditor) {
            fbPendingOpenQueue.push(filePath);
            return;
        }

        const tab = {
            path: filePath,
            name: filePath.split("/").pop() || "untitled",
            content: "",
            language: guessMonacoLang(filePath),
            dirty: false,
            encoding: "utf-8",
            eol: "lf",
            viewState: null,
            size: 0,
            loading: true,
        };

        // 同步占位，防止快速双击打开重复 Tab
        fbOpenTabs.push(tab);
        switchToTab(fbOpenTabs.length - 1);

        const token = sessionStorage.getItem("octopus_token");
        fetch(`/api/file?path=${encodeURIComponent(filePath)}&encoding=${tab.encoding}&token=${token}`)
            .then(r => r.json())
            .then(data => {
                tab.loading = false;
                // Tab 已被关闭则跳过
                if (fbOpenTabs.indexOf(tab) < 0) return;
                if (data.error) {
                    showToast(data.binary ? "二进制文件无法编辑" : "加载失败: " + data.error);
                    const errIdx = fbOpenTabs.indexOf(tab);
                    if (errIdx >= 0) doCloseTab(errIdx);
                    return;
                }
                tab.content = data.content || "";
                tab.size = data.size || 0;
                tab.eol = data.eol || "lf";
                tab.encoding = data.encoding || "utf-8";
                // 只有当前 Tab 仍是活动 Tab 时才更新编辑器内容
                const curIdx = fbOpenTabs.indexOf(tab);
                if (curIdx === fbActiveTabIndex && monacoEditor) {
                    suppressDirtyCheck = true;
                    monacoEditor.setValue(tab.content);
                    suppressDirtyCheck = false;
                    monacoEditor.updateOptions({ readOnly: false, domReadOnly: false });
                    updateStatusBar(tab);
                }
                renderTabs();
            })
            .catch(err => {
                tab.loading = false;
                showToast("加载失败: " + err.message);
                if (fbOpenTabs.indexOf(tab) >= 0) doCloseTab(fbOpenTabs.indexOf(tab));
            });
    }

    function switchToTab(index) {
        if (index < 0 || index >= fbOpenTabs.length) return;
        // 切换 Tab 时关闭 diff 视图
        if (diffVisible) closeDiffView();
        // 保存当前 Tab 的 viewState 和 content（跳过 loading 中的 tab）
        const oldTab = getActiveTab();
        if (oldTab && monacoEditor && !oldTab.loading) {
            oldTab.viewState = monacoEditor.saveViewState();
            oldTab.content = monacoEditor.getValue();
        }
        fbActiveTabIndex = index;
        const tab = fbOpenTabs[index];
        // 恢复内容
        if (monacoEditor) {
            monacoEditor.updateOptions({ readOnly: !!tab.loading, domReadOnly: !!tab.loading });
            suppressDirtyCheck = true;
            monaco.editor.setModelLanguage(monacoEditor.getModel(), tab.language);
            monacoEditor.setValue(tab.content || "");
            if (tab.viewState) monacoEditor.restoreViewState(tab.viewState);
            suppressDirtyCheck = false;
            monacoEditor.focus();
        }
        updateToolbarFromTab(tab);
        populateLangMenu(tab.language);
        renderTabs();
        updateStatusBar(tab);
    }

    function closeTab(index) {
        if (index < 0 || index >= fbOpenTabs.length) return;
        const tab = fbOpenTabs[index];
        if (tab.dirty) {
            showUnsavedConfirm(tab).then(action => {
                if (action === "cancel") { if (monacoEditor) monacoEditor.focus(); return; }
                const currentIdx = fbOpenTabs.indexOf(tab);
                if (currentIdx < 0) return;
                if (action === "save") {
                    if (tab.untitled) {
                        saveUntitledTab(tab, (ok) => {
                            if (!ok) return;
                            const newIdx = fbOpenTabs.indexOf(tab);
                            if (newIdx >= 0) doCloseTab(newIdx);
                        });
                    } else {
                        doSaveTab(tab, (ok) => {
                            if (!ok) return;
                            const saveIdx = fbOpenTabs.indexOf(tab);
                            if (saveIdx >= 0) doCloseTab(saveIdx);
                        });
                    }
                } else {
                    doCloseTab(currentIdx);
                }
            });
        } else {
            doCloseTab(index);
        }
    }

    // 关闭全部 Tab（VS Code 风格）
    async function closeAllTabs() {
        if (fbOpenTabs.length === 0) return;
        // 分离干净和脏的 tab
        const dirtyTabs = fbOpenTabs.filter(t => t.dirty);
        if (dirtyTabs.length === 0) {
            // 全部干净，直接关闭
            fbOpenTabs.length = 0;
            fbActiveTabIndex = -1;
            if (monacoEditor) {
                monacoEditor.setValue("");
                monacoEditor.updateOptions({ readOnly: true, domReadOnly: true });
            }
            renderTabs();
            resetToolbar();
            resetStatusBar();
            return;
        }
        // 有脏 tab，弹汇总对话框
        const action = await showCloseAllConfirm(dirtyTabs);
        if (action === "cancel") return;
        if (action === "discard") {
            fbOpenTabs.length = 0;
            fbActiveTabIndex = -1;
            if (monacoEditor) {
                monacoEditor.setValue("");
                monacoEditor.updateOptions({ readOnly: true, domReadOnly: true });
            }
            renderTabs();
            resetToolbar();
            resetStatusBar();
            return;
            renderTabs();
            return;
        }
        // action === "save"：逐个保存，新文件逐个弹出另存为
        const saveTabs = [...dirtyTabs];
        let cancelled = false;
        for (const tab of saveTabs) {
            if (!fbOpenTabs.includes(tab)) continue;
            const ok = await new Promise(resolve => {
                if (tab.untitled) {
                    saveUntitledTab(tab, (ok) => {
                        resolve(ok);
                    }, () => {
                        resolve(false);
                    });
                } else {
                    doSaveTab(tab, (ok) => {
                        resolve(ok);
                    });
                }
            });
            if (!ok) { cancelled = true; break; }
        }
        if (!cancelled) {
            fbOpenTabs.length = 0;
            fbActiveTabIndex = -1;
            if (monacoEditor) {
                monacoEditor.setValue("");
                monacoEditor.updateOptions({ readOnly: true, domReadOnly: true });
            }
            resetToolbar();
            resetStatusBar();
        }
        renderTabs();
    }

    function showCloseAllConfirm(dirtyTabs) {
        return new Promise(resolve => {
            let dialog = document.getElementById("unsaved-dialog");
            if (dialog) dialog.remove();
            dialog = document.createElement("div");
            dialog.id = "unsaved-dialog";
            const fileList = dirtyTabs.map(t =>
                `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:12px;color:var(--text-secondary)">` +
                `<i class="ti ${t.untitled ? 'ti-file-plus' : 'ti-file'}" style="font-size:13px;color:var(--text-dim)"></i>` +
                `<span>${escapeHtml(t.name)}</span>` +
                `</div>`
            ).join("");
            dialog.innerHTML = `<div class="unsaved-content">
                <h3>关闭全部</h3>
                <p style="margin-bottom:10px">以下 ${dirtyTabs.length} 个文件有未保存的修改：</p>
                <div style="max-height:160px;overflow-y:auto;text-align:left;margin-bottom:16px">${fileList}</div>
                <div class="unsaved-actions">
                    <button class="btn-approve" data-action="save">全部保存</button>
                    <button class="btn-reject" data-action="discard">全部不保存</button>
                    <button class="btn-reject" style="background:var(--bg-card);border-color:var(--border)" data-action="cancel">取消</button>
                </div>
            </div>`;
            document.body.appendChild(dialog);
            dialog.querySelectorAll("button").forEach(btn => {
                btn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    dialog.remove();
                    resolve(btn.dataset.action);
                });
            });
            dialog.addEventListener("click", (e) => {
                if (e.target === dialog) { dialog.remove(); resolve("cancel"); }
            });
        });
    }

    function doCloseTab(index) {
        if (index < 0 || index >= fbOpenTabs.length) return;
        // 如果关闭的是当前活动 Tab，先重置 index 避免switchToTab 保存错误的 viewState
        const wasActive = fbActiveTabIndex === index;
        if (wasActive) fbActiveTabIndex = -1;
        fbOpenTabs.splice(index, 1);
        if (fbOpenTabs.length === 0) {
            if (monacoEditor) {
                suppressDirtyCheck = true; monacoEditor.setValue(""); suppressDirtyCheck = false;
                monacoEditor.updateOptions({ readOnly: true, domReadOnly: true });
            }
            renderTabs();
            resetToolbar();
            resetStatusBar();
        } else if (wasActive) {
            const newIdx = Math.min(index, fbOpenTabs.length - 1);
            switchToTab(newIdx);
        } else if (fbActiveTabIndex > index) {
            fbActiveTabIndex--;
            renderTabs();
        } else {
            renderTabs();
        }
    }

    function renderTabs() {
        if (!$editorTabsScroll) return;
        $editorTabsScroll.innerHTML = "";
        if (fbOpenTabs.length === 0) {
            // 无打开文件时不显示 Tab
            const $closeAll = document.getElementById("ed-close-all");
            if ($closeAll) $closeAll.classList.add("hidden");
        } else {
            fbOpenTabs.forEach((tab, i) => {
                const el = document.createElement("div");
                el.className = "ed-tab" + (i === fbActiveTabIndex ? " active" : "");
                const iconClass = getFileIconClass(tab.name);
                el.innerHTML = `<i class="ed-tab-icon ${iconClass}"></i>` +
                    (tab.loading ? '<i class="ti ti-loader ed-tab-loading" style="font-size:10px;animation:spin 1s linear infinite"></i>' : '') +
                    `<span class="ed-tab-name">${escapeHtml(tab.name)}</span>` +
                    (tab.dirty ? '<span class="ed-tab-dirty">●</span>' : '') +
                    `<button class="ed-tab-close" data-idx="${i}"><i class="ti ti-x"></i></button>`;
                // 点击切换
                el.addEventListener("click", (e) => {
                    if (e.target.closest(".ed-tab-close")) return;
                    if (i !== fbActiveTabIndex) {
                        // 检查当前 Tab 是否 dirty（不阻塞切换，只是保存 viewState）
                        switchToTab(i);
                    }
                });
                // 关闭按钮
                el.querySelector(".ed-tab-close").addEventListener("click", (e) => {
                    e.stopPropagation();
                    closeTab(i);
                });
                // 中键关闭
                el.addEventListener("mousedown", (e) => {
                    if (e.button === 1) { e.preventDefault(); closeTab(i); }
                });
                // 拖拽排序
                el.draggable = true;
                el.addEventListener("dragstart", (e) => {
                    e.dataTransfer.setData("text/tab-index", String(i));
                    el.style.opacity = "0.5";
                });
                el.addEventListener("dragend", () => { el.style.opacity = ""; });
                el.addEventListener("dragover", (e) => { e.preventDefault(); el.style.borderLeft = "2px solid var(--accent)"; });
                el.addEventListener("dragleave", () => { el.style.borderLeft = ""; });
                el.addEventListener("drop", (e) => {
                    e.preventDefault();
                    el.style.borderLeft = "";
                    const fromIdx = parseInt(e.dataTransfer.getData("text/tab-index"));
                    if (isNaN(fromIdx) || fromIdx === i) return;
                    const [moved] = fbOpenTabs.splice(fromIdx, 1);
                    // splice 后数组缩短，调整插入位置
                    const insertIdx = fromIdx < i ? i - 1 : i;
                    fbOpenTabs.splice(insertIdx, 0, moved);
                    // 更新 active index
                    if (fbActiveTabIndex === fromIdx) {
                        fbActiveTabIndex = insertIdx;
                    } else {
                        let adj = fbActiveTabIndex;
                        if (fromIdx < adj) adj--;
                        if (insertIdx <= adj) adj++;
                        fbActiveTabIndex = adj;
                    }
                    renderTabs();
                });
                $editorTabsScroll.appendChild(el);
            });
        }
        const $closeAll = document.getElementById("ed-close-all");
        if ($closeAll) $closeAll.classList.remove("hidden");
        updateTabArrows();
        // 滚动到活跃 Tab
        if (fbActiveTabIndex >= 0) {
            const activeEl = $editorTabsScroll.children[fbActiveTabIndex];
            if (activeEl) activeEl.scrollIntoView({ behavior: "smooth", inline: "nearest", block: "nearest" });
        }
    }

    function updateTabArrows() {
        if (!$editorTabsScroll || !$edTabLeft || !$edTabRight) return;
        const { scrollLeft, scrollWidth, clientWidth } = $editorTabsScroll;
        $edTabLeft.classList.toggle("hidden", scrollLeft <= 0);
        $edTabRight.classList.toggle("hidden", scrollLeft + clientWidth >= scrollWidth - 1);
    }

    // ── 工具栏同步 ──
    function updateToolbarFromTab(tab) {
        if (!tab) return;
        if ($edLangLabel) $edLangLabel.textContent = LANG_DISPLAY[tab.language] || tab.language;
        if ($edEncodingLabel) $edEncodingLabel.textContent = tab.encoding.toUpperCase();
        if ($edEolLabel) $edEolLabel.textContent = tab.eol.toUpperCase();
        if ($edTabsizeLabel && monacoEditor) $edTabsizeLabel.textContent = monacoEditor.getOption(monaco.editor.EditorOption.tabSize);
        if ($edMinimap) $edMinimap.classList.toggle("active", edMinimap);
        if ($edWordwrap) $edWordwrap.classList.toggle("active", edWordWrap);
        if ($edColumn) $edColumn.classList.toggle("active", edColumnMode);
    }

    function resetToolbar() {
        if ($edLangLabel) $edLangLabel.textContent = "纯文本";
        if ($edEncodingLabel) $edEncodingLabel.textContent = "UTF-8";
        if ($edEolLabel) $edEolLabel.textContent = "LF";
        if ($edTabsizeLabel) $edTabsizeLabel.textContent = "4";
        if ($edMinimap) $edMinimap.classList.toggle("active", edMinimap);
        if ($edWordwrap) $edWordwrap.classList.toggle("active", edWordWrap);
        if ($edColumn) $edColumn.classList.toggle("active", edColumnMode);
    }

    function updateStatusBar(tab) {
        if (!tab) return;
        if ($sbEncoding) $sbEncoding.textContent = tab.encoding.toUpperCase();
        if ($sbEol) $sbEol.textContent = tab.eol.toUpperCase();
        if ($sbLang) $sbLang.textContent = LANG_DISPLAY[tab.language] || tab.language;
        if ($sbSize) $sbSize.textContent = formatFileSize(tab.size);
        if (monacoEditor) {
            const pos = monacoEditor.getPosition();
            if ($sbCursor && pos) $sbCursor.textContent = `Ln ${pos.lineNumber}, Col ${pos.column}`;
            if ($sbIndent) {
                const ts = monacoEditor.getOption(monaco.editor.EditorOption.tabSize);
                if ($sbIndent) $sbIndent.textContent = `空格: ${ts}`;
            }
        }
    }

    function resetStatusBar() {
        if ($sbCursor) $sbCursor.textContent = "Ln 1, Col 1";
        if ($sbSelection) $sbSelection.classList.add("hidden");
        if ($sbEncoding) $sbEncoding.textContent = "UTF-8";
        if ($sbEol) $sbEol.textContent = "LF";
        if ($sbLang) $sbLang.textContent = "纯文本";
        if ($sbIndent) $sbIndent.textContent = "空格: 4";
        if ($sbSize) $sbSize.textContent = "";
    }

    const LANG_DISPLAY = {
        "plaintext": "纯文本", "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
        "json": "JSON", "html": "HTML", "css": "CSS", "scss": "SCSS", "less": "Less",
        "markdown": "Markdown", "yaml": "YAML", "xml": "XML", "ini": "TOML/INI",
        "shell": "Shell", "bash": "Bash", "c": "C", "cpp": "C++", "java": "Java",
        "go": "Go", "rust": "Rust", "ruby": "Ruby", "php": "PHP", "sql": "SQL",
        "swift": "Swift", "kotlin": "Kotlin", "dart": "Dart", "lua": "Lua", "r": "R",
        "graphql": "GraphQL", "dockerfile": "Dockerfile",
    };

    function formatFileSize(bytes) {
        if (bytes == null) return "";
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }

    function getFileIconClass(name) {
        const ext = (name || "").split(".").pop().toLowerCase();
        const map = {
            py: "ti ti-brand-python", js: "ti ti-brand-javascript", ts: "ti ti-brand-typescript",
            html: "ti ti-brand-html5", css: "ti ti-brand-css3", json: "ti ti-file-code",
            md: "ti ti-markdown", yaml: "ti ti-file-code", yml: "ti ti-file-code",
            toml: "ti ti-file-code", txt: "ti ti-file-text",
        };
        return map[ext] || "ti ti-file";
    }

    // ── 工具栏操作 ──
    function setupDropdown(btn, menu, onSelect) {
        if (!btn || !menu) return;
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            // 关闭其他下拉
            document.querySelectorAll(".ed-dropdown").forEach(m => { if (m !== menu) m.classList.add("hidden"); });
            if (!menu.classList.contains("hidden")) {
                menu.classList.add("hidden");
                return;
            }
            // 把菜单移到 body 并定位到按钮下方，避免被 overflow 裁剪
            if (menu.parentElement !== document.body) document.body.appendChild(menu);
            const rect = btn.getBoundingClientRect();
            menu.style.position = "fixed";
            menu.style.left = rect.left + "px";
            menu.style.top = (rect.bottom + 4) + "px";
            menu.classList.remove("hidden");
        });
        // 用 mousedown 而非 click，避免被其他元素拦截
        menu.addEventListener("mousedown", (e) => {
            const item = e.target.closest(".ed-dropdown-item");
            if (!item) return;
            e.preventDefault();
            e.stopPropagation();
            if (onSelect) onSelect(item.dataset.val);
            menu.classList.add("hidden");
        });
    }

    function onLangSelect(lang) {
        const tab = getActiveTab();
        if (!tab) { showToast("请先打开或新建一个文件"); return; }
        if (monacoEditor) {
            tab.language = lang;
            monaco.editor.setModelLanguage(monacoEditor.getModel(), lang);
            if ($edLangLabel) $edLangLabel.textContent = LANG_DISPLAY[lang] || lang;
            if ($sbLang) $sbLang.textContent = LANG_DISPLAY[lang] || lang;
            populateLangMenu(lang);
        }
    }

    function populateLangMenu(activeLang) {
        if (!$edLangMenu) return;
        const langs = [
            "plaintext", "python", "javascript", "typescript", "json", "html", "css",
            "scss", "less", "markdown", "yaml", "xml", "shell", "bash", "ini",
            "c", "cpp", "java", "go", "rust", "ruby", "php", "sql", "swift",
            "kotlin", "dart", "lua", "r", "graphql", "dockerfile",
        ];
        $edLangMenu.innerHTML = "";
        langs.forEach(lang => {
            const div = document.createElement("div");
            div.className = "ed-dropdown-item" + (lang === activeLang ? " active" : "");
            div.dataset.val = lang;
            div.textContent = LANG_DISPLAY[lang] || lang;
            $edLangMenu.appendChild(div);
        });
    }

    function onTabSizeSelect(val) {
        const size = parseInt(val);
        if (isNaN(size) || !monacoEditor) { showToast("请先打开一个文件"); return; }
        monacoEditor.updateOptions({ tabSize: size });
        if ($edTabsizeLabel) $edTabsizeLabel.textContent = size;
        if ($sbIndent) $sbIndent.textContent = `空格: ${size}`;
    }

    function onEncodingSelect(encoding) {
        const tab = getActiveTab();
        if (!tab) { showToast("请先打开或新建一个文件"); return; }
        if (tab.untitled || !tab.path) { showToast("请先保存文件再切换编码"); return; }
        if (tab.encoding === encoding) return;
        // 有未保存修改时先确认
        if (tab.dirty) {
            showConfirm("切换编码", `文件有未保存的修改，切换编码将丢弃修改。确定继续吗？`).then(ok => {
                if (ok) doEncodingSwitch(tab, encoding);
            });
        } else {
            doEncodingSwitch(tab, encoding);
        }
    }
    function doEncodingSwitch(tab, encoding) {
        const token = sessionStorage.getItem("octopus_token");
        fetch(`/api/file?path=${encodeURIComponent(tab.path)}&encoding=${encoding}&token=${token}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    showToast("编码切换失败: " + data.error);
                    return;
                }
                tab.encoding = encoding;
                tab.content = data.content || "";
                tab.size = data.size || 0;
                tab.eol = data.eol || "lf";
                tab.dirty = false;
                if (monacoEditor) { suppressDirtyCheck = true; monacoEditor.setValue(tab.content); suppressDirtyCheck = false; }
                if ($edEncodingLabel) $edEncodingLabel.textContent = encoding.toUpperCase();
                if ($sbEncoding) $sbEncoding.textContent = encoding.toUpperCase();
                if ($sbEol) $sbEol.textContent = (tab.eol).toUpperCase();
                if ($edEolLabel) $edEolLabel.textContent = (tab.eol).toUpperCase();
                updateStatusBar(tab);
                renderTabs();
            })
            .catch(err => showToast("编码切换失败: " + err.message));
    }

    function onEolSelect(eol) {
        const tab = getActiveTab();
        if (!tab || !monacoEditor) { showToast("请先打开一个文件"); return; }
        if (tab.eol === eol) return;
        const pos = monacoEditor.getPosition();
        let content = monacoEditor.getValue();
        if (eol === "crlf") {
            content = content.replace(/\r\n/g, "\n").replace(/\n/g, "\r\n");
        } else {
            content = content.replace(/\r\n/g, "\n");
        }
        suppressDirtyCheck = true;
        monacoEditor.setValue(content);
        if (pos) monacoEditor.setPosition(pos);
        suppressDirtyCheck = false;
        tab.eol = eol;
        tab.content = content;
        tab.dirty = true;
        if ($edEolLabel) $edEolLabel.textContent = eol.toUpperCase();
        if ($sbEol) $sbEol.textContent = eol.toUpperCase();
        renderTabs();
    }

    function formatDocument() {
        if (!monacoEditor) return;
        const action = monacoEditor.getAction("editor.action.formatDocument");
        if (action) {
            const before = monacoEditor.getValue();
            action.run().then(() => {
                if (monacoEditor.getValue() === before) {
                    showToast("当前语言没有可用的格式化器");
                }
            }).catch(() => showToast("格式化失败"));
        } else {
            showToast("当前语言不支持格式化");
        }
    }

    function onCaseSelect(type) {
        if (!monacoEditor) return;
        if (type === "upper") monacoEditor.trigger("toolbar", "editor.action.transformToUppercase");
        else if (type === "lower") monacoEditor.trigger("toolbar", "editor.action.transformToLowercase");
    }

    function toggleMinimap() {
        edMinimap = !edMinimap;
        if (monacoEditor) monacoEditor.updateOptions({ minimap: { enabled: edMinimap } });
        if ($edMinimap) $edMinimap.classList.toggle("active", edMinimap);
    }

    function changeFontSize(delta) {
        edFontSize = Math.max(12, Math.min(24, edFontSize + delta));
        if (monacoEditor) monacoEditor.updateOptions({ fontSize: edFontSize });
    }

    function toggleWordWrap() {
        edWordWrap = !edWordWrap;
        if (monacoEditor) monacoEditor.updateOptions({ wordWrap: edWordWrap ? "on" : "off" });
        if ($edWordwrap) $edWordwrap.classList.toggle("active", edWordWrap);
    }

    function applyColumnMode() {
        if (monacoEditor) monacoEditor.updateOptions({ columnSelection: edColumnMode || edColumnAltActive });
    }
    function toggleColumnMode() {
        edColumnMode = !edColumnMode;
        if ($edColumn) $edColumn.classList.toggle("active", edColumnMode);
        applyColumnMode();
    }

    // Alt/Option 键切换列选模式（单击切换，避免与 Monaco Alt+拖拽多光标冲突）
    document.addEventListener("keydown", (e) => {
        if (!fileBrowserMode || !monacoEditor) return;
        if ((e.key === "Alt" || e.code === "AltLeft" || e.code === "AltRight") && !e.repeat) {
            const tag = e.target.tagName;
            if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
            e.preventDefault();
            toggleColumnMode();
        }
    }, true);

    function showGoToLine() {
        if (!monacoEditor) return;
        const existing = document.getElementById("goto-line-dialog");
        if (existing) { existing.querySelector("input").focus(); return; }
        const model = monacoEditor.getModel();
        if (!model) return;
        const lineCount = model.getLineCount();
        // 创建内联对话框
        let dialog = document.getElementById("goto-line-dialog");
        if (dialog) dialog.remove();
        dialog = document.createElement("div");
        dialog.id = "goto-line-dialog";
        dialog.innerHTML = `<div class="goto-line-content">
            <h3>跳转到行 (1-${lineCount})</h3>
            <input type="number" min="1" max="${lineCount}" placeholder="输入行号">
        </div>`;
        document.body.appendChild(dialog);
        const input = dialog.querySelector("input");
        input.focus();
        function go() {
            const line = parseInt(input.value);
            if (!isNaN(line) && line >= 1 && line <= lineCount) {
                monacoEditor.revealLineInCenter(line);
                monacoEditor.setPosition({ lineNumber: line, column: 1 });
                monacoEditor.focus();
            }
            dialog.remove();
        }
        input.addEventListener("keydown", (e) => {
            e.stopPropagation();
            if (e.key === "Enter") go();
            else if (e.key === "Escape") { dialog.remove(); if (monacoEditor) monacoEditor.focus(); }
        });
        dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.remove(); });
    }

    // ── 保存 ──
    function saveCurrentFile() {
        const tab = getActiveTab();
        if (!tab || !monacoEditor) return;
        tab.content = monacoEditor.getValue();
        if (tab.untitled) {
            // 虚拟 Tab：弹另存为
            saveUntitledTab(tab);
        } else {
            doSaveTab(tab);
        }
    }

    function saveUntitledTab(tab, callback, onCancel) {
        const activeDir = getActiveDirPath();
        showSaveAsDialog(tab, activeDir || cwd || "", callback, onCancel);
    }

    // 通用目录浏览器组件（用于另存为 / 打开文件）
    // 视觉风格复用 fb-node/fb-icon/fb-name，交互为平铺导航式（双击进入文件夹、面包屑、双击打开）
    function createDirBrowser(rootPath, options = {}) {
        const { mode = "save" } = options;
        const wrap = document.createElement("div");
        wrap.className = "dir-browser";
        wrap.innerHTML = `<div class="dir-browser-breadcrumb"></div><div class="dir-browser-list"></div>`;
        const $breadcrumb = wrap.querySelector(".dir-browser-breadcrumb");
        const $list = wrap.querySelector(".dir-browser-list");
        let currentPath = rootPath;
        let selectedPath = null;
        let selectedIsDir = false;
        let selectedRow = null;

        function selectRow(div, path, isDir) {
            if (selectedRow) selectedRow.classList.remove("active");
            div.classList.add("active");
            selectedRow = div;
            selectedPath = path;
            selectedIsDir = !!isDir;
        }

        function renderBreadcrumb(path) {
            const parts = path.split("/");
            $breadcrumb.innerHTML = "";
            let accumulated = "";
            parts.forEach((part, i) => {
                if (!part && i === 0) { accumulated = "/"; return; }
                accumulated = accumulated ? accumulated + "/" + part : part;
                if (i > 0) $breadcrumb.insertAdjacentHTML("beforeend", '<i class="ti ti-chevron-right" style="font-size:10px;color:var(--text-dim)"></i>');
                const btn = document.createElement("button");
                btn.textContent = part || "/";
                btn.className = "dir-browser-crumb";
                const crumbPath = accumulated;
                btn.addEventListener("click", () => loadDir(crumbPath));
                $breadcrumb.appendChild(btn);
            });
        }

        function createEntryRow(entry) {
            const div = document.createElement("div");
            div.className = "dir-browser-item" + (entry.type === "dir" ? " fb-dir" : " fb-file");

            const icon = document.createElement("span");
            icon.className = "fb-icon";
            if (entry.type === "dir") {
                icon.innerHTML = '<i class="ti ti-folder"></i>';
            } else {
                icon.innerHTML = `<i class="${getFileIconClass(entry.name)}"></i>`;
            }
            div.appendChild(icon);

            const nameSpan = document.createElement("span");
            nameSpan.className = "fb-name";
            nameSpan.textContent = entry.name;
            div.appendChild(nameSpan);

            if (entry.type === "dir") {
                // 单击选中，双击下钻进入子目录
                div.addEventListener("click", () => selectRow(div, entry.path, true));
                div.addEventListener("dblclick", () => loadDir(entry.path));
            } else {
                div.addEventListener("click", () => selectRow(div, entry.path, false));
                if (mode === "open") {
                    div.addEventListener("dblclick", () => {
                        selectedPath = entry.path;
                        selectedIsDir = false;
                        wrap.dispatchEvent(new CustomEvent("file-selected", { detail: entry.path }));
                    });
                }
            }
            return div;
        }

        function loadDir(path) {
            currentPath = path;
            selectedPath = null;
            selectedIsDir = false;
            selectedRow = null;
            const token = sessionStorage.getItem("octopus_token");
            fetch("/api/files?token=" + token + "&path=" + encodeURIComponent(path))
                .then(r => r.json())
                .then(data => {
                    if (data.error) { showToast(data.error); return; }
                    currentPath = data.path;
                    renderBreadcrumb(data.path);
                    $list.innerHTML = "";
                    if (data.path && data.path !== "/") {
                        const parent = data.path.substring(0, data.path.lastIndexOf("/")) || "/";
                        const upRow = document.createElement("div");
                        upRow.className = "dir-browser-item dir-browser-parent";
                        const upName = document.createElement("span");
                        upName.className = "fb-name";
                        upName.textContent = "..";
                        upRow.appendChild(upName);
                        upRow.addEventListener("click", () => selectRow(upRow, parent, true));
                        upRow.addEventListener("dblclick", () => loadDir(parent));
                        $list.appendChild(upRow);
                    }
                    (data.entries || []).forEach(entry => {
                        $list.appendChild(createEntryRow(entry));
                    });
                })
                .catch(() => showToast("无法读取目录"));
        }

        wrap.getSelectedPath = () => selectedPath;
        wrap.getSelectedIsDir = () => selectedIsDir;
        wrap.getCurrentPath = () => currentPath;
        wrap.loadDir = loadDir;

        loadDir(rootPath);
        return wrap;
    }

    function showSaveAsDialog(tab, dirPath, callback, onCancel) {
        let dialog = document.getElementById("saveas-dialog");
        if (dialog) dialog.remove();
        dialog = document.createElement("div");
        dialog.id = "saveas-dialog";
        dialog.innerHTML = `<div class="unsaved-content">
            <h3 style="margin-bottom:12px">保存文件</h3>
            <div id="saveas-dir-browser" style="flex:1;min-height:0;display:flex;flex-direction:column"></div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:12px;flex-shrink:0">
                <span style="font-size:12px;color:var(--text-dim);white-space:nowrap">文件名</span>
                <input id="saveas-input" type="text" value="${escapeHtml(tab.name)}" style="flex:1;padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;color:var(--text);background:var(--bg-main);outline:none;font-family:inherit">
            </div>
            <div class="unsaved-actions" style="margin-top:16px">
                <button class="btn-approve" data-action="save">保存</button>
                <button class="btn-reject" style="background:var(--bg-card);border-color:var(--border)" data-action="cancel">取消</button>
            </div>
        </div>`;
        document.body.appendChild(dialog);

        const browserContainer = dialog.querySelector("#saveas-dir-browser");
        const dirBrowser = createDirBrowser(dirPath, { mode: "save" });
        browserContainer.appendChild(dirBrowser);

        const input = dialog.querySelector("#saveas-input");
        const dotIdx = tab.name.lastIndexOf(".");
        if (dotIdx > 0) { input.setSelectionRange(0, dotIdx); } else { input.select(); }

        const close = () => { dialog.remove(); if (monacoEditor) monacoEditor.focus(); if (onCancel) onCancel(); };
        dialog.querySelector('[data-action="cancel"]').addEventListener("click", close);
        dialog.querySelector('[data-action="save"]').addEventListener("click", () => {
            const name = input.value.trim();
            if (!name) { showToast("请输入文件名"); return; }
            if (/[/\\]/.test(name)) { showToast("文件名不能包含 / 或 \\"); return; }
            const selectedDir = dirBrowser.getCurrentPath();
            const fullPath = selectedDir + "/" + name;
            const token = sessionStorage.getItem("octopus_token");
            fetch("/api/file?token=" + token + "&path=" + encodeURIComponent(fullPath))
                .then(r => r.json())
                .then(data => {
                    if (!data.error || data.binary) {
                        showGeneralConfirm("覆盖文件", `文件 "${name}" 已存在，是否覆盖？`, () => {
                            close();
                            doSaveAs(tab, selectedDir, name, callback);
                        });
                    } else {
                        close();
                        doSaveAs(tab, selectedDir, name, callback);
                    }
                })
                .catch(() => {
                    close();
                    doSaveAs(tab, selectedDir, name, callback);
                });
        });
        input.addEventListener("keydown", (e) => {
            e.stopPropagation();
            if (e.key === "Enter") { dialog.querySelector('[data-action="save"]').click(); }
            if (e.key === "Escape") { close(); }
        });
    }

    function doSaveAs(tab, dirPath, name, callback) {
        const fullPath = dirPath + "/" + name;
        // 如果目标路径已有其他 tab 打开，关闭旧 tab
        const existingIdx = fbOpenTabs.findIndex(t => t !== tab && t.path === fullPath);
        if (existingIdx >= 0) doCloseTab(existingIdx);
        const token = sessionStorage.getItem("octopus_token");
        fetch("/api/file?token=" + token, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: fullPath, content: tab.content, encoding: tab.encoding, eol: tab.eol }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    tab.untitled = false;
                    tab.path = fullPath;
                    tab.name = name;
                    tab.dirty = false;
                    tab.size = new Blob([tab.content]).size;
                    tab.language = guessMonacoLang(name);
                    // 只有当前活动 tab 才更新编辑器和工具栏
                    const idx = fbOpenTabs.indexOf(tab);
                    if (idx === fbActiveTabIndex) {
                        if (monacoEditor) monaco.editor.setModelLanguage(monacoEditor.getModel(), tab.language);
                        updateToolbarFromTab(tab);
                        updateStatusBar(tab);
                    }
                    renderTabs();
                    showToast("已保存");
                    // 刷新文件树并展开目录选中该文件
                    loadFileTree(fbCurrentPath, () => expandAndSelect(dirPath, fullPath));
                    if (callback) callback(true);
                } else {
                    showToast("保存失败: " + (data.error || ""));
                    if (callback) callback(false);
                }
            })
            .catch(err => {
                showToast("保存失败: " + err.message);
                if (callback) callback(false);
            });
    }

    function doSaveTab(tab, callback) {
        const token = sessionStorage.getItem("octopus_token");
        fetch("/api/file?token=" + token, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: tab.path, content: tab.content, encoding: tab.encoding, eol: tab.eol }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    tab.dirty = false;
                    tab.size = new Blob([tab.content]).size;
                    renderTabs();
                    if (fbOpenTabs.indexOf(tab) === fbActiveTabIndex) updateStatusBar(tab);
                    showToast("已保存");
                    loadFileTree(fbCurrentPath);
                    if (callback) callback(true);
                } else {
                    showToast("保存失败: " + (data.error || ""));
                    if (callback) callback(false);
                }
            })
            .catch(err => {
                showToast("保存失败: " + err.message);
                if (callback) callback(false);
            });
    }

    // ── 未保存确认 ──
    function showUnsavedConfirm(tab) {
        return new Promise(resolve => {
            let dialog = document.getElementById("unsaved-dialog");
            if (dialog) dialog.remove();
            dialog = document.createElement("div");
            dialog.id = "unsaved-dialog";
            const isUntitled = tab.untitled;
            dialog.innerHTML = `<div class="unsaved-content">
                <h3>${isUntitled ? "未保存的内容" : "文件已修改"}</h3>
                <p>${isUntitled ? escapeHtml(tab.name) + " 尚未保存到磁盘。" : escapeHtml(tab.name) + " 有未保存的修改。"}</p>
                <div class="unsaved-actions">
                    <button class="btn-approve" data-action="save">${isUntitled ? "保存为..." : "保存"}</button>
                    <button class="btn-reject" data-action="discard">不保存</button>
                    <button class="btn-reject" style="background:var(--bg-card);border-color:var(--border)" data-action="cancel">取消</button>
                </div>
            </div>`;
            document.body.appendChild(dialog);
            dialog.querySelectorAll("button").forEach(btn => {
                btn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    dialog.remove();
                    resolve(btn.dataset.action);
                });
            });
            dialog.addEventListener("click", (e) => {
                if (e.target === dialog) { dialog.remove(); resolve("cancel"); }
            });
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
        const filename = (filePath || "").split("/").pop();
        if (filename && filename.toLowerCase() === "dockerfile".toLowerCase()) return "dockerfile";
        return map[ext] || "plaintext";
    }

    // ── 创建新文件/文件夹 ──
    function createNewEntry(dirPath, type) {
        // 在文件树中找到目标目录的 fb-children 容器，添加内联输入框
        const dirNode = $fbTree.querySelector(`.fb-node[data-path="${CSS.escape(dirPath)}"]`);
        let container = null;
        if (dirNode) {
            container = dirNode.querySelector(".fb-children");
            // 如果子容器未展开，先展开
            if (container && !container.classList.contains("open")) {
                container.classList.add("open");
                const toggle = dirNode.querySelector(".fb-toggle");
                if (toggle) toggle.classList.add("open");
                container.dataset.loaded = "true";
                container.innerHTML = "";
            }
        }
        if (!container) {
            // 找不到目录节点，在根树底部添加
            container = $fbTree;
        }

        const depth = dirNode ? (parseInt((dirNode.style.paddingLeft || "12").replace("px", "")) - 12) / 16 + 1 : 0;
        const row = document.createElement("div");
        row.className = "fb-node";
        row.style.paddingLeft = (12 + depth * 16) + "px";

        const input = document.createElement("input");
        input.type = "text";
        input.className = "fb-rename-input";
        input.value = type === "dir" ? "new_folder" : "new_file.txt";
        input.style.flex = "1";

        row.appendChild(input);
        container.insertBefore(row, container.firstChild);
        input.focus();
        input.setSelectionRange(0, input.value.lastIndexOf(".") >= 0 ? input.value.lastIndexOf(".") : input.value.length);

        function cancel() { row.remove(); }

        function submit() {
            const name = input.value.trim();
            if (!name) { cancel(); return; }
            if (/[/\\]/.test(name)) { showToast("名称不能包含 / 或 \\"); return; }
            const token = sessionStorage.getItem("octopus_token");
            fetch("/api/file/create?token=" + token, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: dirPath, name: name, type: type }),
            })
                .then(r => r.json())
                .then(data => {
                    if (data.ok) {
                        row.remove();
                        showToast("创建成功");
                        // 刷新后展开父目录并选中新项
                        loadFileTree(fbCurrentPath, () => {
                            expandAndSelect(dirPath, data.path);
                        });
                        if (type === "file") openFileInEditor(data.path);
                    } else {
                        showToast("创建失败: " + data.error);
                        input.focus();
                    }
                })
                .catch(err => {
                    showToast("创建失败: " + err.message);
                    input.focus();
                });
        }

        let submitted = false;
        input.addEventListener("keydown", (e) => {
            e.stopPropagation();
            if (e.key === "Enter") { e.preventDefault(); if (!submitted) { submitted = true; submit(); } }
            else if (e.key === "Escape") cancel();
        });
        input.addEventListener("blur", () => { if (!submitted) { submitted = true; submit(); } });
    }

    // ── 快捷键 ──
    document.addEventListener("keydown", function (e) {
        if (!fileBrowserMode || !monacoEditor) return;
        // 在输入框/textarea 中不拦截（避免影响对话框、重命名输入等）
        const tag = e.target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        const mod = e.ctrlKey || e.metaKey;
        if (mod && e.key === "s") {
            e.preventDefault();
            saveCurrentFile();
        }
        if (mod && e.key === "w") {
            e.preventDefault();
            if (fbActiveTabIndex >= 0) closeTab(fbActiveTabIndex);
        }
        if (mod && e.key === "Tab") {
            e.preventDefault();
            if (fbOpenTabs.length > 1) {
                const next = e.shiftKey
                    ? (fbActiveTabIndex - 1 + fbOpenTabs.length) % fbOpenTabs.length
                    : (fbActiveTabIndex + 1) % fbOpenTabs.length;
                switchToTab(next);
            }
        }
        if (mod && e.key === "p") {
            // TODO: 快速打开文件（文件搜索）
        }
    });

    // 浏览器关闭/刷新提示
    window.addEventListener("beforeunload", function (e) {
        if (fbOpenTabs.some(t => t.dirty)) {
            e.preventDefault();
            e.returnValue = "";
        }
    });

    // 全局点击关闭编辑器下拉菜单
    document.addEventListener("click", (e) => {
        if (!e.target.closest(".ed-dropdown-wrap") && !e.target.closest(".ed-dropdown")) {
            document.querySelectorAll(".ed-dropdown").forEach(m => m.classList.add("hidden"));
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
    let loadingDotsEl = null;

    function showLoadingDots() {
        if (loadingDotsEl) return;
        if (showThinking || showTools) return;
        const div = document.createElement("div");
        div.className = "loading-dots";
        div.innerHTML = "<span></span><span></span><span></span>";
        $messages.appendChild(div);
        loadingDotsEl = div;
        scrollToBottom();
    }

    function removeLoadingDots() {
        if (loadingDotsEl) {
            loadingDotsEl.remove();
            loadingDotsEl = null;
        }
    }

    function appendThinkingBlock(text) {
        hideWelcome();
        const div = document.createElement("div");
        div.className = "thinking-block";
        div.addEventListener("click", () => div.classList.toggle("expanded"));
        div.textContent = "💭 " + text;
        if (!showThinking) div.style.display = "none";
        $messages.appendChild(div);
        scrollToBottom();
    }

    function appendThinking(text, beforeEl) {
        hideWelcome();
        if (thinkingEl) {
            thinkingEl.textContent = "💭 " + text;
        } else {
            const div = document.createElement("div");
            div.className = "thinking-block";
            div.addEventListener("click", () => div.classList.toggle("expanded"));
            div.textContent = "💭 " + text;
            if (!showThinking) div.style.display = "none";
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
        if (!showTools) div.style.display = "none";
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
        if (!showTools) container.style.display = "none";
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
        exportFile(html, `session_${sessionId ? sessionId.slice(0, 8) : "export"}.html`, "text/html");
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
    function exportFile(content, filename, mimeType = "text/plain;charset=utf-8") {
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
        if (diffEditor && typeof monaco !== "undefined" && monaco.editor) {
            diffEditor.updateOptions({ theme: darkMode ? "vs-dark" : "vs" });
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

    // ── 侧边栏拖动调整宽度 ──
    function initSidebarResize() {
        if (!$resizeHandle || !$sidebar) return;
        let isResizing = false;

        $resizeHandle.addEventListener("mousedown", function (e) {
            isResizing = true;
            $sidebar.classList.add("resizing");
            $resizeHandle.classList.add("active");
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";
            e.preventDefault();
        });

        document.addEventListener("mousemove", function (e) {
            if (!isResizing) return;
            const minW = 280;
            const newWidth = Math.max(minW, e.clientX);
            $sidebar.style.width = newWidth + "px";
        });

        document.addEventListener("mouseup", function () {
            if (!isResizing) return;
            isResizing = false;
            $sidebar.classList.remove("resizing");
            $resizeHandle.classList.remove("active");
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        });
    }

    // ── 启动 ──
    document.addEventListener("DOMContentLoaded", () => {
        init();
        if ($sidebarToggle) $sidebarToggle.addEventListener("click", toggleSidebar);
        if ($sidebarExpand) $sidebarExpand.addEventListener("click", toggleSidebar);
        initSidebarResize();
        // 右键菜单全局关闭（capture 阶段，防止 tree 节点 stopPropagation 阻断）
        document.addEventListener("click", hideContextMenu, true);
        document.addEventListener("contextmenu", hideContextMenu, true);
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") hideContextMenu();
        });
        window.addEventListener("beforeunload", () => {
            if (ws) ws.close(1000, "page unload");
        });
    });
})();
