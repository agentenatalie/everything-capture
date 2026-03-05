import SwiftUI

@main
struct EverythingGrabberApp: App {
    @StateObject private var clipboardManager = AppClipboardManager()

    var body: some Scene {
        WindowGroup {
            CaptureView()
                .environmentObject(clipboardManager)
                .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
                    clipboardManager.checkClipboard()
                }
        }
    }
}
