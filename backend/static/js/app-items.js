        async function fetchItems() {
            const requestId = ++libraryRequestId;
            if (!ensureAuthenticated({ showOverlay: false })) {
                resetAuthenticatedAppState();
                return;
            }
            try {
                const response = await fetch(`/api/items?${getActiveSearchParams(200).toString()}`);
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
            } catch (error) {
                if (!authState.authenticated) return;
                setStatsMessage('加载失败');
                grid.className = 'grid';
                grid.innerHTML = '<div class="empty-state">无法连接到后端 API</div>';
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
                let changed = false;

                itemsData = itemsData.map((item) => {
                    const nextStatus = statusMap.get(item.id);
                    if (!nextStatus) return item;
                    if (item.notion_page_id === nextStatus.notion_page_id && item.obsidian_path === nextStatus.obsidian_path) {
                        return item;
                    }
                    changed = true;
                    return {
                        ...item,
                        notion_page_id: nextStatus.notion_page_id || null,
                        obsidian_path: nextStatus.obsidian_path || null,
                    };
                });

                commandSearchResults = commandSearchResults.map((item) => {
                    const nextStatus = statusMap.get(item.id);
                    if (!nextStatus) return item;
                    return {
                        ...item,
                        notion_page_id: nextStatus.notion_page_id || null,
                        obsidian_path: nextStatus.obsidian_path || null,
                    };
                });

                filteredEntries = itemsData;

                if (changed) {
                    renderItems(filteredEntries);
                    const refreshedItem = currentOpenItemId
                        ? itemsData.find((item) => item.id === currentOpenItemId) || commandSearchResults.find((item) => item.id === currentOpenItemId)
                        : null;
                    if (refreshedItem && currentOpenItemId === refreshedItem.id) {
                        openModalByItem(refreshedItem);
                    }
                }
            } catch (error) {
                console.warn('Failed to refresh remote sync status', error);
            } finally {
                remoteSyncRefreshInFlight = false;
            }
        }

        function getTrackedRemoteSyncItemIds(entries = itemsData) {
            return (entries || [])
                .filter((item) => item.notion_page_id || item.obsidian_path)
                .map((item) => item.id);
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
                    : '<div class="empty-state">暂无收录内容，请在 App 中添加。</div>';
                return;
            }

            if (currentView === 'list') {
                grid.className = 'list-view';
                grid.innerHTML = entries.map((item) => {
                    const textPreview = getDisplayItemPreview(item, 120);
                    const length = item.canonical_text ? item.canonical_text.length : 0;
                    const thumb = getItemThumbnail(item);
                    const activeClass = currentOpenItemId === item.id ? ' is-active' : '';
                    const displayTitle = getDisplayItemTitle(item);
                    const fullTitle = String(item.title || displayTitle || '无标题').trim();
                    const thumbHtml = thumb
                        ? `<div class="list-thumb"><img src="${thumb.url}" loading="lazy" alt=""></div>`
                        : `<div class="list-thumb"></div>`;
                    return `
                        <div class="list-row${activeClass}" onclick="handleItemPrimaryAction('${item.id}')">
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
                                    ${renderSyncBadges(item)}
                                    ${renderFolderActionButton(item)}
                                    <button onclick="deleteItem('${item.id}', event)" class="delete-btn" title="删除">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2M10 11v6M14 11v6"/></svg>
                                    </button>
                                    <a href="${item.source_url}" target="_blank" class="source-link" onclick="event.stopPropagation()">原文 ↗</a>
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
                return;
            }

            grid.className = 'grid';
            grid.innerHTML = entries.map((item) => {
                const activeClass = currentOpenItemId === item.id ? ' is-active' : '';
                const displayTitle = getDisplayItemTitle(item);
                const title = escapeHtml(displayTitle);
                const fullTitle = escapeAttribute(String(item.title || displayTitle || '无标题').trim());
                const sourceLabel = escapeHtml(`来自 ${platformDisplayLabel(item)}`);
                const relativeTime = escapeHtml(formatRelativeTime(item.created_at));
                const tagsHtml = renderCardTags(item);

                return `
                    <div class="card${activeClass}" onclick="handleItemPrimaryAction('${item.id}')">
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
                            <h3 class="card-title" title="${fullTitle}">${title}</h3>
                            <div class="card-bottom-row">
                                <div class="tags">
                                    ${tagsHtml}
                                </div>
                                <div class="card-footer-actions">
                                    <button onclick="deleteItem('${item.id}', event)" class="delete-btn" title="删除">
                                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2M10 11v6M14 11v6"/></svg>
                                    </button>
                                    <a href="${item.source_url}" target="_blank" class="source-link" onclick="event.stopPropagation()">
                                        原文 ↗
                                </a>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
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

        function renderNotePanel(item) {
            if (!readerNotePanel) return;

            const summary = formatParseStatusSummary(item);
            const extractedText = String(item?.extracted_text || '');
            const placeholder = item?.parse_status === 'processing'
                ? '正在解析图片 / 视频中的原始文字内容...'
                : '解析后的原始文字会显示在这里，你也可以直接修改。';

            readerNotePanel.innerHTML = `
                <div class="reader-note-shell">
                    <div class="reader-note-header">
                        <div class="reader-note-title">解析笔记</div>
                        <div class="reader-note-meta">${escapeHtml(summary)}</div>
                    </div>
                    <textarea id="readerNoteTextarea" class="reader-note-textarea" placeholder="${escapeAttribute(placeholder)}">${escapeHtml(extractedText)}</textarea>
                    <div class="reader-note-actions">
                        <button
                            onclick="saveItemNote('${item.id}')"
                            class="extract-btn modal-action-btn"
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
            renderItems(filteredEntries);
            if (currentOpenItemId === itemId) {
                isNotePanelOpen = true;
                openModalByItem(getItemById(itemId), { keepNotePanel: true });
            }

            try {
                const response = await fetch(`/api/items/${itemId}/parse-content`, { method: 'POST' });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '解析失败');

                mergeUpdatedItem(data);
                renderItems(filteredEntries);
                if (currentOpenItemId === itemId) {
                    isNotePanelOpen = true;
                    openModalByItem(data, { keepNotePanel: true });
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
                    renderItems(filteredEntries);
                    if (currentOpenItemId === itemId) {
                        isNotePanelOpen = true;
                        openModalByItem(getItemById(itemId), { keepNotePanel: true });
                    }
                }
                showToast(`解析失败：${error.message}`, 'error');
            } finally {
                manualParseInFlightItemId = null;
                renderItems(filteredEntries);
                const nextItem = getItemById(itemId);
                if (nextItem && currentOpenItemId === itemId) {
                    openModalByItem(nextItem, { keepNotePanel: true });
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
                renderItems(filteredEntries);
                if (currentOpenItemId === itemId) {
                    openModalByItem(data, { keepNotePanel: true });
                }
                showToast('解析笔记已保存', 'success');
            } catch (error) {
                showToast(`保存失败：${error.message}`, 'error');
            } finally {
                noteSaveInFlight = false;
                const nextItem = getItemById(itemId);
                if (nextItem && currentOpenItemId === itemId) {
                    openModalByItem(nextItem, { keepNotePanel: true });
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
            currentOpenItemId = item.id;
            renderItems(filteredEntries);
            if (!keepNotePanel) {
                isNotePanelOpen = false;
            }
            modalTitle.innerText = getDisplayItemTitle(item);
            readerStatusDots.innerHTML = `
                <span class="knowledge-dot notion ${item.notion_page_id ? 'is-ready' : 'is-idle'}" title="Notion${item.notion_page_id ? '已同步' : '未同步'}"></span>
                <span class="knowledge-dot obsidian ${item.obsidian_path ? 'is-ready' : 'is-idle'}" title="Obsidian${item.obsidian_path ? '已同步' : '未同步'}"></span>
            `;
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
                    html += `<div class="modal-media"><video controls preload="metadata" poster="${cover ? cover.url : ''}"><source src="${videos[0].url}" type="video/mp4"></video></div>`;
                }
                if (images.length > 0) {
                    html += `<div class="modal-media"><div class="media-gallery">${images.map(img => `<img src="${img.url}" alt="">`).join('')}</div>${images.length > 1 ? '<div class="gallery-hint">← 左右滑动查看更多图片 →</div>' : ''}</div>`;
                }
                html += `<div style="white-space:pre-wrap">${item.canonical_text || '暂无内容'}</div>`;
                modalContent.innerHTML = html;

            } else {
                // ── 通用网页 / 微信：优先恢复原始图文流，再按稳妥策略回退 ──────────────
                modalContent.innerHTML = renderWebArticle(item, videos);
            }

            modalFooter.innerHTML = `
                <div class="modal-footer-actions">
                    <button onclick="parseItemContent('${item.id}')" class="extract-btn modal-action-btn" ${manualParseInFlightItemId === item.id || item.parse_status === 'processing' ? 'disabled' : ''}>${manualParseInFlightItemId === item.id || item.parse_status === 'processing' ? '解析中...' : '解析内容'}</button>
                    <button onclick="syncItem('${item.id}', 'notion')" class="extract-btn modal-action-btn">${item.notion_page_id ? '再次检查 Notion 同步' : '同步至 Notion'}</button>
                    <button onclick="syncItem('${item.id}', 'obsidian')" class="extract-btn modal-action-btn">${item.obsidian_path ? '再次检查 Obsidian 同步' : '同步至 Obsidian'}</button>
                    <button onclick="downloadZip('${item.id}')" class="extract-btn modal-action-btn">下载 ZIP</button>
                </div>
            `;

            modalOverlay.classList.add('active');
            document.body.style.overflow = 'hidden';
        }

        async function syncItem(id, target) {
            showToast(`正在后台同步至 ${target}...`, 'info');
            try {
                const res = await fetch(`/api/connect/${target}/sync/${id}`, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    const currentItem = itemsData.find(item => item.id === id);
                    if (currentItem) {
                        if (target === 'notion' && data.notion_page_id) currentItem.notion_page_id = data.notion_page_id;
                        if (target === 'obsidian' && data.obsidian_path) currentItem.obsidian_path = data.obsidian_path;
                    }
                    const commandItem = commandSearchResults.find((item) => item.id === id);
                    if (commandItem) {
                        if (target === 'notion' && data.notion_page_id) commandItem.notion_page_id = data.notion_page_id;
                        if (target === 'obsidian' && data.obsidian_path) commandItem.obsidian_path = data.obsidian_path;
                    }
                    renderItems(filteredEntries);
                    const refreshedItem = itemsData.find(item => item.id === id) || commandSearchResults.find(item => item.id === id);
                    if (currentOpenItemId === id && refreshedItem) {
                        openModalByItem(refreshedItem);
                    }
                    if (target === 'notion' && data.target_object) {
                        const targetLabel = data.target_object === 'database' ? 'Database' : 'Page';
                        const targetName = data.target_title || data.target_id || 'Untitled';
                        showToast(`已同步到 Notion ${targetLabel}: ${targetName}`, 'success');
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
            }
        }

        function downloadZip(id) {
            window.location.href = `/api/items/${id}/export/zip`;
        }

        function closeModalDialog() {
            modalOverlay.classList.remove('active');
            document.body.style.overflow = '';
            currentOpenItemId = null;
            noteSaveInFlight = false;
            isNotePanelOpen = false;
            if (readerNotePanel) {
                readerNotePanel.innerHTML = '';
            }
            setNotePanelOpen(false);
            readerStatusDots.innerHTML = '';
            modalFooter.innerHTML = '';
            renderItems(filteredEntries);
        }

        closeModal.onclick = () => {
            closeModalDialog();
        };

        closeModal.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                closeModalDialog();
            }
        });

        modalOverlay.onclick = (e) => {
            if (e.target === modalOverlay) closeModalDialog();
        };
        settingsOverlay.onclick = (e) => {
            if (e.target === settingsOverlay) closeSettingsModal.onclick();
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
                setNotePanelOpen();
            };

            toggleNoteBtn.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setNotePanelOpen();
                }
            });
        }

        bootstrapAuth();
