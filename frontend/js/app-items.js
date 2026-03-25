        let activeItemDragPreview = null;
        let isReaderFullscreen = false;
        let readerSidebarOpen = false;
        let readerSidebarTab = 'note';
        const itemPageNotesByItem = new Map();
        const itemPageNotesLoadStateByItem = new Map();
        const itemPageNotesErrorByItem = new Map();
        const itemPageNoteMutationIds = new Set();
        let activePageNoteId = null;
        let pageNoteViewMode = 'preview'; // 'source' | 'preview'
        let pageNoteAutoSaveTimer = null;
        let contentViewMode = 'view'; // 'view' | 'edit'
        let contentAutoSaveTimer = null;
        let contentTitleAC = null; // AbortController for title edit listeners
        let contentBodyAC = null; // AbortController for body contenteditable listeners
        let contentWasEdited = false; // tracks if content was edited in this modal session
        let readerSidebarResizing = false;
        let readerSidebarStartX = 0;
        let readerSidebarStartWidth = 0;
        let readerChromeHidden = false;
        let readerChromeLastToggle = 0;
        let readerLastScrollTop = 0;
        const readerNavStack = []; // stack of item IDs for back-navigation from citations
        let readerNavOrigin = null; // 'askAi' | 'readerAi' | null — where the citation nav started
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
        const extraItemCache = new Map();

        function cacheItemById(item) {
            if (!item || !item.id) return;
            const key = String(item.id);
            extraItemCache.set(key, item);
        }

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
            if (readerChromeHidden === shouldHide) return;
            // Cooldown: prevent rapid toggling (at least 300ms between state changes)
            const now = performance.now();
            if (now - readerChromeLastToggle < 300) return;
            readerChromeLastToggle = now;
            readerChromeHidden = shouldHide;
            modalShell?.classList.toggle('is-reader-chrome-hidden', shouldHide);
            // After layout change, sync scroll baseline so the reflow-caused
            // scroll shift doesn't trigger another toggle (breaks the flicker loop)
            requestAnimationFrame(() => {
                readerLastScrollTop = modalContent?.scrollTop || 0;
                readerScrollIntent = 0;
            });
        }

        function resetReaderChromeState(forceScrollTop = false) {
            if (modalContent && forceScrollTop) {
                modalContent.scrollTop = 0;
            }
            readerLastScrollTop = modalContent?.scrollTop || 0;
            readerScrollIntent = 0;
            readerChromeLastToggle = 0; // bypass cooldown on explicit reset
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

            // Not enough content to scroll — always show bars
            if (maxScrollTop <= 220) {
                readerScrollIntent = 0;
                setReaderChromeHidden(false);
                return;
            }

            // Near the top — always show bars
            if (currentScrollTop <= 24) {
                readerScrollIntent = 0;
                setReaderChromeHidden(false);
                return;
            }

            // Ignore tiny jitter
            if (Math.abs(delta) < 2) return;

            if (delta > 0) {
                // Scrolling down — hide bars quickly
                if (readerScrollIntent < 0) readerScrollIntent = 0; // reset on direction change
                readerScrollIntent += delta;
                if (currentScrollTop > 60 && readerScrollIntent >= 20) {
                    readerScrollIntent = 0;
                    setReaderChromeHidden(true);
                }
            } else {
                // Scrolling up — reveal bars
                if (readerScrollIntent > 0) readerScrollIntent = 0; // reset on direction change
                readerScrollIntent -= delta; // accumulate positive for up scroll
                if (readerScrollIntent >= 24) {
                    readerScrollIntent = 0;
                    setReaderChromeHidden(false);
                }
            }
        }

        function openReaderSidebarPanel(tab = 'note') {
            if (!isReaderFullscreen) return;
            const validTabs = ['note', 'pageNotes', 'ai'];
            const nextTab = validTabs.includes(tab) ? tab : 'note';

            // If sidebar is already open on the same tab and user is editing a note in source mode,
            // skip re-render to avoid destroying the textarea and losing unsaved input.
            if (readerSidebarOpen && readerSidebarTab === nextTab && nextTab === 'pageNotes'
                && activePageNoteId && pageNoteViewMode === 'source') {
                return;
            }

            readerSidebarOpen = true;
            readerSidebarTab = nextTab;
            readerSidebar?.classList.add('is-open');
            readerSidebarContent?.setAttribute('data-tab', nextTab);
            setReaderChromeHidden(false);

            sidebarNoteTab?.classList.toggle('is-active', nextTab === 'note');
            sidebarPageNotesTab?.classList.toggle('is-active', nextTab === 'pageNotes');
            sidebarAiTab?.classList.toggle('is-active', nextTab === 'ai');

            if (nextTab === 'note') {
                renderSidebarNoteContent();
            } else if (nextTab === 'pageNotes') {
                renderSidebarPageNotesContent();
            } else {
                renderSidebarAiContent();
                window.requestAnimationFrame(() => {
                    window.focusReaderAiComposer?.();
                });
            }
        }

        function closeReaderSidebarPanel() {
            // Save any in-progress note editing before closing
            if (activePageNoteId && pageNoteViewMode === 'source' && currentOpenItemId) {
                clearTimeout(pageNoteAutoSaveTimer);
                captureAndCacheNoteFromDOM(currentOpenItemId, activePageNoteId);
                triggerPageNoteAutoSave(currentOpenItemId, activePageNoteId);
            }
            readerSidebarOpen = false;
            readerSidebar?.classList.remove('is-open');
            readerSidebarContent?.removeAttribute('data-tab');
            activePageNoteId = null;
            pageNoteViewMode = 'preview';
            clearTimeout(pageNoteAutoSaveTimer);
        }

        function setReaderSidebarTab(tab) {
            const validTabs = ['note', 'pageNotes', 'ai'];
            const nextTab = validTabs.includes(tab) ? tab : 'note';

            // If switching away from pageNotes while editing, save first
            if (readerSidebarTab === 'pageNotes' && nextTab !== 'pageNotes'
                && activePageNoteId && pageNoteViewMode === 'source') {
                clearTimeout(pageNoteAutoSaveTimer);
                captureAndCacheNoteFromDOM(currentOpenItemId, activePageNoteId);
                triggerPageNoteAutoSave(currentOpenItemId, activePageNoteId);
            }

            readerSidebarTab = nextTab;
            readerSidebarContent?.setAttribute('data-tab', nextTab);
            sidebarNoteTab?.classList.toggle('is-active', nextTab === 'note');
            sidebarPageNotesTab?.classList.toggle('is-active', nextTab === 'pageNotes');
            sidebarAiTab?.classList.toggle('is-active', nextTab === 'ai');
            setReaderChromeHidden(false);

            if (nextTab === 'note') {
                renderSidebarNoteContent();
            } else if (nextTab === 'pageNotes') {
                renderSidebarPageNotesContent();
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
                ? renderExtractedSections(item, {
                    asPrimary: true,
                    showKicker: false,
                    hideBodySectionTitle: true,
                })
                : '';
            const fallbackMarkup = extractedText
                ? `
                    <section class="reader-extracted-panel is-primary">
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

            readerSidebarContent.innerHTML = `
                <div class="analysis-shell">
                    <div class="analysis-toolbar">
                        <div class="analysis-toolbar-info">
                            <div class="analysis-toolbar-title">${escapeHtml(detectedTitle || getDisplayItemTitle(item) || '未命名内容')}</div>
                            <div class="analysis-toolbar-meta${item?.parse_status === 'processing' ? ' is-processing' : ''}">${escapeHtml(summary)}</div>
                        </div>
                        <button
                            class="analysis-ai-btn${isOrganizingAnalysis ? ' is-loading' : ''}"
                            type="button"
                            onclick="organizeItemAnalysis('${item.id}', event)"
                            title="${escapeAttribute(analysisAiTitle)}"
                            aria-label="${escapeAttribute(analysisAiTitle)}"
                            ${isOrganizingAnalysis || item?.parse_status === 'processing' ? 'disabled' : ''}
                        >
                            ${isOrganizingAnalysis ? '<span class="analysis-ai-spinner"></span>' : analysisAiSparkIcon}
                        </button>
                    </div>
                    <div class="analysis-content">
                        ${contentMarkup}
                    </div>
                </div>
            `;
        }

        function renderSidebarPageNotesContent() {
            if (!readerSidebarContent || !currentOpenItemId) return;
            const item = getItemById(currentOpenItemId);
            if (!item) return;

            const loadState = pageNotesLoadState(item.id);
            const notes = getItemPageNotes(item.id);

            if (loadState === 'idle') {
                loadItemPageNotes(item.id).catch(() => {});
            }

            // If a note is selected, render the editor view
            if (activePageNoteId) {
                const note = notes.find((n) => n.id === activePageNoteId);
                if (note) {
                    renderPageNoteEditor(item, note);
                    return;
                }
                // Note was deleted or not found, fall back to list
                activePageNoteId = null;
            }

            renderPageNotesList(item, notes, loadState);
        }

        function renderPageNotesList(item, notes, loadState) {
            const loadError = itemPageNotesErrorByItem.get(item.id) || '';
            let listMarkup = '';

            if (loadState === 'loading' && !notes.length) {
                listMarkup = '<div class="pn-empty-state">正在加载笔记...</div>';
            } else if (loadState === 'error' && !notes.length) {
                listMarkup = `<div class="pn-empty-state">${escapeHtml(loadError || '加载失败')}</div>`;
            } else if (!notes.length) {
                listMarkup = `
                    <div class="pn-empty-state">
                        <div class="pn-empty-icon">
                            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
                            </svg>
                        </div>
                        <div class="pn-empty-title">还没有笔记</div>
                        <div class="pn-empty-desc">记录你的想法、整理要点或写下待办事项</div>
                    </div>
                `;
            } else {
                listMarkup = `
                    <div class="pn-list">
                        ${notes.map((note) => {
                            const preview = (note.content || '').replace(/\n/g, ' ').slice(0, 80);
                            const timeStr = note.updated_at ? formatDate(note.updated_at) : '';
                            return `
                                <button class="pn-list-item" type="button" data-note-id="${escapeAttribute(note.id)}">
                                    <div class="pn-list-item-title">${escapeHtml(note.title || '无标题')}</div>
                                    ${preview ? `<div class="pn-list-item-preview">${escapeHtml(preview)}</div>` : ''}
                                    ${timeStr ? `<div class="pn-list-item-time">${escapeHtml(timeStr)}</div>` : ''}
                                </button>
                            `;
                        }).join('')}
                    </div>
                `;
            }

            readerSidebarContent.innerHTML = `
                <div class="pn-shell">
                    <div class="pn-toolbar">
                        <div class="pn-toolbar-title">笔记 <span class="pn-toolbar-count">${notes.length}</span></div>
                        <button class="pn-new-btn" type="button" title="新建笔记">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                                <path d="M12 5v14M5 12h14"/>
                            </svg>
                            新建
                        </button>
                    </div>
                    ${listMarkup}
                </div>
            `;

            // Bind events
            readerSidebarContent.querySelector('.pn-new-btn')?.addEventListener('click', async () => {
                const newNote = await createReaderPageNote(item.id);
                if (newNote) {
                    activePageNoteId = newNote.id;
                    pageNoteViewMode = 'source';
                    renderSidebarPageNotesContent();
                }
            });

            readerSidebarContent.querySelectorAll('.pn-list-item').forEach((el) => {
                el.addEventListener('click', () => {
                    activePageNoteId = el.getAttribute('data-note-id');
                    renderSidebarPageNotesContent();
                });
            });
        }

        function renderPageNoteEditor(item, note) {
            const isSaving = itemPageNoteMutationIds.has(note.id);
            const timeStr = note.updated_at ? formatDate(note.updated_at) : '';
            const isPreview = pageNoteViewMode === 'preview';
            const md = typeof window.renderMarkdownContent === 'function' ? window.renderMarkdownContent : null;

            // Source mode icon (code / angle brackets)
            const sourceIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`;
            // Preview mode icon (eye)
            const previewIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;

            const renderedBody = md && note.content ? md(note.content) : escapeHtml(note.content || '').replace(/\n/g, '<br>');

            readerSidebarContent.innerHTML = `
                <div class="pn-shell pn-editor-view">
                    <div class="pn-editor-toolbar">
                        <button class="pn-back-btn" type="button" title="返回列表">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M19 12H5M12 19l-7-7 7-7"/>
                            </svg>
                            笔记
                        </button>
                        <div class="pn-editor-toolbar-actions">
                            <span class="pn-save-indicator" id="pnSaveIndicator">${isSaving ? '保存中...' : (timeStr ? timeStr : '')}</span>
                            <button class="pn-mode-toggle" type="button" title="${isPreview ? '源码模式' : '渲染模式'}">
                                ${isPreview ? previewIcon : sourceIcon}
                            </button>
                            <button class="pn-delete-btn" type="button" title="删除笔记">
                                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                    ${isPreview ? `
                        <div class="pn-editor-body pn-preview-body">
                            <div class="pn-preview-title">${escapeHtml(note.title || '无标题')}</div>
                            <div class="pn-preview-content ai-markdown">${renderedBody || '<span class="pn-preview-empty">空笔记</span>'}</div>
                        </div>
                    ` : `
                        <div class="pn-editor-body">
                            <input
                                id="pnEditorTitle"
                                class="pn-editor-title"
                                type="text"
                                value="${escapeAttribute(note.title || '')}"
                                placeholder="笔记标题"
                                spellcheck="false"
                            />
                            <textarea
                                id="pnEditorContent"
                                class="pn-editor-content"
                                placeholder="开始写点什么..."
                                spellcheck="false"
                            >${escapeHtml(note.content || '')}</textarea>
                        </div>
                    `}
                    <div class="pn-delete-confirm" id="pnDeleteConfirm">
                        <span>确定删除这条笔记？</span>
                        <button class="pn-delete-confirm-yes" type="button">删除</button>
                        <button class="pn-delete-confirm-no" type="button">取消</button>
                    </div>
                </div>
            `;

            const deleteConfirm = document.getElementById('pnDeleteConfirm');

            // Mode toggle
            readerSidebarContent.querySelector('.pn-mode-toggle')?.addEventListener('click', () => {
                if (pageNoteViewMode === 'source') {
                    // Capture DOM values into cache synchronously BEFORE destroying the DOM
                    clearTimeout(pageNoteAutoSaveTimer);
                    captureAndCacheNoteFromDOM(item.id, note.id);
                    // Fire save in background (uses captured values already in cache)
                    triggerPageNoteAutoSave(item.id, note.id);
                    // Switch to preview immediately using locally cached data
                    pageNoteViewMode = 'preview';
                    const freshNote = getItemPageNotes(item.id).find((n) => n.id === note.id) || note;
                    renderPageNoteEditor(item, freshNote);
                } else {
                    pageNoteViewMode = 'source';
                    const freshNote = getItemPageNotes(item.id).find((n) => n.id === note.id) || note;
                    renderPageNoteEditor(item, freshNote);
                }
            });

            // Source mode bindings
            if (!isPreview) {
                const titleInput = document.getElementById('pnEditorTitle');
                const contentInput = document.getElementById('pnEditorContent');
                // Auto-resize textarea
                function autoResize() {
                    contentInput.style.height = 'auto';
                    contentInput.style.height = contentInput.scrollHeight + 'px';
                }
                autoResize();

                // Auto-save with debounce
                function scheduleAutoSave() {
                    clearTimeout(pageNoteAutoSaveTimer);
                    const indicator = document.getElementById('pnSaveIndicator');
                    if (indicator) indicator.textContent = '未保存';
                    pageNoteAutoSaveTimer = setTimeout(() => {
                        triggerPageNoteAutoSave(item.id, note.id);
                    }, 1200);
                }

                titleInput?.addEventListener('input', scheduleAutoSave);
                contentInput?.addEventListener('input', () => {
                    autoResize();
                    scheduleAutoSave();
                });

                // Save on blur (but not when clicking mode toggle)
                titleInput?.addEventListener('blur', () => {
                    clearTimeout(pageNoteAutoSaveTimer);
                    triggerPageNoteAutoSave(item.id, note.id);
                });
                contentInput?.addEventListener('blur', () => {
                    clearTimeout(pageNoteAutoSaveTimer);
                    triggerPageNoteAutoSave(item.id, note.id);
                });
            }

            // Back button
            readerSidebarContent.querySelector('.pn-back-btn')?.addEventListener('click', () => {
                clearTimeout(pageNoteAutoSaveTimer);
                if (pageNoteViewMode === 'source') {
                    // Capture before DOM is destroyed
                    captureAndCacheNoteFromDOM(item.id, note.id);
                    triggerPageNoteAutoSave(item.id, note.id);
                }
                activePageNoteId = null;
                pageNoteViewMode = 'preview';
                renderSidebarPageNotesContent();
            });

            // Delete with confirmation
            readerSidebarContent.querySelector('.pn-delete-btn')?.addEventListener('click', () => {
                deleteConfirm?.classList.add('is-visible');
            });
            deleteConfirm?.querySelector('.pn-delete-confirm-no')?.addEventListener('click', () => {
                deleteConfirm?.classList.remove('is-visible');
            });
            deleteConfirm?.querySelector('.pn-delete-confirm-yes')?.addEventListener('click', async () => {
                activePageNoteId = null;
                pageNoteViewMode = 'preview';
                await deleteReaderPageNote(item.id, note.id);
            });
        }

        // Capture current editor values from DOM and update local cache immediately.
        // Returns { title, content } or null if DOM not available.
        function captureAndCacheNoteFromDOM(itemId, noteId) {
            const titleInput = document.getElementById('pnEditorTitle');
            const contentInput = document.getElementById('pnEditorContent');
            if (!titleInput || !contentInput) return null;

            const title = titleInput.value || '';
            const content = contentInput.value || '';

            // Update local cache immediately so re-renders use fresh data
            const notes = getItemPageNotes(itemId);
            const updated = notes.map((n) => n.id === noteId ? { ...n, title, content } : n);
            itemPageNotesByItem.set(itemId, updated);

            return { title, content };
        }

        async function triggerPageNoteAutoSave(itemId, noteId) {
            if (!itemId || !noteId || itemPageNoteMutationIds.has(noteId)) return;

            // Capture values from DOM now — they may not exist after mode switch
            const captured = captureAndCacheNoteFromDOM(itemId, noteId);
            if (!captured) return;

            const indicator = document.getElementById('pnSaveIndicator');
            if (indicator) indicator.textContent = '保存中...';
            itemPageNoteMutationIds.add(noteId);

            try {
                const response = await fetch(`/api/items/${itemId}/page-notes/${noteId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title: captured.title,
                        content: captured.content,
                    }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '保存失败');

                // Merge server response (has updated_at etc.) but keep any newer local edits
                const latestNotes = getItemPageNotes(itemId);
                const nextNotes = latestNotes.map((n) => {
                    if (n.id !== noteId) return n;
                    // If user kept editing after we captured, preserve their local values
                    const titleInput = document.getElementById('pnEditorTitle');
                    const contentInput = document.getElementById('pnEditorContent');
                    if (titleInput && contentInput) {
                        return { ...data, title: titleInput.value || '', content: contentInput.value || '' };
                    }
                    return data;
                });
                itemPageNotesByItem.set(itemId, nextNotes);
                itemPageNotesLoadStateByItem.set(itemId, 'loaded');
                const ind = document.getElementById('pnSaveIndicator');
                if (ind) ind.textContent = '已保存';
            } catch (error) {
                const ind = document.getElementById('pnSaveIndicator');
                if (ind) ind.textContent = '保存失败';
            } finally {
                itemPageNoteMutationIds.delete(noteId);
            }
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
            if (currentOpenItemId === itemId && readerSidebarOpen && readerSidebarTab === 'pageNotes') {
                renderSidebarPageNotesContent();
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
                if (currentOpenItemId === itemId && readerSidebarOpen && readerSidebarTab === 'pageNotes') {
                    // Don't re-render while user is actively editing in source mode — it destroys unsaved input
                    if (!(activePageNoteId && pageNoteViewMode === 'source')) {
                        renderSidebarPageNotesContent();
                    }
                }
            }
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
                showToast(successMessage, 'success');
                return data;
            } catch (error) {
                showToast(`页面笔记创建失败：${error.message}`, 'error');
                throw error;
            }
        }

        async function deleteReaderPageNote(itemId, noteId) {
            if (!itemId || !noteId || itemPageNoteMutationIds.has(noteId)) return;
            itemPageNoteMutationIds.add(noteId);
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
                showToast('笔记已删除', 'success');
            } catch (error) {
                showToast(`删除失败：${error.message}`, 'error');
            } finally {
                itemPageNoteMutationIds.delete(noteId);
                renderSidebarPageNotesContent();
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
                renderItems(filteredEntries, { animate: true });
                startBackgroundRefresh();
                const trackedSyncIds = getTrackedRemoteSyncItemIds(itemsData);
                if (trackedSyncIds.length) {
                    scheduleRemoteSyncRefresh({ delay: 400, force: true, itemIds: trackedSyncIds });
                }
            } catch (error) {
                if (error?.name === 'AbortError') return;
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
                    if (refreshedItem && currentOpenItemId === refreshedItem.id && !contentWasEdited && contentViewMode !== 'edit') {
                        refreshOpenModalChrome(refreshedItem, { preserveSidebarTab: true });
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
                refreshOpenModalChrome(refreshedItem, { preserveSidebarTab: true });
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
            if (document.visibilityState === 'hidden') return;
            if (remoteSyncRefreshInFlight) return;

            const nextItemIds = Array.isArray(itemIds) ? itemIds.filter(Boolean) : getTrackedRemoteSyncItemIds();
            if (nextItemIds.length === 0) return;

            const now = Date.now();
            if (!force && now - lastRemoteSyncRefreshAt < REMOTE_SYNC_REFRESH_COOLDOWN_MS) return;

            lastRemoteSyncRefreshAt = now;
            refreshRemoteSyncStatus(nextItemIds, libraryRequestId);
        }

        function renderItems(entries, options = {}) {
            const { animate = false } = options;
            if (entries.length === 0) {
                grid.className = currentView === 'gallery' ? 'grid' : 'list-view';
                grid.innerHTML = filterInput.value.trim() || platformFilter.value !== 'all' || currentFolderScope !== 'all'
                    ? `<div class="empty-state">${currentFolderScope === 'folder' && !filterInput.value.trim() && platformFilter.value === 'all' ? '这个文件夹里还没有内容。' : '没有找到匹配内容，请换个关键词或平台试试。'}</div>`
                    : '<div class="empty-state">⌘K 开启你的收录之旅。</div>';
                return;
            }

            if (currentView === 'list') {
                grid.className = 'list-view';
                grid.innerHTML = entries.map((item) => renderListRowMarkup(item)).join('');
            } else {
                grid.className = 'grid';
                grid.innerHTML = entries.map((item) => renderCardMarkup(item)).join('');
            }

            if (animate) {
                const children = grid.querySelectorAll('.card, .list-row');
                const staggerLimit = Math.min(children.length, 20);
                for (let i = 0; i < staggerLimit; i += 1) {
                    children[i].style.animationDelay = `${i * 30}ms`;
                }
                grid.classList.add('is-animating');
                const cleanup = () => {
                    grid.classList.remove('is-animating');
                    for (let i = 0; i < staggerLimit; i += 1) {
                        children[i].style.animationDelay = '';
                    }
                };
                window.setTimeout(cleanup, staggerLimit * 30 + 350);
            }
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
            const key = String(itemId);
            return itemsData.find((entry) => String(entry.id) === key)
                || commandSearchResults.find((entry) => String(entry.id) === key)
                || extraItemCache.get(key)
                || null;
        }

        function mergeUpdatedItem(updatedItem) {
            itemsData = itemsData.map((entry) => entry.id === updatedItem.id ? updatedItem : entry);
            filteredEntries = filteredEntries.map((entry) => entry.id === updatedItem.id ? updatedItem : entry);
            commandSearchResults = commandSearchResults.map((entry) => entry.id === updatedItem.id ? updatedItem : entry);
        }

        /* ── Background refresh: poll processing items & detect new external captures ── */
        let _bgIntervalId = null;
        let _bgRefreshInFlight = false;
        const BG_REFRESH_FAST_MS = 2500;
        const BG_REFRESH_SLOW_MS = 8000;
        let _bgCurrentInterval = 0;

        function _getProcessingItemIds() {
            return itemsData
                .filter((item) => item.parse_status === 'processing')
                .map((item) => item.id);
        }

        // Items created within the last 60s that have no media yet — likely still downloading
        function _getIncompleteNewItemIds() {
            const cutoff = Date.now() - 60000;
            return itemsData
                .filter((item) => {
                    if (item.parse_status === 'processing') return false; // already tracked
                    const createdAt = item.created_at ? new Date(item.created_at).getTime() : 0;
                    if (createdAt < cutoff) return false;
                    const hasMedia = Array.isArray(item.media) && item.media.length > 0;
                    const hasContent = !!(item.canonical_text || item.extracted_text || item.canonical_html);
                    return !hasMedia || !hasContent;
                })
                .map((item) => item.id);
        }

        function _getPollableItemIds() {
            return [...new Set([..._getProcessingItemIds(), ..._getIncompleteNewItemIds()])];
        }

        function startBackgroundRefresh() {
            const wantFast = _getPollableItemIds().length > 0;
            const interval = wantFast ? BG_REFRESH_FAST_MS : BG_REFRESH_SLOW_MS;
            if (_bgIntervalId && _bgCurrentInterval === interval) return;
            if (_bgIntervalId) window.clearInterval(_bgIntervalId);
            _bgCurrentInterval = interval;
            _bgIntervalId = window.setInterval(_bgRefreshTick, interval);
            console.log('[bg-refresh] started, interval=' + interval + 'ms');
        }

        function stopBackgroundRefresh() {
            if (_bgIntervalId) {
                window.clearInterval(_bgIntervalId);
                _bgIntervalId = null;
                _bgCurrentInterval = 0;
            }
        }

        async function _bgRefreshTick() {
            if (_bgRefreshInFlight || document.visibilityState === 'hidden') return;
            _bgRefreshInFlight = true;
            try {
                // 1) Poll items that need updates (processing + incomplete new items)
                const pollIds = _getPollableItemIds();
                if (pollIds.length) {
                    console.log('[bg-refresh] polling ' + pollIds.length + ' items');
                }
                for (const itemId of pollIds) {
                    try {
                        const res = await fetch('/api/items/' + itemId);
                        if (!res.ok) continue;
                        const updated = await res.json();
                        const prev = getItemById(itemId);
                        const wasProcessing = prev?.parse_status === 'processing';
                        // Skip overwriting if user is actively editing this item's content
                        if (currentOpenItemId === itemId && (contentViewMode === 'edit' || contentWasEdited)) {
                            // Preserve local content edits, only merge non-content fields
                            const local = getItemById(itemId);
                            if (local) {
                                updated.title = local.title;
                                updated.canonical_text = local.canonical_text;
                                updated.canonical_text_length = local.canonical_text_length;
                            }
                        }
                        mergeUpdatedItem(updated);
                        patchRenderedItemsById(itemId);
                        if (currentOpenItemId === itemId && !contentWasEdited && contentViewMode !== 'edit') {
                            refreshOpenModalChrome(updated, { preserveSidebarTab: true });
                        }
                        if (wasProcessing && updated.parse_status === 'completed') {
                            console.log('[bg-refresh] item ' + itemId + ' parse completed, triggering AI organize');
                            organizeItemAnalysis(itemId);
                        }
                        if (wasProcessing && updated.parse_status === 'failed') {
                            console.log('[bg-refresh] item ' + itemId + ' parse failed');
                        }
                    } catch (err) {
                        console.warn('[bg-refresh] poll item error', itemId, err);
                    }
                }

                // 2) Check total count for new items from external sources (phone shortcuts, etc.)
                try {
                    const params = new URLSearchParams();
                    params.set('limit', '1');
                    const countRes = await fetch('/api/items?' + params.toString());
                    if (countRes.ok) {
                        const serverTotal = Number(countRes.headers.get('X-Total-Count') || '0');
                        if (serverTotal > 0 && serverTotal > latestTotalCount) {
                            console.log('[bg-refresh] new items detected: server=' + serverTotal + ' local=' + latestTotalCount);
                            latestTotalCount = serverTotal;
                            await fetchItems();
                        }
                    }
                } catch (err) {
                    console.warn('[bg-refresh] count check error', err);
                }

                // Adjust interval speed based on current state
                const wantFast = _getPollableItemIds().length > 0;
                const desiredInterval = wantFast ? BG_REFRESH_FAST_MS : BG_REFRESH_SLOW_MS;
                if (desiredInterval !== _bgCurrentInterval) {
                    console.log('[bg-refresh] switching interval to ' + desiredInterval + 'ms');
                    stopBackgroundRefresh();
                    _bgCurrentInterval = desiredInterval;
                    _bgIntervalId = window.setInterval(_bgRefreshTick, desiredInterval);
                }
            } catch (err) {
                console.error('[bg-refresh] unexpected error', err);
            } finally {
                _bgRefreshInFlight = false;
            }
        }

        // Pause polling when tab is hidden, resume when visible
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                startBackgroundRefresh();
                _bgRefreshTick();
            }
        });

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

        function renderModalFooter(item) {
            if (!modalFooter || !item) return;

            const parseIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m17.729 23.2502 4.671 -8.763c0.0513 -0.0959 0.0832 -0.2009 0.0939 -0.3091 0.0106 -0.1082 -0.0001 -0.2174 -0.0317 -0.3214 -0.0316 -0.1041 -0.0834 -0.2008 -0.1524 -0.2848 -0.069 -0.084 -0.1539 -0.1536 -0.2498 -0.2047l-1.46 -0.779c-0.1938 -0.103 -0.4206 -0.125 -0.6305 -0.061 -0.21 0.0639 -0.386 0.2084 -0.4895 0.402l-5.5 10.321"/><path d="m20.8449 17.4081 -2.9209 -1.558"/><path d="M14.25 12v3"/><path d="M15.75 13.5h-3"/><path d="M21.75 6v3"/><path d="M23.25 7.5h-3"/><path d="M0.75 5.25h4.5"/><path d="M18.75 5.25h-4.5"/><path d="M9.75 23.25h-7.5c-0.39782 0 -0.77936 -0.158 -1.06066 -0.4393C0.908035 22.5294 0.75 22.1478 0.75 21.75V2.25c0 -0.39782 0.158035 -0.77936 0.43934 -1.06066C1.47064 0.908035 1.85218 0.75 2.25 0.75h15c0.3978 0 0.7794 0.158035 1.0607 0.43934 0.2813 0.2813 0.4393 0.66284 0.4393 1.06066v3"/><path d="M5.25 23.25v-9"/><path d="M14.25 9.75v-9"/><path d="M5.25 9.75v-9"/><path d="M0.75 18.75h4.5"/><path d="M0.75 14.25h9"/><path d="M0.75 9.75h18"/></svg>`;
            const notionIcon = `<svg width="16" height="16" viewBox="0 0 100 100" fill="none"><path d="M6.017 4.313l55.333 -4.087c6.797 -0.583 8.543 -0.19 12.817 2.917l17.663 12.443c2.913 2.14 3.883 2.723 3.883 5.053v68.243c0 4.277 -1.553 6.807 -6.99 7.193L24.467 99.967c-4.08 0.193 -6.023 -0.39 -8.16 -3.113L3.3 79.94c-2.333 -3.113 -3.3 -5.443 -3.3 -8.167V11.113c0 -3.497 1.553 -6.413 6.017 -6.8z" fill="#fff"/><path fill-rule="evenodd" clip-rule="evenodd" d="M61.35 0.227l-55.333 4.087C1.553 4.7 0 7.617 0 11.113v60.66c0 2.723 0.967 5.053 3.3 8.167l13.007 16.913c2.137 2.723 4.08 3.307 8.16 3.113l64.257 -3.89c5.433 -0.387 6.99 -2.917 6.99 -7.193V20.64c0 -2.21 -0.873 -2.847 -3.443 -4.733L74.167 3.143c-4.273 -3.107 -6.02 -3.5 -12.817 -2.917zM25.92 19.523c-5.247 0.353 -6.437 0.433 -9.417 -1.99L8.927 11.507c-0.77 -0.78 -0.383 -1.753 1.557 -1.947l53.193 -3.887c4.467 -0.39 6.793 1.167 8.54 2.527l9.123 6.61c0.39 0.197 1.36 1.36 0.193 1.36l-54.933 3.307 -0.68 0.047zM19.803 88.3V30.367c0 -2.53 0.777 -3.697 3.103 -3.893L86 22.78c2.14 -0.193 3.107 1.167 3.107 3.693v57.547c0 2.53 -0.39 4.67 -3.883 4.863l-60.377 3.5c-3.493 0.193 -5.043 -0.97 -5.043 -4.083zm59.6 -54.827c0.387 1.75 0 3.5 -1.75 3.7l-2.91 0.577v42.773c-2.527 1.36 -4.853 2.137 -6.797 2.137 -3.107 0 -3.883 -0.973 -6.21 -3.887l-19.03 -29.94v28.967l6.02 1.363s0 3.5 -4.857 3.5l-13.39 0.777c-0.39 -0.78 0 -2.723 1.357 -3.11l3.497 -0.97v-38.3L30.48 40.667c-0.39 -1.75 0.58 -4.277 3.3 -4.473l14.367 -0.967 19.8 30.327v-26.83l-5.047 -0.58c-0.39 -2.143 1.163 -3.7 3.103 -3.89l13.4 -0.78z" fill="currentColor"/></svg>`;
            const obsidianIcon = `<svg width="16" height="16" viewBox="0 0 256 256" fill="none"><path d="M94.82 149.44c6.53-1.94 17.13-4.9 29.26-5.71a102.97 102.97 0 0 1-7.64-48.84c1.63-16.51 7.54-30.38 13.25-42.1l3.47-7.14 4.48-9.18c2.35-5 4.08-9.38 4.9-13.56.81-4.07.81-7.64-.2-11.11-1.03-3.47-3.07-7.14-7.15-11.21a17.02 17.02 0 0 0-15.8 3.77l-52.81 47.5a17.12 17.12 0 0 0-5.5 10.2l-4.5 30.18a149.26 149.26 0 0 1 38.24 57.2ZM54.45 106l-1.02 3.06-27.94 62.2a17.33 17.33 0 0 0 3.27 18.96l43.94 45.16a88.7 88.7 0 0 0 8.97-88.5A139.47 139.47 0 0 0 54.45 106Z" fill="currentColor"/><path d="m82.9 240.79 2.34.2c8.26.2 22.33 1.02 33.64 3.06 9.28 1.73 27.73 6.83 42.82 11.21 11.52 3.47 23.45-5.8 25.08-17.73 1.23-8.67 3.57-18.46 7.75-27.53a94.81 94.81 0 0 0-25.9-40.99 56.48 56.48 0 0 0-29.56-13.35 96.55 96.55 0 0 0-40.99 4.79 98.89 98.89 0 0 1-15.29 80.34h.1Z" fill="currentColor"/><path d="M201.87 197.76a574.87 574.87 0 0 0 19.78-31.6 8.67 8.67 0 0 0-.61-9.48 185.58 185.58 0 0 1-21.82-35.9c-5.91-14.16-6.73-36.08-6.83-46.69 0-4.07-1.22-8.05-3.77-11.21l-34.16-43.33c0 1.94-.4 3.87-.81 5.81a76.42 76.42 0 0 1-5.71 15.9l-4.7 9.8-3.36 6.72a111.95 111.95 0 0 0-12.03 38.23 93.9 93.9 0 0 0 8.67 47.92 67.9 67.9 0 0 1 39.56 16.52 99.4 99.4 0 0 1 25.8 37.31Z" fill="currentColor"/></svg>`;
            const editIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`;
            const viewIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
            const isParseLoading = manualParseInFlightItemId === item.id || item.parse_status === 'processing';
            const isNotionLoading = isItemSyncInFlight(item.id, 'notion');
            const isObsidianLoading = isItemSyncInFlight(item.id, 'obsidian');
            const notionTitle = isNotionLoading ? 'Notion 同步中...' : (item.notion_page_id ? '再次检查 Notion 同步' : '同步至 Notion');
            const obsidianTitle = isObsidianLoading ? 'Obsidian 同步中...' : getObsidianSyncButtonLabel(item);
            const contentModeTitle = contentViewMode === 'edit' ? '预览模式' : '编辑模式';
            const contentModeIcon = contentViewMode === 'edit' ? viewIcon : editIcon;

            modalFooter.innerHTML = `
                <div class="modal-footer-actions modal-footer-icons">
                    <button onclick="parseItemContent('${item.id}')" class="extract-btn modal-icon-btn parse-action-btn${isParseLoading ? ' is-loading' : ''}" title="${isParseLoading ? '解析中...' : '解析内容'}" ${isParseLoading ? 'disabled' : ''}>${parseIcon}</button>
                    <button onclick="syncItem('${item.id}', 'notion')" class="extract-btn modal-icon-btn${isNotionLoading ? ' is-loading' : ''}" title="${notionTitle}" ${isNotionLoading ? 'disabled' : ''}>${notionIcon}</button>
                    <button onclick="syncItem('${item.id}', 'obsidian')" class="extract-btn modal-icon-btn${isObsidianLoading ? ' is-loading' : ''}" title="${obsidianTitle}" ${isObsidianLoading ? 'disabled' : ''}>${obsidianIcon}</button>
                    <button class="extract-btn modal-icon-btn content-mode-toggle" title="${contentModeTitle}">${contentModeIcon}</button>
                </div>
            `;

            modalFooter.querySelector('.content-mode-toggle')?.addEventListener('click', async () => {
                const toggleBtn = modalFooter.querySelector('.content-mode-toggle');
                if (contentViewMode === 'edit') {
                    clearTimeout(contentAutoSaveTimer);
                    const vals = readContentEditorDOM();
                    await saveContentToServer(item.id, vals);
                    _disableContentEditing();
                    contentViewMode = 'view';
                    if (toggleBtn) {
                        toggleBtn.title = '编辑模式';
                        toggleBtn.innerHTML = editIcon;
                    }
                } else {
                    contentViewMode = 'edit';
                    _enableContentEditing(item.id);
                    if (toggleBtn) {
                        toggleBtn.title = '预览模式';
                        toggleBtn.innerHTML = viewIcon;
                    }
                }
            });
        }

        function refreshOpenModalChrome(item, options = {}) {
            if (!item || currentOpenItemId !== item.id || !modalOverlay?.classList.contains('active')) return;

            const preserveSidebarTab = Boolean(options.preserveSidebarTab);
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
            renderModalFooter(item);

            if (readerSidebarOpen && preserveSidebarTab && readerSidebarTab === 'note') {
                openReaderSidebarPanel('note');
            }
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
                refreshOpenModalChrome(getItemById(itemId), { preserveSidebarTab: true });
            }

            try {
                const response = await fetch(`/api/items/${itemId}/parse-content`, { method: 'POST' });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '解析失败');

                manualParseInFlightItemId = null;
                mergeUpdatedItem(data);
                patchRenderedItemsById(itemId);
                if (currentOpenItemId === itemId) {
                    refreshOpenModalChrome(data, { preserveSidebarTab: true });
                }
                showToast('内容解析完成', 'success');
                organizeItemAnalysis(itemId);
                return;
            } catch (error) {
                manualParseInFlightItemId = null;
                const failedItem = getItemById(itemId);
                if (failedItem) {
                    mergeUpdatedItem({
                        ...failedItem,
                        parse_status: 'failed',
                        parse_error: error.message,
                    });
                    patchRenderedItemsById(itemId);
                    if (currentOpenItemId === itemId) {
                        refreshOpenModalChrome(getItemById(itemId), { preserveSidebarTab: true });
                    }
                }
                showToast(`解析失败：${error.message}`, 'error');
            } finally {
                manualParseInFlightItemId = null;
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
                refreshOpenModalChrome(currentItem, { preserveSidebarTab: true });
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
                    refreshOpenModalChrome(data, { preserveSidebarTab: true });
                }
                showToast('内容分析已整理', 'success');
            } catch (error) {
                showToast(`整理失败：${error.message}`, 'error');
            } finally {
                analysisOrganizeInFlightItemId = null;
                const nextItem = getItemById(itemId);
                if (nextItem && currentOpenItemId === itemId) {
                    refreshOpenModalChrome(nextItem, { preserveSidebarTab: true });
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
                    refreshOpenModalChrome(data, { preserveSidebarTab: true });
                }
                showToast('解析笔记已保存', 'success');
            } catch (error) {
                showToast(`保存失败：${error.message}`, 'error');
            } finally {
                noteSaveInFlight = false;
                const nextItem = getItemById(itemId);
                if (nextItem && currentOpenItemId === itemId) {
                    refreshOpenModalChrome(nextItem, { preserveSidebarTab: true });
                }
            }
        }

        // Read current editor DOM values (title and body from contentEditable elements)
        function readContentEditorDOM() {
            const title = modalTitle?.isContentEditable ? (modalTitle.textContent?.trim() ?? null) : null;
            if (!modalContent?.isContentEditable) return { title, canonical_text: null, canonical_html: null };
            const canonical_text = modalContent.innerText ?? null;
            const canonical_html = modalContent.innerHTML ?? null;
            return { title, canonical_text, canonical_html };
        }

        // Save content edits to the database. Returns the server response item.
        async function saveContentToServer(itemId, vals) {
            if (!itemId || !vals || (vals.title == null && vals.canonical_text == null && vals.canonical_html == null)) return null;
            try {
                const response = await fetch(`/api/items/${itemId}/content`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(vals),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '保存失败');
                mergeUpdatedItem(data);
                patchRenderedItemsById(itemId);
                contentWasEdited = true;
                return data;
            } catch (error) {
                showToast(`内容保存失败：${error.message}`, 'error');
                return null;
            }
        }

        function scheduleContentAutoSave(itemId) {
            clearTimeout(contentAutoSaveTimer);
            contentAutoSaveTimer = setTimeout(() => {
                const vals = readContentEditorDOM();
                saveContentToServer(itemId, vals);
            }, 1200);
        }

        // Enable contenteditable on title and body for inline editing
        function _enableContentEditing(itemId) {
            // Title
            if (contentTitleAC) { contentTitleAC.abort(); }
            contentTitleAC = new AbortController();
            const titleSig = { signal: contentTitleAC.signal };
            modalTitle.contentEditable = 'true';
            modalTitle.classList.add('is-editable');
            modalTitle.addEventListener('input', () => scheduleContentAutoSave(itemId), titleSig);
            modalTitle.addEventListener('blur', () => { clearTimeout(contentAutoSaveTimer); saveContentToServer(itemId, readContentEditorDOM()); }, titleSig);
            modalTitle.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); modalTitle.blur(); } }, titleSig);

            // Body — make the rendered content area editable
            if (contentBodyAC) { contentBodyAC.abort(); }
            contentBodyAC = new AbortController();
            const bodySig = { signal: contentBodyAC.signal };
            modalContent.contentEditable = 'true';
            modalContent.classList.add('is-content-editable');
            modalContent.addEventListener('input', () => scheduleContentAutoSave(itemId), bodySig);
            modalContent.addEventListener('blur', () => { clearTimeout(contentAutoSaveTimer); saveContentToServer(itemId, readContentEditorDOM()); }, bodySig);
        }

        // Disable contenteditable on title and body
        function _disableContentEditing() {
            if (contentTitleAC) { contentTitleAC.abort(); contentTitleAC = null; }
            if (contentBodyAC) { contentBodyAC.abort(); contentBodyAC = null; }
            modalTitle.contentEditable = 'false';
            modalTitle.classList.remove('is-editable');
            modalContent.contentEditable = 'false';
            modalContent.classList.remove('is-content-editable');
        }

        function openModalById(itemId, options) {
            const item = getItemById(itemId);
            if (!item) return;
            openModalByItem(item, options);
        }

        function openModalByItem(item, options = {}) {
            // If this item is already open and content was edited, skip background re-renders
            // to prevent overwriting user edits. Only user-initiated mode switches bypass this.
            if (currentOpenItemId === item.id && (contentWasEdited || contentViewMode === 'edit') && !options._contentModeSwitch) {
                // Still update non-content UI (status dots, footer buttons, sidebar)
                readerStatusDots.innerHTML = renderKnowledgeDotMarkup(item);
                patchRenderedItemsById(item.id);
                return;
            }
            const keepNotePanel = Boolean(options.keepNotePanel);
            const preserveSidebarTab = Boolean(options.preserveSidebarTab);
            const pushToNavStack = Boolean(options.pushToNavStack);
            const navOrigin = options.navOrigin || null; // 'askAi' | 'readerAi'
            const previousOpenItemId = currentOpenItemId;

            // If navigating from a citation and we already have an item open, push it to the stack
            if (pushToNavStack && previousOpenItemId && previousOpenItemId !== item.id) {
                readerNavStack.push(previousOpenItemId);
            }
            // Record where this citation navigation started (only on first push)
            if (pushToNavStack && navOrigin && readerNavStack.length <= 1) {
                readerNavOrigin = navOrigin;
            }
            currentOpenItemId = item.id;
            const isNewItem = previousOpenItemId !== currentOpenItemId;
            const preferredSidebarTab = preserveSidebarTab ? (readerSidebarTab || 'note') : 'note';
            if (isNewItem) {
                contentViewMode = 'view';
                contentWasEdited = false;
                clearTimeout(contentAutoSaveTimer);
                if (contentBodyAC) { contentBodyAC.abort(); contentBodyAC = null; }
                patchRenderedItemsById([previousOpenItemId, currentOpenItemId]);
            }
            if (!keepNotePanel) {
                isNotePanelOpen = false;
            }
            modalTitle.innerText = getDisplayItemTitle(item);
            // Clean up previous edit listeners
            if (contentTitleAC) { contentTitleAC.abort(); contentTitleAC = null; }
            if (contentBodyAC) { contentBodyAC.abort(); contentBodyAC = null; }
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
                    html += `<div class="modal-media modal-media--carousel${images.length > 1 ? ' is-multi' : ''}"><div class="media-gallery">${images.map((img, i) => `<img src="${escapeAttribute(resolveMediaUrl(img.url || ''))}" alt=""${i > 0 ? ' loading="lazy" decoding="async"' : ' decoding="async"'}>`).join('')}</div>${images.length > 1 ? '<div class="gallery-hint">← 左右滑动查看更多图片 →</div>' : ''}</div>`;
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

            // ── contenteditable for edit mode ──────────────────────────────
            if (contentViewMode === 'edit') {
                _enableContentEditing(item.id);
            } else {
                modalTitle.contentEditable = 'false';
                modalTitle.classList.remove('is-editable');
                modalContent.contentEditable = 'false';
                modalContent.classList.remove('is-content-editable');
            }

            renderModalFooter(item);

            // Set fullscreen BEFORE active so overlay bg is white from frame 1 (no dark flash)
            toggleReaderFullscreen(true);
            modalOverlay.classList.remove('is-closing');
            document.body.style.overflow = 'hidden';
            // Force the browser to finish layout for the injected content in this frame,
            // then start the animation in the next frame so they don't compete.
            // eslint-disable-next-line no-unused-expressions
            modalOverlay.offsetHeight;
            requestAnimationFrame(() => {
                modalOverlay.classList.add('active');
                resetReaderChromeState(isNewItem);
                openReaderSidebarPanel(preferredSidebarTab);
            });
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
                        refreshOpenModalChrome(refreshedItem, { preserveSidebarTab: true });
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
            if (modalOverlay.classList.contains('is-closing')) return;

            // If there's a previous item on the nav stack, go back to it instead of closing
            if (readerNavStack.length > 0) {
                const prevItemId = readerNavStack.pop();
                const prevItem = getItemById(prevItemId);
                if (prevItem) {
                    openModalByItem(prevItem, { preserveSidebarTab: true });
                    return;
                }
                // If item no longer available, clear stack and close normally
                readerNavStack.length = 0;
            }

            // Return to the originating UI if applicable
            const origin = readerNavOrigin;
            readerNavOrigin = null;
            const returningToAskAi = origin === 'askAi';
            if (returningToAskAi) {
                // Reveal the Ask AI overlay that was hidden behind the reader — no animation
                const askAiOverlay = document.getElementById('askAiOverlay');
                if (askAiOverlay?.classList.contains('is-behind-reader')) {
                    askAiOverlay.classList.remove('is-behind-reader');
                } else if (typeof window.openAskAiModal === 'function') {
                    window.openAskAiModal();
                }
            }

            // Save any pending content edits before closing
            if (contentViewMode === 'edit' && currentOpenItemId) {
                clearTimeout(contentAutoSaveTimer);
                saveContentToServer(currentOpenItemId, readContentEditorDOM());
            }

            const previousOpenItemId = currentOpenItemId;
            currentOpenItemId = null;
            noteSaveInFlight = false;
            analysisOrganizeInFlightItemId = null;
            isNotePanelOpen = false;
            contentViewMode = 'view';
            contentWasEdited = false;
            clearTimeout(contentAutoSaveTimer);
            _disableContentEditing();

            // Start close animation
            modalOverlay.classList.add('is-closing');

            const cleanup = () => {
                modalOverlay.classList.remove('active', 'is-closing');
                // Keep overflow hidden when Ask AI is on top to avoid scrollbar-induced reflow
                if (!returningToAskAi) {
                    document.body.style.overflow = '';
                }
                toggleReaderFullscreen(false);
                readerSidebarOpen = false;
                readerSidebarTab = 'note';
                readerLastScrollTop = 0;
                readerNavStack.length = 0;
                readerNavOrigin = null;

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
            };

            window.setTimeout(cleanup, 240);
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
        sidebarPageNotesTab?.addEventListener('click', () => setReaderSidebarTab('pageNotes'));
        sidebarAiTab?.addEventListener('click', () => setReaderSidebarTab('ai'));

        // Initialize sidebar resize
        initSidebarResize();
        initReaderScrollMotion();

        function closeTopmostPopupOnEscape() {
            const askAiOverlay = document.getElementById('askAiOverlay');
            if (askAiOverlay?.classList.contains('active') && !askAiOverlay.classList.contains('is-behind-reader') && typeof closeAskAiDialog === 'function') {
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
            if (closeTopmostPopupOnEscape()) {
                e.preventDefault();
                e.stopImmediatePropagation();
                return;
            }
            // No popup open — clear search filter if active
            if (filterInput && filterInput.value.trim()) {
                filterInput.value = '';
                filterInput.blur();
                fetchItems();
                e.preventDefault();
                e.stopImmediatePropagation();
                return;
            }
        }, true);

        window.addEventListener('everything-capture:open-item', (event) => {
            const detail = event?.detail || {};
            const item = detail.item || null;
            const itemId = String(detail.itemId || item?.id || '').trim();
            const options = { pushToNavStack: true, navOrigin: detail.navOrigin || null };
            if (item) {
                openModalByItem(item, options);
                event.preventDefault();
                return;
            }
            if (itemId) {
                openModalById(itemId, options);
                event.preventDefault();
            }
        });

        // Expose functions to window for onclick handlers
        window.saveSidebarNote = saveSidebarNote;
        window.organizeItemAnalysis = organizeItemAnalysis;
        window.toggleReaderFullscreen = toggleReaderFullscreen;
        window.openReaderSidebarPanel = openReaderSidebarPanel;
        window.closeReaderSidebarPanel = closeReaderSidebarPanel;
        // ── Highlights ──────────────────────────────────────────────────────────

        const highlightsByItem = new Map();
        const highlightsLoadStateByItem = new Map();
        let highlightToolbarEl = null;
        let highlightPopoverEl = null;

        function getHighlightsForItem(itemId) {
            return highlightsByItem.get(itemId) || [];
        }

        // ── CSS selector path helpers ──────────────────────────────────────────

        function _selectorPathForElement(el, root) {
            if (!el || el === root) return '';
            const parts = [];
            let cur = el;
            while (cur && cur !== root && cur.parentElement) {
                if (cur.id) {
                    parts.unshift('#' + cur.id);
                    break;
                }
                const parent = cur.parentElement;
                const siblings = Array.from(parent.children);
                const idx = siblings.indexOf(cur) + 1;
                const tag = cur.tagName.toLowerCase();
                parts.unshift(`${tag}:nth-child(${idx})`);
                cur = parent;
            }
            return parts.join(' > ');
        }

        function _textNodeIndex(textNode) {
            const parent = textNode.parentNode;
            if (!parent) return 0;
            const children = parent.childNodes;
            for (let i = 0; i < children.length; i++) {
                if (children[i] === textNode) return i;
            }
            return 0;
        }

        function _resolveTextNode(root, selectorPath, textNodeIndex) {
            if (!selectorPath) return null;
            let el;
            try {
                el = root.querySelector(selectorPath);
            } catch { return null; }
            if (!el) return null;
            const node = el.childNodes[textNodeIndex];
            return (node && node.nodeType === Node.TEXT_NODE) ? node : null;
        }

        function _getContext(text, offset, length) {
            const start = Math.max(0, offset - length);
            const end = Math.min(text.length, offset + length);
            return { before: text.slice(start, offset), after: text.slice(offset, end) };
        }

        // ── Build highlight data from selection text ──────────────────────────

        function _buildHighlightData() {
            const root = modalContent;
            if (!root) return null;

            const text = _pendingSelectionText;
            if (!text || !text.trim()) return null;

            const fullText = root.textContent || '';
            const idx = fullText.indexOf(text);
            const ctx = idx >= 0
                ? { before: fullText.slice(Math.max(0, idx - 100), idx), after: fullText.slice(idx + text.length, idx + text.length + 100) }
                : { before: '', after: '' };

            return {
                text,
                // Use simple placeholders — we rely on text search for both applying and restoring
                selector_path: '',
                start_text_node_index: 0,
                start_offset: 0,
                end_selector_path: '',
                end_text_node_index: 0,
                end_offset: 0,
                context_before: ctx.before,
                context_after: ctx.after,
            };
        }

        // ── Apply highlight by text search ─────────────────────────────────────

        function _applyHighlightMark(highlightId, text, color, contextBefore, contextAfter) {
            if (!modalContent || !text) return;
            // Skip if already applied
            if (modalContent.querySelector(`mark[data-highlight-id="${highlightId}"]`)) return;

            const fullText = modalContent.textContent || '';

            // Try with context first for precision
            let textStart = -1;
            if (contextBefore || contextAfter) {
                const searchStr = (contextBefore || '') + text + (contextAfter || '');
                const idx = fullText.indexOf(searchStr);
                if (idx >= 0) textStart = idx + (contextBefore || '').length;
            }
            // Fallback: direct text search
            if (textStart < 0) {
                textStart = fullText.indexOf(text);
            }
            if (textStart < 0) return;

            // Walk text nodes to find the DOM range
            const walker = document.createTreeWalker(modalContent, NodeFilter.SHOW_TEXT);
            let charCount = 0;
            let startNode = null, startOff = 0, endNode = null, endOff = 0;
            let node;
            while ((node = walker.nextNode())) {
                const nodeLen = node.length;
                if (!startNode && charCount + nodeLen > textStart) {
                    startNode = node;
                    startOff = textStart - charCount;
                }
                if (startNode && charCount + nodeLen >= textStart + text.length) {
                    endNode = node;
                    endOff = textStart + text.length - charCount;
                    break;
                }
                charCount += nodeLen;
            }
            if (!startNode || !endNode) return;

            try {
                const range = document.createRange();
                range.setStart(startNode, startOff);
                range.setEnd(endNode, endOff);

                const mark = document.createElement('mark');
                mark.className = `highlight-${color}`;
                mark.dataset.highlightId = highlightId;
                mark.appendChild(range.extractContents());
                range.insertNode(mark);
            } catch (e) {
                console.warn('[HL] apply mark failed', e);
            }
        }

        function _unwrapHighlightMarks(highlightId) {
            if (!modalContent) return;
            const marks = modalContent.querySelectorAll(`mark[data-highlight-id="${highlightId}"]`);
            marks.forEach(mark => {
                const parent = mark.parentNode;
                while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
                parent.removeChild(mark);
                parent.normalize();
            });
        }

        // ── Restore highlights on article open ─────────────────────────────────

        function _restoreHighlights(itemId) {
            const highlights = getHighlightsForItem(itemId);
            if (!highlights.length || !modalContent) return;

            for (const h of highlights) {
                _applyHighlightMark(h.id, h.text, h.color, h.context_before, h.context_after);
            }
        }

        // ── Load highlights from API ───────────────────────────────────────────

        async function loadItemHighlights(itemId) {
            if (!itemId) return [];
            const state = highlightsLoadStateByItem.get(itemId);
            if (state === 'loading' || state === 'loaded') return getHighlightsForItem(itemId);

            highlightsLoadStateByItem.set(itemId, 'loading');
            try {
                const res = await fetch(`/api/items/${itemId}/highlights`);
                if (!res.ok) throw new Error('Failed to load highlights');
                const data = await res.json();
                const highlights = data.highlights || [];
                highlightsByItem.set(itemId, highlights);
                highlightsLoadStateByItem.set(itemId, 'loaded');
                return highlights;
            } catch {
                highlightsLoadStateByItem.set(itemId, 'idle');
                return [];
            }
        }

        async function createHighlight(itemId, highlightData) {
            try {
                console.log('[HL] creating highlight', { itemId, color: highlightData.color, text: highlightData.text?.slice(0, 50) });
                const res = await fetch(`/api/items/${itemId}/highlights`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(highlightData),
                });
                if (!res.ok) {
                    const errData = await res.json().catch(() => ({}));
                    console.error('[HL] create failed', res.status, errData);
                    throw new Error(errData.detail || 'Failed to create highlight');
                }
                const h = await res.json();
                console.log('[HL] created', h.id);
                const existing = getHighlightsForItem(itemId);
                highlightsByItem.set(itemId, [...existing, h]);
                return h;
            } catch (err) {
                showToast('高亮创建失败: ' + err.message, 'error');
                return null;
            }
        }

        async function updateHighlight(itemId, highlightId, updates) {
            try {
                const res = await fetch(`/api/items/${itemId}/highlights/${highlightId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updates),
                });
                if (!res.ok) throw new Error('Failed to update highlight');
                const h = await res.json();
                const existing = getHighlightsForItem(itemId);
                highlightsByItem.set(itemId, existing.map(x => x.id === h.id ? h : x));
                return h;
            } catch {
                showToast('高亮更新失败', 'error');
                return null;
            }
        }

        async function deleteHighlight(itemId, highlightId) {
            try {
                const res = await fetch(`/api/items/${itemId}/highlights/${highlightId}`, { method: 'DELETE' });
                if (!res.ok) throw new Error('Failed to delete highlight');
                const existing = getHighlightsForItem(itemId);
                highlightsByItem.set(itemId, existing.filter(x => x.id !== highlightId));
                _unwrapHighlightMarks(highlightId);
            } catch {
                showToast('高亮删除失败', 'error');
            }
        }

        // ── Floating toolbar / popover ─────────────────────────────────────────

        const HIGHLIGHT_COLORS = ['yellow', 'green', 'blue', 'red'];
        const HIGHLIGHT_COLOR_VALUES = {
            yellow: 'rgba(255, 212, 0, 0.45)',
            green: 'rgba(72, 199, 142, 0.45)',
            blue: 'rgba(66, 153, 225, 0.45)',
            red: 'rgba(245, 101, 101, 0.45)',
        };

        function _dismissHighlightToolbar() {
            if (highlightToolbarEl) {
                highlightToolbarEl.remove();
                highlightToolbarEl = null;
            }
            _pendingSelection = null;
            _pendingSelectionText = null;
        }

        function _dismissHighlightPopover() {
            if (highlightPopoverEl) {
                highlightPopoverEl.remove();
                highlightPopoverEl = null;
            }
        }

        function _positionFloatingEl(el, selectionRect) {
            const scrollParent = modalContent?.closest('.reader-main-column') || document.body;
            const containerRect = scrollParent.getBoundingClientRect();

            // Convert viewport coords to container-relative coords (accounting for scroll)
            let top = selectionRect.top - containerRect.top + scrollParent.scrollTop - el.offsetHeight - 8;
            let left = selectionRect.left - containerRect.left + scrollParent.scrollLeft + (selectionRect.width / 2) - (el.offsetWidth / 2);

            // Keep within bounds
            left = Math.max(4, Math.min(left, containerRect.width - el.offsetWidth - 4));
            if (top < scrollParent.scrollTop + 4) {
                // Show below selection if no room above
                top = selectionRect.bottom - containerRect.top + scrollParent.scrollTop + 8;
            }

            el.style.top = top + 'px';
            el.style.left = left + 'px';
        }

        function _showHighlightToolbar(range) {
            _dismissHighlightToolbar();
            _dismissHighlightPopover();

            const itemId = currentOpenItemId;
            if (!itemId || contentViewMode === 'edit') return;

            const rect = range.getBoundingClientRect();
            if (!rect.width && !rect.height) return;

            // Save the selected text — we use text search to apply marks, not Range manipulation
            _pendingSelectionText = range.toString();

            const toolbar = document.createElement('div');
            toolbar.className = 'highlight-toolbar';

            // Prevent toolbar clicks from clearing selection
            toolbar.addEventListener('mousedown', (e) => e.preventDefault());

            // Color dots
            for (const color of HIGHLIGHT_COLORS) {
                const dot = document.createElement('button');
                dot.className = 'hl-color-dot';
                dot.dataset.color = color;
                dot.style.background = HIGHLIGHT_COLOR_VALUES[color];
                dot.title = color;
                dot.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _handleHighlightCreate(itemId, color);
                });
                toolbar.appendChild(dot);
            }

            // Quote to note button
            const quoteBtn = document.createElement('button');
            quoteBtn.className = 'hl-quote-btn';
            quoteBtn.title = '引用到笔记';
            quoteBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>';
            quoteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                _handleQuoteToNote(itemId, 'yellow');
            });
            toolbar.appendChild(quoteBtn);

            const scrollParent = modalContent?.closest('.reader-main-column') || document.body;
            scrollParent.style.position = 'relative';
            scrollParent.appendChild(toolbar);
            highlightToolbarEl = toolbar;

            _positionFloatingEl(toolbar, rect);
        }

        function _showHighlightPopover(markEl) {
            _dismissHighlightToolbar();
            _dismissHighlightPopover();

            const highlightId = markEl.dataset.highlightId;
            const itemId = currentOpenItemId;
            if (!highlightId || !itemId) return;

            const existing = getHighlightsForItem(itemId).find(h => h.id === highlightId);
            const currentColor = existing?.color || 'yellow';

            const popover = document.createElement('div');
            popover.className = 'highlight-toolbar highlight-popover';

            // Color dots
            for (const color of HIGHLIGHT_COLORS) {
                const dot = document.createElement('button');
                dot.className = 'hl-color-dot' + (color === currentColor ? ' is-active' : '');
                dot.dataset.color = color;
                dot.style.background = HIGHLIGHT_COLOR_VALUES[color];
                dot.title = color;
                dot.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (color === currentColor) return;
                    await updateHighlight(itemId, highlightId, { color });
                    // Update mark classes
                    const marks = modalContent.querySelectorAll(`mark[data-highlight-id="${highlightId}"]`);
                    marks.forEach(m => {
                        m.className = `highlight-${color}`;
                    });
                    _dismissHighlightPopover();
                });
                popover.appendChild(dot);
            }

            // Quote to note
            const quoteBtn = document.createElement('button');
            quoteBtn.className = 'hl-quote-btn';
            quoteBtn.title = '引用到笔记';
            quoteBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>';
            quoteBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const text = existing?.text || markEl.textContent || '';
                await _quoteTextToNote(itemId, text, highlightId);
                _dismissHighlightPopover();
            });
            popover.appendChild(quoteBtn);

            // Delete button
            const delBtn = document.createElement('button');
            delBtn.className = 'hl-delete-btn';
            delBtn.title = '删除高亮';
            delBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>';
            delBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                await deleteHighlight(itemId, highlightId);
                _dismissHighlightPopover();
            });
            popover.appendChild(delBtn);

            const scrollParent = modalContent?.closest('.reader-main-column') || document.body;
            scrollParent.style.position = 'relative';
            scrollParent.appendChild(popover);
            highlightPopoverEl = popover;

            const rect = markEl.getBoundingClientRect();
            _positionFloatingEl(popover, rect);
        }

        // ── Highlight create + quote to note ───────────────────────────────────

        let _pendingSelection = null;
        let _pendingSelectionText = null;

        async function _handleHighlightCreate(itemId, color) {
            console.log('[HL] _handleHighlightCreate', { itemId, color, text: _pendingSelectionText?.slice(0, 50) });
            const data = _buildHighlightData();
            if (!data) {
                console.warn('[HL] no data from selection');
                _dismissHighlightToolbar();
                return;
            }

            data.color = color;
            window.getSelection()?.removeAllRanges();
            _dismissHighlightToolbar();

            const h = await createHighlight(itemId, data);
            if (h) {
                _applyHighlightMark(h.id, h.text, h.color, h.context_before, h.context_after);
            }
        }

        async function _handleQuoteToNote(itemId, color) {
            const data = _buildHighlightData();
            if (!data) {
                _dismissHighlightToolbar();
                return;
            }

            const text = data.text;
            data.color = color;

            // Determine target note
            let targetNoteId = null;
            if (activePageNoteId && pageNoteViewMode === 'source' && readerSidebarTab === 'pageNotes') {
                targetNoteId = activePageNoteId;
            }

            if (!targetNoteId) {
                // Create new note with quoted text
                const noteTitle = text.length > 30 ? text.slice(0, 30) + '...' : text;
                const note = await createReaderPageNote(itemId, {
                    title: noteTitle,
                    content: `> ${text}\n\n`,
                    successMessage: '已引用到新笔记',
                });
                if (note) {
                    targetNoteId = note.id;
                    data.page_note_id = note.id;
                    activePageNoteId = note.id;
                    pageNoteViewMode = 'source';
                    openReaderSidebarPanel('pageNotes');
                }
            } else {
                // Append to existing note
                data.page_note_id = targetNoteId;
                const contentInput = document.getElementById('pnEditorContent');
                if (contentInput) {
                    const current = contentInput.value || '';
                    const separator = current.endsWith('\n\n') ? '' : (current.endsWith('\n') ? '\n' : '\n\n');
                    contentInput.value = current + separator + `> ${text}\n\n`;
                    // Trigger auto-save
                    triggerPageNoteAutoSave(itemId, targetNoteId);
                    // Scroll textarea to bottom
                    contentInput.scrollTop = contentInput.scrollHeight;
                }
                showToast('已引用到当前笔记', 'success');
            }

            // Create the highlight
            window.getSelection()?.removeAllRanges();
            _dismissHighlightToolbar();

            const h = await createHighlight(itemId, data);
            if (h) {
                _applyHighlightMark(h.id, h.text, h.color, h.context_before, h.context_after);
            }
        }

        async function _quoteTextToNote(itemId, text, highlightId) {
            if (!text) return;

            let targetNoteId = null;
            if (activePageNoteId && pageNoteViewMode === 'source' && readerSidebarTab === 'pageNotes') {
                targetNoteId = activePageNoteId;
            }

            if (!targetNoteId) {
                const noteTitle = text.length > 30 ? text.slice(0, 30) + '...' : text;
                const note = await createReaderPageNote(itemId, {
                    title: noteTitle,
                    content: `> ${text}\n\n`,
                    successMessage: '已引用到新笔记',
                });
                if (note) {
                    targetNoteId = note.id;
                    activePageNoteId = note.id;
                    pageNoteViewMode = 'source';
                    openReaderSidebarPanel('pageNotes');
                }
            } else {
                const contentInput = document.getElementById('pnEditorContent');
                if (contentInput) {
                    const current = contentInput.value || '';
                    const separator = current.endsWith('\n\n') ? '' : (current.endsWith('\n') ? '\n' : '\n\n');
                    contentInput.value = current + separator + `> ${text}\n\n`;
                    triggerPageNoteAutoSave(itemId, targetNoteId);
                    contentInput.scrollTop = contentInput.scrollHeight;
                }
                showToast('已引用到当前笔记', 'success');
            }

            // Link highlight to note
            if (highlightId && targetNoteId) {
                await updateHighlight(itemId, highlightId, { page_note_id: targetNoteId });
            }
        }

        // ── Event listeners ────────────────────────────────────────────────────

        // Selection toolbar on mouseup in modal content
        modalContent?.addEventListener('mouseup', (e) => {
            if (contentViewMode === 'edit') return;

            // Check if clicked on an existing highlight mark
            const markEl = e.target.closest('mark[data-highlight-id]');
            if (markEl) {
                _showHighlightPopover(markEl);
                return;
            }

            // Short delay to let selection finalize
            setTimeout(() => {
                const sel = window.getSelection();
                if (!sel || sel.isCollapsed || !sel.rangeCount) {
                    _dismissHighlightToolbar();
                    return;
                }

                const range = sel.getRangeAt(0);
                const text = range.toString().trim();
                if (!text) {
                    _dismissHighlightToolbar();
                    return;
                }

                // Verify selection is within modalContent
                if (!modalContent.contains(range.startContainer) || !modalContent.contains(range.endContainer)) {
                    return;
                }

                _showHighlightToolbar(range);
            }, 10);
        });

        // Dismiss on mousedown (new selection start)
        modalContent?.addEventListener('mousedown', (e) => {
            if (!e.target.closest('.highlight-toolbar') && !e.target.closest('.highlight-popover')) {
                _dismissHighlightToolbar();
                _dismissHighlightPopover();
            }
        });

        // Dismiss on Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                _dismissHighlightToolbar();
                _dismissHighlightPopover();
            }
        });

        // Dismiss when clicking outside modal content
        modalOverlay?.addEventListener('click', (e) => {
            if (!e.target.closest('.modal-body') && !e.target.closest('.highlight-toolbar') && !e.target.closest('.highlight-popover')) {
                _dismissHighlightToolbar();
                _dismissHighlightPopover();
            }
        });

        // ── Hook into openModalByItem to restore highlights ────────────────────

        const _originalOpenModalByItem = openModalByItem;

        // We need to monkey-patch because openModalByItem is a local function
        // Instead, we'll hook into the end of it via the animation callback
        // We override the existing function and call the original
        // Actually, let's use a simpler approach: listen for modal open and restore

        // Use a MutationObserver to detect when modal content changes
        if (modalContent) {
            const _hlRestoreObserver = new MutationObserver(() => {
                const itemId = currentOpenItemId;
                if (!itemId) return;
                // Debounce: wait a tick for content to settle
                clearTimeout(_hlRestoreObserver._timer);
                _hlRestoreObserver._timer = setTimeout(async () => {
                    // Only restore if we have loaded highlights or need to load them
                    if (highlightsLoadStateByItem.get(itemId) !== 'loaded') {
                        await loadItemHighlights(itemId);
                    }
                    _restoreHighlights(itemId);
                }, 100);
            });
            _hlRestoreObserver.observe(modalContent, { childList: true, subtree: false });
        }

        window.renderSidebarAiContent = renderSidebarAiContent;
        window.setReaderChromeHidden = setReaderChromeHidden;
        window.createReaderPageNote = createReaderPageNote;
        window.deleteReaderPageNote = deleteReaderPageNote;
        window.loadItemPageNotes = loadItemPageNotes;
        window.cacheItemById = cacheItemById;
        window.getItemById = getItemById;
        window.openModalById = openModalById;
        window.openModalByItem = openModalByItem;

        bootstrapApp();
