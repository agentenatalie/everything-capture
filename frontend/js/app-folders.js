        /*
         * Everything Capture — frontend folders module.
         * This software is licensed under Elastic License 2.0; see the LICENSE file.
         * Unauthorized use for hosted or managed services is strictly prohibited.
         * For commercial or SaaS licensing, contact:
         * https://github.com/agentenatalie
         */
        const PINNED_FOLDER_IDS_STORAGE_KEY = 'everything-capture-pinned-folder-ids-v1';
        const RECENT_FOLDER_USAGE_STORAGE_KEY = 'everything-capture-recent-folder-usage-v1';
        const MAX_RECENT_FOLDER_USAGE_ENTRIES = 150;
        const FOLDER_LIST_AUTOSCROLL_EDGE_PX = 72;
        const FOLDER_LIST_AUTOSCROLL_MAX_SPEED = 18;

        let folderListAutoScrollFrame = null;
        let folderListAutoScrollSpeed = 0;

        function readStoredFolderIds(storageKey) {
            try {
                const parsed = JSON.parse(window.localStorage.getItem(storageKey) || '[]');
                return Array.isArray(parsed)
                    ? parsed.map((value) => String(value || '').trim()).filter(Boolean)
                    : [];
            } catch (error) {
                return [];
            }
        }

        function readStoredFolderUsage() {
            try {
                const parsed = JSON.parse(window.localStorage.getItem(RECENT_FOLDER_USAGE_STORAGE_KEY) || '{}');
                if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
                return Object.fromEntries(
                    Object.entries(parsed)
                        .map(([folderId, timestamp]) => [String(folderId || '').trim(), Number(timestamp || 0)])
                        .filter(([folderId, timestamp]) => folderId && Number.isFinite(timestamp) && timestamp > 0)
                );
            } catch (error) {
                return {};
            }
        }

        let pinnedFolderIds = new Set(readStoredFolderIds(PINNED_FOLDER_IDS_STORAGE_KEY));
        let recentFolderUsage = readStoredFolderUsage();

        function persistPinnedFolderIds() {
            try {
                window.localStorage.setItem(PINNED_FOLDER_IDS_STORAGE_KEY, JSON.stringify([...pinnedFolderIds]));
            } catch (error) {
                console.warn('Failed to persist pinned folders', error);
            }
        }

        function persistRecentFolderUsage() {
            try {
                const entries = Object.entries(recentFolderUsage)
                    .sort(([, a], [, b]) => Number(b || 0) - Number(a || 0))
                    .slice(0, MAX_RECENT_FOLDER_USAGE_ENTRIES);
                recentFolderUsage = Object.fromEntries(entries);
                window.localStorage.setItem(RECENT_FOLDER_USAGE_STORAGE_KEY, JSON.stringify(recentFolderUsage));
            } catch (error) {
                console.warn('Failed to persist recent folders', error);
            }
        }

        function pruneFolderPreferences() {
            const knownFolderIds = new Set(foldersData.map((folder) => folder.id));
            const nextPinnedIds = [...pinnedFolderIds].filter((folderId) => knownFolderIds.has(folderId));
            if (nextPinnedIds.length !== pinnedFolderIds.size) {
                pinnedFolderIds = new Set(nextPinnedIds);
                persistPinnedFolderIds();
            }

            let changedRecentUsage = false;
            for (const folderId of Object.keys(recentFolderUsage)) {
                if (!knownFolderIds.has(folderId)) {
                    delete recentFolderUsage[folderId];
                    changedRecentUsage = true;
                }
            }
            if (changedRecentUsage) {
                persistRecentFolderUsage();
            }
        }

        function normalizeFolderIds(folderIds = []) {
            return Array.from(new Set(
                (Array.isArray(folderIds) ? folderIds : [folderIds])
                    .map((folderId) => String(folderId || '').trim())
                    .filter(Boolean)
            ));
        }

        function markFoldersRecentlyUsed(folderIds = [], options = {}) {
            const normalizedFolderIds = normalizeFolderIds(folderIds);
            if (!normalizedFolderIds.length) return;
            const knownFolderIds = new Set(foldersData.map((folder) => folder.id));
            const now = Date.now();
            let changed = false;
            normalizedFolderIds.forEach((folderId, index) => {
                if (knownFolderIds.size && !knownFolderIds.has(folderId)) return;
                const nextTimestamp = now - index;
                if (recentFolderUsage[folderId] !== nextTimestamp) {
                    recentFolderUsage[folderId] = nextTimestamp;
                    changed = true;
                }
            });
            if (!changed) return;
            persistRecentFolderUsage();
            if (options.render) {
                renderFolderNavigation();
            }
        }

        function isFolderPinned(folderId) {
            return pinnedFolderIds.has(String(folderId || '').trim());
        }

        function toggleFolderPin(folderId) {
            const normalizedFolderId = String(folderId || '').trim();
            const folder = getFolderById(normalizedFolderId);
            if (!folder) return;
            closeFolderContextMenu();
            if (pinnedFolderIds.has(normalizedFolderId)) {
                pinnedFolderIds.delete(normalizedFolderId);
                showToast(`已取消固定：${folder.name}`, 'info');
            } else {
                pinnedFolderIds.add(normalizedFolderId);
                expandFolderAncestors(normalizedFolderId);
                showToast(`已固定在文件夹顶部：${folder.name}`, 'success');
            }
            persistPinnedFolderIds();
            renderFolderNavigation();
        }

        function parseFolderTimestamp(value) {
            const timestamp = Date.parse(value || '');
            return Number.isFinite(timestamp) ? timestamp : 0;
        }

        function getFolderDirectUsageTimestamp(folder) {
            if (!folder) return 0;
            return Math.max(
                Number(recentFolderUsage[folder.id] || 0),
                parseFolderTimestamp(folder.updated_at),
                parseFolderTimestamp(folder.created_at)
            );
        }

        function createFolderUsageTimestampGetter(folders) {
            const childrenByParent = {};
            const foldersById = {};
            for (const folder of folders) {
                foldersById[folder.id] = folder;
                const parentId = folder.parent_id || '__root__';
                if (!childrenByParent[parentId]) childrenByParent[parentId] = [];
                childrenByParent[parentId].push(folder);
            }
            const cache = new Map();
            const getTimestamp = (folderId) => {
                if (cache.has(folderId)) return cache.get(folderId);
                const folder = foldersById[folderId];
                let latest = getFolderDirectUsageTimestamp(folder);
                for (const child of childrenByParent[folderId] || []) {
                    latest = Math.max(latest, getTimestamp(child.id));
                }
                cache.set(folderId, latest);
                return latest;
            };
            return getTimestamp;
        }

        function compareFolderFallback(a, b) {
            const sortOrderA = Number.isFinite(Number(a.sort_order)) ? Number(a.sort_order) : 0;
            const sortOrderB = Number.isFinite(Number(b.sort_order)) ? Number(b.sort_order) : 0;
            if (sortOrderA !== sortOrderB) return sortOrderA - sortOrderB;
            const createdA = parseFolderTimestamp(a.created_at);
            const createdB = parseFolderTimestamp(b.created_at);
            if (createdA !== createdB) return createdA - createdB;
            return String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hans');
        }

        function sortFoldersForNavigation(folders, getUsageTimestamp) {
            return [...folders].sort((a, b) => {
                const aPinned = isFolderPinned(a.id);
                const bPinned = isFolderPinned(b.id);
                if (aPinned !== bPinned) return aPinned ? -1 : 1;
                if (aPinned && bPinned) {
                    const pinnedOrder = [...pinnedFolderIds];
                    const pinnedA = pinnedOrder.indexOf(a.id);
                    const pinnedB = pinnedOrder.indexOf(b.id);
                    if (pinnedA !== pinnedB) return pinnedA - pinnedB;
                }
                const recentA = getUsageTimestamp(a.id);
                const recentB = getUsageTimestamp(b.id);
                if (recentA !== recentB) return recentB - recentA;
                return compareFolderFallback(a, b);
            });
        }

        function showToast(msg, type) {
            toast.textContent = msg;
            toast.className = 'toast ' + type + ' show';
            setTimeout(() => { toast.classList.remove('show'); }, 4000);
        }

        function setStatsMessage(message) {
            stats.classList.add('is-plain');
            stats.textContent = message;
        }

        function setStatsSummary(total, visible, returned, hasFilter) {
            stats.classList.remove('is-plain');
            const isInFolder = currentFolderScope === 'folder' || currentFolderScope === 'unfiled';
            const statsCountLabel = isInFolder
                ? `文件夹收录&nbsp;&nbsp;<strong>${visible}</strong>&nbsp;&nbsp;篇内容`
                : `已收录&nbsp;&nbsp;<strong>${total}</strong>&nbsp;&nbsp;篇内容`;
            if (hasFilter && visible > returned) {
                stats.innerHTML = `<span class="stats-primary">${statsCountLabel}</span><span class="stats-secondary">匹配 ${visible} 篇，显示最新 ${returned} 篇</span>`;
                return;
            }
            stats.innerHTML = `<span class="stats-primary">${statsCountLabel}</span>`;
        }

        function folderIconSvg() {
            return '<svg class="folder-item-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3.75 6.75A2.25 2.25 0 0 1 6 4.5h3.2a2.25 2.25 0 0 1 1.59.66l1.05 1.05c.28.28.66.44 1.06.44H18A2.25 2.25 0 0 1 20.25 8.9v7.6A2.25 2.25 0 0 1 18 18.75H6A2.25 2.25 0 0 1 3.75 16.5v-9.75Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>';
        }

        function checkSvg() {
            return '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 12 4.2 4.2L19 6.5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
        }

        function getCurrentFolderLabel() {
            if (currentFolderScope === 'unfiled') return '未分类';
            if (currentFolderScope === 'favorites') return '收藏夹';
            if (currentFolderScope === 'unread') return '未读';
            if (currentFolderScope === 'folder') {
                const folder = foldersData.find((entry) => entry.id === currentFolderId);
                return folder ? `文件夹：${folder.name}` : '文件夹';
            }
            return '全部内容';
        }

        function handleItemPrimaryAction(itemId) {
            history.pushState({ reader: itemId }, '', '/reader/' + encodeURIComponent(itemId));
            openModalById(itemId);
        }

        function getItemFolderNames(item) {
            if (Array.isArray(item?.folder_names) && item.folder_names.length) {
                return uniquePreserveOrder(item.folder_names.filter(Boolean));
            }
            return item?.folder_name ? [item.folder_name] : [];
        }

        function renderFolderTags(item) {
            const folderNames = getItemFolderNames(item);
            let html = '';
            if (folderNames.length) {
                html += folderNames.slice(0, 3).map((folderName) => (
                    `<span class="folder-tag">${folderIconSvg()}<span>${escapeHtml(folderName)}</span></span>`
                )).join('');
            }
            const tagNames = item.tag_names || [];
            if (tagNames.length) {
                html += tagNames.slice(0, 2).map((tagName) => (
                    `<span class="item-tag-pill">${escapeHtml(tagName)}</span>`
                )).join('');
            }
            return html;
        }

        function openFolderPickerForItem(itemId, title = '管理文件夹') {
            const normalizedItemId = String(itemId || '').trim();
            const selectedItemIds = typeof getSelectedLibraryItemIds === 'function'
                ? getSelectedLibraryItemIds()
                : [];
            const targetItemIds = selectedItemIds.includes(normalizedItemId) && selectedItemIds.length > 1
                ? selectedItemIds
                : [normalizedItemId];
            const item = itemsData.find((entry) => entry.id === normalizedItemId) || commandSearchResults.find((entry) => entry.id === normalizedItemId);
            const preferredFolderIds = targetItemIds.length > 1
                ? getSharedFolderIds(targetItemIds)
                : (Array.isArray(item?.folder_ids) ? item.folder_ids : []);
            const pickerTitle = targetItemIds.length > 1 && title === '管理文件夹'
                ? `管理 ${targetItemIds.length} 条内容的文件夹`
                : title;
            openFolderPicker(targetItemIds, preferredFolderIds, pickerTitle);
        }

        function renderFolderActionButton(item) {
            return `
                <button onclick="openFolderPickerForItem('${item.id}', '管理文件夹'); event.stopPropagation();" class="folder-action-btn" title="管理文件夹">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M3.75 6.75A2.25 2.25 0 0 1 6 4.5h3.2a2.25 2.25 0 0 1 1.59.66l1.05 1.05c.28.28.66.44 1.06.44H18A2.25 2.25 0 0 1 20.25 8.9v7.6A2.25 2.25 0 0 1 18 18.75H6A2.25 2.25 0 0 1 3.75 16.5v-9.75Z"></path>
                    </svg>
                </button>
            `;
        }

        function setActiveFolder(scope, folderId = null) {
            if (scope === 'folder' && folderId) {
                expandFolderAncestors(folderId);
                markFoldersRecentlyUsed([folderId], { render: false });
            }
            currentFolderScope = scope;
            currentFolderId = scope === 'folder' ? folderId : null;
            renderFolderNavigation();
            fetchItems();
            // Reload graph if graph view is active
            if (currentView === 'graph') {
                _graphLoaded = false;
                if (typeof initGraph === 'function') initGraph();
            }
        }

        function persistCollapsedFolderIds() {
            localStorage.setItem('collapsedFolderIds', JSON.stringify([...collapsedFolderIds]));
        }

        function hasFolderChildren(folderId) {
            return foldersData.some((entry) => entry.parent_id === folderId);
        }

        function expandFolderAncestors(folderId) {
            let current = getFolderById(folderId);
            let changed = false;
            while (current && current.parent_id) {
                if (collapsedFolderIds.has(current.parent_id)) {
                    collapsedFolderIds.delete(current.parent_id);
                    changed = true;
                }
                current = getFolderById(current.parent_id);
            }
            if (changed) {
                persistCollapsedFolderIds();
            }
            return changed;
        }

        function handleFolderNavActivate(scope, folderId = null) {
            if (scope !== 'folder' || !folderId) {
                setActiveFolder(scope, folderId);
                return;
            }

            const folder = getFolderById(folderId);
            if (!folder) {
                setActiveFolder(scope, folderId);
                return;
            }

            const isActive = currentFolderScope === 'folder' && currentFolderId === folderId;
            const isMainFolder = !folder.parent_id;
            const hasChildren = hasFolderChildren(folderId);
            const isCollapsed = collapsedFolderIds.has(folderId);
            if (isMainFolder && hasChildren) {
                if (isCollapsed) {
                    collapsedFolderIds.delete(folderId);
                    persistCollapsedFolderIds();
                    setActiveFolder(scope, folderId);
                    return;
                }
                collapsedFolderIds.add(folderId);
                persistCollapsedFolderIds();
                setActiveFolder(scope, folderId);
                return;
            }

            if (isActive) return;
            setActiveFolder(scope, folderId);
        }

        function renderFolderNavItem(label, scope, count, folderId = null, options = {}) {
            const active = currentFolderScope === scope && (scope !== 'folder' || currentFolderId === folderId);
            const isMainFolder = scope === 'folder' && (options.level || 0) === 0 && Boolean(options.hasChildren);
            const scopeClass = scope === 'favorites'
                ? ' is-favorites-scope'
                : (scope === 'unread' ? ' is-unread-scope' : '');
            const menuButton = options.menu
                ? `<button class="folder-item-menu" type="button" onclick="openFolderContextMenu('${folderId}', event)">···</button>`
                : '';
            const glyph = getFolderGlyph(label, scope);
            const level = options.level || 0;
            const indent = level * 20;
            const contextMenuAttr = scope === 'folder' ? ` oncontextmenu="event.preventDefault();openFolderContextMenu('${folderId}', event)"` : '';
            const dragAttrs = scope === 'folder'
                ? ` draggable="true" data-folder-id="${folderId}" data-folder-scope="${scope}" ondragstart="handleFolderDragStart(event, '${folderId}')" ondragend="handleFolderDragEnd()" ondragover="handleFolderDragOver(event, '${folderId}')" ondragleave="handleFolderDragLeave(event, '${folderId}')" ondrop="handleFolderDrop(event, '${folderId}')"`
                : ` data-folder-scope="${scope}"`;
            return `
                <div class="folder-item${scopeClass}${active ? ' active' : ''}${isMainFolder ? ' is-main-folder' : ''}" role="button" tabindex="0" title="${escapeAttribute(label)}" style="${indent ? `padding-left:${12 + indent}px` : ''}" onclick="handleFolderNavActivate('${scope}', ${folderId ? `'${folderId}'` : 'null'})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();handleFolderNavActivate('${scope}', ${folderId ? `'${folderId}'` : 'null'});}"${dragAttrs}${contextMenuAttr}>
                    <span class="folder-item-glyph" aria-hidden="true"><span>${escapeHtml(glyph)}</span></span>
                    <span class="folder-item-name">${escapeHtml(label)}</span>
                    <span class="folder-item-count">${count}</span>
                    ${menuButton}
                </div>
            `;
        }

        function toggleFolderCollapse(folderId) {
            if (collapsedFolderIds.has(folderId)) {
                collapsedFolderIds.delete(folderId);
            } else {
                collapsedFolderIds.add(folderId);
            }
            persistCollapsedFolderIds();
            renderFolderNavigation();
        }

        function buildFolderTree(folders) {
            const byParent = {};
            for (const f of folders) {
                const pid = f.parent_id || '__root__';
                if (!byParent[pid]) byParent[pid] = [];
                byParent[pid].push(f);
            }
            const getUsageTimestamp = createFolderUsageTimestampGetter(folders);
            function collect(parentId, level) {
                const children = sortFoldersForNavigation(byParent[parentId] || [], getUsageTimestamp);
                const result = [];
                for (const f of children) {
                    const hasChildren = (byParent[f.id] || []).length > 0;
                    result.push({ ...f, _level: level, _hasChildren: hasChildren });
                    if (hasChildren && !collapsedFolderIds.has(f.id)) {
                        result.push(...collect(f.id, level + 1));
                    }
                }
                return result;
            }
            return collect('__root__', 0);
        }

        function updateSidebarState() {
            document.body.classList.toggle('sidebar-collapsed', !sidebarExpanded);
            const toggleLabel = sidebarExpanded ? '收起侧边栏' : '展开侧边栏';
            toggleSidebarBtn.title = toggleLabel;
            toggleSidebarBtn.setAttribute('aria-label', toggleLabel);
        }

        function getFolderGlyph(label, scope) {
            if (scope === 'all') return '全';
            if (scope === 'favorites') return '藏';
            if (scope === 'unread') return '未';
            const normalized = String(label || '').trim();
            if (!normalized) return '文';
            return normalized[0].toUpperCase();
        }

        function renderFolderNavigation() {
            const normalizedQuery = folderSearchQuery.trim().toLowerCase();
            const treeItems = buildFolderTree(foldersData);
            const flatFolderItems = sortFoldersForNavigation(
                foldersData,
                createFolderUsageTimestampGetter(foldersData)
            );
            const allItems = [
                { label: '全部内容', scope: 'all', count: totalFolderCount, _level: 0, _hasChildren: false },
                { label: '收藏夹', scope: 'favorites', count: favoriteFolderCount, _level: 0, _hasChildren: false },
                { label: '未读', scope: 'unread', count: unreadFolderCount, _level: 0, _hasChildren: false },
                ...treeItems.map((f) => ({
                    label: f.name,
                    scope: 'folder',
                    count: f.item_count || 0,
                    id: f.id,
                    _level: f._level,
                    _hasChildren: f._hasChildren,
                })),
            ];
            const visibleItems = allItems.filter((entry) => {
                if (!normalizedQuery) return true;
                return String(entry.label || '').toLowerCase().includes(normalizedQuery);
            });

            let html = visibleItems.length
                ? visibleItems.map((entry) => renderFolderNavItem(entry.label, entry.scope, entry.count, entry.id || null, { menu: entry.scope === 'folder', level: entry._level, hasChildren: entry._hasChildren })).join('')
                : '<div class="folder-empty">没有匹配的文件夹</div>';

            // Tags section
            html += renderTagsSidebarSection();

            folderList.innerHTML = html;

            const mobileItems = [
                { label: '全部', scope: 'all', count: totalFolderCount },
                { label: '收藏夹', scope: 'favorites', count: favoriteFolderCount },
                { label: '未读', scope: 'unread', count: unreadFolderCount },
                ...flatFolderItems.map((folder) => ({ label: folder.name, scope: 'folder', count: folder.item_count || 0, id: folder.id })),
            ];
            folderMobileStrip.innerHTML = mobileItems.map((item) => {
                const active = currentFolderScope === item.scope && (item.scope !== 'folder' || currentFolderId === item.id);
                const scopeClass = item.scope === 'favorites'
                    ? ' folder-chip--favorites'
                    : (item.scope === 'unread' ? ' folder-chip--unread' : '');
                const folderId = item.id ? `'${item.id}'` : 'null';
                return `<button class="folder-chip${scopeClass}${active ? ' active' : ''}" type="button" onclick="setActiveFolder('${item.scope}', ${folderId})">${escapeHtml(item.label)} · ${item.count}</button>`;
            }).join('') + '<button class="folder-chip" type="button" onclick="openCreateFolderPrompt()">+ 新建</button>';
        }

        function renderTagsSidebarSection() {
            if (!tagsData || !tagsData.length) return '';
            const pills = tagsData.map(t => {
                const active = currentTagId === t.id;
                return `<span class="sidebar-tag-pill${active ? ' active' : ''}" onclick="event.stopPropagation();setActiveTag('${t.id}')" title="${escapeAttribute(t.name)}"><span class="sidebar-tag-label">${escapeHtml(t.name)}</span><span class="sidebar-tag-count">${t.item_count || 0}</span></span>`;
            }).join('');
            return `<div class="sidebar-tags-section"><div class="sidebar-tags-header">标签</div><div class="sidebar-tags-cloud">${pills}</div></div>`;
        }

        function renderTagsInSidebar() {
            renderFolderNavigation();
        }

        function setActiveTag(tagId) {
            if (currentTagId === tagId) {
                currentTagId = null;
            } else {
                currentTagId = tagId;
            }
            tagFilter.value = currentTagId || '';
            if (typeof syncToolbarFilterLabels === 'function') syncToolbarFilterLabels();
            renderFolderNavigation();
            fetchItems();
        }

        function setFolderReorderArmed(isArmed) {
            folderReorderArmed = Boolean(isArmed);
            document.body.classList.toggle('folder-reorder-armed', folderReorderArmed);
        }

        function clearFolderDropIndicator() {
            if (!currentFolderDropTargetId) {
                currentFolderDropMode = '';
                return;
            }
            const previousTarget = folderList.querySelector(`.folder-item[data-folder-id="${currentFolderDropTargetId}"]`);
            previousTarget?.classList.remove('is-drop-target', 'is-drop-before', 'is-drop-after', 'is-drop-inside');
            currentFolderDropTargetId = null;
            currentFolderDropMode = '';
        }

        function updateFolderDropIndicator(folderId, mode, element) {
            if (!folderId || !element) return;
            if (currentFolderDropTargetId === folderId && currentFolderDropMode === mode) return;
            clearFolderDropIndicator();
            currentFolderDropTargetId = folderId;
            currentFolderDropMode = mode;
            element.classList.add('is-drop-target');
            if (mode === 'before') {
                element.classList.add('is-drop-before');
            } else if (mode === 'after') {
                element.classList.add('is-drop-after');
            } else {
                element.classList.add('is-drop-inside');
            }
        }

        function hasDragDataType(event, dataType) {
            const dragTypes = event?.dataTransfer?.types;
            if (!dragTypes) return false;
            if (typeof dragTypes.includes === 'function') return dragTypes.includes(dataType);
            if (typeof dragTypes.contains === 'function') return dragTypes.contains(dataType);
            return Array.from(dragTypes).includes(dataType);
        }

        function hasFolderListDragPayload(event) {
            return Boolean(
                draggedLibraryItemId
                || draggedLibraryItemIds.length
                || draggedFolderId
                || hasDragDataType(event, ITEM_DRAG_DATA_TYPE)
                || hasDragDataType(event, ITEM_MULTI_DRAG_DATA_TYPE)
                || hasDragDataType(event, FOLDER_DRAG_DATA_TYPE)
            );
        }

        function stopFolderListAutoScroll() {
            folderListAutoScrollSpeed = 0;
            if (folderListAutoScrollFrame) {
                window.cancelAnimationFrame(folderListAutoScrollFrame);
                folderListAutoScrollFrame = null;
            }
        }

        function runFolderListAutoScroll() {
            if (!folderListAutoScrollSpeed) {
                folderListAutoScrollFrame = null;
                return;
            }
            folderList.scrollTop += folderListAutoScrollSpeed;
            folderListAutoScrollFrame = window.requestAnimationFrame(runFolderListAutoScroll);
        }

        function updateFolderListAutoScroll(event) {
            if (!folderList || !hasFolderListDragPayload(event)) {
                stopFolderListAutoScroll();
                return;
            }

            const rect = folderList.getBoundingClientRect();
            const insideHorizontalBounds = event.clientX >= rect.left - 24 && event.clientX <= rect.right + 24;
            if (!insideHorizontalBounds || event.clientY < rect.top || event.clientY > rect.bottom) {
                stopFolderListAutoScroll();
                return;
            }

            const topDistance = event.clientY - rect.top;
            const bottomDistance = rect.bottom - event.clientY;
            let nextSpeed = 0;
            if (topDistance < FOLDER_LIST_AUTOSCROLL_EDGE_PX) {
                const intensity = 1 - Math.max(0, topDistance) / FOLDER_LIST_AUTOSCROLL_EDGE_PX;
                nextSpeed = -Math.max(4, Math.round(intensity * FOLDER_LIST_AUTOSCROLL_MAX_SPEED));
            } else if (bottomDistance < FOLDER_LIST_AUTOSCROLL_EDGE_PX) {
                const intensity = 1 - Math.max(0, bottomDistance) / FOLDER_LIST_AUTOSCROLL_EDGE_PX;
                nextSpeed = Math.max(4, Math.round(intensity * FOLDER_LIST_AUTOSCROLL_MAX_SPEED));
            }

            folderListAutoScrollSpeed = nextSpeed;
            if (nextSpeed && !folderListAutoScrollFrame) {
                folderListAutoScrollFrame = window.requestAnimationFrame(runFolderListAutoScroll);
            } else if (!nextSpeed) {
                stopFolderListAutoScroll();
            }
        }

        function handleFolderListDragOver(event) {
            if (!hasFolderListDragPayload(event)) return;
            event.preventDefault();
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
            updateFolderListAutoScroll(event);
        }

        function handleFolderListDragLeave(event) {
            const nextTarget = event.relatedTarget;
            if (nextTarget && folderList.contains(nextTarget)) return;
            stopFolderListAutoScroll();
        }

        function getFolderById(folderId) {
            return foldersData.find((entry) => entry.id === folderId) || null;
        }

        function normalizeFolderParentId(parentId) {
            return parentId ? String(parentId).trim() || null : null;
        }

        function getSiblingFolderIds(parentId = null) {
            const normalizedParentId = normalizeFolderParentId(parentId);
            return foldersData
                .filter((folder) => normalizeFolderParentId(folder.parent_id) === normalizedParentId)
                .map((folder) => folder.id);
        }

        function isFolderDescendant(folderId, ancestorId) {
            let current = getFolderById(folderId);
            const visited = new Set();
            while (current && current.parent_id) {
                if (current.parent_id === ancestorId) return true;
                if (visited.has(current.parent_id)) break;
                visited.add(current.parent_id);
                current = getFolderById(current.parent_id);
            }
            return false;
        }

        function canDropFolderInside(sourceFolderId, targetFolderId) {
            const targetFolder = getFolderById(targetFolderId);
            if (!targetFolder) return false;
            if (sourceFolderId === targetFolderId) return false;
            if (sourceFolderId && isFolderDescendant(targetFolderId, sourceFolderId)) return false;
            return true;
        }

        function resolveFolderDropMode(event, sourceFolderId, targetFolderId) {
            const targetElement = event?.currentTarget;
            if (!targetElement) return 'inside';

            const targetRect = targetElement.getBoundingClientRect();
            const relY = targetRect.height > 0 ? (event.clientY - targetRect.top) / targetRect.height : 0.5;
            const allowInside = canDropFolderInside(sourceFolderId, targetFolderId);

            if (!allowInside) {
                return relY >= 0.5 ? 'after' : 'before';
            }
            if (relY <= 0.34) return 'before';
            if (relY >= 0.66) return 'after';
            return 'inside';
        }

        function normalizeDraggedItemIds(itemIds = []) {
            return Array.from(new Set(
                (Array.isArray(itemIds) ? itemIds : [itemIds])
                    .map((value) => String(value || '').trim())
                    .filter(Boolean)
            ));
        }

        function getDraggedLibraryItemIdsFromEvent(event) {
            const rawMultiIds = event?.dataTransfer?.getData(ITEM_MULTI_DRAG_DATA_TYPE) || '';
            if (rawMultiIds) {
                try {
                    const parsed = JSON.parse(rawMultiIds);
                    const normalizedIds = normalizeDraggedItemIds(parsed);
                    if (normalizedIds.length) return normalizedIds;
                } catch (error) {
                    console.warn('Failed to parse dragged item ids', error);
                }
            }
            if (draggedLibraryItemIds.length) {
                return normalizeDraggedItemIds(draggedLibraryItemIds);
            }
            return normalizeDraggedItemIds(event?.dataTransfer?.getData(ITEM_DRAG_DATA_TYPE) || draggedLibraryItemId);
        }

        async function moveItemsToFolder(itemIds, folderId) {
            const normalizedItemIds = normalizeDraggedItemIds(itemIds);
            const folder = getFolderById(folderId);
            if (!normalizedItemIds.length || !folder) return;

            const targetItems = normalizedItemIds.map((itemId) => getItemById(itemId)).filter(Boolean);
            const updatedItems = targetItems.map((item) => {
                const existingFolderIds = Array.isArray(item.folder_ids) ? item.folder_ids.filter(Boolean) : [];
                return buildLocallyUpdatedFolderItem(item, [folderId, ...existingFolderIds.filter((entry) => entry !== folderId)]);
            });
            const hasAnyChange = updatedItems.some((item, index) => {
                const previousItem = targetItems[index];
                const previousFolderIds = Array.isArray(previousItem?.folder_ids) ? previousItem.folder_ids.filter(Boolean) : [];
                return JSON.stringify(item.folder_ids || []) !== JSON.stringify(previousFolderIds);
            });
            if (!hasAnyChange) {
                showToast(`已在文件夹「${folder.name}」中`, 'info');
                return;
            }

            if (normalizedItemIds.length === 1) {
                const item = targetItems[0];
                const response = await fetch(`/api/items/${normalizedItemIds[0]}/folder`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ folder_ids: updatedItems[0]?.folder_ids || [] }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || '拖入文件夹失败');
                }
                applyLocalFolderSnapshots([data?.id ? data : updatedItems[0]]);
            } else {
                const response = await fetch('/api/items/bulk-folder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        item_ids: normalizedItemIds,
                        folder_ids: [folderId],
                        append: true,
                    }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || '批量拖入文件夹失败');
                }
                applyLocalFolderSnapshots(updatedItems);
            }

            if (typeof clearLibraryItemSelection === 'function') {
                clearLibraryItemSelection({ render: true });
            }
            showToast(
                normalizedItemIds.length > 1
                    ? `已将 ${normalizedItemIds.length} 条内容放入「${folder.name}」`
                    : `已放入「${folder.name}」`,
                'success'
            );
            markFoldersRecentlyUsed([folderId], { render: false });
            await fetchFolders();
        }

        function buildReorderedFolderIds(sourceFolderId, targetFolderId, dropMode, parentId = null) {
            const orderedFolderIds = getSiblingFolderIds(parentId);
            const sourceIndex = orderedFolderIds.indexOf(sourceFolderId);
            const targetIndex = orderedFolderIds.indexOf(targetFolderId);
            if (targetIndex === -1 || sourceFolderId === targetFolderId) {
                return orderedFolderIds;
            }

            if (sourceIndex !== -1) {
                orderedFolderIds.splice(sourceIndex, 1);
            }
            const adjustedTargetIndex = orderedFolderIds.indexOf(targetFolderId);
            const insertionIndex = dropMode === 'after' ? adjustedTargetIndex + 1 : adjustedTargetIndex;
            orderedFolderIds.splice(Math.max(0, insertionIndex), 0, sourceFolderId);
            return orderedFolderIds;
        }

        async function moveFolderToParent(folderId, parentId = null, options = {}) {
            const { silent = false } = options;
            const folder = getFolderById(folderId);
            const normalizedParentId = normalizeFolderParentId(parentId);
            if (!folder) return false;
            if (normalizeFolderParentId(folder.parent_id) === normalizedParentId) {
                return false;
            }

            const response = await fetch(`/api/folders/${folderId}/parent`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ parent_id: normalizedParentId }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.detail || '移动文件夹失败');
            }

            if (!silent) {
                const parentFolder = normalizedParentId ? getFolderById(normalizedParentId) : null;
                showToast(parentFolder ? `已放入「${parentFolder.name}」` : '已移到顶层', 'success');
            }
            return true;
        }

        async function moveFolderInside(sourceFolderId, targetFolderId) {
            const targetFolder = getFolderById(targetFolderId);
            if (!targetFolder) return;
            const moved = await moveFolderToParent(sourceFolderId, targetFolderId, { silent: true });
            if (!moved) {
                showToast(`已在「${targetFolder.name}」下`, 'info');
                return;
            }
            showToast(`已放入「${targetFolder.name}」`, 'success');
            await fetchFolders();
        }

        async function reorderFolderPosition(sourceFolderId, targetFolderId, dropMode) {
            const targetFolder = getFolderById(targetFolderId);
            const sourceFolder = getFolderById(sourceFolderId);
            if (!targetFolder || !sourceFolder) return;

            const targetParentId = normalizeFolderParentId(targetFolder.parent_id);
            const movedParent = await moveFolderToParent(sourceFolderId, targetParentId, { silent: true });
            const nextFolderIds = buildReorderedFolderIds(sourceFolderId, targetFolderId, dropMode, targetParentId);
            const currentFolderIds = getSiblingFolderIds(targetParentId);
            if (!movedParent && JSON.stringify(nextFolderIds) === JSON.stringify(currentFolderIds)) return;

            const response = await fetch('/api/folders/reorder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder_ids: nextFolderIds, parent_id: targetParentId }),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || '文件夹排序失败');
            }

            const parentFolder = targetParentId ? getFolderById(targetParentId) : null;
            showToast(
                movedParent
                    ? (parentFolder ? `已移到「${parentFolder.name}」下` : '已移到顶层')
                    : '文件夹顺序已更新',
                'success'
            );
            await fetchFolders();
        }

        function handleFolderDragStart(event, folderId) {
            if (!event.dataTransfer) return;
            draggedFolderId = folderId;
            document.body.classList.add('folder-reordering');
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData(FOLDER_DRAG_DATA_TYPE, folderId);
            event.dataTransfer.setData('text/plain', folderId);
        }

        function handleFolderDragEnd() {
            draggedFolderId = null;
            document.body.classList.remove('folder-reordering');
            clearFolderDropIndicator();
            stopFolderListAutoScroll();
        }

        function handleFolderDragOver(event, folderId) {
            const hasItemDrag = Boolean(draggedLibraryItemId || draggedLibraryItemIds.length || hasDragDataType(event, ITEM_DRAG_DATA_TYPE) || hasDragDataType(event, ITEM_MULTI_DRAG_DATA_TYPE));
            const hasFolderDrag = Boolean(draggedFolderId || hasDragDataType(event, FOLDER_DRAG_DATA_TYPE));
            if (!hasItemDrag && !hasFolderDrag) return;
            if (hasFolderDrag && draggedFolderId === folderId) return;

            event.preventDefault();
            updateFolderListAutoScroll(event);
            const targetElement = event.currentTarget;
            if (hasFolderDrag) {
                const sourceFolderId = draggedFolderId || event.dataTransfer?.getData(FOLDER_DRAG_DATA_TYPE) || '';
                const dropMode = resolveFolderDropMode(event, sourceFolderId, folderId);
                updateFolderDropIndicator(folderId, dropMode, targetElement);
                event.dataTransfer.dropEffect = 'move';
                return;
            }

            updateFolderDropIndicator(folderId, 'inside', targetElement);
            event.dataTransfer.dropEffect = 'move';
        }

        function handleFolderDragLeave(event, folderId) {
            const nextTarget = event.relatedTarget;
            if (nextTarget && event.currentTarget.contains(nextTarget)) return;
            if (currentFolderDropTargetId === folderId) {
                clearFolderDropIndicator();
            }
        }

        async function handleFolderDrop(event, folderId) {
            event.preventDefault();
            const droppedItemIds = getDraggedLibraryItemIdsFromEvent(event);
            const droppedFolderId = event.dataTransfer?.getData(FOLDER_DRAG_DATA_TYPE) || draggedFolderId;
            const dropMode = droppedFolderId
                ? resolveFolderDropMode(event, droppedFolderId, folderId)
                : (currentFolderDropMode || 'inside');
            clearFolderDropIndicator();

            try {
                if (droppedItemIds.length) {
                    await moveItemsToFolder(droppedItemIds, folderId);
                    return;
                }
                if (droppedFolderId && droppedFolderId !== folderId) {
                    if (dropMode === 'inside') {
                        await moveFolderInside(droppedFolderId, folderId);
                        return;
                    }
                    await reorderFolderPosition(droppedFolderId, folderId, dropMode === 'after' ? 'after' : 'before');
                }
            } catch (error) {
                showToast(error.message, 'error');
            } finally {
                draggedLibraryItemId = null;
                draggedLibraryItemIds = [];
                draggedFolderId = null;
                stopFolderListAutoScroll();
                document.body.classList.remove('item-dragging', 'folder-reordering');
                if (typeof clearItemDragPreview === 'function') {
                    clearItemDragPreview();
                }
            }
        }

        async function fetchFolders() {
            try {
                const response = await fetch('/api/folders');
                if (!response.ok) throw new Error('API Error');
                const data = await response.json();
                foldersData = Array.isArray(data.folders) ? data.folders : [];
                totalFolderCount = Number(data.total_count || 0);
                unfiledFolderCount = Number(data.unfiled_count || 0);
                favoriteFolderCount = Number(data.favorite_count || 0);
                unreadFolderCount = Number(data.unread_count || 0);
                pruneFolderPreferences();
                if (mobileCaptureSelectedFolderIds.length) {
                    mobileCaptureSelectedFolderIds = mobileCaptureSelectedFolderIds.filter((folderId) => foldersData.some((folder) => folder.id === folderId));
                    persistMobileCaptureSelectedFolder();
                }
                if (currentFolderScope === 'unfiled') {
                    currentFolderScope = 'all';
                    currentFolderId = null;
                }
                if (currentFolderScope === 'folder' && currentFolderId && !foldersData.some((folder) => folder.id === currentFolderId)) {
                    currentFolderScope = 'all';
                    currentFolderId = null;
                }
                renderFolderNavigation();
                updateMobileCaptureFolderSummary();
                fetchTags();
            } catch (error) {
                folderList.innerHTML = '<div class="folder-loading">文件夹加载失败</div>';
                folderMobileStrip.innerHTML = '';
                updateMobileCaptureFolderSummary();
            }
        }

        async function createFolder(name, parentId = null) {
            const trimmedName = String(name || '').trim();
            if (!trimmedName) return null;
            const body = { name: trimmedName };
            if (parentId) body.parent_id = parentId;
            const response = await fetch('/api/folders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.detail || '创建文件夹失败');
            }
            await fetchFolders();
            if (data?.id) {
                markFoldersRecentlyUsed([data.id], { render: true });
            }
            return data;
        }

        function populateParentFolderSelect(preselectId) {
            let html = '<option value="">顶层文件夹</option>';
            const orderedFolders = buildFolderTree(foldersData);
            for (const f of orderedFolders) {
                const selected = f.id === preselectId ? ' selected' : '';
                const prefix = f._level > 0 ? `${'　'.repeat(f._level)}└ ` : '';
                html += `<option value="${f.id}"${selected}>${escapeHtml(prefix + f.name)}</option>`;
            }
            folderPickerParentSelect.innerHTML = html;
        }

        function openCreateFolderPrompt(preselectParentId) {
            folderPickerContext = 'create';
            folderCreateInput.value = '';
            folderPickerTargetIds = [];
            folderPickerSelectedIds = new Set(currentFolderScope === 'folder' && currentFolderId ? [currentFolderId] : []);
            folderPickerTitle.textContent = '新建文件夹';
            folderCreateConfirmBtn.textContent = '立即新建';
            populateParentFolderSelect(preselectParentId || null);
            folderPickerParentRow.style.display = '';
            folderPickerSectionTitle.style.display = '';
            renderFolderPickerOptions();
            folderPickerOverlay.classList.add('active');
            requestAnimationFrame(() => folderCreateInput.focus());
        }

        function getSharedFolderIds(itemIds = []) {
            const targets = itemIds
                .map((itemId) => itemsData.find((item) => item.id === itemId))
                .filter(Boolean);
            if (!targets.length) return [];
            const [firstTarget, ...restTargets] = targets;
            const baseFolderIds = Array.isArray(firstTarget.folder_ids) ? firstTarget.folder_ids.filter(Boolean) : [];
            return baseFolderIds.filter((folderId) => (
                restTargets.every((item) => Array.isArray(item.folder_ids) && item.folder_ids.includes(folderId))
            ));
        }

        function getFolderPickerMode() {
            return folderPickerContext;
        }

        function openFolderPicker(itemIds = [], preferredFolderIds = [], title = '加入文件夹') {
            folderPickerContext = 'assign';
            folderPickerTargetIds = Array.isArray(itemIds) ? itemIds.filter(Boolean) : [];
            const nextSelectedIds = Array.isArray(preferredFolderIds) && preferredFolderIds.length
                ? preferredFolderIds.filter(Boolean)
                : getSharedFolderIds(folderPickerTargetIds);
            folderPickerSelectedIds = new Set(nextSelectedIds);
            folderPickerTitle.textContent = title;
            folderCreateInput.value = '';
            folderCreateConfirmBtn.textContent = folderPickerTargetIds.length > 0 ? '新建并选中' : '立即新建';
            folderPickerParentRow.style.display = 'none';
            folderPickerSectionTitle.style.display = '';
            renderFolderPickerOptions();
            folderPickerOverlay.classList.add('active');
            requestAnimationFrame(() => folderCreateInput.focus());
        }

        function persistMobileCaptureSelectedFolder() {
            try {
                if (mobileCaptureSelectedFolderIds.length) {
                    window.localStorage.setItem(MOBILE_CAPTURE_SELECTED_FOLDER_STORAGE_KEY, JSON.stringify(mobileCaptureSelectedFolderIds));
                } else {
                    window.localStorage.removeItem(MOBILE_CAPTURE_SELECTED_FOLDER_STORAGE_KEY);
                }
            } catch (error) {
                console.warn('Failed to persist mobile capture folder selection', error);
            }
        }

        function updateMobileCaptureFolderSummary() {
            if (!mobileFolderSelection || !mobileFolderPickerBtn) return;
            const selectedFolders = foldersData.filter((folder) => mobileCaptureSelectedFolderIds.includes(folder.id));
            mobileFolderSelection.textContent = selectedFolders.length
                ? `当前：${selectedFolders.map((folder) => folder.name).join('、')}`
                : '当前：不指定文件夹';
            mobileFolderPickerBtn.textContent = selectedFolders.length ? '更换文件夹' : '选择文件夹';
        }

        async function openMobileCaptureFolderPicker(options = {}) {
            const {
                submitAfterSelection = false,
                pendingText = '',
            } = options;

            folderPickerContext = submitAfterSelection ? 'mobile-capture-submit' : 'mobile-capture';
            folderPickerTargetIds = [];
            folderPickerSelectedIds = new Set(mobileCaptureSelectedFolderIds);
            pendingMobileCaptureSubmission = submitAfterSelection ? {
                text: String(pendingText || '').trim(),
            } : null;
            folderPickerTitle.textContent = submitAfterSelection ? '选择收录文件夹' : '手机端存入文件夹';
            folderCreateInput.value = '';
            folderCreateConfirmBtn.textContent = submitAfterSelection ? '新建并收录' : '新建并使用';
            folderPickerParentRow.style.display = 'none';
            folderPickerSectionTitle.style.display = '';
            folderPickerOverlay.classList.add('active');
            requestAnimationFrame(() => folderCreateInput.focus());

            if (!foldersData.length) {
                folderPickerList.innerHTML = '<div class="folder-picker-empty">正在加载文件夹...</div>';
                updateFolderPickerStatus();
                await fetchFolders();
                if (!folderPickerOverlay.classList.contains('active')) return;
                if (!['mobile-capture', 'mobile-capture-submit'].includes(folderPickerContext)) return;
            }

            renderFolderPickerOptions();
        }

        function closeFolderPickerDialog() {
            folderPickerOverlay.classList.remove('active');
            folderPickerContext = 'assign';
            folderPickerTargetIds = [];
            folderPickerSelectedIds = new Set();
            folderCreateInput.value = '';
            pendingMobileCaptureSubmission = null;
            folderPickerActionInFlight = false;
            folderPickerApplyBtn.disabled = false;
            folderPickerClearBtn.disabled = false;
            folderCreateConfirmBtn.disabled = false;
            folderPickerParentRow.style.display = 'none';
            folderPickerSectionTitle.style.display = '';
            folderPickerHint.textContent = '选择文件夹后完成保存';
        }

        function setFolderPickerActionState(isBusy) {
            folderPickerActionInFlight = Boolean(isBusy);
            folderPickerApplyBtn.disabled = Boolean(isBusy);
            folderCreateConfirmBtn.disabled = Boolean(isBusy);
            if (folderPickerClearBtn.hidden) {
                folderPickerClearBtn.disabled = Boolean(isBusy);
                return;
            }
            const hasSelection = folderPickerSelectedIds.size > 0;
            folderPickerClearBtn.disabled = Boolean(isBusy) || !hasSelection;
        }

        function updateFolderPickerStatus() {
            const mode = getFolderPickerMode();
            const selectedFolders = foldersData.filter((folder) => folderPickerSelectedIds.has(folder.id));
            const selectedNames = selectedFolders.map((folder) => folder.name);
            const isMobileCaptureMode = mode === 'mobile-capture' || mode === 'mobile-capture-submit';
            folderPickerStatus.classList.toggle('is-centered', isMobileCaptureMode);
            if (mode === 'assign') {
                folderPickerHint.textContent = folderPickerTargetIds.length > 1
                    ? `当前将同时更新 ${folderPickerTargetIds.length} 条内容，可多选文件夹。`
                    : '当前内容可加入多个文件夹，支持多选。';
                folderPickerStatus.textContent = selectedNames.length
                    ? `已选 ${selectedNames.length} 个文件夹：${selectedNames.join('、')}`
                    : '未选择文件夹，保存后将从所有文件夹中移除。';
                folderPickerClearBtn.hidden = false;
                folderPickerApplyBtn.hidden = false;
                folderPickerApplyBtn.textContent = '完成保存';
                folderPickerClearBtn.disabled = folderPickerActionInFlight || selectedNames.length === 0;
                return;
            }

            if (mode === 'mobile-capture') {
                folderPickerHint.textContent = '为手机端新收录内容选择默认文件夹，可以多选，也可以留空。';
                folderPickerStatus.textContent = selectedNames.length
                    ? `默认存入 ${selectedNames.length} 个文件夹：${selectedNames.join('、')}`
                    : '当前不指定文件夹';
                folderPickerClearBtn.hidden = false;
                folderPickerApplyBtn.hidden = false;
                folderPickerClearBtn.textContent = '不指定文件夹';
                folderPickerApplyBtn.textContent = '保存选择';
                folderPickerClearBtn.disabled = folderPickerActionInFlight || selectedNames.length === 0;
                return;
            }

            if (mode === 'mobile-capture-submit') {
                folderPickerHint.textContent = '这次收录前先选文件夹，可以多选，也可以直接不指定。';
                folderPickerStatus.textContent = selectedNames.length
                    ? `本次收录将存入 ${selectedNames.length} 个文件夹：${selectedNames.join('、')}`
                    : '本次收录不指定文件夹';
                folderPickerClearBtn.hidden = false;
                folderPickerApplyBtn.hidden = false;
                folderPickerClearBtn.textContent = '不指定文件夹';
                folderPickerApplyBtn.textContent = '确认并收录';
                folderPickerClearBtn.disabled = folderPickerActionInFlight || selectedNames.length === 0;
                return;
            }

            folderPickerHint.textContent = '输入名称可直接创建；点现有文件夹可快速切换。';
            folderPickerStatus.textContent = selectedNames.length
                ? `当前高亮：${selectedNames.join('、')}`
                : '新建后会保持在当前内容列表。';
            folderPickerClearBtn.hidden = true;
            folderPickerApplyBtn.hidden = true;
            folderPickerClearBtn.textContent = '清空选择';
            folderPickerApplyBtn.textContent = '完成';
        }

        function renderFolderPickerOptions() {
            const mode = getFolderPickerMode();
            const orderedFolders = sortFoldersForNavigation(
                foldersData,
                createFolderUsageTimestampGetter(foldersData)
            );
            const options = orderedFolders.map((folder) => ({ id: folder.id, label: folder.name, count: folder.item_count || 0 }));
            folderPickerList.innerHTML = options.length ? options.map((option) => {
                const active = folderPickerSelectedIds.has(option.id);
                return `
                    <button class="folder-picker-option${active ? ' active' : ''}" type="button" onclick="toggleFolderPickerSelection('${option.id}')">
                        <span class="folder-picker-option-main">
                            <span class="folder-picker-option-label">${escapeHtml(option.label)}</span>
                            <span class="folder-picker-option-subtitle">${mode === 'assign'
                                ? '点击切换当前选择'
                                : mode === 'mobile-capture' || mode === 'mobile-capture-submit'
                                    ? '点击切换本次选择'
                                    : '点击切换到这个文件夹'}</span>
                        </span>
                        <span class="folder-picker-option-side">
                            <span class="folder-picker-option-meta">${option.count} 条</span>
                            <span class="folder-picker-check">${checkSvg()}</span>
                        </span>
                    </button>
                `;
            }).join('') : '<div class="folder-picker-empty">还没有文件夹。先在上面输入名称创建一个。</div>';
            updateFolderPickerStatus();
        }

        function toggleFolderPickerSelection(folderId) {
            const mode = getFolderPickerMode();
            if (mode === 'create') {
                folderPickerSelectedIds = new Set(folderId ? [folderId] : []);
                renderFolderPickerOptions();
                closeFolderPickerDialog();
                setActiveFolder('folder', folderId);
                return;
            }

            if (mode === 'mobile-capture') {
                if (folderPickerSelectedIds.has(folderId)) {
                    folderPickerSelectedIds.delete(folderId);
                } else {
                    folderPickerSelectedIds.add(folderId);
                }
                renderFolderPickerOptions();
                return;
            }

            if (mode === 'mobile-capture-submit') {
                if (folderPickerSelectedIds.has(folderId)) {
                    folderPickerSelectedIds.delete(folderId);
                } else {
                    folderPickerSelectedIds.add(folderId);
                }
                renderFolderPickerOptions();
                return;
            }

            if (folderPickerSelectedIds.has(folderId)) {
                folderPickerSelectedIds.delete(folderId);
            } else {
                folderPickerSelectedIds.add(folderId);
            }
            renderFolderPickerOptions();
        }

        async function applyFolderSelection() {
            if (folderPickerActionInFlight) return;
            try {
                setFolderPickerActionState(true);
                const mode = getFolderPickerMode();
                const folderIds = Array.from(folderPickerSelectedIds);
                if (mode === 'mobile-capture') {
                    mobileCaptureSelectedFolderIds = folderIds;
                    persistMobileCaptureSelectedFolder();
                    markFoldersRecentlyUsed(folderIds, { render: false });
                    updateMobileCaptureFolderSummary();
                    closeFolderPickerDialog();
                    showToast(
                        mobileCaptureSelectedFolderIds.length
                            ? `手机端将默认存入：${foldersData.filter((folder) => mobileCaptureSelectedFolderIds.includes(folder.id)).map((folder) => folder.name).join('、') || '已选文件夹'}`
                            : '手机端将不指定文件夹',
                        'success'
                    );
                    return;
                }

                if (mode === 'mobile-capture-submit') {
                    mobileCaptureSelectedFolderIds = folderIds;
                    persistMobileCaptureSelectedFolder();
                    markFoldersRecentlyUsed(folderIds, { render: false });
                    updateMobileCaptureFolderSummary();
                    const submissionText = pendingMobileCaptureSubmission?.text || '';
                    closeFolderPickerDialog();
                    if (submissionText) {
                        mobileCaptureInput.value = submissionText;
                        await submitMobileCapture({ auto: false, skipFolderPrompt: true });
                    }
                    return;
                }

                if (folderPickerTargetIds.length > 1) {
                    const response = await fetch('/api/items/bulk-folder', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ item_ids: folderPickerTargetIds, folder_ids: folderIds }),
                    });
                    const data = await response.json().catch(() => ({}));
                    if (!response.ok) throw new Error(data.detail || '批量归类失败');
                    const updatedItems = folderPickerTargetIds
                        .map((itemId) => getItemById(itemId))
                        .filter(Boolean)
                        .map((item) => buildLocallyUpdatedFolderItem(item, folderIds));
                    applyLocalFolderSnapshots(updatedItems);
                    if (typeof clearLibraryItemSelection === 'function') {
                        clearLibraryItemSelection({ render: true });
                    }
                    showToast(`已整理 ${data.updated_count} 条内容`, 'success');
                } else if (folderPickerTargetIds.length === 1) {
                    const targetItem = getItemById(folderPickerTargetIds[0]);
                    const response = await fetch(`/api/items/${folderPickerTargetIds[0]}/folder`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ folder_ids: folderIds }),
                    });
                    const data = await response.json().catch(() => ({}));
                    if (!response.ok) throw new Error(data.detail || '归类失败');
                    applyLocalFolderSnapshots([data?.id ? data : buildLocallyUpdatedFolderItem(targetItem, folderIds)]);
                    if (typeof clearLibraryItemSelection === 'function') {
                        clearLibraryItemSelection({ render: true });
                    }
                    const toastLabel = Array.isArray(data.folder_names) && data.folder_names.length
                        ? data.folder_names.join('、')
                        : '无文件夹';
                    showToast(`已更新到：${toastLabel}`, 'success');
                } else {
                    closeFolderPickerDialog();
                    return;
                }
                markFoldersRecentlyUsed(folderIds, { render: false });
                closeFolderPickerDialog();
                await fetchFolders();
            } catch (error) {
                setFolderPickerActionState(false);
                showToast(error.message, 'error');
            }
        }

        async function createFolderAndApply() {
            if (folderPickerActionInFlight) return;
            try {
                setFolderPickerActionState(true);
                const mode = getFolderPickerMode();
                const parentId = mode === 'create' ? (folderPickerParentSelect.value || null) : null;
                const folder = await createFolder(folderCreateInput.value, parentId);
                if (!folder) {
                    setFolderPickerActionState(false);
                    return;
                }
                folderCreateInput.value = '';
                if (parentId && collapsedFolderIds.has(parentId)) {
                    collapsedFolderIds.delete(parentId);
                    persistCollapsedFolderIds();
                    renderFolderNavigation();
                }
                if (mode === 'mobile-capture') {
                    folderPickerSelectedIds.add(folder.id);
                    mobileCaptureSelectedFolderIds = Array.from(folderPickerSelectedIds);
                    persistMobileCaptureSelectedFolder();
                    updateMobileCaptureFolderSummary();
                    closeFolderPickerDialog();
                    showToast(`已创建并加入默认文件夹：${folder.name}`, 'success');
                    return;
                }
                if (mode === 'mobile-capture-submit') {
                    folderPickerSelectedIds.add(folder.id);
                    mobileCaptureSelectedFolderIds = Array.from(folderPickerSelectedIds);
                    persistMobileCaptureSelectedFolder();
                    updateMobileCaptureFolderSummary();
                    const submissionText = pendingMobileCaptureSubmission?.text || '';
                    closeFolderPickerDialog();
                    showToast(`已创建文件夹并用于本次收录：${folder.name}`, 'success');
                    if (submissionText) {
                        mobileCaptureInput.value = submissionText;
                        await submitMobileCapture({ auto: false, skipFolderPrompt: true });
                    }
                    return;
                }
                if (folderPickerTargetIds.length > 0) {
                    folderPickerSelectedIds.add(folder.id);
                    renderFolderPickerOptions();
                    showToast(`已创建并选中：${folder.name}`, 'success');
                    return;
                }
                showToast(`已创建文件夹：${folder.name}`, 'success');
                closeFolderPickerDialog();
            } catch (error) {
                setFolderPickerActionState(false);
                showToast(error.message, 'error');
            }
        }

        function getFolderDepth(folderId) {
            let depth = 0;
            let current = foldersData.find(f => f.id === folderId);
            while (current && current.parent_id) {
                depth++;
                current = foldersData.find(f => f.id === current.parent_id);
            }
            return depth;
        }

        function createSubfolderPrompt(parentId) {
            closeFolderContextMenu();
            openCreateFolderPrompt(parentId);
        }

        function openFolderContextMenu(folderId, event) {
            event.stopPropagation();
            const folder = foldersData.find((entry) => entry.id === folderId);
            if (!folder) return;
            const canNest = true;
            const isPinned = isFolderPinned(folderId);
            const pinBtn = `
                <button type="button" onclick="toggleFolderPin('${folderId}')">
                    <span class="folder-context-menu-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none">
                            <path fill="currentColor" d="M12 6.5c0.3199 0 0.6204 0.15337 0.8086 0.41211l4 5.49999c0.2211 0.3042 0.2537 0.7069 0.083 1.042S16.3761 14 16 14h-3v7c0 0.5523 -0.4477 1 -1 1s-1 -0.4477 -1 -1v-7H8c-0.3761 0 -0.72091 -0.2108 -0.8916 -0.5459 -0.17066 -0.3351 -0.13814 -0.7378 0.08301 -1.042l3.99999 -5.49999 0.0752 -0.0918C11.4546 6.61742 11.7199 6.5 12 6.5M17 2c0.5523 0 1 0.44772 1 1s-0.4477 1 -1 1H7c-0.55228 0 -1 -0.44772 -1 -1s0.44772 -1 1 -1z"></path>
                        </svg>
                    </span>
                    <span class="folder-context-menu-copy">${isPinned ? '取消固定' : '固定在顶部'}</span>
                </button>
            `;
            const subfolderBtn = canNest ? `
                <button type="button" onclick="createSubfolderPrompt('${folderId}')">
                    <span class="folder-context-menu-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 5v14M5 12h14"></path>
                        </svg>
                    </span>
                    <span class="folder-context-menu-copy">创建子文件夹</span>
                </button>
            ` : '';
            folderContextMenu.innerHTML = `
                ${pinBtn}
                ${subfolderBtn}
                <button type="button" onclick="renameFolderPrompt('${folderId}')">
                    <span class="folder-context-menu-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 20h9"></path>
                            <path d="m16.5 3.5 4 4L7 21H3v-4L16.5 3.5Z"></path>
                        </svg>
                    </span>
                    <span class="folder-context-menu-copy">重命名</span>
                </button>
                <button type="button" class="is-danger" onclick="deleteFolderPrompt('${folderId}')">
                    <span class="folder-context-menu-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M3 6h18"></path>
                            <path d="M8 6V4h8v2"></path>
                            <path d="m19 6-1 14H6L5 6"></path>
                            <path d="M10 11v6M14 11v6"></path>
                        </svg>
                    </span>
                    <span class="folder-context-menu-copy">删除文件夹</span>
                </button>
            `;
            folderContextMenu.classList.add('show');
            folderContextMenu.style.visibility = 'hidden';

            const menuRect = folderContextMenu.getBoundingClientRect();
            const isContextMenu = event.type === 'contextmenu';
            const trigger = event.currentTarget || event.target;
            const triggerRect = trigger.getBoundingClientRect();
            const desiredTop = isContextMenu ? event.clientY : triggerRect.bottom + 8;
            const desiredLeft = isContextMenu ? event.clientX : triggerRect.right - menuRect.width;
            const maxLeft = window.innerWidth - menuRect.width - 12;
            const maxTop = window.innerHeight - menuRect.height - 12;

            folderContextMenu.style.top = `${Math.max(12, Math.min(desiredTop, maxTop))}px`;
            folderContextMenu.style.left = `${Math.max(12, Math.min(desiredLeft, maxLeft))}px`;
            folderContextMenu.style.visibility = '';
        }

        function closeFolderContextMenu() {
            folderContextMenu.classList.remove('show');
            folderContextMenu.style.visibility = '';
        }

        async function renameFolderPrompt(folderId) {
            closeFolderContextMenu();
            const folder = foldersData.find((entry) => entry.id === folderId);
            if (!folder) return;
            const nextName = window.prompt('重命名文件夹', folder.name);
            if (nextName === null) return;
            try {
                const response = await fetch(`/api/folders/${folderId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: nextName }),
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || '重命名失败');
                showToast('文件夹已重命名', 'success');
                await fetchFolders();
                if (currentFolderId === folderId) {
                    setStatsSummary(
                        latestTotalCount || itemsData.length,
                        latestVisibleCount || itemsData.length,
                        latestReturnedCount || itemsData.length,
                        !!filterInput.value.trim() || platformFilter.value !== 'all' || currentFolderScope !== 'all'
                    );
                }
            } catch (error) {
                showToast(error.message, 'error');
            }
        }

        async function deleteFolderPrompt(folderId) {
            closeFolderContextMenu();
            const folder = foldersData.find((entry) => entry.id === folderId);
            if (!folder) return;
            if (!window.confirm(`删除文件夹“${folder.name}”？已关联的内容会保留，但不再属于这个文件夹。`)) return;
            try {
                const response = await fetch(`/api/folders/${folderId}`, { method: 'DELETE' });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || '删除文件夹失败');
                }
                showToast('文件夹已删除', 'deleted');
                if (currentFolderId === folderId) {
                    currentFolderScope = 'all';
                    currentFolderId = null;
                }
                await Promise.all([fetchFolders(), fetchItems()]);
            } catch (error) {
                showToast(error.message, 'error');
            }
        }
