        const grid = document.getElementById('grid');
        const stats = document.getElementById('stats');
        const modalOverlay = document.getElementById('modalOverlay');
        const modalShell = modalOverlay.querySelector('.modal');
        const commandOverlay = document.getElementById('commandOverlay');
        const modalTitle = document.getElementById('modalTitle');
        const readerNotePanel = document.getElementById('readerNotePanel');
        const modalContent = document.getElementById('modalContent');
        const modalFooter = document.getElementById('modalFooter');
        const readerStatusDots = document.getElementById('readerStatusDots');
        const closeModal = document.getElementById('closeModal');
        const toggleNoteBtn = document.getElementById('toggleNoteBtn');
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
        const authOverlay = document.getElementById('authOverlay');
        const authGoogleBtn = document.getElementById('authGoogleBtn');
        const authModeEmailBtn = document.getElementById('authModeEmailBtn');
        const authModePhoneBtn = document.getElementById('authModePhoneBtn');
        const emailAuthForm = document.getElementById('emailAuthForm');
        const phoneAuthForm = document.getElementById('phoneAuthForm');
        const authEmailInput = document.getElementById('authEmailInput');
        const authEmailCodeInput = document.getElementById('authEmailCodeInput');
        const authEmailRequestBtn = document.getElementById('authEmailRequestBtn');
        const authEmailVerifyBtn = document.getElementById('authEmailVerifyBtn');
        const authEmailStatus = document.getElementById('authEmailStatus');
        const authPhoneInput = document.getElementById('authPhoneInput');
        const authPhoneCodeInput = document.getElementById('authPhoneCodeInput');
        const authPhoneRequestBtn = document.getElementById('authPhoneRequestBtn');
        const authPhoneVerifyBtn = document.getElementById('authPhoneVerifyBtn');
        const authPhoneStatus = document.getElementById('authPhoneStatus');
        const authProviderHint = document.getElementById('authProviderHint');
        const sidebarAvatarImage = document.getElementById('sidebarAvatarImage');
        const sidebarUserStatusDot = document.getElementById('sidebarUserStatusDot');
        const sidebarUserName = document.getElementById('sidebarUserName');
        const sidebarUserSubtitle = document.getElementById('sidebarUserSubtitle');
        const sidebarSettingsBtn = document.getElementById('sidebarSettingsBtn');
        const sidebarLogoutBtn = document.getElementById('sidebarLogoutBtn');

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
        let librarySearchTimer = null;
        let commandSearchTimer = null;
        let libraryRequestId = 0;
        let commandRequestId = 0;
        const REMOTE_SYNC_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
        const REMOTE_SYNC_REFRESH_COOLDOWN_MS = 60 * 1000;
        let remoteSyncRefreshTimer = null;
        let remoteSyncRefreshQueuedTimer = null;
        let remoteSyncRefreshInFlight = false;
        let lastRemoteSyncRefreshAt = 0;
        let hasWindowFocusedOnce = false;
        let latestSettings = null;
        let authState = {
            authenticated: false,
            user: null,
            providers: {
                google_enabled: false,
                email_enabled: false,
                phone_enabled: false,
                email_delivery_mode: 'disabled',
                phone_delivery_mode: 'disabled',
            },
        };
        let authMode = 'email';
        let hasLoadedAuthenticatedData = false;
        let authBootstrapComplete = false;
        let authUnauthorizedNoticeShown = false;
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
        const MOBILE_CAPTURE_SELECTED_FOLDER_STORAGE_KEY = 'everything-grabber-mobile-folder-selection-v1';
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
        const defaultSidebarAvatar = sidebarAvatarImage ? sidebarAvatarImage.getAttribute('src') : '';
