        const askAiBtn = document.getElementById('askAiBtn');
        const askAiOverlay = document.getElementById('askAiOverlay');
        const closeAskAiModal = document.getElementById('closeAskAiModal');
        const askAiInput = document.getElementById('askAiInput');
        const askAiResult = document.getElementById('askAiResult');
        const askAiMeta = document.getElementById('askAiMeta');
        const submitAskAiBtn = document.getElementById('submitAskAiBtn');
        const openReaderAiBtn = document.getElementById('openReaderAiBtn');
        const readerAiPanel = document.getElementById('readerAiPanel');
        const aiModeChatBtn = document.getElementById('aiModeChatBtn');
        const aiModeAgentBtn = document.getElementById('aiModeAgentBtn');
        const clearAiChatBtn = document.getElementById('clearAiChatBtn');
        const aiAgentPermissions = document.getElementById('aiAgentPermissions');

        const aiAnalysisCache = new Map();
        const aiRelatedCache = new Map();
        const aiAnalysisInFlight = new Set();
        const aiRelatedInFlight = new Set();
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

        let askAiRequestInFlight = false;
        let aiAssistantMode = 'chat';
        let aiConversation = [];

        function isAiConfigured() {
            return Boolean(latestSettings?.ai_ready);
        }

        function escapeAiText(value) {
            return escapeHtml(String(value || '')).replace(/\n/g, '<br>');
        }

        function renderAiEmptyState(message) {
            return `<div class="ai-empty-copy">${escapeHtml(message)}</div>`;
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
            if (askAiMeta) {
                askAiMeta.textContent = aiAssistantMode === 'agent'
                    ? 'Agent 会先读知识库，再在你开放的权限范围内直接操作站内内容。'
                    : 'Chat 会基于知识库回答问题；如果资料不足会直接说明。';
            }
            renderAiAssistantPermissions();
            renderAiConversation();
        }

        function renderAiAssistantPermissions() {
            if (!aiAgentPermissions) return;
            if (aiAssistantMode !== 'agent') {
                aiAgentPermissions.innerHTML = '<span class="ai-agent-permission">当前模式：只回答，不执行动作</span>';
                return;
            }

            const permissions = currentAgentPermissions();
            aiAgentPermissions.innerHTML = permissions.length
                ? permissions.map((permission) => `<span class="ai-agent-permission">${escapeHtml(AI_PERMISSION_LABELS[permission] || permission)}</span>`).join('')
                : '<span class="ai-agent-permission">当前只有只读知识库权限</span>';
        }

        function buildAiCitationAction(citation) {
            if (citation.library_item_id) {
                return `<button class="ai-citation-link" type="button" onclick="openAiCitation('${citation.library_item_id}')">打开笔记</button>`;
            }
            if (citation.source) {
                return `<a class="ai-citation-link" href="${escapeAttribute(citation.source)}" target="_blank" rel="noopener noreferrer">原文</a>`;
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
                        <div class="ai-answer-card is-warning">
                            <div class="ai-answer-title">${aiAssistantMode === 'agent' ? 'AI Agent' : 'AI Chat'}</div>
                            <div class="ai-answer-text">先在设置页填写 AI API Key。Base URL 和模型已经按你的常用 Infini-AI 兼容配置预填好了。</div>
                        </div>
                    `;
                    return;
                }

                askAiResult.innerHTML = `
                    <div class="ai-answer-card">
                        <div class="ai-answer-title">${aiAssistantMode === 'agent' ? 'AI Agent' : 'AI Chat'}</div>
                        <div class="ai-answer-text">
                            ${aiAssistantMode === 'agent'
                                ? '你可以让我先检索知识库，再在权限范围内帮你调整文件夹、触发解析或发起同步。'
                                : '你可以直接围绕整个知识库发问，我会优先使用已有 summary / 摘要回答。'}
                        </div>
                    </div>
                `;
                return;
            }

            askAiResult.innerHTML = aiConversation.map((entry) => {
                if (entry.role === 'user') {
                    return `
                        <div class="ai-chat-message is-user">
                            <div class="ai-chat-bubble">
                                <div class="ai-chat-role">你</div>
                                <div class="ai-answer-text">${escapeAiText(entry.content || '')}</div>
                            </div>
                        </div>
                    `;
                }

                const citations = Array.isArray(entry.citations) ? entry.citations : [];
                const citationsMarkup = citations.length
                    ? `
                        <div class="ai-answer-citations">
                            <div class="ai-block-title">引用笔记</div>
                            <div class="ai-citation-list">${citations.map((citation) => buildAiCitationMarkup(citation, true)).join('')}</div>
                        </div>
                    `
                    : '';
                const toolEventsMarkup = buildAiToolEventsMarkup(entry.toolEvents);
                const metaBits = [];
                if (entry.knowledgeBasePath) {
                    metaBits.push(`知识库：${escapeHtml(entry.knowledgeBasePath)}`);
                }
                if (Number.isFinite(Number(entry.noteCount)) && Number(entry.noteCount) > 0) {
                    metaBits.push(`已读取 ${Number(entry.noteCount)} 篇笔记`);
                }
                const metaMarkup = metaBits.length
                    ? `<div class="ai-answer-meta">${metaBits.map((bit) => `<span>${bit}</span>`).join('')}</div>`
                    : '';
                return `
                    <div class="ai-chat-message">
                        <div class="ai-chat-bubble">
                            <div class="ai-chat-role">${entry.mode === 'agent' ? 'AI Agent' : 'AI Chat'}</div>
                            <div class="ai-answer-card${entry.isError ? ' is-error' : (entry.insufficientContext ? ' is-warning' : '')}">
                                <div class="ai-answer-text">${escapeAiText(entry.content || '')}</div>
                                ${metaMarkup}
                            </div>
                            ${toolEventsMarkup}
                            ${citationsMarkup}
                        </div>
                    </div>
                `;
            }).join('');

            window.requestAnimationFrame(() => {
                askAiResult.scrollTop = askAiResult.scrollHeight;
            });
        }

        async function submitAskAiQuestion() {
            if (!ensureAuthenticated()) return;
            if (!askAiInput || askAiRequestInFlight) return;

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
                const response = await fetch('/api/ai/assistant', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        mode: aiAssistantMode,
                        messages: normalizeConversationForRequest(),
                        top_k: 6,
                    }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || 'AI 请求失败');
                }
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

        function openAskAiModal() {
            if (!ensureAuthenticated()) return;
            askAiOverlay.classList.add('active');
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
                `请基于我的知识库分析这条笔记：${getDisplayItemTitle(item) || '未命名内容'}`,
            ];
            const folderNames = Array.isArray(item.folder_names) ? item.folder_names.filter(Boolean) : [];
            if (folderNames.length) {
                lines.push(`文件夹：${folderNames.join(' / ')}`);
            }
            const preview = String(getDisplayItemPreview(item, 180) || '').trim();
            if (preview) {
                lines.push(`内容片段：${preview}`);
            }
            lines.push('请告诉我它的核心观点、为什么值得保存、可能关联到哪些已有笔记，以及我下一步适合追问什么。');
            return lines.join('\n');
        }

        function openItemAiAssistant(event, itemId) {
            event?.stopPropagation?.();
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
            if (!currentOpenItemId) return;
            openItemAiAssistant(event, currentOpenItemId);
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

        function renderItemAiPanel(item) {
            if (!readerAiPanel || !item) return;

            const analysis = aiAnalysisCache.get(item.id);
            const related = aiRelatedCache.get(item.id);
            const analysisBusy = aiAnalysisInFlight.has(item.id);
            const relatedBusy = aiRelatedInFlight.has(item.id);
            const canUseAi = isAiConfigured();
            const knowledgeBasePath = latestSettings?.ai_knowledge_base_path || related?.knowledge_base_path || analysis?.knowledge_base_path || '';

            let analysisMarkup = '';
            if (!canUseAi) {
                analysisMarkup = `
                    <div class="ai-panel-card">
                        <div class="ai-panel-copy">配置 AI API 后，可以基于同一套 Obsidian 知识库生成这条笔记的分析。</div>
                    </div>
                `;
            } else if (analysis) {
                const summaryLine = analysis.summary_used
                    ? `<div class="ai-panel-summary-hint">优先参考已有摘要：${escapeHtml(analysis.summary_used)}</div>`
                    : '';
                const corePoints = Array.isArray(analysis.core_points) && analysis.core_points.length
                    ? `<ul class="ai-bullet-list">${analysis.core_points.map((point) => `<li>${escapeHtml(point)}</li>`).join('')}</ul>`
                    : renderAiEmptyState('这次没有拆出更多核心观点。');
                const themes = Array.isArray(analysis.themes) && analysis.themes.length
                    ? `<div class="ai-chip-list">${analysis.themes.map((theme) => `<span class="ai-chip">${escapeHtml(theme)}</span>`).join('')}</div>`
                    : renderAiEmptyState('没有明确主题标签。');
                const thinkingQuestions = Array.isArray(analysis.thinking_questions) && analysis.thinking_questions.length
                    ? `<ul class="ai-bullet-list">${analysis.thinking_questions.map((question) => `<li>${escapeHtml(question)}</li>`).join('')}</ul>`
                    : renderAiEmptyState('这次没有给出延伸问题。');

                analysisMarkup = `
                    <div class="ai-panel-card">
                        <div class="ai-block">
                            <div class="ai-block-title">一句话总结</div>
                            <div class="ai-block-copy">${escapeHtml(analysis.one_liner || '暂无')}</div>
                            ${summaryLine}
                        </div>
                        <div class="ai-block">
                            <div class="ai-block-title">核心观点拆解</div>
                            ${corePoints}
                        </div>
                        <div class="ai-block">
                            <div class="ai-block-title">为什么值得保存</div>
                            <div class="ai-block-copy">${escapeHtml(analysis.why_saved || '暂无')}</div>
                        </div>
                        <div class="ai-block">
                            <div class="ai-block-title">主题判断</div>
                            ${themes}
                        </div>
                        <div class="ai-block">
                            <div class="ai-block-title">继续思考的问题</div>
                            ${thinkingQuestions}
                        </div>
                    </div>
                `;
            } else if (analysisBusy) {
                analysisMarkup = renderAiEmptyState('AI 正在分析这条笔记...');
            } else {
                analysisMarkup = `
                    <div class="ai-panel-card">
                        <div class="ai-panel-copy">AI 会基于当前笔记与知识库里的相关笔记，给出高于 summary 一层的理解。</div>
                    </div>
                `;
            }

            let relatedMarkup = '';
            if (related && Array.isArray(related.related) && related.related.length) {
                relatedMarkup = `<div class="ai-citation-list">${related.related.map((citation) => buildAiCitationMarkup(citation, true)).join('')}</div>`;
            } else if (relatedBusy) {
                relatedMarkup = renderAiEmptyState('正在查找相关笔记...');
            } else {
                relatedMarkup = renderAiEmptyState('还没有找到可展示的相关笔记。');
            }

            readerAiPanel.innerHTML = `
                <div class="reader-ai-shell">
                    <div class="reader-ai-header">
                        <div class="reader-ai-headline">
                            <div class="reader-ai-title">AI 分析</div>
                            <div class="reader-ai-meta">${escapeHtml(knowledgeBasePath ? `知识库：${knowledgeBasePath}` : '读取同一套 Obsidian 知识库，优先使用已有摘要')}</div>
                        </div>
                        <button
                            class="extract-btn${analysisBusy ? ' is-loading' : ''}"
                            type="button"
                            onclick="runItemAiAnalysis('${item.id}')"
                            ${!canUseAi || analysisBusy ? 'disabled' : ''}
                        >
                            ${analysis ? '重新生成分析' : '生成分析'}
                        </button>
                    </div>
                    ${analysisMarkup}
                    <div class="ai-related-section">
                        <div class="ai-block-title">Related Notes</div>
                        ${relatedMarkup}
                    </div>
                </div>
            `;
        }

        async function loadRelatedNotesForItem(itemId) {
            if (!itemId || aiRelatedInFlight.has(itemId)) return;
            aiRelatedInFlight.add(itemId);
            const currentItem = getItemById(itemId);
            if (currentItem) renderItemAiPanel(currentItem);

            try {
                const response = await fetch(`/api/ai/items/${itemId}/related?limit=5`);
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || '加载相关笔记失败');
                }
                aiRelatedCache.set(itemId, data);
            } catch (error) {
                console.warn('Failed to load related notes', error);
                aiRelatedCache.set(itemId, { related: [], knowledge_base_path: latestSettings?.ai_knowledge_base_path || '' });
            } finally {
                aiRelatedInFlight.delete(itemId);
                const nextItem = getItemById(itemId);
                if (nextItem && currentOpenItemId === itemId) {
                    renderItemAiPanel(nextItem);
                }
            }
        }

        async function runItemAiAnalysis(itemId) {
            if (!itemId || aiAnalysisInFlight.has(itemId)) return;
            if (!isAiConfigured()) {
                showToast('先完成 AI 设置。', 'info');
                openSettingsPanel();
                return;
            }

            aiAnalysisInFlight.add(itemId);
            const currentItem = getItemById(itemId);
            if (currentItem) renderItemAiPanel(currentItem);

            try {
                const response = await fetch(`/api/ai/items/${itemId}/analysis`, {
                    method: 'POST',
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || '生成 AI 分析失败');
                }
                aiAnalysisCache.set(itemId, data);
            } catch (error) {
                showToast(`AI 分析失败：${error.message}`, 'error');
            } finally {
                aiAnalysisInFlight.delete(itemId);
                const nextItem = getItemById(itemId);
                if (nextItem && currentOpenItemId === itemId) {
                    renderItemAiPanel(nextItem);
                }
            }
        }

        function refreshItemAiPanel(item) {
            if (!readerAiPanel || !item) return;
            renderItemAiPanel(item);
            if (!aiRelatedCache.has(item.id)) {
                loadRelatedNotesForItem(item.id);
            }
        }

        function openAiCitation(libraryItemId) {
            if (!libraryItemId) return;
            if (askAiOverlay?.classList.contains('active')) {
                closeAskAiDialog();
            }
            openModalById(libraryItemId);
        }

        window.runItemAiAnalysis = runItemAiAnalysis;
        window.refreshItemAiPanel = refreshItemAiPanel;
        window.openAiCitation = openAiCitation;
        window.openCurrentItemAiAssistant = openCurrentItemAiAssistant;
        window.openItemAiAssistant = openItemAiAssistant;
        window.refreshAiAssistantUi = refreshAiAssistantUi;

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
        clearAiChatBtn?.addEventListener('click', clearAiConversation);
        aiModeChatBtn?.addEventListener('click', () => setAiAssistantMode('chat'));
        aiModeAgentBtn?.addEventListener('click', () => setAiAssistantMode('agent'));
        askAiInput?.addEventListener('keydown', (event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault();
                submitAskAiQuestion();
            }
        });
        askAiOverlay?.addEventListener('click', (event) => {
            if (event.target === askAiOverlay) {
                closeAskAiDialog();
            }
        });

        setAiAssistantMode('chat');
