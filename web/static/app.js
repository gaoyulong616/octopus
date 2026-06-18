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
    let hasSentMessage = false;
    let streamBuffer = "";
    let currentAssistantEl = null;
    let renderTimer = null;
    let pendingConfirmId = null;
    let pendingConfirmTool = null;
    let confirmQueue = [];
    let lastTask = null;
    let voiceRecognition = null;
    let voiceActive = false;
    let notificationsEnabled = false;
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

    // ── 用户认证状态 ──
    let currentUser = null;
    let authToken = "";
    let isLoggedIn = false;
    let _uiInitialized = false;

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

    // ── DOM ──
    const $chatScroll = document.getElementById("chat-scroll");
    const $messages = document.getElementById("messages");
    const $welcomePanel = document.getElementById("welcome-panel");
    const $input = document.getElementById("input");
    const $micBtn = document.getElementById("mic-btn");
    const $sendBtn = document.getElementById("send-btn");
    const $stopBtn = document.getElementById("stop-btn");

    // ── 认证相关 DOM ──
    const $authPage = document.getElementById("auth-page");
    const $tabLogin = document.getElementById("tab-login");
    const $tabRegister = document.getElementById("tab-register");
    const $formLogin = document.getElementById("form-login");
    const $formRegister = document.getElementById("form-register");
    const $loginUsername = document.getElementById("login-username");
    const $loginPassword = document.getElementById("login-password");
    const $loginRemember = document.getElementById("login-remember");
    const $btnLogin = document.getElementById("btn-login");
    const $regName = document.getElementById("reg-name");
    const $regUsername = document.getElementById("reg-username");
    const $regEmail = document.getElementById("reg-email");
    const $regPassword = document.getElementById("reg-password");
    const $regPassword2 = document.getElementById("reg-password2");
    const $btnRegister = document.getElementById("btn-register");
    const $authError = document.getElementById("auth-error");

    // ── 用户菜单相关 DOM ──
    const $userMenu = document.getElementById("user-menu");
    const $userAvatar = document.getElementById("user-avatar");
    const $userNameDisplay = document.getElementById("user-name-display");
    const $userMenuAvatar = document.getElementById("user-menu-avatar");
    const $userMenuName = document.getElementById("user-menu-name");
    const $userMenuEmail = document.getElementById("user-menu-email");
    const $menuProfile = document.getElementById("menu-profile");
    const $menuLogout = document.getElementById("menu-logout");

    // ── 个人中心相关 DOM ──
    const $profilePanel = document.getElementById("profile-panel");
    const $profileClose = document.getElementById("profile-close");
    const $profileAvatar = document.getElementById("profile-avatar");
    const $profileName = document.getElementById("profile-name");
    const $profileEmail = document.getElementById("profile-email");
    const $profileId = document.getElementById("profile-id");
    const $profileCreated = document.getElementById("profile-created");
    const $profileLastLogin = document.getElementById("profile-last-login");
    const $profileEditName = document.getElementById("profile-edit-name");
    const $profileEditEmail = document.getElementById("profile-edit-email");
    const $profileEditStatus = document.getElementById("profile-edit-status");
    const $btnSaveProfile = document.getElementById("btn-save-profile");

    // ── 修改密码 ──
    const $cpCurrent = document.getElementById("cp-current");
    const $cpNew = document.getElementById("cp-new");
    const $cpNew2 = document.getElementById("cp-new2");
    const $cpError = document.getElementById("cp-error");
    const $cpConfirm = document.getElementById("cp-confirm");
    const $confirmInput = document.getElementById("confirm-input");
    const $confirmDialog = document.getElementById("confirm-dialog");
    const $confirmTool = document.getElementById("confirm-tool");
    const $confirmApprove = document.getElementById("confirm-approve");
    const $confirmReject = document.getElementById("confirm-reject");
    const $confirmApproveAll = document.getElementById("confirm-approve-all");
    const $modeIndicator = document.getElementById("mode-indicator");
    const $thinkingToggle = document.getElementById("thinking-toggle");
    const $toolsToggle = document.getElementById("tools-toggle");
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
    const $sessionList = document.getElementById("session-list");
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
        if (!$lightbox) return;
        const $img = $lightbox.querySelector(".lightbox-img");
        if (!$img) return;
        $img.src = src;
        $lightbox.classList.add("open");
        document.body.style.overflow = "hidden";
        // 下载按钮：点击下载当前图片
        var $dl = $lightbox.querySelector(".lightbox-download");
        if ($dl) {
            $dl.onclick = function () { downloadImage(src); };
        }
    }

    function downloadImage(src) {
        var a = document.createElement("a");
        a.href = src;
        a.download = src.split("/").pop().split("?")[0] || "image";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    function closeLightbox() {
        const $lightbox = document.getElementById("image-lightbox");
        if (!$lightbox) return;
        $lightbox.classList.remove("open");
        document.body.style.overflow = "";
        // 动画结束后再清 src，避免图片闪没
        const $img = $lightbox.querySelector(".lightbox-img");
        if ($img) setTimeout(function () { $img.src = ""; }, 300);
    }

    window._openLightbox = openLightbox;

    // ── 欢迎面板 ──
    function hideWelcome() {
        if ($welcomePanel) $welcomePanel.classList.add("hidden");
    }

    function showWelcomePanel() {
        if ($welcomePanel) $welcomePanel.classList.remove("hidden");
    }

    // ── UI 事件监听器初始化（登录后或已有 token 时调用） ──
    function initUI() {
        if (_uiInitialized) return;
        _uiInitialized = true;
        console.log("[Init] Initializing UI event listeners");

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
            $inputArea.addEventListener("dragover", (e) => {
                e.preventDefault(); e.stopPropagation();
                $inputArea.classList.add("drag-over");
            });
            $inputArea.addEventListener("dragleave", () => $inputArea.classList.remove("drag-over"));
            $inputArea.addEventListener("drop", (e) => {
                $inputArea.classList.remove("drag-over");
                handleDrop(e);
            });
        }
        const $chatArea = document.getElementById("chat-scroll");
        if ($chatArea) {
            let dragCounter = 0;
            $chatArea.addEventListener("dragover", (e) => { e.preventDefault(); e.stopPropagation(); });
            $chatArea.addEventListener("dragenter", (e) => {
                e.preventDefault(); e.stopPropagation();
                dragCounter++;
                $chatArea.classList.add("drag-over");
            });
            $chatArea.addEventListener("dragleave", () => {
                dragCounter--;
                if (dragCounter <= 0) { dragCounter = 0; $chatArea.classList.remove("drag-over"); }
            });
            $chatArea.addEventListener("drop", (e) => {
                dragCounter = 0;
                $chatArea.classList.remove("drag-over");
                handleDrop(e);
            });
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
        // 初始同步按钮状态
        if (showThinking) $thinkingToggle.classList.add("active");
        if (showTools) $toolsToggle.classList.add("active");
        $modelBtn.addEventListener("click", toggleModelSelector);
        $deleteModeBtn.addEventListener("click", toggleDeleteMode);
        $deleteSelectAllBtn.addEventListener("click", deleteSelectAll);
        $deleteConfirmBtn.addEventListener("click", deleteSelected);
        $deleteCancelBtn.addEventListener("click", exitDeleteMode);

        $micBtn.addEventListener("click", toggleVoiceInput);

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
                    } else if (fmt === "htmlx") {
                        exportAsHTMLX();
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
                if (this.classList.contains("disabled")) return;
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
            // 图表工具栏 dropdown：如果点击的不是工具栏内的下载按钮或 dropdown，关闭所有
            document.querySelectorAll(".chart-dropdown.open").forEach(dd => {
                const tb = dd.closest(".chart-toolbar");
                if (tb && !tb.contains(e.target)) {
                    dd.classList.remove("open");
                    tb.classList.remove("dropdown-open");
                }
            });
        });

        // 图片灯箱：事件委托，点击任意图片打开灯箱
        document.addEventListener("click", function (e) {
            var img = e.target.closest("img");
            if (!img) return;
            // 排除灯箱内部图片、图标等
            if (img.closest("#image-lightbox")) return;
            if (img.classList.contains("ti")) return;  // tabler icons
            var src = img.src || img.getAttribute("src");
            if (!src) return;
            openLightbox(src);
        });

        const $lightbox = document.getElementById("image-lightbox");
        if ($lightbox) {
            $lightbox.querySelector(".lightbox-backdrop").addEventListener("click", closeLightbox);
            $lightbox.querySelector(".lightbox-close").addEventListener("click", closeLightbox);
            document.addEventListener("keydown", (e) => {
                if (e.key === "Escape" && $lightbox.classList.contains("open")) {
                    closeLightbox();
                }
            });
        }

        // 认证相关事件（在 DOMContentLoaded 中调用，确保只执行一次）
    }

    // ── 认证相关事件初始化（在页面加载时执行一次）
    function initAuthRelatedEvents() {
        initUserMenuEvents();
        initProfileEvents();
    }

    // ── 初始化 ──
    function init() {
        initMermaidTheme(darkMode);
        initAuthEvents();

        // 检查认证状态
        const savedToken = localStorage.getItem("octopus_auth_token") || sessionStorage.getItem("octopus_auth_token");
        console.log("[Init] Starting, savedToken:", savedToken ? "exists" : "none");
        if (savedToken) {
            authToken = savedToken;
            checkAuthStatus();
        } else {
            console.log("[Init] No token, showing auth page");
            showAuthPage();
            return;
        }

        initUI();
    }


    // ── 认证相关函数 ──
    function showAuthPage() {
        if ($authPage) $authPage.classList.remove("hidden");
        document.querySelector(".db-root").style.display = "none";
    }

    function hideAuthPage() {
        if ($authPage) $authPage.classList.add("hidden");
        document.querySelector(".db-root").style.display = "flex";
    }

    function showAuthError(msg) {
        if ($authError) {
            $authError.textContent = msg;
            $authError.classList.add("show");
        }
    }

    function clearAuthError() {
        if ($authError) {
            $authError.textContent = "";
            $authError.classList.remove("show");
        }
    }

    function checkAuthStatus() {
        console.log("[Auth] Checking auth status, token:", authToken ? "exists" : "none");
        fetch("/api/auth/me", {
            headers: { "Authorization": `Bearer ${authToken}` }
        })
        .then(res => {
            console.log("[Auth] /api/auth/me response status:", res.status);
            return res.json();
        })
        .then(data => {
            console.log("[Auth] /api/auth/me response data:", data);
            if (data.error) {
                console.log("[Auth] Error in response, logging out");
                logout();
                return;
            }
            currentUser = data;
            isLoggedIn = true;
            hideAuthPage();
            updateUserDisplay();
            // 认证成功后初始化 UI 和其他组件
            initUI();
            connectWS(authToken);
            loadSessions();
            loadCommands();
            loadModels();
        })
        .catch((e) => {
            console.log("[Auth] Fetch failed, logging out:", e);
            logout();
        });
    }

    function login(username, password, remember) {
        clearAuthError();
        fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                showAuthError(data.error);
                return;
            }
            authToken = data.access_token;
            currentUser = data.user;
            isLoggedIn = true;

            if (remember) {
                localStorage.setItem("octopus_auth_token", authToken);
                localStorage.setItem("octopus_refresh_token", data.refresh_token);
            } else {
                sessionStorage.setItem("octopus_auth_token", authToken);
                sessionStorage.setItem("octopus_refresh_token", data.refresh_token);
            }

            hideAuthPage();
            updateUserDisplay();

            // 登录成功后初始化 UI 和其他组件
            initUI();
            connectWS(authToken);
            loadSessions();
            loadCommands();
            loadModels();
        })
        .catch(() => {
            showAuthError("登录失败，请检查网络连接");
        });
    }

    function register(name, username, email, password, password2) {
        clearAuthError();
        if (!name || !name.trim()) {
            showAuthError("请输入姓名");
            return;
        }
        if (!username || !username.trim()) {
            showAuthError("请输入账号");
            return;
        }
        if (!/^[a-zA-Z0-9_]+$/.test(username)) {
            showAuthError("账号只能包含数字、字母和下划线");
            return;
        }
        if (password !== password2) {
            showAuthError("两次输入的密码不一致");
            return;
        }
        if (password.length < 6) {
            showAuthError("密码长度至少为6位");
            return;
        }

        fetch("/api/auth/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name.trim(), username: username.trim(), email: email.trim() || null, password })
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                showAuthError(data.error);
                return;
            }
            showAuthError("注册成功，请登录");
            switchToLogin();
        })
        .catch(() => {
            showAuthError("注册失败，请检查网络连接");
        });
    }

    function logout() {
        isLoggedIn = false;
        _uiInitialized = false;
        currentUser = null;
        authToken = "";
        localStorage.removeItem("octopus_auth_token");
        localStorage.removeItem("octopus_refresh_token");
        sessionStorage.removeItem("octopus_auth_token");
        sessionStorage.removeItem("octopus_refresh_token");
        if ($loginUsername) $loginUsername.value = "";
        if ($loginPassword) $loginPassword.value = "";
        if ($loginRemember) $loginRemember.checked = false;
        if ($regName) $regName.value = "";
        if ($regUsername) $regUsername.value = "";
        if ($regEmail) $regEmail.value = "";
        if ($regPassword) $regPassword.value = "";
        if ($regPassword2) $regPassword2.value = "";
        clearAuthError();
        showAuthPage();
    }

    function switchToLogin() {
        $tabLogin.classList.add("active");
        $tabRegister.classList.remove("active");
        $formLogin.classList.remove("hidden");
        $formRegister.classList.add("hidden");
        clearAuthError();
    }

    function switchToRegister() {
        $tabRegister.classList.add("active");
        $tabLogin.classList.remove("active");
        $formRegister.classList.remove("hidden");
        $formLogin.classList.add("hidden");
        clearAuthError();
    }

    function updateUserDisplay() {
        if (!currentUser) return;
        const name = currentUser.name || currentUser.username || "用户";
        const avatarChar = name.charAt(0).toUpperCase();
        if ($userAvatar) $userAvatar.textContent = avatarChar;
        if ($userNameDisplay) $userNameDisplay.textContent = name;
        if ($userMenuAvatar) $userMenuAvatar.textContent = avatarChar;
        if ($userMenuName) $userMenuName.textContent = name;
        if ($userMenuEmail) $userMenuEmail.textContent = currentUser.email || "未绑定邮箱";
        if ($profileAvatar) $profileAvatar.textContent = avatarChar;
        if ($profileName) $profileName.textContent = name;
        if ($profileEmail) $profileEmail.textContent = currentUser.email || "未绑定邮箱";
        if ($profileId) $profileId.textContent = `ID: ${currentUser.id}`;
        if ($profileCreated) $profileCreated.textContent = currentUser.created_at ? formatDate(currentUser.created_at) : "--";
        if ($profileLastLogin) $profileLastLogin.textContent = currentUser.last_login_at ? formatDate(currentUser.last_login_at) : "--";
    }

    function formatDate(dateStr) {
        try {
            const date = new Date(dateStr);
            return date.toLocaleString("zh-CN", {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit"
            });
        } catch {
            return dateStr;
        }
    }

    // ── 事件初始化 ──
    function initAuthEvents() {
        if ($tabLogin) $tabLogin.addEventListener("click", switchToLogin);
        if ($tabRegister) $tabRegister.addEventListener("click", switchToRegister);

        if ($btnLogin) $btnLogin.addEventListener("click", () => {
            login($loginUsername.value, $loginPassword.value, $loginRemember.checked);
        });

        if ($btnRegister) $btnRegister.addEventListener("click", () => {
            register($regName.value, $regUsername.value, $regEmail.value, $regPassword.value, $regPassword2.value);
        });

        if ($loginUsername) $loginUsername.addEventListener("keydown", (e) => {
            if (e.key === "Enter") $btnLogin.click();
        });
        if ($loginPassword) $loginPassword.addEventListener("keydown", (e) => {
            if (e.key === "Enter") $btnLogin.click();
        });

        // input tooltip
        document.querySelectorAll(".form-input[data-tip]").forEach($input => {
            const tipId = "tip-" + $input.id;
            const $tip = document.getElementById(tipId);
            if ($tip) {
                $input.addEventListener("focus", () => $tip.style.opacity = "1");
                $input.addEventListener("blur", () => $tip.style.opacity = "0");
            }
        });
    }

    function initUserMenuEvents() {
        document.addEventListener("click", (e) => {
            const $dbUserEl = e.target.closest(".db-user");
            if ($dbUserEl) {
                e.stopPropagation();
                $userMenu.classList.toggle("hidden");
                return;
            }
            if ($menuProfile && e.target.closest("#menu-profile")) {
                e.stopPropagation();
                $userMenu.classList.add("hidden");
                showProfile();
                return;
            }
            if ($menuLogout && e.target.closest("#menu-logout")) {
                e.stopPropagation();
                $userMenu.classList.add("hidden");
                logout();
                return;
            }
            if (!$userMenu.contains(e.target)) {
                $userMenu.classList.add("hidden");
            }
        });
    }

    function showProfile() {
        if ($profilePanel) $profilePanel.classList.remove("hidden");
        if (currentUser) {
            var _name = currentUser.name || currentUser.username || "用户";
            var _char = _name.charAt(0).toUpperCase();
            if ($profileAvatar) $profileAvatar.textContent = _char;
            if ($profileName) $profileName.textContent = _name;
            if ($profileEmail) $profileEmail.textContent = currentUser.email || "未绑定邮箱";
            if ($profileId) $profileId.textContent = "用户 ID: " + (currentUser.id || "");
            if ($profileCreated) $profileCreated.textContent = formatDate(currentUser.created_at);
            if ($profileLastLogin) $profileLastLogin.textContent = formatDate(currentUser.last_login_at);
            if ($profileEditName) $profileEditName.value = currentUser.name || "";
            if ($profileEditEmail) $profileEditEmail.value = currentUser.email || "";
        }
        if ($cpCurrent) $cpCurrent.value = "";
        if ($cpNew) $cpNew.value = "";
        if ($cpNew2) $cpNew2.value = "";
        if ($cpError) { $cpError.textContent = ""; $cpError.classList.remove("show", "ok"); }
        if ($profileEditStatus) { $profileEditStatus.textContent = ""; $profileEditStatus.classList.remove("show", "ok"); }
    }

    function formatDate(iso) {
        if (!iso) return "--";
        try { return new Date(iso).toLocaleString("zh-CN"); } catch(e) { return iso; }
    }

    function hideProfile() {
        if ($profilePanel) $profilePanel.classList.add("hidden");
    }

    function setProfileStatus(msg, isOk) {
        if (!$profileEditStatus) return;
        $profileEditStatus.textContent = msg;
        $profileEditStatus.classList.add("show");
        if (isOk) $profileEditStatus.classList.add("ok");
        else $profileEditStatus.classList.remove("ok");
    }

    function saveProfile() {
        var name = $profileEditName ? $profileEditName.value.trim() : "";
        var email = $profileEditEmail ? $profileEditEmail.value.trim() : "";
        if ($btnSaveProfile) { $btnSaveProfile.disabled = true; $btnSaveProfile.textContent = "保存中…"; }
        fetch("/api/auth/me/profile", {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${authToken}`
            },
            body: JSON.stringify({ name: name, email: email })
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                setProfileStatus(data.error, false);
                return;
            }
            currentUser = data;
            updateUserDisplay();
            if ($profileName) $profileName.textContent = data.name || data.username || "用户";
            if ($profileEmail) $profileEmail.textContent = data.email || "未绑定邮箱";
            setProfileStatus("已保存", true);
        })
        .catch(() => setProfileStatus("保存失败，请检查网络连接", false))
        .finally(() => {
            if ($btnSaveProfile) { $btnSaveProfile.disabled = false; $btnSaveProfile.textContent = "保存修改"; }
        });
    }

    function initProfileEvents() {
        if ($profileClose) $profileClose.addEventListener("click", hideProfile);
        if ($btnSaveProfile) $btnSaveProfile.addEventListener("click", saveProfile);
    }

    // 静默重认证：用账号+密码换新 token，仅更新 token/storage 并重连 WS，不重置 UI
    function silentReauth(username, password) {
        return fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: username, password: password })
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) { logout(); return; }
            authToken = data.access_token;
            currentUser = data.user;
            const hadLocal = !!localStorage.getItem("octopus_auth_token");
            if (hadLocal) {
                localStorage.setItem("octopus_auth_token", authToken);
                localStorage.setItem("octopus_refresh_token", data.refresh_token);
            } else {
                sessionStorage.setItem("octopus_auth_token", authToken);
                sessionStorage.setItem("octopus_refresh_token", data.refresh_token);
            }
            updateUserDisplay();
            // 先静默关闭旧 WS（detach onclose 防止 4001 触发 logout）
            if (ws) { ws.onclose = null; try { ws.close(); } catch(e) {} }
            connectWS(authToken);
        })
        .catch(() => logout());
    }

    function changePassword() {
        const current = $cpCurrent.value;
        const newPwd = $cpNew.value;
        const newPwd2 = $cpNew2.value;

        if (!current || !newPwd || !newPwd2) {
            if ($cpError) {
                $cpError.textContent = "请填写所有字段";
                $cpError.classList.add("show");
            }
            return;
        }
        if (newPwd !== newPwd2) {
            if ($cpError) {
                $cpError.textContent = "两次输入的密码不一致";
                $cpError.classList.add("show");
            }
            return;
        }
        if (newPwd.length < 6) {
            if ($cpError) {
                $cpError.textContent = "密码长度至少为6位";
                $cpError.classList.add("show");
            }
            return;
        }

        fetch("/api/auth/me/password", {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${authToken}`
            },
            body: JSON.stringify({ current_password: current, new_password: newPwd })
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                if ($cpError) {
                    $cpError.textContent = data.error;
                    $cpError.classList.add("show");
                }
                return;
            }
            // 改密后旧 token 失效（token_version 自增），用新密码静默换取新 token
            if ($cpCurrent) $cpCurrent.value = "";
            if ($cpNew) $cpNew.value = "";
            if ($cpNew2) $cpNew2.value = "";
            if ($cpError) {
                $cpError.textContent = "密码已更新，正在刷新会话…";
                $cpError.classList.add("show", "ok");
            }
            silentReauth(currentUser.username, newPwd).then(() => {
                if ($cpError) { $cpError.textContent = ""; $cpError.classList.remove("show", "ok"); }
            });
        })
        .catch(() => {
            if ($cpError) {
                $cpError.textContent = "修改失败，请检查网络连接";
                $cpError.classList.add("show");
            }
        });
    }

    if ($cpConfirm) $cpConfirm.addEventListener("click", changePassword);

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
        ws.onclose = (event) => {
            // 4001 = Unauthorized, 需要重新登录
            if (event.code === 4001) {
                showSystem("认证失效，请重新登录");
                logout();
                return;
            }
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
                busy = false;
                updateButtons();
                break;

            case "error":
                flushStream();
                removeLoadingDots();
                hideWelcome();
                appendError(text);
                notifyIfHidden("Octopus - 出错了", text || "执行过程中出现错误");
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
                break;

            case "done":
                // 后台会话完成：仅显示气泡，不影响当前会话状态
                if (meta && meta.completed_session_id && meta.completed_session_id !== sessionId) {
                    showBackgroundSessionBubble(meta.completed_session_id);
                    loadSessions();
                    break;
                }
                flushStream();
                busy = false;
                updateButtons();
                loadSessions();
                notifyIfHidden("Octopus - 任务完成", lastTask || "任务已完成");
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
                busy = false;
                hasSentMessage = true;
                updateButtons();
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
                loadSessions();
                break;

            case "session_created":
                sessionId = meta.session_id;
                busy = false;
                hasSentMessage = false;
                updateButtons();
                $messages.innerHTML = "";
                showWelcomePanel();
                updateSessionTitle("Octopus");
                loadSessions();
                break;

            case "mode_changed":
                planMode = text === "plan";
                updateModeDisplay();
                if (meta.note) {
                    showToast(meta.note);
                } else {
                    showToast(planMode ? "已切换到 Plan 模式（只读，不会修改文件）" : "已切换到 Auto 模式（可执行所有操作）");
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
        renderDiffBlocks(container);
        renderSvgBlocks(container);
        renderMermaid(container);
        renderEcharts(container);
        renderTable(container);
        renderVideoLinks(container);
        renderDocLinks(container);
        renderAudioLinks(container);
        renderImageLinks(container);
        renderDownloadLinks(container);
        renderExternalDownloads(container);
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
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        terminalWS = new WebSocket(`${proto}//${location.host}/ws/pty?token=${authToken}`);
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

            // 关闭文件浏览器意味着回到对话视图，同步选中状态到 nav-chat
            document.querySelectorAll(".db-nav-item").forEach(el => el.classList.remove("act"));
            const $navChat = document.getElementById("nav-chat");
            if ($navChat) $navChat.classList.add("act");
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
        authFetch(`/api/files?path=${encodeURIComponent(dirPath)}`)
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
        authFetch(`/api/files?path=${encodeURIComponent(parentDirPath)}`)
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

        authFetch(`/api/files?path=${encodeURIComponent(dirPath)}`)
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
        el._hideTimer = setTimeout(() => el.classList.remove("show"), 2000);
    }

    // ── 语音输入 ──
    function toggleVoiceInput() {
        if (voiceActive) { stopVoiceInput(); return; }
        startVoiceInput();
    }

    function startVoiceInput() {
        var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) { showToast("当前浏览器不支持语音识别，请使用 Chrome", true); return; }
        if (voiceRecognition) { try { voiceRecognition.abort(); } catch (e) {} }
        voiceRecognition = new SR();
        voiceRecognition.lang = "zh-CN";
        voiceRecognition.interimResults = false;
        voiceRecognition.continuous = false;
        voiceRecognition.onresult = function (event) {
            var t = event.results[0][0].transcript;
            $input.value = $input.value + t;
            autoResize();
            updateButtons();
            showToast("语音识别完成");
            voiceActive = false;
            updateMicButtonState();
        };
        voiceRecognition.onerror = function (event) {
            var msg = "语音识别出错";
            if (event.error === "not-allowed") msg = "麦克风权限被拒绝";
            else if (event.error === "no-speech") msg = "未检测到语音";
            else if (event.error === "network") msg = "网络错误";
            showToast(msg, true);
            voiceActive = false;
            updateMicButtonState();
        };
        voiceRecognition.onend = function () {
            voiceActive = false;
            updateMicButtonState();
        };
        voiceRecognition.start();
        voiceActive = true;
        updateMicButtonState();
    }

    function stopVoiceInput() {
        if (voiceRecognition) { try { voiceRecognition.abort(); } catch (e) {}; voiceRecognition = null; }
        voiceActive = false;
        updateMicButtonState();
    }

    function updateMicButtonState() {
        if (voiceActive) {
            $micBtn.classList.add("recording");
            $micBtn.querySelector("i").className = "ti ti-microphone-filled";
            $micBtn.title = "停止录音";
        } else {
            $micBtn.classList.remove("recording");
            $micBtn.querySelector("i").className = "ti ti-microphone";
            $micBtn.title = "语音输入";
        }
    }

    // ── 浏览器通知 ──
    function requestNotificationPermission() {
        if (!("Notification" in window)) return;
        if (Notification.permission === "granted") { notificationsEnabled = true; return; }
        if (Notification.permission === "denied") return;
        Notification.requestPermission().then(function (perm) {
            notificationsEnabled = (perm === "granted");
        });
    }

    function notifyIfHidden(title, body) {
        if (!notificationsEnabled || !document.hidden) return;
        if (!("Notification" in window)) return;
        if (Notification.permission !== "granted") return;
        try {
            new Notification(title, {
                body: body,
                icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🐙</text></svg>",
                tag: "octopus-task"
            });
        } catch (e) {}
    }

    // ── 会话内搜索 ──
    let $searchBox = null;
    let searchMatches = [];
    let searchIdx = -1;

    function openSearch() {
        if ($searchBox) {
            const inp = $searchBox.querySelector("input");
            inp.focus();
            inp.select();
            return;
        }
        $searchBox = document.createElement("div");
        $searchBox.id = "search-box";
        $searchBox.innerHTML = `
            <input type="text" placeholder="搜索当前会话..." autocomplete="off">
            <span class="search-count">0/0</span>
            <button class="search-btn" data-act="prev" title="上一个 (Shift+Enter)"><i class="ti ti-chevron-up"></i></button>
            <button class="search-btn" data-act="next" title="下一个 (Enter)"><i class="ti ti-chevron-down"></i></button>
            <button class="search-btn" data-act="close" title="关闭 (Esc)"><i class="ti ti-x"></i></button>`;
        document.body.appendChild($searchBox);
        const input = $searchBox.querySelector("input");
        let timer = null;
        input.addEventListener("input", () => {
            clearTimeout(timer);
            timer = setTimeout(() => doSearch(input.value), 150);
        });
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                navSearch(e.shiftKey ? -1 : 1);
            } else if (e.key === "Escape") {
                e.preventDefault();
                closeSearch();
            } else if (e.key === "ArrowDown") {
                e.preventDefault();
                navSearch(1);
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                navSearch(-1);
            }
        });
        $searchBox.addEventListener("click", (e) => {
            const btn = e.target.closest(".search-btn");
            if (!btn) return;
            const act = btn.dataset.act;
            if (act === "prev") navSearch(-1);
            else if (act === "next") navSearch(1);
            else if (act === "close") closeSearch();
        });
        input.focus();
    }

    function closeSearch() {
        clearSearchHighlights();
        if ($searchBox) {
            $searchBox.remove();
            $searchBox = null;
        }
        searchMatches = [];
        searchIdx = -1;
    }

    function clearSearchHighlights() {
        document.querySelectorAll("mark.search-match").forEach(m => {
            const parent = m.parentNode;
            parent.replaceChild(document.createTextNode(m.textContent), m);
            parent.normalize();
        });
    }

    function doSearch(query) {
        clearSearchHighlights();
        searchMatches = [];
        searchIdx = -1;
        const count = $searchBox.querySelector(".search-count");
        if (!query) {
            count.textContent = "0/0";
            return;
        }
        const q = query.toLowerCase();
        const messages = document.querySelectorAll(".message-content");
        messages.forEach(content => {
            const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, {
                acceptNode(node) {
                    if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
                    const tag = (node.parentNode.tagName || "").toUpperCase();
                    if (tag === "SCRIPT" || tag === "STYLE" || tag === "MARK") return NodeFilter.FILTER_REJECT;
                    return node.nodeValue.toLowerCase().includes(q) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
                }
            });
            const targets = [];
            let n;
            while ((n = walker.nextNode())) targets.push(n);
            targets.forEach(node => {
                const text = node.nodeValue;
                const lower = text.toLowerCase();
                const frag = document.createDocumentFragment();
                let last = 0;
                let i = lower.indexOf(q);
                while (i !== -1) {
                    if (i > last) frag.appendChild(document.createTextNode(text.slice(last, i)));
                    const mark = document.createElement("mark");
                    mark.className = "search-match";
                    mark.textContent = text.slice(i, i + q.length);
                    frag.appendChild(mark);
                    last = i + q.length;
                    i = lower.indexOf(q, last);
                }
                if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
                node.parentNode.replaceChild(frag, node);
            });
        });
        searchMatches = Array.from(document.querySelectorAll("mark.search-match"));
        if (searchMatches.length > 0) {
            searchIdx = 0;
            highlightCurrent();
        }
        count.textContent = searchMatches.length === 0
            ? "0/0"
            : `${searchIdx + 1}/${searchMatches.length}`;
    }

    function navSearch(dir) {
        if (searchMatches.length === 0) return;
        searchIdx = (searchIdx + dir + searchMatches.length) % searchMatches.length;
        highlightCurrent();
    }

    function highlightCurrent() {
        document.querySelectorAll("mark.search-current").forEach(m => m.classList.remove("search-current"));
        if (searchIdx >= 0 && searchMatches[searchIdx]) {
            const m = searchMatches[searchIdx];
            m.classList.add("search-current");
            m.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        if ($searchBox) {
            $searchBox.querySelector(".search-count").textContent =
                searchMatches.length === 0 ? "0/0" : `${searchIdx + 1}/${searchMatches.length}`;
        }
    }

    document.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && (e.key === "f" || e.key === "F")) {
            const tag = (e.target.tagName || "").toUpperCase();
            if (tag === "INPUT" || tag === "TEXTAREA") {
                // 输入框中 Cmd+F 让浏览器处理(查找输入框内容)
                if (e.target.id === "input") {
                    e.preventDefault();
                    openSearch();
                }
                return;
            }
            e.preventDefault();
            openSearch();
        }
    });

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
        const filename = path.split("/").pop() || "file";
        showToast("已下载 " + filename);
        // 使用 fetch 获取 blob，创建 object URL 触发下载
        authFetch(`/api/file/download?path=${encodeURIComponent(path)}`)
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
            $fbTree.innerHTML = '<div class="fb-loading">删除中...</div>';
            authFetch(`/api/file?path=${encodeURIComponent(path)}`, { method: "DELETE" })
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
            $fbTree.innerHTML = '<div class="fb-loading">删除中...</div>';
            // 按路径深度降序排列（深层优先），串行删除避免并发冲突
            paths.sort((a, b) => b.split("/").length - a.split("/").length);
            const deletedPaths = [];
            let errorCount = 0;
            paths.reduce((prev, path) =>
                prev.then(() =>
                    authFetch(`/api/file?path=${encodeURIComponent(path)}`, { method: "DELETE" })
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
            authFetch(`/api/file/rename`, {
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

            $fbTree.innerHTML = '<div class="fb-loading">上传中...</div>';

            // 逐个上传所有文件
            let failCount = 0;
            const lastFilePath = dirPath + "/" + files[files.length - 1].name;
            files.reduce((prev, file) =>
                prev.then(() => {
                    const formData = new FormData();
                    formData.append("file", file);
                    return authFetch(`/api/file/upload?dir=${encodeURIComponent(dirPath)}`, {
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
                paths: { vs: "/static/vendor/vs" },
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
        // 获取磁盘上的原始内容
        authFetch("/api/file?path=" + encodeURIComponent(tab.path) + "&encoding=" + (tab.encoding || "utf-8"))
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

        authFetch(`/api/file?path=${encodeURIComponent(filePath)}&encoding=${tab.encoding}`)
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
        authFetch(`/api/file?path=${encodeURIComponent(tab.path)}&encoding=${encoding}`)
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
            authFetch("/api/files?path=" + encodeURIComponent(path))
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
            authFetch("/api/file?path=" + encodeURIComponent(fullPath))
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
        authFetch("/api/file", {
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
        authFetch("/api/file", {
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
            authFetch("/api/file/create", {
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
        renderVideoLinks(contentEl);
        renderDocLinks(contentEl);
        renderDownloadLinks(contentEl);
        renderExternalDownloads(contentEl);
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
            renderDiffBlocks(contentEl);
            renderSvgBlocks(contentEl);
            renderGitGraph(contentEl);
            renderMermaid(contentEl);
            renderEcharts(contentEl);
            renderTable(contentEl);
            renderVideoLinks(contentEl);
            renderDocLinks(contentEl);
            renderAudioLinks(contentEl);
            renderImageLinks(contentEl);
            renderDownloadLinks(contentEl);
            renderExternalDownloads(contentEl);
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

    function escapeAttr(str) {
        return (str || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    // SVG 代码块内联渲染
    function renderSvgBlocks(container) {
        if (!container) return;
        container.querySelectorAll("pre code.language-svg").forEach(function (codeEl) {
            if (codeEl.dataset.svgRendered) return;
            codeEl.dataset.svgRendered = "1";
            var svgText = codeEl.textContent || "";
            // 检查是否包含有效的 SVG 标签
            if (!/<svg[\s\S]*<\/svg>/i.test(svgText)) return;
            var wrapper = document.createElement("div");
            wrapper.className = "svg-block";
            wrapper.innerHTML = svgText;
            var pre = codeEl.closest("pre");
            if (pre) pre.replaceWith(wrapper);
        });
    }

    // 自动检测 /videos/ 链接并替换为 <video> 播放器
    const VIDEO_EXTS = [".mp4", ".webm", ".mov", ".mkv", ".avi", ".ogv", ".ogg", ".m4v", ".ts"];
    function renderVideoLinks(contentEl) {
        if (!contentEl) return;
        contentEl.querySelectorAll("a[href^='/videos/']").forEach(a => {
            const href = a.getAttribute("href");
            const ext = href.slice(href.lastIndexOf(".")).toLowerCase();
            if (!VIDEO_EXTS.includes(ext)) return;
            if (a.dataset.videoRendered) return;
            a.dataset.videoRendered = "1";
            const title = a.textContent.trim();
            const wrapper = document.createElement("div");
            wrapper.className = "ed-video";
            wrapper.innerHTML = '<video controls preload="metadata" class="ed-video-player" src="' + escapeAttr(href) + '"></video>'
                + (title ? '<div class="ed-video-title">' + escapeHtml(title) + '</div>' : "");
            a.replaceWith(wrapper);
        });
    }

    // 自动检测 /music/ 链接并替换为 <audio> 播放器
    const AUDIO_EXTS = [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".wma", ".aac", ".opus", ".weba"];
    function renderAudioLinks(contentEl) {
        if (!contentEl) return;
        contentEl.querySelectorAll("a[href^='/music/']").forEach(function (a) {
            var href = a.getAttribute("href");
            var ext = href.slice(href.lastIndexOf(".")).toLowerCase();
            if (!AUDIO_EXTS.includes(ext)) return;
            if (a.dataset.audioRendered) return;
            a.dataset.audioRendered = "1";
            var title = a.textContent.trim();
            var wrapper = document.createElement("div");
            wrapper.className = "ed-audio";
            wrapper.innerHTML = '<audio controls preload="metadata" class="ed-audio-player" src="' + escapeAttr(href) + '"></audio>'
                + (title ? '<div class="ed-audio-title">' + escapeHtml(title) + '</div>' : "");
            a.replaceWith(wrapper);
        });
    }

    // 自动检测 /images/ 链接并替换为 <img>（带灯箱点击）
    var IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif", ".tiff", ".tif"];
    function renderImageLinks(contentEl) {
        if (!contentEl) return;
        // 情形 1: markdown 链接语法 [text](/images/...) → <a>
        contentEl.querySelectorAll("a[href^='/images/']").forEach(function (a) {
            var href = a.getAttribute("href");
            var ext = href.slice(href.lastIndexOf(".")).toLowerCase();
            if (!IMAGE_EXTS.includes(ext)) return;
            if (a.dataset.imageRendered) return;
            a.dataset.imageRendered = "1";
            var title = a.textContent.trim();
            var wrapper = document.createElement("div");
            wrapper.className = "ed-image";
            var img = document.createElement("img");
            img.src = href;
            img.className = "ed-image-img";
            img.alt = title || "";
            img.loading = "lazy";
            img.dataset.imageRendered = "1";
            img.addEventListener("click", function () { window._openLightbox(href); });
            wrapper.appendChild(img);
            if (title) {
                var caption = document.createElement("div");
                caption.className = "ed-image-title";
                caption.textContent = title;
                wrapper.appendChild(caption);
            }
            a.replaceWith(wrapper);
        });
        // 情形 2: markdown 图片语法 ![alt](/images/...) → 裸 <img>（marked 输出为 <p><img></p>）
        // 直接给 img 加 class 和事件，不额外包 div（那样会被浏览器从 p 里踢出来）
        contentEl.querySelectorAll("img[src^='/images/']").forEach(function (img) {
            if (img.dataset.imageRendered) return;
            var src = img.getAttribute("src");
            var ext = src.slice(src.lastIndexOf(".")).toLowerCase();
            if (!IMAGE_EXTS.includes(ext)) return;
            img.dataset.imageRendered = "1";
            img.classList.add("ed-image-img");
            img.addEventListener("click", function () { window._openLightbox(src); });
            // alt 文本作为 caption 追加到 <p> 后面
            var alt = img.getAttribute("alt");
            if (alt) {
                var cap = document.createElement("div");
                cap.className = "ed-image-title";
                cap.textContent = alt;
                img.parentNode.insertBefore(cap, img.nextSibling);
            }
        });
    }

    // 自动检测 /dl/ 链接并替换为下载卡片
    function renderDownloadLinks(contentEl) {
        if (!contentEl) return;
        contentEl.querySelectorAll("a[href^='/dl/']").forEach(function (a) {
            if (a.dataset.downloadRendered) return;
            // 表格内的链接：去样式去点击，留纯文本（避免破坏表格布局）
            if (a.closest("td, th, table")) {
                var txt = document.createTextNode(a.textContent);
                a.replaceWith(txt);
                return;
            }
            a.dataset.downloadRendered = "1";
            var href = a.getAttribute("href");
            // /dl/path/to/file.csv → /path/to/file.csv
            var filePath = href.slice(3);
            try { filePath = decodeURIComponent(filePath); } catch (e) {}
            var linkText = a.textContent.trim();
            var fileName = linkText || filePath.split("/").pop() || "文件";
            var card = document.createElement("div");
            card.className = "ed-download";
            var iconFile = document.createElement("i");
            iconFile.className = "ti ti-file-download ed-download-icon";
            var nameEl = document.createElement("span");
            nameEl.className = "ed-download-name";
            nameEl.textContent = fileName;
            var actionEl = document.createElement("i");
            actionEl.className = "ti ti-download ed-download-action";
            actionEl.title = "下载 " + fileName;
            actionEl.addEventListener("click", function (e) {
                e.stopPropagation();
                downloadFile(filePath);
            });
            card.appendChild(iconFile);
            card.appendChild(nameEl);
            card.appendChild(actionEl);
            a.replaceWith(card);
        });
    }

    // 自动检测 title="download" 的外链（MinIO/OSS/第三方文件服务）并替换为下载卡片
    function renderExternalDownloads(contentEl) {
        if (!contentEl) return;
        contentEl.querySelectorAll('a[title="download"]').forEach(function (a) {
            if (a.dataset.extDownloadRendered) return;
            // 表格内的链接：去样式去点击，留纯文本
            if (a.closest("td, th, table")) {
                var txt = document.createTextNode(a.textContent);
                a.replaceWith(txt);
                return;
            }
            a.dataset.extDownloadRendered = "1";
            var href = a.getAttribute("href") || "";
            // 文件名优先用链接文本，否则从 URL path 末段提取
            var fileName = a.textContent.trim();
            if (!fileName) {
                try {
                    var u = new URL(href);
                    var last = u.pathname.split("/").filter(Boolean).pop();
                    if (last) fileName = decodeURIComponent(last);
                } catch (e) {}
            }
            if (!fileName) fileName = "外部文件";
            // 移除 title 避免 hover 显示 "download"
            a.removeAttribute("title");
            var card = document.createElement("div");
            card.className = "ed-download";
            var iconFile = document.createElement("i");
            iconFile.className = "ti ti-file-download ed-download-icon";
            var nameEl = document.createElement("span");
            nameEl.className = "ed-download-name";
            nameEl.textContent = fileName;
            var actionEl = document.createElement("i");
            actionEl.className = "ti ti-download ed-download-action";
            actionEl.title = "在新标签页打开 " + fileName;
            actionEl.addEventListener("click", function (e) {
                e.stopPropagation();
                e.preventDefault();
                window.open(href, "_blank", "noopener,noreferrer");
            });
            card.appendChild(iconFile);
            card.appendChild(nameEl);
            card.appendChild(actionEl);
            a.replaceWith(card);
        });
    }

    // ── 文档预览（/docs/ 链接 → 可点击卡片 → 模态框内 jit-viewer）──
    const DOC_EXTS = [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".md", ".csv", ".ofd"];
    const DOC_ICONS = {
        pdf: "doc-card-icon-pdf", docx: "doc-card-icon-word", doc: "doc-card-icon-word",
        xlsx: "doc-card-icon-excel", xls: "doc-card-icon-excel",
        pptx: "doc-card-icon-ppt", ppt: "doc-card-icon-ppt",
        txt: "doc-card-icon-text", md: "doc-card-icon-text", csv: "doc-card-icon-text",
    };
    const DOC_GLYPH = {
        pdf: "PDF", docx: "W", doc: "W",
        xlsx: "X", xls: "X",
        pptx: "P", ppt: "P",
        txt: "T", md: "MD", csv: "CSV",
    };

    let jitViewerLoaded = false;

    function lazyLoadJitViewer() {
        if (jitViewerLoaded) return Promise.resolve();
        return new Promise((resolve, reject) => {
            // CSS
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = "/static/vendor/jit-viewer.min.css?v=2";
            link.onload = () => {
                // JS
                const script = document.createElement("script");
                script.src = "/static/vendor/jit-viewer.min.js?v=2";
                script.onload = () => {
                    jitViewerLoaded = true;
                    resolve();
                };
                script.onerror = () => reject(new Error("jit-viewer 加载失败"));
                document.head.appendChild(script);
            };
            link.onerror = () => reject(new Error("jit-viewer CSS 加载失败"));
            document.head.appendChild(link);
        });
    }

    function renderDocLinks(contentEl) {
        if (!contentEl) return;
        const links = contentEl.querySelectorAll("a[href^='/docs/']");
        if (links.length === 0) return;
        // 只有 1 个文档链接时自动展开，多个时用紧凑卡片
        const autoExpand = links.length === 1;

        links.forEach(a => {
            // 表格内的链接去掉链接样式和点击行为，只留纯文本
            if (a.closest("td, th, table")) {
                const txt = document.createTextNode(a.textContent);
                a.replaceWith(txt);
                return;
            }
            const href = a.getAttribute("href");
            const ext = href.slice(href.lastIndexOf(".")).toLowerCase();
            if (!DOC_EXTS.includes(ext)) return;
            if (a.dataset.docRendered) return;
            a.dataset.docRendered = "1";
            const title = decodeURIComponent(href.split("/").pop());
            const extKey = ext.replace(".", "");
            const iconCls = DOC_ICONS[extKey] || "doc-card-icon-text";
            const glyph = DOC_GLYPH[extKey] || "?";

            if (autoExpand) {
                // 单个推荐：直接展开预览
                const wrapper = document.createElement("div");
                wrapper.className = "ed-doc";
                const container = document.createElement("div");
                container.className = "ed-doc-container";
                container.style.height = "500px";
                container.style.minHeight = "500px";
                container.innerHTML = '<div class="ed-doc-loading"><i class="ti ti-loader" style="animation:spin 1s linear infinite"></i> 加载文档中…</div>';
                wrapper.appendChild(container);
                a.replaceWith(wrapper);

                // 异步加载 jit-viewer
                lazyLoadJitViewer().then(() => {
                    const loadingEl = container.querySelector(".ed-doc-loading");
                    if (loadingEl) loadingEl.remove();
                    if (typeof JitViewer === "undefined" || !JitViewer.createViewer) {
                        container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-dim)">jit-viewer 加载失败</div>';
                        return;
                    }
                    try {
                        const isDark = document.documentElement.getAttribute("data-theme") === "dark";
                        JitViewer.createViewer({
                            target: container,
                            file: href,
                            filename: title,
                            toolbar: true,
                            theme: isDark ? "dark" : "light",
                            locale: "zh-CN",
                        }).mount();
                    } catch (e) {
                        container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-dim)">预览失败: ' + escapeHtml(e.message) + '</div>';
                    }
                }).catch(err => {
                    container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-dim)">' + escapeHtml(err.message) + '</div>';
                });
            } else {
                // 多个链接：紧凑卡片，点击"预览"才展开
                const card = document.createElement("span");
                card.className = "doc-card";
                card.innerHTML = '<span class="doc-card-icon ' + iconCls + '">' + escapeHtml(glyph) + '</span>'
                    + '<span class="doc-card-name">' + escapeHtml(title) + '</span>'
                    + '<button class="doc-card-btn" data-expanded="false">预览</button>';
                a.replaceWith(card);

                const btn = card.querySelector(".doc-card-btn");
                btn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    const expanded = btn.dataset.expanded === "true";
                    if (expanded) {
                        const existing = card.querySelector(".ed-doc");
                        if (existing) existing.remove();
                        btn.textContent = "预览";
                        btn.dataset.expanded = "false";
                    } else {
                        btn.textContent = "加载中…";
                        btn.dataset.expanded = "true";
                        const wrapper = document.createElement("div");
                        wrapper.className = "ed-doc";
                        const container = document.createElement("div");
                        container.className = "ed-doc-container";
                        container.style.minHeight = "400px";
                        container.innerHTML = '<div class="ed-doc-loading"><i class="ti ti-loader" style="animation:spin 1s linear infinite"></i> 加载文档中…</div>';
                        wrapper.appendChild(container);
                        card.parentNode.insertBefore(wrapper, card.nextSibling);

                        lazyLoadJitViewer().then(() => {
                            const loadingEl = container.querySelector(".ed-doc-loading");
                            if (loadingEl) loadingEl.remove();
                            btn.textContent = "收起";
                            if (typeof JitViewer === "undefined" || !JitViewer.createViewer) {
                                container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-dim)">jit-viewer 加载失败</div>';
                                return;
                            }
                            try {
                                const isDark = document.documentElement.getAttribute("data-theme") === "dark";
                                JitViewer.createViewer({
                                    target: container,
                                    file: href,
                                    filename: title,
                                    toolbar: true,
                                    theme: isDark ? "dark" : "light",
                                    locale: "zh-CN",
                                }).mount();
                                addDocFullscreenBtn(container);
                            } catch (e) {
                                container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-dim)">预览失败: ' + escapeHtml(e.message) + '</div>';
                            }
                        }).catch(err => {
                            btn.textContent = "预览失败";
                            container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-dim)">' + escapeHtml(err.message) + '</div>';
                        });
                    }
                });
            }
        });
    }

    // ── 语言别名 → 标准名（用于复用已有 LANG_DISPLAY，避免重复声明）
    const LANG_ALIAS = {
        js: "javascript", ts: "typescript",
        py: "python",
        sh: "shell", zsh: "shell",
        md: "markdown", yml: "yaml",
        rs: "rust", rb: "ruby",
    };

    function displayOfLang(lang) {
        if (!lang) return "";
        const lower = lang.toLowerCase();
        const std = LANG_ALIAS[lower] || lower;
        if (LANG_DISPLAY[std]) return LANG_DISPLAY[std];
        if (lower === "jsx") return "JSX";
        if (lower === "tsx") return "TSX";
        if (lower === "csharp" || lower === "c#") return "C#";
        return lang.charAt(0).toUpperCase() + lang.slice(1);
    }

    const LANG_EXT = {
        python: "py", py: "py",
        javascript: "js", js: "js", node: "js",
        typescript: "ts", ts: "ts",
        jsx: "jsx", tsx: "tsx",
        bash: "sh", sh: "sh", shell: "sh", zsh: "sh",
        html: "html", xml: "xml", svg: "svg",
        css: "css", scss: "scss", less: "less",
        json: "json", yaml: "yaml", yml: "yml", toml: "toml",
        markdown: "md", md: "md",
        sql: "sql",
        go: "go",
        rust: "rs", rs: "rs",
        java: "java",
        kotlin: "kt",
        swift: "swift",
        c: "c", cpp: "cpp", "c++": "cpp",
        "c#": "cs", csharp: "cs",
        php: "php",
        ruby: "rb", rb: "rb",
        dockerfile: "dockerfile",
        makefile: "mk",
        ini: "ini", conf: "conf",
        diff: "diff", patch: "patch",
    };

    function extOfLang(lang) {
        if (!lang) return "txt";
        return LANG_EXT[lang.toLowerCase()] || "txt";
    }

    function highlightCode(el) {
        el.querySelectorAll("pre code").forEach((block) => {
            hljs.highlightElement(block);
            const pre = block.parentElement;
            if (pre && pre.tagName === "PRE" && !pre.querySelector(".code-toolbar")) {
                addCodeToolbar(pre, block);
            }
        });
    }

    function addCodeToolbar(pre, code) {
        const lang = (code.className.match(/language-(\w[\w+#-]*)/) || [])[1] || "";
        const toolbar = document.createElement("div");
        toolbar.className = "code-toolbar";
        toolbar.innerHTML = `
            <button class="code-tbtn" data-act="copy" title="复制代码"><i class="ti ti-copy"></i></button>
            <button class="code-tbtn" data-act="save" title="保存为文件"><i class="ti ti-download"></i></button>`;
        pre.appendChild(toolbar);
        if (lang) {
            const langLabel = document.createElement("div");
            langLabel.className = "code-lang";
            langLabel.textContent = displayOfLang(lang);
            pre.appendChild(langLabel);
        }
        toolbar.addEventListener("click", (e) => {
            const btn = e.target.closest(".code-tbtn");
            if (!btn) return;
            const act = btn.dataset.act;
            const text = code.textContent || "";
            if (act === "copy") {
                const write = (navigator.clipboard && navigator.clipboard.writeText)
                    ? navigator.clipboard.writeText(text)
                    : new Promise((resolve, reject) => {
                        const ta = document.createElement("textarea");
                        ta.value = text;
                        document.body.appendChild(ta);
                        ta.select();
                        try { document.execCommand("copy"); resolve(); }
                        catch (err) { reject(err); }
                        ta.remove();
                    });
                write.then(
                    () => {
                        const orig = btn.innerHTML;
                        btn.innerHTML = '<i class="ti ti-check"></i>';
                        clearTimeout(btn._copyTimer);
                        btn._copyTimer = setTimeout(() => { btn.innerHTML = orig; }, 2000);
                    },
                    () => showToast("复制失败", true)
                );
            } else if (act === "save") {
                const ext = extOfLang(lang);
                const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
                const filename = `代码_${ts}.${ext}`;
                const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
            }
        });
    }

    function renderGitGraph(container) {
        if (!container) return;
        // 将 language-gitgraph 代码块转为 mermaid gitGraph 语法
        container.querySelectorAll("pre code.language-gitgraph").forEach(function (codeEl) {
            if (codeEl.dataset.gitgraphRendered) return;
            codeEl.dataset.gitgraphRendered = "1";
            var content = (codeEl.textContent || "").trim();
            if (!content) return;
            // 如果内容不以 gitGraph 开头，自动补齐
            if (!/^gitGraph/i.test(content)) {
                content = "gitGraph\n  " + content.replace(/\n/g, "\n  ");
            }
            codeEl.textContent = content;
            codeEl.classList.remove("language-gitgraph");
            codeEl.classList.add("language-mermaid");
        });
    }

    function renderMermaid(container) {
        if (!window.mermaid) return;
        // marked 输出 <pre><code class="language-mermaid"> → 转为 mermaid 期望的 <pre class="mermaid">
        container.querySelectorAll("pre code.language-mermaid").forEach(code => {
            const pre = code.parentElement;
            pre.className = "mermaid chart-host";
            pre.dataset.mermaidSource = code.textContent;
            pre.textContent = code.textContent;
        });
        const nodes = container.querySelectorAll(".mermaid:not([data-processed])");
        if (nodes.length > 0) {
            mermaid.run({ nodes: [...nodes] }).finally(() => {
                nodes.forEach(n => injectChartToolbar(n));
            });
        }
    }

    function injectChartToolbar(host) {
        if (!host || host.querySelector(".chart-toolbar")) return;
        host.classList.add("chart-host");

        // 准备源码视图 - 存到 host._chartSource（不依赖 dataset 防被覆盖）
        let src = "";
        if (host.classList.contains("mermaid")) {
            src = host.dataset.mermaidSource || "";
            if (!src) {
                // 回退：从 textContent 提取（mermaid 渲染后 textContent 可能是 SVG 的文本）
                const codeEl = host.querySelector("code");
                if (codeEl && codeEl.classList.contains("language-mermaid")) {
                    src = codeEl.textContent;
                }
            }
        } else if (host._echartSource) {
            src = host._echartSource;
        }
        host._chartSource = src;
        const sourcePre = document.createElement("pre");
        sourcePre.className = "chart-source";
        sourcePre.textContent = src;
        host.appendChild(sourcePre);

        // 缩放状态
        host._scale = 1.0;

        const tb = document.createElement("div");
        tb.className = "chart-toolbar";
        tb.innerHTML = `
            <div class="chart-dropdown" data-dropdown="download">
              <div class="chart-dropdown-item" data-act="download-image"><i class="ti ti-photo"></i>下载图片</div>
              <div class="chart-dropdown-item" data-act="copy-image"><i class="ti ti-copy"></i>复制图片</div>
            </div>
            <div class="chart-mode-default">
              <button class="chart-btn" data-act="download" title="下载"><i class="ti ti-download"></i></button>
              <span class="chart-sep"></span>
              <button class="chart-btn" data-act="zoom-out" title="缩小"><i class="ti ti-zoom-out"></i></button>
              <button class="chart-btn" data-act="zoom-in" title="放大"><i class="ti ti-zoom-in"></i></button>
              <button class="chart-btn" data-act="fit" title="适应页面"><i class="ti ti-arrows-maximize"></i></button>
              <button class="chart-btn" data-act="fullscreen" title="全屏查看"><i class="ti ti-maximize"></i></button>
              <span class="chart-sep"></span>
              <button class="chart-btn" data-act="view-code" title="查看代码"><i class="ti ti-code"></i></button>
            </div>
            <div class="chart-mode-code">
              <button class="chart-btn" data-act="copy" title="复制"><i class="ti ti-copy"></i></button>
              <span class="chart-sep"></span>
              <button class="chart-btn" data-act="preview" title="预览"><i class="ti ti-eye"></i></button>
            </div>
        `;
        host.appendChild(tb);

        // 将所有图表原始内容包进 chart-body，方便源码模式整体切换
        const body = document.createElement("div");
        body.className = "chart-body";
        while (host.firstChild) {
            if (host.firstChild === sourcePre || host.firstChild === tb) break;
            body.appendChild(host.firstChild);
        }
        if (body.children.length > 0) {
            host.insertBefore(body, sourcePre);
        }

        const dropdown = tb.querySelector('.chart-dropdown');
        function openDropdown() { dropdown.classList.add("open"); tb.classList.add("dropdown-open"); }
        function closeDropdown() { dropdown.classList.remove("open"); tb.classList.remove("dropdown-open"); }
        tb.querySelector('[data-act="download"]').addEventListener("click", (e) => {
            e.stopPropagation();
            if (dropdown.classList.contains("open")) closeDropdown();
            else openDropdown();
        });
        dropdown.addEventListener("click", (e) => {
            e.stopPropagation();
            const item = e.target.closest(".chart-dropdown-item");
            if (!item) return;
            const act = item.dataset.act;
            closeDropdown();
            if (act === "download-image") downloadChartImage(host);
            else if (act === "copy-image") copyChartImage(host);
        });
        // 全局统一关闭（见下方 global click handler）

        tb.querySelector('[data-act="zoom-out"]').addEventListener("click", () => applyChartScale(host, host._scale - 0.1));
        tb.querySelector('[data-act="zoom-in"]').addEventListener("click", () => applyChartScale(host, host._scale + 0.1));
        tb.querySelector('[data-act="fit"]').addEventListener("click", () => applyChartScale(host, 1.0));
        tb.querySelector('[data-act="fullscreen"]').addEventListener("click", () => toggleChartFullscreen(host));

        tb.querySelector('[data-act="view-code"]').addEventListener("click", (e) => {
            e.stopPropagation();
            closeDropdown();
            const curSrc = host._chartSource || "";
            host._origHeight = host.style.height;
            host.style.height = "auto";
            host.classList.add("show-source");
            tb.classList.add("show-code");
            const cs = host.querySelector(".chart-source");
            if (cs) {
                if (!cs.textContent.trim() && curSrc) {
                    cs.textContent = curSrc;
                }
            }
        });
        tb.querySelector('[data-act="copy"]').addEventListener("click", (e) => {
            e.stopPropagation();
            const text = sourcePre.textContent || "";
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(
                    () => showToast("代码已复制"),
                    () => showToast("复制失败")
                );
            } else {
                showToast("剪贴板不可用");
            }
        });
        tb.querySelector('[data-act="preview"]').addEventListener("click", (e) => {
            e.stopPropagation();
            closeDropdown();
            host.style.height = host._origHeight || "";
            host.classList.remove("show-source");
            tb.classList.remove("show-code");
        });

        // 初始化按钮边界状态（scale=1 → fit 灰掉）
        applyChartScale(host, host._scale);
    }

    function applyChartScale(host, scale) {
        // scale 范围 [0.5, 2]
        scale = Math.max(0.5, Math.min(2, Math.round(scale * 100) / 100));
        host._scale = scale;

        const svg = host.querySelector("svg");
        const canvas = host.querySelector("canvas");

        // 取原始尺寸（首次缓存）
        if (!host._origSize) {
            let bw = 0, bh = 0;
            if (svg) {
                const vb = svg.viewBox && svg.viewBox.baseVal;
                if (vb && vb.width) { bw = vb.width; bh = vb.height; }
                if (!bw) { const r = svg.getBoundingClientRect(); bw = r.width; bh = r.height; }
            } else if (canvas) {
                bw = canvas.offsetWidth; bh = canvas.offsetHeight;
            }
            host._origSize = { w: bw, h: bh };
        }
        const o = host._origSize;

        if (svg) {
            svg.style.width = (o.w * scale) + "px";
            svg.style.height = (o.h * scale) + "px";
            svg.style.maxWidth = scale > 1.001 ? "none" : "";
            svg.style.maxHeight = scale > 1.001 ? "none" : "";
        }
        if (canvas && host._echart) {
            // 首次缓存原始容器高度（echart host 有固定 height 如 360px）
            if (!host._origHostHeight) host._origHostHeight = host.style.height;
            host._echart.resize({ width: Math.round(o.w * scale), height: Math.round(o.h * scale) });
            host.style.height = scale > 1.001 ? (Math.round(o.h * scale)) + "px" : (host._origHostHeight || "");
        }

        // 容器：放大时允许滚动；缩小时还原
        if (scale > 1.001) {
            host.style.overflow = "auto";
            host.classList.add("chart-scaled");
            // 工具栏跟随滚动（全屏模式下工具栏已 fixed，不需要跟随）
            const isFullscreen = host.classList.contains("chart-fullscreen-active");
            if (!host._scrollHandler && !isFullscreen) {
                const tb = host.querySelector(".chart-toolbar");
                host._scrollHandler = () => {
                    if (tb) {
                        tb.style.top = (host.scrollTop + 10) + "px";
                        tb.style.right = (-host.scrollLeft + 10) + "px";
                    }
                };
                host.addEventListener("scroll", host._scrollHandler);
            }
        } else {
            host.style.overflow = "";
            host.classList.remove("chart-scaled");
            if (host._scrollHandler) {
                host.removeEventListener("scroll", host._scrollHandler);
                host._scrollHandler = null;
                const tb = host.querySelector(".chart-toolbar");
                if (tb) { tb.style.top = ""; tb.style.right = ""; }
            }
        }

        // 按钮边界禁用：达到极限值灰掉
        const tb = host.querySelector(".chart-toolbar");
        if (tb) {
            const zOut = tb.querySelector('[data-act="zoom-out"]');
            const zIn = tb.querySelector('[data-act="zoom-in"]');
            const fit = tb.querySelector('[data-act="fit"]');
            // scale=2 时：放大灰掉（已达最大）
            // scale=0.5 时：缩小灰掉（已达最小）
            // scale=1 时：恢复灰掉（已是原始）
            if (zOut) zOut.disabled = scale <= 0.5 + 0.001;
            if (zIn) zIn.disabled = scale >= 2 - 0.001;
            if (fit) fit.disabled = Math.abs(scale - 1) < 0.001;
        }
    }

    function toggleChartFullscreen(host) {
        const isFs = host.classList.contains("chart-fullscreen-active");
        const btn = host.querySelector('.chart-toolbar [data-act="fullscreen"]');
        if (isFs) {
            const onKey = host._fsKey;
            if (onKey) document.removeEventListener("keydown", onKey);
            // FLIP 退出全屏
            flipElement(host, () => {
                host.classList.remove("chart-fullscreen-active");
                if (host._fsParent) {
                    host._fsParent.insertBefore(host, host._fsNext || null);
                    delete host._fsParent; delete host._fsNext;
                }
            });
            if (host._fsScale !== undefined) {
                applyChartScale(host, host._fsScale);
                delete host._fsScale;
            }
            if (host._fsHeight !== undefined) {
                host.style.height = host._fsHeight;
                delete host._fsHeight;
            }
            if (host._echart) {
                const canvas = host.querySelector("canvas");
                if (canvas) { canvas.style.width = ""; canvas.style.height = ""; canvas.removeAttribute("width"); canvas.removeAttribute("height"); }
                const h = parseInt(host.style.height) || 360;
                setTimeout(() => { if (host._echart) host._echart.resize({ width: host.clientWidth, height: h }); }, 100);
            }
            if (btn) { btn.innerHTML = '<i class="ti ti-maximize"></i>'; btn.title = "全屏查看"; }
        } else {
            // 保存状态 + 重置缩放（在 firstRect 捕获之前完成）
            host._fsParent = host.parentNode;
            host._fsNext = host.nextSibling;
            host._fsScale = host._scale || 1.0;
            if (host._scale > 1.001) applyChartScale(host, 1.0);
            if (host._echart) host._fsHeight = host.style.height || host._origHostHeight;
            const tb = host.querySelector(".chart-toolbar");
            // FLIP 进入全屏：所有 DOM 修改在 applyChange 回调内
            flipElement(host, () => {
                if (tb) { tb.style.top = ""; tb.style.right = ""; }
                document.body.appendChild(host);
                if (host._echart) host.style.height = "";
                host.classList.add("chart-fullscreen-active");
            });
            // FLIP 动画结束后 resize ECharts
            if (host._echart) {
                const resize = () => {
                    const canvas = host.querySelector("canvas");
                    if (canvas) { canvas.style.width = ""; canvas.style.height = ""; canvas.removeAttribute("width"); canvas.removeAttribute("height"); }
                    if (host._echart) host._echart.resize({ width: host.clientWidth, height: host.clientHeight });
                };
                host.addEventListener("transitionend", function ecResize() {
                    host.removeEventListener("transitionend", ecResize);
                    resize();
                });
                setTimeout(resize, 350);
            }
            if (btn) { btn.innerHTML = '<i class="ti ti-minimize"></i>'; btn.title = "退出全屏 (Esc)"; }
            const onKey = (e) => { if (e.key === "Escape") { toggleChartFullscreen(host); } };
            host._fsKey = onKey;
            document.addEventListener("keydown", onKey);
        }
    }




    function flipElement(el, applyChange) {
        const firstRect = el.getBoundingClientRect();
        applyChange();
        const lastRect = el.getBoundingClientRect();
        const dx = firstRect.left - lastRect.left;
        const dy = firstRect.top - lastRect.top;
        const sx = firstRect.width / lastRect.width;
        const sy = firstRect.height / lastRect.height;
        el.style.transformOrigin = "top left";
        el.style.transition = "none";
        el.style.transform = `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})`;
        el.offsetWidth;
        el.style.transition = "transform 0.28s cubic-bezier(0.2, 0.8, 0.3, 1)";
        el.style.transform = "";
        const onEnd = () => {
            el.style.transition = "";
            el.style.transform = "";
            el.style.transformOrigin = "";
            el.removeEventListener("transitionend", onEnd);
        };
        el.addEventListener("transitionend", onEnd);
    }

    function flipChart(host, applyClassChange) {
        const firstRect = host.getBoundingClientRect();
        applyClassChange();
        const lastRect = host.getBoundingClientRect();
        const dx = firstRect.left - lastRect.left;
        const dy = firstRect.top - lastRect.top;
        const sx = firstRect.width / lastRect.width;
        const sy = firstRect.height / lastRect.height;
        host.style.transformOrigin = "top left";
        host.style.transition = "none";
        host.style.transform = `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})`;
        host.offsetWidth;
        host.style.transition = "transform 0.22s cubic-bezier(0.2, 0.9, 0.3, 1)";
        host.style.transform = "";
        const onEnd = () => {
            host.style.transition = "";
            host.style.transform = "";
            host.style.transformOrigin = "";
            host.removeEventListener("transitionend", onEnd);
        };
        host.addEventListener("transitionend", onEnd);
    }

    function chartFileName(host, ext) {
        const prefix = host.classList.contains("mermaid") ? "mermaid" : "echarts";
        return prefix + "_" + new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19) + "." + ext;
    }

    async function downloadChartImage(host) {
        const filename = chartFileName(host, "png");
        const canvas = host.querySelector("canvas");
        const src = host._chartSource || "";
        const sz = _chartDisplaySize(host);
        console.log("[chart] downloadChartImage", { isMermaid: host.classList.contains("mermaid"), srcLen: src.length, hasCanvas: !!canvas, hasEchart: !!host._echart, disp: sz });
        try {
            let blob;
            if (host.classList.contains("mermaid") && src && window.mermaid) {
                console.log("[chart] mermaid.render with src:", src.slice(0, 80));
                const result = await mermaid.render("chart-dl-" + Date.now(), src);
                blob = await svgStringToPng(result.svg, sz.w, sz.h);
            } else if (canvas && host._echart) {
                const pr = window.devicePixelRatio || 2;
                console.log("[chart] echarts getDataURL, pixelRatio:", pr);
                blob = dataUrlToBlob(host._echart.getDataURL({ type: "png", pixelRatio: pr, backgroundColor: "#fff" }));
            } else {
                const svg = host.querySelector("svg:not(.chart-source)");
                if (svg) {
                    console.log("[chart] fallback svgToPngBlob, disp:", sz.w, sz.h);
                    blob = await svgToPngBlob(svg, sz.w, sz.h);
                } else {
                    console.warn("[chart] no source, no svg, no echarts");
                    showToast("无可下载内容"); return;
                }
            }
            console.log("[chart] download blob:", blob.size, "bytes");
            triggerDownload(blob, filename);
        } catch (e) {
            console.error("[chart] download failed:", e);
            showToast("下载失败: " + (e.message || e));
        }
    }

    async function copyChartImage(host) {
        const canvas = host.querySelector("canvas");
        const src = host._chartSource || "";
        const sz = _chartDisplaySize(host);
        console.log("[chart] copyChartImage", { isMermaid: host.classList.contains("mermaid"), srcLen: src.length, hasCanvas: !!canvas, hasEchart: !!host._echart, disp: sz });
        try {
            let blob;
            if (host.classList.contains("mermaid") && src && window.mermaid) {
                const result = await mermaid.render("chart-cp-" + Date.now(), src);
                blob = await svgStringToPng(result.svg, sz.w, sz.h);
            } else if (canvas && host._echart) {
                const pr = window.devicePixelRatio || 2;
                blob = dataUrlToBlob(host._echart.getDataURL({ type: "png", pixelRatio: pr, backgroundColor: "#fff" }));
            } else {
                const svg = host.querySelector("svg:not(.chart-source)");
                if (svg) blob = await svgToPngBlob(svg, sz.w, sz.h);
                else { showToast("无可复制内容"); return; }
            }
            if (!navigator.clipboard || !window.ClipboardItem) {
                showToast("浏览器不支持复制图片"); return;
            }
            await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
            showToast("图片已复制");
        } catch (e) {
            console.error("[chart] copy failed:", e);
            showToast("复制失败: " + (e.message || e));
        }
    }

    // 从 SVG 字符串中提取 viewBox 宽高
    function _parseViewBox(svgStr) {
        const m = svgStr.match(/viewBox\s*=\s*["']([^"']+)["']/);
        if (m) {
            const parts = m[1].trim().split(/[\s,]+/);
            return { w: parseFloat(parts[2]) || 0, h: parseFloat(parts[3]) || 0 };
        }
        return { w: 0, h: 0 };
    }

    // 获取图表在当前页面上的实际渲染尺寸（CSS 像素）
    function _chartDisplaySize(host) {
        const svg = host.querySelector("svg:not(.chart-source)");
        const canvas = host.querySelector("canvas");
        if (svg) {
            const r = svg.getBoundingClientRect();
            if (r.width > 0) return { w: Math.round(r.width), h: Math.round(r.height) };
        }
        if (canvas) {
            const r = canvas.getBoundingClientRect();
            if (r.width > 0) return { w: Math.round(r.width), h: Math.round(r.height) };
        }
        const r = host.getBoundingClientRect();
        return { w: Math.round(r.width) || 800, h: Math.round(r.height) || 500 };
    }

    // svgStringToPng: 输入 SVG 字符串 → PNG Blob（按页面实际尺寸输出）
    function svgStringToPng(svgStr, dispW, dispH) {
        const vb = _parseViewBox(svgStr);
        return _svgToPng(svgStr, dispW || vb.w || 800, dispH || vb.h || 500);
    }

    // svgToPngBlob: 输入 DOM SVG 元素 → PNG Blob（按页面实际尺寸输出）
    function svgToPngBlob(svgEl, dispW, dispH) {
        const clone = svgEl.cloneNode(true);
        clone.removeAttribute("style");
        const w = dispW || Math.round(clone.viewBox?.baseVal?.width || svgEl.getBoundingClientRect().width) || 800;
        const h = dispH || Math.round(clone.viewBox?.baseVal?.height || svgEl.getBoundingClientRect().height) || 500;
        clone.setAttribute("width", w);
        clone.setAttribute("height", h);
        let svgStr = new XMLSerializer().serializeToString(clone);
        return _svgToPng(svgStr, w, h);
    }

    // 核心 PNG 转换：base64 data URL + img 挂 body + retina canvas
    function _svgToPng(svgStr, expectW, expectH) {
        return new Promise((resolve, reject) => {
            const cleaned = svgStr.replace(/<\?xml[^?]*\?>/, "").trim();
            let final = cleaned;
            if (!/xmlns=/.test(final)) {
                final = final.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
            }
            if (!/style=/.test(final.split(">")[0] || "")) {
                final = final.replace("<svg", '<svg style="background:#fff"');
            }
            // 用期望的显示尺寸设置 SVG width/height（让浏览器按此渲染）
            if (!/width\s*=/.test(final) && expectW && expectH) {
                final = final.replace("<svg", `<svg width="${expectW}" height="${expectH}"`);
            }

            const base64 = btoa(unescape(encodeURIComponent(final)));
            const dataUrl = "data:image/svg+xml;base64," + base64;

            const img = new Image();
            img.style.cssText = "position:fixed;left:-9999px;top:0;pointer-events:none;";
            document.body.appendChild(img);
            const cleanup = () => { if (img.parentNode) img.parentNode.removeChild(img); };
            img.onload = () => {
                cleanup();
                const pr = window.devicePixelRatio || 2;
                const w = Math.max(1, Math.round(expectW || img.naturalWidth || 800));
                const h = Math.max(1, Math.round(expectH || img.naturalHeight || 500));
                const cvs = document.createElement("canvas");
                cvs.width = w * pr;
                cvs.height = h * pr;
                const ctx = cvs.getContext("2d");
                ctx.scale(pr, pr);
                ctx.fillStyle = "#fff";
                ctx.fillRect(0, 0, w, h);
                ctx.drawImage(img, 0, 0, w, h);
                console.log("[chart] png generated:", cvs.width, "x", cvs.height, "display", w, "x", h, "(pixelRatio", pr, ")");
                cvs.toBlob(b => b ? resolve(b) : reject(new Error("toBlob null")), "image/png");
            };
            img.onerror = (e) => { cleanup(); console.error("[chart] img.onerror, svg head:", final.slice(0, 200)); reject(new Error("image load failed")); };
            img.src = dataUrl;
        });
    }

    function dataUrlToBlob(dataUrl) {
        const [meta, b64] = dataUrl.split(",");
        const mime = /:(.*?);/.exec(meta)[1];
        const bin = atob(b64);
        const arr = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        return new Blob([arr], { type: mime });
    }

    function triggerDownload(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function initMermaidTheme(isDark) {
        if (!window.mermaid) return;
        const common = {
            startOnLoad: false,
            theme: "base",
            fontFamily: "inherit",
            flowchart: { curve: "basis", htmlLabels: false, useMaxWidth: true, padding: 12 },
            sequence: { useMaxWidth: true, mirrorActors: false, boxMargin: 8 },
            gantt: { useMaxWidth: true },
            securityLevel: "loose",
        };
        const themeVariables = isDark ? {
            background: "transparent",
            primaryColor: "#2d3250",
            primaryTextColor: "#e8e8f5",
            primaryBorderColor: "#7c8be8",
            secondaryColor: "#1f3a3a",
            secondaryTextColor: "#d4f1e8",
            secondaryBorderColor: "#5ec4b8",
            tertiaryColor: "#3a2f1a",
            tertiaryTextColor: "#f5e3c4",
            tertiaryBorderColor: "#d4a857",
            lineColor: "#9aa3c7",
            textColor: "#e8e8f5",
            fontSize: "14px",
            edgeLabelBackground: "#1e1e32",
            clusterBkg: "transparent",
            clusterBorder: "#3a3a5e",
            nodeBorder: "#7c8be8",
            mainBkg: "#2d3250",
            secondBkg: "#1f3a3a",
        } : {
            background: "transparent",
            primaryColor: "#eef2ff",
            primaryTextColor: "#1e1e3f",
            primaryBorderColor: "#5468d4",
            secondaryColor: "#ecfdf5",
            secondaryTextColor: "#0f3d2a",
            secondaryBorderColor: "#10b981",
            tertiaryColor: "#fffbeb",
            tertiaryTextColor: "#5b3f0e",
            tertiaryBorderColor: "#f59e0b",
            lineColor: "#64748b",
            textColor: "#1e1e3f",
            fontSize: "14px",
            edgeLabelBackground: "#ffffff",
            clusterBkg: "transparent",
            clusterBorder: "#cbd5e1",
            nodeBorder: "#5468d4",
            mainBkg: "#eef2ff",
            secondBkg: "#ecfdf5",
        };
        try {
            mermaid.initialize({ ...common, themeVariables });
            rerenderMermaid();
        } catch (e) { console.warn("mermaid init failed:", e); }
    }

    function rerenderMermaid() {
        document.querySelectorAll(".mermaid").forEach(node => {
            const src = node.dataset.mermaidSource || node.textContent;
            if (!src) return;
            node.removeAttribute("data-processed");
            node.removeAttribute("data-id");
            node.innerHTML = "";
            node.dataset.mermaidSource = src;
            node.textContent = src;
        });
        const nodes = document.querySelectorAll(".mermaid:not([data-processed])");
        if (nodes.length > 0) {
            try {
                mermaid.run({ nodes: [...nodes] }).finally(() => {
                    nodes.forEach(n => injectChartToolbar(n));
                });
            } catch (e) { console.warn("mermaid rerun failed:", e); }
        }
    }

    function renderEcharts(container) {
        if (!window.echarts) return;
        const isDark = document.documentElement.getAttribute("data-theme") === "dark";
        container.querySelectorAll("pre code.language-echarts").forEach(code => {
            const pre = code.parentElement;
            let opt;
            try {
                opt = JSON.parse(code.textContent);
            } catch (e) {
                // JSON 不完整（可能是流式中间态）或包含函数表达式 → 尝试 JS 对象解析兜底
                try {
                    opt = new Function('return (' + code.textContent + ')')();
                } catch (e2) {
                    // 都不是 → 保留 pre 等下次再试
                    return;
                }
            }
            const wrap = document.createElement("div");
            wrap.className = "ed-echarts";
            wrap.style.height = (typeof opt._height === "number" ? opt._height : 360) + "px";
            delete opt._height;
            pre.replaceWith(wrap);
            const chart = echarts.init(wrap, isDark ? "dark" : null);
            try {
                chart.setOption(opt);
            } catch (e) {
                wrap.textContent = "ECharts 渲染失败: " + e.message;
            }
            wrap._echart = chart;
            wrap._echartSource = code.textContent;
            injectChartToolbar(wrap);
            const ro = new ResizeObserver(() => chart.resize());
            ro.observe(wrap);
            // 实例上挂 RO 避免被 GC
            wrap._echartsRO = ro;
            wrap._echartsInstance = chart;
        });
    }

    // 表格 → 对齐文本（中文按 2 字符宽，英文按 1，空格填充对齐）
    function formatTableText(columns, rows) {
        const CJK = /[　-〿一-鿿＀-￯豈-﫿]/;
        function dispW(s) {
            let w = 0;
            for (const ch of String(s)) w += CJK.test(ch) ? 2 : 1;
            return w;
        }
        function pad(s, w) {
            const str = String(s);
            const d = w - dispW(str);
            return d > 0 ? str + " ".repeat(d) : str;
        }
        const headers = columns.map(c => c.title || c.field || "");
        const widths = headers.map(h => dispW(h));
        const dataRows = rows.map(r => columns.map(c => {
            const v = r == null ? undefined : r[c.field];
            return v == null ? "" : String(v);
        }));
        dataRows.forEach(row => {
            row.forEach((s, i) => {
                const w = dispW(s);
                if (w > widths[i]) widths[i] = w;
            });
        });
        const lines = [headers.map((h, i) => pad(h, widths[i])).join("  ")];
        dataRows.forEach(row => lines.push(row.map((s, i) => pad(s, widths[i])).join("  ")));
        return lines.join("\n");
    }

    function renderTable(container) {
        container.querySelectorAll("pre code.language-table").forEach(code => {
            const pre = code.parentElement;
            let opt;
            try {
                opt = JSON.parse(code.textContent);
            } catch (e) {
                // JSON 不完整（流式中间态）→ 保留 pre 等下次再试
                return;
            }
            if (!Array.isArray(opt.columns) || !Array.isArray(opt.data)) return;

            const state = {
                page: 1,
                pageSize: typeof opt._pageSize === "number" ? opt._pageSize : 20,
                sortField: null,
                sortDir: null  // 'asc' | 'desc' | null
            };

            const wrap = document.createElement("div");
            wrap.className = "ed-table";
            wrap._tableOpt = opt;  // 保存原始数据，供导出使用
            pre.replaceWith(wrap);

            const columns = opt.columns;
            const allData = opt.data;

            // 顶部按钮事件委托（避免重新 render 后失绑）
            wrap.addEventListener("click", (e) => {
                const btn = e.target.closest(".ed-table-action-btn");
                if (!btn) return;
                const act = btn.dataset.act;
                if (act === "copy") copyTableAsText();
                else if (act === "download") downloadTableAsXlsx();
                else if (act === "fullscreen") toggleFullscreen();
            });

            function sortedData() {
                if (!state.sortField || !state.sortDir) return allData;
                const f = state.sortField;
                const dir = state.sortDir === "asc" ? 1 : -1;
                return [...allData].sort((a, b) => {
                    const va = a == null ? undefined : a[f];
                    const vb = b == null ? undefined : b[f];
                    if (va == null && vb == null) return 0;
                    if (va == null) return 1;
                    if (vb == null) return -1;
                    if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
                    return String(va).localeCompare(String(vb), "zh") * dir;
                });
            }

            function render() {
                const total = allData.length;
                const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
                if (state.page > totalPages) state.page = totalPages;
                if (state.page < 1) state.page = 1;

                const rows = sortedData();
                const start = (state.page - 1) * state.pageSize;
                const pageRows = rows.slice(start, start + state.pageSize);

                // 表头
                let thead = "";
                columns.forEach(col => {
                    const sortable = col.sortable === true;
                    const cls = ["ed-th"];
                    if (sortable) cls.push("ed-th-sortable");
                    if (state.sortField === col.field && state.sortDir) cls.push("sorted-" + state.sortDir);
                    const arrow = state.sortField === col.field
                        ? (state.sortDir === "asc" ? " ▲" : state.sortDir === "desc" ? " ▼" : "")
                        : "";
                    const align = col.align || "left";
                    const style = col.width ? `text-align:${align};width:${col.width}` : `text-align:${align}`;
                    thead += `<th class="${cls.join(" ")}" style="${style}"${sortable ? ` data-field="${escapeHtml(col.field || "")}"` : ""}>${escapeHtml(col.title || col.field || "")}${arrow}</th>`;
                });

                // 表体
                let tbody = "";
                if (pageRows.length === 0) {
                    tbody = `<tr><td class="ed-table-empty" colspan="${columns.length}">无数据</td></tr>`;
                } else {
                    pageRows.forEach((row, idx) => {
                        let tds = "";
                        columns.forEach(col => {
                            const v = row == null ? undefined : row[col.field];
                            const align = col.align || "left";
                            const txt = v == null ? "" : escapeHtml(String(v));
                            tds += `<td style="text-align:${align}">${txt}</td>`;
                        });
                        tbody += `<tr class="${idx % 2 === 1 ? "ed-table-alt" : ""}">${tds}</tr>`;
                    });
                }

                // 分页栏
                const sizeOpts = [10, 20, 50, 100];
                if (!sizeOpts.includes(state.pageSize)) {
                    sizeOpts.push(state.pageSize);
                    sizeOpts.sort((a, b) => a - b);
                }
                const sizeOptHtml = sizeOpts.map(n =>
                    `<option value="${n}" ${n === state.pageSize ? "selected" : ""}>${n}</option>`
                ).join("");

                const isFs = wrap.classList.contains("ed-table-fullscreen-active");
                wrap.innerHTML = `
                    <div class="ed-table-title">
                        <span class="ed-table-title-text">${opt.title ? escapeHtml(opt.title) : ""}</span>
                        <div class="ed-table-actions">
                            <button class="ed-table-action-btn" data-act="copy" title="复制为对齐文本"><i class="ti ti-copy"></i></button>
                            <button class="ed-table-action-btn" data-act="download" title="下载为 xlsx"><i class="ti ti-download"></i></button>
                            <button class="ed-table-action-btn" data-act="fullscreen" title="${isFs ? "退出全屏 (Esc)" : "全屏预览"}"><i class="ti ${isFs ? "ti-minimize" : "ti-maximize"}"></i></button>
                        </div>
                    </div>
                    <div class="ed-table-scroll">
                        <table>
                            <thead><tr>${thead}</tr></thead>
                            <tbody>${tbody}</tbody>
                        </table>
                    </div>
                    <div class="ed-table-pager">
                        <span class="ed-table-info">共 ${total} 条</span>
                        <span class="ed-table-info">第 ${state.page}/${totalPages} 页</span>
                        <button class="ed-table-btn" data-act="prev" ${state.page <= 1 ? "disabled" : ""}>‹ 上页</button>
                        <button class="ed-table-btn" data-act="next" ${state.page >= totalPages ? "disabled" : ""}>下页 ›</button>
                        <span class="ed-table-jump">跳转 <input type="number" class="ed-table-input" min="1" max="${totalPages}" value="${state.page}" data-act="jump"> 页</span>
                        <span class="ed-table-pagesize">每页 <select class="ed-table-input" data-act="pagesize">${sizeOptHtml}</select></span>
                    </div>
                `;

                // 排序点击
                wrap.querySelectorAll(".ed-th-sortable").forEach(th => {
                    th.addEventListener("click", () => {
                        const f = th.dataset.field;
                        if (state.sortField !== f) {
                            state.sortField = f;
                            state.sortDir = "asc";
                        } else if (state.sortDir === "asc") {
                            state.sortDir = "desc";
                        } else {
                            state.sortField = null;
                            state.sortDir = null;
                        }
                        state.page = 1;
                        render();
                    });
                });
                // 翻页按钮
                wrap.querySelectorAll(".ed-table-btn").forEach(btn => {
                    btn.addEventListener("click", () => {
                        const act = btn.dataset.act;
                        if (act === "prev" && state.page > 1) state.page--;
                        else if (act === "next" && state.page < totalPages) state.page++;
                        render();
                    });
                });
                // 跳页输入
                const jump = wrap.querySelector("input[data-act='jump']");
                if (jump) {
                    jump.addEventListener("change", () => {
                        const p = parseInt(jump.value, 10);
                        if (!isNaN(p) && p >= 1 && p <= totalPages) state.page = p;
                        render();
                    });
                }
                // 每页大小切换
                const sizeSel = wrap.querySelector("select[data-act='pagesize']");
                if (sizeSel) {
                    sizeSel.addEventListener("change", () => {
                        state.pageSize = parseInt(sizeSel.value, 10);
                        state.page = 1;
                        render();
                    });
                }
                // 顶部按钮（复制 / 下载 / 全屏）：事件委托到 wrap，避免重新 render 后失绑
            }

            function copyTableAsText() {
                const text = formatTableText(columns, sortedData());
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(
                        () => showToast("已复制表格到剪贴板"),
                        () => showToast("复制失败", true)
                    );
                } else {
                    const ta = document.createElement("textarea");
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    try { document.execCommand("copy"); showToast("已复制表格到剪贴板"); }
                    catch (e) { showToast("复制失败", true); }
                    ta.remove();
                }
            }

            function downloadTableAsXlsx() {
                if (!window.XLSX) { showToast("xlsx 库未加载", true); return; }
                const rows = sortedData().map(r => {
                    const o = {};
                    columns.forEach(c => {
                        o[c.title || c.field] = r == null ? "" : (r[c.field] == null ? "" : r[c.field]);
                    });
                    return o;
                });
                const ws = XLSX.utils.json_to_sheet(rows);
                const wb = XLSX.utils.book_new();
                XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
                const title = opt.title || ("表格_" + new Date().toISOString().slice(0, 10));
                XLSX.writeFile(wb, title + ".xlsx");
            }

            function toggleFullscreen() {
                const isFs = wrap.classList.contains("ed-table-fullscreen-active");
                if (isFs) {
                    document.removeEventListener("keydown", onKey);
                    updateFsIcon(false);
                    flipElement(wrap, () => {
                        wrap.classList.remove("ed-table-fullscreen-active");
                        if (wrap._fsParent) {
                            wrap._fsParent.insertBefore(wrap, wrap._fsNext || null);
                            delete wrap._fsParent; delete wrap._fsNext;
                        }
                    });
                } else {
                    wrap._fsParent = wrap.parentNode;
                    wrap._fsNext = wrap.nextSibling;
                    updateFsIcon(true);
                    flipElement(wrap, () => {
                        document.body.appendChild(wrap);
                        wrap.classList.add("ed-table-fullscreen-active");
                        // 清除 updateChartToolbarPositions 设置的 sticky transform 偏移
                        wrap.querySelector(".ed-table-title")?.style.removeProperty("transform");
                        wrap.querySelector("thead")?.style.removeProperty("transform");
                    });
                    document.addEventListener("keydown", onKey);
                }
            }
            function updateFsIcon(isFs) {
                const btn = wrap.querySelector('.ed-table-action-btn[data-act="fullscreen"]');
                if (!btn) return;
                btn.innerHTML = isFs ? '<i class="ti ti-minimize"></i>' : '<i class="ti ti-maximize"></i>';
                btn.title = isFs ? "退出全屏 (Esc)" : "全屏预览";
            }
            const onKey = (e) => { if (e.key === "Escape") toggleFullscreen(); };

            render();
        });
    }

    // ── DOM 操作 ──
    function appendUserMessage(text) {
        hideWelcome();
        const div = document.createElement("div");
        div.className = "message message-user";
        div.innerHTML = `<div class="message-content">${escapeHtml(text)}</div>${_userMsgActionsHtml()}`;
        _bindUserMsgActions(div, text);
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
        div.innerHTML = `<div class="message-content">${escapeHtml(text)}${imagesHtml}</div>${_userMsgActionsHtml()}`;
        _bindUserMsgActions(div, text);
        $messages.appendChild(div);
        scrollToBottom();
    }

    function _userMsgActionsHtml() {
        return `<div class="message-user-actions">
            <button class="msg-action-btn" data-act="copy" title="复制"><i class="ti ti-copy"></i></button>
            <button class="msg-action-btn" data-act="edit" title="编辑"><i class="ti ti-edit"></i></button>
        </div>`;
    }

    function _bindUserMsgActions(div, text) {
        div.addEventListener("click", (e) => {
            const btn = e.target.closest(".msg-action-btn");
            if (!btn) return;
            const act = btn.dataset.act;
            if (act === "copy") {
                const writeText = (navigator.clipboard && navigator.clipboard.writeText)
                    ? navigator.clipboard.writeText(text)
                    : new Promise((resolve, reject) => {
                        const ta = document.createElement("textarea");
                        ta.value = text;
                        document.body.appendChild(ta);
                        ta.select();
                        try { document.execCommand("copy"); resolve(); }
                        catch (err) { reject(err); }
                        ta.remove();
                    });
                writeText.then(
                    () => {
                        const orig = btn.innerHTML;
                        btn.innerHTML = '<i class="ti ti-check"></i>';
                        btn.classList.add("copied");
                        clearTimeout(btn._copyTimer);
                        btn._copyTimer = setTimeout(() => {
                            btn.innerHTML = orig;
                            btn.classList.remove("copied");
                        }, 2000);
                    },
                    () => showToast("复制失败", true)
                );
            } else if (act === "edit") {
                $input.value = text;
                $input.focus();
                $input.dispatchEvent(new Event("input", { bubbles: true }));
                $input.scrollIntoView({ behavior: "smooth", block: "center" });
            }
        });
    }

    function appendAssistantMessage() {
        hideWelcome();
        const div = document.createElement("div");
        div.className = "message message-assistant";
        div.innerHTML = `<div class="message-content"></div><div class="message-assistant-actions">
            <button class="msg-action-btn" data-act="copy" title="复制"><i class="ti ti-copy"></i></button>
            <button class="msg-action-btn" data-act="speak" title="朗读"><i class="ti ti-volume-2"></i></button>
            <button class="msg-action-btn" data-act="like" title="点赞"><i class="ti ti-thumb-up"></i></button>
            <button class="msg-action-btn" data-act="dislike" title="拉胯"><i class="ti ti-thumb-down"></i></button>
        </div>`;
        div.addEventListener("click", (e) => {
            const btn = e.target.closest(".msg-action-btn");
            if (!btn) return;
            const act = btn.dataset.act;
            if (act === "like" || act === "dislike") {
                const otherAct = act === "like" ? "dislike" : "like";
                const otherBtn = div.querySelector(`.msg-action-btn[data-act="${otherAct}"]`);
                if (btn.classList.contains("active")) {
                    btn.classList.remove("active");
                    if (otherBtn) otherBtn.style.display = "";
                } else {
                    btn.classList.add("active");
                    if (otherBtn) {
                        otherBtn.style.display = "none";
                        otherBtn.classList.remove("active");
                    }
                }
                return;
            }
            if (act === "copy") {
                const content = div.querySelector(".message-content");
                const text = content.innerText || content.textContent || "";
                const writeText = (navigator.clipboard && navigator.clipboard.writeText)
                    ? navigator.clipboard.writeText(text)
                    : new Promise((resolve, reject) => {
                        const ta = document.createElement("textarea");
                        ta.value = text;
                        document.body.appendChild(ta);
                        ta.select();
                        try { document.execCommand("copy"); resolve(); }
                        catch (err) { reject(err); }
                        ta.remove();
                    });
                writeText.then(
                    () => {
                        const orig = btn.innerHTML;
                        btn.innerHTML = '<i class="ti ti-check"></i>';
                        clearTimeout(btn._copyTimer);
                        btn._copyTimer = setTimeout(() => { btn.innerHTML = orig; }, 2000);
                    },
                    () => showToast("复制失败", true)
                );
            } else if (act === "speak") {
                showToast("暂未支持朗读");
            }
        });
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

    function renderDiffBlocks(container) {
        if (!container) return;
        container.querySelectorAll("pre code.language-diff").forEach(function (codeEl) {
            if (codeEl.dataset.diffRendered) return;
            codeEl.dataset.diffRendered = "1";
            var text = codeEl.textContent || "";
            var lines = text.split("\n");
            var diffEl = document.createElement("div");
            diffEl.className = "diff-view";
            var lineNum = 0;
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i];
                if (!line && i === lines.length - 1) continue;
                if (line.indexOf("---") === 0 || line.indexOf("+++") === 0) continue;
                var match = line.match(/^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/);
                if (match) { lineNum = parseInt(match[1], 10) - 1; continue; }
                if (line.indexOf("+") === 0) {
                    lineNum++;
                    var row = document.createElement("div");
                    row.className = "diff-line diff-added";
                    row.innerHTML = '<span class="diff-ln">' + String(lineNum) + '</span><span class="diff-prefix">+</span><span class="diff-text">' + escapeHtml(line.slice(1)) + '</span>';
                    diffEl.appendChild(row);
                } else if (line.indexOf("-") === 0) {
                    var row = document.createElement("div");
                    row.className = "diff-line diff-removed";
                    row.innerHTML = '<span class="diff-ln"></span><span class="diff-prefix">-</span><span class="diff-text">' + escapeHtml(line.slice(1)) + '</span>';
                    diffEl.appendChild(row);
                } else if (line.indexOf(" ") === 0) {
                    lineNum++;
                }
            }
            var pre = codeEl.closest("pre");
            if (pre) pre.replaceWith(diffEl);
        });
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
    let _scrollBtnHideTimer = null;
    function _showScrollBtn() {
        if (!$scrollBottomBtn) return;
        $scrollBottomBtn.classList.remove("hidden");
        if (_scrollBtnHideTimer) clearTimeout(_scrollBtnHideTimer);
        _scrollBtnHideTimer = setTimeout(() => {
            $scrollBottomBtn.classList.add("hidden");
            _scrollBtnHideTimer = null;
        }, 3000);
    }
    function _hideScrollBtnNow() {
        if (!$scrollBottomBtn) return;
        $scrollBottomBtn.classList.add("hidden");
        if (_scrollBtnHideTimer) { clearTimeout(_scrollBtnHideTimer); _scrollBtnHideTimer = null; }
    }
    if ($scrollBottomBtn && $chatScroll) {
        $scrollBottomBtn.addEventListener("click", () => { _hideScrollBtnNow(); scrollToBottom(true); });
        $chatScroll.addEventListener("scroll", () => {
            const atBottom = $chatScroll.scrollHeight - $chatScroll.scrollTop - $chatScroll.clientHeight < 80;
            _userScrolledUp = !atBottom;
            if (atBottom) _hideScrollBtnNow();
        });
        $chatScroll.addEventListener("wheel", () => { if (_userScrolledUp) _showScrollBtn(); });
        $chatScroll.addEventListener("touchmove", () => { if (_userScrolledUp) _showScrollBtn(); });
        document.addEventListener("keydown", (e) => {
            if (!_userScrolledUp) return;
            const k = e.key;
            if (k === "ArrowUp" || k === "ArrowDown" || k === "PageUp" || k === "PageDown" || k === "Home" || k === "End") {
                _showScrollBtn();
            }
        });
        $chatScroll.addEventListener("scroll", () => {
            requestAnimationFrame(updateChartToolbarPositions);
        }, { passive: true });
        window.addEventListener("resize", updateChartToolbarPositions);
    }

    function updateChartToolbarPositions() {
        if (!$chatScroll) return;
        const chatRect = $chatScroll.getBoundingClientRect();
        const TOP_OFFSET = 10;
        const TB_HEIGHT = 40;
        const BEFORE_HEIGHT = 32;
        const STICK_OFFSET = 0;
        document.querySelectorAll(".chart-host:not(.chart-fullscreen-active)").forEach(host => {
            const tb = host.querySelector(".chart-toolbar");
            if (!tb) return;
            const rect = host.getBoundingClientRect();
            // chart-host 顶部已滚入视口上方，且底部仍有空间 → toolbar 跟随视口顶部
            if (rect.top < chatRect.top + TOP_OFFSET && rect.bottom > chatRect.top + TOP_OFFSET + TB_HEIGHT) {
                const offset = chatRect.top + TOP_OFFSET - rect.top;
                tb.style.top = offset + "px";
            } else {
                tb.style.top = TOP_OFFSET + "px";
            }
        });
        // 代码块：贴 chatRect.top，避免内容从顶部缝隙露出
        document.querySelectorAll(".message-content pre:not(.mermaid)").forEach(pre => {
            const rect = pre.getBoundingClientRect();
            if (rect.top < chatRect.top + STICK_OFFSET && rect.bottom > chatRect.top + STICK_OFFSET + BEFORE_HEIGHT) {
                const offset = Math.max(0, chatRect.top + STICK_OFFSET - rect.top);
                pre.style.setProperty("--pre-sticky-top", offset + "px");
            } else {
                pre.style.setProperty("--pre-sticky-top", "0px");
            }
        });
        // 分页表格：title + 表头一起跟随，贴 chatRect.top
        document.querySelectorAll(".ed-table:not(.ed-table-fullscreen-active)").forEach(tbl => {
            const title = tbl.querySelector(".ed-table-title");
            const thead = tbl.querySelector("thead");
            if (!title || !thead) return;
            const rect = tbl.getBoundingClientRect();
            // 表格底部还需大于固定栏占用区域（约 title 高度 + 表头高度 + 缓冲）
            if (rect.top < chatRect.top + STICK_OFFSET && rect.bottom > chatRect.top + STICK_OFFSET + 80) {
                const offset = Math.max(0, chatRect.top + STICK_OFFSET - rect.top);
                title.style.transform = `translateY(${offset}px)`;
                thead.style.transform = `translateY(${offset}px)`;
            } else {
                title.style.transform = "";
                thead.style.transform = "";
            }
        });
    }

    // ── 发送 ──
    function sendTask() {
        if (!notificationsEnabled) requestNotificationPermission();
        if (voiceActive) stopVoiceInput();
        const text = $input.value.trim();
        const hasImages = pendingImages.length > 0;

        if (!text && !hasImages) return;
        hasSentMessage = true;

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
        if (busy && voiceActive) stopVoiceInput();
        $micBtn.classList.toggle("hidden", (hasText && !voiceActive) || busy);
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
        $modeIndicator.innerHTML = `<i class="ti ti-wand"></i><span>${planMode ? "plan" : "auto"}</span>`;
        $modeIndicator.className = "db-tool-btn" + (planMode ? " active" : "");
        $modeIndicator.title = "点击切换 Plan/Auto 模式";
    }

    // ── 模型选择器 ──
    // 认证请求辅助函数
    function authFetch(url, options = {}) {
        const headers = options.headers || {};
        headers["Authorization"] = `Bearer ${authToken}`;
        options.headers = headers;
        return fetch(url, options);
    }

    async function loadModels() {
        try {
            const resp = await authFetch("/api/models");
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
    // ── Emoji 数据 ──
    const EMOJI_LIST = [
        ["😀",":grinning:","笑脸"],["😂",":joy:","笑哭"],["🤣",":rofl:","笑倒"],["😊",":blush:","害羞"],
        ["😍",":heart_eyes:","爱心眼"],["😘",":kissing:","亲吻"],["😜",":stuck_out_tongue:","吐舌"],
        ["🤔",":thinking:","思考"],["🤨",":raised_eyebrow:","挑眉"],["😎",":sunglasses:","墨镜"],
        ["😢",":cry:","哭泣"],["😡",":rage:","愤怒"],["🤯",":exploding_head:","爆炸头"],
        ["🥳",":partying:","派对"],["🤗",":hugging:","拥抱"],["🤝",":handshake:","握手"],
        ["👍",":+1:","赞"],["👎",":-1:","踩"],["👏",":clap:","鼓掌"],["🙏",":pray:","祈祷"],
        ["💪",":muscle:","肌肉"],["🧠",":brain:","大脑"],["💡",":bulb:","灯泡"],["🔥",":fire:","火"],
        ["⭐",":star:","星星"],["🚀",":rocket:","火箭"],["🎉",":tada:","庆祝"],["🎯",":dart:","靶心"],
        ["✅",":white_check_mark:","完成"],["❌",":x:","错误"],["⚠️",":warning:","警告"],
        ["🔴",":red_circle:","红圆"],["🟢",":green_circle:","绿圆"],["🔵",":blue_circle:","蓝圆"],
        ["🟡",":yellow_circle:","黄圆"],["⚡",":zap:","闪电"],["🐛",":bug:","Bug"],["🔧",":wrench:","扳手"],
        ["💻",":computer:","电脑"],["📱",":phone:","手机"],["📊",":bar_chart:","图表"],
        ["📝",":memo:","备忘"],["🔍",":mag:","搜索"],["🔗",":link:","链接"],["📌",":pushpin:","图钉"],
        ["🗑️",":wastebasket:","删除"],["➕",":heavy_plus_sign:","加号"],["➖",":heavy_minus_sign:","减号"],
        ["▶️",":arrow_forward:","播放"],["⏸️",":pause_button:","暂停"],["⏹️",":stop_button:","停止"],
        ["🔊",":loud_sound:","音量"],["🔇",":mute:","静音"],["🎵",":musical_note:","音符"],
        ["📁",":file_folder:","文件夹"],["📄",":page_facing_up:","文件"],["🗂️",":card_index_dividers:","归档"],
        ["💾",":floppy_disk:","保存"],["🖨️",":printer:","打印"],["📧",":email:","邮件"],
        ["🌍",":earth_africa:","地球"],["🏠",":house:","家"],["🛠️",":tools:","工具"],
        ["🎨",":art:","调色板"],["💰",":moneybag:","钱袋"],["📈",":chart_with_upwards_trend:","上涨"],
        ["🧪",":test_tube:","试管"],["🔒",":lock:","锁"],["🔓",":unlock:","开锁"],
        ["🤖",":robot:","机器人"],["✨",":sparkles:","闪光"],["💬",":speech_balloon:","对话气泡"],
        ["🧵",":thread:","串"],["📦",":package:","包"],["🎁",":gift:","礼物"],
        ["♻️",":recycle:","回收"],["💯",":100:","一百分"],["👀",":eyes:","眼睛"],
    ];

    function updateAutocomplete() {
        var text = $input.value;
        var caretPos = $input.selectionStart || 0;
        var beforeCaret = text.slice(0, caretPos);

        // 检测 :keyword 模式（冒号后在词内）
        var emojiMatch = beforeCaret.match(/(^|[^:]):(\w{1,20})$/);
        if (emojiMatch) {
            var query = emojiMatch[2].toLowerCase();
            var matches = EMOJI_LIST.filter(function (e) {
                return e[1].slice(1, -1).indexOf(query) !== -1 || e[2].indexOf(query) !== -1;
            }).slice(0, 10);
            if (matches.length > 0) {
                var colonPos = beforeCaret.lastIndexOf(":" + query);
                showEmojiPicker(matches, colonPos, 1 + query.length + 1);
                return;
            }
        }

        if (!text.startsWith("/")) { hideAutocomplete(); return; }

        var parts = text.split(/\s+/);
        var cmdPart = parts[0].toLowerCase();

        if (parts.length === 1) {
            var cmdMatches = Object.keys(commands).filter(function (c) { return c.startsWith(cmdPart); });
            if (cmdMatches.length === 0 || (cmdMatches.length === 1 && cmdMatches[0] === cmdPart)) {
                hideAutocomplete();
                return;
            }
            showAutocomplete(cmdMatches.map(function (c) { return { value: c, label: c, desc: commands[c] }; }));
        } else {
            hideAutocomplete();
        }
    }

    function showEmojiPicker(emojis, startPos, matchLen) {
        var ac = $autocomplete;
        ac.innerHTML = "";
        emojis.forEach(function (e) {
            var div = document.createElement("div");
            div.className = "ac-item emoji-item";
            div.innerHTML = '<span class="emoji-char">' + e[0] + '</span> <span class="ac-label">' + escapeHtml(e[1]) + '</span><span class="ac-desc">' + escapeHtml(e[2]) + '</span>';
            div.addEventListener("mousedown", function (ev) {
                ev.preventDefault();
                var text = $input.value;
                $input.value = text.slice(0, startPos) + e[0] + " " + text.slice(startPos + matchLen);
                hideAutocomplete();
                autoResize();
                $input.focus();
            });
            ac.appendChild(div);
        });
        ac.classList.remove("hidden");
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
        try {
            const resp = await authFetch("/api/sessions");
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
                                renderDiffBlocks(el.querySelector(".message-content"));
                                renderSvgBlocks(el.querySelector(".message-content"));
                                renderGitGraph(el.querySelector(".message-content"));
                                renderMermaid(el.querySelector(".message-content"));
                                renderEcharts(el.querySelector(".message-content"));
                                renderTable(el.querySelector(".message-content"));
                                renderVideoLinks(el.querySelector(".message-content"));
                                renderDocLinks(el.querySelector(".message-content"));
                                renderAudioLinks(el.querySelector(".message-content"));
                                renderImageLinks(el.querySelector(".message-content"));
                                renderDownloadLinks(el.querySelector(".message-content"));
                                renderExternalDownloads(el.querySelector(".message-content"));
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
                                renderDiffBlocks(el.querySelector(".message-content"));
                                renderSvgBlocks(el.querySelector(".message-content"));
                                renderGitGraph(el.querySelector(".message-content"));
                                renderMermaid(el.querySelector(".message-content"));
                                renderEcharts(el.querySelector(".message-content"));
                                renderTable(el.querySelector(".message-content"));
                                renderVideoLinks(el.querySelector(".message-content"));
                                renderDocLinks(el.querySelector(".message-content"));
                                renderAudioLinks(el.querySelector(".message-content"));
                                renderImageLinks(el.querySelector(".message-content"));
                                renderDownloadLinks(el.querySelector(".message-content"));
                                renderExternalDownloads(el.querySelector(".message-content"));
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
                    renderDiffBlocks(el.querySelector(".message-content"));
                    renderSvgBlocks(el.querySelector(".message-content"));
                    renderGitGraph(el.querySelector(".message-content"));
                    renderMermaid(el.querySelector(".message-content"));
                    renderEcharts(el.querySelector(".message-content"));
                    renderTable(el.querySelector(".message-content"));
                                renderVideoLinks(el.querySelector(".message-content"));
                    renderDocLinks(el.querySelector(".message-content"));
                    renderAudioLinks(el.querySelector(".message-content"));
                    renderImageLinks(el.querySelector(".message-content"));
                    renderDownloadLinks(el.querySelector(".message-content"));
                    renderExternalDownloads(el.querySelector(".message-content"));
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
            div.dataset.sid = s.session_id;

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

            const pinBtn = document.createElement("i");
            pinBtn.className = s.pinned ? "ti ti-pin-filled" : "ti ti-pin";
            pinBtn.style.cssText = "font-size:13px;flex-shrink:0;cursor:pointer;opacity:0.25;transition:opacity 0.15s;";
            if (s.pinned) { pinBtn.style.opacity = "0.7"; }
            pinBtn.title = s.pinned ? "取消置顶" : "置顶";
            pinBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                togglePin(s.session_id, !s.pinned);
            });
            div.appendChild(pinBtn);

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

    function confirmNewSession() {
        if (!hasSentMessage) return;
        sendJSON({ action: "new_session" });
    }

    function resumeSession(sid) {
        if (deleteMode) return;
        if (sid === sessionId) return;
        sendJSON({ action: "resume", session_id: sid });
    }

    async function togglePin(sid, pinned) {
        // 动画：置顶图标弹跳 + 会话项高亮闪现
        var sessionItem = document.querySelector('.db-hist[data-sid="' + sid + '"]');
        if (sessionItem) {
            sessionItem.classList.add("pin-highlight");
            setTimeout(function () { sessionItem.classList.remove("pin-highlight"); }, 700);
        }
        var pinIcon = sessionItem ? sessionItem.querySelector(".ti-pin, .ti-pin-filled") : null;
        if (pinIcon) {
            pinIcon.classList.add("pin-animate");
            // 即时更新图标外观
            if (pinned) {
                pinIcon.className = pinIcon.className.replace("ti-pin", "ti-pin-filled");
            } else {
                pinIcon.className = pinIcon.className.replace("ti-pin-filled", "ti-pin");
            }
            pinIcon.style.opacity = pinned ? "0.7" : "0.25";
            pinIcon.title = pinned ? "取消置顶" : "置顶";
            setTimeout(function () { pinIcon.classList.remove("pin-animate"); }, 500);
        }
        try {
            await authFetch("/api/sessions/" + sid, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ pinned: pinned })
            });
            // 延迟刷新列表，等动画完成
            setTimeout(function () { loadSessions(); }, 750);
        } catch (e) {
            showToast("置顶操作失败", true);
        }
    }

    function showBackgroundSessionBubble(sid) {
        var el = $sessionList.querySelector('.db-hist[data-sid="' + sid + '"]');
        if (el) {
            var icon = el.querySelector(".ti-message");
            if (icon) {
                icon.className = "ti ti-check";
                icon.style.color = "var(--accent-green)";
                icon.title = "任务已完成";
                setTimeout(function () {
                    icon.className = "ti ti-message";
                    icon.style.color = "";
                    icon.title = "";
                }, 5000);
            }
        } else {
            // 列表尚未渲染，延迟刷新
            setTimeout(function () { loadSessions(); }, 1000);
        }
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
        authFetch(`/api/sessions`)
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

        const ids = [...selectedSessions];
        let deleted = 0;
        for (const sid of ids) {
            try {
                const resp = await authFetch(`/api/sessions/${sid}`, { method: "DELETE" });
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

    // ── 构建全量表格 HTML（无分页） ──
    function buildFullTableHTML(opt) {
        const columns = opt.columns;
        const allData = opt.data;
        let thead = "";
        columns.forEach(col => {
            const align = col.align || "left";
            const style = col.width ? "text-align:" + align + ";width:" + col.width : "text-align:" + align;
            thead += "<th class=\"ed-th\" style=\"" + style + "\">" + escapeHtml(col.title || col.field || "") + "</th>";
        });
        let tbody = "";
        if (allData.length === 0) {
            tbody = "<tr><td class=\"ed-table-empty\" colspan=\"" + columns.length + "\">无数据</td></tr>";
        } else {
            allData.forEach(function (row, idx) {
                var tds = "";
                columns.forEach(function (col) {
                    var v = row == null ? undefined : row[col.field];
                    var align = col.align || "left";
                    var txt = v == null ? "" : escapeHtml(String(v));
                    tds += "<td style=\"text-align:" + align + "\">" + txt + "</td>";
                });
                tbody += "<tr class=\"" + (idx % 2 === 1 ? "ed-table-alt" : "") + "\">" + tds + "</tr>";
            });
        }
        var titleHTML = opt.title ? "<div class=\"ed-table-title\"><span class=\"ed-table-title-text\">" + escapeHtml(opt.title) + "</span></div>" : "";
        return titleHTML + "<div class=\"ed-table-scroll\"><table><thead><tr>" + thead + "</tr></thead><tbody>" + tbody + "</tbody></table></div>";
    }

    // ── 构建导出 HTML（HTML/PDF 共用） ──
    async function buildExportHTML() {
        const title = sessionTitle || "Octopus Session";
        const theme = document.documentElement.getAttribute("data-theme") || "light";
        const isDark = theme === "dark";

        let mainCSS = "";
        try {
            const resp = await fetch("/static/style.css?v=105");
            mainCSS = await resp.text();
        } catch (e) { /* ignore */ }

        let tablerCSS = "";
        try {
            const resp = await fetch("/static/vendor/tabler-icons.min.css?v=1");
            tablerCSS = await resp.text();
            tablerCSS = tablerCSS.replace(/\.\/fonts\//g, "/static/vendor/fonts/");
        } catch (e) { /* ignore */ }

        const hlLight = document.getElementById("highlight-css-light");
        const hlDark = document.getElementById("highlight-css-dark");
        const hlLightHref = hlLight ? hlLight.href : "";
        const hlDarkHref = hlDark ? hlDark.href : "";

        // 克隆消息区做导出预处理（不破坏实时 DOM）
        const clone = $messages.cloneNode(true);

        // ── 1. ECharts: canvas → img (canvas 的像素数据不随 innerHTML 序列化) ──
        const origCharts = $messages.querySelectorAll(".ed-echarts");
        const cloneCharts = clone.querySelectorAll(".ed-echarts");
        for (let i = 0; i < origCharts.length; i++) {
            const orig = origCharts[i];
            const cl = cloneCharts[i];
            if (!cl || !orig._echart) continue;
            try {
                const bg = isDark ? "#1e1e2e" : "#ffffff";
                const dataUrl = orig._echart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: bg });
                cl.innerHTML = "";
                cl.style.height = "auto";  // 移除固定高度限制
                cl.style.overflow = "visible";
                const img = document.createElement("img");
                img.src = dataUrl;
                img.style.cssText = "max-width:100%;height:auto;display:block;";
                cl.appendChild(img);
            } catch (e) { /* 转换失败则保留原 canvas */ }
        }

        // ── 2. 表格：展开全部行 ──
        const origTables = $messages.querySelectorAll(".ed-table");
        const cloneTables = clone.querySelectorAll(".ed-table");
        for (let i = 0; i < origTables.length; i++) {
            const orig = origTables[i];
            const cl = cloneTables[i];
            if (!cl || !orig._tableOpt) continue;
            cl.innerHTML = buildFullTableHTML(orig._tableOpt);
        }

        // ── 3. 图片 src → data URL（导出 HTML 离线打开时 /images/ 路径无效）──
        const imgEls = clone.querySelectorAll(".ed-image-img, img[src^='/images/'], img[src^='/videos/']");
        for (const img of imgEls) {
            const src = img.getAttribute("src");
            if (!src || !src.startsWith("/")) continue;
            try {
                const resp = await fetch(src);
                if (!resp.ok) continue;
                const blob = await resp.blob();
                const reader = new FileReader();
                const dataUrl = await new Promise(function (resolve, reject) {
                    reader.onload = function () { resolve(reader.result); };
                    reader.onerror = reject;
                    reader.readAsDataURL(blob);
                });
                img.src = dataUrl;
            } catch (e) { /* 转换失败保留原路径 */ }
        }

        // ── 4. 隐藏图表工具栏和源码视图 ──
        clone.querySelectorAll(".chart-toolbar, .chart-source").forEach(function (el) {
            el.style.display = "none";
        });
        // 取消源码模式，确保 chart-body 可见
        clone.querySelectorAll(".chart-host.show-source").forEach(function (el) {
            el.classList.remove("show-source");
        });
        // 取消全屏模式
        clone.querySelectorAll(".ed-table-fullscreen-active, .chart-fullscreen-active").forEach(function (el) {
            el.classList.remove("ed-table-fullscreen-active", "chart-fullscreen-active");
        });

        const messagesHTML = clone.innerHTML;

        return "<!DOCTYPE html>\n"
            + "<html lang=\"zh-CN\"" + (isDark ? " data-theme=\"dark\"" : "") + ">\n"
            + "<head>\n"
            + "<meta charset=\"UTF-8\">\n"
            + "<title>" + escapeHtml(title) + "</title>\n"
            + "<link rel=\"stylesheet\" href=\"" + hlLightHref + "\">\n"
            + (hlDarkHref ? "<link rel=\"stylesheet\" href=\"" + hlDarkHref + "\" disabled>\n" : "")
            + "<style>" + tablerCSS + "</style>\n"
            + "<style>" + mainCSS + "</style>\n"
            + "<style>\n"
            + "  html, body { height: auto !important; overflow: visible !important; "
            + (isDark ? "color-scheme: dark; " : "")
            + "print-color-adjust: exact; -webkit-print-color-adjust: exact; }\n"
            + "  .db-root { height: auto !important; background: transparent !important; }\n"
            + "  .db-main { background: transparent !important; overflow: visible !important; }\n"
            + "  .db-chat { overflow: visible !important; max-height: none !important; flex: auto !important; padding: 8px 0 0 !important; mask-image: none !important; -webkit-mask-image: none !important; }\n"
            + "  .db-welcome { display: none !important; }\n"
            + "  .chart-toolbar, .chart-source, .ed-table-pager, .ed-table-actions { display: none !important; }\n"
            + "  .ed-echarts, .ed-table, .chart-host { page-break-inside: avoid; }\n"
            + "  .message-user { print-color-adjust: exact; -webkit-print-color-adjust: exact; }\n"
            + "  .message-assistant { print-color-adjust: exact; -webkit-print-color-adjust: exact; }\n"
            + "  @media print {\n"
            + "    html, body { print-color-adjust: exact; -webkit-print-color-adjust: exact; background: transparent !important; }\n"
            + "    .db-root { height: auto !important; background: transparent !important; }\n"
            + "    .db-main { background: transparent !important; }\n"
            + "    .db-chat { padding: 8px 0 0 !important; mask-image: none !important; -webkit-mask-image: none !important; }\n"
            + "    .ed-echarts, .ed-table, .chart-host { page-break-inside: avoid; }\n"
            + "    .ed-echarts img { max-width: 100%; }\n"
            + "    .message-user { print-color-adjust: exact; -webkit-print-color-adjust: exact; }\n"
            + "  }\n"
            + "</style>\n"
            + "</head>\n"
            + "<body>\n"
            + "<div class=\"db-root\">\n"
            + "  <div class=\"db-main\">\n"
            + "    <div class=\"db-chat\">\n"
            + "      <div id=\"messages\">" + messagesHTML + "</div>\n"
            + "    </div>\n"
            + "  </div>\n"
            + "</div>\n"
            + "  <div id=\"export-lightbox\" style=\"display:flex;position:fixed;inset:0;z-index:999999;background:rgba(0,0,0,0.92);align-items:center;justify-content:center;opacity:0;visibility:hidden;pointer-events:none;transition:opacity 0.25s ease,visibility 0.25s ease;\">\n"
            + "    <img id=\"export-lightbox-img\" style=\"max-width:92vw;max-height:92vh;object-fit:contain;border-radius:8px;box-shadow:0 24px 80px rgba(0,0,0,0.6);cursor:default;transform:scale(0.85);transition:transform 0.3s cubic-bezier(0.34,1.56,0.64,1);\">\n"
            + "    <button id=\"export-lightbox-close\" style=\"position:absolute;top:16px;right:16px;width:40px;height:40px;border:none;border-radius:50%;background:rgba(255,255,255,0.15);color:#fff;font-size:24px;cursor:pointer;line-height:1;\">&times;</button>\n"
            + "  </div>\n"
            + "  <script>\n"
            + "    (function(){\n"
            + "      var lb=document.getElementById('export-lightbox');\n"
            + "      var lbImg=document.getElementById('export-lightbox-img');\n"
            + "      var lbClose=document.getElementById('export-lightbox-close');\n"
            + "      function open(src){lbImg.src=src;lb.style.opacity='1';lb.style.visibility='visible';lb.style.pointerEvents='auto';lbImg.style.transform='scale(1)';}\n"
            + "      function close(){lb.style.opacity='0';lb.style.visibility='hidden';lb.style.pointerEvents='none';lbImg.style.transform='scale(0.85)';setTimeout(function(){lbImg.src='';},300);}\n"
            + "      lbClose.addEventListener('click',close);\n"
            + "      lb.addEventListener('click',function(e){if(e.target===lb)close();});\n"
            + "      document.addEventListener('keydown',function(e){if(e.key==='Escape')close();});\n"
            + "      var imgs=document.querySelectorAll('img');\n"
            + "      for(var i=0;i<imgs.length;i++){\n"
            + "        imgs[i].style.cursor='pointer';\n"
            + "        imgs[i].addEventListener('click',function(){open(this.src);});\n"
            + "      }\n"
            + "    })();\n"
            + "  </" + "script>\n"
            + "</body>\n"
            + "</html>";
    }

    // ── 导出 HTML ──
    async function exportAsHTML() {
        const html = await buildExportHTML();
        exportFile(html, `session_${sessionId ? sessionId.slice(0, 8) : "export"}.html`, "text/html");
    }

    // ── 导出 PDF（用 Blob URL 加载 iframe 后打印） ──
    async function exportAsPDF() {
        const html = await buildExportHTML();
        const blob = new Blob([html], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        const iframe = document.createElement("iframe");
        iframe.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;border:none;z-index:9999;background:#fff;";
        iframe.src = url;
        var printed = false;
        iframe.onload = function () {
            if (printed) return;
            printed = true;
            setTimeout(function () {
                try {
                    iframe.contentWindow.focus();
                    iframe.contentWindow.print();
                } catch (e) {
                    showSystem("PDF 导出失败: " + e.message);
                }
                setTimeout(function () {
                    document.body.removeChild(iframe);
                    URL.revokeObjectURL(url);
                }, 2000);
            }, 500);
        };
        document.body.appendChild(iframe);
    }

    // ── 导出 HTMLX：交互式全量内联（echarts/mermaid/highlight/marked/purify/xlsx/tabler 全部内联）──
    const RUNNER_JS = `(function(){
        "use strict";
        try{
        var isDark = document.documentElement.getAttribute("data-theme") === "dark";

        function esc(s){
            return String(s==null?"":s).replace(/[&<>"']/g,function(c){
                return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
            });
        }
        function toast(msg,isErr){
            var t=document.createElement("div");
            t.textContent=msg;
            t.style.cssText="position:fixed;left:50%;bottom:30px;transform:translateX(-50%);background:"+(isErr?"#dc2626":"#1e1e2e")+";color:#fff;padding:8px 16px;border-radius:6px;font-size:13px;z-index:999999;box-shadow:0 6px 24px rgba(0,0,0,0.18);";
            document.body.appendChild(t);
            setTimeout(function(){t.style.transition="opacity .3s";t.style.opacity="0";setTimeout(function(){t.remove();},300);},1500);
        }
        function decodeAttr(v){return v?v.replace(/&quot;/g,'"').replace(/&amp;/g,"&").replace(/&lt;/g,"<").replace(/&gt;/g,">"):v;}

        // ── 图片 lightbox ──
        (function(){
            if(document.getElementById("x-lightbox"))return;
            var lb=document.createElement("div");
            lb.id="x-lightbox";
            lb.style.cssText="display:none;position:fixed;inset:0;z-index:999999;background:rgba(0,0,0,.92);align-items:center;justify-content:center;";
            var img=document.createElement("img");
            img.style.cssText="max-width:92vw;max-height:92vh;object-fit:contain;border-radius:8px;box-shadow:0 24px 80px rgba(0,0,0,.6);";
            var cls=document.createElement("button");
            cls.innerHTML="&times;";
            cls.style.cssText="position:absolute;top:16px;right:16px;width:40px;height:40px;border:none;border-radius:50%;background:rgba(255,255,255,.15);color:#fff;font-size:24px;cursor:pointer;line-height:1;";
            lb.appendChild(img);lb.appendChild(cls);
            document.body.appendChild(lb);
            function open(src){img.src=src;lb.style.display="flex";}
            function hide(){lb.style.display="none";img.src="";}
            cls.onclick=hide;
            lb.onclick=function(e){if(e.target===lb)hide();};
            document.addEventListener("keydown",function(e){if(e.key==="Escape")hide();});
            document.querySelectorAll("#messages img").forEach(function(im){
                im.style.cursor="pointer";
                im.onclick=function(){open(im.src);};
            });
        })();

        // ── ECharts 重渲染 ──
        document.querySelectorAll(".ed-echarts[data-x-option]").forEach(function(el){
            var raw=el.getAttribute("data-x-option");
            if(!raw)return;
            el.removeAttribute("data-x-option");
            var opt;
            try{opt=JSON.parse(decodeAttr(raw));}catch(e){el.textContent="ECharts option 解析失败";return;}
            try{
                var chart=window.echarts.init(el,isDark?"dark":null);
                chart.setOption(opt);
                el._echart=chart;
                window.addEventListener("resize",function(){chart.resize({width:el.clientWidth,height:el.clientHeight});});
            }catch(e){el.textContent="ECharts 渲染失败: "+e.message;}
        });

        // ── mermaid 重渲染 ──
        if(window.mermaid){
            try{
                mermaid.initialize({startOnLoad:false,theme:isDark?"dark":"default",securityLevel:"loose"});
                var nodes=Array.from(document.querySelectorAll(".mermaid"));
                nodes.forEach(function(n){
                    n.removeAttribute("data-processed");
                    n.textContent=decodeAttr(n.getAttribute("data-mermaid-source")||"");
                });
                if(nodes.length)mermaid.run({nodes:nodes}).catch(function(e){console.error("mermaid",e);});
            }catch(e){console.error("mermaid init",e);}
        }

        // ── 表格 runner ──
        document.querySelectorAll(".ed-table[data-x-table]").forEach(function(wrap){
            var raw=wrap.getAttribute("data-x-table");
            if(!raw)return;
            wrap.removeAttribute("data-x-table");
            var opt;
            try{opt=JSON.parse(decodeAttr(raw));}catch(e){return;}
            var columns=opt.columns||[];
            var data=opt.data||[];
            var state={page:1,pageSize:typeof opt._pageSize==="number"?opt._pageSize:20,sortField:null,sortDir:null};

            function sortedRows(){
                if(!state.sortField)return data;
                var f=state.sortField,d=state.sortDir==="desc"?-1:1;
                return data.slice().sort(function(a,b){
                    var x=a==null?undefined:a[f],y=b==null?undefined:b[f];
                    if(x==null&&y==null)return 0;
                    if(x==null)return -1*d;
                    if(y==null)return 1*d;
                    if(typeof x==="number"&&typeof y==="number")return (x-y)*d;
                    return String(x).localeCompare(String(y))*d;
                });
            }

            function render(){
                var rows=sortedRows();
                var total=rows.length;
                var totalPages=Math.max(1,Math.ceil(total/state.pageSize));
                if(state.page>totalPages)state.page=totalPages;
                if(state.page<1)state.page=1;
                var start=(state.page-1)*state.pageSize;
                var slice=rows.slice(start,start+state.pageSize);

                var sortClass=function(f){
                    if(state.sortField!==f)return "ed-th-sortable";
                    if(state.sortDir==="asc")return "ed-th-sortable sorted-asc";
                    if(state.sortDir==="desc")return "ed-th-sortable sorted-desc";
                    return "ed-th-sortable";
                };

                var thead=columns.map(function(c){
                    var al=c.align||"left";
                    var st=c.width?("text-align:"+al+";width:"+c.width):("text-align:"+al);
                    return '<th class="ed-th '+sortClass(c.field)+'" data-sort="'+esc(c.field||"")+'" style="'+st+'">'+esc(c.title||c.field||"")+'</th>';
                }).join("");

                var tbody;
                if(slice.length===0){
                    tbody='<tr><td class="ed-table-empty" colspan="'+columns.length+'">无数据</td></tr>';
                }else{
                    tbody=slice.map(function(row,idx){
                        var tds=columns.map(function(c){
                            var v=row==null?undefined:row[c.field];
                            var al=c.align||"left";
                            var txt=v==null?"":esc(String(v));
                            return '<td style="text-align:'+al+'">'+txt+'</td>';
                        }).join("");
                        return '<tr class="'+(idx%2===1?"ed-table-alt":"")+'">'+tds+'</tr>';
                    }).join("");
                }

                var isFs=wrap.classList.contains("ed-table-fullscreen-active");
                var actions='<div class="ed-table-actions">'+
                    '<button class="ed-table-action-btn" data-act="copy" title="复制"><i class="ti ti-copy"></i></button>'+
                    '<button class="ed-table-action-btn" data-act="download" title="下载 CSV"><i class="ti ti-download"></i></button>'+
                    '<button class="ed-table-action-btn" data-act="fullscreen" title="'+(isFs?"退出全屏":"全屏")+'"><i class="ti '+(isFs?"ti-minimize":"ti-maximize")+'"></i></button>'+
                    '</div>';

                var titleHTML='<div class="ed-table-title"><span class="ed-table-title-text">'+esc(opt.title||"")+'</span>'+actions+'</div>';

                wrap.innerHTML=titleHTML+
                    '<div class="ed-table-scroll"><table><thead><tr>'+thead+'</tr></thead><tbody>'+tbody+'</tbody></table></div>'+
                    '<div class="ed-table-pager">'+
                    '<span class="ed-table-info">共 '+total+' 条</span>'+
                    '<span class="ed-table-info">第 '+state.page+'/'+totalPages+' 页</span>'+
                    '<button class="ed-table-btn" data-act="prev" '+(state.page<=1?"disabled":"")+'>‹ 上页</button>'+
                    '<button class="ed-table-btn" data-act="next" '+(state.page>=totalPages?"disabled":"")+'>下页 ›</button>'+
                    '<span class="ed-table-jump">跳转 <input type="number" class="ed-table-input" min="1" max="'+totalPages+'" value="'+state.page+'" data-act="jump"> 页</span>'+
                    '<span class="ed-table-pagesize">每页 <select class="ed-table-input" data-act="pagesize">'+
                        [10,20,50,100].map(function(s){return '<option value="'+s+'"'+(s===state.pageSize?" selected":"")+'>'+s+'</option>';}).join("")+
                    '</select></span>'+
                    '</div>';

                bind();
            }

            function bind(){
                wrap.querySelectorAll(".ed-th[data-sort]").forEach(function(th){
                    th.onclick=function(){
                        var f=th.dataset.sort;
                        if(!f)return;
                        if(state.sortField!==f){state.sortField=f;state.sortDir="asc";}
                        else if(state.sortDir==="asc")state.sortDir="desc";
                        else{state.sortField=null;state.sortDir=null;}
                        state.page=1;
                        render();
                    };
                });
                wrap.querySelectorAll(".ed-table-btn").forEach(function(btn){
                    btn.onclick=function(){
                        var a=btn.dataset.act;
                        if(a==="prev"&&state.page>1)state.page--;
                        else if(a==="next")state.page++;
                        render();
                    };
                });
                var jump=wrap.querySelector("input[data-act=jump]");
                if(jump)jump.onchange=function(){
                    var p=parseInt(jump.value,10);
                    if(!isNaN(p))state.page=p;
                    render();
                };
                var sel=wrap.querySelector("select[data-act=pagesize]");
                if(sel)sel.onchange=function(){
                    state.pageSize=parseInt(sel.value,10);
                    state.page=1;
                    render();
                };
                wrap.querySelectorAll(".ed-table-action-btn").forEach(function(btn){
                    btn.onclick=function(){
                        var a=btn.dataset.act;
                        if(a==="copy")copyText();
                        else if(a==="download")downloadCSV();
                        else if(a==="fullscreen"){wrap.classList.toggle("ed-table-fullscreen-active");render();}
                    };
                });
            }

            function copyText(){
                var rows=sortedRows();
                var lines=[];
                lines.push(columns.map(function(c){return c.title||c.field||"";}).join("\\t"));
                rows.forEach(function(row){
                    lines.push(columns.map(function(c){
                        var v=row==null?undefined:row[c.field];
                        return v==null?"":String(v);
                    }).join("\\t"));
                });
                var txt=lines.join("\\n");
                if(navigator.clipboard&&navigator.clipboard.writeText){
                    navigator.clipboard.writeText(txt).then(function(){toast("已复制");},function(){toast("复制失败",true);});
                }
            }

            function csvCell(s){
                if(/[",\\n]/.test(s))return '"'+s.replace(/"/g,'""')+'"';
                return s;
            }
            function downloadCSV(){
                var rows=sortedRows();
                var csv=[];
                csv.push(columns.map(function(c){return csvCell(c.title||c.field||"");}).join(","));
                rows.forEach(function(row){
                    csv.push(columns.map(function(c){
                        var v=row==null?undefined:row[c.field];
                        return csvCell(v==null?"":String(v));
                    }).join(","));
                });
                var blob=new Blob(["\\ufeff"+csv.join("\\n")],{type:"text/csv;charset=utf-8"});
                var a=document.createElement("a");
                a.href=URL.createObjectURL(blob);
                a.download=(opt.title||"table")+".csv";
                document.body.appendChild(a);a.click();a.remove();
                setTimeout(function(){URL.revokeObjectURL(a.href);},1000);
            }

            render();
        });

        // ── 图表简易工具栏（全屏 + 下载 PNG）──
        document.querySelectorAll(".ed-echarts").forEach(function(el){
            if(el.querySelector(".x-chart-tb"))return;
            if(el.style.position!=="relative")el.style.position="relative";
            var tb=document.createElement("div");
            tb.className="x-chart-tb";
            tb.style.cssText="position:absolute;top:6px;right:6px;display:flex;gap:4px;z-index:10;";
            function btn(icon,title){
                var b=document.createElement("button");
                b.innerHTML='<i class="ti '+icon+'"></i>';
                b.title=title;
                b.style.cssText="background:rgba(255,255,255,.85);border:1px solid #ddd;border-radius:4px;padding:2px 6px;cursor:pointer;font-size:12px;";
                return b;
            }
            var fs=btn("ti-maximize","全屏");
            fs.onclick=function(){
                el.classList.toggle("chart-fullscreen-active");
                if(el._echart)setTimeout(function(){el._echart.resize({width:el.clientWidth,height:el.clientHeight});},50);
            };
            var dl=btn("ti-download","下载 PNG");
            dl.onclick=function(){
                if(!el._echart)return;
                var url=el._echart.getDataURL({type:"png",pixelRatio:2,backgroundColor:isDark?"#1e1e2e":"#fff"});
                var a=document.createElement("a");
                a.href=url;a.download="chart.png";document.body.appendChild(a);a.click();a.remove();
            };
            tb.appendChild(fs);tb.appendChild(dl);
            el.appendChild(tb);
        });

        // ── 全屏 ESC 退出 ──
        document.addEventListener("keydown",function(e){
            if(e.key!=="Escape")return;
            var fs=document.querySelector(".ed-table-fullscreen-active, .chart-fullscreen-active");
            if(!fs)return;
            fs.classList.remove("ed-table-fullscreen-active","chart-fullscreen-active");
            if(fs._echart)setTimeout(function(){fs._echart.resize({width:fs.clientWidth,height:fs.clientHeight});},50);
        });

        }catch(err){
            console.error("[export-runner]",err);
            var t=document.createElement("div");
            t.textContent="runner error: "+(err&&err.message||err);
            t.style.cssText="position:fixed;left:8px;bottom:8px;background:#dc2626;color:#fff;padding:8px 12px;border-radius:4px;font-size:12px;z-index:999999;max-width:90vw;word-break:break-all;";
            document.body.appendChild(t);
        }
    })();`;

    async function exportAsHTMLX() {
        const title = sessionTitle || "Octopus Session";
        const theme = document.documentElement.getAttribute("data-theme") || "light";
        const isDark = theme === "dark";

        // 收集组件原始数据
        const chartData = [];
        const tableData = [];
        const mermaidData = [];

        const origCharts = Array.from($messages.querySelectorAll(".ed-echarts"));
        origCharts.forEach(el => {
            if (el._echart) {
                try { chartData.push(el._echart.getOption()); }
                catch (e) { chartData.push(null); }
            } else chartData.push(null);
        });

        const origTables = Array.from($messages.querySelectorAll(".ed-table"));
        origTables.forEach(el => {
            tableData.push(el._tableOpt || null);
        });

        const origMermaids = Array.from($messages.querySelectorAll(".mermaid"));
        origMermaids.forEach(el => {
            mermaidData.push(el.dataset.mermaidSource || "");
        });

        // 克隆并打标
        const clone = $messages.cloneNode(true);

        const cloneCharts = clone.querySelectorAll(".ed-echarts");
        chartData.forEach((opt, i) => {
            const cl = cloneCharts[i];
            if (!cl) return;
            cl.innerHTML = "";
            if (opt) cl.dataset.xOption = JSON.stringify(opt).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        });

        const cloneTables = clone.querySelectorAll(".ed-table");
        tableData.forEach((opt, i) => {
            const cl = cloneTables[i];
            if (!cl) return;
            cl.innerHTML = "";
            if (opt) cl.dataset.xTable = JSON.stringify(opt).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        });

        const cloneMermaids = clone.querySelectorAll(".mermaid");
        mermaidData.forEach((src, i) => {
            const cl = cloneMermaids[i];
            if (!cl) return;
            cl.removeAttribute("data-processed");
            cl.innerHTML = "";
            if (src) cl.dataset.mermaidSource = src;
        });

        // 取消残留的全屏/源码视图状态
        clone.querySelectorAll(".ed-table-fullscreen-active, .chart-fullscreen-active, .chart-host.show-source")
            .forEach(el => el.classList.remove("ed-table-fullscreen-active", "chart-fullscreen-active", "show-source"));
        // 清掉旧的 chart-toolbar（runner 不复用，由简易工具栏替代）
        clone.querySelectorAll(".chart-toolbar, .code-toolbar").forEach(el => el.remove());

        // fetch vendor
        const fetchText = async (p) => { try { const r = await fetch(p); return await r.text(); } catch (e) { return ""; } };
        const fetchBlob = async (p) => { try { const r = await fetch(p); return await r.blob(); } catch (e) { return null; } };
        const blobToData = (blob) => new Promise((resolve, reject) => {
            const r = new FileReader();
            r.onload = () => resolve(r.result);
            r.onerror = reject;
            r.readAsDataURL(blob);
        });

        const [echartsJs, mermaidJs, hlJs, markedJs, purifyJs, xlsxJs, mainCSS, tablerCSS, hlLightCss, hlDarkCss] = await Promise.all([
            fetchText("/static/vendor/echarts.min.js"),
            fetchText("/static/vendor/mermaid.min.js"),
            fetchText("/static/vendor/highlight.min.js"),
            fetchText("/static/vendor/marked.min.js"),
            fetchText("/static/vendor/purify.min.js"),
            fetchText("/static/vendor/xlsx.full.min.js"),
            fetchText("/static/style.css"),
            fetchText("/static/vendor/tabler-icons.min.css"),
            fetchText("/static/vendor/github.css"),
            fetchText("/static/vendor/github-dark.css"),
        ]);

        // 内联 tabler woff2
        let tablerCSSInlined = tablerCSS;
        const woff2 = await fetchBlob("/static/vendor/fonts/tabler-icons.woff2");
        if (woff2) {
            try {
                const dataUrl = await blobToData(woff2);
                tablerCSSInlined = tablerCSS.replace(/@font-face\{[^}]*tabler-icons[^}]*\}/g, function (m) {
                    return m.replace(/src:[^;}]*[;}]?/, 'src:url("' + dataUrl + '") format("woff2");');
                });
            } catch (e) { /* fallback to raw CSS */ }
        }

        // 内联图片
        const imgEls = clone.querySelectorAll("img[src^='/']");
        for (const img of imgEls) {
            try {
                const r = await fetch(img.getAttribute("src"));
                if (!r.ok) continue;
                const blob = await r.blob();
                img.src = await blobToData(blob);
            } catch (e) { /* keep original */ }
        }

        const messagesHTML = clone.innerHTML;

        const html = "<!DOCTYPE html>\n"
            + "<html lang=\"zh-CN\"" + (isDark ? " data-theme=\"dark\"" : "") + ">\n"
            + "<head>\n"
            + "<meta charset=\"UTF-8\">\n"
            + "<title></title>\n"
            + "<style>" + (isDark ? (hlDarkCss || hlLightCss) : hlLightCss) + "</style>\n"
            + "<style>" + tablerCSSInlined + "</style>\n"
            + "<style>" + mainCSS + "</style>\n"
            + "<style>\n"
            + "  html, body { height: auto !important; overflow: visible !important; " + (isDark ? "color-scheme: dark; background: #1e1e2e; " : "background: #fff;") + "}\n"
            + "  .db-root { height: auto !important; background: transparent !important; display: block !important; }\n"
            + "  .db-main { background: transparent !important; overflow: visible !important; height: auto !important; display: block !important; }\n"
            + "  .db-chat { overflow: visible !important; max-height: none !important; flex: auto !important; padding: 8px 0 0 !important; mask-image: none !important; -webkit-mask-image: none !important; }\n"
            + "  .db-welcome { display: none !important; }\n"
            + "  .ed-echarts, .ed-table, .mermaid { page-break-inside: avoid; }\n"
            + "  .ed-table-fullscreen-active { position: fixed; inset: 0; z-index: 99999; background: #fff; padding: 20px; overflow: auto; }\n"
            + "  [data-theme=\"dark\"] .ed-table-fullscreen-active { background: #1e1e2e; }\n"
            + "  .chart-fullscreen-active { position: fixed; inset: 0; z-index: 99999; background: #fff; padding: 20px; }\n"
            + "  [data-theme=\"dark\"] .chart-fullscreen-active { background: #1e1e2e; }\n"
            + "</style>\n"
            + "</head>\n"
            + "<body>\n"
            + "<div class=\"db-root\">\n"
            + "  <div class=\"db-main\">\n"
            + "    <div class=\"db-chat\">\n"
            + "      <div id=\"messages\">" + messagesHTML + "</div>\n"
            + "    </div>\n"
            + "  </div>\n"
            + "</div>\n"
            + "<script>" + echartsJs + "</" + "script>\n"
            + "<script>" + mermaidJs + "</" + "script>\n"
            + "<script>" + hlJs + "</" + "script>\n"
            + "<script>" + markedJs + "</" + "script>\n"
            + "<script>" + purifyJs + "</" + "script>\n"
            + "<script>" + xlsxJs + "</" + "script>\n"
            + "<script>\n" + RUNNER_JS + "\n</" + "script>\n"
            + "</body>\n"
            + "</html>";

        exportFile(html, `session_${sessionId ? sessionId.slice(0, 8) : "export"}.interactive.html`, "text/html", true);
    }

    // ── 文件下载 ──
    function exportFile(content, filename, mimeType = "text/plain;charset=utf-8", silent = false) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        if (!silent) showSystem(`已导出: ${filename}`);
    }

    // ── 工具函数 ──
    async function loadCommands() {
        try {
            const resp = await authFetch("/api/commands");
            commands = await resp.json();
        } catch (e) { /* ignore */ }
    }

    function updateModelInfo() {
        // $modelInfo 是左下角用户名，不覆盖
        if ($modelBtnText) $modelBtnText.textContent = model || "选择模型";
        $modelBtn.title = "切换模型: " + model;
        if ($agentLabel) $agentLabel.textContent = currentAgent ? `· ${currentAgent}` : "";
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
            } else if (isTextFile(file)) {
                readDroppedTextFile(file);
            } else {
                showToast("不支持: " + (file.name || "未知"), true);
            }
        }
    }

    function isTextFile(file) {
        const textTypes = [
            "text/", "application/json", "application/xml",
            "application/javascript", "application/x-yaml",
            "application/x-sh", "application/x-python",
        ];
        if (textTypes.some(t => file.type.startsWith(t))) return true;
        const ext = (file.name || "").split(".").pop().toLowerCase();
        const textExts = ["txt","md","py","js","ts","jsx","tsx","json","yaml","yml",
            "html","css","scss","xml","sh","bash","zsh","c","h","cpp","java","go",
            "rs","rb","php","sql","toml","ini","cfg","conf","log","csv","env",
            "gitignore","dockerfile","makefile","rst","tex","svg"];
        return textExts.includes(ext);
    }

    function readDroppedTextFile(file) {
        if (file.size > 512 * 1024) {
            showToast("文本文件不能超过 512KB", true);
            return;
        }
        const reader = new FileReader();
        reader.onload = (e) => {
            const content = e.target.result;
            const header = "```" + (file.name || "file") + "\n" + content + "\n```\n\n";
            $input.value = header + $input.value;
            autoResize();
            updateButtons();
            showToast("已导入: " + file.name);
        };
        reader.onerror = () => showToast("读取文件失败: " + file.name, true);
        reader.readAsText(file);
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
        initMermaidTheme(darkMode);
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
        initAuthRelatedEvents();
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
