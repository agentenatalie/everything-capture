const toast = document.getElementById('toast');
const mobileCaptureInput = document.getElementById('mobileCaptureInput');
const mobileFolderPickerBtn = document.getElementById('mobileFolderPickerBtn');
const backendConnectionStatus = document.getElementById('backendConnectionStatus');
const mobileQueueSummary = document.getElementById('mobileQueueSummary');
const mobilePasteBtn = document.getElementById('mobilePasteBtn');
const mobileSubmitBtn = document.getElementById('mobileSubmitBtn');
const mobileCaptureResult = document.getElementById('mobileCaptureResult');
const folderPickerOverlay = document.getElementById('folderPickerOverlay');
const folderPickerTitle = document.getElementById('folderPickerTitle');
const folderPickerList = document.getElementById('folderPickerList');
const folderPickerHint = document.getElementById('folderPickerHint');
const folderPickerStatus = document.getElementById('folderPickerStatus');
const folderPickerClearBtn = document.getElementById('folderPickerClearBtn');
const folderPickerApplyBtn = document.getElementById('folderPickerApplyBtn');
const closeFolderPicker = document.getElementById('closeFolderPicker');
const folderCreateInput = document.getElementById('folderCreateInput');
const folderCreateConfirmBtn = document.getElementById('folderCreateConfirmBtn');
const queueOverlay = document.getElementById('queueOverlay');
const closeQueueOverlay = document.getElementById('closeQueueOverlay');
const queueRefreshBtn = document.getElementById('queueRefreshBtn');
const queueFilterStatus = document.getElementById('queueFilterStatus');
const queueListStatus = document.getElementById('queueListStatus');
const queueList = document.getElementById('queueList');
const queuePendingCount = document.getElementById('queuePendingCount');
const queueProcessingCount = document.getElementById('queueProcessingCount');
const queueTotalCount = document.getElementById('queueTotalCount');

const MOBILE_CAPTURE_SELECTED_FOLDER_STORAGE_KEY = 'everything-capture-mobile-folder-selection-v1';
const CAPTURE_HISTORY_STORAGE_KEY = 'everything-capture-history-v1';
const CAPTURE_STATUS_POLL_INTERVAL_MS = 5000;
const CAPTURE_STATUS_POLL_MAX_DURATION_MS = 10 * 60 * 1000;
const BACKEND_STATUS_POLL_INTERVAL_MS = 60000;
const BACKEND_CONNECTED_GRACE_MS = 10 * 60 * 1000;

