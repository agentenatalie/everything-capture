import WebKit
import UIKit
import Foundation

struct ExtractionData {
    let title: String
    let text: String
    let html: String?
}

class WebViewExtractor: NSObject, WKNavigationDelegate {
    private var webView: WKWebView!
    private var extractContinuation: CheckedContinuation<ExtractionData, Error>?
    private var stabilityTimer: Timer?
    private var lastTextLength: Int = 0
    private var stabilityCount: Int = 0
    private var timeoutItem: DispatchWorkItem?
    
    override init() {
        super.init()
        
        let config = WKWebViewConfiguration()
        config.processPool = WKProcessPool()
        
        // ★ 核心修复：给 WebView 一个真实的 iPhone 尺寸（即使不可见）
        let screenSize = UIScreen.main.bounds.size
        webView = WKWebView(frame: CGRect(x: 0, y: 0, width: screenSize.width, height: screenSize.height), configuration: config)
        webView.navigationDelegate = self
        
        // 使用移动端 Safari UA，因为小红书桌面端强制要求带 Cookie 登录才能查看笔记
        // 而移动端虽然有 App 引导遮罩，但 DOM 中包含了正文
        webView.customUserAgent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        // ★ 核心修复：将 WebView 挂载到 App 窗口中（offscreen）
        // 许多网站在 WebView 不在视图层级中时会完全不渲染
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            if let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
               let window = windowScene.windows.first {
                self.webView.alpha = 0.01 // 几乎不可见但在视图树中
                window.addSubview(self.webView)
            }
        }
    }
    
    deinit {
        DispatchQueue.main.async { [weak webView] in
            webView?.removeFromSuperview()
        }
    }
    
    func extract(from url: URL) async throws -> ExtractionData {
        // 强制升级 HTTP 到 HTTPS 以避免 iOS App Transport Security 拦截
        var finalURL = url
        if finalURL.scheme == "http" {
            if let httpsURL = URL(string: finalURL.absoluteString.replacingOccurrences(of: "http://", with: "https://")) {
                finalURL = httpsURL
            }
        }
        
        // ★ 小红书专用：先尝试 HTTP 直接提取（完全绕过 WebView 反爬）
        let urlString = finalURL.absoluteString
        if urlString.contains("xiaohongshu.com") || urlString.contains("xhslink.com") || urlString.contains("xhs.cn") {
            if let result = await extractXiaohongshuViaHTTP(from: finalURL),
               result.text.trimmingCharacters(in: .whitespacesAndNewlines).count > 20 {
                return result
            }
        }
        
        // 通用 WebView 提取（非小红书 或 小红书 HTTP 提取失败时的兜底）
        return try await withCheckedThrowingContinuation { continuation in
            self.extractContinuation = continuation
            
            DispatchQueue.main.async {
                self.timeoutItem = DispatchWorkItem { [weak self] in
                    self?.finishWithExtraction()
                }
                // 给页面 20 秒加载
                DispatchQueue.main.asyncAfter(deadline: .now() + 20, execute: self.timeoutItem!)
                
                let request = URLRequest(url: finalURL)
                self.webView.load(request)
            }
        }
    }
    
    // MARK: - 小红书 HTTP 直接提取（不经过 WebView）
    
    private func extractXiaohongshuViaHTTP(from url: URL) async -> ExtractionData? {
        do {
            var request = URLRequest(url: url)
            request.setValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1", forHTTPHeaderField: "User-Agent")
            request.timeoutInterval = 15
            
            let (data, _) = try await URLSession.shared.data(for: request)
            guard let html = String(data: data, encoding: .utf8) else { return nil }
            
            // 策略 1: 从原始 HTML 中解析 __INITIAL_STATE__ JSON
            if let ssrData = parseXHSInitialState(from: html) {
                return ssrData
            }
            
            // 策略 2: 从 Open Graph meta 标签中提取
            if let metaData = parseXHSMetaTags(from: html) {
                return metaData
            }
            
            return nil
        } catch {
            return nil
        }
    }
    
    private func parseXHSInitialState(from html: String) -> ExtractionData? {
        // 查找 window.__INITIAL_STATE__ 或 window.__INITIAL_SSR_STATE__
        let markers = ["window.__INITIAL_STATE__", "window.__INITIAL_SSR_STATE__"]
        
        for marker in markers {
            guard let markerRange = html.range(of: marker) else { continue }
            
            // 找到 '=' 号后的 JSON 起始位置
            let afterMarker = html[markerRange.upperBound...]
            guard let eqIndex = afterMarker.firstIndex(of: "=") else { continue }
            let afterEq = html[html.index(after: eqIndex)...]
            let trimmed = afterEq.drop(while: { $0.isWhitespace })
            guard trimmed.first == "{" else { continue }
            
            // 使用平衡括号法找到完整的 JSON 对象
            var depth = 0
            var endIndex = trimmed.startIndex
            var inString = false
            var prevChar: Character = " "
            
            for i in trimmed.indices {
                let ch = trimmed[i]
                if ch == "\"" && prevChar != "\\" {
                    inString = !inString
                } else if !inString {
                    if ch == "{" { depth += 1 }
                    else if ch == "}" { depth -= 1 }
                    if depth == 0 {
                        endIndex = trimmed.index(after: i)
                        break
                    }
                }
                prevChar = ch
            }
            
            guard depth == 0 else { continue }
            
            var jsonStr = String(trimmed[trimmed.startIndex..<endIndex])
            jsonStr = jsonStr.replacingOccurrences(of: "undefined", with: "null")
            
            guard let jsonData = jsonStr.data(using: .utf8),
                  let state = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any] else {
                continue
            }
            
            // 尝试从 noteData.data 路径获取
            if let noteData = state["noteData"] as? [String: Any],
               let dataMap = noteData["data"] as? [String: Any] {
                for (_, value) in dataMap {
                    if let noteWrapper = value as? [String: Any],
                       let noteObj = noteWrapper["note"] as? [String: Any] {
                        if let result = extractNoteFields(from: noteObj) {
                            return result
                        }
                    }
                }
            }
            
            // 尝试从 note.noteDetailMap 路径获取
            if let noteSection = state["note"] as? [String: Any],
               let noteDetailMap = noteSection["noteDetailMap"] as? [String: Any] {
                for (_, value) in noteDetailMap {
                    if let noteDetail = value as? [String: Any] {
                        let noteObj = (noteDetail["note"] as? [String: Any]) ?? noteDetail
                        if let result = extractNoteFields(from: noteObj) {
                            return result
                        }
                    }
                }
            }
        }
        
        return nil
    }
    
    private func extractNoteFields(from noteObj: [String: Any]) -> ExtractionData? {
        let title = noteObj["title"] as? String ?? ""
        let desc = noteObj["desc"] as? String ?? ""
        
        var tags = ""
        if let tagList = noteObj["tagList"] as? [[String: Any]] {
            tags = tagList.compactMap { ($0["name"] as? String) ?? ($0["tagName"] as? String) }
                .filter { !$0.isEmpty }
                .map { "#\($0)" }
                .joined(separator: " ")
        }
        
        var fullText = ""
        if !title.isEmpty { fullText += title + "\n\n" }
        if !desc.isEmpty { fullText += desc }
        if !tags.isEmpty { fullText += "\n\n" + tags }
        
        let trimmedText = fullText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmedText.count > 20 else { return nil }
        return ExtractionData(title: title.isEmpty ? "Unknown" : title, text: trimmedText, html: nil)
    }
    
    private func parseXHSMetaTags(from html: String) -> ExtractionData? {
        let title = extractMetaContent(from: html, attribute: "property", value: "og:title")
                  ?? extractMetaContent(from: html, attribute: "name", value: "title")
                  ?? ""
        
        let desc = extractMetaContent(from: html, attribute: "property", value: "og:description")
                 ?? extractMetaContent(from: html, attribute: "name", value: "description")
                 ?? ""
        
        guard !desc.isEmpty else { return nil }
        
        var fullText = ""
        if !title.isEmpty { fullText += title + "\n\n" }
        fullText += desc
        
        let trimmedText = fullText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmedText.count > 10 else { return nil }
        return ExtractionData(title: title.isEmpty ? "Unknown" : title, text: trimmedText, html: nil)
    }
    
    private func extractMetaContent(from html: String, attribute: String, value: String) -> String? {
        // 兼容两种顺序: <meta property="x" content="y"> 和 <meta content="y" property="x">
        let patterns = [
            "<meta[^>]*\(attribute)=\"\(value)\"[^>]*content=\"([^\"]*?)\"",
            "<meta[^>]*content=\"([^\"]*?)\"[^>]*\(attribute)=\"\(value)\""
        ]
        
        for pattern in patterns {
            guard let regex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive) else { continue }
            let nsRange = NSRange(html.startIndex..., in: html)
            if let match = regex.firstMatch(in: html, options: [], range: nsRange),
               let contentRange = Range(match.range(at: 1), in: html) {
                return String(html[contentRange])
                    .replacingOccurrences(of: "&amp;", with: "&")
                    .replacingOccurrences(of: "&lt;", with: "<")
                    .replacingOccurrences(of: "&gt;", with: ">")
                    .replacingOccurrences(of: "&quot;", with: "\"")
                    .replacingOccurrences(of: "&#39;", with: "'")
            }
        }
        return nil
    }
    
    // MARK: - WKNavigationDelegate
    
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // 页面加载完成后，等待 2 秒再检测稳定性
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
            self.startStabilityCheck()
        }
    }
    
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        // 处理 provisional navigation 失败（如 DNS 解析失败等）
        if let cont = extractContinuation {
            cont.resume(throwing: error)
            extractContinuation = nil
        }
    }
    
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if let cont = extractContinuation {
            cont.resume(throwing: error)
            extractContinuation = nil
        }
    }
    
    // MARK: - 稳定性检测
    
    private func startStabilityCheck() {
        stabilityCount = 0
        lastTextLength = 0
        
        let maxChecks = 16 // 最多 8 秒
        var currentChecks = 0
        
        stabilityTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] timer in
            guard let self = self else {
                timer.invalidate()
                return
            }
            currentChecks += 1
            if currentChecks >= maxChecks {
                timer.invalidate()
                self.executeScrollAndExtract()
                return
            }
            
            self.webView.evaluateJavaScript("document.body ? document.body.innerText.length : 0") { (result, error) in
                if let length = result as? Int {
                    if self.lastTextLength > 0 && abs(self.lastTextLength - length) < max(Int(Double(self.lastTextLength) * 0.05), 5) {
                        self.stabilityCount += 1
                    } else {
                        self.stabilityCount = 0
                    }
                    self.lastTextLength = length
                    
                    if self.stabilityCount >= 2 {
                        timer.invalidate()
                        self.executeScrollAndExtract()
                    }
                }
            }
        }
    }
    
    // MARK: - 自动滚动触发懒加载
    
    private func executeScrollAndExtract() {
        // 用简单同步滚动代替 async（兼容性更好）
        let scrollScript = """
        (function() {
            window.scrollTo(0, document.body.scrollHeight * 0.6);
            setTimeout(function() {
                window.scrollTo(0, document.body.scrollHeight);
                setTimeout(function() {
                    window.scrollTo(0, 0);
                }, 800);
            }, 800);
            return true;
        })();
        """
        
        webView.evaluateJavaScript(scrollScript) { _, _ in
            // 滚动后额外等待 2 秒再提取
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
                self.finishWithExtraction()
            }
        }
    }
    
    // MARK: - 正文提取
    
    private func finishWithExtraction() {
        self.timeoutItem?.cancel()
        self.stabilityTimer?.invalidate()
        
        // 第一步：强制显示隐藏的正文节点
        let unhideScript = """
        (function() {
            var selectors = '#js_content, article, .article, .content, main, .RichText, .rich_media_content, .Post-RichTextContainer, #noteContainer, .note-detail, .note-content, #detail-desc, .desc, .note-text, .note-scroller';
            var nodes = document.querySelectorAll(selectors);
            for(var i = 0; i < nodes.length; i++) {
                nodes[i].style.cssText = 'display:block !important; opacity:1 !important; visibility:visible !important; height:auto !important; overflow:visible !important; max-height:none !important;';
            }
            // 彻底移除小红书的 App 引导遮罩层，防止其文本被收集
            var overlays = document.querySelectorAll('.download-guide, .open-app-btn, .launch-app-modal, [class*="openApp"], [class*="download"], .bottom-button-box');
            for(var j = 0; j < overlays.length; j++) {
                if(overlays[j] && overlays[j].parentNode) {
                    overlays[j].parentNode.removeChild(overlays[j]);
                }
            }
        })();
        """
        
        webView.evaluateJavaScript(unhideScript) { [weak self] _, _ in
            guard let self = self else { return }
            
            // 第二步：检测是否为小红书，使用专用提取
            let currentURL = self.webView.url?.absoluteString ?? ""
            if currentURL.contains("xiaohongshu.com") || currentURL.contains("xhslink.com") || currentURL.contains("xhs.cn") {
                self.executeXiaohongshuExtraction()
                return
            }
            
            // 第三步：通用页面 → 尝试 Readability
            guard let readabilityPath = Bundle.main.path(forResource: "Readability", ofType: "js"),
                  let readabilityScript = try? String(contentsOfFile: readabilityPath) else {
                // Readability.js 文件找不到，直接使用 fallback
                self.executeFallbackExtraction()
                return
            }
            
            self.webView.evaluateJavaScript(readabilityScript) { [weak self] _, error in
                guard let self = self else { return }
                
                let parseScript = """
                (function() {
                    try {
                        var doc = document.cloneNode(true);
                        var article = new Readability(doc).parse();
                        if (article && article.textContent && article.textContent.trim().length > 100) {
                            return { title: article.title || document.title, text: article.textContent, html: article.content || "" };
                        }
                    } catch(e) {}
                    return null;
                })();
                """
                
                self.webView.evaluateJavaScript(parseScript) { (result, error) in
                    if let dict = result as? [String: Any],
                       let title = dict["title"] as? String,
                       let text = dict["text"] as? String,
                       let html = dict["html"] as? String,
                       text.trimmingCharacters(in: .whitespacesAndNewlines).count > 100 {
                        self.resumeContinuation(with: ExtractionData(title: title, text: text, html: html))
                    } else {
                        self.executeFallbackExtraction()
                    }
                }
            }
        }
    }
    
    // MARK: - 小红书专用提取
    
    private func executeXiaohongshuExtraction() {
        // 策略 1：从 window.__INITIAL_STATE__ 或 __INITIAL_SSR_STATE__ SSR 数据中提取笔记内容
        let ssrScript = """
        (function() {
            try {
                // 尝试直接从全局变量读取
                var state = window.__INITIAL_STATE__ || window.__INITIAL_SSR_STATE__;
                if (!state) {
                    // 从 script 标签中查找
                    var scripts = document.querySelectorAll('script');
                    for (var i = 0; i < scripts.length; i++) {
                        var text = scripts[i].textContent || '';
                        if (text.indexOf('__INITIAL_STATE__') !== -1 || text.indexOf('__INITIAL_SSR_STATE__') !== -1) {
                            var match = text.match(/window\\.__INITIAL_(?:SSR_)?STATE__\\s*=\\s*(\\{.+\\})/s);
                            if (match && match[1]) {
                                // 处理 undefined 值（小红书的 SSR 常见）
                                var cleaned = match[1].replace(/undefined/g, 'null');
                                state = JSON.parse(cleaned);
                            }
                            break;
                        }
                    }
                }
                
                if (state && state.note && state.note.noteDetailMap) {
                    var noteMap = state.note.noteDetailMap;
                    var noteKeys = Object.keys(noteMap);
                    if (noteKeys.length > 0) {
                        var noteData = noteMap[noteKeys[0]];
                        var note = noteData.note || noteData;
                        var title = note.title || '';
                        var desc = note.desc || '';
                        
                        // 提取标签
                        var tags = '';
                        if (note.tagList && note.tagList.length > 0) {
                            tags = note.tagList.map(function(t) { return '#' + (t.name || t.tagName || ''); }).join(' ');
                        }
                        
                        var fullText = '';
                        if (title) fullText += title + '\\n\\n';
                        if (desc) fullText += desc;
                        if (tags) fullText += '\\n\\n' + tags;
                        
                        if (fullText.trim().length > 20) {
                            return { title: title || document.title, text: fullText.trim() };
                        }
                    }
                }
                
                // 也尝试 note.firstNoteId 路径
                if (state && state.note && state.note.firstNoteId) {
                    var fid = state.note.firstNoteId;
                    var nd = state.note.noteDetailMap && state.note.noteDetailMap[fid];
                    if (nd) {
                        var n = nd.note || nd;
                        var t = n.title || '';
                        var d = n.desc || '';
                        var combined = (t ? t + '\\n\\n' : '') + d;
                        if (combined.trim().length > 20) {
                            return { title: t || document.title, text: combined.trim() };
                        }
                    }
                }
            } catch(e) {
                // SSR 解析失败，返回 null 让后备方案接管
            }
            return null;
        })();
        """
        
        webView.evaluateJavaScript(ssrScript) { [weak self] (result, error) in
            guard let self = self else { return }
            
            if let dict = result as? [String: Any],
               let title = dict["title"] as? String,
               let text = dict["text"] as? String,
               text.trimmingCharacters(in: .whitespacesAndNewlines).count > 20 {
                self.resumeContinuation(with: ExtractionData(title: title, text: text, html: nil))
                return
            }
            
            // 策略 2：DOM 选择器提取（小红书专用）
            self.executeXiaohongshuDOMExtraction()
        }
    }
    
    private func executeXiaohongshuDOMExtraction() {
        let domScript = """
        (function() {
            var title = document.title || 'Unknown';
            
            // 尝试获取标题
            var titleEl = document.querySelector('#detail-title') ||
                          document.querySelector('.title') ||
                          document.querySelector('[class*="title"]') ||
                          document.querySelector('h1');
            if (titleEl && titleEl.innerText && titleEl.innerText.trim().length > 0) {
                title = titleEl.innerText.trim();
            }
            
            // 小红书专用选择器（按优先级排列）
            var selectors = [
                '#detail-desc',
                '.note-text',
                '.note-content',
                '#noteContainer .content',
                '.note-scroller .content',
                '[class*="noteDetail"] [class*="desc"]',
                '[class*="note"] [class*="content"]',
                '.desc',
                'article',
                '.content',
                'main'
            ];
            
            for (var i = 0; i < selectors.length; i++) {
                try {
                    var node = document.querySelector(selectors[i]);
                    if (node && node.innerText && node.innerText.trim().length > 20) {
                        var text = title + '\\n\\n' + node.innerText.trim();
                        return { title: title, text: text, html: node.innerHTML || "" };
                    }
                } catch(e) {}
            }
            
            // 收集所有有意义的段落
            var allText = '';
            var tags = document.querySelectorAll('p, h1, h2, h3, span.desc, [class*="desc"]');
            for (var j = 0; j < tags.length; j++) {
                var t = tags[j].innerText;
                // 排除带有 App 下载提示的无关文本
                if (t && t.trim().length > 5 && t.indexOf('在浏览器中打开') === -1 && t.indexOf('已下载') === -1 && t.indexOf('打开App') === -1) {
                    allText += t.trim() + '\\n\\n';
                }
            }
            if (allText.trim().length > 50) {
                return { title: title, text: allText.trim(), html: '' };
            }
            
            // 最终兜底
            var bodyText = document.body ? document.body.innerText : '';
            // 简单清理兜底中的引导文本
            bodyText = bodyText.replace(/已下载[？?]点击右上角[，,]在浏览器中打开/g, '').replace(/打开App/gi, '');
            return { title: title, text: bodyText || '', html: '' };
        })();
        """
        
        webView.evaluateJavaScript(domScript) { [weak self] (result, error) in
            if let dict = result as? [String: Any],
               let title = dict["title"] as? String,
               let text = dict["text"] as? String {
                let html = dict["html"] as? String
                self?.resumeContinuation(with: ExtractionData(title: title, text: text, html: html))
            } else {
                self?.resumeContinuation(with: ExtractionData(title: "Unknown", text: "", html: nil))
            }
        }
    }
    
    // MARK: - 终极后备提取
    
    private func executeFallbackExtraction() {
        let fallbackScript = """
        (function() {
            var title = document.title || "Unknown";
            
            // 策略 1：精准节点选择器（覆盖主流平台）
            var selectors = [
                '#js_content',
                '.rich_media_content',
                '#detail-desc',
                '.note-text',
                '.note-content',
                'article',
                '[role="article"]',
                '.Post-RichTextContainer',
                '.RichText',
                '.article-content',
                '.post-content',
                '.story-body',
                '.content',
                'main'
            ];
            
            for (var i = 0; i < selectors.length; i++) {
                var node = document.querySelector(selectors[i]);
                if (node && node.innerText && node.innerText.trim().length > 50) {
                    return { title: title, text: node.innerText.trim(), html: node.innerHTML || "" };
                }
            }
            
            // 策略 2：暴力收集所有段落
            var allText = "";
            var allHtml = "";
            var tags = document.querySelectorAll('p, h1, h2, h3, h4, h5, h6, li, blockquote, pre, td');
            for (var j = 0; j < tags.length; j++) {
                var t = tags[j].innerText;
                if (t && t.trim().length > 5) {
                    allText += t.trim() + "\\n\\n";
                    allHtml += tags[j].outerHTML || "";
                }
            }
            if (allText.trim().length > 50) {
                return { title: title, text: allText.trim(), html: allHtml };
            }
            
            // 策略 3：直接拿 body
            var bodyText = document.body ? document.body.innerText : "";
            var bodyHtml = document.body ? document.body.innerHTML : "";
            return { title: title, text: bodyText || "", html: bodyHtml || "" };
        })();
        """
        
        webView.evaluateJavaScript(fallbackScript) { [weak self] (result, error) in
            if let dict = result as? [String: Any],
               let title = dict["title"] as? String,
               let text = dict["text"] as? String {
                let html = dict["html"] as? String
                self?.resumeContinuation(with: ExtractionData(title: title, text: text, html: html))
            } else {
                self?.resumeContinuation(with: ExtractionData(title: "Unknown", text: "", html: nil))
            }
        }
    }
    
    // MARK: - Continuation
    
    private func resumeContinuation(with data: ExtractionData) {
        if let cont = extractContinuation {
            cont.resume(returning: data)
            extractContinuation = nil
        }
    }
}
