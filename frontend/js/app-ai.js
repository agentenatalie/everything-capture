        const askAiBtn = document.getElementById('askAiBtn');
        const askAiOverlay = document.getElementById('askAiOverlay');
        const closeAskAiModal = document.getElementById('closeAskAiModal');
        const askAiInput = document.getElementById('askAiInput');
        const askAiResult = document.getElementById('askAiResult');
        const submitAskAiBtn = document.getElementById('submitAskAiBtn');
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

        function escapeAiText(value) {
            return escapeHtml(String(value || '')).replace(/\n/g, '<br>');
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
            const source = String(value || '').replace(/\r\n/g, '\n').trim();
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

        function normalizeConversationForRequest() {
            return aiConversation
                .filter((entry) => (entry.role === 'user' || entry.role === 'assistant') && !entry.isError)
                .map((entry) => ({
                    role: entry.role,
                    content: String(entry.content || '').trim(),
                }))
                .filter((entry) => entry.content)
                .slice(-10);
        }

        function renderAiConversation() {
            if (!askAiResult) return;

            if (!aiConversation.length) {
                if (!isAiConfigured()) {
                    askAiResult.innerHTML = `
                        <div class="ai-welcome">
                            <div class="ai-welcome-icon">
                                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 3.75l1.93 4.32 4.32 1.93-4.32 1.93L12 16.25l-1.93-4.32-4.32-1.93 4.32-1.93L12 3.75z"/><path d="M18.35 14.85l.8 1.8 1.8.8-1.8.8-.8 1.8-.8-1.8-1.8-.8 1.8-.8.8-1.8z"/></svg>
                            </div>
                            <div class="ai-welcome-title">先配置 AI</div>
                            <div class="ai-welcome-desc">在设置页填写 API Key 后即可使用</div>
                        </div>
                    `;
                    return;
                }

                askAiResult.innerHTML = `
                    <div class="ai-welcome">
                        <div class="ai-welcome-icon">
                            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 3.75l1.93 4.32 4.32 1.93-4.32 1.93L12 16.25l-1.93-4.32-4.32-1.93 4.32-1.93L12 3.75z"/><path d="M18.35 14.85l.8 1.8 1.8.8-1.8.8-.8 1.8-.8-1.8-1.8-.8 1.8-.8.8-1.8z"/></svg>
                        </div>
                        <div class="ai-welcome-title">问我任何问题</div>
                        <div class="ai-welcome-desc">支持 Markdown 回复渲染，会优先基于你的知识库作答</div>
                    </div>
                `;
                return;
            }

            askAiResult.innerHTML = aiConversation.map((entry) => {
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

            window.requestAnimationFrame(() => {
                askAiResult.scrollTop = askAiResult.scrollHeight;
            });
        }

        async function requestAiAssistant(messages, mode = aiAssistantMode) {
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

            aiConversation.push({ role: 'user', content: question });
            askAiInput.value = '';
            renderAiConversation();

            askAiRequestInFlight = true;
            submitAskAiBtn.disabled = true;
            submitAskAiBtn.classList.add('is-loading');
            submitAskAiBtn.textContent = aiAssistantMode === 'agent' ? '执行中...' : '思考中...';

            try {
                const data = await requestAiAssistant(normalizeConversationForRequest(), aiAssistantMode);
                aiConversation.push({
                    role: 'assistant',
                    mode: data.mode || aiAssistantMode,
                    content: data.message || '',
                    citations: Array.isArray(data.citations) ? data.citations : [],
                    toolEvents: Array.isArray(data.tool_events) ? data.tool_events : [],
                    insufficientContext: Boolean(data.insufficient_context),
                    knowledgeBasePath: data.knowledge_base_path || '',
                    noteCount: Number(data.note_count || 0),
                });
                renderAiConversation();
            } catch (error) {
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
                askAiRequestInFlight = false;
                submitAskAiBtn.disabled = false;
                submitAskAiBtn.classList.remove('is-loading');
                submitAskAiBtn.textContent = '提问';
            }
        }

        async function openAskAiModal() {
            if (!(await ensureAiSessionReady({ allowRecovery: true }))) {
                showToast('无法连接本地会话。', 'error');
                return;
            }
            askAiOverlay.classList.add('active');
            await ensureAiSettingsLoaded();
            refreshAiAssistantUi();
            if (askAiInput) {
                window.setTimeout(() => askAiInput.focus(), 30);
            }
        }

        function buildItemAssistantPrompt(item) {
            if (!item) {
                return '请基于我的知识库帮我分析当前这条笔记。';
            }

            const lines = [
                `当前笔记：${getDisplayItemTitle(item) || '未命名内容'}`,
            ];
            const folderNames = Array.isArray(item.folder_names) ? item.folder_names.filter(Boolean) : [];
            if (folderNames.length) {
                lines.push(`文件夹：${folderNames.join(' / ')}`);
            }
            const preview = String(getDisplayItemPreview(item, 240) || '').trim();
            if (preview) {
                lines.push(`内容片段：${preview}`);
            }
            lines.push('请结合这条笔记以及我的知识库回答。若证据不足，直接说明。');
            return lines.join('\n');
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
            const contextPrefix = buildItemAssistantPrompt(item);
            return getReaderAiConversation(item.id)
                .filter((entry) => (entry.role === 'user' || entry.role === 'assistant') && !entry.isError)
                .map((entry) => {
                    const content = String(entry.content || '').trim();
                    if (!content) return null;
                    if (entry.role === 'user') {
                        return {
                            role: 'user',
                            content: `${contextPrefix}\n\n用户问题：${content}`,
                        };
                    }
                    return {
                        role: 'assistant',
                        content,
                    };
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
                : `
                    <div class="reader-ai-empty-state">
                        <div class="reader-ai-empty-title">Ask AI</div>
                        <div class="reader-ai-empty-copy">围绕当前笔记和知识库继续追问。右侧栏会随 reader 一起打开，你可以直接切到这里继续问。</div>
                    </div>
                `;

            const quickActionsMarkup = READER_AI_SUGGESTIONS.map((prompt) => (
                `<button class="reader-ai-quick-action" type="button" data-reader-ai-prompt="${escapeAttribute(prompt)}">${escapeHtml(prompt)}</button>`
            )).join('');

            return `
                <div class="reader-ai-sidebar-shell">
                    <div class="reader-ai-context">
                        <div class="reader-ai-context-label">当前上下文</div>
                        <div class="reader-ai-context-title">${escapeHtml(getDisplayItemTitle(item) || '未命名内容')}</div>
                        <div class="reader-ai-context-copy">会自动带上当前笔记摘要、文件夹和正文片段，不需要你重复粘贴上下文。</div>
                    </div>
                    <div class="reader-ai-quick-actions">${quickActionsMarkup}</div>
                    <div class="reader-ai-messages" id="readerAiMessages">${messagesMarkup}</div>
                    <div class="reader-ai-composer">
                        <textarea id="readerAiInput" class="reader-ai-input" placeholder="问这条笔记、问关联内容，或让 AI 帮你整理下一步..." ${isBusy ? 'disabled' : ''}>${escapeHtml(draft)}</textarea>
                        <div class="reader-ai-composer-actions">
                            <button id="readerAiClearBtn" class="reader-ai-secondary-btn" type="button" ${conversation.length ? '' : 'disabled'}>清空</button>
                            <button id="readerAiSubmitBtn" class="reader-ai-submit" type="button" ${isBusy ? 'disabled' : ''}>${isBusy ? '思考中...' : '发送'}</button>
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
                const data = await requestAiAssistant(buildReaderAiRequestMessages(item), 'chat');
                conversation.push({
                    role: 'assistant',
                    mode: data.mode || 'chat',
                    content: data.message || '',
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
            const item = typeof getItemById === 'function' ? getItemById(itemId) : null;
            setAiAssistantMode('chat');
            openAskAiModal();
            if (!askAiInput) return;
            askAiInput.value = buildItemAssistantPrompt(item);
            askAiInput.focus();
            const caret = askAiInput.value.length;
            if (typeof askAiInput.setSelectionRange === 'function') {
                askAiInput.setSelectionRange(caret, caret);
            }
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

        askAiBtn?.addEventListener('click', openAskAiModal);
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

            openAskAiModal();
        });

        setAiAssistantMode('chat');
