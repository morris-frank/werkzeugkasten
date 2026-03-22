import SwiftUI
import WerkzeugkastenCore

@main
struct WerkzeugkastenMenuBarApp: App {
    @StateObject private var settings = SettingsStore()
    @StateObject private var windowCoordinator = WindowCoordinator()

    init() {
        Task {
            await NotificationHelper.requestAuthorizationIfNeeded()
        }
    }

    var body: some Scene {
        MenuBarExtra("Werkzeugkasten", systemImage: "text.insert") {
            MenuBarContent()
                .environmentObject(settings)
                .environmentObject(windowCoordinator)
        }

        WindowGroup(id: WindowSceneID.researchList.rawValue) {
            ManagedWindowRoot(sceneID: .researchList) {
                ResearchListWindow()
            }
                .environmentObject(settings)
                .environmentObject(windowCoordinator)
        }
        .defaultWindowPlacement(centeredWindowPlacement)
        .windowResizability(.contentMinSize)
        .windowIdealSize(.fitToContent)
        .restorationBehavior(.disabled)

        WindowGroup(id: WindowSceneID.researchTable.rawValue) {
            ManagedWindowRoot(sceneID: .researchTable) {
                ResearchTableWindow()
            }
                .environmentObject(settings)
                .environmentObject(windowCoordinator)
        }
        .defaultWindowPlacement(centeredWindowPlacement)
        .windowResizability(.contentMinSize)
        .windowIdealSize(.fitToContent)
        .restorationBehavior(.disabled)

        WindowGroup(id: WindowSceneID.summarize.rawValue) {
            ManagedWindowRoot(sceneID: .summarize) {
                SummarizeWindow()
            }
                .environmentObject(settings)
                .environmentObject(windowCoordinator)
        }
        .defaultWindowPlacement(centeredWindowPlacement)
        .windowResizability(.contentMinSize)
        .windowIdealSize(.fitToContent)
        .restorationBehavior(.disabled)

        WindowGroup(id: WindowSceneID.prettifyCodexLog.rawValue) {
            ManagedWindowRoot(sceneID: .prettifyCodexLog) {
                PrettifyCodexLogWindow()
            }
                .environmentObject(settings)
                .environmentObject(windowCoordinator)
        }
        .defaultWindowPlacement(centeredWindowPlacement)
        .windowResizability(.contentMinSize)
        .windowIdealSize(.fitToContent)
        .restorationBehavior(.disabled)

        WindowGroup(id: WindowSceneID.settings.rawValue) {
            ManagedWindowRoot(sceneID: .settings) {
                SettingsWindow()
            }
                .environmentObject(settings)
                .environmentObject(windowCoordinator)
        }
        .defaultWindowPlacement(centeredWindowPlacement)
        .windowResizability(.contentSize)
        .restorationBehavior(.disabled)
    }

    private func centeredWindowPlacement(_ content: WindowLayoutRoot, _: WindowPlacementContext) -> WindowPlacement {
        WindowPlacement(.center, size: content.sizeThatFits(.unspecified))
    }
}
