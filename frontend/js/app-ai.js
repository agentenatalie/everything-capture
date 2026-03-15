        const askAiBtn = document.getElementById('askAiBtn');
        const askAiOverlay = document.getElementById('askAiOverlay');
        const closeAskAiModal = document.getElementById('closeAskAiModal');
        const askAiInput = document.getElementById('askAiInput');
        const askAiResult = document.getElementById('askAiResult');
        const submitAskAiBtn = document.getElementById('submitAskAiBtn');
        const askAiMeta = document.getElementById('askAiMeta');
        const aiModeChatBtn = document.getElementById('aiModeChatBtn');
        const aiModeAgentBtn = document.getElementById('aiModeAgentBtn');
        const clearAiChatBtn = document.getElementById('clearAiChatBtn');
        const aiAgentPermissions = document.getElementById('aiAgentPermissions');

        const AI_PERMISSION_LABELS = {
            read_knowledge_base: '读取知识库',
            manage_folders: '调整文件夹',
            parse_content: '触发解析',
            sync_obsidian: '同步 Obsidian',
            sync_notion: '同步 Notion',
        };
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

        let askAiRequestInFlight = false;
        let readerAiRequestInFlight = false;
        let aiAssistantMode = 'chat';
        let aiConversation = [];
        let aiSettingsLoadPromise = null;
        let currentAiContextItemId = null;
        const readerAiConversationByItem = new Map();
        const readerAiDraftByItem = new Map();

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
                    : '输入问题...';
            }
            syncAskAiMeta();
        }

        function syncAskAiMeta() {
            if (!askAiMeta) return;
            const currentItem = getCurrentAiContextItem();
            if (askAiRequestInFlight) {
                askAiMeta.textContent = aiAssistantMode === 'agent'
                    ? 'Agent 正在检索知识库并执行已授权动作...'
                    : 'AI 正在整理当前上下文并生成回答...';
                return;
            }
            askAiMeta.textContent = currentItem
                ? `当前会带上《${getDisplayItemTitle(currentItem) || '当前内容'}》的内容分析、抓取文本和知识库上下文`
                : '按 Enter 发送，Shift+Enter 换行';
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
                const langAttr = codeLang ? ` data-lang="${escapeAttribute(codeLang)}"` : '';
                html.push(`<pre><code${langAttr}>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
                inCodeBlock = false;
                codeLang = '';
                codeLines = [];
            };

            for (const line of lines) {
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
            aiAssistantMode = mode === 'agent' ? 'agent' : 'chat';
            aiModeChatBtn?.classList.toggle('is-active', aiAssistantMode === 'chat');
            aiModeAgentBtn?.classList.toggle('is-active', aiAssistantMode === 'agent');
            renderAiAssistantPermissions();
            renderAiConversation();
        }

        function renderAiAssistantPermissions() {
            if (!aiAgentPermissions) return;
            if (aiAssistantMode !== 'agent') {
                aiAgentPermissions.style.display = 'none';
                return;
            }
            aiAgentPermissions.style.display = 'flex';
            const permissions = currentAgentPermissions();
            aiAgentPermissions.innerHTML = permissions.length
                ? permissions.map((permission) => `<span class="ai-agent-permission">${escapeHtml(AI_PERMISSION_LABELS[permission] || permission)}</span>`).join('')
                : '<span class="ai-agent-permission">只读知识库</span>';
        }

        function buildAiCitationAction(citation) {
            if (citation.library_item_id) {
                return `<button class="ai-citation-link" type="button" onclick="openAiCitation('${citation.library_item_id}')">打开笔记</button>`;
            }
            if (citation.source) {
                const safeUrl = sanitizeAiUrl(citation.source);
                if (safeUrl) {
                    return `<a class="ai-citation-link" href="${escapeAttribute(safeUrl)}" target="_blank" rel="noopener noreferrer">原文</a>`;
                }
            }
            return '';
        }

        function buildAiCitationMarkup(citation, compact = false) {
            const title = escapeHtml(citation.title || '未命名笔记');
            const summary = citation.summary
                ? `<div class="ai-citation-summary">${escapeHtml(citation.summary)}</div>`
                : '';
            const metaParts = [
                citation.folder ? escapeHtml(citation.folder) : '',
                citation.relative_path ? escapeHtml(citation.relative_path) : '',
            ].filter(Boolean);
            const meta = metaParts.length
                ? `<div class="ai-citation-meta">${metaParts.join(' · ')}</div>`
                : '';
            const action = buildAiCitationAction(citation);
            return `
                <div class="ai-citation-item${compact ? ' is-compact' : ''}">
                    <div class="ai-citation-main">
                        <div class="ai-citation-title">${title}</div>
                        ${summary}
                        ${meta}
                    </div>
                    ${action ? `<div class="ai-citation-side">${action}</div>` : ''}
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

        function renderAssistantMessage(entry, compact = false) {
            const citations = Array.isArray(entry.citations) ? entry.citations : [];
            const citationsMarkup = citations.length
                ? `
                    <div class="ai-answer-citations">
                        <div class="ai-block-title">引用内容</div>
                        <div class="ai-citation-list">${citations.map((citation) => buildAiCitationMarkup(citation, compact)).join('')}</div>
                    </div>
                `
                : '';
            const toolEventsMarkup = buildAiToolEventsMarkup(entry.toolEvents);
            const metaMarkup = buildAiMetaMarkup(entry);

            return `
                <div class="ai-chat-message${compact ? ' is-compact' : ''}">
                    <div class="ai-chat-avatar">AI</div>
                    <div class="ai-chat-bubble">
                        <div class="ai-answer-text ai-markdown${entry.isError ? ' is-error' : ''}">${renderMarkdown(entry.content || '')}</div>
                        ${metaMarkup}
                        ${toolEventsMarkup}
                        ${citationsMarkup}
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
                <div class="ai-chat-message ai-chat-message--loading${compact ? ' is-compact' : ''}" aria-live="polite">
                    <div class="ai-chat-avatar">AI</div>
                    <div class="ai-chat-bubble ai-chat-bubble--loading">
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
                            <div class="ai-welcome-icon">
                                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 4.25 13.8 8.2 17.75 10 13.8 11.8 12 15.75 10.2 11.8 6.25 10 10.2 8.2 12 4.25Z"></path><path d="M18.25 15.25 19 16.9 20.65 17.65 19 18.4 18.25 20.05 17.5 18.4 15.85 17.65 17.5 16.9 18.25 15.25Z"></path></svg>
                            </div>
                            <div class="ai-welcome-title">先配置 AI</div>
                            <div class="ai-welcome-desc">在设置页填好 API Key 后，就可以基于知识库对话或让 Agent 执行操作。</div>
                        </div>
                    `;
                    return;
                }

                askAiResult.innerHTML = `
                    <div class="ai-welcome">
                        <div class="ai-welcome-icon">
                            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 4.25 13.8 8.2 17.75 10 13.8 11.8 12 15.75 10.2 11.8 6.25 10 10.2 8.2 12 4.25Z"></path><path d="M18.25 15.25 19 16.9 20.65 17.65 19 18.4 18.25 20.05 17.5 18.4 15.85 17.65 17.5 16.9 18.25 15.25Z"></path></svg>
                        </div>
                        <div class="ai-welcome-title">${currentItem ? `围绕《${escapeHtml(getDisplayItemTitle(currentItem) || '当前内容')}》提问` : '从知识库开始'}</div>
                        <div class="ai-welcome-desc">${currentItem ? '会自动带上当前文章的内容分析、抓取文本和 OCR / 帧文字，再结合知识库回答。' : '直接提问，或切到 Agent 让它在权限允许范围内执行真实操作。'}</div>
                    </div>
                `;
                return;
            }

            const conversationMarkup = aiConversation.map((entry) => {
                if (entry.role === 'user') {
                    return `
                        <div class="ai-chat-message is-user">
                            <div class="ai-chat-avatar">你</div>
                            <div class="ai-chat-bubble"><div class="ai-chat-text">${escapeAiText(entry.content || '')}</div></div>
                        </div>
                    `;
                }
                return renderAssistantMessage(entry);
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
            aiConversation.push({ role: 'user', content: question });
            askAiInput.value = '';
            renderAiConversation();
            submitAskAiBtn.disabled = true;
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
                });
                renderAiConversation();
            } catch (error) {
                askAiRequestInFlight = false;
                aiConversation.push({
                    role: 'assistant',
                    mode: aiAssistantMode,
                    content: error.message || 'AI 请求失败',
                    citations: [],
                    toolEvents: [],
                    isError: true,
                });
                renderAiConversation();
                showToast(`AI 失败：${error.message}`, 'error');
            } finally {
                submitAskAiBtn.disabled = false;
                submitAskAiBtn.classList.remove('is-loading');
                submitAskAiBtn.setAttribute('aria-label', '发送');
                syncAskAiMeta();
            }
        }

        async function openAskAiModal(options = {}) {
            const { itemId = null, resetConversation = false } = options;
            if (!(await ensureAiSessionReady({ allowRecovery: true }))) {
                showToast('无法连接本地会话。', 'error');
                return;
            }
            setAskAiContextItemId(itemId, { resetConversation });
            askAiOverlay.classList.add('active');
            await ensureAiSettingsLoaded();
            refreshAiAssistantUi();
            if (askAiInput) {
                window.setTimeout(() => askAiInput.focus(), 30);
            }
        }

        function closeAskAiDialog() {
            askAiOverlay.classList.remove('active');
        }

        function refreshAiAssistantUi() {
            renderAiAssistantPermissions();
            renderAiConversation();
        }

        function clearAiConversation() {
            aiConversation = [];
            renderAiConversation();
        }

        function openAiCitation(libraryItemId) {
            if (!libraryItemId) return;
            if (askAiOverlay?.classList.contains('active')) {
                closeAskAiDialog();
            }
            openModalById(libraryItemId);
        }

        function getReaderAiConversation(itemId) {
            return readerAiConversationByItem.get(itemId) || [];
        }

        function rerenderReaderAiSidebar(itemId) {
            if (!currentOpenItemId || currentOpenItemId !== itemId) return;
            if (!readerSidebarOpen || readerSidebarTab !== 'ai') return;
            window.renderSidebarAiContent?.();
        }

        function buildReaderAiRequestMessages(item) {
            return getReaderAiConversation(item.id)
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
            const conversation = getReaderAiConversation(item.id);
            const draft = readerAiDraftByItem.get(item.id) || '';
            const isBusy = readerAiRequestInFlight && currentOpenItemId === item.id;

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
                ? conversation.map((entry) => {
                    if (entry.role === 'user') {
                        return `
                            <div class="ai-chat-message is-user is-compact">
                                <div class="ai-chat-avatar">你</div>
                                <div class="ai-chat-bubble"><div class="ai-chat-text">${escapeAiText(entry.content || '')}</div></div>
                            </div>
                        `;
                    }
                    return renderAssistantMessage(entry, true);
                }).join('')
                : '';

            const quickActionsMarkup = READER_AI_SUGGESTIONS.map((prompt) => (
                `<button class="reader-ai-quick-action" type="button" data-reader-ai-prompt="${escapeAttribute(prompt)}">${escapeHtml(prompt)}</button>`
            )).join('');
            const contextMarkup = `
                <div class="reader-ai-context">
                    <div class="reader-ai-context-label">当前上下文</div>
                    <div class="reader-ai-context-title">${escapeHtml(getDisplayItemTitle(item) || '未命名内容')}</div>
                    <div class="reader-ai-context-copy">会自动带上当前文章的内容分析、抓取正文和 OCR / 帧文字，不需要你重复粘贴上下文。</div>
                </div>
            `;
            const quickActionsSectionMarkup = `
                <div class="reader-ai-quick-actions">${quickActionsMarkup}</div>
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
            const input = document.getElementById('readerAiInput');
            const submitBtn = document.getElementById('readerAiSubmitBtn');
            const clearBtn = document.getElementById('readerAiClearBtn');
            const messages = document.getElementById('readerAiMessages');
            const quickActions = document.querySelectorAll('[data-reader-ai-prompt]');

            input?.addEventListener('input', () => {
                readerAiDraftByItem.set(item.id, input.value || '');
                input.style.height = 'auto';
                input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
            });

            input?.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    submitReaderAiQuestion();
                }
            });

            submitBtn?.addEventListener('click', () => submitReaderAiQuestion());
            clearBtn?.addEventListener('click', () => {
                readerAiConversationByItem.delete(item.id);
                readerAiDraftByItem.set(item.id, '');
                rerenderReaderAiSidebar(item.id);
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

            const conversation = getReaderAiConversation(item.id);
            conversation.push({ role: 'user', content: question });
            readerAiConversationByItem.set(item.id, conversation);
            readerAiDraftByItem.set(item.id, '');
            if (input) {
                input.value = '';
            }
            readerAiRequestInFlight = true;
            rerenderReaderAiSidebar(item.id);

            try {
                const data = await requestAiAssistant(
                    buildReaderAiRequestMessages(item),
                    'chat',
                    { currentItemId: item.id }
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
                });
                readerAiConversationByItem.set(item.id, conversation);
            } catch (error) {
                conversation.push({
                    role: 'assistant',
                    mode: 'chat',
                    content: error.message || 'AI 请求失败',
                    citations: [],
                    toolEvents: [],
                    isError: true,
                });
                readerAiConversationByItem.set(item.id, conversation);
                showToast(`AI 失败：${error.message}`, 'error');
            } finally {
                readerAiRequestInFlight = false;
                rerenderReaderAiSidebar(item.id);
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
            askAiInput.focus();
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
        askAiInput?.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submitAskAiQuestion();
            }
        });
        askAiInput?.addEventListener('input', () => {
            askAiInput.style.height = 'auto';
            askAiInput.style.height = `${Math.min(askAiInput.scrollHeight, 120)}px`;
        });
        clearAiChatBtn?.addEventListener('click', clearAiConversation);
        askAiOverlay?.addEventListener('click', (event) => {
            if (event.target === askAiOverlay) {
                closeAskAiDialog();
            }
        });

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
