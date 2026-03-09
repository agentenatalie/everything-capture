        function escapeHtml(value) {
            return String(value || '')
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#39;');
        }

        function escapeAttribute(value) {
            return escapeHtml(value).replaceAll('`', '&#96;');
        }

        function truncateText(value, maxLength) {
            if (!value) return '';
            return value.length > maxLength ? `${value.slice(0, maxLength)}…` : value;
        }

        function extractFirstHttpUrl(value) {
            if (!value) return null;
            const match = String(value).match(/https?:\/\/[^\s<>"'`]+/i);
            if (!match) return null;

            const candidate = match[0].replace(/[)\]}>.,!?;:'"。，！？；：]+$/u, '');
            try {
                const parsed = new URL(candidate);
                if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
                    return candidate;
                }
            } catch (error) {
                return null;
            }
            return null;
        }

        function isLikelyUrl(value) {
            if (!value) return false;
            try {
                const candidate = new URL(value);
                return candidate.protocol === 'http:' || candidate.protocol === 'https:';
            } catch (error) {
                return false;
            }
        }

        function resolveCommandUrl(value) {
            const trimmedValue = String(value || '').trim();
            if (!trimmedValue) return null;
            if (isLikelyUrl(trimmedValue)) return trimmedValue;
            return extractFirstHttpUrl(trimmedValue);
        }

        function setCommandActionsVisible(visible) {
            extractBtn.hidden = !visible;
            clipboardBtn.hidden = !visible;
        }

        function setMobileCaptureFeedback(message = '', tone = '') {
            if (!mobileCaptureResult) return;
            const nextMessage = String(message || '').trim();
            mobileCaptureResult.hidden = !nextMessage;
            mobileCaptureResult.textContent = nextMessage;
            mobileCaptureResult.className = 'mobile-capture-result';
            if (tone) {
                mobileCaptureResult.classList.add(`is-${tone}`);
            }
        }

        const MOBILE_CAPTURE_QUEUE_STORAGE_KEY = 'everything-grabber-mobile-outbox-v1';
        const MOBILE_CAPTURE_DUPLICATE_WINDOW_MS = 4000;
        const COMMAND_EXTRACT_DUPLICATE_WINDOW_MS = 4000;
        let mobileCaptureQueue = loadMobileCaptureQueue();
        let mobileCaptureQueueFlushInFlight = false;
        let mobileCaptureQueueFlushQueued = false;

        function loadMobileCaptureQueue() {
            try {
                const raw = window.localStorage.getItem(MOBILE_CAPTURE_QUEUE_STORAGE_KEY);
                const parsed = raw ? JSON.parse(raw) : [];
                if (!Array.isArray(parsed)) return [];
                return parsed
                    .map((entry) => ({
                        id: String(entry?.id || '').trim(),
                        text: String(entry?.text || '').trim(),
                        folderIds: Array.isArray(entry?.folderIds)
                            ? entry.folderIds.map((value) => String(value || '').trim()).filter(Boolean)
                            : (String(entry?.folderId || '').trim() ? [String(entry.folderId).trim()] : []),
                        createdAt: String(entry?.createdAt || '').trim(),
                    }))
                    .filter((entry) => entry.id && entry.text);
            } catch (error) {
                return [];
            }
        }

        function persistMobileCaptureQueue() {
            try {
                if (!mobileCaptureQueue.length) {
                    window.localStorage.removeItem(MOBILE_CAPTURE_QUEUE_STORAGE_KEY);
                    return;
                }
                window.localStorage.setItem(MOBILE_CAPTURE_QUEUE_STORAGE_KEY, JSON.stringify(mobileCaptureQueue));
            } catch (error) {
                console.warn('Failed to persist mobile capture queue', error);
            }
        }

        function normalizeMobileQueueFolderIds(folderIds = []) {
            return Array.isArray(folderIds)
                ? folderIds.map((value) => String(value || '').trim()).filter(Boolean).sort()
                : [];
        }

        function findQueuedMobileCapture(text, folderIds = []) {
            const normalizedText = String(text || '').trim();
            const normalizedFolderIds = normalizeMobileQueueFolderIds(folderIds);
            if (!normalizedText) return null;
            return mobileCaptureQueue.find((entry) => {
                const entryFolderIds = normalizeMobileQueueFolderIds(entry.folderIds || []);
                return entry.text === normalizedText && JSON.stringify(entryFolderIds) === JSON.stringify(normalizedFolderIds);
            }) || null;
        }

        function queueMobileCapture(text) {
            const normalizedText = String(text || '').trim();
            if (!normalizedText) return { entry: null, alreadyQueued: false };
            const normalizedFolderIds = normalizeMobileQueueFolderIds(mobileCaptureSelectedFolderIds);

            const existingEntry = findQueuedMobileCapture(normalizedText, normalizedFolderIds);
            if (existingEntry) {
                return { entry: existingEntry, alreadyQueued: true };
            }

            const entry = {
                id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
                text: normalizedText,
                folderIds: normalizedFolderIds,
                createdAt: new Date().toISOString(),
            };
            mobileCaptureQueue.push(entry);
            persistMobileCaptureQueue();
            return { entry, alreadyQueued: false };
        }

        function buildMobileCaptureSubmissionSignature(text, folderIds = []) {
            const normalizedText = String(text || '').trim();
            const normalizedFolderIds = normalizeMobileQueueFolderIds(folderIds);
            return JSON.stringify({
                text: normalizedText,
                folderIds: normalizedFolderIds,
            });
        }

        function isRecentDuplicateMobileCapture(signature) {
            if (!signature) return false;
            return (
                signature === lastMobileCaptureSubmissionSignature
                && Date.now() - lastMobileCaptureSubmissionAt < MOBILE_CAPTURE_DUPLICATE_WINDOW_MS
            );
        }

        function buildCommandExtractSignature(value) {
            return String(value || '').trim();
        }

        function isRecentDuplicateCommandExtract(signature) {
            if (!signature) return false;
            return (
                signature === lastCommandExtractSignature
                && Date.now() - lastCommandExtractAt < COMMAND_EXTRACT_DUPLICATE_WINDOW_MS
            );
        }

        function refreshMobileCaptureQueueFeedback(message = '', tone = 'info') {
            if (message) {
                setMobileCaptureFeedback(message, tone);
                return;
            }
            if (mobileCaptureQueue.length) {
                setMobileCaptureFeedback(`本地待同步 ${mobileCaptureQueue.length} 条`, 'info');
                return;
            }
            setMobileCaptureFeedback('');
        }

        async function flushMobileCaptureQueue(options = {}) {
            const { silent = false } = options;
            if (!mobileCaptureQueue.length) {
                if (!silent) {
                    refreshMobileCaptureQueueFeedback('');
                }
                return { deliveredCount: 0, pendingCount: 0 };
            }

            if (mobileCaptureQueueFlushInFlight) {
                mobileCaptureQueueFlushQueued = true;
                return {
                    deliveredCount: 0,
                    pendingCount: mobileCaptureQueue.length,
                };
            }

            if (!authState.authenticated) {
                refreshMobileCaptureQueueFeedback(`已保存到本地待同步 ${mobileCaptureQueue.length} 条，连接电脑并登录后自动同步`, 'info');
                return {
                    deliveredCount: 0,
                    pendingCount: mobileCaptureQueue.length,
                };
            }

            mobileCaptureQueueFlushInFlight = true;
            if (mobileSubmitBtn) {
                mobileSubmitBtn.disabled = true;
                mobileSubmitBtn.classList.add('is-loading');
            }

            let deliveredCount = 0;
            const remainingQueue = [];

            try {
                for (const entry of mobileCaptureQueue) {
                    try {
                        await submitExtractRequest({
                            text: entry.text,
                            ...(entry.folderIds?.length ? { folder_ids: entry.folderIds } : {}),
                        }, {
                            endpoint: '/api/phone-extract',
                        });
                        deliveredCount += 1;
                    } catch (error) {
                        remainingQueue.push(entry);
                        console.warn('Mobile queued capture delivery failed', error);
                    }
                }

                mobileCaptureQueue = remainingQueue;
                persistMobileCaptureQueue();

                if (deliveredCount > 0) {
                    fetchItems();
                }

                const pendingCount = mobileCaptureQueue.length;
                if (pendingCount === 0) {
                    const message = '已同步到电脑，已清除本地暂存';
                    refreshMobileCaptureQueueFeedback(message, 'success');
                    if (!silent) {
                        showToast(message, 'success');
                    }
                } else if (deliveredCount > 0) {
                    const message = `已同步 ${deliveredCount} 条，剩余 ${pendingCount} 条待同步`;
                    refreshMobileCaptureQueueFeedback(message, 'info');
                    if (!silent) {
                        showToast(message, 'info');
                    }
                } else {
                    const message = `电脑暂未在线，已保留本地暂存 ${pendingCount} 条`;
                    refreshMobileCaptureQueueFeedback(message, 'info');
                    if (!silent) {
                        showToast(message, 'info');
                    }
                }

                return { deliveredCount, pendingCount };
            } finally {
                mobileCaptureQueueFlushInFlight = false;
                if (mobileSubmitBtn) {
                    mobileSubmitBtn.disabled = false;
                    mobileSubmitBtn.classList.remove('is-loading');
                }
                if (mobileCaptureQueueFlushQueued) {
                    mobileCaptureQueueFlushQueued = false;
                    if (mobileCaptureQueue.length) {
                        await flushMobileCaptureQueue({ silent: true });
                    }
                }
            }
        }

        function setButtonLoadingState(button, isLoading, idleLabel, loadingLabel) {
            if (!button) return;
            button.disabled = Boolean(isLoading);
            button.classList.toggle('is-loading', Boolean(isLoading));
            button.textContent = isLoading ? loadingLabel : idleLabel;
        }

        function getActiveSearchParams(limit = 200, qOverride = null) {
            const params = new URLSearchParams();
            const keyword = (qOverride ?? filterInput.value).trim();
            const platform = platformFilter.value;
            params.set('limit', String(limit));
            if (keyword) params.set('q', keyword);
            if (platform !== 'all') params.set('platform', platform);
            if (currentFolderScope === 'unfiled') {
                params.set('folder_scope', 'unfiled');
            } else if (currentFolderScope === 'folder' && currentFolderId) {
                params.set('folder_id', currentFolderId);
            }
            return params;
        }

        function scheduleLibrarySearch() {
            window.clearTimeout(librarySearchTimer);
            librarySearchTimer = window.setTimeout(() => {
                fetchItems();
            }, 180);
        }

        function scheduleCommandSearch(query) {
            window.clearTimeout(commandSearchTimer);
            commandSearchTimer = window.setTimeout(() => {
                fetchCommandResults(query);
            }, 150);
        }

        function clearCommandResults() {
            commandRequestId += 1;
            commandSearchResults = [];
            commandResults.innerHTML = '';
        }

        function uniquePreserveOrder(values) {
            const seen = new Set();
            return values.filter((value) => {
                const normalized = String(value || '').trim();
                if (!normalized || seen.has(normalized)) return false;
                seen.add(normalized);
                return true;
            });
        }

        function getItemImages(item) {
            return (item.media || [])
                .filter((media) => media.type === 'image' && media.url)
                .sort((a, b) => a.display_order - b.display_order);
        }

        function extractImageUrlsFromHtml(html) {
            return Array.from(
                String(html || '').matchAll(/<img[^>]+src=["']([^"']+)["'][^>]*>/gi),
                (match) => match[1]
            );
        }

        function hasSuspiciousRepeatedImages(imageUrls, mediaImageUrls) {
            const nonEmptyImageUrls = imageUrls.filter(Boolean);
            const uniqueInlineImages = uniquePreserveOrder(nonEmptyImageUrls);
            const uniqueMediaImages = uniquePreserveOrder(mediaImageUrls);
            return nonEmptyImageUrls.length > 1 && uniqueInlineImages.length === 1 && uniqueMediaImages.length > 1;
        }

        function parseContentBlocks(item) {
            if (!item.content_blocks_json) return null;
            try {
                const blocks = JSON.parse(item.content_blocks_json);
                return Array.isArray(blocks) ? blocks : null;
            } catch (error) {
                return null;
            }
        }

        function summarizeStructuredBlocks(blocks) {
            const types = new Set((blocks || []).map((block) => String(block?.type || '')).filter(Boolean));
            const mediaTypes = new Set(['image', 'video', 'cover']);
            return {
                hasText: (blocks || []).some((block) => {
                    const content = String(block?.content || block?.markdown || '').trim();
                    return (block?.type === 'text' || block?.type === 'paragraph') && content;
                }),
                textOnly: types.size > 0 && Array.from(types).every((type) => type === 'text' || type === 'paragraph'),
                hasMedia: (blocks || []).some((block) => mediaTypes.has(block?.type)),
                hasRichStructure: (blocks || []).some((block) => {
                    const type = String(block?.type || '');
                    return type && type !== 'text' && type !== 'paragraph' && !mediaTypes.has(type);
                }),
            };
        }

        function getEmbedVideoUrl(url) {
            const value = String(url || '').trim();
            if (!value) return '';
            try {
                const parsed = new URL(value);
                const host = parsed.hostname.toLowerCase();
                const path = parsed.pathname || '';
                if (host.includes('youtu.be')) {
                    const id = path.replace(/^\/+/, '').split('/')[0];
                    return id ? `https://www.youtube.com/embed/${id}` : value;
                }
                if (host.includes('youtube.com') || host.includes('youtube-nocookie.com')) {
                    if (path.startsWith('/embed/')) return `https://www.youtube.com${path.split('?')[0]}`;
                    if (path === '/watch') {
                        const id = parsed.searchParams.get('v');
                        return id ? `https://www.youtube.com/embed/${id}` : value;
                    }
                    if (path.startsWith('/shorts/')) {
                        const id = path.split('/shorts/')[1]?.split('/')[0];
                        return id ? `https://www.youtube.com/embed/${id}` : value;
                    }
                }
                if (host === 'player.vimeo.com') return value;
                if (host.includes('vimeo.com')) {
                    const match = path.match(/\/(?:video\/)?(\d+)/);
                    return match ? `https://player.vimeo.com/video/${match[1]}` : value;
                }
                return value;
            } catch (error) {
                return value;
            }
        }

        function isIframeVideoUrl(url) {
            const value = String(url || '').trim();
            return /youtube(?:-nocookie)?\.com|youtu\.be|vimeo\.com/i.test(value);
        }

        function renderVideoMedia(url) {
            const safeUrl = escapeAttribute(url);
            if (isIframeVideoUrl(url)) {
                return `<div class="modal-media"><iframe src="${escapeAttribute(getEmbedVideoUrl(url))}" title="Embedded video" loading="lazy" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div>`;
            }
            return `<div class="modal-media"><video controls preload="metadata"><source src="${safeUrl}" type="video/mp4"></video></div>`;
        }

        function renderStructuredBlocks(blocks) {
            return blocks.map((block) => {
                const content = String(block.markdown || block.content || '').trim();
                if ((block.type === 'text' || block.type === 'paragraph') && content) {
                    return `<p class="content-para">${escapeHtml(content).replace(/\n/g, '<br>')}</p>`;
                }
                if (block.type === 'heading_1' && content) {
                    return `<h1 class="content-title">${escapeHtml(content)}</h1>`;
                }
                if (block.type === 'heading_2' && content) {
                    return `<h2 class="content-subtitle">${escapeHtml(content)}</h2>`;
                }
                if (block.type === 'heading_3' && content) {
                    return `<h3 class="content-subtitle" style="font-size:1.05rem;">${escapeHtml(content)}</h3>`;
                }
                if (block.type === 'bulleted_list_item' && content) {
                    return `<p class="content-para">• ${escapeHtml(content)}</p>`;
                }
                if (block.type === 'numbered_list_item' && content) {
                    return `<p class="content-para">1. ${escapeHtml(content)}</p>`;
                }
                if (block.type === 'quote' && content) {
                    return `<blockquote class="note-quote">${escapeHtml(content).replace(/\n/g, '<br>')}</blockquote>`;
                }
                if (block.type === 'code' && content) {
                    return `<pre class="preview-code"><code>${escapeHtml(content)}</code></pre>`;
                }
                if (block.type === 'divider') {
                    return '<hr class="divider-line">';
                }
                if (block.type === 'image' && block.url) {
                    return `<div class="inline-img-wrap"><img src="${escapeAttribute(block.url)}" alt="" class="inline-img"></div>`;
                }
                if (block.type === 'video' && block.url) {
                    return renderVideoMedia(block.url);
                }
                return '';
            }).join('');
        }

        function shouldPreferCanonicalHtml(item, blocks, mediaImageUrls) {
            if (!item.canonical_html) return false;
            if (!blocks || !blocks.length) return true;

            const summary = summarizeStructuredBlocks(blocks);
            const htmlImageUrls = extractImageUrlsFromHtml(item.canonical_html);
            const htmlHasRichFormatting = /<(h[1-6]|blockquote|ul|ol|pre|code|figure)\b/i.test(item.canonical_html);

            if (summary.textOnly && (htmlImageUrls.length > 0 || htmlHasRichFormatting)) return true;
            if (!summary.hasMedia && htmlImageUrls.length > 0) return true;
            if (!summary.hasRichStructure && htmlHasRichFormatting) return true;
            if (hasSuspiciousRepeatedImages(htmlImageUrls, mediaImageUrls)) return false;
            return false;
        }

        function buildInlineMediaFallback(item) {
            const paragraphs = String(item.canonical_text || '暂无内容')
                .split(/\n{2,}/)
                .map((paragraph) => paragraph.trim())
                .filter(Boolean);
            const imageUrls = uniquePreserveOrder(getItemImages(item).map((image) => image.url));

            if (!paragraphs.length) paragraphs.push('暂无内容');
            if (!imageUrls.length) {
                return `<div style="white-space:pre-wrap">${escapeHtml(item.canonical_text || '暂无内容').replace(/\n/g, '<br>')}</div>`;
            }

            const imageAnchors = new Map();
            imageUrls.forEach((url, index) => {
                const anchorIndex = Math.min(
                    paragraphs.length - 1,
                    Math.floor(((index + 1) * paragraphs.length) / (imageUrls.length + 1))
                );
                const bucket = imageAnchors.get(anchorIndex) || [];
                bucket.push(url);
                imageAnchors.set(anchorIndex, bucket);
            });

            let html = '';
            paragraphs.forEach((paragraph, index) => {
                html += `<p class="content-para">${escapeHtml(paragraph).replace(/\n/g, '<br>')}</p>`;
                const anchoredImages = imageAnchors.get(index) || [];
                anchoredImages.forEach((url) => {
                    html += `<div class="inline-img-wrap"><img src="${escapeAttribute(url)}" alt="" class="inline-img"></div>`;
                });
            });
            return html;
        }

        function renderWebArticle(item, videos) {
            const mediaImageUrls = getItemImages(item).map((image) => image.url);
            const blocks = parseContentBlocks(item);
            let bodyHtml = '';

            if (blocks && blocks.length > 0 && !shouldPreferCanonicalHtml(item, blocks, mediaImageUrls)) {
                const blockImageUrls = blocks
                    .filter((block) => block.type === 'image' && block.url)
                    .map((block) => block.url);
                const summary = summarizeStructuredBlocks(blocks);
                if (summary.hasText && !hasSuspiciousRepeatedImages(blockImageUrls, mediaImageUrls)) {
                    bodyHtml = renderStructuredBlocks(blocks);
                }
            }

            if (!bodyHtml && item.canonical_html) {
                const htmlImageUrls = extractImageUrlsFromHtml(item.canonical_html);
                if (!hasSuspiciousRepeatedImages(htmlImageUrls, mediaImageUrls)) {
                    bodyHtml = `<div class="article-html" style="margin-top: 0;">${item.canonical_html}</div>`;
                }
            }

            if (!bodyHtml) {
                bodyHtml = buildInlineMediaFallback(item);
            }

            let html = '';
            if (videos.length > 0 && !/<(video|iframe)\b/i.test(bodyHtml)) {
                html += renderVideoMedia(videos[0].url);
            }
            html += bodyHtml;
            return html;
        }

        function updateCommandPaletteState() {
            const value = urlInput.value.trim();
            const platformLabel = platformFilter.options[platformFilter.selectedIndex]?.textContent || '全部';
            const resolvedUrl = resolveCommandUrl(value);
            const hasEmbeddedUrl = Boolean(resolvedUrl && !isLikelyUrl(value));

            if (!value) {
                setCommandActionsVisible(true);
                extractBtn.disabled = true;
                extractBtnLabel.textContent = '粘贴链接或输入关键词';
                extractBtnMeta.textContent = 'ENTER';
                commandHelpText.innerHTML = '输入 <strong>链接</strong> 会直接导入，输入 <strong>文字</strong> 会搜索已保存内容。';
                clearCommandResults();
                return;
            }

            extractBtn.disabled = false;
            if (resolvedUrl) {
                setCommandActionsVisible(true);
                extractBtnLabel.textContent = hasEmbeddedUrl ? '导入识别出的链接' : '导入这个链接';
                extractBtnMeta.textContent = 'ENTER';
                commandHelpText.innerHTML = hasEmbeddedUrl
                    ? `已从分享文案中识别到 <strong>链接</strong>：<code>${escapeHtml(truncateText(resolvedUrl, 42))}</code>`
                    : '识别为 <strong>链接</strong>，按 Enter 会直接导入到 Everything Capture。';
                clearCommandResults();
                return;
            }

            setCommandActionsVisible(false);
            extractBtnLabel.textContent = `搜索资料库 “${truncateText(value, 18)}”`;
            extractBtnMeta.textContent = `${platformLabel} · ENTER`;
            commandHelpText.innerHTML = `识别为 <strong>搜索意图</strong>，会结合标题、正文、链接和主题相关词做智能排序。`;
            scheduleCommandSearch(value);
        }

        async function fetchCommandResults(query) {
            const trimmedQuery = (query || '').trim();
            if (!trimmedQuery || resolveCommandUrl(trimmedQuery)) {
                clearCommandResults();
                return;
            }
            if (!ensureAuthenticated({ showOverlay: false })) {
                clearCommandResults();
                return;
            }

            const requestId = ++commandRequestId;
            commandResults.innerHTML = '<div class="suggestion-empty">搜索中...</div>';
            try {
                const response = await fetch(`/api/items?${getActiveSearchParams(6, trimmedQuery).toString()}`);
                if (!response.ok) throw new Error('API Error');
                const results = await response.json();
                if (requestId !== commandRequestId) return;
                commandSearchResults = results;
                if (!results.length) {
                    commandResults.innerHTML = '<div class="suggestion-empty">没有找到匹配内容</div>';
                    return;
                }

                commandResults.innerHTML = results.map((item) => {
                    const snippet = truncateText(item.canonical_text || item.source_url || '无正文内容', 44);
                    return `
                        <button class="suggestion-item" type="button" onclick="openCommandResult('${item.id}')">
                            <div class="command-result-body">
                                <span class="command-result-title">${escapeHtml(item.title || '无标题')}</span>
                                <span class="command-result-snippet">${escapeHtml(snippet)}</span>
                            </div>
                            <span class="suggestion-meta">${platformDisplayLabel(item)} · ${formatDate(item.created_at)}</span>
                        </button>
                    `;
                }).join('');
            } catch (error) {
                if (requestId !== commandRequestId) return;
                commandResults.innerHTML = '<div class="suggestion-empty">搜索失败，请稍后重试</div>';
            }
        }

        function applyCommandSearch() {
            if (!ensureAuthenticated({ mode: 'email' })) return;
            const query = urlInput.value.trim();
            if (!query) {
                showToast('请输入关键词', 'error');
                return;
            }
            filterInput.value = query;
            fetchItems();
            closeCommandPalette();
        }

        function runCommandAction() {
            const value = urlInput.value.trim();
            if (!value) {
                showToast('请输入链接或关键词', 'error');
                return;
            }
            if (resolveCommandUrl(value)) {
                extractURL();
                return;
            }
            applyCommandSearch();
        }

        async function submitExtractRequest(payloadOrUrl, options = {}) {
            const endpoint = options.endpoint || '/api/extract';
            const payload = typeof payloadOrUrl === 'string'
                ? { url: payloadOrUrl }
                : { ...(payloadOrUrl || {}) };
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.detail || '未知错误');
            }
            return data;
        }

        function formatExtractSuccessMessage(data) {
            const mediaInfo = data.media_count > 0 ? `，${data.media_count} 个媒体` : '';
            return `收录成功：${data.title} (${data.text_length} 字${mediaInfo}，平台：${data.platform})`;
        }

        function openCommandResult(itemId) {
            const item = commandSearchResults.find((entry) => entry.id === itemId);
            if (!item) return;
            filterInput.value = urlInput.value.trim();
            fetchItems();
            closeCommandPalette();
            openModalByItem(item);
        }

        async function extractURL(urlOverride = null) {
            if (!ensureAuthenticated({ mode: 'email' })) return;
            const rawValue = urlOverride ?? urlInput.value.trim();
            const url = resolveCommandUrl(rawValue);
            if (!rawValue) { showToast('请输入链接', 'error'); return; }
            if (!url) { showToast('请输入有效的 http/https 链接', 'error'); return; }
            if (commandExtractInFlight) return;

            const extractSignature = buildCommandExtractSignature(url);
            if (isRecentDuplicateCommandExtract(extractSignature)) {
                showToast('这个链接刚刚已经提交过了', 'info');
                return;
            }

            commandExtractInFlight = true;
            lastCommandExtractSignature = extractSignature;
            lastCommandExtractAt = Date.now();
            extractBtn.disabled = true;
            extractBtn.classList.add('is-loading');
            extractBtnLabel.textContent = '处理中...';
            try {
                const data = await submitExtractRequest(url);
                showToast(formatExtractSuccessMessage(data), 'success');
                urlInput.value = '';
                clearCommandResults();
                updateCommandPaletteState();
                closeCommandPalette();
                fetchItems();
            } catch (e) {
                showToast(`失败：${e.message}`, 'error');
            } finally {
                commandExtractInFlight = false;
                extractBtn.disabled = false;
                extractBtn.classList.remove('is-loading');
                updateCommandPaletteState();
            }
        }

        function isMobileCaptureViewport() {
            return window.matchMedia('(max-width: 860px)').matches;
        }

        async function syncMobileClipboardIntoInput(options = {}) {
            const { silent = false } = options;
            if (!isMobileCaptureViewport() || !navigator.clipboard?.readText) return null;

            try {
                const text = (await navigator.clipboard.readText()).trim();
                if (!text) return null;
                if (mobileCaptureInput) {
                    mobileCaptureInput.value = text;
                }
                return text;
            } catch (error) {
                if (!silent && error?.name !== 'NotAllowedError') {
                    showToast(`读取剪贴板失败：${error.message}`, 'error');
                }
                return null;
            }
        }

        async function pasteClipboardIntoMobileInput() {
            let text = '';
            let clipboardReadBlocked = false;

            if (navigator.clipboard?.readText && window.isSecureContext) {
                try {
                    text = (await navigator.clipboard.readText()).trim();
                } catch (error) {
                    clipboardReadBlocked = true;
                }
            } else {
                clipboardReadBlocked = true;
            }

            if (!text) {
                const manualValue = window.prompt(
                    clipboardReadBlocked
                        ? '系统限制了网页直接读取剪切板，请在这里粘贴内容'
                        : '请粘贴内容',
                    ''
                );
                if (manualValue === null) {
                    return;
                }
                text = String(manualValue || '').trim();
            }

            if (!text) {
                showToast('没有可粘贴的内容', 'info');
                return;
            }

            mobileCaptureInput.value = text;
            mobileCaptureInput?.focus();
            if (mobileCaptureInput?.setSelectionRange) {
                const end = mobileCaptureInput.value.length;
                mobileCaptureInput.setSelectionRange(end, end);
            }
            showToast('已粘贴到输入框', 'success');
        }

        async function submitMobileCapture(options = {}) {
            const { auto = false, skipFolderPrompt = false } = options;
            const rawValue = mobileCaptureInput?.value?.trim() || '';
            if (!rawValue) {
                if (!auto) showToast('请先粘贴链接或文字', 'error');
                return;
            }

            if (mobileCaptureSubmitInFlight) {
                return;
            }

            if (auto && rawValue === lastAutoCapturedClipboardText) {
                return;
            }

            if (!auto && !skipFolderPrompt) {
                try {
                    await openMobileCaptureFolderPicker({
                        submitAfterSelection: true,
                        pendingText: rawValue,
                    });
                } catch (error) {
                    showToast(`打开文件夹选择失败：${error.message}`, 'error');
                }
                return;
            }

            const submissionSignature = buildMobileCaptureSubmissionSignature(rawValue, mobileCaptureSelectedFolderIds);
            if (isRecentDuplicateMobileCapture(submissionSignature)) {
                if (!auto) {
                    showToast('这条内容刚刚已经提交过了', 'info');
                }
                return;
            }

            const { alreadyQueued } = queueMobileCapture(rawValue);
            lastMobileCaptureSubmissionSignature = submissionSignature;
            lastMobileCaptureSubmissionAt = Date.now();
            lastAutoCapturedClipboardText = rawValue;
            if (mobileCaptureInput) {
                mobileCaptureInput.value = '';
            }

            const stagedMessage = alreadyQueued
                ? `已在本地待同步队列中（${mobileCaptureQueue.length} 条）`
                : `已保存到本地待同步（${mobileCaptureQueue.length} 条）`;
            refreshMobileCaptureQueueFeedback(stagedMessage, 'info');
            if (!auto) {
                showToast(stagedMessage, 'info');
            }

            mobileCaptureSubmitInFlight = true;
            try {
                await flushMobileCaptureQueue({ silent: auto });
            } finally {
                mobileCaptureSubmitInFlight = false;
            }
        }

        function startMobileCaptureAutomation() {
            if (mobileCaptureAutomationStarted || !mobileCaptureInput) return;
            mobileCaptureAutomationStarted = true;
            refreshMobileCaptureQueueFeedback();
            if (typeof updateMobileCaptureFolderSummary === 'function') {
                updateMobileCaptureFolderSummary();
            }

            window.setTimeout(() => {
                flushMobileCaptureQueue({ silent: true });
            }, 260);

            document.addEventListener('visibilitychange', () => {
                if (document.visibilityState === 'visible') {
                    flushMobileCaptureQueue({ silent: true });
                }
            });

            window.addEventListener('focus', () => {
                flushMobileCaptureQueue({ silent: true });
            });

            window.addEventListener('online', () => {
                flushMobileCaptureQueue({ silent: true });
            });
        }

        urlInput.addEventListener('input', updateCommandPaletteState);
        urlInput.addEventListener('paste', (e) => {
            const pastedText = e.clipboardData?.getData('text')?.trim();
            const resolvedUrl = resolveCommandUrl(pastedText);
            if (!pastedText || !resolvedUrl || isLikelyUrl(pastedText)) return;

            e.preventDefault();
            urlInput.value = pastedText;
            updateCommandPaletteState();
            extractURL(resolvedUrl);
        });
        urlInput.addEventListener('keydown', e => {
            if (e.key === 'Enter') {
                e.preventDefault();
                runCommandAction();
            }
        });
        commandOverlay.addEventListener('click', e => {
            if (e.target === commandOverlay) closeCommandPalette();
        });
        mobileSubmitBtn?.addEventListener('click', () => {
            submitMobileCapture({ auto: false });
        });
        mobilePasteBtn?.addEventListener('click', () => {
            pasteClipboardIntoMobileInput();
        });
        mobileCaptureInput?.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                submitMobileCapture({ auto: false });
            }
        });
        document.addEventListener('keydown', e => {
            const key = e.key.toLowerCase();
            if (authOverlay.classList.contains('active') && e.key === 'Escape') {
                e.preventDefault();
                focusAuthInput();
                return;
            }
            if ((e.metaKey || e.ctrlKey) && key === 'k') {
                e.preventDefault();
                if (commandOverlay.classList.contains('active')) closeCommandPalette();
                else openCommandPalette();
            }
            if (e.key === 'Escape' && folderPickerOverlay.classList.contains('active')) {
                closeFolderPickerDialog();
                return;
            }
            if (e.key === 'Escape' && commandOverlay.classList.contains('active')) {
                closeCommandPalette();
                return;
            }
            if (e.key === 'Escape' && modalOverlay.classList.contains('active')) {
                closeModalDialog();
            }
        });

        function formatDate(dateStr) {
            const date = new Date(dateStr);
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            return `${month}/${day}`;
        }

        function renderSyncBadges(item) {
            return `
                <div class="knowledge-dots" aria-label="知识库状态">
                    <span class="knowledge-dot notion ${item.notion_page_id ? 'is-ready' : 'is-idle'}" title="Notion${item.notion_page_id ? '已同步' : '未同步'}"></span>
                    <span class="knowledge-dot obsidian ${item.obsidian_path ? 'is-ready' : 'is-idle'}" title="Obsidian${item.obsidian_path ? '已同步' : '未同步'}"></span>
                </div>
            `;
        }

        function setModalFullscreen(nextValue) {
            isModalFullscreen = typeof nextValue === 'boolean' ? nextValue : !isModalFullscreen;
            modalShell.classList.toggle('is-fullscreen', isModalFullscreen);
            toggleFullscreenBtn.setAttribute('aria-label', isModalFullscreen ? '退出全屏' : '全屏阅读');
            toggleFullscreenBtn.innerHTML = isModalFullscreen
                ? `<svg viewBox="0 0 24 24" fill="none" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 3H3v6M15 3h6v6M21 15v6h-6M3 15v6h6"></path></svg>`
                : `<svg viewBox="0 0 24 24" fill="none" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5"></path></svg>`;
        }

        function getItemThumbnail(item) {
            if (!item.media || item.media.length === 0) return null;
            const images = item.media.filter(m => m.type === 'image');
            const covers = item.media.filter(m => m.type === 'cover');

            // 优先选择封面图 (Cover 通常是静态的)
            if (covers.length > 0) return covers[0];

            // 其次选择非 GIF 的图片
            const staticImages = images.filter(m => !m.url.toLowerCase().endsWith('.gif'));
            if (staticImages.length > 0) return staticImages[0];

            // 最后没办法了再选第一张图 (可能是 GIF)
            return images[0] || null;
        }

        function normalizePlatform(platform, sourceUrl = '') {
            const value = (platform || '').toLowerCase();
            if (value.includes('douyin') || value.includes('抖音') || value.includes('tiktok')) return 'douyin';
            if (value.includes('xiaohongshu') || value.includes('小红书') || value.includes('rednote') || value === 'xhs') return 'xiaohongshu';
            if (value.includes('wechat') || value.includes('weixin') || sourceUrl.includes('mp.weixin.qq.com') || sourceUrl.includes('weixin.qq.com')) return 'wechat';
            if (value === 'x' || value.includes('twitter')) return 'x';
            if (value === 'general' || value === 'generic' || value === 'web' || value === 'site') return 'web';
            return value;
        }

        function platformDisplayLabel(item) {
            const platform = normalizePlatform(item.platform || '', (item.source_url || '').toLowerCase());
            if (platform === 'web') return 'web';
            return platform || 'web';
        }

        function formatRelativeTime(dateStr) {
            const value = new Date(dateStr);
            if (Number.isNaN(value.getTime())) return formatDate(dateStr);

            const diffMs = Date.now() - value.getTime();
            const diffMinutes = Math.max(0, Math.floor(diffMs / (1000 * 60)));
            const diffHours = Math.max(0, Math.floor(diffMinutes / 60));
            const diffDays = Math.max(1, Math.floor(diffHours / 24));

            if (diffMinutes < 3) return '刚刚';
            if (diffMinutes < 60) return `${diffMinutes}分钟前`;
            if (diffHours < 24) return `${diffHours}小时前`;
            return `${diffDays}天前`;
        }

        function renderPlatformMark(item) {
            const platform = normalizePlatform(item.platform || '', (item.source_url || '').toLowerCase());
            switch (platform) {
                case 'wechat':
                    return '<span class="platform-glyph">微</span>';
                case 'douyin':
                    return '<span class="platform-glyph">抖</span>';
                case 'xiaohongshu':
                    return '<span class="platform-glyph">红</span>';
                case 'x':
                    return '<span class="platform-glyph">X</span>';
                default:
                    return '<span class="platform-glyph">W</span>';
            }
        }

        function renderCardTags(item) {
            return uniquePreserveOrder(getItemFolderNames(item))
                .slice(0, 3)
                .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
                .join('');
        }

        function renderCardPreview(item) {
            const media = Array.isArray(item.media) ? item.media : [];
            const images = media.filter((entry) => entry.type === 'image');
            const videos = media.filter((entry) => entry.type === 'video');
            const thumb = getItemThumbnail(item);
            const badge = images.length > 1
                ? `<span class="card-media-badge">${images.length} 张图片</span>`
                : (videos.length > 0 ? '<span class="card-media-badge">视频</span>' : '');
            const previewBody = thumb
                ? `<img src="${escapeAttribute(thumb.url)}" loading="lazy" alt="">`
                : `<div class="card-preview-placeholder">
                        <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                            <circle cx="8.5" cy="8.5" r="1.5"></circle>
                            <path d="m21 15-5-5L5 21"></path>
                        </svg>
                    </div>`;

            return `
                <div class="card-preview">
                    ${previewBody}
                    <div class="card-icon">${renderPlatformMark(item)}</div>
                    ${badge}
                </div>
            `;
        }
