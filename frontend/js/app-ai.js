        const askAiBtn = document.getElementById('askAiBtn');
        const askAiOverlay = document.getElementById('askAiOverlay');
        const closeAskAiModal = document.getElementById('closeAskAiModal');
        const askAiInput = document.getElementById('askAiInput');
        const askAiResult = document.getElementById('askAiResult');
        const submitAskAiBtn = document.getElementById('submitAskAiBtn');
        const askAiMeta = document.getElementById('askAiMeta');
        const aiChatHistory = document.getElementById('aiChatHistory');
        const aiAgentHistory = document.getElementById('aiAgentHistory');
        const aiChatCount = document.getElementById('aiChatCount');
        const aiAgentCount = document.getElementById('aiAgentCount');
        const aiNewConversationBtn = document.getElementById('aiNewConversationBtn');
        const aiSidebar = document.getElementById('aiSidebar');
        const aiMenuBtn = document.getElementById('aiMenuBtn');
        const aiWelcomeGrid = document.getElementById('aiWelcomeGrid');
        const aiTopbarSubtitle = document.getElementById('aiTopbarSubtitle');
        const aiModeChatBtn = document.getElementById('aiModeChatBtn');
        const aiModeAgentBtn = document.getElementById('aiModeAgentBtn');

        const AI_TOOL_LABELS = {
            search_knowledge_base: '知识库检索',
            search_library_items: '站内内容搜索',
            get_item_details: '读取笔记详情',
            list_recent_notes: '最近笔记',
            get_related_notes: '相关笔记',
            list_folders: '读取文件夹',
            assign_item_folders: '调整文件夹',
            parse_item_content: '内容解析',
            sync_item_to_obsidian: '同步到 Obsidian',
            sync_item_to_notion: '同步到 Notion',
        };
        const AI_MUTATING_TOOLS = new Set([
            'assign_item_folders',
            'parse_item_content',
            'sync_item_to_obsidian',
            'sync_item_to_notion',
        ]);
        const READER_AI_SUGGESTIONS = [
            '总结这条笔记的核心观点',
            '这条内容为什么值得保存？',
            '它和我已有的哪些笔记相关？',
            '给我 3 个值得继续追问的问题',
        ];
        const READER_AI_SESSION_STORAGE_KEY = 'everything-capture.reader-ai.sidebar.v1';
        const AI_CODE_COPY_ICON = `
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <rect x="9" y="9" width="10" height="10" rx="2"></rect>
                <path d="M15 9V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path>
            </svg>
        `;
        const AI_CODE_COPIED_ICON = `
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M20 7 9 18l-5-5"></path>
            </svg>
        `;

        let askAiRequestInFlight = false;
        let readerAiRequestInFlight = false;
        let aiAssistantMode = 'chat';
        // Chat 和 Agent 分别维护独立的对话
        let aiChatConversation = [];
        let aiAgentConversation = [];
        let aiChatConversationId = null;
        let aiAgentConversationId = null;
        // 当前对话的 getter
        Object.defineProperty(window, '_aiCurrentConversation', {
            get: () => aiAssistantMode === 'agent' ? aiAgentConversation : aiChatConversation,
            set: (val) => { if (aiAssistantMode === 'agent') aiAgentConversation = val; else aiChatConversation = val; }
        });
        Object.defineProperty(window, '_aiCurrentConversationId', {
            get: () => aiAssistantMode === 'agent' ? aiAgentConversationId : aiChatConversationId,
            set: (val) => { if (aiAssistantMode === 'agent') aiAgentConversationId = val; else aiChatConversationId = val; }
        });
        // 兼容旧代码
        let aiConversation = [];
        let aiConversationId = null;
        let aiChatConversationHistory = [];
        let aiAgentConversationHistory = [];
        let aiHistorySearchQuery = '';
        let aiHistoryLoading = false;
        let aiHistoryRequestId = 0;
        let aiSettingsLoadPromise = null;
        let currentAiContextItemId = null;
        const readerAiConversationIdByItem = new Map();
        const readerAiConversationLoadedByItem = new Set();
        const readerAiConversationByItem = new Map();
        const readerAiDraftByItem = new Map();
        const aiComposerCompositionState = new WeakMap();

        function normalizeReaderAiItemKey(itemId) {
            return String(itemId ?? '').trim();
        }

        function readReaderAiSessionStore() {
            try {
                const raw = window.sessionStorage?.getItem(READER_AI_SESSION_STORAGE_KEY);
                if (!raw) return {};
                const parsed = JSON.parse(raw);
                return parsed && typeof parsed === 'object' ? parsed : {};
            } catch (error) {
                console.warn('Failed to read reader AI session store', error);
                return {};
            }
        }

        function writeReaderAiSessionStore(nextStore) {
            try {
                window.sessionStorage?.setItem(READER_AI_SESSION_STORAGE_KEY, JSON.stringify(nextStore || {}));
            } catch (error) {
                console.warn('Failed to persist reader AI session store', error);
            }
        }

        function persistReaderAiSessionState(itemId) {
            const key = normalizeReaderAiItemKey(itemId);
            if (!key) return;
            const store = readReaderAiSessionStore();
            const conversation = getReaderAiConversation(key);
            const draft = String(readerAiDraftByItem.get(key) || '');
            if (!conversation.length && !draft) {
                delete store[key];
            } else {
                store[key] = {
                    messages: serializeConversationForSave(conversation).slice(-24),
                    draft,
                };
            }
            writeReaderAiSessionStore(store);
        }

        function loadReaderAiSessionState(itemId) {
            const key = normalizeReaderAiItemKey(itemId);
            if (!key) return;
            const store = readReaderAiSessionStore();
            const saved = store[key];
            if (!saved || typeof saved !== 'object') return;
            const messages = Array.isArray(saved.messages)
                ? saved.messages.map(normalizeStoredConversationMessage)
                : [];
            if (messages.length) {
                readerAiConversationByItem.set(key, messages);
            }
            if (typeof saved.draft === 'string' && saved.draft.trim()) {
                readerAiDraftByItem.set(key, saved.draft);
            }
        }

        async function copyTextToClipboard(value) {
            const text = String(value || '');
            if (!text) return false;
            try {
                if (navigator.clipboard?.writeText && window.isSecureContext) {
                    await navigator.clipboard.writeText(text);
                    return true;
                }
            } catch (error) {
                console.warn('Navigator clipboard copy failed, falling back', error);
            }

            const helper = document.createElement('textarea');
            helper.value = text;
            helper.setAttribute('readonly', 'readonly');
            helper.style.position = 'fixed';
            helper.style.opacity = '0';
            helper.style.pointerEvents = 'none';
            document.body.appendChild(helper);
            helper.focus();
            helper.select();
            let succeeded = false;
            try {
                succeeded = document.execCommand('copy');
            } catch (error) {
                console.warn('execCommand copy failed', error);
            } finally {
                helper.remove();
            }
            return succeeded;
        }

        function createCodeCopyButton() {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'ai-code-copy';
            button.setAttribute('data-ai-copy-code', '');
            button.setAttribute('aria-label', '复制代码');
            button.setAttribute('title', '复制代码');
            button.innerHTML = AI_CODE_COPY_ICON;
            return button;
        }

        function decorateStandaloneCodeBlocks(root = document) {
            const scope = root && typeof root.querySelectorAll === 'function' ? root : document;
            const preElements = scope.querySelectorAll('pre');
            preElements.forEach((pre) => {
                if (!(pre instanceof HTMLElement)) return;
                if (pre.closest('.ai-code-block')) return;
                const codeElement = pre.querySelector('code');
                if (!codeElement) return;
                pre.classList.add('ec-code-block');
                if (pre.dataset.ecCodeDecorated === 'true') return;
                pre.dataset.ecCodeDecorated = 'true';
                pre.appendChild(createCodeCopyButton());
            });
        }

        let codeBlockDecorationQueued = false;
        function queueDecorateStandaloneCodeBlocks(root = document) {
            if (codeBlockDecorationQueued) return;
            codeBlockDecorationQueued = true;
            window.requestAnimationFrame(() => {
                codeBlockDecorationQueued = false;
                decorateStandaloneCodeBlocks(root);
            });
        }

        function syncAiModeUi() {
            aiModeChatBtn?.classList.toggle('is-active', aiAssistantMode === 'chat');
            aiModeAgentBtn?.classList.toggle('is-active', aiAssistantMode === 'agent');
            if (aiTopbarSubtitle) {
                const currentItem = getCurrentAiContextItem();
                aiTopbarSubtitle.textContent = currentItem
                    ? `围绕《${getDisplayItemTitle(currentItem) || '当前内容'}》继续`
                    : (aiAssistantMode === 'agent' ? '按权限执行真实操作' : '基于你的知识库连续对话');
            }
        }

        function setAiComposerComposing(element, isComposing) {
            if (!element) return;
            aiComposerCompositionState.set(element, Boolean(isComposing));
        }

        function isAiComposerComposing(event, element) {
            return Boolean(
                event?.isComposing
                || event?.keyCode === 229
                || event?.which === 229
                || (element && aiComposerCompositionState.get(element))
            );
        }

        function autoResizeAiComposer(textarea, maxHeight = 120) {
            if (!textarea) return;
            textarea.style.height = 'auto';
            textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
        }

        function bindAiComposer(textarea, options = {}) {
            const {
                maxHeight = 120,
                onSubmit = () => {},
                onInput = null,
            } = options;
            if (!textarea || textarea.dataset.aiComposerBound === 'true') {
                return;
            }

            textarea.dataset.aiComposerBound = 'true';
            autoResizeAiComposer(textarea, maxHeight);

            textarea.addEventListener('compositionstart', () => {
                setAiComposerComposing(textarea, true);
            });

            textarea.addEventListener('compositionupdate', () => {
                setAiComposerComposing(textarea, true);
            });

            textarea.addEventListener('compositionend', () => {
                setAiComposerComposing(textarea, false);
                window.requestAnimationFrame(() => autoResizeAiComposer(textarea, maxHeight));
            });

            textarea.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter' || event.shiftKey) {
                    return;
                }
                if (isAiComposerComposing(event, textarea)) {
                    return;
                }
                event.preventDefault();
                onSubmit();
            });

            textarea.addEventListener('input', () => {
                autoResizeAiComposer(textarea, maxHeight);
                if (typeof onInput === 'function') {
                    onInput(textarea.value || '', textarea);
                }
            });
        }

        function isAiNetworkFailure(error) {
            const message = String(error?.message || error || '').trim();
            return error instanceof TypeError || /Failed to fetch|Load failed|NetworkError/i.test(message);
        }

        async function waitForAuthBootstrap(timeoutMs = 2200) {
            if (typeof authBootstrapComplete === 'undefined' || authBootstrapComplete) {
                return;
            }
            const startedAt = Date.now();
            while (typeof authBootstrapComplete !== 'undefined' && !authBootstrapComplete && (Date.now() - startedAt) < timeoutMs) {
                await new Promise((resolve) => window.setTimeout(resolve, 40));
            }
        }

        async function ensureAiSessionReady(options = {}) {
            const { allowRecovery = true } = options;
            await waitForAuthBootstrap();
            if (ensureAuthenticated()) return true;
            if (!allowRecovery) return false;

            if (typeof refreshAuthSession === 'function') {
                const refreshedSession = await refreshAuthSession({ silent: true });
                if (refreshedSession?.authenticated || ensureAuthenticated()) {
                    return true;
                }
            }

            if (typeof provisionLocalSession === 'function') {
                const provisionedSession = await provisionLocalSession({ silent: true });
                if (provisionedSession?.authenticated || ensureAuthenticated()) {
                    return true;
                }
            }

            return ensureAuthenticated();
        }

        function normalizeAiRequestError(error) {
            const message = String(error?.message || error || '').trim();
            if (!message) return 'AI 请求失败';
            if (/Authentication required|401/i.test(message)) {
                return '本地会话已断开，已尝试恢复，请再试一次。';
            }
            if (isAiNetworkFailure(error)) {
                return '无法连接到本地 AI 服务，请确认后端仍在运行。';
            }
            return message;
        }

        async function ensureAiSettingsLoaded() {
            if (latestSettings || typeof loadSettings !== 'function') {
                return latestSettings;
            }
            await ensureAiSessionReady({ allowRecovery: true });
            if (!ensureAuthenticated()) {
                return latestSettings;
            }
            if (!aiSettingsLoadPromise) {
                aiSettingsLoadPromise = Promise.resolve(loadSettings({ includeNotionDatabases: false }))
                    .catch((error) => {
                        console.error('Failed to preload AI settings', error);
                        return null;
                    })
                    .finally(() => {
                        aiSettingsLoadPromise = null;
                    });
            }
            const settings = await aiSettingsLoadPromise;
            return settings || latestSettings;
        }

        function isAiConfigured() {
            return Boolean(latestSettings?.ai_ready);
        }

        function getCurrentAiContextItem() {
            if (!currentAiContextItemId || typeof getItemById !== 'function') return null;
            return getItemById(currentAiContextItemId);
        }

        function updateAskAiInputContextUi() {
            const currentItem = getCurrentAiContextItem();
            if (askAiInput) {
                askAiInput.placeholder = currentItem
                    ? `围绕《${getDisplayItemTitle(currentItem) || '当前内容'}》提问...`
                    : '发送消息...';
            }
            syncAiModeUi();
            syncAskAiMeta();
        }

        function syncAskAiMeta() {
            if (!askAiMeta) return;
            if (askAiRequestInFlight) {
                askAiMeta.textContent = '';
                askAiMeta.classList.remove('is-loading');
                askAiMeta.hidden = true;
                return;
            }
            askAiMeta.hidden = false;
            askAiMeta.textContent = '按 Enter 发送，Shift+Enter 换行';
            askAiMeta.classList.remove('is-loading');
        }

        function updateAskAiSubmitState() {
            if (!submitAskAiBtn || !askAiInput) return;
            const hasContent = String(askAiInput.value || '').trim().length > 0;
            submitAskAiBtn.toggleAttribute('disabled', askAiRequestInFlight || !hasContent);
        }

        function setAskAiContextItemId(itemId, options = {}) {
            const { resetConversation = false } = options;
            const nextId = String(itemId || '').trim() || null;
            currentAiContextItemId = nextId;
            if (resetConversation) {
                clearAiConversation();
            }
            updateAskAiInputContextUi();
        }

        function formatAiRelativeTime(value) {
            const timestamp = value ? new Date(value) : null;
            if (!timestamp || Number.isNaN(timestamp.getTime())) return '刚刚';
            const diffMs = Date.now() - timestamp.getTime();
            const diffMinutes = Math.max(0, Math.round(diffMs / 60000));
            if (diffMinutes < 1) return '刚刚';
            if (diffMinutes < 60) return `${diffMinutes} 分钟前`;
            const diffHours = Math.round(diffMinutes / 60);
            if (diffHours < 24) return `${diffHours} 小时前`;
            const diffDays = Math.round(diffHours / 24);
            if (diffDays < 7) return `${diffDays} 天前`;
            return `${timestamp.getMonth() + 1}/${timestamp.getDate()}`;
        }

        function normalizeStoredConversationMessage(entry = {}) {
            return {
                role: entry.role === 'user' ? 'user' : 'assistant',
                mode: entry.mode === 'agent' ? 'agent' : 'chat',
                content: stripAiReasoningBlocks(entry.content || ''),
                citations: Array.isArray(entry.citations) ? entry.citations : [],
                toolEvents: Array.isArray(entry.tool_events) ? entry.tool_events : (Array.isArray(entry.toolEvents) ? entry.toolEvents : []),
                insufficientContext: Boolean(entry.insufficient_context ?? entry.insufficientContext),
                knowledgeBasePath: entry.knowledge_base_path || entry.knowledgeBasePath || '',
                noteCount: Number(entry.note_count ?? entry.noteCount ?? 0),
                isError: Boolean(entry.is_error ?? entry.isError),
                createdAt: entry.created_at || entry.createdAt || '',
            };
        }

        function serializeConversationForSave(conversation = []) {
            return conversation
                .filter((entry) => (entry.role === 'user' || entry.role === 'assistant') && String(entry.content || '').trim())
                .map((entry) => ({
                    role: entry.role,
                    mode: entry.mode === 'agent' ? 'agent' : 'chat',
                    content: stripAiReasoningBlocks(entry.content || ''),
                    citations: Array.isArray(entry.citations) ? entry.citations : [],
                    tool_events: Array.isArray(entry.toolEvents) ? entry.toolEvents : [],
                    insufficient_context: Boolean(entry.insufficientContext),
                    knowledge_base_path: entry.knowledgeBasePath || '',
                    note_count: Number(entry.noteCount || 0),
                    is_error: Boolean(entry.isError),
                    created_at: entry.createdAt || new Date().toISOString(),
                }));
        }

        function renderAiConversationHistory() {
            const renderList = (container, conversations, mode) => {
                if (!container) return;

                if (aiHistoryLoading && !conversations.length) {
                    container.innerHTML = '<div class="ai-history-empty">加载中...</div>';
                    return;
                }

                if (!conversations.length) {
                    container.innerHTML = '<div class="ai-history-empty">暂无对话</div>';
                    return;
                }

                container.innerHTML = conversations.map((conversation) => `
                    <button
                        class="ai-history-item${conversation.id === aiConversationId && aiAssistantMode === mode ? ' is-active' : ''}"
                        type="button"
                        data-conversation-id="${escapeAttribute(conversation.id)}"
                        data-mode="${mode}"
                    >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                        </svg>
                        <span class="ai-history-item-title">${escapeHtml(conversation.title || '未命名')}</span>
                        <span class="ai-history-item-delete" data-delete-id="${escapeAttribute(conversation.id)}" aria-label="删除对话">&times;</span>
                        <span class="ai-history-delete-confirm">
                            <span>删除？</span>
                            <span class="ai-history-delete-yes" data-confirm-id="${escapeAttribute(conversation.id)}">删除</span>
                            <span class="ai-history-delete-no">取消</span>
                        </span>
                    </button>
                `).join('');

                container.querySelectorAll('.ai-history-item-delete').forEach((del) => {
                    del.addEventListener('click', (e) => {
                        e.stopPropagation();
                        e.preventDefault();
                        const item = del.closest('.ai-history-item');
                        if (item) item.classList.add('is-confirming');
                    });
                });

                container.querySelectorAll('.ai-history-delete-no').forEach((btn) => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        e.preventDefault();
                        const item = btn.closest('.ai-history-item');
                        if (item) item.classList.remove('is-confirming');
                    });
                });

                container.querySelectorAll('.ai-history-delete-yes').forEach((btn) => {
                    btn.addEventListener('click', async (e) => {
                        e.stopPropagation();
                        e.preventDefault();
                        const id = btn.getAttribute('data-confirm-id');
                        if (!id) return;
                        try {
                            await deleteAiConversation(id);
                        } catch (error) {
                            showToast(`删除失败：${error.message}`, 'error');
                        }
                    });
                });

                container.querySelectorAll('[data-conversation-id]').forEach((button) => {
                    button.addEventListener('click', async () => {
                        const conversationId = button.getAttribute('data-conversation-id');
                        const convMode = button.getAttribute('data-mode');
                        if (!conversationId || conversationId === aiConversationId) return;
                        try {
                            setAiAssistantMode(convMode);
                            await loadAiConversationById(conversationId);
                        } catch (error) {
                            showToast(`对话加载失败：${error.message}`, 'error');
                        }
                    });
                });
            };

            renderList(aiChatHistory, aiChatConversationHistory, 'chat');
            renderList(aiAgentHistory, aiAgentConversationHistory, 'agent');

            if (aiChatCount) {
                aiChatCount.textContent = aiChatConversationHistory.length;
            }
            if (aiAgentCount) {
                aiAgentCount.textContent = aiAgentConversationHistory.length;
            }
        }

        async function loadAiConversationHistory() {
            if (!(await ensureAiSessionReady({ allowRecovery: true }))) {
                return [];
            }

            const requestId = ++aiHistoryRequestId;
            aiHistoryLoading = true;
            renderAiConversationHistory();

            try {
                const params = new URLSearchParams();
                params.set('limit', '30');
                if (aiHistorySearchQuery) {
                    params.set('q', aiHistorySearchQuery);
                }
                const response = await fetch(`/api/ai/conversations?${params.toString()}`);
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '历史对话加载失败');
                if (requestId !== aiHistoryRequestId) return [];

                const allConversations = Array.isArray(data.conversations)
                    ? data.conversations.filter((conversation) => !conversation?.current_item_id)
                    : [];
                aiChatConversationHistory = allConversations.filter((c) => c.mode !== 'agent');
                aiAgentConversationHistory = allConversations.filter((c) => c.mode === 'agent');

                return [...aiChatConversationHistory, ...aiAgentConversationHistory];
            } catch (error) {
                if (requestId === aiHistoryRequestId) {
                    aiChatConversationHistory = [];
                    aiAgentConversationHistory = [];
                }
                showToast(`历史对话加载失败：${error.message}`, 'error');
                return [];
            } finally {
                if (requestId === aiHistoryRequestId) {
                    aiHistoryLoading = false;
                    renderAiConversationHistory();
                }
            }
        }

        async function loadAiConversationById(conversationId) {
            if (!(await ensureAiSessionReady({ allowRecovery: true }))) {
                showToast('无法连接本地会话。', 'error');
                return;
            }
            const response = await fetch(`/api/ai/conversations/${conversationId}`);
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.detail || '对话加载失败');
            }
            const loadedMode = data.mode === 'agent' ? 'agent' : 'chat';
            const loadedConversation = Array.isArray(data.messages) ? data.messages.map(normalizeStoredConversationMessage) : [];

            // 更新对应模式的对话
            if (loadedMode === 'agent') {
                aiAgentConversationId = data.id || conversationId;
                aiAgentConversation = loadedConversation.slice();
            } else {
                aiChatConversationId = data.id || conversationId;
                aiChatConversation = loadedConversation.slice();
            }

            // 设置当前模式并加载对话
            aiAssistantMode = loadedMode;
            aiConversationId = data.id || conversationId;
            aiConversation = loadedConversation.slice();
            currentAiContextItemId = data.current_item_id || null;

            syncAiModeUi();
            updateAskAiInputContextUi();
            renderAiConversationHistory();
            renderAiConversation();
        }

        async function deleteAiConversation(conversationId) {
            if (!(await ensureAiSessionReady({ allowRecovery: true }))) {
                showToast('无法连接本地会话。', 'error');
                return;
            }
            const response = await fetch(`/api/ai/conversations/${conversationId}`, { method: 'DELETE' });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || '删除失败');
            }
            if (conversationId === aiConversationId) {
                clearAiConversation();
            }
            if (conversationId === aiChatConversationId) {
                aiChatConversationId = null;
                aiChatConversation = [];
            }
            if (conversationId === aiAgentConversationId) {
                aiAgentConversationId = null;
                aiAgentConversation = [];
            }
            aiChatConversationHistory = aiChatConversationHistory.filter((c) => c.id !== conversationId);
            aiAgentConversationHistory = aiAgentConversationHistory.filter((c) => c.id !== conversationId);
            renderAiConversationHistory();
            renderAiConversation();
            showToast('对话已删除');
        }

        async function persistAiConversationSnapshot(conversation, options = {}) {
            const { conversationId = null, currentItemId = null, mode = aiAssistantMode } = options;
            const messages = serializeConversationForSave(conversation);
            if (!messages.length) return null;

            const response = await fetch('/api/ai/conversations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    conversation_id: conversationId || undefined,
                    mode,
                    current_item_id: currentItemId || undefined,
                    messages,
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.detail || '对话保存失败');
            }
            return data;
        }

        function stripAiReasoningBlocks(value) {
            return String(value || '')
                .replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, '')
                .replace(/\n{3,}/g, '\n\n')
                .trim();
        }

        function escapeAiText(value) {
            return escapeHtml(stripAiReasoningBlocks(value)).replace(/\n/g, '<br>');
        }

        function renderAiEmptyState(message) {
            return `<div class="ai-empty-copy">${escapeHtml(message)}</div>`;
        }

        function sanitizeAiUrl(value) {
            const raw = String(value || '').trim();
            if (!raw) return '';
            if (/^(https?:|mailto:)/i.test(raw)) {
                return raw;
            }
            return '';
        }

        function renderInlineMarkdown(value) {
            const placeholders = [];
            let html = escapeHtml(String(value || ''));

            html = html.replace(/`([^`]+)`/g, (_, code) => {
                const token = `__AI_MD_CODE_${placeholders.length}__`;
                placeholders.push(`<code>${escapeHtml(code)}</code>`);
                return token;
            });

            html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
                const safeUrl = sanitizeAiUrl(url);
                if (!safeUrl) return escapeHtml(label);
                return `<a href="${escapeAttribute(safeUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
            });

            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>');
            html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
            html = html.replace(/_([^_]+)_/g, '<em>$1</em>');
            html = html.replace(/~~([^~]+)~~/g, '<del>$1</del>');

            placeholders.forEach((replacement, index) => {
                html = html.replace(`__AI_MD_CODE_${index}__`, replacement);
            });

            return html;
        }

        function renderMarkdown(value) {
            const source = stripAiReasoningBlocks(value).replace(/\r\n/g, '\n').trim();
            if (!source) return '';

            const splitTableRow = (row) => {
                const trimmed = String(row || '').trim().replace(/^\|/, '').replace(/\|$/, '');
                const cells = [];
                let current = '';
                let escaping = false;
                for (const char of trimmed) {
                    if (escaping) {
                        current += char;
                        escaping = false;
                        continue;
                    }
                    if (char === '\\') {
                        escaping = true;
                        continue;
                    }
                    if (char === '|') {
                        cells.push(current.trim());
                        current = '';
                        continue;
                    }
                    current += char;
                }
                cells.push(current.trim());
                return cells;
            };

            const isTableSeparator = (line) => /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(String(line || ''));
            const isTableLine = (line) => {
                const trimmed = String(line || '').trim();
                return trimmed.includes('|') && !/^\s*```/.test(trimmed);
            };

            const renderTable = (headerLine, separatorLine, bodyLines) => {
                const headers = splitTableRow(headerLine);
                const alignments = splitTableRow(separatorLine).map((cell) => {
                    const trimmed = cell.trim();
                    const starts = trimmed.startsWith(':');
                    const ends = trimmed.endsWith(':');
                    if (starts && ends) return 'center';
                    if (ends) return 'right';
                    return 'left';
                });
                const bodyRows = bodyLines
                    .map((line) => splitTableRow(line))
                    .filter((row) => row.length && row.some((cell) => cell));
                const maxColumns = Math.max(headers.length, ...bodyRows.map((row) => row.length), 0);
                const normalizedHeaders = Array.from({ length: maxColumns }, (_, index) => headers[index] || '');
                const normalizedBodyRows = bodyRows.map((row) => Array.from({ length: maxColumns }, (_, index) => row[index] || ''));

                return `
                    <div class="ai-table-wrap">
                        <table>
                            <thead>
                                <tr>${normalizedHeaders.map((cell, index) => `<th style="text-align:${alignments[index] || 'left'}">${renderInlineMarkdown(cell)}</th>`).join('')}</tr>
                            </thead>
                            <tbody>
                                ${normalizedBodyRows.map((row) => `<tr>${row.map((cell, index) => `<td style="text-align:${alignments[index] || 'left'}">${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            };

            const lines = source.split('\n');
            const html = [];
            let paragraph = [];
            let listType = '';
            let listItems = [];
            let quoteLines = [];
            let inCodeBlock = false;
            let codeLang = '';
            let codeLines = [];

            const flushParagraph = () => {
                if (!paragraph.length) return;
                html.push(`<p>${renderInlineMarkdown(paragraph.join('\n')).replace(/\n/g, '<br>')}</p>`);
                paragraph = [];
            };

            const flushList = () => {
                if (!listItems.length) return;
                html.push(`<${listType}>${listItems.map((item) => `<li>${renderInlineMarkdown(item).replace(/\n/g, '<br>')}</li>`).join('')}</${listType}>`);
                listType = '';
                listItems = [];
            };

            const flushQuote = () => {
                if (!quoteLines.length) return;
                html.push(`<blockquote>${renderMarkdown(quoteLines.join('\n'))}</blockquote>`);
                quoteLines = [];
            };

            const flushCode = () => {
                if (!inCodeBlock) return;
                const normalizedLanguage = escapeAttribute((codeLang || 'code').trim() || 'code');
                html.push(`
                    <div class="ai-code-block">
                        <button
                            class="ai-code-copy"
                            type="button"
                            data-ai-copy-code
                            data-code-language="${normalizedLanguage}"
                            aria-label="复制代码"
                            title="复制代码"
                        >${AI_CODE_COPY_ICON}</button>
                        <pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>
                    </div>
                `);
                inCodeBlock = false;
                codeLang = '';
                codeLines = [];
            };

            for (let index = 0; index < lines.length; index += 1) {
                const line = lines[index];
                const trimmed = line.trim();

                if (inCodeBlock) {
                    if (/^```/.test(trimmed)) {
                        flushCode();
                    } else {
                        codeLines.push(line);
                    }
                    continue;
                }

                if (/^```/.test(trimmed)) {
                    flushParagraph();
                    flushList();
                    flushQuote();
                    inCodeBlock = true;
                    codeLang = trimmed.replace(/^```/, '').trim();
                    codeLines = [];
                    continue;
                }

                if (!trimmed) {
                    flushParagraph();
                    flushList();
                    flushQuote();
                    continue;
                }

                if (isTableLine(line) && isTableSeparator(lines[index + 1])) {
                    flushParagraph();
                    flushList();
                    flushQuote();
                    const headerLine = line;
                    const separatorLine = lines[index + 1];
                    const bodyLines = [];
                    index += 2;
                    while (index < lines.length && lines[index].trim() && isTableLine(lines[index])) {
                        bodyLines.push(lines[index]);
                        index += 1;
                    }
                    index -= 1;
                    html.push(renderTable(headerLine, separatorLine, bodyLines));
                    continue;
                }

                const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
                if (headingMatch) {
                    flushParagraph();
                    flushList();
                    flushQuote();
                    const level = headingMatch[1].length;
                    html.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
                    continue;
                }

                if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
                    flushParagraph();
                    flushList();
                    flushQuote();
                    html.push('<hr>');
                    continue;
                }

                const quoteMatch = line.match(/^\s*>\s?(.*)$/);
                if (quoteMatch) {
                    flushParagraph();
                    flushList();
                    quoteLines.push(quoteMatch[1]);
                    continue;
                }

                if (quoteLines.length) {
                    flushQuote();
                }

                const unorderedMatch = line.match(/^\s*[-*+]\s+(.*)$/);
                const orderedMatch = line.match(/^\s*\d+\.\s+(.*)$/);
                if (unorderedMatch || orderedMatch) {
                    flushParagraph();
                    const nextType = unorderedMatch ? 'ul' : 'ol';
                    if (listType && listType !== nextType) {
                        flushList();
                    }
                    listType = nextType;
                    listItems.push((unorderedMatch || orderedMatch)[1]);
                    continue;
                }

                if (listItems.length) {
                    flushList();
                }

                paragraph.push(line);
            }

            flushParagraph();
            flushList();
            flushQuote();
            flushCode();

            return html.join('');
        }

        function currentAgentPermissions() {
            const permissions = ['read_knowledge_base'];
            if (latestSettings?.ai_agent_can_manage_folders !== false) {
                permissions.push('manage_folders');
            }
            if (latestSettings?.ai_agent_can_parse_content !== false) {
                permissions.push('parse_content');
            }
            if (latestSettings?.ai_agent_can_sync_obsidian && latestSettings?.obsidian_ready) {
                permissions.push('sync_obsidian');
            }
            if (latestSettings?.ai_agent_can_sync_notion && latestSettings?.notion_ready) {
                permissions.push('sync_notion');
            }
            return permissions;
        }

        function normalizeAiContextText(value) {
            return String(value || '')
                .replace(/\r\n/g, '\n')
                .replace(/\r/g, '\n')
                .replace(/\u0000/g, '')
                .replace(/[ \t]+\n/g, '\n')
                .replace(/\n{3,}/g, '\n\n')
                .trim();
        }

        function truncateAiContextText(value, limit = 1200) {
            const normalized = normalizeAiContextText(value);
            if (!normalized || normalized.length <= limit) return normalized;
            return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
        }

        function buildItemAiContextSnippet(item, limit = 1200) {
            if (!item) return '';
            const candidates = [
                item?.extracted_text,
                item?.canonical_text,
                item?.ocr_text,
                Array.isArray(item?.frame_texts)
                    ? item.frame_texts
                        .map((entry) => normalizeAiContextText(entry?.text || entry?.content || ''))
                        .filter(Boolean)
                        .join('\n')
                    : '',
            ];
            for (const candidate of candidates) {
                const snippet = truncateAiContextText(candidate, limit);
                if (snippet) return snippet;
            }
            return '';
        }

        function buildItemContextLines(item, options = {}) {
            const {
                snippetLimit = 1200,
                includeSnippet = true,
                closingLine = '请优先基于这条内容和我的知识库回答；若证据不足，直接说明。',
            } = options;
            if (!item) {
                return ['请基于我的知识库帮我分析当前这条笔记。'];
            }

            const lines = [
                `当前笔记：${getDisplayItemTitle(item) || '未命名内容'}`,
            ];
            const folderNames = Array.isArray(item.folder_names) ? item.folder_names.filter(Boolean) : [];
            if (folderNames.length) {
                lines.push(`文件夹：${folderNames.join(' / ')}`);
            }
            const detectedTitle = typeof getExtractedDisplayTitle === 'function' ? getExtractedDisplayTitle(item) : '';
            if (detectedTitle) {
                lines.push(`检测标题：${detectedTitle}`);
            }
            if (item?.parse_status === 'completed') {
                lines.push('当前状态：已有内容分析。');
            } else if (item?.parse_status === 'processing') {
                lines.push('当前状态：内容仍在解析中。');
            }
            if (includeSnippet) {
                const snippet = buildItemAiContextSnippet(item, snippetLimit);
                if (snippet) {
                    lines.push(`当前内容片段：\n${snippet}`);
                }
            }
            lines.push(closingLine);
            return lines;
        }

        function setAiAssistantMode(mode) {
            const prevMode = aiAssistantMode;
            // 保存当前模式的对话
            if (prevMode === 'agent') {
                aiAgentConversation = aiConversation.slice();
                aiAgentConversationId = aiConversationId;
            } else {
                aiChatConversation = aiConversation.slice();
                aiChatConversationId = aiConversationId;
            }

            // 切换模式
            aiAssistantMode = mode === 'agent' ? 'agent' : 'chat';

            // 加载新模式的对话
            if (aiAssistantMode === 'agent') {
                aiConversation = aiAgentConversation.slice();
                aiConversationId = aiAgentConversationId;
            } else {
                aiConversation = aiChatConversation.slice();
                aiConversationId = aiChatConversationId;
            }

            syncAiModeUi();
            renderAiConversationHistory();
            renderAiWelcome();
            renderAiConversation();
        }

        function renderAiWelcome() {
            const welcomeGrid = document.getElementById('aiWelcomeGrid');
            if (!welcomeGrid) return;
            const starters = aiAssistantMode === 'agent'
                ? [
                    { title: '整理最近保存的内容', description: '自动分类和整理最近的笔记' },
                    { title: '触发内容解析', description: '对未解析的内容执行解析' },
                    { title: '同步到 Obsidian', description: '将选中的笔记同步到 Obsidian' },
                    { title: '同步到 Notion', description: '将选中的笔记同步到 Notion' },
                ]
                : [
                    { title: '总结最近保存内容', description: '从知识库里挑出最近最值得继续看的内容' },
                    { title: '帮我找相关笔记', description: '围绕一个主题串起已有记录和潜在线索' },
                    { title: '把一条内容拆成行动', description: '从当前笔记里提炼下一步、待办和追问点' },
                    { title: '分析当前内容', description: '结合当前文章和知识库给出结构化判断' },
                ];

            welcomeGrid.innerHTML = starters.map((item) => `
                <button class="ai-starter" type="button" data-ai-starter="${escapeAttribute(item.title)}">
                    <div class="ai-starter-title">${escapeHtml(item.title)}</div>
                    <div class="ai-starter-desc">${escapeHtml(item.description)}</div>
                </button>
            `).join('');

            welcomeGrid.querySelectorAll('[data-ai-starter]').forEach((button) => {
                button.addEventListener('click', () => {
                    const starter = String(button.getAttribute('data-ai-starter') || '').trim();
                    if (!starter || !askAiInput) return;
                    askAiInput.value = starter;
                    autoResizeAiComposer(askAiInput, 200);
                    updateAskAiSubmitState();
                    askAiInput.focus();
                });
            });
        }

        function getVisibleAiCitations(citations) {
            if (!Array.isArray(citations)) return [];
            return citations.filter((citation) => citation && (citation.title || citation.library_item_id));
        }

        function buildAiCitationMarkup(citation, compact = false) {
            const title = escapeHtml(citation.title || '未命名笔记');
            const citationId = String(citation.library_item_id || '').trim();
            const iconMarkup = `
                <span class="ai-citation-link" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M14 5h5v5"></path>
                        <path d="M10 14 19 5"></path>
                        <path d="M19 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h4"></path>
                    </svg>
                </span>
            `;
            if (citationId) {
                return `
                    <button
                        class="ai-citation-item is-link${compact ? ' is-compact' : ''}"
                        type="button"
                        data-ai-citation-id="${escapeAttribute(citationId)}"
                        aria-label="打开引用内容：${title}"
                        title="打开引用内容"
                    >
                        <span class="ai-citation-title">${title}</span>
                        ${iconMarkup}
                    </button>
                `;
            }
            return `
                <div class="ai-citation-item${compact ? ' is-compact' : ''}">
                    <div class="ai-citation-title">${title}</div>
                    ${iconMarkup}
                </div>
            `;
        }

        function buildAiToolEventsMarkup(toolEvents = []) {
            if (!Array.isArray(toolEvents) || !toolEvents.length) return '';
            return `
                <div class="ai-tool-events">
                    ${toolEvents.map((event) => `
                        <div class="ai-tool-event${event.status === 'failed' ? ' is-failed' : ''}">
                            <div class="ai-tool-event-name">${escapeHtml(AI_TOOL_LABELS[event.name] || event.name || 'Agent')}</div>
                            <div class="ai-tool-event-summary">${escapeHtml(event.summary || '')}</div>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        function buildAiMetaMarkup(entry) {
            const metaBits = [];
            if (entry.knowledgeBasePath) {
                metaBits.push(`知识库：${escapeHtml(entry.knowledgeBasePath)}`);
            }
            if (Number.isFinite(Number(entry.noteCount)) && Number(entry.noteCount) > 0) {
                metaBits.push(`已读取 ${Number(entry.noteCount)} 篇笔记`);
            }
            return metaBits.length
                ? `<div class="ai-answer-meta">${metaBits.join(' · ')}</div>`
                : '';
        }

        function buildAiMessageActionsMarkup(options = {}) {
            const {
                itemId = null,
                conversationId = null,
                messageIndex = -1,
                origin = 'main',
                entry = null,
            } = options;
            const canAttachToPageNote = Boolean(
                itemId
                && entry
                && !entry.isError
                && entry.role === 'assistant'
                && String(entry.content || '').trim()
            );
            if (!canAttachToPageNote) {
                return '';
            }
            if (origin !== 'reader' && !conversationId) {
                return '';
            }
            const handler = origin === 'reader'
                ? `saveReaderAiMessageToPageNote(${JSON.stringify(String(itemId))}, ${messageIndex})`
                : `saveTopAiMessageToPageNote(${messageIndex})`;
            return `
                <div class="ai-message-actions">
                    <button class="ai-message-action-btn" type="button" onclick='${handler}'>加入页面笔记</button>
                </div>
            `;
        }

        function hasSuccessfulAiMutation(toolEvents = []) {
            return Array.isArray(toolEvents) && toolEvents.some((event) => (
                event
                && AI_MUTATING_TOOLS.has(String(event.name || ''))
                && String(event.status || 'completed') !== 'failed'
            ));
        }

        async function applyAiAssistantSideEffects(responseData) {
            const updatedItems = Array.isArray(responseData?.updated_items) ? responseData.updated_items : [];
            const toolEvents = Array.isArray(responseData?.tool_events) ? responseData.tool_events : [];
            const needsMutationRefresh = hasSuccessfulAiMutation(toolEvents);
            const needsFolderRefresh = toolEvents.some((event) => (
                event
                && String(event.name || '') === 'assign_item_folders'
                && String(event.status || 'completed') !== 'failed'
            ));

            updatedItems.forEach((item) => {
                if (!item?.id) return;
                if (typeof mergeUpdatedItem === 'function') {
                    mergeUpdatedItem(item);
                }
                if (typeof patchRenderedItemsById === 'function') {
                    patchRenderedItemsById(item.id);
                }
            });

            const currentUpdatedItem = currentOpenItemId
                ? updatedItems.find((item) => item?.id === currentOpenItemId)
                : null;
            if (currentUpdatedItem && modalOverlay?.classList.contains('active') && typeof openModalByItem === 'function') {
                openModalByItem(currentUpdatedItem, { preserveSidebarTab: true });
            }

            if (!needsMutationRefresh) return;

            const refreshTasks = [];
            if (typeof fetchItems === 'function') {
                refreshTasks.push(fetchItems());
            }
            if (needsFolderRefresh && typeof fetchFolders === 'function') {
                refreshTasks.push(fetchFolders());
            }
            if (refreshTasks.length) {
                await Promise.all(refreshTasks);
            }

            if (currentOpenItemId && modalOverlay?.classList.contains('active') && typeof getItemById === 'function' && typeof openModalByItem === 'function') {
                const refreshedItem = getItemById(currentOpenItemId);
                if (refreshedItem) {
                    openModalByItem(refreshedItem, { preserveSidebarTab: true });
                }
            }
        }

        function renderAssistantMessage(entry, options = {}) {
            const {
                compact = false,
                itemId = null,
                conversationId = null,
                messageIndex = -1,
                origin = 'main',
            } = options;
            const citations = getVisibleAiCitations(entry.citations);
            const citationsMarkup = citations.length
                ? `
                    <div class="ai-citations">
                        <div class="ai-citation-label">引用内容</div>
                        <div class="ai-citation-list">${citations.map((citation) => buildAiCitationMarkup(citation, compact)).join('')}</div>
                    </div>
                `
                : '';
            const toolEventsMarkup = buildAiToolEventsMarkup(entry.toolEvents);
            const metaMarkup = buildAiMetaMarkup(entry);
            const actionsMarkup = buildAiMessageActionsMarkup({ itemId, conversationId, messageIndex, origin, entry });

            return `
                <div class="ai-msg${compact ? ' is-compact' : ''}">
                    <div class="ai-msg-inner">
                        <div class="ai-msg-content">
                            <div class="ai-markdown${entry.isError ? ' is-error' : ''}">${renderMarkdown(entry.content || '')}</div>
                            ${metaMarkup}
                            ${actionsMarkup}
                            ${toolEventsMarkup}
                            ${citationsMarkup}
                        </div>
                    </div>
                </div>
            `;
        }

        function renderUserMessage(entry, options = {}) {
            const { compact = false } = options;
            return `
                <div class="ai-msg is-user${compact ? ' is-compact' : ''}">
                    <div class="ai-msg-inner">
                        <div class="ai-msg-content">${escapeAiText(entry.content || '')}</div>
                    </div>
                </div>
            `;
        }

        function renderAiLoadingMessage(options = {}) {
            const {
                mode = 'chat',
                compact = false,
                label = '',
                description = '',
            } = options;
            const title = label || (mode === 'agent' ? 'Agent 正在执行' : 'AI 正在思考');
            const copy = description || (mode === 'agent'
                ? '正在读取知识库，并按当前权限准备动作。'
                : '正在整理上下文、检索知识库并生成回答。');

            return `
                <div class="ai-msg ai-msg--loading${compact ? ' is-compact' : ''}" aria-live="polite">
                    <div class="ai-msg-inner">
                        <div class="ai-msg-content">
                            <div class="ai-loading-card">
                                <div class="ai-loading-row">
                                    <div class="ai-loading-label">${escapeHtml(title)}</div>
                                    <div class="ai-loading-dots" aria-hidden="true">
                                        <span></span>
                                        <span></span>
                                        <span></span>
                                    </div>
                                </div>
                                <div class="ai-loading-copy">${escapeHtml(copy)}</div>
                                <div class="ai-loading-bars" aria-hidden="true">
                                    <span></span>
                                    <span></span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        function renderAiHome(currentItem) {
            const title = currentItem
                ? `围绕《${escapeHtml(getDisplayItemTitle(currentItem) || '当前内容')}》继续`
                : '有什么可以帮忙的？';
            const badge = currentItem
                ? `<div class="ai-welcome-badge">当前内容 · ${escapeHtml(getDisplayItemTitle(currentItem) || '未命名内容')}</div>`
                : '<div class="ai-welcome-badge">基于知识库连续对话</div>';
            const subtitle = currentItem
                ? '我会自动带上这条内容的正文、内容分析和相关知识库上下文。'
                : '可以直接提问、总结内容、串联笔记，或切到 Agent 执行动作。';

            return `
                <div class="ai-welcome">
                    ${badge}
                    <h1 class="ai-welcome-title">${title}</h1>
                    <p class="ai-welcome-subtitle">${subtitle}</p>
                    <div class="ai-welcome-grid" id="aiWelcomeGrid"></div>
                </div>
            `;
        }

        function normalizeConversationForRequest() {
            return aiConversation
                .filter((entry) => (entry.role === 'user' || entry.role === 'assistant') && !entry.isError)
                .map((entry) => ({
                    role: entry.role,
                    content: entry.role === 'assistant'
                        ? stripAiReasoningBlocks(entry.content || '')
                        : String(entry.content || '').trim(),
                }))
                .filter((entry) => entry.content)
                .slice(-10);
        }

        function renderAiConversation() {
            if (!askAiResult) return;
            const currentItem = getCurrentAiContextItem();
            syncAskAiMeta();

            if (!aiConversation.length) {
                if (!isAiConfigured()) {
                    askAiResult.innerHTML = `
                        <div class="ai-welcome">
                            <div class="ai-welcome-badge">Ask AI 尚未启用</div>
                            <h1 class="ai-welcome-title">先完成 AI 设置</h1>
                            <p class="ai-welcome-subtitle">在设置里填好模型、Base URL 和密钥后，这里就能开始连续对话。</p>
                        </div>
                    `;
                    return;
                }

                askAiResult.innerHTML = renderAiHome(currentItem);
                renderAiWelcome();
                return;
            }

            const conversationMarkup = aiConversation.map((entry, index) => {
                if (entry.role === 'user') {
                    return renderUserMessage(entry);
                }
                return renderAssistantMessage(entry, {
                    itemId: currentAiContextItemId,
                    conversationId: aiConversationId,
                    messageIndex: index,
                    origin: 'main',
                });
            }).join('');
            const loadingMarkup = askAiRequestInFlight
                ? renderAiLoadingMessage({
                    mode: aiAssistantMode,
                    label: aiAssistantMode === 'agent' ? 'Agent 正在执行' : 'AI 正在思考',
                    description: currentItem
                        ? '正在结合当前内容与知识库上下文生成回答。'
                        : '正在检索知识库并生成回答。',
                })
                : '';
            askAiResult.innerHTML = `${conversationMarkup}${loadingMarkup}`;

            window.requestAnimationFrame(() => {
                askAiResult.scrollTop = askAiResult.scrollHeight;
            });
        }

        async function persistTopAiConversation() {
            const saved = await persistAiConversationSnapshot(aiConversation, {
                conversationId: aiConversationId,
                currentItemId: currentAiContextItemId,
                mode: aiAssistantMode,
            });
            if (!saved) return null;
            aiConversationId = saved.id || aiConversationId;
            aiConversation = Array.isArray(saved.messages) ? saved.messages.map(normalizeStoredConversationMessage) : aiConversation;
            // 同步到对应模式的变量
            if (aiAssistantMode === 'agent') {
                aiAgentConversationId = aiConversationId;
                aiAgentConversation = aiConversation.slice();
            } else {
                aiChatConversationId = aiConversationId;
                aiChatConversation = aiConversation.slice();
            }
            await loadAiConversationHistory();
            renderAiConversation();
            return saved;
        }

        async function requestAiAssistant(messages, mode = aiAssistantMode, options = {}) {
            const { currentItemId = null } = options;
            let lastError = null;

            for (let attempt = 0; attempt < 2; attempt += 1) {
                await ensureAiSessionReady({ allowRecovery: true });

                try {
                    const response = await fetch('/api/ai/assistant', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            mode,
                            messages,
                            top_k: 6,
                            current_item_id: currentItemId || undefined,
                        }),
                    });
                    const data = await response.json().catch(() => ({}));
                    if (response.status === 401 && attempt === 0) {
                        lastError = new Error(data.detail || 'Authentication required');
                        continue;
                    }
                    if (!response.ok) {
                        throw new Error(data.detail || 'AI 请求失败');
                    }
                    return data;
                } catch (error) {
                    lastError = error;
                    if (attempt === 0 && (isAiNetworkFailure(error) || /Authentication required|401/i.test(String(error?.message || '')))) {
                        await ensureAiSessionReady({ allowRecovery: true });
                        await new Promise((resolve) => window.setTimeout(resolve, 120));
                        continue;
                    }
                    break;
                }
            }

            throw new Error(normalizeAiRequestError(lastError));
        }

        function ensureReaderAiConversationLoaded(itemId) {
            const key = normalizeReaderAiItemKey(itemId);
            if (!key || readerAiConversationLoadedByItem.has(key)) return;
            readerAiConversationLoadedByItem.add(key);
            loadReaderAiSessionState(key);
        }

        async function persistReaderAiConversation(itemId) {
            const key = normalizeReaderAiItemKey(itemId);
            persistReaderAiSessionState(key);
            return {
                id: readerAiConversationIdByItem.get(key) || null,
                messages: getReaderAiConversation(key),
            };
        }

        async function saveTopAiMessageToPageNote(messageIndex) {
            if (!currentAiContextItemId || !aiConversationId) {
                showToast('这段对话还没有绑定到具体内容。', 'info');
                return;
            }
            const entry = aiConversation[messageIndex];
            if (!entry || entry.role !== 'assistant') return;
            if (typeof window.createReaderPageNote !== 'function') {
                showToast('页面笔记功能尚未就绪。', 'error');
                return;
            }
            await window.createReaderPageNote(currentAiContextItemId, {
                content: stripAiReasoningBlocks(entry.content || ''),
                aiConversationId,
                aiMessageIndex: messageIndex,
                successMessage: 'AI 回答已加入页面笔记',
            });
        }

        async function saveReaderAiMessageToPageNote(itemId, messageIndex) {
            const key = normalizeReaderAiItemKey(itemId);
            const conversation = getReaderAiConversation(key);
            const conversationId = readerAiConversationIdByItem.get(key) || null;
            const entry = conversation[messageIndex];
            if (!entry || entry.role !== 'assistant') {
                return;
            }
            if (typeof window.createReaderPageNote !== 'function') {
                showToast('页面笔记功能尚未就绪。', 'error');
                return;
            }
            await window.createReaderPageNote(itemId, {
                content: stripAiReasoningBlocks(entry.content || ''),
                aiConversationId: conversationId,
                aiMessageIndex: messageIndex,
                successMessage: 'AI 回答已加入页面笔记',
            });
        }

        async function submitAskAiQuestion() {
            if (!(await ensureAiSessionReady({ allowRecovery: true }))) {
                showToast('无法初始化本地会话。', 'error');
                return;
            }
            if (!askAiInput || askAiRequestInFlight) return;

            await ensureAiSettingsLoaded();

            const question = String(askAiInput.value || '').trim();
            if (!question) {
                showToast('先输入一个问题。', 'info');
                return;
            }

            if (!isAiConfigured()) {
                showToast('先完成 AI 设置。', 'info');
                openSettingsPanel();
                return;
            }

            askAiRequestInFlight = true;
            aiConversation.push({ role: 'user', content: question, createdAt: new Date().toISOString() });
            // 同步到对应模式的变量
            if (aiAssistantMode === 'agent') {
                aiAgentConversation = aiConversation.slice();
            } else {
                aiChatConversation = aiConversation.slice();
            }
            askAiInput.value = '';
            autoResizeAiComposer(askAiInput, 200);
            renderAiConversation();
            updateAskAiSubmitState();
            submitAskAiBtn.classList.add('is-loading');
            submitAskAiBtn.setAttribute('aria-label', aiAssistantMode === 'agent' ? 'Agent 执行中' : 'AI 思考中');

            try {
                const data = await requestAiAssistant(
                    normalizeConversationForRequest(),
                    aiAssistantMode,
                    { currentItemId: currentAiContextItemId }
                );
                await applyAiAssistantSideEffects(data);
                askAiRequestInFlight = false;
                aiConversation.push({
                    role: 'assistant',
                    mode: data.mode || aiAssistantMode,
                    content: stripAiReasoningBlocks(data.message || ''),
                    citations: Array.isArray(data.citations) ? data.citations : [],
                    toolEvents: Array.isArray(data.tool_events) ? data.tool_events : [],
                    insufficientContext: Boolean(data.insufficient_context),
                    knowledgeBasePath: data.knowledge_base_path || '',
                    noteCount: Number(data.note_count || 0),
                    createdAt: new Date().toISOString(),
                });
                // 同步到对应模式的变量
                if (aiAssistantMode === 'agent') {
                    aiAgentConversation = aiConversation.slice();
                } else {
                    aiChatConversation = aiConversation.slice();
                }
                renderAiConversation();
                await persistTopAiConversation();
            } catch (error) {
                askAiRequestInFlight = false;
                aiConversation.push({
                    role: 'assistant',
                    mode: aiAssistantMode,
                    content: error.message || 'AI 请求失败',
                    citations: [],
                    toolEvents: [],
                    isError: true,
                    createdAt: new Date().toISOString(),
                });
                // 同步到对应模式的变量
                if (aiAssistantMode === 'agent') {
                    aiAgentConversation = aiConversation.slice();
                } else {
                    aiChatConversation = aiConversation.slice();
                }
                renderAiConversation();
                try {
                    await persistTopAiConversation();
                } catch (saveError) {
                    console.error('Failed to persist failed AI conversation', saveError);
                }
                showToast(`AI 失败：${error.message}`, 'error');
            } finally {
                submitAskAiBtn.classList.remove('is-loading');
                submitAskAiBtn.setAttribute('aria-label', '发送');
                syncAskAiMeta();
                updateAskAiSubmitState();
            }
        }

        async function openAskAiModal(options = {}) {
            const { itemId = null, resetConversation = false } = options;
            if (!(await ensureAiSessionReady({ allowRecovery: true }))) {
                showToast('无法连接本地会话。', 'error');
                return;
            }
            if (resetConversation) {
                aiHistorySearchQuery = '';
            }
            setAskAiContextItemId(itemId, { resetConversation });

            // 加载当前模式的对话
            aiConversation = aiAssistantMode === 'agent' ? aiAgentConversation.slice() : aiChatConversation.slice();
            aiConversationId = aiAssistantMode === 'agent' ? aiAgentConversationId : aiChatConversationId;

            syncAiModeUi();

            askAiOverlay.classList.add('active');
            document.body.style.overflow = 'hidden';
            await ensureAiSettingsLoaded();
            await loadAiConversationHistory();
            refreshAiAssistantUi();
            renderAiWelcome();
            if (askAiInput) {
                autoResizeAiComposer(askAiInput, 200);
                window.setTimeout(() => askAiInput.focus(), 30);
            }
            updateAskAiSubmitState();
        }

        function closeAskAiDialog() {
            askAiOverlay.classList.remove('active');
            document.body.style.overflow = '';
        }

        function refreshAiAssistantUi() {
            renderAiConversationHistory();
            renderAiConversation();
        }

        function clearAiConversation() {
            // 只清空当前模式的对话
            aiConversation = [];
            aiConversationId = null;
            if (aiAssistantMode === 'agent') {
                aiAgentConversation = [];
                aiAgentConversationId = null;
            } else {
                aiChatConversation = [];
                aiChatConversationId = null;
            }
            renderAiConversation();
            renderAiConversationHistory();
            renderAiWelcome();
        }

        function startNewAiConversation() {
            clearAiConversation();
            if (askAiInput) {
                askAiInput.value = '';
                autoResizeAiComposer(askAiInput, 200);
                askAiInput.focus();
            }
            updateAskAiSubmitState();
        }

        function requestOpenCitationItem(options = {}) {
            const item = options.item || null;
            const itemId = String(options.itemId || item?.id || '').trim();
            if (!item && !itemId) return false;

            const event = new CustomEvent('everything-capture:open-item', {
                cancelable: true,
                detail: {
                    item,
                    itemId,
                },
            });
            window.dispatchEvent(event);
            if (event.defaultPrevented) {
                return true;
            }

            if (item && typeof window.openModalByItem === 'function') {
                window.openModalByItem(item);
                return true;
            }
            if (itemId && typeof window.openModalById === 'function') {
                window.openModalById(itemId);
                return true;
            }
            return false;
        }

        async function openAiCitation(libraryItemId) {
            const normalizedItemId = String(libraryItemId || '').trim();
            if (!normalizedItemId) return;
            if (askAiOverlay?.classList.contains('active')) {
                closeAskAiDialog();
            }

            const getItem = typeof window.getItemById === 'function' ? window.getItemById : null;

            if (typeof getItem === 'function') {
                const cachedItem = getItem(normalizedItemId);
                if (cachedItem && requestOpenCitationItem({ item: cachedItem, itemId: normalizedItemId })) {
                    return;
                }
            }

            if (!(await ensureAiSessionReady({ allowRecovery: true }))) {
                showToast('无法恢复本地会话，引用内容暂时打不开。', 'error');
                return;
            }

            let lastError = null;
            for (let attempt = 0; attempt < 2; attempt += 1) {
                try {
                    const response = await fetch(`/api/items/${encodeURIComponent(normalizedItemId)}`);
                    const data = await response.json().catch(() => ({}));
                    if (response.status === 401 && attempt === 0) {
                        await ensureAiSessionReady({ allowRecovery: true });
                        lastError = new Error(data.detail || 'Authentication required');
                        continue;
                    }
                    if (!response.ok) {
                        throw new Error(data.detail || '引用内容不存在');
                    }

                    const item = data;
                    if (typeof window.cacheItemById === 'function') {
                        window.cacheItemById(item);
                    }
                    if (requestOpenCitationItem({ item, itemId: normalizedItemId })) {
                        return;
                    }
                    throw new Error('阅读弹窗未就绪');
                } catch (error) {
                    lastError = error;
                    if (attempt === 0 && /Authentication required|401/i.test(String(error?.message || ''))) {
                        await ensureAiSessionReady({ allowRecovery: true });
                        continue;
                    }
                    break;
                }
            }

            const message = String(lastError?.message || '引用内容不存在');
            showToast(`引用内容无法打开：${message}`, 'error');
        }

        function getReaderAiConversation(itemId) {
            const key = normalizeReaderAiItemKey(itemId);
            return key ? (readerAiConversationByItem.get(key) || []) : [];
        }

        function rerenderReaderAiSidebar(itemId) {
            const key = normalizeReaderAiItemKey(itemId);
            if (!key || normalizeReaderAiItemKey(currentOpenItemId) !== key) return;
            if (!readerSidebarOpen || readerSidebarTab !== 'ai') return;
            window.renderSidebarAiContent?.();
        }

        function buildReaderAiRequestMessages(item) {
            return getReaderAiConversation(item?.id)
                .filter((entry) => (entry.role === 'user' || entry.role === 'assistant') && !entry.isError)
                .map((entry) => {
                    const content = entry.role === 'assistant'
                        ? stripAiReasoningBlocks(entry.content || '')
                        : String(entry.content || '').trim();
                    if (!content) return null;
                    return { role: entry.role, content };
                })
                .filter(Boolean)
                .slice(-10);
        }

        function renderReaderAiSidebar(item) {
            const itemKey = normalizeReaderAiItemKey(item?.id);
            ensureReaderAiConversationLoaded(itemKey);
            const conversation = getReaderAiConversation(itemKey);
            const draft = readerAiDraftByItem.get(itemKey) || '';
            const isBusy = readerAiRequestInFlight && normalizeReaderAiItemKey(currentOpenItemId) === itemKey;

            if (!isAiConfigured()) {
                return `
                    <div class="reader-ai-sidebar-shell is-empty">
                        <div class="reader-ai-empty-state">
                            <div class="reader-ai-empty-title">Ask AI 还没配置</div>
                            <div class="reader-ai-empty-copy">先在设置里填写 API Key，再从这里按需展开嵌入式 AI 侧栏。</div>
                            <button class="reader-ai-settings-btn" type="button" onclick="openSettingsPanel()">打开设置</button>
                        </div>
                    </div>
                `;
            }

            const messagesMarkup = conversation.length
                ? conversation.map((entry, index) => {
                    if (entry.role === 'user') {
                        return renderUserMessage(entry, { compact: true });
                    }
                    return renderAssistantMessage(entry, {
                        compact: true,
                        itemId: itemKey,
                        conversationId: readerAiConversationIdByItem.get(itemKey) || null,
                        messageIndex: index,
                        origin: 'reader',
                    });
                }).join('')
                : '';

            const quickActionsMarkup = READER_AI_SUGGESTIONS.map((prompt) => (
                `<button class="reader-ai-quick-action" type="button" data-reader-ai-prompt="${escapeAttribute(prompt)}">${escapeHtml(prompt)}</button>`
            )).join('');
            const contextMarkup = `
                <div class="reader-ai-context">
                    <div class="reader-ai-context-label">当前内容</div>
                    <div class="reader-ai-context-title">${escapeHtml(getDisplayItemTitle(item) || '未命名内容')}</div>
                    <div class="reader-ai-context-copy">自动附带正文、内容分析和知识库上下文。</div>
                </div>
            `;
            const quickActionsSectionMarkup = `
                <div class="reader-ai-quick-actions">
                    <div class="reader-ai-quick-actions-title">建议提问</div>
                    <div class="reader-ai-quick-actions-list">${quickActionsMarkup}</div>
                </div>
            `;
            const loadingMarkup = isBusy
                ? renderAiLoadingMessage({
                    mode: 'chat',
                    compact: true,
                    label: 'Ask AI 正在思考',
                    description: '正在结合当前笔记的内容分析与知识库上下文生成回答。',
                })
                : '';

            return `
                <div class="reader-ai-sidebar-shell">
                    <div class="reader-ai-messages" id="readerAiMessages">${contextMarkup}${quickActionsSectionMarkup}${messagesMarkup}${loadingMarkup}</div>
                    <div class="reader-ai-composer${isBusy ? ' is-loading' : ''}">
                        <textarea id="readerAiInput" class="reader-ai-input" placeholder="问这条笔记、问关联内容，或让 AI 帮你整理下一步..." ${isBusy ? 'disabled' : ''}>${escapeHtml(draft)}</textarea>
                        <div class="reader-ai-composer-actions">
                            <button id="readerAiClearBtn" class="reader-ai-secondary-btn" type="button" ${conversation.length ? '' : 'disabled'}>清空</button>
                            <button id="readerAiSubmitBtn" class="reader-ai-submit${isBusy ? ' is-loading' : ''}" type="button" ${isBusy ? 'disabled' : ''}>${isBusy ? '思考中...' : '发送'}</button>
                        </div>
                    </div>
                </div>
            `;
        }

        function focusReaderAiComposer() {
            const input = document.getElementById('readerAiInput');
            if (!input) return;
            input.focus();
            const caret = input.value.length;
            if (typeof input.setSelectionRange === 'function') {
                input.setSelectionRange(caret, caret);
            }
        }

        function bindReaderAiSidebar(item) {
            const itemKey = normalizeReaderAiItemKey(item?.id);
            const input = document.getElementById('readerAiInput');
            const submitBtn = document.getElementById('readerAiSubmitBtn');
            const clearBtn = document.getElementById('readerAiClearBtn');
            const messages = document.getElementById('readerAiMessages');
            const quickActions = document.querySelectorAll('[data-reader-ai-prompt]');

            bindAiComposer(input, {
                maxHeight: 180,
                onSubmit: () => submitReaderAiQuestion(),
                onInput: (value) => {
                    readerAiDraftByItem.set(itemKey, value);
                    persistReaderAiSessionState(itemKey);
                },
            });

            submitBtn?.addEventListener('click', () => submitReaderAiQuestion());
            clearBtn?.addEventListener('click', () => {
                readerAiConversationByItem.delete(itemKey);
                readerAiConversationIdByItem.delete(itemKey);
                readerAiConversationLoadedByItem.add(itemKey);
                readerAiDraftByItem.set(itemKey, '');
                persistReaderAiSessionState(itemKey);
                rerenderReaderAiSidebar(itemKey);
            });
            quickActions.forEach((button) => {
                button.addEventListener('click', () => {
                    submitReaderAiQuestion(button.getAttribute('data-reader-ai-prompt') || '');
                });
            });

            if (messages) {
                window.requestAnimationFrame(() => {
                    messages.scrollTop = messages.scrollHeight;
                });
            }
        }

        async function submitReaderAiQuestion(prefillQuestion = '') {
            if (!(await ensureAiSessionReady({ allowRecovery: true }))) {
                showToast('无法初始化本地会话。', 'error');
                return;
            }
            if (!currentOpenItemId || readerAiRequestInFlight) return;
            const item = typeof getItemById === 'function' ? getItemById(currentOpenItemId) : null;
            if (!item) return;
            const itemKey = normalizeReaderAiItemKey(item.id);

            await ensureAiSettingsLoaded();
            if (!isAiConfigured()) {
                showToast('先完成 AI 设置。', 'info');
                openSettingsPanel();
                return;
            }

            const input = document.getElementById('readerAiInput');
            const question = String(prefillQuestion || input?.value || '').trim();
            if (!question) {
                showToast('先输入一个问题。', 'info');
                return;
            }

            const conversation = getReaderAiConversation(itemKey);
            conversation.push({ role: 'user', content: question, createdAt: new Date().toISOString() });
            readerAiConversationByItem.set(itemKey, conversation);
            readerAiDraftByItem.set(itemKey, '');
            persistReaderAiSessionState(itemKey);
            if (input) {
                input.value = '';
            }
            readerAiRequestInFlight = true;
            rerenderReaderAiSidebar(itemKey);

            try {
                const data = await requestAiAssistant(
                    buildReaderAiRequestMessages(item),
                    'chat',
                    { currentItemId: itemKey }
                );
                await applyAiAssistantSideEffects(data);
                conversation.push({
                    role: 'assistant',
                    mode: data.mode || 'chat',
                    content: stripAiReasoningBlocks(data.message || ''),
                    citations: Array.isArray(data.citations) ? data.citations : [],
                    toolEvents: Array.isArray(data.tool_events) ? data.tool_events : [],
                    insufficientContext: Boolean(data.insufficient_context),
                    knowledgeBasePath: data.knowledge_base_path || '',
                    noteCount: Number(data.note_count || 0),
                    createdAt: new Date().toISOString(),
                });
                readerAiConversationByItem.set(itemKey, conversation);
                await persistReaderAiConversation(itemKey);
            } catch (error) {
                conversation.push({
                    role: 'assistant',
                    mode: 'chat',
                    content: error.message || 'AI 请求失败',
                    citations: [],
                    toolEvents: [],
                    isError: true,
                    createdAt: new Date().toISOString(),
                });
                readerAiConversationByItem.set(itemKey, conversation);
                try {
                    await persistReaderAiConversation(itemKey);
                } catch (saveError) {
                    console.error('Failed to persist reader AI conversation', saveError);
                }
                showToast(`AI 失败：${error.message}`, 'error');
            } finally {
                readerAiRequestInFlight = false;
                rerenderReaderAiSidebar(itemKey);
            }
        }

        async function openReaderAiSidebarForCurrentItem() {
            if (!currentOpenItemId) {
                showToast('请先打开一条笔记。', 'info');
                return;
            }
            if (!isReaderFullscreen && typeof window.toggleReaderFullscreen === 'function') {
                window.toggleReaderFullscreen();
            }
            window.openReaderSidebarPanel?.('ai');
            await ensureAiSettingsLoaded();
            const itemKey = normalizeReaderAiItemKey(currentOpenItemId);
            ensureReaderAiConversationLoaded(itemKey);
            rerenderReaderAiSidebar(itemKey);
            focusReaderAiComposer();
            window.requestAnimationFrame(() => {
                focusReaderAiComposer();
            });
            window.setTimeout(() => {
                focusReaderAiComposer();
            }, 60);
        }

        function openItemAiAssistant(event, itemId) {
            event?.stopPropagation?.();
            if (!itemId) {
                showToast('请先打开一条笔记。', 'info');
                return;
            }
            if (currentOpenItemId === itemId && modalOverlay?.classList.contains('active')) {
                openReaderAiSidebarForCurrentItem();
                return;
            }
            setAiAssistantMode('chat');
            openAskAiModal({ itemId, resetConversation: true });
            if (!askAiInput) return;
            askAiInput.value = '';
            autoResizeAiComposer(askAiInput, 200);
            askAiInput.focus();
            updateAskAiSubmitState();
        }

        function openCurrentItemAiAssistant(event) {
            event?.stopPropagation?.();
            if (modalOverlay?.classList.contains('active') && currentOpenItemId) {
                openReaderAiSidebarForCurrentItem();
                return;
            }
            if (!currentOpenItemId) {
                showToast('请先打开一条笔记。', 'info');
                return;
            }
            openItemAiAssistant(event, currentOpenItemId);
        }

        window.isAiConfigured = isAiConfigured;
        window.openAiCitation = openAiCitation;
        window.openAskAiModal = openAskAiModal;
        window.openCurrentItemAiAssistant = openCurrentItemAiAssistant;
        window.openItemAiAssistant = openItemAiAssistant;
        window.refreshAiAssistantUi = refreshAiAssistantUi;
        window.renderReaderAiSidebar = renderReaderAiSidebar;
        window.bindReaderAiSidebar = bindReaderAiSidebar;
        window.focusReaderAiComposer = focusReaderAiComposer;
        window.submitReaderAiQuestion = submitReaderAiQuestion;
        window.saveTopAiMessageToPageNote = saveTopAiMessageToPageNote;
        window.saveReaderAiMessageToPageNote = saveReaderAiMessageToPageNote;
        window.renderMarkdownContent = renderMarkdown;

        askAiBtn?.addEventListener('click', () => openAskAiModal({ itemId: null, resetConversation: true }));
        openReaderAiBtn?.addEventListener('click', openCurrentItemAiAssistant);
        openReaderAiBtn?.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                openCurrentItemAiAssistant(event);
            }
        });
        closeAskAiModal?.addEventListener('click', closeAskAiDialog);
        submitAskAiBtn?.addEventListener('click', submitAskAiQuestion);
        aiModeChatBtn?.addEventListener('click', () => setAiAssistantMode('chat'));
        aiModeAgentBtn?.addEventListener('click', () => setAiAssistantMode('agent'));

        bindAiComposer(askAiInput, {
            maxHeight: 200,
            onSubmit: submitAskAiQuestion,
        });
        aiNewConversationBtn?.addEventListener('click', startNewAiConversation);

        // 侧边栏切换
        aiMenuBtn?.addEventListener('click', () => {
            aiSidebar?.classList.toggle('is-collapsed');
        });

        // 输入框状态更新
        askAiInput?.addEventListener('input', () => {
            updateAskAiSubmitState();
        });

        askAiOverlay?.addEventListener('click', (event) => {
            if (event.target === askAiOverlay) {
                closeAskAiDialog();
            }
        });

        document.addEventListener('click', async (event) => {
            const citationBtn = event.target instanceof Element
                ? event.target.closest('[data-ai-citation-id]')
                : null;
            if (citationBtn) {
                event.preventDefault();
                const citationId = String(citationBtn.getAttribute('data-ai-citation-id') || '').trim();
                if (citationId) {
                    await openAiCitation(citationId);
                }
                return;
            }

            const copyBtn = event.target instanceof Element
                ? event.target.closest('[data-ai-copy-code]')
                : null;
            if (!copyBtn) return;
            const codeHost = copyBtn.closest('.ai-code-block') || copyBtn.closest('pre');
            const codeElement = codeHost?.matches('pre')
                ? codeHost.querySelector('code')
                : codeHost?.querySelector('pre code');
            const text = codeElement?.textContent || '';
            if (!text) return;
            const copied = await copyTextToClipboard(text);
            if (!copied) {
                showToast('代码复制失败', 'error');
                return;
            }
            copyBtn.innerHTML = AI_CODE_COPIED_ICON;
            copyBtn.setAttribute('aria-label', '已复制');
            copyBtn.setAttribute('title', '已复制');
            copyBtn.classList.add('is-copied');
            window.setTimeout(() => {
                copyBtn.innerHTML = AI_CODE_COPY_ICON;
                copyBtn.setAttribute('aria-label', '复制代码');
                copyBtn.setAttribute('title', '复制代码');
                copyBtn.classList.remove('is-copied');
            }, 1400);
        });

        queueDecorateStandaloneCodeBlocks(document);
        if (document.body && typeof MutationObserver !== 'undefined') {
            const codeBlockObserver = new MutationObserver((mutations) => {
                for (const mutation of mutations) {
                    if (mutation.type !== 'childList') continue;
                    if (mutation.addedNodes.length) {
                        queueDecorateStandaloneCodeBlocks(document);
                        break;
                    }
                }
            });
            codeBlockObserver.observe(document.body, {
                childList: true,
                subtree: true,
            });
        }

        document.addEventListener('keydown', (event) => {
            const key = String(event.key || '').toLowerCase();
            if (!(event.metaKey || event.ctrlKey) || key !== 'l') return;

            event.preventDefault();

            if (modalOverlay?.classList.contains('active') && currentOpenItemId) {
                openReaderAiSidebarForCurrentItem();
                return;
            }

            if (askAiOverlay?.classList.contains('active')) {
                askAiInput?.focus();
                return;
            }

            openAskAiModal({ itemId: null, resetConversation: true });
        });

        setAiAssistantMode('chat');
        updateAskAiInputContextUi();
