import Foundation

extension String {
    func withoutEmoji() -> String {
        return self.filter { character in
            for scalar in character.unicodeScalars {
                if scalar.properties.isEmojiPresentation || scalar.properties.isEmojiModifier || scalar.properties.isEmojiModifierBase {
                    return false
                }
            }
            return true
        }
    }
}

enum QualityResult {
    case passed(cleanedText: String)
    case tooShort(length: Int)
    case blockedKeyword(keyword: String)
}

class QualityGate {
    // 很多公众号文章底部包含"打开App"،但文章主体是有效的，所以我们暂时将严格屏蔽词放宽
    static let blockedKeywords = ["安全检查-访问受限", "为保证您的帐户安全", "已下载？点击右上角，在浏览器中打开"]
    
    static func check(content: String) -> QualityResult {
        // 清理掉 Emoji
        let cleanedContent = content.withoutEmoji().trimmingCharacters(in: .whitespacesAndNewlines)
        
        // 降低字数门槛，有些图片型公众号文章文字很少
        if cleanedContent.count < 100 {
            return .tooShort(length: cleanedContent.count)
        }
        
        for keyword in blockedKeywords {
            if cleanedContent.contains(keyword) {
                return .blockedKeyword(keyword: keyword)
            }
        }
        
        return .passed(cleanedText: cleanedContent)
    }
}


class APIClient {
    static let shared = APIClient()
    private let baseURL = "http://127.0.0.1:8000/api"
    
    enum APIError: Error {
        case invalidURL
        case networkError(Error)
        case serverError(Int)
        case unknown
    }
    
    func ingest(url: String, title: String, canonicalText: String) async throws -> String {
        guard let ingestURL = URL(string: "\(baseURL)/ingest") else {
            throw APIError.invalidURL
        }
        
        var request = URLRequest(url: ingestURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let payload: [String: Any] = [
            "source_url": url,
            "final_url": url,
            "title": title,
            "canonical_text": canonicalText,
            "canonical_html": "", // Skipping HTML
            "client": [
                "platform": "ios"
            ]
        ]
        
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.unknown
        }
        
        if httpResponse.statusCode == 201 || httpResponse.statusCode == 200 {
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let itemId = json["item_id"] as? String {
                return itemId
            }
            return "unknown_id"
        } else {
            throw APIError.serverError(httpResponse.statusCode)
        }
    }
    
    /// 服务端提取：发送 URL 到后端，由后端完成内容抓取
    func extractViaServer(url: String) async throws -> (itemId: String, title: String, textLength: Int) {
        guard let extractURL = URL(string: "\(baseURL)/extract") else {
            throw APIError.invalidURL
        }
        
        var request = URLRequest(url: extractURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30
        
        let payload: [String: Any] = ["url": url]
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.unknown
        }
        
        if httpResponse.statusCode == 201 || httpResponse.statusCode == 200 {
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let itemId = json["item_id"] as? String,
               let title = json["title"] as? String,
               let textLength = json["text_length"] as? Int {
                return (itemId, title, textLength)
            }
            throw APIError.unknown
        } else {
            throw APIError.serverError(httpResponse.statusCode)
        }
    }
}
