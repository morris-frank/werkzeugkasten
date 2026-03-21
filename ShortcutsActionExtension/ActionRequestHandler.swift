import Foundation
import UniformTypeIdentifiers
import ShortcutsCore

private final class ExtensionContextBox: @unchecked Sendable {
    let value: NSExtensionContext

    init(_ value: NSExtensionContext) {
        self.value = value
    }
}

final class ActionRequestHandler: NSObject, NSExtensionRequestHandling {
    func beginRequest(with context: NSExtensionContext) {
        let contextBox = ExtensionContextBox(context)

        Task { @MainActor in
            let extensionContext = contextBox.value

            do {
                let urls = try await Self.extractFileURLs(from: extensionContext.inputItems)
                let uniqueURLs = InputNormalizer.uniqueFileURLs(urls)
                let runner = EngineRunner()
                let response: SummarizeFilesResponse = try await runner.run(
                    .summarizeFiles,
                    payload: ["paths": uniqueURLs.map(\.path)],
                    configuration: try SettingsStore().configuration()
                )

                await NotificationHelper.post(
                    title: "Shortcuts Summary Complete",
                    body: response.failures.isEmpty
                        ? "Processed \(response.files.count) file(s)."
                        : "Processed \(response.files.count) file(s) with \(response.failures.count) failure(s)."
                )

                extensionContext.completeRequest(returningItems: nil)
            } catch {
                await NotificationHelper.post(
                    title: "Shortcuts Summary Failed",
                    body: error.localizedDescription
                )
                extensionContext.cancelRequest(withError: error)
            }
        }
    }

    private static func extractFileURLs(from items: [Any]) async throws -> [URL] {
        let extensionItems = items.compactMap { $0 as? NSExtensionItem }
        var urls: [URL] = []

        for item in extensionItems {
            for provider in item.attachments ?? [] where provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                urls.append(try await loadURL(from: provider))
            }
        }

        if urls.isEmpty {
            throw EngineError.invalidPayload("No files were provided to the Finder action.")
        }
        return urls
    }

    private static func loadURL(from provider: NSItemProvider) async throws -> URL {
        try await withCheckedThrowingContinuation { continuation in
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }

                if let url = item as? URL {
                    continuation.resume(returning: url)
                    return
                }

                if let data = item as? Data, let url = URL(dataRepresentation: data, relativeTo: nil) {
                    continuation.resume(returning: url)
                    return
                }

                continuation.resume(throwing: EngineError.invalidPayload("Could not load a file URL from Finder."))
            }
        }
    }
}
