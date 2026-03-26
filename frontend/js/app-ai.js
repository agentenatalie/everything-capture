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
            parse_item_content: '识别内容',
            sync_item_to_obsidian: '同步到 Obsidian',
            sync_item_to_notion: '同步到 Notion',
            execute_sandbox_command: '沙箱命令执行',
            export_items_to_zip: '导出内容打包',
            create_folder: '创建文件夹',
            batch_assign_item_folders: '批量归档',
            save_memory: '记住偏好',
            delete_memory: '删除记忆',
            web_search: '联网搜索',
        };
        const AI_MUTATING_TOOLS = new Set([
            'assign_item_folders',
            'parse_item_content',
            'sync_item_to_obsidian',
            'sync_item_to_notion',
            'execute_sandbox_command',
            'export_items_to_zip',
            'create_folder',
            'batch_assign_item_folders',
        ]);
        const READER_AI_SUGGESTIONS = [
            '结合正文和我的笔记，总结核心观点',
            '综合正文内容和笔记，这条为什么值得保存？',
            '基于正文和笔记内容，它和我已有的哪些知识相关？',
            '结合正文和笔记，给我 3 个值得继续追问的问题',
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

        async function ensureAiSessionReady() { return true; }

        function normalizeAiRequestError(error) {
            const message = String(error?.message || error || '').trim();
            if (!message) return 'AI 请求失败';
            if (isAiNetworkFailure(error)) {
                return '无法连接到本地 AI 服务，请确认后端仍在运行。';
            }
            return message;
        }

        async function ensureAiSettingsLoaded() {
            if (latestSettings || typeof loadSettings !== 'function') {
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
                content: entry.content || '',
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
                    content: entry.content || '',
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

        /**
         * Extract thinking blocks and answer from AI response content.
         * Supports both <think>...</think> tags and JSON {"think": ..., "answer": ...} format.
         * Returns { thinking: string|null, answer: string }
         */
        function extractThinkingAndAnswer(value) {
            const raw = String(value || '');
            if (!raw.trim()) return { thinking: null, answer: '' };

            // Try JSON format: {"think": "...", "answer": "..."}
            const trimmed = raw.trim();
            if (trimmed.startsWith('{')) {
                try {
                    const parsed = JSON.parse(trimmed);
                    if (parsed && typeof parsed.think === 'string' && typeof parsed.answer === 'string') {
                        return {
                            thinking: parsed.think.trim() || null,
                            answer: parsed.answer.trim(),
                        };
                    }
                } catch (_) {
                    // Not valid JSON, fall through to <think> tag parsing
                }
            }

            // Try <think>...</think> tag format
            const thinkMatch = raw.match(/<think\b[^>]*>([\s\S]*?)<\/think>/i);
            if (thinkMatch) {
                const thinking = thinkMatch[1].trim() || null;
                const answer = raw
                    .replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, '')
                    .replace(/\n{3,}/g, '\n\n')
                    .trim();
                return { thinking, answer };
            }

            // Check for open <think> tag without closing (streaming in progress)
            const openThinkMatch = raw.match(/<think\b[^>]*>([\s\S]*)$/i);
            if (openThinkMatch) {
                return {
                    thinking: openThinkMatch[1].trim() || null,
                    answer: '',
                    _thinkingInProgress: true,
                };
            }

            return { thinking: null, answer: raw };
        }

        /**
         * Render a collapsible thinking block.
         * @param {string} thinking - The thinking content
         * @param {boolean} inProgress - Whether thinking is still streaming
         * @returns {string} HTML string
         */
        function renderThinkingBlock(thinking, inProgress = false) {
            if (!thinking) return '';
            const thinkingHtml = renderMarkdown(thinking);
            const openAttr = inProgress ? ' open' : '';
            return `
                <details class="ai-thinking-toggle"${openAttr}>
                    <summary class="ai-thinking-summary">思考过程</summary>
                    <div class="ai-thinking-content ai-markdown">${thinkingHtml}</div>
                </details>
            `;
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
            if (raw.startsWith('/api/')) {
                return raw;
            }
            return '';
        }

        function renderInlineMarkdown(value) {
            const placeholders = [];
            let html = escapeHtml(String(value || ''));

            html = html.replace(/`([^`]+)`/g, (_, code) => {
                const token = `\x00AICODE${placeholders.length}\x00`;
                // If the backtick content is an export download path, render as download link instead of code
                if (code.trim().startsWith('/api/ai/exports/')) {
                    const path = code.trim();
                    const fileName = decodeURIComponent(path.split('/').pop());
                    placeholders.push(`<a href="${escapeAttribute(path)}" download style="color:#3b83f6">${escapeHtml(fileName)}</a>`);
                } else {
                    placeholders.push(`<code>${escapeHtml(code)}</code>`);
                }
                return token;
            });

            html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
                const safeUrl = sanitizeAiUrl(url);
                if (!safeUrl) return escapeHtml(label);
                const token = `\x00AICODE${placeholders.length}\x00`;
                const isDownload = safeUrl.startsWith('/api/ai/exports/');
                const attrs = isDownload ? `href="${escapeAttribute(safeUrl)}" download style="color:#3b83f6"` : `href="${escapeAttribute(safeUrl)}" target="_blank" rel="noopener noreferrer"`;
                placeholders.push(`<a ${attrs}>${escapeHtml(label)}</a>`);
                return token;
            });

            // Auto-link bare /api/ai/exports/ paths as download links
            html = html.replace(/(\/api\/ai\/exports\/[^\s<>)"',;，。、！？》）\]]+)/gi, (match) => {
                const token = `\x00AICODE${placeholders.length}\x00`;
                const fileName = decodeURIComponent(match.split('/').pop());
                placeholders.push(`<a href="${escapeAttribute(match)}" download style="color:#3b83f6">${escapeHtml(fileName)}</a>`);
                return token;
            });

            // Auto-link bare URLs (https://... or http://...)
            html = html.replace(/(?<![="'\w/])(https?:\/\/[^\s<>)"',;，。、！？》）\]]+)/gi, (match) => {
                const token = `\x00AICODE${placeholders.length}\x00`;
                placeholders.push(`<a href="${escapeAttribute(match)}" target="_blank" rel="noopener noreferrer">${match}</a>`);
                return token;
            });

            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>');
            html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
            html = html.replace(/_([^_]+)_/g, '<em>$1</em>');
            html = html.replace(/~~([^~]+)~~/g, '<del>$1</del>');

            placeholders.forEach((replacement, index) => {
                html = html.replace(`\x00AICODE${index}\x00`, replacement);
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
            if (latestSettings?.ai_agent_can_execute_commands) {
                permissions.push('execute_commands');
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
                    { title: '整理最近保存的内容', description: '自动分类和整理最近的笔记', prompt: '请帮我整理最近保存的所有内容。按主题或领域自动分类，对没有归入文件夹的内容建议合适的文件夹，对已有标签的内容检查标签是否准确，并将分类结果执行到位。' },
                    { title: '导出为 Markdown', description: '按主题打包内容为 MD 文件', prompt: '请搜索我收藏库中的所有内容，按主题分类整理后导出为一个合并的 Markdown 文件。每条内容保留完整正文、来源链接和保存时间，用清晰的标题层级组织。' },
                    { title: '生成主题摘要报告', description: '围绕某个主题汇总并输出结构化文档', prompt: '请在我的收藏库中搜索与以下主题相关的所有内容，生成一份结构化的摘要报告，包括核心观点、关键数据、不同来源的观点对比，最后导出为 Markdown 文件。主题是：' },
                    { title: '识别全部内容', description: '识别图片文字和视频语音', prompt: '请检查我的知识库，找出所有尚未解析（parse_status 不是 done）的内容，逐一触发内容解析。完成后汇报一共解析了多少条、有哪些解析失败需要注意。' },
                ]
                : [
                    { title: '总结最近保存内容', description: '从知识库里挑出最近最值得继续看的内容', prompt: '请从我的知识库中找出最近保存的内容，按主题归类总结。对每条内容用一两句话概括核心观点，并标注哪些值得深入阅读、哪些可以归档。最后给出一个整体的知识积累趋势观察。' },
                    { title: '帮我找相关笔记', description: '围绕一个主题串起已有记录和潜在线索', prompt: '我想探索一个主题，请在我的知识库中搜索所有相关的笔记和内容。将找到的内容按关联程度排列，说明它们之间的联系和共同线索，并指出哪些方向还缺少资料、值得进一步收集。主题是：' },
                    { title: '把一条内容拆成行动', description: '从当前笔记里提炼下一步、待办和追问点', prompt: '请分析我当前正在阅读的这条内容，从中提取所有可执行的行动项、待办事项和值得追问的问题。按优先级排列，并为每个行动项给出具体的下一步建议。' },
                    { title: '分析当前内容', description: '结合当前文章和知识库给出结构化判断', prompt: '请对我当前正在阅读的内容进行深度分析：1) 提炼核心论点和关键信息；2) 在我的知识库中找出与之相关或矛盾的已有笔记；3) 评估内容的可信度和价值；4) 给出我应该如何利用这些信息的建议。' },
                ];

            welcomeGrid.innerHTML = starters.map((item, idx) => `
                <button class="ai-starter" type="button" data-ai-starter-idx="${idx}">
                    <div class="ai-starter-title">${escapeHtml(item.title)}</div>
                    <div class="ai-starter-desc">${escapeHtml(item.description)}</div>
                </button>
            `).join('');

            welcomeGrid.querySelectorAll('[data-ai-starter-idx]').forEach((button) => {
                button.addEventListener('click', () => {
                    const idx = Number(button.getAttribute('data-ai-starter-idx'));
                    const starter = starters[idx];
                    if (!starter || !askAiInput) return;
                    askAiInput.value = starter.prompt || starter.title;
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
            // Filter out export_items_to_zip events — download link is already in the message text
            const filtered = toolEvents.filter((e) => e.name !== 'export_items_to_zip');
            if (!filtered.length) return '';
            return `
                <div class="ai-tool-events">
                    ${filtered.map((event) => {
                        return `
                        <div class="ai-tool-event${event.status === 'failed' ? ' is-failed' : ''}">
                            <div class="ai-tool-event-name">${escapeHtml(AI_TOOL_LABELS[event.name] || event.name || 'Agent')}</div>
                            <div class="ai-tool-event-summary">${renderInlineMarkdown(event.summary || '')}</div>
                        </div>
                        `;
                    }).join('')}
                </div>
            `;
        }

        function buildAiMetaMarkup(entry) {
            const metaBits = [];
            if (entry.knowledgeBasePath) {
                metaBits.push(`知识库：${escapeHtml(entry.knowledgeBasePath)}`);
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
            const needsFolderRefresh = toolEvents.some((event) => {
                const name = String(event?.name || '');
                return event
                    && (name === 'assign_item_folders' || name === 'batch_assign_item_folders' || name === 'create_folder')
                    && String(event.status || 'completed') !== 'failed';
            });

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

        function _buildCitationRefMap(content, citations) {
            // Build a map from [N] index → library_item_id
            // Backend returns citations in the order [N] markers appear in the text
            // So we parse the unique [N] values from text and pair with citations in order
            const refMap = {};
            if (!Array.isArray(citations) || !citations.length) return refMap;
            const raw = String(content || '');
            const seen = new Set();
            const ordered = [];
            const re = /\[(\d{1,3})\]/g;
            let m;
            while ((m = re.exec(raw)) !== null) {
                const n = parseInt(m[1], 10);
                if (!seen.has(n)) {
                    seen.add(n);
                    ordered.push(n);
                }
            }
            ordered.forEach((n, i) => {
                const c = citations[i];
                if (c && c.library_item_id) {
                    refMap[n] = c;
                }
            });
            return refMap;
        }

        function _linkifyCitationRefs(html, content, citations) {
            // Convert [N] in rendered HTML to clickable citation buttons
            if (!Array.isArray(citations) || !citations.length) return html;
            const refMap = _buildCitationRefMap(content, citations);
            if (!Object.keys(refMap).length) return html;

            return html.replace(/\[(\d{1,3})\]/g, (match, num) => {
                const n = parseInt(num, 10);
                const citation = refMap[n];
                if (citation && citation.library_item_id) {
                    const cId = escapeAttribute(citation.library_item_id);
                    const cTitle = escapeHtml(citation.title || `引用 ${num}`);
                    return `<button class="ai-citation-ref" data-ai-citation-id="${cId}" title="${cTitle}" type="button">[${num}]</button>`;
                }
                return match;
            });
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
            const toolEventsMarkup = buildAiToolEventsMarkup(entry.toolEvents);
            const metaMarkup = buildAiMetaMarkup(entry);
            const actionsMarkup = buildAiMessageActionsMarkup({ itemId, conversationId, messageIndex, origin, entry });

            // Extract thinking blocks for collapsible display
            const { thinking, answer } = extractThinkingAndAnswer(entry.content || '');
            const thinkingMarkup = renderThinkingBlock(thinking);

            const displayContent = answer || entry.content || '';
            let markdownHtml = renderMarkdown(displayContent);
            // Make [N] references clickable — link to the cited item
            if (citations.length) {
                markdownHtml = _linkifyCitationRefs(markdownHtml, displayContent, entry.citations);
            }

            const copyBtnMarkup = (!entry.isError && displayContent.trim())
                ? `<button class="ai-msg-copy-btn" type="button" data-ai-copy-msg aria-label="复制" title="复制">${AI_CODE_COPY_ICON}</button>`
                : '';

            const toolbarMarkup = (copyBtnMarkup || actionsMarkup) ? `
                            <div class="ai-msg-toolbar">
                                ${actionsMarkup}
                                ${copyBtnMarkup}
                            </div>` : '';

            return `
                <div class="ai-msg${compact ? ' is-compact' : ''}">
                    <div class="ai-msg-inner">
                        <div class="ai-msg-content">
                            ${thinkingMarkup}
                            <div class="ai-markdown${entry.isError ? ' is-error' : ''}">${markdownHtml}</div>
                            ${metaMarkup}
                            ${toolEventsMarkup}
                            ${toolbarMarkup}
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

        function updateAiNavTrack() {
            const track = document.getElementById('aiNavTrack');
            if (!track || !askAiResult) { if (track) track.classList.remove('is-visible'); return; }
            const userMsgs = askAiResult.querySelectorAll('.ai-msg.is-user');
            if (userMsgs.length < 2) { track.classList.remove('is-visible'); track.innerHTML = ''; return; }

            const scrollH = askAiResult.scrollHeight;
            const clientH = askAiResult.clientHeight;
            if (scrollH <= clientH) { track.classList.remove('is-visible'); track.innerHTML = ''; return; }

            track.innerHTML = '';
            userMsgs.forEach((msg) => {
                const item = document.createElement('div');
                item.className = 'ai-nav-item';

                const mark = document.createElement('div');
                mark.className = 'ai-nav-mark';

                const label = document.createElement('div');
                label.className = 'ai-nav-label';
                const text = (msg.querySelector('.ai-msg-content')?.textContent || '').trim();
                label.textContent = text.length > 10 ? text.slice(0, 10) + '…' : text;

                item.appendChild(label);
                item.appendChild(mark);
                item.addEventListener('click', () => {
                    msg.scrollIntoView({ behavior: 'instant', block: 'start' });
                });
                track.appendChild(item);
            });
            track.classList.add('is-visible');
            _updateAiNavActive();
        }

        function _updateAiNavActive() {
            const track = document.getElementById('aiNavTrack');
            if (!track || !askAiResult) return;
            const items = track.querySelectorAll('.ai-nav-item');
            const userMsgs = askAiResult.querySelectorAll('.ai-msg.is-user');
            if (!items.length || items.length !== userMsgs.length) return;

            const scrollTop = askAiResult.scrollTop;
            const clientH = askAiResult.clientHeight;
            let activeIdx = 0;
            userMsgs.forEach((msg, i) => {
                if (msg.offsetTop <= scrollTop + clientH * 0.3) activeIdx = i;
            });
            items.forEach((item, i) => {
                const mark = item.querySelector('.ai-nav-mark');
                if (mark) mark.classList.toggle('is-active', i === activeIdx);
            });
        }

        // Throttled scroll listener for nav track
        let _aiNavScrollRaf = 0;
        if (document.getElementById('askAiResult')) {
            document.getElementById('askAiResult').addEventListener('scroll', () => {
                if (_aiNavScrollRaf) return;
                _aiNavScrollRaf = window.requestAnimationFrame(() => {
                    _aiNavScrollRaf = 0;
                    _updateAiNavActive();
                });
            });
        }

        function renderAiConversation() {
            if (!askAiResult) return;
            const currentItem = getCurrentAiContextItem();
            syncAskAiMeta();
            askAiResult.classList.toggle('has-messages', aiConversation.length > 0);

            if (!aiConversation.length) {
                if (!isAiConfigured()) {
                    askAiResult.innerHTML = `
                        <div class="ai-welcome">
                            <div class="ai-welcome-badge">Ask AI 尚未启用</div>
                            <h1 class="ai-welcome-title">先完成 AI 设置</h1>
                            <p class="ai-welcome-subtitle">在设置里填好模型、Base URL 和密钥后，这里就能开始连续对话。</p>
                        </div>
                    `;
                    updateAiNavTrack();
                    return;
                }

                askAiResult.innerHTML = renderAiHome(currentItem);
                renderAiWelcome();
                updateAiNavTrack();
                return;
            }

            const conversationMarkup = aiConversation.map((entry, index) => {
                if (entry._streamStatus !== undefined) {
                    // Streaming entry — rendered separately, skip here
                    return '';
                }
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
            // Show old-style loading card only for agent mode (chat mode uses streaming)
            const isStreamingChat = askAiRequestInFlight && aiAssistantMode === 'chat';
            const loadingMarkup = (askAiRequestInFlight && !isStreamingChat)
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
                updateAiNavTrack();
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

        function _updateStreamingMessage(entry) {
            if (!askAiResult) return;
            const streamingEl = askAiResult.querySelector('.ai-msg--streaming');
            if (!streamingEl) return;
            const contentEl = streamingEl.querySelector('.ai-msg-content > .ai-markdown');
            const statusEl = streamingEl.querySelector('.ai-streaming-status');
            let thinkingEl = streamingEl.querySelector('.ai-thinking-toggle');

            // Extract thinking blocks from streaming content
            const { thinking, answer, _thinkingInProgress } = extractThinkingAndAnswer(entry.content || '');

            // Handle thinking block UI
            if (thinking) {
                if (!thinkingEl) {
                    // Insert thinking toggle before the markdown content
                    const msgContent = streamingEl.querySelector('.ai-msg-content');
                    if (msgContent && contentEl) {
                        const thinkHtml = renderThinkingBlock(thinking, _thinkingInProgress);
                        contentEl.insertAdjacentHTML('beforebegin', thinkHtml);
                        thinkingEl = streamingEl.querySelector('.ai-thinking-toggle');
                    }
                } else {
                    // Update existing thinking content
                    const thinkContent = thinkingEl.querySelector('.ai-thinking-content');
                    if (thinkContent) {
                        thinkContent.innerHTML = renderMarkdown(thinking);
                    }
                }
            }

            if (contentEl) {
                contentEl.innerHTML = renderMarkdown(answer || '');
            }
            if (statusEl) {
                statusEl.textContent = entry._streamStatus || '';
                statusEl.style.display = entry._streamStatus ? '' : 'none';
            }
            window.requestAnimationFrame(() => {
                askAiResult.scrollTop = askAiResult.scrollHeight;
            });
        }

        async function _streamChatAssistant(messages, currentItemId) {
            const response = await fetch('/api/ai/assistant/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    mode: 'chat',
                    messages,
                    top_k: 6,
                    current_item_id: currentItemId || undefined,
                }),
            });
            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || 'AI 请求失败');
            }
            return response.body;
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

            // Agent mode: use the original non-streaming endpoint
            if (aiAssistantMode === 'agent') {
                try {
                    const data = await requestAiAssistant(
                        normalizeConversationForRequest(),
                        'agent',
                        { currentItemId: currentAiContextItemId }
                    );
                    await applyAiAssistantSideEffects(data);
                    askAiRequestInFlight = false;
                    aiConversation.push({
                        role: 'assistant',
                        mode: data.mode || 'agent',
                        content: data.message || '',
                        citations: Array.isArray(data.citations) ? data.citations : [],
                        toolEvents: Array.isArray(data.tool_events) ? data.tool_events : [],
                        insufficientContext: Boolean(data.insufficient_context),
                        knowledgeBasePath: data.knowledge_base_path || '',
                        noteCount: Number(data.note_count || 0),
                        createdAt: new Date().toISOString(),
                    });
                    aiAgentConversation = aiConversation.slice();
                    renderAiConversation();
                    await persistTopAiConversation();
                } catch (error) {
                    askAiRequestInFlight = false;
                    aiConversation.push({
                        role: 'assistant', mode: 'agent',
                        content: error.message || 'AI 请求失败',
                        citations: [], toolEvents: [], isError: true,
                        createdAt: new Date().toISOString(),
                    });
                    aiAgentConversation = aiConversation.slice();
                    renderAiConversation();
                    try { await persistTopAiConversation(); } catch (_) {}
                    showToast(`AI 失败：${error.message}`, 'error');
                } finally {
                    submitAskAiBtn.classList.remove('is-loading');
                    submitAskAiBtn.setAttribute('aria-label', '发送');
                    syncAskAiMeta();
                    updateAskAiSubmitState();
                }
                return;
            }

            // Chat mode: streaming
            const streamEntry = {
                role: 'assistant',
                mode: 'chat',
                content: '',
                citations: [],
                toolEvents: [],
                _streamStatus: '正在检索知识库…',
                createdAt: new Date().toISOString(),
            };
            aiConversation.push(streamEntry);
            aiChatConversation = aiConversation.slice();

            // Render the streaming placeholder
            if (askAiResult) {
                const existingLoading = askAiResult.querySelector('.ai-msg--loading');
                if (existingLoading) existingLoading.remove();
                const streamHtml = `
                    <div class="ai-msg ai-msg--streaming">
                        <div class="ai-msg-inner">
                            <div class="ai-msg-content">
                                <div class="ai-streaming-status">正在检索知识库…</div>
                                <div class="ai-markdown"></div>
                            </div>
                        </div>
                    </div>
                `;
                askAiResult.insertAdjacentHTML('beforeend', streamHtml);
                window.requestAnimationFrame(() => { askAiResult.scrollTop = askAiResult.scrollHeight; });
            }

            try {
                const body = await _streamChatAssistant(
                    normalizeConversationForRequest(),
                    currentAiContextItemId,
                );
                const reader = body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                let doneCitations = [];

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        const trimmed = line.trim();
                        if (!trimmed || !trimmed.startsWith('data: ')) continue;
                        let event;
                        try { event = JSON.parse(trimmed.slice(6)); } catch (_) { continue; }

                        if (event.type === 'status') {
                            streamEntry._streamStatus = event.message || '';
                            _updateStreamingMessage(streamEntry);
                        } else if (event.type === 'delta') {
                            if (streamEntry._streamStatus) {
                                streamEntry._streamStatus = '';
                            }
                            streamEntry.content += event.content || '';
                            _updateStreamingMessage(streamEntry);
                        } else if (event.type === 'done') {
                            streamEntry.content = event.message || streamEntry.content;
                            doneCitations = Array.isArray(event.citations) ? event.citations : [];
                            streamEntry.citations = doneCitations;
                            streamEntry.insufficientContext = Boolean(event.insufficient_context);
                        } else if (event.type === 'error') {
                            throw new Error(event.message || 'AI streaming failed');
                        }
                    }
                }

                // Finalize: remove streaming class, do a full re-render
                delete streamEntry._streamStatus;
                askAiRequestInFlight = false;
                aiChatConversation = aiConversation.slice();
                renderAiConversation();
                await persistTopAiConversation();
            } catch (error) {
                askAiRequestInFlight = false;
                // Replace streaming entry with error
                const idx = aiConversation.indexOf(streamEntry);
                if (idx >= 0) {
                    aiConversation[idx] = {
                        role: 'assistant', mode: 'chat',
                        content: error.message || 'AI 请求失败',
                        citations: [], toolEvents: [], isError: true,
                        createdAt: new Date().toISOString(),
                    };
                }
                aiChatConversation = aiConversation.slice();
                renderAiConversation();
                try { await persistTopAiConversation(); } catch (_) {}
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

            askAiOverlay.classList.remove('is-closing');
            askAiOverlay.classList.add('active');
            document.title = 'Ask AI - Everything Capture';
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
            if (!askAiOverlay || askAiOverlay.classList.contains('is-closing')) return;
            if (history.state?.ai) {
                history.back();
                return;
            }
            _performAskAiClose();
        }

        function _performAskAiClose() {
            if (!askAiOverlay || askAiOverlay.classList.contains('is-closing')) return;
            document.title = 'Everything Capture - 收录看板';
            askAiOverlay.classList.remove('is-behind-reader');
            askAiOverlay.classList.add('is-closing');
            window.setTimeout(() => {
                askAiOverlay.classList.remove('active', 'is-closing');
                document.body.style.overflow = '';
            }, 240);
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
            const navOrigin = options.navOrigin || null;
            if (!item && !itemId) return false;

            const event = new CustomEvent('everything-capture:open-item', {
                cancelable: true,
                detail: {
                    item,
                    itemId,
                    navOrigin,
                },
            });
            window.dispatchEvent(event);
            if (event.defaultPrevented) {
                return true;
            }

            if (item && typeof window.openModalByItem === 'function') {
                window.openModalByItem(item, { pushToNavStack: true, navOrigin });
                return true;
            }
            if (itemId && typeof window.openModalById === 'function') {
                window.openModalById(itemId, { pushToNavStack: true, navOrigin });
                return true;
            }
            return false;
        }

        async function openAiCitation(libraryItemId) {
            const normalizedItemId = String(libraryItemId || '').trim();
            if (!normalizedItemId) return;
            const fromAskAi = askAiOverlay?.classList.contains('active') && !askAiOverlay.classList.contains('is-closing');
            const navOrigin = fromAskAi ? 'askAi' : (currentOpenItemId ? 'readerAi' : null);
            if (fromAskAi) {
                // Hide Ask AI behind the reader without animation — it stays "active"
                // so we can reveal it instantly when the user navigates back.
                askAiOverlay.classList.add('is-behind-reader');
            }

            const getItem = typeof window.getItemById === 'function' ? window.getItemById : null;

            if (typeof getItem === 'function') {
                const cachedItem = getItem(normalizedItemId);
                if (cachedItem && requestOpenCitationItem({ item: cachedItem, itemId: normalizedItemId, navOrigin })) {
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
                    if (requestOpenCitationItem({ item, itemId: normalizedItemId, navOrigin })) {
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
                    <div class="reader-ai-messages" id="readerAiMessages">${conversation.length ? '' : contextMarkup + quickActionsSectionMarkup}${messagesMarkup}${loadingMarkup}</div>
                    <div class="reader-ai-composer${isBusy ? ' is-loading' : ''}">
                        <textarea id="readerAiInput" class="reader-ai-input" placeholder="问这条笔记、问关联内容，或让 AI 帮你整理下一步..." ${isBusy ? 'disabled' : ''}>${escapeHtml(draft)}</textarea>
                        <div class="reader-ai-composer-actions">
                            <button id="readerAiClearBtn" class="reader-ai-secondary-btn" type="button" ${conversation.length ? '' : 'disabled'}>清空</button>
                            <button id="readerAiSubmitBtn" class="reader-ai-submit${isBusy ? ' is-loading' : ''}" type="button" ${isBusy ? 'disabled' : ''}>${isBusy ? '<span class="reader-ai-spinner"></span>' : '发送'}</button>
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
                    content: data.message || '',
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

        window.closeAskAiOverlay = _performAskAiClose;
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

        askAiBtn?.addEventListener('click', () => {
            history.pushState({ ai: true }, '', '/ask-ai');
            openAskAiModal({ itemId: null, resetConversation: true });
        });
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

            const msgCopyBtn = event.target instanceof Element
                ? event.target.closest('[data-ai-copy-msg]')
                : null;
            if (msgCopyBtn) {
                const msgEl = msgCopyBtn.closest('.ai-msg');
                const markdown = msgEl?.querySelector('.ai-markdown');
                const text = markdown?.innerText || '';
                if (!text) return;
                const copied = await copyTextToClipboard(text);
                if (!copied) {
                    showToast('复制失败', 'error');
                    return;
                }
                msgCopyBtn.innerHTML = AI_CODE_COPIED_ICON;
                msgCopyBtn.setAttribute('aria-label', '已复制');
                msgCopyBtn.setAttribute('title', '已复制');
                msgCopyBtn.classList.add('is-copied');
                window.setTimeout(() => {
                    msgCopyBtn.innerHTML = AI_CODE_COPY_ICON;
                    msgCopyBtn.setAttribute('aria-label', '复制');
                    msgCopyBtn.setAttribute('title', '复制');
                    msgCopyBtn.classList.remove('is-copied');
                }, 1400);
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
            const mod = event.metaKey || event.ctrlKey;
            if (!mod) return;

            if (key === 'l') {
                event.preventDefault();
                if (modalOverlay?.classList.contains('active') && currentOpenItemId) {
                    openReaderAiSidebarForCurrentItem();
                    return;
                }
                if (askAiOverlay?.classList.contains('active')) {
                    askAiInput?.focus();
                    return;
                }
                history.pushState({ ai: true }, '', '/ask-ai');
                openAskAiModal({ itemId: null, resetConversation: true });
                return;
            }
        });

        // ⌘B: new conversation when AI overlay is open
        window.addEventListener('keydown', (event) => {
            if (!(event.metaKey || event.ctrlKey) || event.shiftKey || event.key.toLowerCase() !== 'b') return;
            if (!askAiOverlay?.classList.contains('active') || askAiOverlay.classList.contains('is-closing')) return;
            event.preventDefault();
            event.stopPropagation();
            startNewAiConversation();
        }, true);

        setAiAssistantMode('chat');
        updateAskAiInputContextUi();
