        const grid = document.getElementById('grid');
        const stats = document.getElementById('stats');
        const modalOverlay = document.getElementById('modalOverlay');
        const modalShell = modalOverlay.querySelector('.modal');
        const commandOverlay = document.getElementById('commandOverlay');
        const modalTitle = document.getElementById('modalTitle');
        const readerMetaLine = document.getElementById('readerMetaLine');
        const readerNotePanel = document.getElementById('readerNotePanel');
        const modalContent = document.getElementById('modalContent');
        const modalFooter = document.getElementById('modalFooter');
        const readerStatusDots = document.getElementById('readerStatusDots');
        const closeModal = document.getElementById('closeModal');
        const toggleNoteBtn = document.getElementById('toggleNoteBtn');
        const toggleReaderFullscreenBtn = document.getElementById('toggleReaderFullscreenBtn');
        const openReaderAiBtn = document.getElementById('openReaderAiBtn');
        const readerSidebar = document.getElementById('readerSidebar');
        const readerSidebarContent = document.getElementById('readerSidebarContent');
        const readerSidebarResizeHandle = document.getElementById('readerSidebarResizeHandle');
        const closeReaderSidebar = document.getElementById('closeReaderSidebar');
        const sidebarNoteTab = document.getElementById('sidebarNoteTab');
        const sidebarPageNotesTab = document.getElementById('sidebarPageNotesTab');
        const sidebarAiTab = document.getElementById('sidebarAiTab');
        const urlInput = document.getElementById('urlInput');
        const extractBtnLabel = document.getElementById('extractBtnLabel');
        const extractBtnMeta = document.getElementById('extractBtnMeta');
        const clipboardBtn = document.getElementById('clipboardBtn');
        const clipboardBtnLabel = document.getElementById('clipboardBtnLabel');
        const extractBtn = document.getElementById('extractBtn');
        const commandHelpText = document.getElementById('commandHelpText');
        const commandResults = document.getElementById('commandResults');
        const toast = document.getElementById('toast');
        const filterInput = document.getElementById('filterInput');
        const platformFilter = document.getElementById('platformFilter');
        const galleryViewBtn = document.getElementById('galleryViewBtn');
        const listViewBtn = document.getElementById('listViewBtn');
        const folderList = document.getElementById('folderList');
        const folderMobileStrip = document.getElementById('folderMobileStrip');
        const createFolderBtn = document.getElementById('createFolderBtn');
        const folderSearchInput = document.getElementById('folderSearchInput');
        const boardShell = document.getElementById('boardShell');
        const mobileCaptureShell = document.getElementById('mobileCaptureShell');
        const mobileCaptureInput = document.getElementById('mobileCaptureInput');
        const mobileFolderPickerBtn = document.getElementById('mobileFolderPickerBtn');
        const mobileFolderSelection = document.getElementById('mobileFolderSelection');
        const mobilePasteBtn = document.getElementById('mobilePasteBtn');
        const mobileSubmitBtn = document.getElementById('mobileSubmitBtn');
        const mobileCaptureHint = document.getElementById('mobileCaptureHint');
        const mobileCaptureResult = document.getElementById('mobileCaptureResult');
        const toggleSidebarBtn = document.getElementById('toggleSidebarBtn');
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
        const folderContextMenu = document.getElementById('folderContextMenu');
        const sidebarUserName = document.getElementById('sidebarUserName');
        const sidebarUserSubtitle = document.getElementById('sidebarUserSubtitle');
        const sidebarSettingsBtn = document.getElementById('sidebarSettingsBtn');

        // Settings elements
        const settingsBtn = document.getElementById('settingsBtn');
        const settingsOverlay = document.getElementById('settingsOverlay');
        const closeSettingsModal = document.getElementById('closeSettingsModal');
        const btnSaveSettings = document.getElementById('saveSettingsBtn');
        const googleOauthClientIdInput = document.getElementById('googleOauthClientId');
        const googleOauthClientSecretInput = document.getElementById('googleOauthClientSecret');
        const googleOauthRedirectUriInput = document.getElementById('googleOauthRedirectUri');
        const googleOauthStatusText = document.getElementById('googleOauthStatusText');
        const notionStatusText = document.getElementById('notionStatusText');
        const obsidianStatusText = document.getElementById('obsidianStatusText');
        const obsidianFolderPathInput = document.getElementById('obsidianFolderPath');
        const obsidianTargetHint = document.getElementById('obsidianTargetHint');
        const testObsidianBtn = document.getElementById('testObsidianBtn');
        const notionDbIdInput = document.getElementById('notionDbId');
        const notionDbSelect = document.getElementById('notionDbSelect');
        const refreshNotionDbsBtn = document.getElementById('refreshNotionDbsBtn');
        const notionTargetHint = document.getElementById('notionTargetHint');

        const iconCalendar = '<svg class="inline-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 3v3M17 3v3M4 9h16M6.5 5h11A1.5 1.5 0 0 1 19 6.5v11A1.5 1.5 0 0 1 17.5 19h-11A1.5 1.5 0 0 1 5 17.5v-11A1.5 1.5 0 0 1 6.5 5Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
        const iconText = '<svg class="inline-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 7.5h14M5 12h14M5 16.5h9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

        let itemsData = [];
        let currentView = 'gallery';
        let filteredEntries = [];
        let commandSearchResults = [];
        let currentOpenItemId = null;
        let isNotePanelOpen = false;
        let noteSaveInFlight = false;
        let manualParseInFlightItemId = null;
        let analysisOrganizeInFlightItemId = null;
        let latestVisibleCount = 0;
        let latestReturnedCount = 0;
        let latestTotalCount = 0;
        let foldersData = [];
        let totalFolderCount = 0;
        let unfiledFolderCount = 0;
        let currentFolderScope = 'all';
        let currentFolderId = null;
        let folderSearchQuery = '';
        let folderPickerContext = 'assign';
        let sidebarExpanded = true;
        let folderPickerTargetIds = [];
        let folderPickerSelectedIds = new Set();
        let draggedLibraryItemId = null;
        let draggedFolderId = null;
        let currentFolderDropTargetId = null;
        let currentFolderDropMode = '';
        let folderReorderArmed = false;
        let syncActionState = {
            notion: new Set(),
            obsidian: new Set(),
        };
        const ITEM_DRAG_DATA_TYPE = 'application/x-everything-capture-item';
        const FOLDER_DRAG_DATA_TYPE = 'application/x-everything-capture-folder';
        let librarySearchTimer = null;
        let commandSearchTimer = null;
        let libraryRequestId = 0;
        let commandRequestId = 0;
        let currentItemsRequestController = null;
        const REMOTE_SYNC_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
        const REMOTE_SYNC_REFRESH_COOLDOWN_MS = 60 * 1000;
        const ACTIVE_SCROLL_CLASS = 'is-scrolling';
        const SCROLL_IDLE_DELAY_MS = 220;
        let remoteSyncRefreshTimer = null;
        let remoteSyncRefreshQueuedTimer = null;
        let remoteSyncRefreshInFlight = false;
        let lastRemoteSyncRefreshAt = 0;
        let hasWindowFocusedOnce = false;
        let scrollIdleTimer = null;
        let latestSettings = null;
        let hasLoadedAuthenticatedData = false;
        let authBootstrapComplete = false;
        let mobileCaptureAutomationStarted = false;
        let mobileClipboardPollTimer = null;
        let lastAutoCapturedClipboardText = '';
        let mobileCaptureSubmitInFlight = false;
        let lastMobileCaptureSubmissionSignature = '';
        let lastMobileCaptureSubmissionAt = 0;
        let pendingMobileCaptureSubmission = null;
        let folderPickerActionInFlight = false;
        let commandExtractInFlight = false;
        let lastCommandExtractSignature = '';
        let lastCommandExtractAt = 0;
        const MOBILE_CAPTURE_SELECTED_FOLDER_STORAGE_KEY = 'everything-capture-mobile-folder-selection-v1';
        let mobileCaptureSelectedFolderIds = (() => {
            try {
                const raw = window.localStorage.getItem(MOBILE_CAPTURE_SELECTED_FOLDER_STORAGE_KEY);
                if (!raw) return [];
                const parsed = JSON.parse(raw);
                if (Array.isArray(parsed)) {
                    return parsed.map((value) => String(value || '').trim()).filter(Boolean);
                }
                const legacyValue = String(parsed || '').trim();
                return legacyValue ? [legacyValue] : [];
            } catch (error) {
                return [];
            }
        })();
        const nativeFetch = window.fetch.bind(window);

        function resolveMediaUrl(url) {
            if (!url) return url;
            if (url.startsWith('/static/')) {
                return (window.API_BASE_URL || '') + url;
            }
            return url;
        }
        window.resolveMediaUrl = resolveMediaUrl;

        function apiFetch(input, init) {
            const baseUrl = window.API_BASE_URL || '';
            init = init || {};
            init.credentials = 'include';
            if (typeof input === 'string') {
                if (input.startsWith('/api/') || input.startsWith('/static/media/')) {
                    input = baseUrl + input;
                }
            } else if (input instanceof Request) {
                const url = input.url;
                if (url.startsWith('/api/') || url.startsWith('/static/media/')) {
                    input = new Request(baseUrl + url, input);
                }
            }
            return nativeFetch(input, init);
        }
        window.fetch = apiFetch;

        function createLocalAuthState(overrides = {}) {
            return {
                authenticated: true,
                user: {
                    id: 'local-default-user',
                    display_name: '本地收录库',
                    email: null,
                    phone_e164: null,
                    avatar_url: null,
                },
                providers: {
                    google_enabled: false,
                    email_enabled: false,
                    phone_enabled: false,
                    email_delivery_mode: 'disabled',
                    phone_delivery_mode: 'disabled',
                },
                ...overrides,
            };
        }

        let authState = createLocalAuthState();

        function applyAuthState(sessionData = {}) {
            authState = createLocalAuthState(sessionData || {});
            const user = authState.user || {};
            if (sidebarUserName) {
                sidebarUserName.textContent = user.display_name || '本地收录库';
            }
            if (sidebarUserSubtitle) {
                sidebarUserSubtitle.textContent = '本地模式';
            }
        }

        function resetAuthenticatedAppState(message = '正在加载本地资料库...') {
            hasLoadedAuthenticatedData = false;
            latestSettings = null;
            itemsData = [];
            filteredEntries = [];
            commandSearchResults = [];
            foldersData = [];
            totalFolderCount = 0;
            unfiledFolderCount = 0;
            latestVisibleCount = 0;
            latestReturnedCount = 0;
            latestTotalCount = 0;
            currentFolderScope = 'all';
            currentFolderId = null;
            if (commandOverlay.classList.contains('active')) closeCommandPalette();
            if (folderPickerOverlay.classList.contains('active')) closeFolderPickerDialog();
            if (settingsOverlay.classList.contains('active')) {
                if (typeof closeSettingsPanel === 'function') closeSettingsPanel();
                else settingsOverlay.classList.remove('active');
            }
            if (modalOverlay.classList.contains('active')) closeModalDialog();
            setStatsMessage('加载本地资料库中');
            grid.className = currentView === 'gallery' ? 'grid' : 'list-view';
            grid.innerHTML = `<div class="empty-state">${message}</div>`;
            folderList.innerHTML = '<div class="folder-loading">正在加载本地文件夹...</div>';
            folderMobileStrip.innerHTML = '';
        }

        function ensureAuthenticated() {
            return true;
        }

        async function refreshAuthSession() {
            applyAuthState();
            return authState;
        }

        async function provisionLocalSession() {
            applyAuthState();
            return authState;
        }

        async function bootstrapAuthenticatedData(options = {}) {
            const { force = false } = options;
            if (hasLoadedAuthenticatedData && !force) return;
            hasLoadedAuthenticatedData = true;
            await Promise.all([loadSettings({ includeNotionDatabases: false }), fetchFolders(), fetchItems()]);
        }

        function openSettingsPanel() {
            settingsOverlay.scrollTop = 0;
            settingsOverlay.classList.add('active');
            window.setReaderChromeHidden?.(false);
            const settingsMainGrid = document.querySelector('.settings-main-grid');
            if (settingsMainGrid) {
                settingsMainGrid.scrollTop = 0;
            }
            loadSettings({ includeNotionDatabases: true });
        }

        async function handleUrlCallbacks(currentSession = authState) {
            const urlParams = new URLSearchParams(window.location.search);
            const notionAuth = urlParams.get('notion_auth');
            let handled = false;

            if (notionAuth === 'success') {
                handled = true;
                const settings = await loadSettings({ includeNotionDatabases: false });
                if (settings?.notion_ready) {
                    showToast('Notion 授权成功，已可直接同步。', 'success');
                } else {
                    showToast('Notion 授权成功，但还需要选择一个同步目标才能同步。', 'info');
                }
            } else if (notionAuth === 'partial') {
                handled = true;
                await loadSettings({ includeNotionDatabases: false });
                showToast('Notion 授权成功，但当前还缺少同步目标。请在设置里选择一个页面或数据库。', 'info');
            } else if (notionAuth === 'failed') {
                handled = true;
                const errorStr = urlParams.get('error') || 'Unknown error';
                showToast(`Notion Authentication Failed: ${errorStr}`, 'error');
            }

            if (handled) {
                window.history.replaceState({}, document.title, window.location.pathname);
            }
        }

        async function bootstrapAuth() {
            applyAuthState();
            resetAuthenticatedAppState();
            updateSidebarState();
            updateCommandPaletteState();
            if (typeof startMobileCaptureAutomation === 'function' && window.matchMedia('(max-width: 860px)').matches) {
                startMobileCaptureAutomation();
            }

            try {
                await bootstrapAuthenticatedData({ force: true });
                if (typeof flushMobileCaptureQueue === 'function') {
                    await flushMobileCaptureQueue({ silent: true });
                }
                await handleUrlCallbacks(authState);
            } finally {
                authBootstrapComplete = true;
            }
        }

        function markScrollActivity() {
            document.body.classList.add(ACTIVE_SCROLL_CLASS);
            window.clearTimeout(scrollIdleTimer);
            scrollIdleTimer = window.setTimeout(() => {
                document.body.classList.remove(ACTIVE_SCROLL_CLASS);
            }, SCROLL_IDLE_DELAY_MS);
        }

        window.addEventListener('scroll', markScrollActivity, { passive: true });
        window.addEventListener('wheel', markScrollActivity, { passive: true });
        window.addEventListener('touchmove', markScrollActivity, { passive: true });
        document.addEventListener('scroll', markScrollActivity, { passive: true, capture: true });
        boardShell?.addEventListener('scroll', markScrollActivity, { passive: true });
        boardShell?.addEventListener('wheel', markScrollActivity, { passive: true });
