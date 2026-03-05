import Foundation
import UIKit
import SwiftUI
import Combine

class AppClipboardManager: ObservableObject {
    @Published var detectedURL: URL?
    @Published var showCapturePrompt: Bool = false
    
    // 24-hour deduplication
    private let deduplicationKey = "GrabberDeduplicatedURLs"
    private var detectedHistory: [String: Date] {
        get {
            guard let data = UserDefaults.standard.data(forKey: deduplicationKey),
                  let dict = try? JSONDecoder().decode([String: Date].self, from: data) else {
                return [:]
            }
            return dict
        }
        set {
            if let data = try? JSONEncoder().encode(newValue) {
                UserDefaults.standard.set(data, forKey: deduplicationKey)
            }
        }
    }

    func checkClipboard() {
        guard let string = UIPasteboard.general.string else { return }
        if let url = extractURL(from: string), isNovelURL(url.absoluteString) {
            self.detectedURL = url
            self.showCapturePrompt = true
        }
    }
    
    private func extractURL(from text: String) -> URL? {
        let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        let matches = detector?.matches(in: text, options: [], range: NSRange(location: 0, length: text.utf16.count))
        
        if let match = matches?.first, let url = match.url {
            if url.scheme == "http" || url.scheme == "https" {
                return url
            }
        }
        return nil
    }
    
    private func isNovelURL(_ urlString: String) -> Bool {
        // V1.0.1 强制去除去重检查逻辑，永远允许弹出
        // 这个方法现在只负责记录历史但不负责拦截
        detectedHistory[urlString] = Date()
        return true
    }
    
    func ignoreCurrent() {
        showCapturePrompt = false
        detectedURL = nil
    }
}
