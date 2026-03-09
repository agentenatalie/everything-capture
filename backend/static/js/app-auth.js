        function getRequestUrl(input) {
            if (typeof input === 'string') return input;
            if (input instanceof Request) return input.url;
            return input?.url || '';
        }

        function createEmptyAuthState(overrides = {}) {
            const nextProviders = overrides.providers || authState.providers || {};
            return {
                authenticated: false,
                user: null,
                providers: {
                    google_enabled: Boolean(nextProviders.google_enabled),
                    email_enabled: Boolean(nextProviders.email_enabled),
                    phone_enabled: Boolean(nextProviders.phone_enabled),
                    email_delivery_mode: nextProviders.email_delivery_mode || 'disabled',
                    phone_delivery_mode: nextProviders.phone_delivery_mode || 'disabled',
                },
                ...overrides,
            };
        }

        function isAuthEndpoint(url) {
            return String(url || '').includes('/api/auth/');
        }

        window.fetch = async function authAwareFetch(input, init) {
            const response = await nativeFetch(input, init);
            const requestUrl = getRequestUrl(input);
            if (response.status === 401 && !isAuthEndpoint(requestUrl)) {
                handleUnauthorizedState();
            }
            return response;
        };

        function setAuthStatus(element, message = '', tone = '') {
            if (!element) return;
            element.textContent = message;
            element.className = 'auth-status';
            if (tone) element.classList.add(`is-${tone}`);
        }

        function updateAuthProviderHint(providers) {
            const hints = [];
            if (providers.google_enabled) {
                hints.push('Google OAuth 已启用');
            } else {
                hints.push('Google OAuth 尚未配置，可先用邮箱或手机号登录后到设置页启用');
            }
            if (providers.email_enabled) {
                hints.push(providers.email_delivery_mode === 'dev' ? '邮箱验证码当前走开发模式' : '邮箱验证码将通过邮件发送');
            }
            if (providers.phone_enabled) {
                hints.push(providers.phone_delivery_mode === 'dev' ? '短信验证码当前走开发模式' : '短信验证码将通过 Twilio 发送');
            }
            authProviderHint.textContent = hints.length
                ? hints.join(' · ')
                : '当前没有可用登录方式。请先配置 Google OAuth、SMTP 或 Twilio。';
        }

        function setAuthMode(mode = 'email') {
            const nextMode = mode === 'phone' ? 'phone' : 'email';
            const providers = authState.providers || {};
            if (nextMode === 'phone' && !providers.phone_enabled && providers.email_enabled) {
                authMode = 'email';
            } else if (nextMode === 'email' && !providers.email_enabled && providers.phone_enabled) {
                authMode = 'phone';
            } else {
                authMode = nextMode;
            }

            const emailActive = authMode === 'email';
            authModeEmailBtn.classList.toggle('active', emailActive);
            authModePhoneBtn.classList.toggle('active', !emailActive);
            emailAuthForm.classList.toggle('active', emailActive);
            phoneAuthForm.classList.toggle('active', !emailActive);
            emailAuthForm.hidden = !emailActive;
            phoneAuthForm.hidden = emailActive;
        }

        function applyAuthProviderAvailability(providers) {
            authGoogleBtn.disabled = !providers.google_enabled;
            authModeEmailBtn.disabled = !providers.email_enabled;
            authModePhoneBtn.disabled = !providers.phone_enabled;
            authEmailRequestBtn.disabled = !providers.email_enabled;
            authEmailVerifyBtn.disabled = !providers.email_enabled;
            authPhoneRequestBtn.disabled = !providers.phone_enabled;
            authPhoneVerifyBtn.disabled = !providers.phone_enabled;

            if (authMode === 'email' && !providers.email_enabled && providers.phone_enabled) {
                setAuthMode('phone');
            } else if (authMode === 'phone' && !providers.phone_enabled && providers.email_enabled) {
                setAuthMode('email');
            } else {
                setAuthMode(authMode);
            }
            updateAuthProviderHint(providers);
        }

        function formatAuthPrimary(user) {
            if (!user) return '未登录';
            if (isLocalDefaultUser(user)) return '本地收录库';
            return user.display_name || user.email || user.phone_e164 || '已登录';
        }

        function formatAuthSecondary(user) {
            if (!user) return '请先登录';
            if (isLocalDefaultUser(user)) return '本地模式 · 自动进入';
            return user.email || user.phone_e164 || '已登录';
        }

        function isLocalDefaultUser(user) {
            return Boolean(user?.id === 'local-default-user');
        }

        function applyAuthState(sessionData) {
            authState = createEmptyAuthState(sessionData || {});
            applyAuthProviderAvailability(authState.providers);

            const user = authState.user;
            sidebarUserName.textContent = formatAuthPrimary(user);
            sidebarUserSubtitle.textContent = formatAuthSecondary(user);
            sidebarAvatarImage.src = user?.avatar_url || defaultSidebarAvatar;
            sidebarUserStatusDot.classList.toggle('is-offline', !authState.authenticated);
            sidebarLogoutBtn.classList.toggle('is-hidden', !authState.authenticated || isLocalDefaultUser(user));
        }

        function focusAuthInput() {
            const target = authMode === 'phone' ? authPhoneInput : authEmailInput;
            requestAnimationFrame(() => target?.focus());
        }

        function closeTransientPanels() {
            if (commandOverlay.classList.contains('active')) closeCommandPalette();
            if (folderPickerOverlay.classList.contains('active')) closeFolderPickerDialog();
            if (settingsOverlay.classList.contains('active')) settingsOverlay.classList.remove('active');
            if (modalOverlay.classList.contains('active')) closeModalDialog();
        }

        function showAuthOverlay(mode = authMode) {
            closeTransientPanels();
            setAuthMode(mode);
            authOverlay.classList.add('active');
            focusAuthInput();
        }

        function hideAuthOverlay() {
            authOverlay.classList.remove('active');
        }

        function resetAuthenticatedAppState(message = '请先登录后查看你的资料库。') {
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
            closeTransientPanels();
            setStatsMessage('请先登录');
            grid.className = currentView === 'gallery' ? 'grid' : 'list-view';
            grid.innerHTML = `<div class="empty-state">${message}</div>`;
            folderList.innerHTML = '<div class="folder-loading">登录后显示文件夹</div>';
            folderMobileStrip.innerHTML = '';
        }

        function ensureAuthenticated(options = {}) {
            const { showOverlay = true, mode = authMode } = options;
            if (authState.authenticated) return true;
            if (showOverlay) showAuthOverlay(mode);
            return false;
        }

        async function refreshAuthSession(options = {}) {
            const { silent = false } = options;
            try {
                const response = await nativeFetch('/api/auth/session');
                const data = response.ok ? await response.json() : createEmptyAuthState();
                applyAuthState(data);
                if (authState.authenticated) {
                    hideAuthOverlay();
                } else if (!silent) {
                    showAuthOverlay(authMode);
                }
                return authState;
            } catch (error) {
                console.error('Failed to refresh auth session', error);
                applyAuthState(createEmptyAuthState());
                if (!silent) {
                    showAuthOverlay(authMode);
                    showToast('无法连接到认证服务', 'error');
                }
                return authState;
            }
        }

        async function provisionLocalSession(options = {}) {
            const { silent = false } = options;
            try {
                const response = await nativeFetch('/api/auth/auto-session', { method: 'POST' });
                const data = response.ok ? await response.json() : createEmptyAuthState();
                applyAuthState(data);
                if (authState.authenticated) {
                    hideAuthOverlay();
                }
                return authState;
            } catch (error) {
                console.error('Failed to provision local session', error);
                applyAuthState(createEmptyAuthState());
                if (!silent) {
                    showToast('无法初始化本地会话', 'error');
                }
                return authState;
            }
        }

        async function bootstrapAuthenticatedData(options = {}) {
            const { force = false } = options;
            if (!authState.authenticated) {
                resetAuthenticatedAppState();
                return;
            }
            if (hasLoadedAuthenticatedData && !force) return;
            hasLoadedAuthenticatedData = true;
            await Promise.all([fetchFolders(), fetchItems()]);
        }

        function clearAuthInputs() {
            authEmailCodeInput.value = '';
            authPhoneCodeInput.value = '';
            setAuthStatus(authEmailStatus);
            setAuthStatus(authPhoneStatus);
        }

        async function handleAuthenticatedSession(sessionData, successMessage) {
            applyAuthState(sessionData);
            clearAuthInputs();
            hideAuthOverlay();
            await bootstrapAuthenticatedData({ force: true });
            if (successMessage) showToast(successMessage, 'success');
        }

        function handleUnauthorizedState() {
            if (authUnauthorizedNoticeShown) return;
            authUnauthorizedNoticeShown = true;
            const providerSnapshot = authState.providers;
            applyAuthState(createEmptyAuthState({ providers: providerSnapshot }));
            resetAuthenticatedAppState('会话已断开，正在重新连接本地资料库...');
            provisionLocalSession({ silent: true })
                .then((session) => {
                    if (session.authenticated) {
                        return bootstrapAuthenticatedData({ force: true });
                    }
                    showToast('无法恢复本地会话', 'error');
                    return null;
                })
                .catch(() => {});
            if (authBootstrapComplete) {
                showToast('会话已刷新，已尝试自动恢复。', 'info');
            }
            window.setTimeout(() => {
                authUnauthorizedNoticeShown = false;
            }, 1500);
        }

        async function logoutCurrentUser() {
            sidebarLogoutBtn.disabled = true;
            try {
                await fetch('/api/auth/logout', { method: 'POST' });
            } catch (error) {
                console.error('Failed to logout', error);
            } finally {
                sidebarLogoutBtn.disabled = false;
            }
            applyAuthState(createEmptyAuthState({ providers: authState.providers }));
            resetAuthenticatedAppState('你已退出登录。重新登录后可继续访问你的资料库。');
            await refreshAuthSession({ silent: true });
            showAuthOverlay(authMode);
            showToast('已退出登录', 'success');
        }

        function openSettingsPanel() {
            if (!ensureAuthenticated({ mode: 'email' })) return;
            settingsOverlay.classList.add('active');
            loadSettings();
        }

        async function requestEmailCode() {
            const email = authEmailInput.value.trim();
            if (!email) {
                setAuthStatus(authEmailStatus, '请输入邮箱地址', 'error');
                return;
            }

            authEmailRequestBtn.disabled = true;
            setAuthStatus(authEmailStatus, '发送中...');
            try {
                const response = await fetch('/api/auth/email/request-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || '发送验证码失败');
                }
                let message = `验证码已发送到 ${data.target_masked}。`;
                if (data.dev_code) {
                    authEmailCodeInput.value = data.dev_code;
                    message += ` 开发模式验证码：${data.dev_code}`;
                }
                setAuthStatus(authEmailStatus, message, 'success');
                authEmailCodeInput.focus();
            } catch (error) {
                setAuthStatus(authEmailStatus, error.message, 'error');
            } finally {
                authEmailRequestBtn.disabled = false;
            }
        }

        async function verifyEmailCode(event) {
            event.preventDefault();
            const email = authEmailInput.value.trim();
            const code = authEmailCodeInput.value.trim();
            if (!email || !code) {
                setAuthStatus(authEmailStatus, '请输入邮箱和验证码', 'error');
                return;
            }

            authEmailVerifyBtn.disabled = true;
            setAuthStatus(authEmailStatus, '登录中...');
            try {
                const response = await fetch('/api/auth/email/verify-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, code }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || '邮箱登录失败');
                }
                await handleAuthenticatedSession(data, '邮箱登录成功');
            } catch (error) {
                setAuthStatus(authEmailStatus, error.message, 'error');
            } finally {
                authEmailVerifyBtn.disabled = false;
            }
        }

        async function requestPhoneCode() {
            const phone = authPhoneInput.value.trim();
            if (!phone) {
                setAuthStatus(authPhoneStatus, '请输入手机号', 'error');
                return;
            }

            authPhoneRequestBtn.disabled = true;
            setAuthStatus(authPhoneStatus, '发送中...');
            try {
                const response = await fetch('/api/auth/phone/request-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || '发送验证码失败');
                }
                let message = `验证码已发送到 ${data.target_masked}。`;
                if (data.dev_code) {
                    authPhoneCodeInput.value = data.dev_code;
                    message += ` 开发模式验证码：${data.dev_code}`;
                }
                setAuthStatus(authPhoneStatus, message, 'success');
                authPhoneCodeInput.focus();
            } catch (error) {
                setAuthStatus(authPhoneStatus, error.message, 'error');
            } finally {
                authPhoneRequestBtn.disabled = false;
            }
        }

        async function verifyPhoneCode(event) {
            event.preventDefault();
            const phone = authPhoneInput.value.trim();
            const code = authPhoneCodeInput.value.trim();
            if (!phone || !code) {
                setAuthStatus(authPhoneStatus, '请输入手机号和验证码', 'error');
                return;
            }

            authPhoneVerifyBtn.disabled = true;
            setAuthStatus(authPhoneStatus, '登录中...');
            try {
                const response = await fetch('/api/auth/phone/verify-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone, code }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || '手机号登录失败');
                }
                await handleAuthenticatedSession(data, '手机号登录成功');
            } catch (error) {
                setAuthStatus(authPhoneStatus, error.message, 'error');
            } finally {
                authPhoneVerifyBtn.disabled = false;
            }
        }

        async function handleUrlCallbacks(currentSession = authState) {
            const urlParams = new URLSearchParams(window.location.search);
            const authResult = urlParams.get('auth');
            const authProvider = urlParams.get('provider');
            const notionAuth = urlParams.get('notion_auth');
            let handled = false;

            if (authResult === 'success' && authProvider === 'google') {
                handled = true;
                if (currentSession.authenticated) {
                    showToast('Google 登录成功', 'success');
                }
            } else if (authResult === 'failed') {
                handled = true;
                const errorStr = urlParams.get('error') || 'unknown_error';
                showToast(`Google 登录失败: ${errorStr}`, 'error');
                showAuthOverlay('email');
            }

            if (notionAuth === 'success') {
                handled = true;
                if (currentSession.authenticated) {
                    const settings = await loadSettings();
                    if (settings?.notion_ready) {
                        showToast('Notion 授权成功，已可直接同步。', 'success');
                    } else {
                        showToast('Notion 授权成功，但还需要选择一个同步目标才能同步。', 'info');
                    }
                }
            } else if (notionAuth === 'partial') {
                handled = true;
                if (currentSession.authenticated) {
                    await loadSettings();
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
            applyAuthState(createEmptyAuthState());
            resetAuthenticatedAppState();
            updateSidebarState();
            updateCommandPaletteState();
            let session = await refreshAuthSession({ silent: true });
            if (!session.authenticated) {
                session = await provisionLocalSession({ silent: true });
            }
            if (session.authenticated) {
                await bootstrapAuthenticatedData({ force: true });
                if (typeof startMobileCaptureAutomation === 'function') {
                    startMobileCaptureAutomation();
                }
            } else {
                resetAuthenticatedAppState('无法初始化本地资料库连接。');
            }
            await handleUrlCallbacks(session);
            authBootstrapComplete = true;
        }
