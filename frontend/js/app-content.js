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

        function hasInlineMarkdownSyntax(value) {
            return /(\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|~~[^~\n]+~~)/.test(String(value || ''));
        }

        function renderInlineMarkdown(value) {
            const source = String(value || '').trim();
            if (!source) return '';

            const replacements = [];
            const createToken = (html) => {
                const token = `@@ECMD${replacements.length}@@`;
                replacements.push({ token, html });
                return token;
            };

            let rendered = source
                .replace(/`([^`\n]+)`/g, (_, code) => createToken(`<code class="inline-code">${escapeHtml(code)}</code>`))
                .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => {
                    try {
                        const parsed = new URL(url);
                        if (!['http:', 'https:'].includes(parsed.protocol)) {
                            return createToken(escapeHtml(label));
                        }
                    } catch (error) {
                        return createToken(escapeHtml(label));
                    }

                    return createToken(
                        `<a href="${escapeAttribute(url)}" target="_blank" rel="noreferrer noopener">${escapeHtml(label)}</a>`
                    );
                })
                .replace(/https?:\/\/[^\s<>"'`]+/g, (rawUrl) => {
                    const safeUrl = extractFirstHttpUrl(rawUrl);
                    if (!safeUrl) return rawUrl;
                    const trailing = rawUrl.slice(safeUrl.length);
                    return createToken(
                        `<a href="${escapeAttribute(safeUrl)}" target="_blank" rel="noreferrer noopener">${escapeHtml(safeUrl)}</a>${escapeHtml(trailing)}`
                    );
                });

            rendered = escapeHtml(rendered)
                .replace(/\*\*([^*\n][^*]*?)\*\*/g, '<strong>$1</strong>')
                .replace(/__([^_\n][^_]*?)__/g, '<strong>$1</strong>')
                .replace(/~~([^~\n][^~]*?)~~/g, '<del>$1</del>')
                .replace(/(^|[^*])\*([^*\n][^*]*?)\*(?=[^*]|$)/g, '$1<em>$2</em>')
                .replace(/(^|[^_])_([^_\n][^_]*?)_(?=[^_]|$)/g, '$1<em>$2</em>');

            replacements.forEach(({ token, html }) => {
                rendered = rendered.replaceAll(token, html);
            });

            return rendered;
        }

        function blockUsesInlineFormatting(block) {
            const markdown = String(block?.markdown || '').trim();
            const content = String(block?.content || '').trim();
            if (!markdown) return false;
            return markdown !== content || hasInlineMarkdownSyntax(markdown);
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

        const MOBILE_CAPTURE_QUEUE_STORAGE_KEY = 'everything-capture-mobile-outbox-v1';
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

        const EXTRACTED_SECTION_LABELS = {
            detected_title: '检测标题',
            urls: '原始链接',
            qr_links: '二维码链接',
            ocr_text: 'OCR 识别',
            subtitle_text: '视频字幕',
            transcript_text: '语音转写',
            body: '解析内容',
        };
        const extractedSectionCache = new Map();

        function normalizeExtractedMultilineText(value) {
            return String(value || '')
                .replace(/\r\n/g, '\n')
                .replace(/\r/g, '\n')
                .replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, '')
                .trim();
        }

        function firstMeaningfulExtractedLine(value) {
            const lines = normalizeExtractedMultilineText(value).split('\n');
            for (const rawLine of lines) {
                const line = rawLine.replace(/\s+/g, ' ').trim();
                if (line) return line;
            }
            return '';
        }

        function parseExtractedTextSections(value) {
            const raw = normalizeExtractedMultilineText(value);
            if (!raw) {
                return {
                    raw: '',
                    detectedTitle: '',
                    sections: [],
                    contentSections: [],
                    previewText: '',
                    hasStructuredSections: false,
                };
            }

            const cached = extractedSectionCache.get(raw);
            if (cached) return cached;

            const sections = [];
            let currentKey = '';
            let currentLines = [];

            const pushSection = () => {
                const sectionValue = currentLines.join('\n').trim();
                if (!currentKey && !sectionValue) return;
                const key = currentKey || 'body';
                sections.push({
                    key,
                    label: EXTRACTED_SECTION_LABELS[key] || key,
                    value: sectionValue,
                });
                currentLines = [];
            };

            raw.split('\n').forEach((line) => {
                const match = line.trim().match(/^\[([a-z_]+)\]$/i);
                if (match) {
                    pushSection();
                    currentKey = match[1].toLowerCase();
                    return;
                }
                currentLines.push(line);
            });
            pushSection();

            const detectedTitle = firstMeaningfulExtractedLine(
                sections.find((section) => section.key === 'detected_title')?.value || ''
            );
            const contentSections = sections.filter((section) => section.key !== 'detected_title' && section.value);
            const previewText = contentSections
                .map((section) => {
                    if (section.key === 'urls' || section.key === 'qr_links') {
                        return uniquePreserveOrder(
                            section.value.split('\n').map((entry) => entry.trim()).filter(Boolean)
                        ).join(' ');
                    }
                    return section.value;
                })
                .join('\n\n')
                .replace(/\n{3,}/g, '\n\n')
                .trim();

            const parsed = {
                raw,
                detectedTitle,
                sections,
                contentSections,
                previewText,
                hasStructuredSections: sections.some((section) => section.key !== 'body'),
            };
            extractedSectionCache.set(raw, parsed);
            return parsed;
        }

        function getExtractedDisplayTitle(item) {
            return parseExtractedTextSections(item?.extracted_text || '').detectedTitle;
        }

        function getExtractedPreviewText(item, maxLength = 120) {
            const previewText = parseExtractedTextSections(item?.extracted_text || '').previewText;
            if (!previewText) return '';
            return truncateText(previewText, maxLength);
        }

        function safeHttpUrl(value) {
            const raw = String(value || '').trim();
            if (!raw) return '';
            try {
                const parsed = new URL(raw);
                if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
                    return parsed.toString();
                }
            } catch (error) {
                return '';
            }
            return '';
        }

        function renderExtractedMarkdown(value) {
            const source = String(value || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
            if (!source) return '';

            const lines = source.split('\n');
            const html = [];
            let paragraph = [];
            let listType = '';
            let listItems = [];

            const isTableSeparator = (l) => /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(String(l || ''));
            const isTableLine = (l) => {
                const t = String(l || '').trim();
                return t.includes('|') && !/^\s*[-*+]\s/.test(t) && !/^\s*\d+\.\s/.test(t);
            };
            const splitTableRow = (row) => {
                const trimmed = String(row || '').trim().replace(/^\|/, '').replace(/\|$/, '');
                const cells = [];
                let current = '';
                for (const char of trimmed) {
                    if (char === '|') { cells.push(current.trim()); current = ''; }
                    else { current += char; }
                }
                cells.push(current.trim());
                return cells;
            };

            const flushParagraph = () => {
                if (!paragraph.length) return;
                html.push(`<p class="content-para">${renderInlineMarkdown(paragraph.join('\n')).replace(/\n/g, '<br>')}</p>`);
                paragraph = [];
            };

            const flushList = () => {
                if (!listItems.length || !listType) return;
                const listClass = listType === 'ol' ? 'content-list content-list-ordered' : 'content-list';
                html.push(
                    `<${listType} class="${listClass}">${listItems.map((item) => `<li>${renderInlineMarkdown(item).replace(/\n/g, '<br>')}</li>`).join('')}</${listType}>`
                );
                listType = '';
                listItems = [];
            };

            for (let index = 0; index < lines.length; index += 1) {
                const line = lines[index];
                const trimmed = line.trim();
                if (!trimmed) {
                    flushParagraph();
                    flushList();
                    continue;
                }

                // Table: header row followed by separator row
                if (isTableLine(line) && isTableSeparator(lines[index + 1])) {
                    flushParagraph();
                    flushList();
                    const headerCells = splitTableRow(line);
                    const alignCells = splitTableRow(lines[index + 1]).map((cell) => {
                        const t = cell.trim();
                        if (t.startsWith(':') && t.endsWith(':')) return 'center';
                        if (t.endsWith(':')) return 'right';
                        return 'left';
                    });
                    index += 2;
                    const bodyRows = [];
                    while (index < lines.length && lines[index].trim() && isTableLine(lines[index])) {
                        bodyRows.push(splitTableRow(lines[index]));
                        index += 1;
                    }
                    index -= 1;
                    const cols = Math.max(headerCells.length, ...bodyRows.map((r) => r.length), 0);
                    html.push(`
                        <div class="ai-table-wrap">
                            <table>
                                <thead><tr>${Array.from({ length: cols }, (_, i) => `<th style="text-align:${alignCells[i] || 'left'}">${renderInlineMarkdown(headerCells[i] || '')}</th>`).join('')}</tr></thead>
                                <tbody>${bodyRows.map((row) => `<tr>${Array.from({ length: cols }, (_, i) => `<td style="text-align:${alignCells[i] || 'left'}">${renderInlineMarkdown(row[i] || '')}</td>`).join('')}</tr>`).join('')}</tbody>
                            </table>
                        </div>
                    `);
                    continue;
                }

                const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
                if (headingMatch) {
                    flushParagraph();
                    flushList();
                    const headingLevel = Math.min(headingMatch[1].length + 1, 4);
                    html.push(
                        `<h${headingLevel} class="reader-extracted-md-heading reader-extracted-md-heading--${headingLevel}">${renderInlineMarkdown(headingMatch[2])}</h${headingLevel}>`
                    );
                    continue;
                }

                const blockquoteMatch = trimmed.match(/^>\s?(.*)$/);
                if (blockquoteMatch) {
                    flushParagraph();
                    flushList();
                    html.push(`<blockquote class="note-quote">${renderInlineMarkdown(blockquoteMatch[1])}</blockquote>`);
                    continue;
                }

                const unorderedMatch = line.match(/^\s*[-*+]\s+(.*)$/);
                const orderedMatch = line.match(/^\s*\d+\.\s+(.*)$/);
                if (unorderedMatch || orderedMatch) {
                    flushParagraph();
                    const nextType = unorderedMatch ? 'ul' : 'ol';
                    if (listType && listType !== nextType) {
                        flushList();
                    }
                    listType = nextType;
                    listItems.push((unorderedMatch || orderedMatch)[1]);
                    continue;
                }

                if (listItems.length) {
                    flushList();
                }

                paragraph.push(line);
            }

            flushParagraph();
            flushList();
            return html.join('');
        }

        function cleanOcrText(value) {
            return value
                .split('\n')
                .map((line) => line.trim())
                .filter((line) => {
                    if (!line) return true; // keep blank lines for paragraph breaks
                    // Filter out garbled OCR: lines that are mostly non-CJK non-alpha noise
                    const alphaOrCjk = line.replace(/[\s\d_`~·\-=+*#@!$%^&()[\]{}<>|\\/:;'",.\u2000-\u206F\u2E00-\u2E7F]/g, '');
                    if (alphaOrCjk.length === 0) return false;
                    const noiseRatio = 1 - (alphaOrCjk.length / line.length);
                    if (noiseRatio > 0.7 && line.length > 3) return false;
                    // Filter very short garbage fragments (1-2 random chars)
                    if (line.length <= 2 && !/[\u4e00-\u9fff]/.test(line)) return false;
                    return true;
                })
                .join('\n')
                .replace(/\n{3,}/g, '\n\n')
                .trim();
        }

        function renderExtractedSectionMarkup(section) {
            if (!section?.value) return '';

            if (section.key === 'ocr_text') {
                const cleaned = cleanOcrText(section.value);
                if (!cleaned) return '';
                return renderExtractedMarkdown(cleaned);
            }

            if (section.key === 'urls' || section.key === 'qr_links') {
                const links = uniquePreserveOrder(
                    section.value.split('\n').map((entry) => entry.trim()).filter(Boolean)
                );
                if (!links.length) return '';
                return `
                    <div class="reader-extracted-links">
                        ${links.map((link) => {
                            const safeUrl = safeHttpUrl(link);
                            if (!safeUrl) {
                                return `<span class="reader-extracted-link is-muted">${escapeHtml(link)}</span>`;
                            }
                            return `<a class="reader-extracted-link" href="${escapeAttribute(safeUrl)}" target="_blank" rel="noreferrer noopener">${escapeHtml(link)}</a>`;
                        }).join('')}
                    </div>
                `;
            }

            return renderExtractedMarkdown(section.value);
        }

        function renderExtractedSections(item, options = {}) {
            const {
                asPrimary = false,
                kicker = '',
                showKicker = true,
                hideBodySectionTitle = false,
            } = options;
            const parsed = parseExtractedTextSections(item?.extracted_text || '');
            if (!parsed.contentSections.length) return '';
            // For video items, OCR is just the cover thumbnail — hide it
            const hasVideo = (item?.media || []).some((m) => m.type === 'video');
            const sections = hasVideo
                ? parsed.contentSections.filter((s) => s.key !== 'ocr_text')
                : parsed.contentSections;
            if (!sections.length) return '';
            const displayKicker = kicker || (asPrimary ? '解析内容' : '补充解析');

            return `
                <section class="reader-extracted-panel${asPrimary ? ' is-primary' : ''}">
                    ${showKicker ? `<div class="reader-extracted-kicker">${escapeHtml(displayKicker)}</div>` : ''}
                    ${sections.map((section) => `
                        <div class="reader-extracted-section">
                            ${hideBodySectionTitle && section.key === 'body' ? '' : `<h3 class="reader-extracted-title">${escapeHtml(section.label)}</h3>`}
                            ${renderExtractedSectionMarkup(section)}
                        </div>
                    `).join('')}
                </section>
            `;
        }

        function isPlaceholderReaderBody(bodyHtml) {
            const plainText = String(bodyHtml || '')
                .replace(/<br\s*\/?>/gi, '\n')
                .replace(/<[^>]+>/g, ' ')
                .replace(/\s+/g, ' ')
                .trim();
            return !plainText || plainText === '暂无内容';
        }

        function renderPlainTextArticle(item) {
            const canonicalText = String(item?.canonical_text || '').trim();
            if (canonicalText) {
                return canonicalText
                    .split(/\n{2,}/)
                    .map((paragraph) => paragraph.trim())
                    .filter(Boolean)
                    .map((paragraph) => `<p class="content-para">${renderInlineMarkdown(paragraph).replace(/\n/g, '<br>')}</p>`)
                    .join('');
            }

            return '<div class="content-empty-state">暂无内容</div>';
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
            const htmlParts = [];
            let index = 0;

            while (index < blocks.length) {
                const block = blocks[index];
                const content = String(block.markdown || block.content || '').trim();
                const renderedContent = renderInlineMarkdown(content);

                if (block.type === 'bulleted_list_item' || block.type === 'numbered_list_item') {
                    const listTag = block.type === 'numbered_list_item' ? 'ol' : 'ul';
                    const listClass = block.type === 'numbered_list_item' ? 'content-list content-list-ordered' : 'content-list';
                    const items = [];
                    while (index < blocks.length && blocks[index].type === block.type) {
                        const itemContent = String(blocks[index].markdown || blocks[index].content || '').trim();
                        if (itemContent) {
                            items.push(`<li>${renderInlineMarkdown(itemContent)}</li>`);
                        }
                        index += 1;
                    }
                    if (items.length) {
                        htmlParts.push(`<${listTag} class="${listClass}">${items.join('')}</${listTag}>`);
                    }
                    continue;
                }

                index += 1;
                if ((block.type === 'text' || block.type === 'paragraph') && content) {
                    htmlParts.push(`<p class="content-para">${renderedContent.replace(/\n/g, '<br>')}</p>`);
                    continue;
                }
                if (block.type === 'heading_1' && content) {
                    htmlParts.push(`<h1 class="content-title">${renderedContent}</h1>`);
                    continue;
                }
                if (block.type === 'heading_2' && content) {
                    htmlParts.push(`<h2 class="content-subtitle">${renderedContent}</h2>`);
                    continue;
                }
                if (block.type === 'heading_3' && content) {
                    htmlParts.push(`<h3 class="content-subtitle" style="font-size:1.05rem;">${renderedContent}</h3>`);
                    continue;
                }
                if (block.type === 'quote' && content) {
                    htmlParts.push(`<blockquote class="note-quote">${renderedContent.replace(/\n/g, '<br>')}</blockquote>`);
                    continue;
                }
                if (block.type === 'code' && content) {
                    htmlParts.push(`<pre class="preview-code"><code>${escapeHtml(content)}</code></pre>`);
                    continue;
                }
                if (block.type === 'divider') {
                    htmlParts.push('<hr class="divider-line">');
                    continue;
                }
                if (block.type === 'image' && block.url) {
                    htmlParts.push(`<div class="inline-img-wrap"><img src="${escapeAttribute(resolveMediaUrl(block.url))}" alt="" class="inline-img" loading="lazy" decoding="async"></div>`);
                    continue;
                }
                if (block.type === 'video' && block.url) {
                    htmlParts.push(renderVideoMedia(resolveMediaUrl(block.url)));
                }
            }

            return htmlParts.join('');
        }

        function shouldPreferCanonicalHtml(item, blocks, mediaImageUrls) {
            if (!item.canonical_html) return false;
            if (!blocks || !blocks.length) return true;

            const summary = summarizeStructuredBlocks(blocks);
            const htmlImageUrls = extractImageUrlsFromHtml(item.canonical_html);
            const htmlHasRichFormatting = /<(h[1-6]|blockquote|ul|ol|pre|code|figure)\b/i.test(item.canonical_html);
            const htmlHasInlineFormatting = /<(a|strong|em|b|i|mark|del|sup|sub)\b/i.test(item.canonical_html);
            const blocksContainInlineFormatting = blocks.some((block) => blockUsesInlineFormatting(block));

            if (summary.textOnly && (htmlImageUrls.length > 0 || htmlHasRichFormatting || htmlHasInlineFormatting)) return true;
            if (!summary.hasMedia && htmlImageUrls.length > 0) return true;
            if (!summary.hasRichStructure && (htmlHasRichFormatting || htmlHasInlineFormatting)) return true;
            if (blocksContainInlineFormatting && (htmlHasRichFormatting || htmlHasInlineFormatting)) return true;
            if (hasSuspiciousRepeatedImages(htmlImageUrls, mediaImageUrls)) return false;

            // If canonical_html text is significantly longer than blocks text, prefer HTML
            // (blocks may have been truncated by missing container tags like <details>, <ul>, <table>)
            const blocksTextLen = blocks.reduce((sum, b) => sum + (b.type === 'text' || b.type === 'paragraph' ? (b.content || b.markdown || '').length : 0), 0);
            const htmlTextLen = item.canonical_html.replace(/<[^>]*>/g, '').length;
            if (htmlTextLen > blocksTextLen * 2 && htmlTextLen - blocksTextLen > 200) return true;

            return false;
        }

        function buildInlineMediaFallback(item) {
            const paragraphs = String(item.canonical_text || '')
                .split(/\n{2,}/)
                .map((paragraph) => paragraph.trim())
                .filter(Boolean);
            const imageUrls = uniquePreserveOrder(getItemImages(item).map((image) => image.url));

            if (!imageUrls.length) {
                return renderPlainTextArticle(item);
            }
            if (!paragraphs.length) {
                return imageUrls.map((url) => `<div class="inline-img-wrap"><img src="${escapeAttribute(resolveMediaUrl(url))}" alt="" class="inline-img" loading="lazy" decoding="async"></div>`).join('');
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
                html += `<p class="content-para">${renderInlineMarkdown(paragraph).replace(/\n/g, '<br>')}</p>`;
                const anchoredImages = imageAnchors.get(index) || [];
                anchoredImages.forEach((url) => {
                    html += `<div class="inline-img-wrap"><img src="${escapeAttribute(resolveMediaUrl(url))}" alt="" class="inline-img" loading="lazy" decoding="async"></div>`;
                });
            });
            return html;
        }

        function resolveHtmlMediaUrls(html) {
            if (!html) return '';
            const template = document.createElement('template');
            template.innerHTML = html;

            template.content.querySelectorAll('[src], [poster], [href], [srcset]').forEach((node) => {
                if (node.tagName === 'IMG') {
                    node.setAttribute('loading', 'lazy');
                    node.setAttribute('decoding', 'async');
                }
                ['src', 'poster', 'href'].forEach((attr) => {
                    const value = node.getAttribute(attr);
                    if (value && value.startsWith('/static/')) {
                        node.setAttribute(attr, resolveMediaUrl(value));
                    }
                });

                const srcset = node.getAttribute('srcset');
                if (srcset && srcset.includes('/static/')) {
                    const normalized = srcset
                        .split(',')
                        .map((entry) => {
                            const trimmed = entry.trim();
                            if (!trimmed) return trimmed;
                            const parts = trimmed.split(/\s+/, 2);
                            parts[0] = resolveMediaUrl(parts[0]);
                            return parts.filter(Boolean).join(' ');
                        })
                        .join(', ');
                    node.setAttribute('srcset', normalized);
                }
            });

            return template.innerHTML;
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
                    bodyHtml = `<div class="article-html" style="margin-top: 0;">${resolveHtmlMediaUrls(item.canonical_html)}</div>`;
                }
            }

            if (!bodyHtml) {
                bodyHtml = buildInlineMediaFallback(item);
            }

            let html = '';
            if (videos.length > 0 && !/<(video|iframe)\b/i.test(bodyHtml)) {
                html += renderVideoMedia(resolveMediaUrl(videos[0].url));
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
                    const snippet = getDisplayItemPreview(item, 44) || truncateText(item.source_url || '无正文内容', 44);
                    return `
                        <button class="suggestion-item" type="button" onclick="openCommandResult('${item.id}')">
                            <div class="command-result-body">
                                <span class="command-result-title">${escapeHtml(getDisplayItemTitle(item))}</span>
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

        function isExtractNetworkFailure(error) {
            const message = String(error?.message || error || '').trim();
            return error instanceof TypeError || /Failed to fetch|Load failed|NetworkError/i.test(message);
        }

        function normalizeExtractRequestError(error) {
            const message = String(error?.message || error || '').trim();
            if (isExtractNetworkFailure(error)) {
                return '无法连接到本地后端服务，请确认项目目录里的 ./run 仍在运行。';
            }
            return message || '未知错误';
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
                showToast(`失败：${normalizeExtractRequestError(e)}`, 'error');
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
            if ((e.metaKey || e.ctrlKey) && key === 'k') {
                e.preventDefault();
                if (commandOverlay.classList.contains('active')) closeCommandPalette();
                else openCommandPalette();
            }
        });

        function formatDate(dateStr) {
            const date = new Date(dateStr);
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            return `${month}/${day}`;
        }

        function renderSyncBadges(item) {
            const obsidianState = item?.obsidian_sync_state === 'partial'
                ? 'partial'
                : (item?.obsidian_sync_state === 'ready' ? 'ready' : (item?.obsidian_path ? 'ready' : 'idle'));
            const obsidianClass = obsidianState === 'ready'
                ? 'is-ready'
                : (obsidianState === 'partial' ? 'is-partial' : 'is-idle');
            const obsidianTitle = obsidianState === 'ready'
                ? 'Obsidian已完全同步'
                : (obsidianState === 'partial' ? 'Obsidian有更新待同步' : 'Obsidian未同步');
            return `
                <div class="knowledge-dots" aria-label="知识库状态">
                    <span class="knowledge-dot notion ${item.notion_page_id ? 'is-ready' : 'is-idle'}" title="Notion${item.notion_page_id ? '已同步' : '未同步'}"></span>
                    <span class="knowledge-dot obsidian ${obsidianClass}" title="${obsidianTitle}"></span>
                </div>
            `;
        }

        function setNotePanelOpen(nextValue) {
            isNotePanelOpen = typeof nextValue === 'boolean' ? nextValue : !isNotePanelOpen;
            if (readerNotePanel) {
                readerNotePanel.classList.toggle('active', isNotePanelOpen);
            }
            if (toggleNoteBtn) {
                toggleNoteBtn.classList.toggle('is-active', isNotePanelOpen);
                toggleNoteBtn.setAttribute('aria-label', isNotePanelOpen ? '收起解析笔记' : '查看解析笔记');
            }
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
            const normalizedSourceUrl = String(sourceUrl || '').toLowerCase();
            if (value.includes('github') || normalizedSourceUrl.includes('github.com/')) return 'github';
            if (value.includes('douyin') || value.includes('抖音') || value.includes('tiktok')) return 'douyin';
            if (value.includes('xiaohongshu') || value.includes('小红书') || value.includes('rednote') || value === 'xhs') return 'xiaohongshu';
            if (value.includes('wechat') || value.includes('weixin') || normalizedSourceUrl.includes('mp.weixin.qq.com') || normalizedSourceUrl.includes('weixin.qq.com')) return 'wechat';
            if (value === 'x' || value.includes('twitter')) return 'x';
            if (value === 'general' || value === 'generic' || value === 'web' || value === 'site') return 'web';
            return value;
        }

        function getGitHubRepoPath(sourceUrl = '') {
            try {
                const parsed = new URL(String(sourceUrl || '').trim());
                if (!parsed.hostname.toLowerCase().includes('github.com')) return '';
                const segments = parsed.pathname.split('/').filter(Boolean);
                if (segments.length < 2) return '';
                return `${segments[0]}/${segments[1]}`.replace(/\.git$/i, '');
            } catch (error) {
                return '';
            }
        }

        function getGitHubTitleParts(item) {
            if (normalizePlatform(item?.platform || '', item?.source_url || '') !== 'github') {
                return null;
            }

            const rawTitle = String(item?.title || '').trim();
            const repoFromUrl = getGitHubRepoPath(item?.source_url || '');
            const titleMatch = rawTitle.match(/^GitHub\s*-\s*([^:：]+?)\s*[:：]\s*(.+)$/i);
            const repoOnlyMatch = rawTitle.match(/^GitHub\s*-\s*(.+)$/i);
            const repoName = (titleMatch?.[1] || repoFromUrl || repoOnlyMatch?.[1] || rawTitle || 'GitHub 项目').trim();
            const description = (titleMatch?.[2] || '').trim();

            return {
                repoName: repoName || 'GitHub 项目',
                description,
                rawTitle: rawTitle || repoName || 'GitHub 项目',
            };
        }

        function getDisplayItemTitle(item) {
            const githubParts = getGitHubTitleParts(item);
            if (githubParts?.repoName) {
                return githubParts.repoName;
            }
            const extractedTitle = getExtractedDisplayTitle(item);
            if (extractedTitle) {
                return extractedTitle;
            }
            return String(item?.title || '').trim() || '无标题';
        }

        function getDisplayItemPreview(item, maxLength = 120) {
            const githubParts = getGitHubTitleParts(item);
            if (githubParts?.description) {
                return truncateText(githubParts.description, maxLength);
            }

            const canonicalText = String(item?.canonical_text || '').trim();
            const extractedTitle = getExtractedDisplayTitle(item);
            const extractedPreview = getExtractedPreviewText(item, maxLength);
            if (canonicalText) {
                const normalizedCanonical = canonicalText.replace(/\s+/g, ' ').trim();
                const normalizedExtractedTitle = String(extractedTitle || '').replace(/\s+/g, ' ').trim();
                if (extractedPreview && normalizedExtractedTitle && (normalizedCanonical === normalizedExtractedTitle || normalizedCanonical.length <= 40)) {
                    return extractedPreview;
                }
                return truncateText(canonicalText, maxLength);
            }
            if (extractedPreview) return extractedPreview;
            return '无正文内容';
        }

        function platformDisplayLabel(item) {
            const platform = normalizePlatform(item.platform || '', (item.source_url || '').toLowerCase());
            if (platform === 'github') return 'GitHub';
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
                case 'github':
                    return `<svg class="platform-icon is-filled" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M11.996 1.284a10.986 10.986 0 0 0 -3.472 21.412c0.548 0.095 0.722 -0.227 0.722 -0.517 0 -0.263 0.006 -0.991 0 -1.91 -3.057 0.662 -3.688 -1.448 -3.688 -1.448a2.907 2.907 0 0 0 -1.22 -1.607c-0.997 -0.682 0.075 -0.669 0.075 -0.669a2.307 2.307 0 0 1 1.683 1.131 2.34 2.34 0 0 0 3.197 0.914 2.34 2.34 0 0 1 0.697 -1.464c-2.439 -0.279 -5.004 -1.22 -5.004 -5.432a4.248 4.248 0 0 1 1.132 -2.948 3.942 3.942 0 0 1 0.107 -2.907s0.924 -0.295 3.02 1.128a10.402 10.402 0 0 1 5.503 0c2.102 -1.422 3.018 -1.128 3.018 -1.128 0.405 0.92 0.444 1.96 0.109 2.907a4.243 4.243 0 0 1 1.13 2.95c0 4.223 -2.569 5.15 -5.016 5.42a2.604 2.604 0 0 1 0.752 2.026v3.041c0 0.294 0.177 0.619 0.735 0.512a10.986 10.986 0 0 0 -3.48 -21.411Z"></path>
                    </svg>`;
                case 'wechat':
                    return `<svg class="platform-icon is-wechat" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M8.45 6.3c-3.06 0-5.45 1.93-5.45 4.53 0 1.5.8 2.8 2.08 3.68l-.42 2.04 2.2-1.14c.35.06.71.08 1.09.08 3.01 0 5.45-1.94 5.45-4.54 0-2.6-2.44-4.65-5.45-4.65Z"></path>
                        <path d="M15.5 10.25c2.93 0 5.25 1.74 5.25 4.05 0 1.31-.73 2.46-1.89 3.22l.38 1.73-1.92-.97c-.28.04-.57.06-.87.06-2.92 0-5.24-1.74-5.24-4.04 0-2.31 2.32-4.05 5.24-4.05Z"></path>
                        <circle cx="6.9" cy="10.75" r="0.75" fill="currentColor" stroke="none"></circle>
                        <circle cx="10.1" cy="10.75" r="0.75" fill="currentColor" stroke="none"></circle>
                        <circle cx="14.35" cy="14.2" r="0.75" fill="currentColor" stroke="none"></circle>
                        <circle cx="17.55" cy="14.2" r="0.75" fill="currentColor" stroke="none"></circle>
                    </svg>`;
                case 'douyin':
                    return `<svg class="platform-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M13 4.25c.52 1.6 1.56 2.88 3.08 3.53 1.08.47 2.24.57 3.42.41"></path>
                        <path d="M13 8.35v6.18a3.28 3.28 0 1 1-2.13-3.08"></path>
                    </svg>`;
                case 'xiaohongshu':
                    return `<svg class="platform-icon is-filled" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M22.405 9.879c0.002 0.016 0.01 0.02 0.07 0.019h0.725a0.797 0.797 0 0 0 0.78 -0.972 0.794 0.794 0 0 0 -0.884 -0.618 0.795 0.795 0 0 0 -0.692 0.794c0 0.101 -0.002 0.666 0.001 0.777zm-11.509 4.808c-0.203 0.001 -1.353 0.004 -1.685 0.003a2.528 2.528 0 0 1 -0.766 -0.126 0.025 0.025 0 0 0 -0.03 0.014L7.7 16.127a0.025 0.025 0 0 0 0.01 0.032c0.111 0.06 0.336 0.124 0.495 0.124 0.66 0.01 1.32 0.002 1.981 0 0.01 0 0.02 -0.006 0.023 -0.015l0.712 -1.545a0.025 0.025 0 0 0 -0.024 -0.036zM0.477 9.91c-0.071 0 -0.076 0.002 -0.076 0.01a0.834 0.834 0 0 0 -0.01 0.08c-0.027 0.397 -0.038 0.495 -0.234 3.06 -0.012 0.24 -0.034 0.389 -0.135 0.607 -0.026 0.057 -0.033 0.042 0.003 0.112 0.046 0.092 0.681 1.523 0.787 1.74 0.008 0.015 0.011 0.02 0.017 0.02 0.008 0 0.033 -0.026 0.047 -0.044 0.147 -0.187 0.268 -0.391 0.371 -0.606 0.306 -0.635 0.44 -1.325 0.486 -1.706 0.014 -0.11 0.021 -0.22 0.03 -0.33l0.204 -2.616 0.022 -0.293c0.003 -0.029 0 -0.033 -0.03 -0.034zm7.203 3.757a1.427 1.427 0 0 1 -0.135 -0.607c-0.004 -0.084 -0.031 -0.39 -0.235 -3.06a0.443 0.443 0 0 0 -0.01 -0.082c-0.004 -0.011 -0.052 -0.008 -0.076 -0.008h-1.48c-0.03 0.001 -0.034 0.005 -0.03 0.034l0.021 0.293c0.076 0.982 0.153 1.964 0.233 2.946 0.05 0.4 0.186 1.085 0.487 1.706 0.103 0.215 0.223 0.419 0.37 0.606 0.015 0.018 0.037 0.051 0.048 0.049 0.02 -0.003 0.742 -1.642 0.804 -1.765 0.036 -0.07 0.03 -0.055 0.003 -0.112zm3.861 -0.913h-0.872a0.126 0.126 0 0 1 -0.116 -0.178l1.178 -2.625a0.025 0.025 0 0 0 -0.023 -0.035l-1.318 -0.003a0.148 0.148 0 0 1 -0.135 -0.21l0.876 -1.954a0.025 0.025 0 0 0 -0.023 -0.035h-1.56c-0.01 0 -0.02 0.006 -0.024 0.015l-0.926 2.068c-0.085 0.169 -0.314 0.634 -0.399 0.938a0.534 0.534 0 0 0 -0.02 0.191 0.46 0.46 0 0 0 0.23 0.378 0.981 0.981 0 0 0 0.46 0.119h0.59c0.041 0 -0.688 1.482 -0.834 1.972a0.53 0.53 0 0 0 -0.023 0.172 0.465 0.465 0 0 0 0.23 0.398c0.15 0.092 0.342 0.12 0.475 0.12l1.66 -0.001c0.01 0 0.02 -0.006 0.023 -0.015l0.575 -1.28a0.025 0.025 0 0 0 -0.024 -0.035zm-6.93 -4.937H3.1a0.032 0.032 0 0 0 -0.034 0.033c0 1.048 -0.01 2.795 -0.01 6.829 0 0.288 -0.269 0.262 -0.28 0.262h-0.74c-0.04 0.001 -0.044 0.004 -0.04 0.047 0.001 0.037 0.465 1.064 0.555 1.263 0.01 0.02 0.03 0.033 0.051 0.033 0.157 0.003 0.767 0.009 0.938 -0.014 0.153 -0.02 0.3 -0.06 0.438 -0.132 0.3 -0.156 0.49 -0.419 0.595 -0.765 0.052 -0.172 0.075 -0.353 0.075 -0.533 0.002 -2.33 0 -4.66 -0.007 -6.991a0.032 0.032 0 0 0 -0.032 -0.032zm11.784 6.896c0 -0.014 -0.01 -0.021 -0.024 -0.022h-1.465c-0.048 -0.001 -0.049 -0.002 -0.05 -0.049v-4.66c0 -0.072 -0.005 -0.07 0.07 -0.07h0.863c0.08 0 0.075 0.004 0.075 -0.074V8.393c0 -0.082 0.006 -0.076 -0.08 -0.076h-3.5c-0.064 0 -0.075 -0.006 -0.075 0.073v1.445c0 0.083 -0.006 0.077 0.08 0.077h0.854c0.075 0 0.07 -0.004 0.07 0.07v4.624c0 0.095 0.008 0.084 -0.085 0.084 -0.37 0 -1.11 -0.002 -1.304 0 -0.048 0.001 -0.06 0.03 -0.06 0.03l-0.697 1.519s-0.014 0.025 -0.008 0.036c0.006 0.01 0.013 0.008 0.058 0.008 1.748 0.003 3.495 0.002 5.243 0.002 0.03 -0.001 0.034 -0.006 0.035 -0.033v-1.539zm4.177 -3.43c0 0.013 -0.007 0.023 -0.02 0.024 -0.346 0.006 -0.692 0.004 -1.037 0.004 -0.014 -0.002 -0.022 -0.01 -0.022 -0.024 -0.005 -0.434 -0.007 -0.869 -0.01 -1.303 0 -0.072 -0.006 -0.071 0.07 -0.07l0.733 -0.003c0.041 0 0.081 0.002 0.12 0.015 0.093 0.025 0.16 0.107 0.165 0.204 0.006 0.431 0.002 1.153 0.001 1.153zm2.67 0.244a1.953 1.953 0 0 0 -0.883 -0.222h-0.18c-0.04 -0.001 -0.04 -0.003 -0.042 -0.04V10.21c0 -0.132 -0.007 -0.263 -0.025 -0.394a1.823 1.823 0 0 0 -0.153 -0.53 1.533 1.533 0 0 0 -0.677 -0.71 2.167 2.167 0 0 0 -1 -0.258c-0.153 -0.003 -0.567 0 -0.72 0 -0.07 0 -0.068 0.004 -0.068 -0.065V7.76c0 -0.031 -0.01 -0.041 -0.046 -0.039H17.93s-0.016 0 -0.023 0.007c-0.006 0.006 -0.008 0.012 -0.008 0.023v0.546c-0.008 0.036 -0.057 0.015 -0.082 0.022h-0.95c-0.022 0.002 -0.028 0.008 -0.03 0.032v1.481c0 0.09 -0.004 0.082 0.082 0.082h0.913c0.082 0 0.072 0.128 0.072 0.128v1.148s0.003 0.117 -0.06 0.117h-1.482c-0.068 0 -0.06 0.082 -0.06 0.082v1.445s-0.01 0.068 0.064 0.068h1.457c0.082 0 0.076 -0.006 0.076 0.079v3.225c0 0.088 -0.007 0.081 0.082 0.081h1.43c0.09 0 0.082 0.007 0.082 -0.08v-3.27c0 -0.029 0.006 -0.035 0.033 -0.035l2.323 -0.003c0.098 0 0.191 0.02 0.28 0.061a0.46 0.46 0 0 1 0.274 0.407c0.008 0.395 0.003 0.79 0.003 1.185 0 0.259 -0.107 0.367 -0.33 0.367h-1.218c-0.023 0.002 -0.029 0.008 -0.028 0.033 0.184 0.437 0.374 0.871 0.57 1.303a0.045 0.045 0 0 0 0.04 0.026c0.17 0.005 0.34 0.002 0.51 0.003 0.15 -0.002 0.517 0.004 0.666 -0.01a2.03 2.03 0 0 0 0.408 -0.075c0.59 -0.18 0.975 -0.698 0.976 -1.313v-1.981c0 -0.128 -0.01 -0.254 -0.034 -0.38 0 0.078 -0.029 -0.641 -0.724 -0.998z"></path>
                    </svg>`;
                case 'x':
                    return `<svg class="platform-icon is-filled" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M18.24 3H20.8l-5.6 6.4L22 21h-5.14l-4.03-5.25L8.22 21H5.66l5.99-6.85L2 3h5.27l3.64 4.8L18.24 3Zm-1 16.1h1.42L6.5 4.82H5.1Z"></path>
                    </svg>`;
                default:
                    return `<svg class="platform-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <circle cx="12" cy="12" r="7.25"></circle>
                        <path d="M4.75 12h14.5"></path>
                        <path d="M12 4.75c2.12 2.1 2.12 12.4 0 14.5"></path>
                        <path d="M12 4.75c-2.12 2.1-2.12 12.4 0 14.5"></path>
                    </svg>`;
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
            const processingBadge = item?.parse_status === 'processing'
                ? `<div class="card-preview-status">
                        <span class="activity-chip is-processing"><span class="activity-chip-pulse" aria-hidden="true"></span>解析中</span>
                    </div>`
                : '';
            const badge = images.length > 1
                ? `<span class="card-media-badge">${images.length} 张图片</span>`
                : (videos.length > 0 ? '<span class="card-media-badge">视频</span>' : '');
            const previewBody = thumb
                ? `<img src="${escapeAttribute(resolveMediaUrl(thumb.url))}" loading="lazy" decoding="async" fetchpriority="low" alt="">`
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
                    ${processingBadge}
                    <div class="card-icon">${renderPlatformMark(item)}</div>
                    ${badge}
                </div>
            `;
        }
