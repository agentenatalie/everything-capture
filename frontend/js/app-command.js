        function openCommandPalette() {
            if (!ensureAuthenticated({ mode: 'email' })) return;
            commandOverlay.classList.add('active');
            updateCommandPaletteState();
            requestAnimationFrame(() => {
                urlInput.focus();
                urlInput.select();
            });
        }

        function closeCommandPalette() {
            commandOverlay.classList.remove('active');
            urlInput.blur();
        }

        async function importFromClipboard() {
            if (!ensureAuthenticated({ mode: 'email' })) return;
            if (!navigator.clipboard?.readText) {
                showToast('当前浏览器不支持读取剪贴板', 'error');
                return;
            }

            clipboardBtn.disabled = true;
            clipboardBtn.classList.add('is-loading');
            clipboardBtnLabel.textContent = '读取剪贴板中...';
            try {
                const text = (await navigator.clipboard.readText()).trim();
                if (!text) {
                    showToast('剪贴板为空', 'error');
                    return;
                }
                urlInput.value = text;
                updateCommandPaletteState();
                urlInput.focus();
                urlInput.select();
                const resolvedUrl = resolveCommandUrl(text);
                if (resolvedUrl && !isLikelyUrl(text)) {
                    showToast('已识别分享文案中的链接，开始导入', 'success');
                    extractURL(resolvedUrl);
                    return;
                }
                showToast('已导入剪贴板内容', 'success');
            } catch (e) {
                showToast('读取剪贴板失败：' + e.message, 'error');
            } finally {
                clipboardBtn.disabled = false;
                clipboardBtn.classList.remove('is-loading');
                clipboardBtnLabel.textContent = '从剪贴板导入';
            }
        }
