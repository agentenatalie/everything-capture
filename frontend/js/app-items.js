        let activeItemDragPreview = null;
        let isReaderFullscreen = false;
        let readerSidebarOpen = false;
        let readerSidebarTab = 'note';
        const itemPageNotesByItem = new Map();
        const itemPageNotesLoadStateByItem = new Map();
        const itemPageNotesErrorByItem = new Map();
        const itemPageNoteMutationIds = new Set();
        let readerSidebarResizing = false;
        let readerSidebarStartX = 0;
        let readerSidebarStartWidth = 0;
        let readerChromeHidden = false;
        let readerLastScrollTop = 0;
        let readerScrollTicking = false;
        let readerScrollIntent = 0;
        const READER_SIDEBAR_MIN_WIDTH = 360;
        const READER_SIDEBAR_MAX_WIDTH = 680;
        const analysisAiSparkIcon = `
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" id="Ai-Spark-Generate-Text--Streamline-Outlined-Material-Pro-Free" height="24" width="24" aria-hidden="true" focusable="false">
                <desc>
                    Ai Spark Generate Text Streamline Icon: https://streamlinehq.com
                </desc>
                <g id="ai-spark-generate-text">
                    <path id="Union" fill="#000000" d="M20 20H4v-2h16zm0 -4H4v-2h16zm-7 -4H4v-2h9zm6 -10.5c0 1.93297 1.567 3.49998 3.5 3.5v2l-0.1748 0.00391c-1.7922 0.08816 -3.2297 1.52481 -3.3203 3.31639L19 10.5h-2c0 -1.87274 -1.4708 -3.4016 -3.3203 -3.49512L13.5 7V5l0.1797 -0.00488C15.5292 4.90158 17 3.37271 17 1.5zM10 8H4V6h6z" stroke-width="1"></path>
                </g>
            </svg>
        `;

        function setReaderFullscreen(nextState) {
            isReaderFullscreen = Boolean(nextState);
            document.body.classList.toggle('reader-is-fullscreen', isReaderFullscreen);
            modalOverlay.classList.toggle('is-fullscreen', isReaderFullscreen);
            modalShell.classList.toggle('is-fullscreen', isReaderFullscreen);

            if (!isReaderFullscreen) {
                closeReaderSidebarPanel();
                setReaderChromeHidden(false);
            }
        }

        function toggleReaderFullscreen(forceState = true) {
            const nextState = typeof forceState === 'boolean' ? forceState : !isReaderFullscreen;
            setReaderFullscreen(nextState);
        }

        function setReaderChromeHidden(nextState) {
            const shouldHide = Boolean(nextState) && isReaderFullscreen && modalOverlay.classList.contains('active');
            readerChromeHidden = shouldHide;
            modalShell?.classList.toggle('is-reader-chrome-hidden', shouldHide);
        }

        function resetReaderChromeState(forceScrollTop = false) {
            if (modalContent && forceScrollTop) {
                modalContent.scrollTop = 0;
            }
            readerLastScrollTop = modalContent?.scrollTop || 0;
            readerScrollIntent = 0;
            setReaderChromeHidden(false);
        }

        function updateReaderChromeVisibilityFromScroll() {
            if (!isReaderFullscreen || !modalOverlay.classList.contains('active')) {
                resetReaderChromeState(false);
                return;
            }
            if (settingsOverlay.classList.contains('active') || folderPickerOverlay.classList.contains('active') || commandOverlay.classList.contains('active')) {
                setReaderChromeHidden(false);
                readerLastScrollTop = modalContent?.scrollTop || 0;
                readerScrollIntent = 0;
                return;
            }
            const currentScrollTop = Math.max(0, modalContent?.scrollTop || 0);
            const scrollHeight = Math.max(0, modalContent?.scrollHeight || 0);
            const clientHeight = Math.max(0, modalContent?.clientHeight || 0);
            const maxScrollTop = Math.max(0, scrollHeight - clientHeight);
            const delta = currentScrollTop - readerLastScrollTop;
            readerLastScrollTop = currentScrollTop;

            if (maxScrollTop <= 220) {
                readerScrollIntent = 0;
                setReaderChromeHidden(false);
                return;
            }

            if (currentScrollTop <= 24) {
                readerScrollIntent = 0;
                setReaderChromeHidden(false);
                return;
            }

            if (Math.abs(delta) < 3) return;

            if (readerChromeHidden) {
                if (delta < 0) {
                    readerScrollIntent += Math.abs(delta);
                    if (readerScrollIntent >= 32) {
                        readerScrollIntent = 0;
                        setReaderChromeHidden(false);
                    }
                    return;
                }
                readerScrollIntent = 0;
                return;
            }

            if (delta > 0) {
                readerScrollIntent += delta;
                if (currentScrollTop > 120 && readerScrollIntent >= 48) {
                    readerScrollIntent = 0;
                    setReaderChromeHidden(true);
                }
                return;
            }

            readerScrollIntent = 0;
        }

        function openReaderSidebarPanel(tab = 'note') {
            if (!isReaderFullscreen) return;
            const nextTab = tab === 'ai' ? 'ai' : 'note';
            readerSidebarOpen = true;
            readerSidebarTab = nextTab;
            readerSidebar?.classList.add('is-open');
            readerSidebarContent?.setAttribute('data-tab', nextTab);
            setReaderChromeHidden(false);

            sidebarNoteTab?.classList.toggle('is-active', nextTab === 'note');
            sidebarAiTab?.classList.toggle('is-active', nextTab === 'ai');

            if (nextTab === 'note') {
                renderSidebarNoteContent();
            } else {
                renderSidebarAiContent();
                window.requestAnimationFrame(() => {
                    window.focusReaderAiComposer?.();
                });
            }
        }

        function closeReaderSidebarPanel() {
            readerSidebarOpen = false;
            readerSidebar?.classList.remove('is-open');
            readerSidebarContent?.removeAttribute('data-tab');
        }

        function setReaderSidebarTab(tab) {
            const nextTab = tab === 'ai' ? 'ai' : 'note';
            readerSidebarTab = nextTab;
            readerSidebarContent?.setAttribute('data-tab', nextTab);
            sidebarNoteTab?.classList.toggle('is-active', nextTab === 'note');
            sidebarAiTab?.classList.toggle('is-active', nextTab === 'ai');
            setReaderChromeHidden(false);

            if (nextTab === 'note') {
                renderSidebarNoteContent();
            } else {
                renderSidebarAiContent();
                window.requestAnimationFrame(() => {
                    window.focusReaderAiComposer?.();
                });
            }
        }

        function renderSidebarNoteContent() {
            if (!readerSidebarContent || !currentOpenItemId) return;
            const item = getItemById(currentOpenItemId);
            if (!item) return;

            const summary = formatParseStatusSummary(item);
            const detectedTitle = typeof getExtractedDisplayTitle === 'function' ? getExtractedDisplayTitle(item) : '';
            const extractedText = String(item?.extracted_text || '').trim();
            const isOrganizingAnalysis = analysisOrganizeInFlightItemId === item.id;
            const analysisAiTitle = isOrganizingAnalysis ? 'AI 正在整理内容分析' : 'AI 重新整理当前内容分析';
            const analysisMarkup = typeof renderExtractedSections === 'function'
                ? renderExtractedSections(item, { asPrimary: true, kicker: '内容分析' })
                : '';
            const fallbackMarkup = extractedText
                ? `
                    <section class="reader-extracted-panel is-primary">
                        <div class="reader-extracted-kicker">内容分析</div>
                        <div class="reader-extracted-section">
                            ${extractedText
                                .split(/\n{2,}/)
                                .map((paragraph) => paragraph.trim())
                                .filter(Boolean)
                                .map((paragraph) => `<p class="content-para">${escapeHtml(paragraph).replace(/\n/g, '<br>')}</p>`)
                                .join('')}
                        </div>
                    </section>
                `
                : '';
            const emptyCopy = item?.parse_status === 'processing'
                ? '正在整理这条内容的分析结果...'
                : '还没有内容分析，点底部“解析内容”生成。';
            const contentMarkup = analysisMarkup || fallbackMarkup || `<div class="content-empty-state">${escapeHtml(emptyCopy)}</div>`;
            const pageNotesMarkup = renderPageNotesSection(item);

            readerSidebarContent.innerHTML = `
                <div class="reader-analysis-shell">
                    <div class="reader-analysis-header">
                        <div class="reader-analysis-header-top">
                            <div class="reader-analysis-header-copy">
                                <div class="reader-analysis-label">内容分析</div>
                                <div class="reader-analysis-title">${escapeHtml(detectedTitle || getDisplayItemTitle(item) || '未命名内容')}</div>
                            </div>
                            <button
                                class="reader-analysis-ai-btn${isOrganizingAnalysis ? ' is-loading' : ''}"
                                type="button"
                                onclick="organizeItemAnalysis('${item.id}', event)"
                                title="${escapeAttribute(analysisAiTitle)}"
                                aria-label="${escapeAttribute(analysisAiTitle)}"
                                ${isOrganizingAnalysis || item?.parse_status === 'processing' ? 'disabled' : ''}
                            >
                                <span class="reader-analysis-ai-btn-icon" aria-hidden="true">
                                    ${isOrganizingAnalysis ? '<span class="reader-analysis-ai-spinner"></span>' : analysisAiSparkIcon}
                                </span>
                            </button>
                        </div>
                        <div class="reader-analysis-meta${item?.parse_status === 'processing' ? ' is-processing' : ''}">${escapeHtml(summary)}</div>
                    </div>
                    ${contentMarkup}
                    ${pageNotesMarkup}
                </div>
            `;
        }

        function renderSidebarAiContent() {
            if (!readerSidebarContent || !currentOpenItemId) return;
            const item = getItemById(currentOpenItemId);
            if (!item) return;
            if (typeof window.renderReaderAiSidebar === 'function') {
                readerSidebarContent.innerHTML = window.renderReaderAiSidebar(item);
                window.bindReaderAiSidebar?.(item);
                return;
            }
            readerSidebarContent.innerHTML = `
                <div class="reader-ai-sidebar-shell is-empty">
                    <div class="reader-ai-empty-state reader-ai-empty-state--loading">
                        <div class="reader-ai-empty-title">Ask AI 正在准备</div>
                        <div class="reader-ai-empty-copy">正在加载当前笔记的 AI 侧栏。</div>
                        <span class="ai-loading-spinner" aria-hidden="true"></span>
                    </div>
                </div>
            `;
        }

        function pageNotesLoadState(itemId) {
            return itemPageNotesLoadStateByItem.get(itemId) || 'idle';
        }

        function getItemPageNotes(itemId) {
            return itemPageNotesByItem.get(itemId) || [];
        }

        async function loadItemPageNotes(itemId, options = {}) {
            const { force = false } = options;
            if (!itemId) return [];
            if (!force && pageNotesLoadState(itemId) === 'loaded') {
                return getItemPageNotes(itemId);
            }
            itemPageNotesLoadStateByItem.set(itemId, 'loading');
            itemPageNotesErrorByItem.delete(itemId);
            if (currentOpenItemId === itemId && readerSidebarOpen && readerSidebarTab === 'note') {
                renderSidebarNoteContent();
            }

            try {
                const response = await fetch(`/api/items/${itemId}/page-notes`);
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '页面笔记加载失败');
                const notes = Array.isArray(data.notes) ? data.notes : [];
                itemPageNotesByItem.set(itemId, notes);
                itemPageNotesLoadStateByItem.set(itemId, 'loaded');
                itemPageNotesErrorByItem.delete(itemId);
                return notes;
            } catch (error) {
                itemPageNotesLoadStateByItem.set(itemId, 'error');
                itemPageNotesErrorByItem.set(itemId, error.message || '页面笔记加载失败');
                throw error;
            } finally {
                if (currentOpenItemId === itemId && readerSidebarOpen && readerSidebarTab === 'note') {
                    renderSidebarNoteContent();
                }
            }
        }

        function renderPageNotesSection(item) {
            const loadState = pageNotesLoadState(item.id);
            const loadError = itemPageNotesErrorByItem.get(item.id) || '';
            const notes = getItemPageNotes(item.id);

            if (loadState === 'idle') {
                loadItemPageNotes(item.id).catch(() => {});
            }

            let listMarkup = '';
            if (loadState === 'loading' && !notes.length) {
                listMarkup = '<div class="reader-page-notes-loading">正在加载页面笔记...</div>';
            } else if (loadState === 'error' && !notes.length) {
                listMarkup = `<div class="reader-page-notes-empty">${escapeHtml(loadError || '页面笔记加载失败')}</div>`;
            } else if (!notes.length) {
                listMarkup = '<div class="reader-page-notes-empty">还没有页面笔记。你可以新建空白笔记，或把 Ask AI 的回答加入这里。</div>';
            } else {
                listMarkup = `
                    <div class="reader-page-notes-list">
                        ${notes.map((note) => {
                            const isSaving = itemPageNoteMutationIds.has(note.id);
                            const noteMeta = note.updated_at ? `最近更新 ${formatDate(note.updated_at)}` : '可编辑';
                            return `
                                <article class="reader-page-note-card">
                                    <input
                                        id="readerPageNoteTitle-${note.id}"
                                        class="reader-page-note-title-input"
                                        type="text"
                                        value="${escapeAttribute(note.title || '')}"
                                        placeholder="笔记标题"
                                    />
                                    <textarea
                                        id="readerPageNoteContent-${note.id}"
                                        class="reader-page-note-textarea"
                                        placeholder="记录你的补充想法、整理结论或后续动作..."
                                    >${escapeHtml(note.content || '')}</textarea>
                                    <div class="reader-page-note-actions">
                                        <div class="reader-page-note-meta">${escapeHtml(noteMeta)}</div>
                                        <div class="reader-page-note-action-group">
                                            <button
                                                class="reader-page-note-save-btn"
                                                type="button"
                                                onclick="saveReaderPageNote('${item.id}', '${note.id}')"
                                                ${isSaving ? 'disabled' : ''}
                                            >${isSaving ? '保存中...' : '保存'}</button>
                                            <button
                                                class="reader-page-note-delete-btn"
                                                type="button"
                                                onclick="deleteReaderPageNote('${item.id}', '${note.id}')"
                                                ${isSaving ? 'disabled' : ''}
                                            >删除</button>
                                        </div>
                                    </div>
                                </article>
                            `;
                        }).join('')}
                    </div>
                `;
            }

            return `
                <section class="reader-page-notes">
                    <div class="reader-page-notes-head">
                        <div>
                            <div class="reader-page-notes-title">页面笔记</div>
                            <div class="reader-page-notes-subtitle">一个内容可以保存多份笔记，每份都能单独编辑。</div>
                        </div>
                        <button class="reader-page-note-add-btn" type="button" onclick="createReaderPageNote('${item.id}')">新建笔记</button>
                    </div>
                    ${listMarkup}
                </section>
            `;
        }

        async function createReaderPageNote(itemId, options = {}) {
            if (!itemId) return null;
            const {
                title = '',
                content = '',
                aiConversationId = null,
                aiMessageIndex = null,
                successMessage = '页面笔记已创建',
            } = options;
            try {
                const response = await fetch(`/api/items/${itemId}/page-notes`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title,
                        content,
                        ai_conversation_id: aiConversationId || undefined,
                        ai_message_index: Number.isFinite(Number(aiMessageIndex)) ? Number(aiMessageIndex) : undefined,
                    }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '页面笔记创建失败');

                const existingNotes = getItemPageNotes(itemId);
                itemPageNotesByItem.set(itemId, [data, ...existingNotes.filter((note) => note.id !== data.id)]);
                itemPageNotesLoadStateByItem.set(itemId, 'loaded');
                itemPageNotesErrorByItem.delete(itemId);
                if (currentOpenItemId === itemId && readerSidebarOpen && readerSidebarTab === 'note') {
                    renderSidebarNoteContent();
                }
                showToast(successMessage, 'success');
                return data;
            } catch (error) {
                showToast(`页面笔记创建失败：${error.message}`, 'error');
                throw error;
            }
        }

        async function saveReaderPageNote(itemId, noteId) {
            if (!itemId || !noteId || itemPageNoteMutationIds.has(noteId)) return;
            const titleInput = document.getElementById(`readerPageNoteTitle-${noteId}`);
            const contentInput = document.getElementById(`readerPageNoteContent-${noteId}`);
            if (!titleInput || !contentInput) return;

            itemPageNoteMutationIds.add(noteId);
            renderSidebarNoteContent();
            try {
                const response = await fetch(`/api/items/${itemId}/page-notes/${noteId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title: titleInput.value || '',
                        content: contentInput.value || '',
                    }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '页面笔记保存失败');

                const nextNotes = getItemPageNotes(itemId).map((note) => (note.id === noteId ? data : note));
                itemPageNotesByItem.set(itemId, nextNotes);
                itemPageNotesLoadStateByItem.set(itemId, 'loaded');
                showToast('页面笔记已保存', 'success');
            } catch (error) {
                showToast(`页面笔记保存失败：${error.message}`, 'error');
            } finally {
                itemPageNoteMutationIds.delete(noteId);
                renderSidebarNoteContent();
            }
        }

        async function deleteReaderPageNote(itemId, noteId) {
            if (!itemId || !noteId || itemPageNoteMutationIds.has(noteId)) return;
            itemPageNoteMutationIds.add(noteId);
            renderSidebarNoteContent();
            try {
                const response = await fetch(`/api/items/${itemId}/page-notes/${noteId}`, {
                    method: 'DELETE',
                });
                if (!response.ok && response.status !== 204) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || '页面笔记删除失败');
                }
                const nextNotes = getItemPageNotes(itemId).filter((note) => note.id !== noteId);
                itemPageNotesByItem.set(itemId, nextNotes);
                itemPageNotesLoadStateByItem.set(itemId, 'loaded');
                showToast('页面笔记已删除', 'success');
            } catch (error) {
                showToast(`页面笔记删除失败：${error.message}`, 'error');
            } finally {
                itemPageNoteMutationIds.delete(noteId);
                renderSidebarNoteContent();
            }
        }

        async function saveSidebarNote(itemId) {
            const textarea = document.getElementById('sidebarNoteTextarea');
            if (!textarea || noteSaveInFlight) return;

            noteSaveInFlight = true;
            const draftText = textarea.value || '';

            try {
                const response = await fetch(`/api/items/${itemId}/note`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ extracted_text: draftText }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '保存失败');

                mergeUpdatedItem(data);
                showToast('笔记已保存', 'success');
            } catch (error) {
                showToast(`保存失败：${error.message}`, 'error');
            } finally {
                noteSaveInFlight = false;
            }
        }

        function initSidebarResize() {
            if (!readerSidebarResizeHandle || !readerSidebar) return;

            readerSidebarResizeHandle.addEventListener('mousedown', (e) => {
                e.preventDefault();
                readerSidebarResizing = true;
                readerSidebarStartX = e.clientX;
                readerSidebarStartWidth = readerSidebar.offsetWidth;
                readerSidebarResizeHandle.classList.add('is-dragging');
                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';
            });

            document.addEventListener('mousemove', (e) => {
                if (!readerSidebarResizing) return;
                const deltaX = readerSidebarStartX - e.clientX;
                const newWidth = Math.max(READER_SIDEBAR_MIN_WIDTH, Math.min(READER_SIDEBAR_MAX_WIDTH, readerSidebarStartWidth + deltaX));
                readerSidebar.style.width = `${newWidth}px`;
            });

            document.addEventListener('mouseup', () => {
                if (!readerSidebarResizing) return;
                readerSidebarResizing = false;
                readerSidebarResizeHandle.classList.remove('is-dragging');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            });
        }

        function initReaderScrollMotion() {
            if (!modalContent) return;
            modalContent.addEventListener('scroll', () => {
                if (readerScrollTicking) return;
                readerScrollTicking = true;
                window.requestAnimationFrame(() => {
                    readerScrollTicking = false;
                    updateReaderChromeVisibilityFromScroll();
                });
            }, { passive: true });
        }

        async function fetchItems() {
            const requestId = ++libraryRequestId;
            if (!ensureAuthenticated({ showOverlay: false })) {
                resetAuthenticatedAppState();
                return;
            }
            const controller = new AbortController();
            if (currentItemsRequestController) {
                currentItemsRequestController.abort();
            }
            currentItemsRequestController = controller;
            try {
                const response = await fetch(`/api/items?${getActiveSearchParams(200).toString()}`, {
                    signal: controller.signal,
                });
                if (!response.ok) throw new Error('API Error');
                const totalCount = Number(response.headers.get('X-Total-Count') || '0');
                const visibleCount = Number(response.headers.get('X-Visible-Count') || '0');
                const returnedCount = Number(response.headers.get('X-Returned-Count') || '0');
                const nextItems = await response.json();
                if (requestId !== libraryRequestId) return;
                itemsData = nextItems;
                filteredEntries = itemsData;
                latestTotalCount = totalCount;
                latestVisibleCount = visibleCount;
                latestReturnedCount = returnedCount || itemsData.length;
                const hasKeyword = !!filterInput.value.trim();
                const hasPlatformFilter = platformFilter.value !== 'all';
                const hasFolderFilter = currentFolderScope !== 'all';
                setStatsSummary(
                    latestTotalCount || itemsData.length,
                    latestVisibleCount || itemsData.length,
                    latestReturnedCount || itemsData.length,
                    hasKeyword || hasPlatformFilter || hasFolderFilter
                );
                renderItems(filteredEntries);
                const trackedSyncIds = getTrackedRemoteSyncItemIds(itemsData);
                if (trackedSyncIds.length) {
                    scheduleRemoteSyncRefresh({ delay: 400, force: true, itemIds: trackedSyncIds });
                }
            } catch (error) {
                if (error?.name === 'AbortError') return;
                if (!authState.authenticated) return;
                setStatsMessage('加载失败');
                grid.className = 'grid';
                grid.innerHTML = '<div class="empty-state">无法连接到后端 API</div>';
            } finally {
                if (currentItemsRequestController === controller) {
                    currentItemsRequestController = null;
                }
            }
        }

        async function refreshRemoteSyncStatus(itemIds, requestId) {
            if (!Array.isArray(itemIds) || itemIds.length === 0) return;
            if (remoteSyncRefreshInFlight) return;

            try {
                remoteSyncRefreshInFlight = true;
                const response = await fetch('/api/connect/sync-status/refresh', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_ids: itemIds }),
                });
                if (!response.ok) return;

                const data = await response.json();
                if (requestId !== libraryRequestId || !data || !Array.isArray(data.items)) return;

                const statusMap = new Map(data.items.map((item) => [item.id, item]));
                const changedItemIds = [];
                const mergeRemoteSyncStatusIntoItem = (item, nextStatus) => {
                    const shouldPreserveObsidianPath = Boolean(item?.obsidian_path)
                        && !nextStatus?.obsidian_path
                        && nextStatus?.obsidian_binding_missing !== true;
                    const mergedObsidianPath = shouldPreserveObsidianPath
                        ? item.obsidian_path
                        : (nextStatus?.obsidian_path || null);
                    const mergedObsidianState = shouldPreserveObsidianPath
                        ? (item.obsidian_sync_state || nextStatus?.obsidian_sync_state || 'ready')
                        : (nextStatus?.obsidian_sync_state || (mergedObsidianPath ? 'ready' : 'idle'));

                    return {
                        ...item,
                        notion_page_id: nextStatus?.notion_page_id || null,
                        obsidian_path: mergedObsidianPath,
                        obsidian_sync_state: mergedObsidianState,
                    };
                };

                itemsData = itemsData.map((item) => {
                    const nextStatus = statusMap.get(item.id);
                    if (!nextStatus) return item;
                    const mergedItem = mergeRemoteSyncStatusIntoItem(item, nextStatus);
                    if (
                        item.notion_page_id === mergedItem.notion_page_id
                        && item.obsidian_path === mergedItem.obsidian_path
                        && (item.obsidian_sync_state || 'idle') === (mergedItem.obsidian_sync_state || 'idle')
                    ) {
                        return item;
                    }
                    changedItemIds.push(item.id);
                    return mergedItem;
                });

                commandSearchResults = commandSearchResults.map((item) => {
                    const nextStatus = statusMap.get(item.id);
                    if (!nextStatus) return item;
                    return mergeRemoteSyncStatusIntoItem(item, nextStatus);
                });

                filteredEntries = itemsData;

                if (changedItemIds.length) {
                    patchRenderedItemsById(changedItemIds);
                    const refreshedItem = currentOpenItemId
                        ? itemsData.find((item) => item.id === currentOpenItemId) || commandSearchResults.find((item) => item.id === currentOpenItemId)
                        : null;
                    if (refreshedItem && currentOpenItemId === refreshedItem.id) {
                        openModalByItem(refreshedItem, { preserveSidebarTab: true });
                    }
                }
            } catch (error) {
                console.warn('Failed to refresh remote sync status', error);
            } finally {
                remoteSyncRefreshInFlight = false;
            }
        }

        function getTrackedRemoteSyncItemIds(entries = itemsData) {
            return Array.from(
                new Set(
                    (entries || [])
                        .map((item) => String(item?.id || '').trim())
                        .filter(Boolean)
                )
            );
        }

        function hasParsedContent(item) {
            return Boolean(
                String(item?.extracted_text || '').trim()
                || item?.parsed_at
                || item?.parse_status === 'completed'
            );
        }

        function getObsidianSyncState(item) {
            const state = String(item?.obsidian_sync_state || '').trim();
            if (state === 'ready' || state === 'partial' || state === 'idle') {
                return state;
            }
            return item?.obsidian_path ? 'ready' : 'idle';
        }

        function getObsidianSyncTitle(item) {
            const state = getObsidianSyncState(item);
            if (state === 'ready') return 'Obsidian已完全同步';
            if (state === 'partial') return 'Obsidian有更新待同步';
            return 'Obsidian未同步';
        }

        function renderKnowledgeDotMarkup(item) {
            const notionBusy = isItemSyncInFlight(item?.id, 'notion');
            const obsidianBusy = isItemSyncInFlight(item?.id, 'obsidian');
            const obsidianState = getObsidianSyncState(item);
            const obsidianClass = obsidianState === 'ready'
                ? 'is-ready'
                : (obsidianState === 'partial' ? 'is-partial' : 'is-idle');
            return `
                <span class="knowledge-dot notion ${notionBusy ? 'is-processing' : (item.notion_page_id ? 'is-ready' : 'is-idle')}" title="${notionBusy ? 'Notion同步中' : `Notion${item.notion_page_id ? '已同步' : '未同步'}`}"></span>
                <span class="knowledge-dot obsidian ${obsidianBusy ? 'is-processing' : obsidianClass}" title="${obsidianBusy ? 'Obsidian同步中' : getObsidianSyncTitle(item)}"></span>
            `;
        }

        function getObsidianSyncButtonLabel(item) {
            const obsidianState = getObsidianSyncState(item);
            if (obsidianState === 'partial') return '更新 Obsidian 笔记';
            if (obsidianState === 'ready') return '再次检查 Obsidian 同步';
            return '同步至 Obsidian';
        }

        function clearItemDragPreview() {
            if (!activeItemDragPreview) return;
            activeItemDragPreview.remove();
            activeItemDragPreview = null;
        }

        function buildItemDragPreview(item) {
            clearItemDragPreview();

            const preview = document.createElement('div');
            preview.className = 'item-drag-preview';
            if (item?.parse_status === 'processing') {
                preview.classList.add('is-processing');
            }

            const thumb = document.createElement('div');
            thumb.className = 'item-drag-preview-thumb';
            const thumbnail = getItemThumbnail(item);
            if (thumbnail?.url) {
                const image = document.createElement('img');
                image.src = resolveMediaUrl(thumbnail.url);
                image.alt = '';
                thumb.appendChild(image);
            } else {
                thumb.textContent = String(platformDisplayLabel(item) || '条').trim().slice(0, 1) || '条';
            }

            const body = document.createElement('div');
            body.className = 'item-drag-preview-body';

            const title = document.createElement('div');
            title.className = 'item-drag-preview-title';
            title.textContent = getDisplayItemTitle(item) || '未命名内容';

            const meta = document.createElement('div');
            meta.className = 'item-drag-preview-meta';

            const platformPill = document.createElement('span');
            platformPill.className = 'item-drag-preview-pill';
            platformPill.textContent = platformDisplayLabel(item);
            meta.appendChild(platformPill);

            if (item?.parse_status === 'processing') {
                const chip = document.createElement('span');
                chip.className = 'item-drag-preview-chip is-processing';
                chip.innerHTML = '<span class="item-drag-preview-chip-pulse" aria-hidden="true"></span>解析中';
                meta.appendChild(chip);
            } else {
                const detail = document.createElement('span');
                detail.className = 'item-drag-preview-detail';
                if (Array.isArray(item?.folder_names) && item.folder_names.length) {
                    const extraCount = Math.max(0, Number(item.folder_count || item.folder_names.length) - 1);
                    detail.textContent = extraCount > 0
                        ? `${item.folder_names[0]} +${extraCount}`
                        : item.folder_names[0];
                } else {
                    detail.textContent = formatRelativeTime(item.created_at);
                }
                meta.appendChild(detail);
            }

            body.append(title, meta);
            preview.append(thumb, body);
            document.body.appendChild(preview);
            activeItemDragPreview = preview;
            return preview;
        }

        function isItemSyncInFlight(itemId, target) {
            return Boolean(itemId && syncActionState?.[target]?.has(itemId));
        }

        function setItemSyncInFlight(itemId, target, isLoading) {
            if (!itemId || !syncActionState?.[target]) return;
            if (isLoading) {
                syncActionState[target].add(itemId);
            } else {
                syncActionState[target].delete(itemId);
            }
            patchRenderedItemsById(itemId);
            const refreshedItem = getItemById(itemId);
            if (refreshedItem && currentOpenItemId === itemId) {
                openModalByItem(refreshedItem, { keepNotePanel: isNotePanelOpen, preserveSidebarTab: true });
            }
        }

        function renderItemActivityBadges(item, options = {}) {
            const { includeParseStatus = true } = options;
            const chips = [];
            if (includeParseStatus && item?.parse_status === 'processing') {
                chips.push('<span class="activity-chip is-processing"><span class="activity-chip-pulse" aria-hidden="true"></span>解析中</span>');
            }
            if (isItemSyncInFlight(item?.id, 'notion')) {
                chips.push('<span class="activity-chip is-processing is-syncing"><span class="activity-chip-pulse" aria-hidden="true"></span>Notion 同步中</span>');
            }
            if (isItemSyncInFlight(item?.id, 'obsidian')) {
                chips.push('<span class="activity-chip is-processing is-syncing"><span class="activity-chip-pulse" aria-hidden="true"></span>Obsidian 同步中</span>');
            }
            if (!chips.length) return '';
            return `<div class="activity-chips">${chips.join('')}</div>`;
        }

        function renderSyncBadges(item) {
            const notionBusy = isItemSyncInFlight(item?.id, 'notion');
            const obsidianBusy = isItemSyncInFlight(item?.id, 'obsidian');
            return `
                <div class="knowledge-dots${notionBusy || obsidianBusy ? ' is-busy' : ''}" aria-label="知识库状态">
                    <span class="knowledge-dot notion ${notionBusy ? 'is-processing' : (item.notion_page_id ? 'is-ready' : 'is-idle')}" title="${notionBusy ? 'Notion同步中' : `Notion${item.notion_page_id ? '已同步' : '未同步'}`}"></span>
                    <span class="knowledge-dot obsidian ${obsidianBusy ? 'is-processing' : (getObsidianSyncState(item) === 'ready' ? 'is-ready' : (getObsidianSyncState(item) === 'partial' ? 'is-partial' : 'is-idle'))}" title="${obsidianBusy ? 'Obsidian同步中' : getObsidianSyncTitle(item)}"></span>
                </div>
            `;
        }

        function renderListRowMarkup(item) {
            const textPreview = getDisplayItemPreview(item, 120);
            const length = item.canonical_text ? item.canonical_text.length : 0;
            const thumb = getItemThumbnail(item);
            const activeClass = currentOpenItemId === item.id ? ' is-active' : '';
            const processingClass = item.parse_status === 'processing' ? ' is-processing' : '';
            const displayTitle = getDisplayItemTitle(item);
            const fullTitle = String(item.title || displayTitle || '无标题').trim();
            const activityBadges = renderItemActivityBadges(item);
            const safeSourceUrl = escapeAttribute(item.source_url || '');
            const thumbHtml = thumb
                ? `<div class="list-thumb"><img src="${escapeAttribute(resolveMediaUrl(thumb.url))}" loading="lazy" decoding="async" fetchpriority="low" alt=""></div>`
                : `<div class="list-thumb"></div>`;
            return `
                <div class="list-row${activeClass}${processingClass}" data-item-id="${escapeAttribute(item.id || '')}" draggable="true" ondragstart="handleItemDragStart(event, '${item.id}')" ondragend="handleLibraryDragEnd(event)" onclick="handleItemPrimaryAction('${item.id}')">
                    <div class="list-main">
                        ${thumbHtml}
                        <div class="list-content">
                            <div class="list-title-row">
                                <div class="list-title" title="${escapeAttribute(fullTitle)}">${escapeHtml(displayTitle)}</div>
                            </div>
                            <div class="list-preview">${escapeHtml(textPreview)}</div>
                        </div>
                    </div>
                    <div class="list-side">
                        <div class="list-meta">
                            <span class="list-stat">${platformDisplayLabel(item)}</span>
                            <span class="list-stat">${formatDate(item.created_at)}</span>
                            <span class="list-stat">${length} 字</span>
                            ${renderFolderTags(item)}
                        </div>
                        <div class="list-actions">
                            ${activityBadges}
                            ${renderSyncBadges(item)}
                            ${renderFolderActionButton(item)}
                            <button onclick="deleteItem('${item.id}', event)" class="delete-btn" title="删除">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2M10 11v6M14 11v6"/></svg>
                            </button>
                            <a href="${safeSourceUrl}" target="_blank" rel="noopener noreferrer" class="source-link" onclick="event.stopPropagation()">原文 ↗</a>
                        </div>
                    </div>
                </div>
            `;
        }

        function renderCardMarkup(item) {
            const activeClass = currentOpenItemId === item.id ? ' is-active' : '';
            const processingClass = item.parse_status === 'processing' ? ' is-processing' : '';
            const displayTitle = getDisplayItemTitle(item);
            const title = escapeHtml(displayTitle);
            const fullTitle = escapeAttribute(String(item.title || displayTitle || '无标题').trim());
            const sourceLabel = escapeHtml(`来自 ${platformDisplayLabel(item)}`);
            const relativeTime = escapeHtml(formatRelativeTime(item.created_at));
            const tagsHtml = renderCardTags(item);
            const activityBadges = renderItemActivityBadges(item, { includeParseStatus: false });
            const safeSourceUrl = escapeAttribute(item.source_url || '');

            return `
                <div class="card${activeClass}${processingClass}" data-item-id="${escapeAttribute(item.id || '')}" draggable="true" ondragstart="handleItemDragStart(event, '${item.id}')" ondragend="handleLibraryDragEnd(event)" onclick="handleItemPrimaryAction('${item.id}')">
                    ${renderCardPreview(item)}
                    <div class="card-content">
                        <div class="card-meta-row">
                            <div class="card-meta">
                                <span>${sourceLabel}</span>
                                <span>•</span>
                                <span>${relativeTime}</span>
                            </div>
                            ${renderSyncBadges(item)}
                        </div>
                        ${activityBadges}
                        <h3 class="card-title" title="${fullTitle}">${title}</h3>
                        <div class="card-bottom-row">
                            <div class="tags">
                                ${tagsHtml}
                            </div>
                            <div class="card-footer-actions">
                                ${renderFolderActionButton(item)}
                                <button onclick="deleteItem('${item.id}', event)" class="delete-btn" title="删除">
                                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2M10 11v6M14 11v6"/></svg>
                                </button>
                                <a href="${safeSourceUrl}" target="_blank" rel="noopener noreferrer" class="source-link" onclick="event.stopPropagation()">
                                    原文 ↗
                                </a>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        function renderItemMarkup(item) {
            return currentView === 'list' ? renderListRowMarkup(item) : renderCardMarkup(item);
        }

        function buildRenderedItemNode(markup) {
            const template = document.createElement('template');
            template.innerHTML = markup.trim();
            return template.content.firstElementChild;
        }

        function findRenderedItemNode(itemId) {
            const normalizedId = String(itemId || '');
            if (!normalizedId || !grid) return null;
            return Array.from(grid.children).find((node) => node?.dataset?.itemId === normalizedId) || null;
        }

        function patchRenderedItemById(itemId) {
            const currentNode = findRenderedItemNode(itemId);
            if (!currentNode) return false;
            const nextItem = filteredEntries.find((entry) => entry.id === itemId);
            if (!nextItem) {
                currentNode.remove();
                return true;
            }
            const nextNode = buildRenderedItemNode(renderItemMarkup(nextItem));
            if (!nextNode) return false;
            currentNode.replaceWith(nextNode);
            return true;
        }

        function patchRenderedItemsById(itemIds) {
            const ids = Array.isArray(itemIds) ? itemIds : [itemIds];
            Array.from(new Set(ids.map((value) => String(value || '').trim()).filter(Boolean)))
                .forEach((itemId) => patchRenderedItemById(itemId));
        }

        function scheduleRemoteSyncRefresh(options = {}) {
            const { delay = 0, force = false, itemIds = null } = options;
            if (remoteSyncRefreshQueuedTimer) {
                window.clearTimeout(remoteSyncRefreshQueuedTimer);
            }
            remoteSyncRefreshQueuedTimer = window.setTimeout(() => {
                remoteSyncRefreshQueuedTimer = null;
                triggerRemoteSyncRefresh({ force, itemIds });
            }, delay);
        }

        function triggerRemoteSyncRefresh(options = {}) {
            const { force = false, itemIds = null } = options;
            if (!authState.authenticated) return;
            if (document.visibilityState === 'hidden') return;
            if (remoteSyncRefreshInFlight) return;

            const nextItemIds = Array.isArray(itemIds) ? itemIds.filter(Boolean) : getTrackedRemoteSyncItemIds();
            if (nextItemIds.length === 0) return;

            const now = Date.now();
            if (!force && now - lastRemoteSyncRefreshAt < REMOTE_SYNC_REFRESH_COOLDOWN_MS) return;

            lastRemoteSyncRefreshAt = now;
            refreshRemoteSyncStatus(nextItemIds, libraryRequestId);
        }

        function renderItems(entries) {
            if (entries.length === 0) {
                grid.className = currentView === 'gallery' ? 'grid' : 'list-view';
                grid.innerHTML = filterInput.value.trim() || platformFilter.value !== 'all' || currentFolderScope !== 'all'
                    ? `<div class="empty-state">${currentFolderScope === 'folder' && !filterInput.value.trim() && platformFilter.value === 'all' ? '这个文件夹里还没有内容。' : '没有找到匹配内容，请换个关键词或平台试试。'}</div>`
                    : '<div class="empty-state">暂无收录内容，请从网页入口粘贴链接开始收录。</div>';
                return;
            }

            if (currentView === 'list') {
                grid.className = 'list-view';
                grid.innerHTML = entries.map((item) => renderListRowMarkup(item)).join('');
                return;
            }

            grid.className = 'grid';
            grid.innerHTML = entries.map((item) => renderCardMarkup(item)).join('');
        }

        function setView(view) {
            currentView = view;
            galleryViewBtn.classList.toggle('active', view === 'gallery');
            listViewBtn.classList.toggle('active', view === 'list');
            renderItems(filteredEntries);
        }

        filterInput.addEventListener('input', scheduleLibrarySearch);
        platformFilter.addEventListener('change', () => {
            updateCommandPaletteState();
            fetchItems();
        });
        galleryViewBtn.addEventListener('click', () => setView('gallery'));
        listViewBtn.addEventListener('click', () => setView('list'));
        createFolderBtn.addEventListener('click', () => openCreateFolderPrompt());
        mobileFolderPickerBtn?.addEventListener('click', () => openMobileCaptureFolderPicker());
        folderSearchInput.addEventListener('input', (e) => {
            folderSearchQuery = e.target.value || '';
            renderFolderNavigation();
        });
        toggleSidebarBtn.addEventListener('click', () => {
            sidebarExpanded = !sidebarExpanded;
            updateSidebarState();
        });
        closeFolderPicker.addEventListener('click', () => closeFolderPickerDialog());
        folderPickerClearBtn.addEventListener('click', () => {
            folderPickerSelectedIds = new Set();
            renderFolderPickerOptions();
        });
        folderPickerApplyBtn.addEventListener('click', () => applyFolderSelection());
        folderCreateConfirmBtn.addEventListener('click', () => createFolderAndApply());
        folderCreateInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                createFolderAndApply();
            }
        });
        sidebarSettingsBtn.addEventListener('click', () => openSettingsPanel());
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Meta') {
                setFolderReorderArmed(true);
            }
        });
        document.addEventListener('keyup', (event) => {
            if (event.key === 'Meta') {
                setFolderReorderArmed(false);
            }
        });
        window.addEventListener('blur', () => {
            setFolderReorderArmed(false);
            clearFolderDropIndicator();
        });

        async function deleteItem(id, event) {
            event.stopPropagation();
            if (!confirm('确定要删除这条内容吗？删除后不可恢复。')) return;

            try {
                const response = await fetch(`/api/items/${id}`, { method: 'DELETE' });
                if (response.ok) {
                    showToast('已删除', 'deleted');
                    await Promise.all([fetchFolders(), fetchItems()]);
                } else {
                    const data = await response.json();
                    showToast('删除失败: ' + (data.detail || '未知错误'), 'error');
                }
            } catch (error) {
                showToast('网络错误：' + error.message, 'error');
            }
        }

        function getItemById(itemId) {
            return itemsData.find((entry) => entry.id === itemId) || commandSearchResults.find((entry) => entry.id === itemId) || null;
        }

        function mergeUpdatedItem(updatedItem) {
            itemsData = itemsData.map((entry) => entry.id === updatedItem.id ? updatedItem : entry);
            filteredEntries = filteredEntries.map((entry) => entry.id === updatedItem.id ? updatedItem : entry);
            commandSearchResults = commandSearchResults.map((entry) => entry.id === updatedItem.id ? updatedItem : entry);
        }

        function formatParseStatusSummary(item) {
            const status = String(item?.parse_status || 'idle');
            if (status === 'processing') return '解析中...';
            if (status === 'failed') return item?.parse_error ? `解析失败 · ${item.parse_error}` : '解析失败';
            if (status === 'completed') {
                const parsedAt = item?.parsed_at ? ` · ${formatDate(item.parsed_at)}` : '';
                return `已解析${parsedAt}`;
            }
            return '未解析';
        }

        function buildReaderMeta(item) {
            if (!item) return '当前笔记';
            const platform = normalizePlatform(item.platform || '', String(item.source_url || '').toLowerCase());
            const platformLabelMap = {
                github: 'GitHub',
                xiaohongshu: '小红书',
                douyin: '抖音',
                wechat: '微信公众号',
                web: '网页',
                twitter: 'X',
                youtube: 'YouTube',
                bilibili: 'Bilibili',
            };
            const folderNames = Array.isArray(item.folder_names) ? item.folder_names.filter(Boolean) : [];
            const parts = [
                folderNames[0] || '',
                platformLabelMap[platform] || (platform ? platform.charAt(0).toUpperCase() + platform.slice(1) : ''),
                item.created_at ? formatDate(item.created_at) : '',
            ].filter(Boolean);
            return parts.join(' · ') || '当前笔记';
        }

        function renderNotePanel(item) {
            if (!readerNotePanel) return;

            const summary = formatParseStatusSummary(item);
            const extractedText = String(item?.extracted_text || '');
            const detectedTitle = typeof getExtractedDisplayTitle === 'function' ? getExtractedDisplayTitle(item) : '';
            const placeholder = item?.parse_status === 'processing'
                ? '正在解析图片 / 视频中的原始文字内容...'
                : '解析后的原始文字会显示在这里，你也可以直接修改。';

            readerNotePanel.innerHTML = `
                <div class="reader-note-shell">
                    <div class="reader-note-header">
                        <div class="reader-note-title-group">
                            <div class="reader-note-kicker">${detectedTitle ? '检测标题' : '解析笔记'}</div>
                            <div class="reader-note-title">${escapeHtml(detectedTitle || '原始提取文本')}</div>
                        </div>
                        <div class="reader-note-meta${item?.parse_status === 'processing' ? ' is-processing' : ''}">${escapeHtml(summary)}</div>
                    </div>
                    <textarea id="readerNoteTextarea" class="reader-note-textarea" placeholder="${escapeAttribute(placeholder)}">${escapeHtml(extractedText)}</textarea>
                    <div class="reader-note-actions">
                        <button
                            onclick="saveItemNote('${item.id}')"
                            class="extract-btn modal-action-btn${noteSaveInFlight ? ' is-loading' : ''}"
                            ${noteSaveInFlight ? 'disabled' : ''}
                        >
                            ${noteSaveInFlight ? '保存中...' : '保存笔记'}
                        </button>
                    </div>
                </div>
            `;
            setNotePanelOpen(isNotePanelOpen);
        }

        async function parseItemContent(itemId, event = null) {
            event?.stopPropagation?.();
            if (manualParseInFlightItemId === itemId) return;

            const currentItem = getItemById(itemId);
            if (!currentItem) return;

            manualParseInFlightItemId = itemId;
            mergeUpdatedItem({
                ...currentItem,
                parse_status: 'processing',
                parse_error: null,
            });
            patchRenderedItemsById(itemId);
            if (currentOpenItemId === itemId) {
                openModalByItem(getItemById(itemId));
                if (readerSidebarOpen && readerSidebarTab === 'note') {
                    openReaderSidebarPanel('note');
                }
            }

            try {
                const response = await fetch(`/api/items/${itemId}/parse-content`, { method: 'POST' });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '解析失败');

                mergeUpdatedItem(data);
                patchRenderedItemsById(itemId);
                if (currentOpenItemId === itemId) {
                    openModalByItem(data, { preserveSidebarTab: true });
                    if (readerSidebarOpen && readerSidebarTab === 'note') {
                        openReaderSidebarPanel('note');
                    }
                }
                showToast('内容解析完成', 'success');
            } catch (error) {
                const failedItem = getItemById(itemId);
                if (failedItem) {
                    mergeUpdatedItem({
                        ...failedItem,
                        parse_status: 'failed',
                        parse_error: error.message,
                    });
                    patchRenderedItemsById(itemId);
                    if (currentOpenItemId === itemId) {
                        openModalByItem(getItemById(itemId), { preserveSidebarTab: true });
                        if (readerSidebarOpen && readerSidebarTab === 'note') {
                            openReaderSidebarPanel('note');
                        }
                    }
                }
                showToast(`解析失败：${error.message}`, 'error');
            } finally {
                manualParseInFlightItemId = null;
                const nextItem = getItemById(itemId);
                if (nextItem && currentOpenItemId === itemId) {
                    openModalByItem(nextItem, { preserveSidebarTab: true });
                    if (readerSidebarOpen && readerSidebarTab === 'note') {
                        openReaderSidebarPanel('note');
                    }
                }
            }
        }

        async function organizeItemAnalysis(itemId, event = null) {
            event?.stopPropagation?.();
            if (!itemId || analysisOrganizeInFlightItemId === itemId) return;

            const currentItem = getItemById(itemId);
            if (!currentItem) return;
            if (currentItem.parse_status === 'processing') {
                showToast('内容还在解析中，稍后再整理。', 'info');
                return;
            }

            analysisOrganizeInFlightItemId = itemId;
            if (currentOpenItemId === itemId) {
                openModalByItem(currentItem, { keepNotePanel: isNotePanelOpen, preserveSidebarTab: true });
            }

            try {
                const response = await fetch(`/api/ai/items/${itemId}/organize-analysis`, { method: 'POST' });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    const detail = String(data.detail || '整理失败');
                    if (/AI settings are incomplete/i.test(detail)) {
                        openSettingsPanel();
                    }
                    throw new Error(detail);
                }

                mergeUpdatedItem(data);
                patchRenderedItemsById(itemId);
                if (currentOpenItemId === itemId) {
                    openModalByItem(data, { keepNotePanel: isNotePanelOpen, preserveSidebarTab: true });
                }
                showToast('内容分析已整理', 'success');
            } catch (error) {
                showToast(`整理失败：${error.message}`, 'error');
            } finally {
                analysisOrganizeInFlightItemId = null;
                const nextItem = getItemById(itemId);
                if (nextItem && currentOpenItemId === itemId) {
                    openModalByItem(nextItem, { keepNotePanel: isNotePanelOpen, preserveSidebarTab: true });
                }
            }
        }

        async function saveItemNote(itemId) {
            const textarea = document.getElementById('readerNoteTextarea');
            if (!textarea || noteSaveInFlight) return;

            noteSaveInFlight = true;
            const draftText = textarea.value || '';
            const currentItem = getItemById(itemId);
            if (currentItem && currentOpenItemId === itemId) {
                renderNotePanel({ ...currentItem, extracted_text: draftText });
            }

            try {
                const response = await fetch(`/api/items/${itemId}/note`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ extracted_text: draftText }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '保存失败');

                mergeUpdatedItem(data);
                patchRenderedItemsById(itemId);
                if (currentOpenItemId === itemId) {
                    openModalByItem(data, { preserveSidebarTab: true });
                    if (readerSidebarOpen && readerSidebarTab === 'note') {
                        openReaderSidebarPanel('note');
                    }
                }
                showToast('解析笔记已保存', 'success');
            } catch (error) {
                showToast(`保存失败：${error.message}`, 'error');
            } finally {
                noteSaveInFlight = false;
                const nextItem = getItemById(itemId);
                if (nextItem && currentOpenItemId === itemId) {
                    openModalByItem(nextItem, { preserveSidebarTab: true });
                    if (readerSidebarOpen && readerSidebarTab === 'note') {
                        openReaderSidebarPanel('note');
                    }
                }
            }
        }

        function openModalById(itemId) {
            const item = itemsData.find((entry) => entry.id === itemId);
            if (!item) return;
            openModalByItem(item);
        }

        function openModalByItem(item, options = {}) {
            const keepNotePanel = Boolean(options.keepNotePanel);
            const preserveSidebarTab = Boolean(options.preserveSidebarTab);
            const previousOpenItemId = currentOpenItemId;
            currentOpenItemId = item.id;
            const isNewItem = previousOpenItemId !== currentOpenItemId;
            const preferredSidebarTab = preserveSidebarTab ? (readerSidebarTab || 'note') : 'note';
            if (isNewItem) {
                patchRenderedItemsById([previousOpenItemId, currentOpenItemId]);
            }
            if (!keepNotePanel) {
                isNotePanelOpen = false;
            }
            modalTitle.innerText = getDisplayItemTitle(item);
            if (readerMetaLine) {
                readerMetaLine.textContent = buildReaderMeta(item);
            }
            readerStatusDots.innerHTML = renderKnowledgeDotMarkup(item);
            if (toggleNoteBtn) {
                const parsedContentReady = hasParsedContent(item);
                toggleNoteBtn.classList.toggle('is-available', parsedContentReady);
                toggleNoteBtn.setAttribute('title', parsedContentReady ? '查看解析笔记（已解析）' : '查看解析笔记');
            }
            renderNotePanel(item);
            const platform = normalizePlatform(item.platform || '');
            const isCarouselPlatform = platform === 'xiaohongshu' || platform === 'douyin';
            const videos = (item.media || []).filter(m => m.type === 'video');

            if (isCarouselPlatform) {
                // ── XHS / 抖音：图片轮播在顶部 ──────────────────────────────
                const images = (item.media || []).filter(m => m.type === 'image').sort((a, b) => a.display_order - b.display_order);
                let html = '';
                if (videos.length > 0) {
                    const cover = (item.media || []).find(m => m.type === 'cover');
                    html += `<div class="modal-media"><video controls preload="metadata" poster="${escapeAttribute(resolveMediaUrl(cover ? cover.url : ''))}"><source src="${escapeAttribute(resolveMediaUrl(videos[0].url || ''))}" type="video/mp4"></video></div>`;
                }
                if (images.length > 0) {
                    html += `<div class="modal-media modal-media--carousel"><div class="media-gallery">${images.map((img) => `<img src="${escapeAttribute(resolveMediaUrl(img.url || ''))}" alt="">`).join('')}</div>${images.length > 1 ? '<div class="gallery-hint">← 左右滑动查看更多图片 →</div>' : ''}</div>`;
                }
                const plainArticleHtml = typeof renderPlainTextArticle === 'function'
                    ? renderPlainTextArticle(item)
                    : `<div style="white-space:pre-wrap">${escapeHtml(item.canonical_text || '暂无内容')}</div>`;
                html += plainArticleHtml;
                modalContent.innerHTML = html;

            } else {
                // ── 通用网页 / 微信：优先恢复原始图文流，再按稳妥策略回退 ──────────────
                modalContent.innerHTML = renderWebArticle(item, videos);
            }

            modalFooter.innerHTML = `
                <div class="modal-footer-actions">
                    <button onclick="parseItemContent('${item.id}')" class="extract-btn modal-action-btn${manualParseInFlightItemId === item.id || item.parse_status === 'processing' ? ' is-loading' : ''}" ${manualParseInFlightItemId === item.id || item.parse_status === 'processing' ? 'disabled' : ''}>${manualParseInFlightItemId === item.id || item.parse_status === 'processing' ? '解析中...' : '解析内容'}</button>
                    <button onclick="syncItem('${item.id}', 'notion')" class="extract-btn modal-action-btn${isItemSyncInFlight(item.id, 'notion') ? ' is-loading' : ''}" ${isItemSyncInFlight(item.id, 'notion') ? 'disabled' : ''}>${isItemSyncInFlight(item.id, 'notion') ? 'Notion 同步中...' : (item.notion_page_id ? '再次检查 Notion 同步' : '同步至 Notion')}</button>
                    <button onclick="syncItem('${item.id}', 'obsidian')" class="extract-btn modal-action-btn${isItemSyncInFlight(item.id, 'obsidian') ? ' is-loading' : ''}" ${isItemSyncInFlight(item.id, 'obsidian') ? 'disabled' : ''}>${isItemSyncInFlight(item.id, 'obsidian') ? 'Obsidian 同步中...' : getObsidianSyncButtonLabel(item)}</button>
                </div>
            `;

            toggleReaderFullscreen(true);
            modalOverlay.classList.add('active');
            document.body.style.overflow = 'hidden';
            resetReaderChromeState(isNewItem);
            openReaderSidebarPanel(preferredSidebarTab);
        }

        async function syncItem(id, target) {
            if (isItemSyncInFlight(id, target)) return;
            showToast(`正在后台同步至 ${target}...`, 'info');
            setItemSyncInFlight(id, target, true);
            try {
                const res = await fetch(`/api/connect/${target}/sync/${id}`, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    const currentItem = itemsData.find(item => item.id === id);
                    const previousObsidianState = currentItem ? getObsidianSyncState(currentItem) : 'idle';
                    const hadObsidianPath = Boolean(currentItem?.obsidian_path);
                    if (currentItem) {
                        if (target === 'notion' && data.notion_page_id) currentItem.notion_page_id = data.notion_page_id;
                        if (target === 'obsidian') {
                            if (data.obsidian_path) currentItem.obsidian_path = data.obsidian_path;
                            currentItem.obsidian_sync_state = data.obsidian_sync_state || 'ready';
                        }
                    }
                    const commandItem = commandSearchResults.find((item) => item.id === id);
                    if (commandItem) {
                        if (target === 'notion' && data.notion_page_id) commandItem.notion_page_id = data.notion_page_id;
                        if (target === 'obsidian') {
                            if (data.obsidian_path) commandItem.obsidian_path = data.obsidian_path;
                            commandItem.obsidian_sync_state = data.obsidian_sync_state || 'ready';
                        }
                    }
                    patchRenderedItemsById(id);
                    const refreshedItem = itemsData.find(item => item.id === id) || commandSearchResults.find(item => item.id === id);
                    if (currentOpenItemId === id && refreshedItem) {
                        openModalByItem(refreshedItem, { preserveSidebarTab: true });
                    }
                    if (target === 'notion' && data.target_object) {
                        const targetLabel = data.target_object === 'database' ? 'Database' : 'Page';
                        const targetName = data.target_title || data.target_id || 'Untitled';
                        showToast(`已同步到 Notion ${targetLabel}: ${targetName}`, 'success');
                    } else if (target === 'obsidian') {
                        if (data.updated === false) {
                            showToast('Obsidian 已是最新内容', 'success');
                        } else if (hadObsidianPath || previousObsidianState === 'partial') {
                            showToast('Obsidian 笔记已更新', 'success');
                        } else {
                            showToast('已同步到 Obsidian', 'success');
                        }
                    } else {
                        showToast(`同步成功 (ID: ${data[`${target}_page_id`] || data.obsidian_path || '已同步'})`, 'success');
                    }
                } else {
                    let message = data.detail || '未知错误';
                    if (typeof message === 'string' && message.includes('notion_database_id')) {
                        message = 'Notion 已授权，但还没有配置 Database ID/URL。请先在设置里选择目标数据库。';
                    }
                    showToast(`同步失败: ${message}`, 'error');
                }
            } catch (e) {
                showToast(`同步出错: ${e.message}`, 'error');
            } finally {
                setItemSyncInFlight(id, target, false);
            }
        }

        function handleItemDragStart(event, itemId) {
            if (!event.dataTransfer) return;
            const item = getItemById(itemId);
            if (!item) {
                event.preventDefault();
                return;
            }
            draggedLibraryItemId = itemId;
            document.body.classList.add('item-dragging');
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData(ITEM_DRAG_DATA_TYPE, itemId);
            event.dataTransfer.setData('text/plain', itemId);
            const dragPreview = buildItemDragPreview(item);
            event.dataTransfer.setDragImage(dragPreview, 26, 22);
        }

        function handleLibraryDragEnd() {
            draggedLibraryItemId = null;
            document.body.classList.remove('item-dragging');
            clearFolderDropIndicator();
            clearItemDragPreview();
        }

        function closeModalDialog() {
            const previousOpenItemId = currentOpenItemId;
            modalOverlay.classList.remove('active');
            document.body.style.overflow = '';
            currentOpenItemId = null;
            noteSaveInFlight = false;
            analysisOrganizeInFlightItemId = null;
            isNotePanelOpen = false;
            toggleReaderFullscreen(false);
            readerSidebarOpen = false;
            readerSidebarTab = 'note';
            readerLastScrollTop = 0;

            if (readerNotePanel) {
                readerNotePanel.innerHTML = '';
            }
            if (readerSidebarContent) {
                readerSidebarContent.innerHTML = '';
            }
            readerSidebar?.classList.remove('is-open');

            setNotePanelOpen(false);
            toggleNoteBtn?.classList.remove('is-available');
            toggleNoteBtn?.classList.remove('is-active');
            toggleNoteBtn?.setAttribute('title', '查看解析笔记');
            if (readerMetaLine) {
                readerMetaLine.textContent = '当前笔记';
            }
            readerStatusDots.innerHTML = '';
            modalFooter.innerHTML = '';

            patchRenderedItemsById(previousOpenItemId);
        }

        closeModal?.addEventListener('click', () => {
            closeModalDialog();
        });

        closeModal?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                closeModalDialog();
            }
        });

        modalOverlay.onclick = (e) => {
            if (e.target === modalOverlay) closeModalDialog();
        };
        settingsOverlay.onclick = (e) => {
            if (e.target === settingsOverlay) {
                if (typeof closeSettingsPanel === 'function') closeSettingsPanel();
                else closeSettingsModal.onclick();
            }
        };
        folderPickerOverlay.onclick = (e) => {
            if (e.target === folderPickerOverlay) closeFolderPickerDialog();
        };

        window.addEventListener('beforeunload', () => {
            if (remoteSyncRefreshTimer) window.clearInterval(remoteSyncRefreshTimer);
            if (remoteSyncRefreshQueuedTimer) window.clearTimeout(remoteSyncRefreshQueuedTimer);
            if (mobileClipboardPollTimer) window.clearInterval(mobileClipboardPollTimer);
        });

        document.addEventListener('click', (e) => {
            if (!folderContextMenu.contains(e.target)) {
                closeFolderContextMenu();
            }
        });

        if (toggleNoteBtn) {
            toggleNoteBtn.onclick = () => {
                if (isReaderFullscreen) {
                    openReaderSidebarPanel('note');
                } else {
                    setNotePanelOpen();
                }
            };

            toggleNoteBtn.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    if (isReaderFullscreen) {
                        openReaderSidebarPanel('note');
                    } else {
                        setNotePanelOpen();
                    }
                }
            });
        }

        // Sidebar events
        closeReaderSidebar?.addEventListener('click', closeModalDialog);
        sidebarNoteTab?.addEventListener('click', () => setReaderSidebarTab('note'));
        sidebarAiTab?.addEventListener('click', () => setReaderSidebarTab('ai'));

        // Initialize sidebar resize
        initSidebarResize();
        initReaderScrollMotion();

        function closeTopmostPopupOnEscape() {
            const askAiOverlay = document.getElementById('askAiOverlay');
            if (askAiOverlay?.classList.contains('active') && typeof closeAskAiDialog === 'function') {
                closeAskAiDialog();
                return true;
            }
            if (folderPickerOverlay.classList.contains('active')) {
                closeFolderPickerDialog();
                return true;
            }
            if (commandOverlay.classList.contains('active')) {
                closeCommandPalette();
                return true;
            }
            if (settingsOverlay.classList.contains('active')) {
                if (typeof closeSettingsPanel === 'function') closeSettingsPanel();
                else settingsOverlay.classList.remove('active');
                return true;
            }
            if (modalOverlay.classList.contains('active')) {
                closeModalDialog();
                return true;
            }
            return false;
        }

        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') return;
            if (!closeTopmostPopupOnEscape()) return;

            e.preventDefault();
            e.stopImmediatePropagation();
        }, true);

        // Expose functions to window for onclick handlers
        window.saveSidebarNote = saveSidebarNote;
        window.organizeItemAnalysis = organizeItemAnalysis;
        window.toggleReaderFullscreen = toggleReaderFullscreen;
        window.openReaderSidebarPanel = openReaderSidebarPanel;
        window.closeReaderSidebarPanel = closeReaderSidebarPanel;
        window.renderSidebarAiContent = renderSidebarAiContent;
        window.setReaderChromeHidden = setReaderChromeHidden;
        window.createReaderPageNote = createReaderPageNote;
        window.saveReaderPageNote = saveReaderPageNote;
        window.deleteReaderPageNote = deleteReaderPageNote;
        window.loadItemPageNotes = loadItemPageNotes;

        bootstrapAuth();
