        function applySecretInputState(input, hasSavedSecret, emptyPlaceholder, savedPlaceholder) {
            if (!input) return;
            input.value = '';
            input.placeholder = hasSavedSecret ? savedPlaceholder : emptyPlaceholder;
            input.dataset.hasSavedSecret = hasSavedSecret ? 'true' : 'false';
        }

        function setGoogleOAuthStatus(data) {
            if (!googleOauthStatusText) return;
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

        const syncAllNotionBtn = document.getElementById('syncAllNotionBtn');
        const syncAllObsidianBtn = document.getElementById('syncAllObsidianBtn');
        const aiBaseUrlInput = document.getElementById('aiBaseUrl');
        const aiModelInput = document.getElementById('aiModel');
        const aiModelSelect = document.getElementById('aiModelSelect');
        const aiModelModeHint = document.getElementById('aiModelModeHint');
        let bulkSyncInFlightTarget = null;

        const AI_PROVIDER_MODEL_PRESETS = [
            {
                key: 'infini-ai-coding',
                label: 'Infini AI Coding',
                matches: (baseUrl) => baseUrl.includes('cloud.infini-ai.com/maas/coding/v1'),
                models: [
                    'deepseek-v3.2',
                    'deepseek-v3.2-thinking',
                    'glm-4.7',
                    'minimax-m2.1',
                    'kimi-k2.5',
                    'glm-5',
                    'minimax-m2.5',
                ],
            },
            {
                key: 'openai',
                label: 'OpenAI',
                matches: (baseUrl) => baseUrl.includes('api.openai.com'),
                models: [
                    'gpt-5',
                    'gpt-5-mini',
                    'gpt-5-nano',
                    'gpt-4.1',
                    'gpt-4.1-mini',
                    'gpt-4.1-nano',
                    'gpt-4o',
                    'gpt-4o-mini',
                ],
            },
            {
                key: 'anthropic-compatible',
                label: 'Claude Compatible',
                matches: (baseUrl) => baseUrl.includes('anthropic') || baseUrl.includes('claude'),
                models: [
                    'claude-opus-4-1',
                    'claude-sonnet-4',
                    'claude-3-7-sonnet',
                    'claude-3-5-haiku',
                ],
            },
            {
                key: 'minimax',
                label: 'MiniMax',
                matches: (baseUrl) => baseUrl.includes('minimax'),
                models: [
                    'minimax-m2.5',
                    'minimax-m2.1',
                    'MiniMax-M1',
                    'abab6.5s-chat',
                ],
            },
        ];

        function normalizeAiBaseUrlForPreset(value) {
            return String(value || '').trim().toLowerCase().replace(/\/+$/, '');
        }

        function detectAiProviderPreset(baseUrl) {
            const normalized = normalizeAiBaseUrlForPreset(baseUrl);
            if (!normalized) return null;
            return AI_PROVIDER_MODEL_PRESETS.find((preset) => {
                try {
                    return preset.matches(normalized);
                } catch (error) {
                    return false;
                }
            }) || null;
        }

        function setAiModelFieldMode(baseUrl, currentModel = '') {
            if (!aiModelInput || !aiModelSelect) return;

            const preset = detectAiProviderPreset(baseUrl);
            const normalizedCurrentModel = String(currentModel || aiModelInput.value || '').trim();

            if (!preset) {
                aiModelSelect.style.display = 'none';
                aiModelInput.style.display = '';
                if (normalizedCurrentModel) {
                    aiModelInput.value = normalizedCurrentModel;
                }
                if (aiModelModeHint) {
                    aiModelModeHint.textContent = '当前为手动输入。';
                }
                return;
            }

            const options = [...preset.models];
            if (normalizedCurrentModel && !options.includes(normalizedCurrentModel)) {
                options.unshift(normalizedCurrentModel);
            }

            aiModelSelect.innerHTML = options
                .map((model) => `<option value="${escapeAttribute(model)}">${escapeHtml(model)}</option>`)
                .join('');
            aiModelSelect.value = normalizedCurrentModel && options.includes(normalizedCurrentModel)
                ? normalizedCurrentModel
                : options[0];
            aiModelInput.value = aiModelSelect.value;
            aiModelSelect.style.display = '';
            aiModelInput.style.display = 'none';
            if (aiModelModeHint) {
                aiModelModeHint.textContent = '已切换为预设模型。';
            }
        }

        function getAiModelValue() {
            if (!aiModelInput || !aiModelSelect) return '';
            const preset = detectAiProviderPreset(aiBaseUrlInput?.value || '');
            if (preset) {
                aiModelInput.value = aiModelSelect.value || aiModelInput.value || '';
            }
            return String(aiModelInput.value || '').trim();
        }

        function refreshBulkSyncButtons() {
            if (syncAllNotionBtn) {
                syncAllNotionBtn.disabled = bulkSyncInFlightTarget !== null || !latestSettings?.notion_ready;
                syncAllNotionBtn.textContent = bulkSyncInFlightTarget === 'notion'
                    ? '同步中...'
                    : '同步 Notion';
            }
            if (syncAllObsidianBtn) {
                syncAllObsidianBtn.disabled = bulkSyncInFlightTarget !== null || !latestSettings?.obsidian_ready;
                syncAllObsidianBtn.textContent = bulkSyncInFlightTarget === 'obsidian'
                    ? '同步中...'
                    : '同步 Obsidian';
            }
        }

        function setNotionStatus(data) {
            if (data?.notion_ready) {
                notionStatusText.textContent = '已同步';
                notionStatusText.style.color = '#1f7a4d';
                return;
            }

            notionStatusText.textContent = '未同步';
            notionStatusText.style.color = '#6b7280';
        }

        function setObsidianStatus(data) {
            if (data?.obsidian_ready) {
                obsidianStatusText.textContent = '已同步';
                obsidianStatusText.style.color = '#1f7a4d';
                setObsidianTargetHint(data);
                return;
            }

            obsidianStatusText.textContent = '未同步';
            obsidianStatusText.style.color = '#6b7280';
            setObsidianTargetHint(data);
        }

        function setAiKnowledgeBaseHint(data) {
            const hint = document.getElementById('aiKnowledgeBaseHint');
            if (!hint) return;
            const knowledgeBasePath = String(data?.ai_knowledge_base_path || '').trim();
            if (knowledgeBasePath) {
                hint.textContent = `知识库：${knowledgeBasePath}`;
                hint.style.color = '#6b7280';
                return;
            }
            hint.textContent = '未识别知识库目录';
            hint.style.color = '#6b7280';
        }

        function setAiStatus(data) {
            const status = document.getElementById('aiStatusText');
            if (!status) return;

            setAiKnowledgeBaseHint(data);

            if (data?.ai_ready && data?.ai_knowledge_base_available) {
                status.textContent = '已配置';
                status.style.color = '#1f7a4d';
                return;
            }

            status.textContent = '未配置';
            status.style.color = '#6b7280';
        }

        function applyAiAgentPermissionInputs(data) {
            const manageFolders = document.getElementById('aiAgentCanManageFolders');
            const parseContent = document.getElementById('aiAgentCanParseContent');
            const syncObsidian = document.getElementById('aiAgentCanSyncObsidian');
            const syncNotion = document.getElementById('aiAgentCanSyncNotion');
            if (manageFolders) manageFolders.checked = data?.ai_agent_can_manage_folders !== false;
            if (parseContent) parseContent.checked = data?.ai_agent_can_parse_content !== false;
            if (syncObsidian) syncObsidian.checked = Boolean(data?.ai_agent_can_sync_obsidian);
            if (syncNotion) syncNotion.checked = Boolean(data?.ai_agent_can_sync_notion);
        }

        function setObsidianTargetHint(data) {
            const baseUrl = (data?.obsidian_rest_api_url || document.getElementById('obsidianApiUrl').value || '').trim();
            const folderPath = (data?.obsidian_folder_path || obsidianFolderPathInput.value || '').trim().replace(/^\/+|\/+$/g, '');
            const locationText = folderPath
                ? `写入位置：/${folderPath}`
                : '写入位置：根目录';

            if (!baseUrl) {
                obsidianTargetHint.textContent = '未设置写入位置';
                return;
            }

            obsidianTargetHint.textContent = locationText;
        }

        function setNotionTargetHint(databases = [], selectedValue = '') {
            const normalizedValue = (selectedValue || notionDbSelect.value || notionDbIdInput.value || '').trim();
            const matched = databases.find((database) =>
                database.id === normalizedValue || database.url === normalizedValue
            );
            const hasDatabaseTarget = databases.some((database) => database.object === 'database');

            if (matched?.object === 'database') {
                notionTargetHint.textContent = `目标：${matched.title || '未命名数据库'}`;
                notionTargetHint.style.color = '#1f7a4d';
                return;
            }

            if (matched?.object === 'page') {
                notionTargetHint.textContent = `目标页：${matched.title || '未命名页面'}`;
                notionTargetHint.style.color = '#6b7280';
                return;
            }

            if (databases.length && !hasDatabaseTarget) {
                notionTargetHint.textContent = '未找到数据库目标';
                notionTargetHint.style.color = '#6b7280';
                return;
            }

            if (normalizedValue) {
                notionTargetHint.textContent = '目标待校验';
                notionTargetHint.style.color = '#6b7280';
                return;
            }

            notionTargetHint.textContent = '未选择目标';
            notionTargetHint.style.color = '#6b7280';
        }

        async function loadNotionDatabases(selectedValue = '') {
            notionDbSelect.innerHTML = '<option value="">先授权，再选择目标</option>';
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
                    notionDbSelect.innerHTML = '<option value="">没有可用目标</option>';
                    setNotionTargetHint([], selectedValue);
                    return [];
                }
                notionDbSelect.innerHTML = '<option value="">选择目标</option>';
                for (const database of databases) {
                    const option = document.createElement('option');
                    option.value = database.id;
                    const shortId = database.id ? database.id.slice(0, 8) : '未知';
                    const objectLabel = database.object === 'database' ? '数据库' : '页面';
                    option.textContent = `${database.title || '未命名'} [${objectLabel}] (${shortId})`;
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

        async function loadSettings(options = {}) {
            const { includeNotionDatabases = false } = options;
            if (!ensureAuthenticated({ showOverlay: false })) return null;
            try {
                const res = await fetch('/api/settings');
                if (res.ok) {
                    const data = await res.json();
                    latestSettings = data;
                    if (googleOauthClientIdInput) {
                        googleOauthClientIdInput.value = data.google_oauth_client_id || '';
                    }
                    applySecretInputState(
                        googleOauthClientSecretInput,
                        Boolean(data.google_oauth_client_secret_saved),
                        'GOCSPX-...',
                        '已保存，留空则保留当前 Client Secret'
                    );
                    if (googleOauthRedirectUriInput) {
                        googleOauthRedirectUriInput.value = data.google_oauth_redirect_uri || '';
                    }
                    applySecretInputState(
                        document.getElementById('notionApiToken'),
                        Boolean(data.notion_api_token_saved),
                        '尚未授权',
                        '已授权，出于安全原因不回显'
                    );
                    document.getElementById('notionClientId').value = data.notion_client_id || '';
                    applySecretInputState(
                        document.getElementById('notionClientSecret'),
                        Boolean(data.notion_client_secret_saved),
                        '输入客户端密钥',
                        '已保存，留空则保留当前密钥'
                    );
                    document.getElementById('notionRedirectUri').value = data.notion_redirect_uri || '';
                    notionDbIdInput.value = data.notion_database_id || '';
                    document.getElementById('obsidianApiUrl').value = data.obsidian_rest_api_url || '';
                    applySecretInputState(
                        document.getElementById('obsidianApiKey'),
                        Boolean(data.obsidian_api_key_saved),
                        '输入密钥',
                        '已保存，留空则保留当前密钥'
                    );
                    document.getElementById('obsidianFolderPath').value = data.obsidian_folder_path || '';
                    aiBaseUrlInput.value = data.ai_base_url || data.ai_base_url_suggestion || '';
                    aiModelInput.value = data.ai_model || (Array.isArray(data.ai_model_options) ? (data.ai_model_options[0] || '') : '');
                    setAiModelFieldMode(aiBaseUrlInput.value, aiModelInput.value);
                    applySecretInputState(
                        document.getElementById('aiApiKey'),
                        Boolean(data.ai_api_key_saved),
                        '输入密钥',
                        '已保存，留空则保留当前密钥'
                    );
                    applyAiAgentPermissionInputs(data);
                    document.getElementById('autoSyncTarget').value = data.auto_sync_target || 'none';
                    setGoogleOAuthStatus(data);
                    setNotionStatus(data);
                    setObsidianStatus(data);
                    setAiStatus(data);
                    refreshBulkSyncButtons();
                    if (includeNotionDatabases) {
                        await loadNotionDatabases(data.notion_database_id || '');
                    }
                    return data;
                }
            } catch (e) {
                console.error("Failed to load settings", e);
            }
            return null;
        }

        function closeSettingsPanel() {
            settingsOverlay.classList.remove('active');
        }

        settingsBtn?.addEventListener('click', () => {
            openSettingsPanel();
        });

        closeSettingsModal.onclick = () => {
            closeSettingsPanel();
        };

        settingsOverlay?.addEventListener('wheel', (event) => {
            if (!settingsOverlay.classList.contains('active')) return;
            const settingsMainGrid = document.querySelector('.settings-main-grid');
            if (!settingsMainGrid) return;
            if (event.target instanceof Element && event.target.closest('.settings-main-grid')) return;
            event.preventDefault();
            settingsMainGrid.scrollTop += event.deltaY;
        }, { passive: false });

        document.querySelectorAll('.settings-nav-link').forEach((link) => {
            link.addEventListener('click', (event) => {
                const selector = link.getAttribute('href');
                if (!selector || !selector.startsWith('#')) return;
                const target = document.querySelector(selector);
                if (!target) return;

                event.preventDefault();
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
        });

        btnSaveSettings.onclick = async () => {
            const payload = {
                notion_client_id: document.getElementById('notionClientId').value.trim() || null,
                notion_redirect_uri: document.getElementById('notionRedirectUri').value.trim() || null,
                notion_database_id: notionDbIdInput.value.trim() || null,
                obsidian_rest_api_url: document.getElementById('obsidianApiUrl').value.trim() || null,
                obsidian_folder_path: document.getElementById('obsidianFolderPath').value.trim() || null,
                ai_base_url: aiBaseUrlInput.value.trim() || null,
                ai_model: getAiModelValue() || null,
                ai_agent_can_manage_folders: document.getElementById('aiAgentCanManageFolders').checked,
                ai_agent_can_parse_content: document.getElementById('aiAgentCanParseContent').checked,
                ai_agent_can_sync_obsidian: document.getElementById('aiAgentCanSyncObsidian').checked,
                ai_agent_can_sync_notion: document.getElementById('aiAgentCanSyncNotion').checked,
                auto_sync_target: document.getElementById('autoSyncTarget').value
            };
            if (googleOauthClientIdInput) {
                payload.google_oauth_client_id = googleOauthClientIdInput.value.trim() || null;
            }
            if (googleOauthRedirectUriInput) {
                payload.google_oauth_redirect_uri = googleOauthRedirectUriInput.value.trim() || null;
            }
            const googleOauthClientSecret = googleOauthClientSecretInput?.value.trim() || '';
            const notionClientSecret = document.getElementById('notionClientSecret').value.trim();
            const obsidianApiKey = document.getElementById('obsidianApiKey').value.trim();
            const aiApiKey = document.getElementById('aiApiKey').value.trim();
            if (googleOauthClientSecret) payload.google_oauth_client_secret = googleOauthClientSecret;
            if (notionClientSecret) payload.notion_client_secret = notionClientSecret;
            if (obsidianApiKey) payload.obsidian_api_key = obsidianApiKey;
            if (aiApiKey) payload.ai_api_key = aiApiKey;
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
                    setAiStatus(data);
                    setAiModelFieldMode(data.ai_base_url || data.ai_base_url_suggestion || '', data.ai_model || '');
                    applyAiAgentPermissionInputs(data);
                    refreshBulkSyncButtons();
                    await loadNotionDatabases(data.notion_database_id || '');
                    if (typeof refreshAiAssistantUi === 'function') {
                        refreshAiAssistantUi();
                    }
                    await refreshAuthSession({ silent: true });
                    showToast('设置已保存。', 'success');
                    closeSettingsPanel();
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
            btn.innerText = "连接中...";
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
                    btn.innerText = "连接 Notion";
                }
            } catch (e) {
                showToast('请求出错: ' + e.message, 'error');
                btn.disabled = false;
                btn.innerText = "连接 Notion";
            }
        };

        function getCurrentNotionOptions() {
            return Array.from(notionDbSelect.options)
                .filter((option) => option.value)
                .map((option) => ({
                    id: option.value,
                    object: option.textContent.includes('[数据库]') ? 'database' : 'page',
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
                showToast('当前目标不在可用列表中，请检查共享设置。', 'info');
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
                showToast('Obsidian 验证成功', 'success');
            } catch (error) {
                showToast(`Obsidian 验证失败: ${error.message}`, 'error');
            } finally {
                testObsidianBtn.disabled = false;
                testObsidianBtn.innerText = '验证 Obsidian';
            }
        };

        async function runBulkSync(target) {
            if (bulkSyncInFlightTarget) return;
            bulkSyncInFlightTarget = target;
            refreshBulkSyncButtons();
            try {
                const response = await fetch(`/api/connect/${target}/sync-all`, { method: 'POST' });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || '批量同步失败');
                }

                const syncedCount = Number(data.synced_count || 0);
                const skippedCount = Number(data.skipped_count || 0);
                const failedCount = Number(data.failed_count || 0);
                const firstError = failedCount && Array.isArray(data.errors) && data.errors[0]?.message
                    ? ` 首个失败：${String(data.errors[0].message).slice(0, 120)}`
                    : '';
                showToast(
                    `${target === 'notion' ? 'Notion' : 'Obsidian'} 全量同步完成：写入或更新 ${syncedCount} 条，未改动 ${skippedCount} 条${failedCount ? `，失败 ${failedCount} 条` : ''}${firstError}`,
                    failedCount ? 'info' : 'success'
                );
                await fetchItems();
                if (currentOpenItemId) {
                    const refreshedItem = itemsData.find((item) => item.id === currentOpenItemId);
                    if (refreshedItem) {
                        openModalByItem(refreshedItem, { preserveSidebarTab: true });
                    }
                }
            } catch (error) {
                showToast(`${target === 'notion' ? 'Notion' : 'Obsidian'} 批量同步失败: ${error.message}`, 'error');
            } finally {
                bulkSyncInFlightTarget = null;
                refreshBulkSyncButtons();
            }
        }

        syncAllNotionBtn?.addEventListener('click', () => runBulkSync('notion'));
        syncAllObsidianBtn?.addEventListener('click', () => runBulkSync('obsidian'));
        aiBaseUrlInput?.addEventListener('input', () => {
            setAiModelFieldMode(aiBaseUrlInput.value, getAiModelValue());
        });
        aiBaseUrlInput?.addEventListener('change', () => {
            setAiModelFieldMode(aiBaseUrlInput.value, getAiModelValue());
        });
        aiModelSelect?.addEventListener('change', () => {
            aiModelInput.value = aiModelSelect.value || '';
        });
        aiModelInput?.addEventListener('input', () => {
            if (aiModelSelect && aiModelSelect.style.display !== 'none') {
                aiModelSelect.value = aiModelInput.value || aiModelSelect.value;
            }
        });

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
