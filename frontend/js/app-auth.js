        function getRequestUrl(input) {
            if (typeof input === 'string') return input;
            if (input instanceof Request) return input.url;
            return input?.url || '';
        }

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

        function isAuthEndpoint(url) {
            return String(url || '').includes('/api/auth/');
        }

        const authAwareFetch = window.fetch;
        window.fetch = async function(input, init) {
            const response = await authAwareFetch(input, init);
            const requestUrl = getRequestUrl(input);
            if (response.status === 401 && !isAuthEndpoint(requestUrl)) {
                handleUnauthorizedState();
            }
            return response;
        };

        function applyAuthState(sessionData) {
            authState = createLocalAuthState(sessionData || {});
            const user = authState.user || {};
            sidebarUserName.textContent = user.display_name || '本地收录库';
            sidebarUserSubtitle.textContent = '本地模式';
            if (sidebarAvatarImage) {
                sidebarAvatarImage.src = user.avatar_url || defaultSidebarAvatar;
            }
            if (sidebarUserStatusDot) {
                sidebarUserStatusDot.classList.remove('is-offline');
            }
            if (sidebarLogoutBtn) {
                sidebarLogoutBtn.classList.add('is-hidden');
            }
        }

        function resetAuthenticatedAppState(message = '正在连接本地资料库...') {
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
            setStatsMessage('连接本地资料库中');
            grid.className = currentView === 'gallery' ? 'grid' : 'list-view';
            grid.innerHTML = `<div class="empty-state">${message}</div>`;
            folderList.innerHTML = '<div class="folder-loading">正在加载本地文件夹...</div>';
            folderMobileStrip.innerHTML = '';
        }

        function ensureAuthenticated() {
            return Boolean(authState.authenticated);
        }

        async function refreshAuthSession(options = {}) {
            const { silent = false } = options;
            try {
                const response = await fetch('/api/auth/session');
                const data = response.ok ? await response.json() : createLocalAuthState({ authenticated: false });
                applyAuthState(data.authenticated ? data : createLocalAuthState({ authenticated: false }));
                return authState;
            } catch (error) {
                console.error('Failed to refresh local session', error);
                applyAuthState(createLocalAuthState({ authenticated: false }));
                if (!silent) {
                    showToast('无法检查本地会话，正在尝试恢复。', 'info');
                }
                return authState;
            }
        }

        async function provisionLocalSession(options = {}) {
            const { silent = false } = options;
            try {
                const response = await fetch('/api/auth/auto-session', { method: 'POST' });
                const data = response.ok ? await response.json() : createLocalAuthState({ authenticated: false });
                applyAuthState(data.authenticated ? data : createLocalAuthState({ authenticated: false }));
                return authState;
            } catch (error) {
                console.error('Failed to provision local session', error);
                applyAuthState(createLocalAuthState({ authenticated: false }));
                if (!silent) {
                    showToast('无法初始化本地会话', 'error');
                }
                return authState;
            }
        }

        async function bootstrapAuthenticatedData(options = {}) {
            const { force = false } = options;
            if (!authState.authenticated) {
                resetAuthenticatedAppState('无法连接到本地资料库。');
                return;
            }
            if (hasLoadedAuthenticatedData && !force) return;
            hasLoadedAuthenticatedData = true;
            await Promise.all([loadSettings({ includeNotionDatabases: false }), fetchFolders(), fetchItems()]);
        }

        async function handleUnauthorizedState() {
            if (authUnauthorizedNoticeShown) return;
            authUnauthorizedNoticeShown = true;
            applyAuthState(createLocalAuthState({ authenticated: false }));
            resetAuthenticatedAppState('本地会话已断开，正在自动恢复...');
            try {
                const session = await provisionLocalSession({ silent: true });
                if (session.authenticated) {
                    await bootstrapAuthenticatedData({ force: true });
                    showToast('本地会话已自动恢复。', 'info');
                } else {
                    showToast('无法恢复本地会话', 'error');
                }
            } catch (error) {
                showToast('无法恢复本地会话', 'error');
            } finally {
                window.setTimeout(() => {
                    authUnauthorizedNoticeShown = false;
                }, 1500);
            }
        }

        function openSettingsPanel() {
            if (!ensureAuthenticated()) return;
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
                if (currentSession.authenticated) {
                    const settings = await loadSettings({ includeNotionDatabases: false });
                    if (settings?.notion_ready) {
                        showToast('Notion 授权成功，已可直接同步。', 'success');
                    } else {
                        showToast('Notion 授权成功，但还需要选择一个同步目标才能同步。', 'info');
                    }
                }
            } else if (notionAuth === 'partial') {
                handled = true;
                if (currentSession.authenticated) {
                    await loadSettings({ includeNotionDatabases: false });
                    showToast('Notion 授权成功，但当前还缺少同步目标。请在设置里选择一个页面或数据库。', 'info');
                }
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
            applyAuthState(createLocalAuthState({ authenticated: false }));
            resetAuthenticatedAppState();
            updateSidebarState();
            updateCommandPaletteState();
            if (typeof startMobileCaptureAutomation === 'function' && window.matchMedia('(max-width: 860px)').matches) {
                startMobileCaptureAutomation();
            }

            let session = await refreshAuthSession({ silent: true });
            if (!session.authenticated) {
                session = await provisionLocalSession({ silent: true });
            }
            if (session.authenticated) {
                await bootstrapAuthenticatedData({ force: true });
                if (typeof flushMobileCaptureQueue === 'function') {
                    await flushMobileCaptureQueue({ silent: true });
                }
            } else {
                resetAuthenticatedAppState('无法初始化本地资料库连接。');
            }

            await handleUrlCallbacks(session);
            authBootstrapComplete = true;
        }
