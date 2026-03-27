        function applySecretInputState(input, hasSavedSecret, emptyPlaceholder, savedPlaceholder) {
            if (!input) return;
            input.value = '';
            input.placeholder = hasSavedSecret ? savedPlaceholder : emptyPlaceholder;
            input.dataset.hasSavedSecret = hasSavedSecret ? 'true' : 'false';
        }

        const syncAllNotionBtn = document.getElementById('syncAllNotionBtn');
        const syncAllObsidianBtn = document.getElementById('syncAllObsidianBtn');
        const aiBaseUrlInput = document.getElementById('aiBaseUrl');
        const aiModelInput = document.getElementById('aiModel');
        const aiModelSelect = document.getElementById('aiModelSelect');
        const aiModelModeHint = document.getElementById('aiModelModeHint');
        const componentsList = document.getElementById('componentsList');
        const componentsStatusText = document.getElementById('componentsStatusText');
        const componentsCatalogHint = document.getElementById('componentsCatalogHint');
        let bulkSyncInFlightTarget = null;
        let latestComponentsCatalog = null;
        const componentTaskStateByComponentId = new Map();
        const componentTaskPollTimers = new Map();

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
                    'minimax-m2.7',
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

        function formatByteSize(sizeBytes) {
            const numericSize = Number(sizeBytes || 0);
            if (!numericSize) return '';
            if (numericSize < 1024 * 1024) {
                return `${Math.max(1, Math.round(numericSize / 1024))} KB`;
            }
            return `${(numericSize / (1024 * 1024)).toFixed(numericSize >= 1024 * 1024 * 1024 ? 1 : 0)} MB`;
        }

        function getEffectiveComponentTask(component) {
            const localTask = componentTaskStateByComponentId.get(component.id);
            if (!localTask) return component.task || null;
            if (!component.task) return localTask;
            return String(localTask.updated_at || '') >= String(component.task.updated_at || '')
                ? localTask
                : component.task;
        }

        function getComponentButtonLabel(component, task) {
            if (component.bundled) {
                return '已内置';
            }
            if (task && (task.status === 'pending' || task.status === 'running')) {
                return '安装中...';
            }
            if (task?.status === 'failed') {
                return '重试安装';
            }
            if (component.status === 'update_available') {
                return '更新组件';
            }
            if (component.status === 'installed') {
                return '已安装';
            }
            if (!component.available) {
                return '暂不可用';
            }
            return '安装组件';
        }

        function getComponentBadgeLabel(component, task) {
            if (component.bundled) return '内置';
            if (task?.status === 'pending' || task?.status === 'running') return '安装中';
            if (task?.status === 'failed') return '安装失败';
            if (component.status === 'update_available') return '可更新';
            if (component.status === 'installed') return '已安装';
            if (component.status === 'unavailable') return '未开放';
            return '未安装';
        }

        function getComponentTaskCopy(task) {
            if (!task) return '';
            const progressValue = Number(task.progress || 0);
            const progressText = progressValue > 0 && progressValue < 1
                ? ` · ${Math.round(progressValue * 100)}%`
                : '';
            if (task.status === 'failed') {
                return task.error || task.message || '组件安装失败';
            }
            return `${task.message || '处理中'}${progressText}`;
        }

        function setComponentsSummary(catalog) {
            if (!componentsStatusText || !componentsCatalogHint) return;

            const components = Array.isArray(catalog?.components) ? catalog.components : [];
            const installedCount = components.filter((component) => {
                const task = getEffectiveComponentTask(component);
                if (task?.status === 'pending' || task?.status === 'running') return false;
                return component.status === 'installed' || component.status === 'update_available' || component.status === 'bundled';
            }).length;
            const installingCount = components.filter((component) => {
                const task = getEffectiveComponentTask(component);
                return task?.status === 'pending' || task?.status === 'running';
            }).length;
            const bundledCount = components.filter((component) => component.bundled).length;

            if (!components.length) {
                componentsStatusText.textContent = '未配置';
                componentsStatusText.style.color = '#6b7280';
                componentsCatalogHint.textContent = '当前没有可用组件。';
                componentsCatalogHint.style.color = '#6b7280';
                return;
            }

            if (installingCount > 0) {
                componentsStatusText.textContent = '安装中';
                componentsStatusText.style.color = '#0f172a';
            } else if (bundledCount > 0 && installedCount === bundledCount) {
                componentsStatusText.textContent = '已内置';
                componentsStatusText.style.color = '#1f7a4d';
            } else if (installedCount > 0) {
                componentsStatusText.textContent = '已安装';
                componentsStatusText.style.color = '#1f7a4d';
            } else {
                componentsStatusText.textContent = '未安装';
                componentsStatusText.style.color = '#6b7280';
            }

            if (!catalog?.manifest_configured && bundledCount === 0) {
                componentsCatalogHint.textContent = '当前使用内置占位清单。要启用一键安装，需要配置 hosted component manifest。';
                componentsCatalogHint.style.color = '#6b7280';
                return;
            }

            if (bundledCount > 0) {
                componentsCatalogHint.textContent = `已识别 ${components.length} 个组件，其中 ${bundledCount} 个已随应用内置。`;
                componentsCatalogHint.style.color = '#6b7280';
                return;
            }

            componentsCatalogHint.textContent = installedCount > 0
                ? `已识别 ${components.length} 个组件，已安装 ${installedCount} 个。`
                : `已识别 ${components.length} 个组件。`;
            componentsCatalogHint.style.color = '#6b7280';
        }

        function renderComponentsCatalog(catalog) {
            if (!componentsList) return;

            latestComponentsCatalog = catalog;
            setComponentsSummary(catalog);
            const components = Array.isArray(catalog?.components) ? catalog.components : [];

            if (!components.length) {
                componentsList.innerHTML = '';
                return;
            }

            componentsList.innerHTML = components.map((component) => {
                const task = getEffectiveComponentTask(component);
                const isInstalling = task?.status === 'pending' || task?.status === 'running';
                const hasFailedTask = task?.status === 'failed';
                const isInstalled = (component.status === 'installed' || component.status === 'bundled') && !isInstalling;
                const buttonDisabled = component.bundled || !component.available || isInstalling || (isInstalled && !hasFailedTask);
                const latestVersion = component.latest_version ? `最新版本 ${escapeHtml(component.latest_version)}` : '未提供版本';
                const installedVersion = component.installed_version
                    ? `已装 ${escapeHtml(component.installed_version)}`
                    : '尚未安装';
                const sizeText = component.download_size_bytes ? ` · ${escapeHtml(formatByteSize(component.download_size_bytes))}` : '';
                const taskCopy = getComponentTaskCopy(task);
                const bundledCopy = component.bundled
                    ? '该组件已随桌面应用一起提供，首次打开即可直接使用。'
                    : '';
                const unavailableCopy = !component.available
                    ? escapeHtml(component.unavailable_reason || '当前尚未提供下载包。')
                    : '';

                return `
                    <div class="settings-component-card" data-component-id="${escapeAttribute(component.id)}">
                        <div class="settings-component-head">
                            <div>
                                <h4 class="settings-component-title">${escapeHtml(component.title || component.id)}</h4>
                                <div class="settings-component-meta">${latestVersion} · ${installedVersion}${sizeText}</div>
                            </div>
                            <div class="settings-component-status">${escapeHtml(getComponentBadgeLabel(component, task))}</div>
                        </div>
                        <div class="settings-component-copy">${escapeHtml(component.description || '未提供组件说明。')}</div>
                        <div class="settings-component-actions">
                            <button
                                class="extract-btn ${component.available && !isInstalled && !component.bundled ? '' : 'settings-secondary'}"
                                type="button"
                                data-component-install="${escapeAttribute(component.id)}"
                                ${buttonDisabled ? 'disabled' : ''}
                            >
                                ${escapeHtml(getComponentButtonLabel(component, task))}
                            </button>
                            ${component.requires_restart ? '<div class="settings-component-task">安装后需要重启应用。</div>' : ''}
                        </div>
                        <div class="settings-component-task">${taskCopy || bundledCopy || unavailableCopy || '安装后会自动写入组件目录并激活当前版本。'}</div>
                    </div>
                `;
            }).join('');
        }

        async function loadComponentsCatalog() {
            if (!componentsList) return null;
            try {
                const response = await fetch('/api/settings/components');
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || '加载组件清单失败');
                }
                renderComponentsCatalog(data);
                return data;
            } catch (error) {
                if (componentsCatalogHint) {
                    componentsCatalogHint.textContent = `加载组件清单失败：${error.message}`;
                    componentsCatalogHint.style.color = '#b91c1c';
                }
                if (componentsList) {
                    componentsList.innerHTML = '';
                }
                return null;
            }
        }

        async function pollComponentTask(taskId, componentId) {
            const previousTimer = componentTaskPollTimers.get(componentId);
            if (previousTimer) {
                clearTimeout(previousTimer);
            }

            try {
                const response = await fetch(`/api/settings/components/tasks/${encodeURIComponent(taskId)}`);
                const task = await response.json();
                if (!response.ok) {
                    throw new Error(task.detail || '获取组件安装进度失败');
                }

                componentTaskStateByComponentId.set(componentId, task);
                if (latestComponentsCatalog) {
                    renderComponentsCatalog(latestComponentsCatalog);
                }

                if (task.status === 'pending' || task.status === 'running') {
                    const timerId = window.setTimeout(() => {
                        pollComponentTask(taskId, componentId);
                    }, 1000);
                    componentTaskPollTimers.set(componentId, timerId);
                    return;
                }

                componentTaskPollTimers.delete(componentId);
                const refreshedCatalog = await loadComponentsCatalog();
                if (refreshedCatalog) {
                    renderComponentsCatalog(refreshedCatalog);
                }

                if (task.status === 'completed') {
                    showToast(task.requires_restart ? '组件安装完成，重启应用后会更稳。' : '组件安装完成。', 'success');
                } else if (task.status === 'failed') {
                    showToast(`组件安装失败: ${task.error || '未知错误'}`, 'error');
                }
            } catch (error) {
                componentTaskPollTimers.delete(componentId);
                componentTaskStateByComponentId.set(componentId, {
                    id: taskId,
                    component_id: componentId,
                    status: 'failed',
                    stage: 'failed',
                    message: '组件安装失败',
                    error: error.message,
                    progress: 1,
                });
                if (latestComponentsCatalog) {
                    renderComponentsCatalog(latestComponentsCatalog);
                }
                showToast(`组件安装失败: ${error.message}`, 'error');
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
            const executeCommands = document.getElementById('aiAgentCanExecuteCommands');
            const webSearch = document.getElementById('aiAgentCanWebSearch');
            const runComputerCommands = document.getElementById('aiAgentCanRunComputerCommands');
            if (manageFolders) manageFolders.checked = data?.ai_agent_can_manage_folders !== false;
            if (parseContent) parseContent.checked = data?.ai_agent_can_parse_content !== false;
            if (syncObsidian) syncObsidian.checked = Boolean(data?.ai_agent_can_sync_obsidian);
            if (syncNotion) syncNotion.checked = Boolean(data?.ai_agent_can_sync_notion);
            if (executeCommands) executeCommands.checked = Boolean(data?.ai_agent_can_execute_commands);
            if (webSearch) webSearch.checked = data?.ai_agent_can_web_search !== false;
            if (runComputerCommands) runComputerCommands.checked = Boolean(data?.ai_agent_can_run_computer_commands);
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
            const { includeNotionDatabases = false, includeComponents = false } = options;
            try {
                const res = await fetch('/api/settings');
                if (res.ok) {
                    const data = await res.json();
                    latestSettings = data;
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
                    aiBaseUrlInput.value = data.ai_base_url || '';
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
                    setNotionStatus(data);
                    setObsidianStatus(data);
                    setAiStatus(data);
                    refreshBulkSyncButtons();
                    if (includeNotionDatabases) {
                        await loadNotionDatabases(data.notion_database_id || '');
                    }
                    if (includeComponents) {
                        await loadComponentsCatalog();
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
                ai_agent_can_execute_commands: document.getElementById('aiAgentCanExecuteCommands').checked,
                ai_agent_can_web_search: document.getElementById('aiAgentCanWebSearch').checked,
                ai_agent_can_run_computer_commands: document.getElementById('aiAgentCanRunComputerCommands').checked,
                auto_sync_target: document.getElementById('autoSyncTarget').value
            };
            const notionClientSecret = document.getElementById('notionClientSecret').value.trim();
            const obsidianApiKey = document.getElementById('obsidianApiKey').value.trim();
            const aiApiKey = document.getElementById('aiApiKey').value.trim();
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
                    setNotionStatus(data);
                    setObsidianStatus(data);
                    setAiStatus(data);
                    aiBaseUrlInput.value = data.ai_base_url || '';
                    setAiModelFieldMode(aiBaseUrlInput.value, data.ai_model || '');
                    applyAiAgentPermissionInputs(data);
                    refreshBulkSyncButtons();
                    await loadNotionDatabases(data.notion_database_id || '');
                    if (typeof refreshAiAssistantUi === 'function') {
                        refreshAiAssistantUi();
                    }
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
        componentsList?.addEventListener('click', async (event) => {
            const installButton = event.target instanceof Element
                ? event.target.closest('[data-component-install]')
                : null;
            if (!installButton) return;

            const componentId = String(installButton.getAttribute('data-component-install') || '').trim();
            if (!componentId) return;

            installButton.setAttribute('disabled', 'disabled');
            try {
                const response = await fetch(`/api/settings/components/${encodeURIComponent(componentId)}/install`, {
                    method: 'POST',
                });
                const task = await response.json();
                if (!response.ok) {
                    throw new Error(task.detail || '启动组件安装失败');
                }

                componentTaskStateByComponentId.set(componentId, task);
                if (latestComponentsCatalog) {
                    renderComponentsCatalog(latestComponentsCatalog);
                }
                showToast('组件下载已开始。', 'info');
                await pollComponentTask(task.id, componentId);
            } catch (error) {
                showToast(`启动组件安装失败: ${error.message}`, 'error');
                if (latestComponentsCatalog) {
                    renderComponentsCatalog(latestComponentsCatalog);
                }
            }
        });
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
