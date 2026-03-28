import AppKit
import SwiftUI

enum WindowSceneID: String {
    case researchList = "research-list"
    case researchTable = "research-table"
    case summarize = "summarize"
    case prettifyCodexLog = "prettify-codex-log"
    case settings = "settings"
}

@MainActor
final class WindowCoordinator: ObservableObject {
    private final class WeakWindowBox {
        weak var window: NSWindow?

        init(window: NSWindow) {
            self.window = window
        }
    }

    private var windows: [WindowSceneID: WeakWindowBox] = [:]

    func register(window: NSWindow?, for sceneID: WindowSceneID) {
        guard let window else { return }
        windows[sceneID] = WeakWindowBox(window: window)
        configure(window)
    }

    func openAndActivate(_ sceneID: WindowSceneID, openWindow: OpenWindowAction) {
        if let window = windows[sceneID]?.window {
            activate(window)
            return
        }

        openWindow(id: sceneID.rawValue)

        Task { @MainActor in
            for _ in 0..<20 {
                if let window = windows[sceneID]?.window {
                    activate(window)
                    return
                }
                try? await Task.sleep(nanoseconds: 50_000_000)
            }
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    private func activate(_ window: NSWindow) {
        configure(window)
        if window.isMiniaturized {
            window.deminiaturize(nil)
        }
        window.center()
        NSApp.activate(ignoringOtherApps: true)
        window.orderFrontRegardless()
        window.makeKeyAndOrderFront(nil)
    }

    private func configure(_ window: NSWindow) {
        window.tabbingMode = .disallowed
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.styleMask.insert(.fullSizeContentView)

        window.toolbar = nil
        window.showsToolbarButton = false


        window.isOpaque = false
        window.toolbar = nil
        window.isMovableByWindowBackground = false
        window.hasShadow = true

        window.standardWindowButton(.closeButton)?.isHidden = true
        window.standardWindowButton(.miniaturizeButton)?.isHidden = true
        window.standardWindowButton(.zoomButton)?.isHidden = true
    }
}

struct ManagedWindowRoot<Content: View>: View {
    @EnvironmentObject private var coordinator: WindowCoordinator

    let sceneID: WindowSceneID
    @ViewBuilder let content: Content

    var body: some View {
        content
            .background(WindowRegistrationView(sceneID: sceneID).environmentObject(coordinator))
    }
}

private struct WindowRegistrationView: NSViewRepresentable {
    @EnvironmentObject private var coordinator: WindowCoordinator

    let sceneID: WindowSceneID

    func makeNSView(context: Context) -> TrackingView {
        let view = TrackingView()
        view.onWindowChange = { window in
            Task { @MainActor in
                coordinator.register(window: window, for: sceneID)
            }
        }
        return view
    }

    func updateNSView(_ nsView: TrackingView, context: Context) {
        Task { @MainActor in
            coordinator.register(window: nsView.window, for: sceneID)
        }
    }
}

private final class TrackingView: NSView {
    var onWindowChange: ((NSWindow?) -> Void)?

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        onWindowChange?(window)
    }
}
