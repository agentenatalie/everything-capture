const toast = document.getElementById('toast');
const mobileCaptureInput = document.getElementById('mobileCaptureInput');
const mobileFolderPickerBtn = document.getElementById('mobileFolderPickerBtn');
const mobileFolderSelection = document.getElementById('mobileFolderSelection');
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

const MOBILE_CAPTURE_SELECTED_FOLDER_STORAGE_KEY = 'everything-grabber-mobile-folder-selection-v1';
const CAPTURE_STATUS_POLL_INTERVAL_MS = 3000;
const CAPTURE_STATUS_POLL_MAX_DURATION_MS = 10 * 60 * 1000;

let foldersData = [];
let captureStatusPollTimer = null;
let activeCapturePollId = null;
let activeCapturePollStartedAt = 0;
let lastAutoFilledClipboardText = '';
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
        return { message: '已收录到待处理队列', tone: 'success', done: false };
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
            message: '已收录到待处理队列，等待本地处理器连接',
            tone: '',
            done: false,
        };
    }

    return { message: '已收录到待处理队列', tone: 'success', done: false };
}

async function pollCaptureItemStatus() {
    if (!activeCapturePollId) return;

    try {
        const item = await api(`/api/items/${activeCapturePollId}`);
        const statusState = describeCaptureItemStatus(item);
        setMobileCaptureFeedback(statusState.message, statusState.tone);

        if (statusState.done) {
            if (item.status === 'processed') {
                showToast('处理完成', 'success');
            } else if (item.status === 'failed') {
                showToast('处理失败', 'error');
            }
            stopCaptureStatusPolling();
            return;
        }
    } catch (error) {
        setMobileCaptureFeedback(`状态查询失败：${error.message || '请求失败'}`, 'error');
        captureStatusPollTimer = window.setTimeout(pollCaptureItemStatus, CAPTURE_STATUS_POLL_INTERVAL_MS);
        return;
    }

    const elapsedMs = activeCapturePollStartedAt ? Date.now() - activeCapturePollStartedAt : 0;
    if (elapsedMs >= CAPTURE_STATUS_POLL_MAX_DURATION_MS) {
        setMobileCaptureFeedback('已收录到待处理队列，等待本地处理器连接', '');
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
    if (!mobileFolderSelection || !mobileFolderPickerBtn) return;
    const selectedFolders = foldersData.filter((folder) => mobileCaptureSelectedFolderIds.includes(folder.id));
    mobileFolderSelection.textContent = selectedFolders.length
        ? `当前：${selectedFolders.map((folder) => folder.name).join('、')}`
        : '当前：不指定文件夹';
    mobileFolderPickerBtn.textContent = selectedFolders.length ? '更换文件夹' : '选择文件夹';
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
                        <span class="folder-picker-option-subtitle">点击切换本次选择</span>
                    </span>
                    <span class="folder-picker-option-side">
                        <span class="folder-picker-option-meta">云端</span>
                        <span class="folder-picker-check">${checkSvg()}</span>
                    </span>
                </button>
            `;
        }).join('')
        : '<div class="folder-picker-empty">还没有文件夹。先在上面输入名称创建一个。</div>';

    const selectedFolders = foldersData.filter((folder) => mobileCaptureSelectedFolderIds.includes(folder.id));
    folderPickerStatus.textContent = selectedFolders.length
        ? `默认存入 ${selectedFolders.length} 个文件夹：${selectedFolders.map((folder) => folder.name).join('、')}`
        : '当前不指定文件夹';
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
    showToast(`已创建并加入默认文件夹：${folder.name}`, 'success');
}

function openMobileCaptureFolderPicker() {
    folderPickerTitle.textContent = '手机端存入文件夹';
    folderPickerHint.textContent = '为手机端新收录内容选择默认文件夹，可以多选，也可以留空。';
    folderCreateConfirmBtn.textContent = '新建并使用';
    renderFolderPickerOptions();
    folderPickerOverlay.classList.add('active');
}

function closeFolderPickerDialog() {
    folderPickerOverlay.classList.remove('active');
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

async function submitMobileCapture() {
    const rawValue = mobileCaptureInput?.value?.trim() || '';
    if (!rawValue) {
        showToast('请先粘贴链接或文字', 'error');
        return;
    }

    mobileSubmitBtn.disabled = true;
    mobileSubmitBtn.classList.add('is-loading');

    try {
        const selectedFolders = foldersData
            .filter((folder) => mobileCaptureSelectedFolderIds.includes(folder.id))
            .map((folder) => folder.name);
        const data = await api('/api/capture', {
            method: 'POST',
            body: JSON.stringify({
                text: rawValue,
                url: rawValue,
                source: 'phone-webapp',
                source_app: 'capture-webapp',
                timestamp: new Date().toISOString(),
                folder_names: selectedFolders,
            }),
        });

        if (data.captured) {
            mobileCaptureInput.value = '';
            lastAutoFilledClipboardText = '';
            setMobileCaptureFeedback('已收录到待处理队列', 'success');
            startCaptureStatusPolling(data.item_id);
            showToast('收录成功', 'success');
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
    persistMobileCaptureSelectedFolder();
    updateMobileCaptureFolderSummary();
    renderFolderPickerOptions();
});

mobileSubmitBtn?.addEventListener('click', () => {
    submitMobileCapture();
});

mobilePasteBtn?.addEventListener('click', () => {
    pasteClipboardIntoMobileInput();
});

mobileCaptureInput?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
        event.preventDefault();
        submitMobileCapture();
    }
});

mobileFolderPickerBtn?.addEventListener('click', () => {
    openMobileCaptureFolderPicker();
});

closeFolderPicker?.addEventListener('click', () => {
    closeFolderPickerDialog();
});

folderPickerClearBtn?.addEventListener('click', () => {
    mobileCaptureSelectedFolderIds = [];
    persistMobileCaptureSelectedFolder();
    updateMobileCaptureFolderSummary();
    renderFolderPickerOptions();
    closeFolderPickerDialog();
    showToast('手机端将不指定文件夹', 'info');
});

folderPickerApplyBtn?.addEventListener('click', () => {
    updateMobileCaptureFolderSummary();
    closeFolderPickerDialog();
    const selectedFolders = foldersData.filter((folder) => mobileCaptureSelectedFolderIds.includes(folder.id));
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

document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        tryAutofillFromClipboard().catch(() => {});
    }
});

window.addEventListener('focus', () => {
    tryAutofillFromClipboard().catch(() => {});
});

fetchFolders().catch((error) => {
    setMobileCaptureFeedback(`加载文件夹失败：${error.message}`, 'error');
});

tryAutofillFromClipboard().catch(() => {});
