        function applySecretInputState(input, hasSavedSecret, emptyPlaceholder, savedPlaceholder) {
            if (!input) return;
            input.value = '';
            input.placeholder = hasSavedSecret ? savedPlaceholder : emptyPlaceholder;
            input.dataset.hasSavedSecret = hasSavedSecret ? 'true' : 'false';
        }

        function setGoogleOAuthStatus(data) {
            if (data?.google_oauth_ready) {
                const managedBy = data.google_oauth_managed_by === 'env' ? '环境变量' : '设置页';
                const redirectHint = data.google_oauth_redirect_uri
                    ? ` Redirect URI：${data.google_oauth_redirect_uri}`
                    : ' Redirect URI：使用当前服务默认回调地址。';
                googleOauthStatusText.textContent = `状态：已配置，可在登录页使用 Google OAuth。来源：${managedBy}.${redirectHint}`;
                googleOauthStatusText.style.color = '#1f7a4d';
                return;
            }

            const missing = data?.google_oauth_missing_fields || [];
            if (missing.length) {
                const labels = [];
                if (missing.includes('google_oauth_client_id')) labels.push('Client ID');
                if (missing.includes('google_oauth_client_secret')) labels.push('Client Secret');
                googleOauthStatusText.textContent = `状态：未完成配置，缺少 ${labels.join(' / ')}。`;
                googleOauthStatusText.style.color = '#b7791f';
                return;
            }

            googleOauthStatusText.textContent = '状态：未配置';
            googleOauthStatusText.style.color = '#6b7280';
        }

        function setNotionStatus(data) {
            if (data?.notion_ready) {
                notionStatusText.textContent = '状态：已连接，可同步到 Notion。';
                notionStatusText.style.color = '#1f7a4d';
                return;
            }

            if (data?.notion_api_token_saved) {
                const missingDatabase = (data.notion_missing_fields || []).includes('notion_database_id');
                notionStatusText.textContent = missingDatabase
                    ? '状态：已完成 OAuth，但还没有选择同步目标，当前不能同步。'
                    : '状态：已授权，但配置仍不完整。';
                notionStatusText.style.color = '#b7791f';
                return;
            }

            notionStatusText.textContent = '状态：未连接';
            notionStatusText.style.color = '#6b7280';
        }

        function setObsidianStatus(data) {
            if (data?.obsidian_ready) {
                obsidianStatusText.textContent = '状态：已配置，可同步到 Obsidian。';
                obsidianStatusText.style.color = '#1f7a4d';
                setObsidianTargetHint(data);
                return;
            }

            const missingUrl = (data?.obsidian_missing_fields || []).includes('obsidian_rest_api_url');
            const missingKey = (data?.obsidian_missing_fields || []).includes('obsidian_api_key');
            if (missingUrl || missingKey) {
                const missingLabels = [];
                if (missingUrl) missingLabels.push('REST API URL');
                if (missingKey) missingLabels.push('API Key');
                obsidianStatusText.textContent = `状态：未完成配置，缺少 ${missingLabels.join(' / ')}。`;
                obsidianStatusText.style.color = '#b7791f';
                setObsidianTargetHint(data);
                return;
            }

            obsidianStatusText.textContent = '状态：未配置';
            obsidianStatusText.style.color = '#6b7280';
            setObsidianTargetHint(data);
        }

        function setObsidianTargetHint(data) {
            const baseUrl = (data?.obsidian_rest_api_url || document.getElementById('obsidianApiUrl').value || '').trim();
            const folderPath = (data?.obsidian_folder_path || obsidianFolderPathInput.value || '').trim().replace(/^\/+|\/+$/g, '');
            const locationText = folderPath
                ? `当前写入：当前打开的 Obsidian Vault /${folderPath}`
                : '当前写入：当前打开的 Obsidian Vault 根目录';

            if (!baseUrl) {
                obsidianTargetHint.textContent = '当前尚未配置 Obsidian REST API URL，无法判断写入位置。';
                return;
            }

            obsidianTargetHint.textContent = `${locationText}。文件名格式：标题-短ID.md。REST API：${baseUrl}`;
        }

        function setNotionTargetHint(databases = [], selectedValue = '') {
            const normalizedValue = (selectedValue || notionDbSelect.value || notionDbIdInput.value || '').trim();
            const matched = databases.find((database) =>
                database.id === normalizedValue || database.url === normalizedValue
            );
            const hasDatabaseTarget = databases.some((database) => database.object === 'database');

            if (matched?.object === 'database') {
                notionTargetHint.textContent = `当前目标是 Database: ${matched.title || 'Untitled'}。同步成功后会作为新页面写入该数据库。`;
                notionTargetHint.style.color = '#1f7a4d';
                return;
            }

            if (matched?.object === 'page') {
                notionTargetHint.textContent = `当前目标是普通 Page: ${matched.title || 'Untitled'}。同步成功后会在这个页面下创建子页面，不会写入数据库视图。若你想写入数据库，请在 Notion 中直接把数据库共享给当前集成，并重新选择那个 Database。`;
                notionTargetHint.style.color = '#b7791f';
                return;
            }

            if (databases.length && !hasDatabaseTarget) {
                notionTargetHint.textContent = '当前集成只看到了 Page，没有看到任何 Database。通常这表示你共享的是页面，而不是数据库本身。';
                notionTargetHint.style.color = '#b7791f';
                return;
            }

            if (normalizedValue) {
                notionTargetHint.textContent = '当前填写的目标尚未在可访问列表中匹配到，可能是旧 ID，保存或同步时后端会尝试自动修复。';
                notionTargetHint.style.color = '#6b7280';
                return;
            }

            notionTargetHint.textContent = '当前尚未解析到有效的 Notion 同步目标。';
            notionTargetHint.style.color = '#6b7280';
        }

        async function loadNotionDatabases(selectedValue = '') {
            notionDbSelect.innerHTML = '<option value="">先完成 OAuth，再从这里选择</option>';
            const hasToken = Boolean(latestSettings?.notion_api_token_saved);
            if (!hasToken) {
                setNotionTargetHint([], selectedValue);
                return [];
            }

            refreshNotionDbsBtn.disabled = true;
            refreshNotionDbsBtn.innerText = '刷新中...';
            try {
                const res = await fetch('/api/connect/notion/databases');
                const data = await res.json();
                if (!res.ok) {
                    console.error('Failed to load Notion databases', data.detail);
                    setNotionTargetHint([], selectedValue);
                    return [];
                }

                const databases = data.results || [];
                if (!databases.length) {
                    notionDbSelect.innerHTML = '<option value="">没有可访问的页面或数据库，请先在 Notion 中把目标页面/数据库共享给当前集成</option>';
                    setNotionTargetHint([], selectedValue);
                    return [];
                }
                notionDbSelect.innerHTML = '<option value="">选择一个 Notion 页面或数据库</option>';
                for (const database of databases) {
                    const option = document.createElement('option');
                    option.value = database.id;
                    const shortId = database.id ? database.id.slice(0, 8) : 'unknown';
                    const objectLabel = database.object === 'database' ? 'Database' : 'Page';
                    option.textContent = `${database.title || 'Untitled'} [${objectLabel}] (${shortId})`;
                    notionDbSelect.appendChild(option);
                }

                const currentValue = (selectedValue || notionDbIdInput.value || '').trim();
                const matched = databases.find((database) =>
                    database.id === currentValue || database.url === currentValue
                );
                if (matched) {
                    notionDbSelect.value = matched.id;
                }
                setNotionTargetHint(databases, currentValue);
                return databases;
            } catch (e) {
                console.error('Failed to load Notion databases', e);
                setNotionTargetHint([], selectedValue);
                return [];
            } finally {
                refreshNotionDbsBtn.disabled = false;
                refreshNotionDbsBtn.innerText = '刷新';
            }
        }

        async function loadSettings() {
            if (!ensureAuthenticated({ showOverlay: false })) return null;
            try {
                const res = await fetch('/api/settings');
                if (res.ok) {
                    const data = await res.json();
                    latestSettings = data;
                    googleOauthClientIdInput.value = data.google_oauth_client_id || '';
                    applySecretInputState(
                        googleOauthClientSecretInput,
                        Boolean(data.google_oauth_client_secret_saved),
                        'GOCSPX-...',
                        '已保存，留空则保留当前 Client Secret'
                    );
                    googleOauthRedirectUriInput.value = data.google_oauth_redirect_uri || '';
                    applySecretInputState(
                        document.getElementById('notionApiToken'),
                        Boolean(data.notion_api_token_saved),
                        'Not connected',
                        '已通过 OAuth 保存，出于安全原因不回显'
                    );
                    document.getElementById('notionClientId').value = data.notion_client_id || '';
                    applySecretInputState(
                        document.getElementById('notionClientSecret'),
                        Boolean(data.notion_client_secret_saved),
                        'secret_...',
                        '已保存，留空则保留当前 Secret'
                    );
                    document.getElementById('notionRedirectUri').value = data.notion_redirect_uri || '';
                    notionDbIdInput.value = data.notion_database_id || '';
                    document.getElementById('obsidianApiUrl').value = data.obsidian_rest_api_url || '';
                    applySecretInputState(
                        document.getElementById('obsidianApiKey'),
                        Boolean(data.obsidian_api_key_saved),
                        'Your API Key',
                        '已保存，留空则保留当前 API Key'
                    );
                    document.getElementById('obsidianFolderPath').value = data.obsidian_folder_path || '';
                    document.getElementById('autoSyncTarget').value = data.auto_sync_target || 'none';
                    setGoogleOAuthStatus(data);
                    setNotionStatus(data);
                    setObsidianStatus(data);
                    await loadNotionDatabases(data.notion_database_id || '');
                    return data;
                }
            } catch (e) {
                console.error("Failed to load settings", e);
            }
            return null;
        }

        settingsBtn.onclick = () => {
            openSettingsPanel();
        };

        closeSettingsModal.onclick = () => {
            settingsOverlay.classList.remove('active');
        };

        btnSaveSettings.onclick = async () => {
            const payload = {
                google_oauth_client_id: googleOauthClientIdInput.value.trim() || null,
                google_oauth_redirect_uri: googleOauthRedirectUriInput.value.trim() || null,
                notion_client_id: document.getElementById('notionClientId').value.trim() || null,
                notion_redirect_uri: document.getElementById('notionRedirectUri').value.trim() || null,
                notion_database_id: notionDbIdInput.value.trim() || null,
                obsidian_rest_api_url: document.getElementById('obsidianApiUrl').value.trim() || null,
                obsidian_folder_path: document.getElementById('obsidianFolderPath').value.trim() || null,
                auto_sync_target: document.getElementById('autoSyncTarget').value
            };
            const googleOauthClientSecret = googleOauthClientSecretInput.value.trim();
            const notionClientSecret = document.getElementById('notionClientSecret').value.trim();
            const obsidianApiKey = document.getElementById('obsidianApiKey').value.trim();
            if (googleOauthClientSecret) payload.google_oauth_client_secret = googleOauthClientSecret;
            if (notionClientSecret) payload.notion_client_secret = notionClientSecret;
            if (obsidianApiKey) payload.obsidian_api_key = obsidianApiKey;
            btnSaveSettings.disabled = true;
            btnSaveSettings.innerText = "保存中...";
            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    const data = await res.json();
                    latestSettings = data;
                    setGoogleOAuthStatus(data);
                    setNotionStatus(data);
                    setObsidianStatus(data);
                    await loadNotionDatabases(data.notion_database_id || '');
                    await refreshAuthSession({ silent: true });
                    if (data.notion_ready || data.obsidian_ready) {
                        showToast('设置已保存，集成已更新。', 'success');
                    } else if (data.google_oauth_ready) {
                        showToast('设置已保存，Google 登录已启用。', 'success');
                    } else {
                        showToast('设置已保存，但仍有未完成的集成配置。', 'info');
                    }
                    settingsOverlay.classList.remove('active');
                } else {
                    showToast('保存设置失败', 'error');
                }
            } catch (e) {
                showToast('保存出错: ' + e.message, 'error');
            } finally {
                btnSaveSettings.disabled = false;
                btnSaveSettings.innerText = "保存设置";
            }
        };

        document.getElementById('connectNotionBtn').onclick = async () => {
            const btn = document.getElementById('connectNotionBtn');
            btn.disabled = true;
            btn.innerText = "Connecting...";
            try {
                // First save the current OAuth credentials so the backend knows them
                const payload = {
                    notion_client_id: document.getElementById('notionClientId').value.trim() || null,
                    notion_redirect_uri: document.getElementById('notionRedirectUri').value.trim() || null
                };
                const notionClientSecret = document.getElementById('notionClientSecret').value.trim();
                if (notionClientSecret) payload.notion_client_secret = notionClientSecret;
                await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const res = await fetch('/api/connect/notion/oauth/url');
                if (res.ok) {
                    const data = await res.json();
                    window.location.href = data.url;
                } else {
                    const data = await res.json();
                    showToast('无法获取授权链接: ' + (data.detail || '检查配置'), 'error');
                    btn.disabled = false;
                    btn.innerText = "Connect to Notion";
                }
            } catch (e) {
                showToast('请求出错: ' + e.message, 'error');
                btn.disabled = false;
                btn.innerText = "Connect to Notion";
            }
        };

        function getCurrentNotionOptions() {
            return Array.from(notionDbSelect.options)
                .filter((option) => option.value)
                .map((option) => ({
                    id: option.value,
                    object: option.textContent.includes('[Database]') ? 'database' : 'page',
                    title: option.textContent
                }));
        }

        notionDbSelect.onchange = () => {
            if (notionDbSelect.value) {
                notionDbIdInput.value = notionDbSelect.value;
            }
            setNotionTargetHint(getCurrentNotionOptions(), notionDbSelect.value);
        };

        notionDbIdInput.addEventListener('input', () => {
            setNotionTargetHint(getCurrentNotionOptions(), notionDbIdInput.value.trim());
        });

        obsidianFolderPathInput.addEventListener('input', () => {
            setObsidianTargetHint({
                obsidian_rest_api_url: document.getElementById('obsidianApiUrl').value.trim(),
                obsidian_folder_path: obsidianFolderPathInput.value.trim(),
            });
        });

        refreshNotionDbsBtn.onclick = async () => {
            await loadNotionDatabases(notionDbIdInput.value.trim());
            if (!notionDbSelect.value && notionDbIdInput.value.trim()) {
                showToast('当前 Database ID/URL 已保留，但不在可访问列表中，请确认数据库已向 Notion 集成开放。', 'info');
            }
        };

        testObsidianBtn.onclick = async () => {
            testObsidianBtn.disabled = true;
            testObsidianBtn.innerText = '验证中...';
            try {
                const obsidianApiKey = document.getElementById('obsidianApiKey').value.trim();
                const response = await fetch('/api/connect/obsidian/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        obsidian_rest_api_url: document.getElementById('obsidianApiUrl').value.trim(),
                        obsidian_api_key: obsidianApiKey || undefined,
                        obsidian_folder_path: document.getElementById('obsidianFolderPath').value.trim(),
                    })
                });
                const data = await response.json();
                if (!response.ok) {
                    showToast(`Obsidian 验证失败: ${data.detail || '未知错误'}`, 'error');
                    return;
                }

                setObsidianTargetHint({
                    obsidian_rest_api_url: document.getElementById('obsidianApiUrl').value.trim(),
                    obsidian_folder_path: document.getElementById('obsidianFolderPath').value.trim(),
                });
                showToast(`Obsidian 验证成功：${data.write_location_hint}`, 'success');
            } catch (error) {
                showToast(`Obsidian 验证失败: ${error.message}`, 'error');
            } finally {
                testObsidianBtn.disabled = false;
                testObsidianBtn.innerText = '验证 Obsidian 写入';
            }
        };

        window.addEventListener('focus', () => {
            if (!hasWindowFocusedOnce) {
                hasWindowFocusedOnce = true;
                return;
            }
            scheduleRemoteSyncRefresh({ delay: 1000 });
        });

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                scheduleRemoteSyncRefresh({ delay: 1000 });
            }
        });

        remoteSyncRefreshTimer = window.setInterval(() => {
            scheduleRemoteSyncRefresh();
        }, REMOTE_SYNC_REFRESH_INTERVAL_MS);

