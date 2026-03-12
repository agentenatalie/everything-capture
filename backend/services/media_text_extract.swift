import AVFoundation
import CoreGraphics
import Dispatch
import Foundation
import ImageIO
import Vision

struct ExtractRequest: Codable {
    struct Asset: Codable {
        let path: String
    }

    let images: [Asset]
    let videos: [Asset]
}

struct FrameText: Codable {
    let timestamp_seconds: Double
    let text: String
}

struct ImageResult: Codable {
    let path: String
    let ocr_text: String
    let qr_links: [String]
    let urls: [String]
}

struct VideoResult: Codable {
    let path: String
    let frame_texts: [FrameText]
    let qr_links: [String]
    let urls: [String]
}

struct ExtractResponse: Codable {
    let images: [ImageResult]
    let videos: [VideoResult]
}

enum ExtractorError: Error {
    case invalidArguments
    case invalidRequestFile
    case unreadableImage
}

func normalizeText(_ value: String) -> String {
    let normalized = value
        .replacingOccurrences(of: "\r\n", with: "\n")
        .replacingOccurrences(of: "\r", with: "\n")
    let compacted = normalized.replacingOccurrences(
        of: #"\n{3,}"#,
        with: "\n\n",
        options: .regularExpression
    )
    return compacted.trimmingCharacters(in: .whitespacesAndNewlines)
}

func normalizeUrl(_ value: String) -> String? {
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return nil }
    let compacted = trimmed.replacingOccurrences(
        of: #"[)\]}>.,!?;:'"。，！？；：]+$"#,
        with: "",
        options: .regularExpression
    )
    guard compacted.lowercased().hasPrefix("http://") || compacted.lowercased().hasPrefix("https://") else {
        return nil
    }
    return compacted
}

func uniquePreserveOrder(_ values: [String]) -> [String] {
    var ordered: [String] = []
    var seen = Set<String>()
    for rawValue in values {
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { continue }
        if seen.contains(value) { continue }
        seen.insert(value)
        ordered.append(value)
    }
    return ordered
}

func extractUrls(_ value: String) -> [String] {
    guard let regex = try? NSRegularExpression(pattern: #"https?://[^\s<>'"`]+"#, options: [.caseInsensitive]) else {
        return []
    }
    let nsValue = value as NSString
    let range = NSRange(location: 0, length: nsValue.length)
    let matches = regex.matches(in: value, options: [], range: range)
    return uniquePreserveOrder(matches.compactMap { match in
        normalizeUrl(nsValue.substring(with: match.range))
    })
}

func loadCGImage(from path: String) throws -> CGImage {
    let url = URL(fileURLWithPath: path)
    guard
        let source = CGImageSourceCreateWithURL(url as CFURL, nil),
        let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
    else {
        throw ExtractorError.unreadableImage
    }
    return image
}

func recognizeText(in image: CGImage) -> String {
    var recognized: [String] = []
    let request = VNRecognizeTextRequest { request, _ in
        let observations = request.results as? [VNRecognizedTextObservation] ?? []
        recognized = observations.compactMap { observation in
            observation.topCandidates(1).first?.string
        }
    }
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    if #available(macOS 13.0, *) {
        request.automaticallyDetectsLanguage = true
    }

    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    try? handler.perform([request])
    return normalizeText(recognized.joined(separator: "\n"))
}

func detectBarcodes(in image: CGImage) -> [String] {
    var payloads: [String] = []
    let request = VNDetectBarcodesRequest { request, _ in
        let observations = request.results as? [VNBarcodeObservation] ?? []
        payloads = observations.compactMap { $0.payloadStringValue }
    }

    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    try? handler.perform([request])
    return uniquePreserveOrder(payloads.compactMap(normalizeUrl))
}