let foldersData = [];
let captureStatusPollTimer = null;
let activeCapturePollId = null;
let activeCapturePollStartedAt = 0;
let lastAutoFilledClipboardText = '';
let lastQueueSnapshot = null;
let backendStatusPollTimer = null;
let backendConnected = false;
let lastBackendConnectedAt = 0;
let activeQueueFilter = 'pending';
let folderPickerMode = 'default';
let pendingSubmitValue = '';
let captureHistory = (() => {
    try {
        const raw = window.localStorage.getItem(CAPTURE_HISTORY_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
        return [];
    }
})();
let mobileCaptureSelectedFolderIds = (() => {
    try {
        const raw = window.localStorage.getItem(MOBILE_CAPTURE_SELECTED_FOLDER_STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
            return parsed.map((value) => String(value || '').trim()).filter(Boolean);
        }
        return [];
    } catch (error) {
        return [];
    }
})();

function showToast(message, tone = 'info') {
    if (!toast) return;
    toast.textContent = message;
    toast.className = `toast ${tone}`.trim();
    requestAnimationFrame(() => {
        toast.classList.add('show');
    });
    window.clearTimeout(showToast._timer);
    showToast._timer = window.setTimeout(() => {
        toast.classList.remove('show');
    }, 2200);
}

function setMobileCaptureFeedback(message = '', tone = '') {
    const nextMessage = String(message || '').trim();
    if (!mobileCaptureResult) return;
    mobileCaptureResult.hidden = !nextMessage;
    mobileCaptureResult.textContent = nextMessage;
    mobileCaptureResult.className = 'mobile-capture-result';
    if (tone) {
        mobileCaptureResult.classList.add(`is-${tone}`);
    }
}

function persistCaptureHistory() {
    try {
        window.localStorage.setItem(CAPTURE_HISTORY_STORAGE_KEY, JSON.stringify(captureHistory.slice(0, 300)));
    } catch (error) {
        console.warn('Failed to persist capture history', error);
    }
}

function normalizeHistoryItem(item) {
    return {
        id: String(item?.id || '').trim(),
        title: item?.title || null,
        raw_url: item?.raw_url || null,
        raw_text: item?.raw_text || null,
        source: item?.source || 'phone-webapp',
        source_app: item?.source_app || 'capture-webapp',
        folder_names: Array.isArray(item?.folder_names) ? item.folder_names : [],
        status: item?.status || 'pending',
        error_reason: item?.error_reason || null,
        local_item_id: item?.local_item_id || null,
        created_at: item?.created_at || new Date().toISOString(),
        updated_at: item?.updated_at || new Date().toISOString(),
        processed_at: item?.processed_at || null,
    };
}

function upsertCaptureHistoryItem(item) {
    const normalized = normalizeHistoryItem(item);
    if (!normalized.id) {
        return;
    }

    const existingIndex = captureHistory.findIndex((entry) => entry.id === normalized.id);
    if (existingIndex >= 0) {
        captureHistory[existingIndex] = {
            ...captureHistory[existingIndex],
            ...normalized,
        };
    } else {
        captureHistory.unshift(normalized);
    }
    captureHistory.sort((left, right) => new Date(right.created_at || 0).getTime() - new Date(left.created_at || 0).getTime());
    captureHistory = captureHistory.slice(0, 300);
    persistCaptureHistory();
}

function filteredHistoryItems(filterName) {
    return captureHistory.filter((item) => {
        if (filterName === 'all') return true;
        return item.status === filterName;
    });
}

function buildMergedStatusCounts(serverCounts = {}) {
    const mergedMap = new Map();
    captureHistory.forEach((item) => {
        if (item?.id) {
            mergedMap.set(item.id, item);
        }
    });
    const counts = {
        pending: 0,
        processing: 0,
        processed: 0,
        failed: 0,
    };

    mergedMap.forEach((item) => {
        if (counts[item.status] !== undefined) {
            counts[item.status] += 1;
        }
    });

    for (const statusName of Object.keys(counts)) {
        counts[statusName] = Math.max(Number(serverCounts?.[statusName] || 0), counts[statusName]);
    }

    return counts;
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getQueueItemPrimaryText(item) {
    const primary = String(
        item?.title
        || item?.raw_url
        || item?.raw_text
        || ''
    ).trim();
    if (!primary) {
        return '未命名收录';
    }
    return primary.length > 96 ? `${primary.slice(0, 96)}…` : primary;
}

function formatRelativeTime(value) {
    if (!value) {
        return '刚刚上传';
    }

    const timestamp = new Date(value).getTime();
    if (Number.isNaN(timestamp)) {
        return '刚刚上传';
    }

    const diffMs = Date.now() - timestamp;
    if (diffMs < 60 * 1000) {
        return '刚刚上传';
    }

    const diffMinutes = Math.floor(diffMs / (60 * 1000));
    if (diffMinutes < 60) {
        return `${diffMinutes} 分钟前上传`;
    }

    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) {
        return `${diffHours} 小时前上传`;
    }

    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} 天前上传`;
}

function renderQueueSummary(statusCounts = {}) {
    const pendingCount = Number(statusCounts.pending || 0);
    const processingCount = Number(statusCounts.processing || 0);
    const waitingCount = pendingCount + processingCount;

    if (!mobileQueueSummary) {
        return;
    }

    if (!waitingCount) {
        mobileQueueSummary.textContent = '等待列表';
        return;
    }

    if (processingCount) {
        mobileQueueSummary.textContent = `等待 ${pendingCount} · 处理中 ${processingCount}`;
        return;
    }

    mobileQueueSummary.textContent = `等待 ${pendingCount}`;
}

function renderBackendConnectionStatus(payload) {
    if (payload?.connected) {
        lastBackendConnectedAt = Date.now();
        backendConnected = true;
    } else {
        backendConnected = Date.now() - lastBackendConnectedAt < BACKEND_CONNECTED_GRACE_MS;
    }
    if (!backendConnectionStatus) {
        return;
    }

    backendConnectionStatus.textContent = backendConnected ? '后端：已连接' : '后端：未连接';
    backendConnectionStatus.className = `backend-connection-status ${backendConnected ? 'is-online' : 'is-offline'}`;
}

async function fetchBackendStatus({ silent = false } = {}) {
    try {
        const payload = await api('/api/worker-status');
        renderBackendConnectionStatus(payload);
        return payload;
    } catch (error) {
        renderBackendConnectionStatus({ connected: backendConnected });
        if (!silent) {
            showToast(error.message || '后端状态读取失败', 'error');
        }
        throw error;
    }
}

function scheduleBackendStatusPolling() {
    if (backendStatusPollTimer) {
        window.clearTimeout(backendStatusPollTimer);
        backendStatusPollTimer = null;
    }

    if (typeof document !== 'undefined' && document.hidden) {
        // Pause polling when the tab is hidden so the queue DB can scale to zero.
        return;
    }

    backendStatusPollTimer = window.setTimeout(async () => {
        try {
            await fetchBackendStatus({ silent: true });
        } catch (error) {
            // Keep polling even if one request fails.
        } finally {
            scheduleBackendStatusPolling();
        }
    }, BACKEND_STATUS_POLL_INTERVAL_MS);
}

function queueFilterLabel(filterName) {
    if (filterName === 'processing') return '处理中';
    if (filterName === 'all') return '已上传总数';
    return '等待中';
}

function renderQueueList(snapshot) {
    const serverItems = Array.isArray(snapshot?.items) ? [...snapshot.items] : [];
    serverItems.forEach((item) => upsertCaptureHistoryItem(item));

    const statusCounts = buildMergedStatusCounts(snapshot?.status_counts || {});
    const pendingCount = Number(statusCounts.pending || 0);
    const processingCount = Number(statusCounts.processing || 0);
    const uploadedTotal = Number(statusCounts.pending || 0)
        + Number(statusCounts.processing || 0)
        + Number(statusCounts.processed || 0)
        + Number(statusCounts.failed || 0);
    const items = filteredHistoryItems(activeQueueFilter);

    document.querySelectorAll('.queue-metric-card').forEach((card) => {
        card.classList.toggle('is-active', card.dataset.filter === activeQueueFilter);
    });

    if (queuePendingCount) queuePendingCount.textContent = String(pendingCount);
    if (queueProcessingCount) queueProcessingCount.textContent = String(processingCount);
    if (queueTotalCount) queueTotalCount.textContent = String(uploadedTotal);
    renderQueueSummary(statusCounts);
    if (queueFilterStatus) {
        queueFilterStatus.textContent = `当前查看：${queueFilterLabel(activeQueueFilter)}`;
    }

    if (queueListStatus) {
        if (activeQueueFilter === 'pending') {
            queueListStatus.textContent = pendingCount
                ? `当前有 ${pendingCount} 条任务正在等待后端处理。`
                : '当前没有等待中的任务。';
        } else if (activeQueueFilter === 'processing') {
            queueListStatus.textContent = processingCount
                ? `当前有 ${processingCount} 条任务正在处理中。`
                : '当前没有正在处理中的任务。';
        } else {
            const failedCount = Number(statusCounts.failed || 0);
            queueListStatus.textContent = `累计已上传 ${uploadedTotal} 条，其中失败 ${failedCount} 条。`;
        }
    }

    if (!queueList) {
        return;
    }

    if (!items.length) {
        queueList.innerHTML = '<div class="queue-empty">当前等待列表为空，新的上传会在这里显示。</div>';
        return;
    }

    items.sort((left, right) => {
        const leftTime = new Date(left?.created_at || 0).getTime();
        const rightTime = new Date(right?.created_at || 0).getTime();
        return rightTime - leftTime;
    });

    queueList.innerHTML = items.map((item) => {
        const statusMap = {
            pending: '等待中',
            processing: '处理中',
            processed: '已处理',
            failed: '处理失败',
        };
        const statusText = statusMap[item.status] || '未知状态';
        const metaParts = [formatRelativeTime(item.created_at)];
        if (Array.isArray(item.folder_names) && item.folder_names.length) {
            metaParts.push(`文件夹：${item.folder_names.join('、')}`);
        }
        if (item.source_app) {
            metaParts.push(`来源：${item.source_app}`);
        } else if (item.source) {
            metaParts.push(`来源：${item.source}`);
        }

        return `
            <div class="queue-item">
                <div class="queue-item-top">
                    <div class="queue-item-title">${escapeHtml(getQueueItemPrimaryText(item))}</div>
                    <div class="queue-item-status${item.status === 'pending' ? ' is-pending' : ''}${item.status === 'processing' ? ' is-processing' : ''}${item.status === 'processed' ? ' is-processed' : ''}${item.status === 'failed' ? ' is-failed' : ''}">${statusText}</div>
                </div>
                <div class="queue-item-meta">${escapeHtml(metaParts.join(' · '))}</div>
                ${item.status === 'failed' && item.error_reason ? `<div class="queue-item-error">${escapeHtml(item.error_reason)}</div>` : ''}
            </div>
        `;
    }).join('');
}

async function warmCaptureService() {
    try {
        await fetch('/healthz', { cache: 'no-store' });
    } catch (error) {
        // Best-effort prewarm only.
    }
}

function getSelectedFolderNames() {
    return foldersData
        .filter((folder) => mobileCaptureSelectedFolderIds.includes(folder.id))
        .map((folder) => folder.name);
}

function refreshFolderPickerPresentation() {
    const selectedFolders = foldersData.filter((folder) => mobileCaptureSelectedFolderIds.includes(folder.id));
    const selectedNames = selectedFolders.map((folder) => folder.name);

    if (folderPickerMode === 'submit') {
        folderPickerTitle.textContent = '选择这次收录的文件夹';
        folderPickerHint.textContent = '这次上传前先选文件夹。可以多选，也可以不指定文件夹，直接放在全部里。';
        folderCreateConfirmBtn.textContent = '新建并加入';
        folderPickerClearBtn.textContent = '此条不指定文件夹';
        folderPickerApplyBtn.textContent = '开始收录';
        folderPickerStatus.textContent = selectedNames.length
            ? `这次将存入 ${selectedNames.length} 个文件夹：${selectedNames.join('、')}`
            : '这次不指定文件夹，会直接进入全部';
        return;
    }

    folderPickerTitle.textContent = '手机端默认文件夹';
    folderPickerHint.textContent = '设置手机端默认文件夹。每次收录前仍然可以再改，也可以留空。';
    folderCreateConfirmBtn.textContent = '新建并使用';
    folderPickerClearBtn.textContent = '不指定文件夹';
    folderPickerApplyBtn.textContent = '保存选择';
    folderPickerStatus.textContent = selectedNames.length
        ? `默认存入 ${selectedNames.length} 个文件夹：${selectedNames.join('、')}`
        : '当前不指定文件夹';
}

async function fetchQueueSnapshot({ silent = false } = {}) {
    try {
        const snapshot = await api(`/api/items?status=${activeQueueFilter}&limit=200`);
        lastQueueSnapshot = snapshot;
        renderQueueList(snapshot);
        return snapshot;
    } catch (error) {
        renderQueueList({ items: [], status_counts: {} });
        if (queueListStatus) {
            queueListStatus.textContent = `等待列表加载失败：${error.message || '请求失败'}`;
        }
        if (queueList) {
            if (!filteredHistoryItems(activeQueueFilter).length) {
                queueList.innerHTML = '<div class="queue-empty">暂时无法读取等待列表，请稍后重试。</div>';
            }
        }
        if (!silent) {
            showToast(error.message || '等待列表加载失败', 'error');
        }
        throw error;
    }
}

function openQueueOverlay() {
    queueOverlay?.classList.add('active');
    if (!lastQueueSnapshot) {
        if (queueListStatus) {
            queueListStatus.textContent = '正在加载等待列表…';
        }
        if (queueList) {
            queueList.innerHTML = '<div class="queue-empty">正在加载…</div>';
        }
    }
    fetchQueueSnapshot({ silent: true }).catch(() => {});
}

function setQueueFilter(filterName) {
    activeQueueFilter = filterName;
    fetchQueueSnapshot({ silent: true }).catch(() => {});
}

function closeQueueDialog() {
    queueOverlay?.classList.remove('active');
}

function stopCaptureStatusPolling() {
    if (captureStatusPollTimer) {
        window.clearTimeout(captureStatusPollTimer);
        captureStatusPollTimer = null;
    }
    activeCapturePollId = null;
    activeCapturePollStartedAt = 0;
}

function describeCaptureItemStatus(item) {
    if (!item || !item.status) {
        return {
            message: backendConnected ? '已保存到网站队列，等待本地处理' : '已保存到网站队列，等待后端连接',
            tone: 'success',
            done: false,
        };
    }

    if (item.status === 'processing') {
        return { message: '处理中', tone: '', done: false };
    }

    if (item.status === 'processed') {
        return { message: '已处理', tone: 'success', done: true };
    }

    if (item.status === 'failed') {
        const detail = String(item.error_reason || '').trim();
        return {
            message: detail ? `处理失败：${detail}` : '处理失败',
            tone: 'error',
            done: true,
        };
    }

    const elapsedMs = activeCapturePollStartedAt ? Date.now() - activeCapturePollStartedAt : 0;
    if (elapsedMs >= 15000) {
        return {
            message: backendConnected ? '已保存到网站队列，等待本地处理' : '已保存到网站队列，等待后端连接',
            tone: '',
            done: false,
        };
    }

    return {
        message: backendConnected ? '已保存到网站队列，等待本地处理' : '已保存到网站队列，等待后端连接',
        tone: 'success',
        done: false,
    };
}

async function pollCaptureItemStatus() {
    if (!activeCapturePollId) return;

    try {
        const item = await api(`/api/items/${activeCapturePollId}`);
        upsertCaptureHistoryItem(item);
        const statusState = describeCaptureItemStatus(item);
        setMobileCaptureFeedback(statusState.message, statusState.tone);

        if (statusState.done) {
            if (item.status === 'processed') {
                showToast('处理完成', 'success');
            } else if (item.status === 'failed') {
                showToast('处理失败', 'error');
            }
            fetchQueueSnapshot({ silent: true }).catch(() => {});
            stopCaptureStatusPolling();
            return;
        }
    } catch (error) {
        setMobileCaptureFeedback('已保存到网站队列，状态稍后自动刷新', '');
        captureStatusPollTimer = window.setTimeout(pollCaptureItemStatus, CAPTURE_STATUS_POLL_INTERVAL_MS);
        return;
    }

    const elapsedMs = activeCapturePollStartedAt ? Date.now() - activeCapturePollStartedAt : 0;
    if (elapsedMs >= CAPTURE_STATUS_POLL_MAX_DURATION_MS) {
        setMobileCaptureFeedback(
            backendConnected ? '已保存到网站队列，等待本地处理' : '已保存到网站队列，等待后端连接',
            ''
        );
        stopCaptureStatusPolling();
        return;
    }

    captureStatusPollTimer = window.setTimeout(pollCaptureItemStatus, CAPTURE_STATUS_POLL_INTERVAL_MS);
}

function startCaptureStatusPolling(itemId) {
    stopCaptureStatusPolling();
    activeCapturePollId = String(itemId || '').trim();
    if (!activeCapturePollId) return;
    activeCapturePollStartedAt = Date.now();
    captureStatusPollTimer = window.setTimeout(pollCaptureItemStatus, CAPTURE_STATUS_POLL_INTERVAL_MS);
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
    if (!mobileFolderPickerBtn) return;
    const selectedFolderNames = getSelectedFolderNames();
    const fullLabel = selectedFolderNames.length ? selectedFolderNames.join('、') : '全部';
    const label = fullLabel.length > 12 ? `${fullLabel.slice(0, 12)}…` : fullLabel;
    mobileFolderPickerBtn.textContent = `选择文件夹 · ${label}`;
}

function checkSvg() {
    return `
        <svg viewBox="0 0 24 24" fill="none" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="m5 13 4 4L19 7"></path>
        </svg>
    `;
}

function renderFolderPickerOptions() {
    folderPickerList.innerHTML = foldersData.length
        ? foldersData.map((folder) => {
            const active = mobileCaptureSelectedFolderIds.includes(folder.id);
            return `
                <button class="folder-picker-option${active ? ' active' : ''}" type="button" data-folder-id="${folder.id}">
                    <span class="folder-picker-option-main">
                        <span class="folder-picker-option-label">${folder.name}</span>
                        <span class="folder-picker-option-subtitle">${folderPickerMode === 'submit' ? '点击切换这次收录的文件夹' : '点击切换默认文件夹'}</span>
                    </span>
                    <span class="folder-picker-option-side">
                        <span class="folder-picker-option-meta">云端</span>
                        <span class="folder-picker-check">${checkSvg()}</span>
                    </span>
                </button>
            `;
        }).join('')
        : '<div class="folder-picker-empty">还没有文件夹。先在上面输入名称创建一个。</div>';

    refreshFolderPickerPresentation();
}

async function api(path, options = {}) {
    const response = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.detail || '请求失败');
    }
    return data;
}

async function fetchFolders() {
    const data = await api('/api/folders');
    foldersData = Array.isArray(data.folders) ? data.folders : [];
    if (mobileCaptureSelectedFolderIds.length) {
        mobileCaptureSelectedFolderIds = mobileCaptureSelectedFolderIds.filter((folderId) => foldersData.some((folder) => folder.id === folderId));
        persistMobileCaptureSelectedFolder();
    }
    updateMobileCaptureFolderSummary();
    renderFolderPickerOptions();
}

async function createFolder() {
    const trimmedName = String(folderCreateInput.value || '').trim();
    if (!trimmedName) {
        showToast('请输入文件夹名称', 'error');
        return;
    }
    const folder = await api('/api/folders', {
        method: 'POST',
        body: JSON.stringify({ name: trimmedName }),
    });
    folderCreateInput.value = '';
    await fetchFolders();
    if (!mobileCaptureSelectedFolderIds.includes(folder.id)) {
        mobileCaptureSelectedFolderIds.push(folder.id);
        persistMobileCaptureSelectedFolder();
        updateMobileCaptureFolderSummary();
        renderFolderPickerOptions();
    }
    showToast(
        folderPickerMode === 'submit'
            ? `已创建并加入这次收录：${folder.name}`
            : `已创建并加入默认文件夹：${folder.name}`,
        'success'
    );
}

function openMobileCaptureFolderPicker(mode = 'default', submitValue = '') {
    folderPickerMode = mode;
    pendingSubmitValue = mode === 'submit' ? String(submitValue || '').trim() : '';
    refreshFolderPickerPresentation();
    renderFolderPickerOptions();
    folderPickerOverlay.classList.add('active');
}

function closeFolderPickerDialog() {
    folderPickerOverlay.classList.remove('active');
    folderPickerMode = 'default';
    pendingSubmitValue = '';
}

async function readClipboardTextSilently() {
    if (!navigator.clipboard?.readText || !window.isSecureContext) {
        return '';
    }

    try {
        return String(await navigator.clipboard.readText()).trim();
    } catch (error) {
        return '';
    }
}

async function tryAutofillFromClipboard() {
    if (!mobileCaptureInput || mobileCaptureInput.value.trim()) {
        return false;
    }

    const text = await readClipboardTextSilently();
    if (!text || text === lastAutoFilledClipboardText) {
        return false;
    }

    lastAutoFilledClipboardText = text;
    mobileCaptureInput.value = text;
    return true;
}

async function pasteClipboardIntoMobileInput() {
    const clipboardApiAvailable = Boolean(navigator.clipboard?.readText && window.isSecureContext);
    let text = await readClipboardTextSilently();
    let clipboardReadBlocked = !clipboardApiAvailable;

    if (!text) {
        const manualValue = window.prompt(
            clipboardReadBlocked
                ? '系统限制了网页直接读取剪切板，请在这里粘贴内容'
                : '请粘贴内容',
            ''
        );
        if (manualValue === null) return;
        text = String(manualValue || '').trim();
    }

    if (!text) {
        showToast('没有可粘贴的内容', 'info');
        return;
    }

    mobileCaptureInput.value = text;
    showToast('已粘贴到输入框', 'success');
}

async function performMobileCapture(rawValue) {
    if (!rawValue) {
        showToast('请先粘贴链接或文字', 'error');
        return;
    }

    setMobileCaptureFeedback('正在收录…', '');
    mobileSubmitBtn.disabled = true;
    mobileSubmitBtn.classList.add('is-loading');

    try {
        const data = await api('/api/capture', {
            method: 'POST',
            body: JSON.stringify({
                text: rawValue,
                url: rawValue,
                source: 'phone-webapp',
                source_app: 'capture-webapp',
                timestamp: new Date().toISOString(),
                folder_names: getSelectedFolderNames(),
            }),
        });

        if (data.captured) {
            upsertCaptureHistoryItem(
                data.item || {
                    id: data.item_id,
                    raw_url: rawValue,
                    raw_text: rawValue,
                    status: data.status || 'pending',
                    folder_names: getSelectedFolderNames(),
                }
            );
            mobileCaptureInput.value = '';
            lastAutoFilledClipboardText = '';
            setMobileCaptureFeedback(
                backendConnected ? '已保存到网站队列，等待本地处理' : '已保存到网站队列，等待后端连接',
                'success'
            );
            startCaptureStatusPolling(data.item_id);
            fetchQueueSnapshot({ silent: true }).catch(() => {});
            fetchBackendStatus({ silent: true }).catch(() => {});
            showToast('已保存到网站队列', 'success');
            return;
        }
        throw new Error('收录未成功');
    } catch (error) {
        const message = error?.message || '收录失败';
        setMobileCaptureFeedback(message, 'error');
        showToast(message, 'error');
    } finally {
        mobileSubmitBtn.disabled = false;
        mobileSubmitBtn.classList.remove('is-loading');
    }
}

function requestFolderSelectionBeforeSubmit() {
    const rawValue = mobileCaptureInput?.value?.trim() || '';
    if (!rawValue) {
        showToast('请先粘贴链接或文字', 'error');
        return;
    }

    mobileCaptureSelectedFolderIds = [];
    openMobileCaptureFolderPicker('submit', rawValue);
}

folderPickerList?.addEventListener('click', (event) => {
    const option = event.target.closest('[data-folder-id]');
    if (!option) return;
    const folderId = option.getAttribute('data-folder-id');
    if (!folderId) return;

    if (mobileCaptureSelectedFolderIds.includes(folderId)) {
        mobileCaptureSelectedFolderIds = mobileCaptureSelectedFolderIds.filter((id) => id !== folderId);
    } else {
        mobileCaptureSelectedFolderIds.push(folderId);
    }
    if (folderPickerMode !== 'submit') {
        persistMobileCaptureSelectedFolder();
    }
    updateMobileCaptureFolderSummary();
    renderFolderPickerOptions();
});

mobileSubmitBtn?.addEventListener('click', () => {
    requestFolderSelectionBeforeSubmit();
});

mobilePasteBtn?.addEventListener('click', () => {
    pasteClipboardIntoMobileInput();
});

mobileCaptureInput?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
        event.preventDefault();
        requestFolderSelectionBeforeSubmit();
    }
});

mobileFolderPickerBtn?.addEventListener('click', () => {
    openMobileCaptureFolderPicker('default');
});

mobileQueueSummary?.addEventListener('click', (event) => {
    event.preventDefault();
    openQueueOverlay();
});

closeFolderPicker?.addEventListener('click', () => {
    closeFolderPickerDialog();
});

closeQueueOverlay?.addEventListener('click', () => {
    closeQueueDialog();
});

folderPickerClearBtn?.addEventListener('click', () => {
    mobileCaptureSelectedFolderIds = [];
    if (folderPickerMode !== 'submit') {
        persistMobileCaptureSelectedFolder();
    }
    updateMobileCaptureFolderSummary();
    renderFolderPickerOptions();
    if (folderPickerMode === 'submit') {
        showToast('这次收录将不指定文件夹', 'info');
        return;
    }
    closeFolderPickerDialog();
    showToast('手机端将不指定文件夹', 'info');
});

folderPickerApplyBtn?.addEventListener('click', async () => {
    const selectedFolders = foldersData.filter((folder) => mobileCaptureSelectedFolderIds.includes(folder.id));

    if (folderPickerMode === 'submit') {
        const submitValue = pendingSubmitValue;
        closeFolderPickerDialog();
        await performMobileCapture(submitValue);
        mobileCaptureSelectedFolderIds = [];
        updateMobileCaptureFolderSummary();
        return;
    }

    updateMobileCaptureFolderSummary();
    closeFolderPickerDialog();
    showToast(
        selectedFolders.length
            ? `手机端将默认存入：${selectedFolders.map((folder) => folder.name).join('、')}`
            : '手机端将不指定文件夹',
        'success'
    );
});

folderCreateConfirmBtn?.addEventListener('click', async () => {
    try {
        await createFolder();
    } catch (error) {
        showToast(error.message || '创建文件夹失败', 'error');
    }
});

folderCreateInput?.addEventListener('keydown', async (event) => {
    if (event.key === 'Enter') {
        event.preventDefault();
        try {
            await createFolder();
        } catch (error) {
            showToast(error.message || '创建文件夹失败', 'error');
        }
    }
});

folderPickerOverlay?.addEventListener('click', (event) => {
    if (event.target === folderPickerOverlay) {
        closeFolderPickerDialog();
    }
});

queueOverlay?.addEventListener('click', (event) => {
    if (event.target === queueOverlay) {
        closeQueueDialog();
    }
});

queueRefreshBtn?.addEventListener('click', () => {
    fetchBackendStatus({ silent: true }).catch(() => {});
    fetchQueueSnapshot().catch(() => {});
});

document.querySelectorAll('.queue-metric-card').forEach((card) => {
    card.addEventListener('click', () => {
        const filterName = card.dataset.filter;
        if (!filterName) {
            return;
        }
        setQueueFilter(filterName);
    });
});

document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        fetchBackendStatus({ silent: true }).catch(() => {});
        warmCaptureService().catch(() => {});
        tryAutofillFromClipboard().catch(() => {});
        scheduleBackendStatusPolling();
    } else if (backendStatusPollTimer) {
        window.clearTimeout(backendStatusPollTimer);
        backendStatusPollTimer = null;
    }
});

window.addEventListener('focus', () => {
    fetchBackendStatus({ silent: true }).catch(() => {});
    warmCaptureService().catch(() => {});
    tryAutofillFromClipboard().catch(() => {});
});

mobileCaptureInput?.addEventListener('focus', () => {
    warmCaptureService().catch(() => {});
});

fetchFolders().catch((error) => {
    setMobileCaptureFeedback(`加载文件夹失败：${error.message}`, 'error');
});

renderQueueSummary();
fetchQueueSnapshot({ silent: true }).catch(() => {});
fetchBackendStatus({ silent: true }).catch(() => {});
scheduleBackendStatusPolling();
warmCaptureService().catch(() => {});
tryAutofillFromClipboard().catch(() => {});
