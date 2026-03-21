import SwiftUI
import ShortcutsCore

@main
struct ShortcutsMenuBarApp: App {
    @StateObject private var settings = SettingsStore()

    init() {
        Task {
            await NotificationHelper.requestAuthorizationIfNeeded()
        }
    }

    var body: some Scene {
        MenuBarExtra("Shortcuts", systemImage: "text.insert") {
            MenuBarContent()
                .environmentObject(settings)
        }

        WindowGroup(id: "research-list") {
            ResearchListWindow()
                .environmentObject(settings)
        }
        .defaultSize(width: 520, height: 520)

        WindowGroup(id: "research-table") {
            ResearchTableWindow()
                .environmentObject(settings)
        }
        .defaultSize(width: 560, height: 620)

        WindowGroup(id: "summarize") {
            SummarizeWindow()
                .environmentObject(settings)
        }
        .defaultSize(width: 560, height: 620)

        WindowGroup(id: "settings") {
            SettingsWindow()
                .environmentObject(settings)
        }
        .defaultSize(width: 520, height: 420)
    }
}