func sampleTimestamps(durationSeconds: Double) -> [Double] {
    guard durationSeconds > 0 else { return [0] }

    let fractions: [Double]
    if durationSeconds <= 6 {
        fractions = [0.15, 0.5, 0.85]
    } else if durationSeconds <= 30 {
        fractions = [0.08, 0.24, 0.42, 0.6, 0.78, 0.92]
    } else {
        fractions = [0.05, 0.18, 0.32, 0.48, 0.64, 0.8, 0.94]
    }

    var points: [Double] = []
    for fraction in fractions {
        let second = max(min(durationSeconds * fraction, durationSeconds), 0)
        let rounded = (second * 10).rounded() / 10
        if !points.contains(rounded) {
            points.append(rounded)
        }
    }
    if !points.contains(0) {
        points.insert(0, at: 0)
    }
    return points.sorted()
}

func loadDurationSeconds(for asset: AVURLAsset) -> Double {
    if #available(macOS 13.0, *) {
        let semaphore = DispatchSemaphore(value: 0)
        var loadedDuration: CMTime = .zero

        Task {
            loadedDuration = (try? await asset.load(.duration)) ?? .zero
            semaphore.signal()
        }

        semaphore.wait()
        return max(CMTimeGetSeconds(loadedDuration), 0)
    }

    return 0
}

func extractVideo(path: String) -> VideoResult {
    let asset = AVURLAsset(url: URL(fileURLWithPath: path))
    let durationSeconds = loadDurationSeconds(for: asset)
    let imageGenerator = AVAssetImageGenerator(asset: asset)
    imageGenerator.appliesPreferredTrackTransform = true
    imageGenerator.requestedTimeToleranceBefore = .zero
    imageGenerator.requestedTimeToleranceAfter = .zero

    var frameTexts: [FrameText] = []
    var qrLinks: [String] = []
    var urls: [String] = []
    var seenTexts = Set<String>()

    for second in sampleTimestamps(durationSeconds: durationSeconds) {
        let cmTime = CMTime(seconds: second, preferredTimescale: 600)
        guard let frameImage = try? imageGenerator.copyCGImage(at: cmTime, actualTime: nil) else {
            continue
        }

        let text = recognizeText(in: frameImage)
        if !text.isEmpty && !seenTexts.contains(text) {
            seenTexts.insert(text)
            frameTexts.append(FrameText(timestamp_seconds: second, text: text))
            urls.append(contentsOf: extractUrls(text))
        }

        let frameQrLinks = detectBarcodes(in: frameImage)
        qrLinks.append(contentsOf: frameQrLinks)
        urls.append(contentsOf: frameQrLinks)
    }

    return VideoResult(
        path: path,
        frame_texts: frameTexts.sorted { lhs, rhs in
            lhs.timestamp_seconds < rhs.timestamp_seconds
        },
        qr_links: uniquePreserveOrder(qrLinks),
        urls: uniquePreserveOrder(urls)
    )
}

func extractImage(path: String) throws -> ImageResult {
    let image = try loadCGImage(from: path)
    let ocrText = recognizeText(in: image)
    let qrLinks = detectBarcodes(in: image)
    let urls = uniquePreserveOrder(extractUrls(ocrText) + qrLinks)
    return ImageResult(path: path, ocr_text: ocrText, qr_links: qrLinks, urls: urls)
}

func loadRequest(from path: String) throws -> ExtractRequest {
    let url = URL(fileURLWithPath: path)
    let data = try Data(contentsOf: url)
    return try JSONDecoder().decode(ExtractRequest.self, from: data)
}

func run() throws {
    guard CommandLine.arguments.count >= 2 else {
        throw ExtractorError.invalidArguments
    }

    let requestPath = CommandLine.arguments[1]
    let request = try loadRequest(from: requestPath)

    let imageResults = request.images.compactMap { asset in
        try? extractImage(path: asset.path)
    }
    let videoResults = request.videos.map { asset in
        extractVideo(path: asset.path)
    }

    let response = ExtractResponse(images: imageResults, videos: videoResults)
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.withoutEscapingSlashes]
    let data = try encoder.encode(response)
    if let output = String(data: data, encoding: .utf8) {
        FileHandle.standardOutput.write(output.data(using: .utf8)!)
    } else {
        throw ExtractorError.invalidRequestFile
    }
}

do {
    try run()
} catch {
    let message = String(describing: error)
    FileHandle.standardError.write(message.data(using: .utf8)!)
    exit(1)
}
