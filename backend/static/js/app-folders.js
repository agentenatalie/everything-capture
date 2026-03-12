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
            const statsCountLabel = `已收录&nbsp;&nbsp;<strong>${total}</strong>&nbsp;&nbsp;篇内容`;
            stats.classList.remove('is-plain');
            if (hasFilter) {
                if (visible > returned) {
                    stats.innerHTML = `<span class="stats-primary">${statsCountLabel}</span><span class="stats-secondary">匹配 ${visible} 篇，显示最新 ${returned} 篇</span>`;
                    return;
                }
                stats.innerHTML = `<span class="stats-primary">${statsCountLabel}</span><span class="stats-secondary">当前显示 ${visible} 篇</span>`;
                return;
            }
            if (total > returned) {
                stats.innerHTML = `<span class="stats-primary">${statsCountLabel}</span><span class="stats-secondary">当前显示最新 ${returned} 篇</span>`;
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
            if (currentFolderScope === 'folder') {
                const folder = foldersData.find((entry) => entry.id === currentFolderId);
                return folder ? `文件夹：${folder.name}` : '文件夹';
            }
            return '全部内容';
        }

        function handleItemPrimaryAction(itemId) {
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
            if (!folderNames.length) return '';
            return folderNames.slice(0, 3).map((folderName) => (
                `<span class="folder-tag">${folderIconSvg()}<span>${escapeHtml(folderName)}</span></span>`
            )).join('');
        }

        function openFolderPickerForItem(itemId, title = '管理文件夹') {
            const item = itemsData.find((entry) => entry.id === itemId) || commandSearchResults.find((entry) => entry.id === itemId);
            const preferredFolderIds = Array.isArray(item?.folder_ids) ? item.folder_ids : [];
            openFolderPicker([itemId], preferredFolderIds, title);
        }

        function renderFolderActionButton(item) {
            return `
                <button onclick="parseItemContent('${item.id}', event)" class="folder-action-btn" title="解析内容">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M7.5 4.75h6.9l2.85 2.85v11.65H7.5A2.25 2.25 0 0 1 5.25 17V7A2.25 2.25 0 0 1 7.5 4.75Z"></path>
                        <path d="M14.25 4.75V8h3.25"></path>
                        <path d="M9 11h6"></path>
                        <path d="M9 14h6"></path>
                    </svg>
                </button>
            `;
        }

        function setActiveFolder(scope, folderId = null) {
            currentFolderScope = scope;
            currentFolderId = scope === 'folder' ? folderId : null;
            renderFolderNavigation();
            fetchItems();
        }

        function renderFolderNavItem(label, scope, count, folderId = null, options = {}) {
            const active = currentFolderScope === scope && (scope !== 'folder' || currentFolderId === folderId);
            const menuButton = options.menu
                ? `<button class="folder-item-menu" type="button" onclick="openFolderContextMenu('${folderId}', event)">···</button>`
                : '';
            const glyph = getFolderGlyph(label, scope);
            return `
                <div class="folder-item${active ? ' active' : ''}" role="button" tabindex="0" title="${escapeAttribute(label)}" onclick="setActiveFolder('${scope}', ${folderId ? `'${folderId}'` : 'null'})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();setActiveFolder('${scope}', ${folderId ? `'${folderId}'` : 'null'});}">
                    <span class="folder-item-glyph" aria-hidden="true">${escapeHtml(glyph)}</span>
                    <span class="folder-item-name">${escapeHtml(label)}</span>
                    <span class="folder-item-count">${count}</span>
                    ${menuButton}
                </div>
            `;
        }

        function updateSidebarState() {
            document.body.classList.toggle('sidebar-collapsed', !sidebarExpanded);
            const toggleLabel = sidebarExpanded ? '收起侧边栏' : '展开侧边栏';
            toggleSidebarBtn.title = toggleLabel;
            toggleSidebarBtn.setAttribute('aria-label', toggleLabel);
        }

        function getFolderGlyph(label, scope) {
            if (scope === 'all') return '全';
            const normalized = String(label || '').trim();
            if (!normalized) return '文';
            return normalized[0].toUpperCase();
        }

        function renderFolderNavigation() {
            const normalizedQuery = folderSearchQuery.trim().toLowerCase();
            const baseItems = [
                { label: '全部内容', scope: 'all', count: totalFolderCount },
            ];
            const userItems = foldersData.map((folder) => ({
                label: folder.name,
                scope: 'folder',
                count: folder.item_count || 0,
                id: folder.id,
            }));
            const visibleItems = [...baseItems, ...userItems].filter((entry) => {
                if (!normalizedQuery) return true;
                return String(entry.label || '').toLowerCase().includes(normalizedQuery);
            });

            folderList.innerHTML = visibleItems.length
                ? visibleItems.map((entry) => renderFolderNavItem(entry.label, entry.scope, entry.count, entry.id || null, { menu: entry.scope === 'folder' })).join('')
                : '<div class="folder-empty">没有匹配的文件夹</div>';

            const mobileItems = [
                { label: '全部', scope: 'all', count: totalFolderCount },
                ...foldersData.map((folder) => ({ label: folder.name, scope: 'folder', count: folder.item_count || 0, id: folder.id })),
            ];
            folderMobileStrip.innerHTML = mobileItems.map((item) => {
                const active = currentFolderScope === item.scope && (item.scope !== 'folder' || currentFolderId === item.id);
                const folderId = item.id ? `'${item.id}'` : 'null';
                return `<button class="folder-chip${active ? ' active' : ''}" type="button" onclick="setActiveFolder('${item.scope}', ${folderId})">${escapeHtml(item.label)} · ${item.count}</button>`;
            }).join('') + '<button class="folder-chip" type="button" onclick="openCreateFolderPrompt()">+ 新建</button>';
        }

        async function fetchFolders() {
            if (!ensureAuthenticated({ showOverlay: false })) {
                folderList.innerHTML = '<div class="folder-loading">正在连接本地文件夹...</div>';
                folderMobileStrip.innerHTML = '';
                updateMobileCaptureFolderSummary();
                return;
            }
            try {
                const response = await fetch('/api/folders');
                if (!response.ok) throw new Error('API Error');
                const data = await response.json();
                foldersData = Array.isArray(data.folders) ? data.folders : [];
                totalFolderCount = Number(data.total_count || 0);
                unfiledFolderCount = Number(data.unfiled_count || 0);
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
            } catch (error) {
                if (!authState.authenticated) return;
                folderList.innerHTML = '<div class="folder-loading">文件夹加载失败</div>';
                folderMobileStrip.innerHTML = '';
                updateMobileCaptureFolderSummary();
            }
        }

        async function createFolder(name) {
            const trimmedName = String(name || '').trim();
            if (!trimmedName) return null;
            const response = await fetch('/api/folders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: trimmedName }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.detail || '创建文件夹失败');
            }
            await fetchFolders();
            return data;
        }

        function openCreateFolderPrompt() {
            folderPickerContext = 'create';
            folderCreateInput.value = '';
            folderPickerTargetIds = [];
            folderPickerSelectedIds = new Set(currentFolderScope === 'folder' && currentFolderId ? [currentFolderId] : []);
            folderPickerTitle.textContent = '新建文件夹';
            folderCreateConfirmBtn.textContent = '立即新建';
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
            folderPickerOverlay.classList.add('active');
            requestAnimationFrame(() => folderCreateInput.focus());

            if (!foldersData.length && authState.authenticated) {
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
                : '新建后会自动切换到对应文件夹。';
            folderPickerClearBtn.hidden = true;
            folderPickerApplyBtn.hidden = true;
            folderPickerClearBtn.textContent = '清空选择';
            folderPickerApplyBtn.textContent = '完成';
        }

        function renderFolderPickerOptions() {
            const mode = getFolderPickerMode();
            const options = foldersData.map((folder) => ({ id: folder.id, label: folder.name, count: folder.item_count || 0 }));
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
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || '批量归类失败');
                    showToast(`已整理 ${data.updated_count} 条内容`, 'success');
                } else if (folderPickerTargetIds.length === 1) {
                    const response = await fetch(`/api/items/${folderPickerTargetIds[0]}/folder`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ folder_ids: folderIds }),
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || '归类失败');
                    const toastLabel = Array.isArray(data.folder_names) && data.folder_names.length
                        ? data.folder_names.join('、')
                        : '无文件夹';
                    showToast(`已更新到：${toastLabel}`, 'success');
                } else {
                    closeFolderPickerDialog();
                    return;
                }
                closeFolderPickerDialog();
                await Promise.all([fetchFolders(), fetchItems()]);
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
                const folder = await createFolder(folderCreateInput.value);
                if (!folder) {
                    setFolderPickerActionState(false);
                    return;
                }
                folderCreateInput.value = '';
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
                setActiveFolder('folder', folder.id);
            } catch (error) {
                setFolderPickerActionState(false);
                showToast(error.message, 'error');
            }
        }

        function openFolderContextMenu(folderId, event) {
            event.stopPropagation();
            const folder = foldersData.find((entry) => entry.id === folderId);
            if (!folder) return;
            folderContextMenu.innerHTML = `
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
            const trigger = event.currentTarget || event.target;
            const triggerRect = trigger.getBoundingClientRect();
            folderContextMenu.classList.add('show');
            folderContextMenu.style.visibility = 'hidden';

            const menuRect = folderContextMenu.getBoundingClientRect();
            const desiredTop = triggerRect.bottom + 8;
            const desiredLeft = triggerRect.right - menuRect.width;
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
