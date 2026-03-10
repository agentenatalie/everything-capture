import SwiftUI

struct CaptureView: View {
    @EnvironmentObject var clipboardManager: AppClipboardManager
    @State private var isExtracting = false
    @State private var extractionResult: String?
    
    var body: some View {
        NavigationView {
            VStack(spacing: 30) {
                Spacer()
                
                Image(systemName: "link.circle.fill")
                    .resizable()
                    .frame(width: 80, height: 80)
                    .foregroundColor(.blue)
                
                Text("Everything Grabber")
                    .font(.largeTitle)
                    .fontWeight(.bold)
                
                if let result = extractionResult {
                    Text(result)
                        .font(.headline)
                        .foregroundColor(result.contains("成功") ? .green : .red)
                        .multilineTextAlignment(.center)
                        .padding()
                        .background(Color.secondary.opacity(0.1))
                        .cornerRadius(10)
                } else if isExtracting {
                    VStack {
                        ProgressView()
                            .scaleEffect(1.5)
                        Text("正在抓取并同步...")
                            .padding(.top)
                            .foregroundColor(.secondary)
                    }
                } else {
                    Text("请复制任意链接以开始。")
                        .foregroundColor(.secondary)
                        .italic()
                    
                    Button(action: {
                        clipboardManager.checkClipboard()
                    }) {
                        Text("手动检测剪贴板")
                            .font(.headline)
                            .foregroundColor(.white)
                            .padding()
                            .frame(maxWidth: .infinity)
                            .background(Color.blue)
                            .cornerRadius(10)
                    }
                    .padding(.horizontal, 40)
                    .padding(.top, 20)
                }
                
                Spacer()
                
                Text("V1.0.3")
                    .font(.caption)
                    .foregroundColor(.gray)
            }
            .padding()
            .navigationTitle("收录助手")
        }
        .navigationViewStyle(StackNavigationViewStyle())
        .onAppear {
            // Simulator 偶尔收不到 didBecomeActive，初始化时也顺便检测一次
            clipboardManager.checkClipboard()
        }
        .alert(isPresented: $clipboardManager.showCapturePrompt) {
            Alert(
                title: Text("检测到链接"),
                message: Text("是否收录此链接？\n\n\(clipboardManager.detectedURL?.absoluteString ?? "")"),
                primaryButton: .default(Text("收录")) {
                    startExtraction()
                },
                secondaryButton: .cancel(Text("忽略")) {
                    clipboardManager.ignoreCurrent()
                }
            )
        }
    }
    
    private func startExtraction() {
        guard let url = clipboardManager.detectedURL else { return }
        clipboardManager.showCapturePrompt = false
        isExtracting = true
        extractionResult = nil
        
        Task {
            // 策略 1: 先尝试服务端提取（支持小红书/抖音/X/通用网站）
            do {
                let (_, title, textLength) = try await APIClient.shared.extractViaServer(url: url.absoluteString)
                DispatchQueue.main.async {
                    self.isExtracting = false
                    self.extractionResult = "收录成功 (服务端提取: \(title), \(textLength) 字)"
                }
                return
            } catch {
                // 服务端提取失败，继续尝试本地提取
                print("服务端提取失败，回退到本地: \(error.localizedDescription)")
            }
            
            // 策略 2: 回退到本地 WebView 提取
            do {
                let extractor = WebViewExtractor()
                let result = try await extractor.extract(from: url)
                let qualityResult = QualityGate.check(content: result.text)
                
                switch qualityResult {
                case .passed(let cleanedText):
                    let _ = try await APIClient.shared.ingest(
                        url: url.absoluteString,
                        title: result.title,
                        canonicalText: cleanedText,
                        canonicalHTML: result.html
                    )
                    DispatchQueue.main.async {
                        self.isExtracting = false
                        self.extractionResult = "收录成功 (本地提取, 内容长度: \(cleanedText.count))"
                    }
                case .tooShort(let length):
                    DispatchQueue.main.async {
                        self.isExtracting = false
                        self.extractionResult = "被拦截：发现文本过短\n仅提取到 \(length) 字符。通常原因是页面未渲染或防爬虫隔离。"
                    }
                case .blockedKeyword(let keyword):
                    DispatchQueue.main.async {
                        self.isExtracting = false
                        self.extractionResult = "被拦截：\n发现屏蔽词 '\(keyword)'。"
                    }
                }
            } catch {
                DispatchQueue.main.async {
                    self.isExtracting = false
                    self.extractionResult = "失败: \(error.localizedDescription)"
                }
            }
        }
    }
}
