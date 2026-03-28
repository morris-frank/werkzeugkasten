import Foundation
import WerkzeugkastenCore

@MainActor
final class SummarizeSession: ObservableObject {
    @Published var inputText = ""
    @Published var fileURLs: [URL] = []
    @Published var isRunning = false
    @Published var status = "Paste text for an in-app summary or drop one or more files."
    @Published var summary = ""
    @Published var result: SummarizeResponse?
    @Published var errorText: String?

    private let runner = EngineRunner()

    func addFiles(_ urls: [URL]) {
        fileURLs = InputNormalizer.uniqueFileURLs(fileURLs + urls)
        status = "Loaded \(fileURLs.count) file(s)"
        errorText = nil
    }

    func clearFiles() {
        fileURLs.removeAll()
        result = nil
        if inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            status = "Paste text for an in-app summary or drop one or more files."
        }
    }

    func handleFinderHandoff(_ url: URL, settings: SettingsStore) {
        do {
            let incomingURLs = try FinderActionHandoff.parseSummarizeURL(url)
            inputText = ""
            summary = ""
            result = nil
            fileURLs = incomingURLs
            status = "Received \(incomingURLs.count) file(s) from Finder. Starting summary..."
            errorText = nil
            run(using: settings)
        } catch {
            errorText = error.localizedDescription
        }
    }

    func run(using settings: SettingsStore) {
        guard !isRunning else { return }

        Task {
            isRunning = true
            errorText = nil
            summary = ""
            result = nil
            defer { isRunning = false }

            do {
                let configuration = try settings.configuration()
                let trimmedText = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
                if !trimmedText.isEmpty {
                    let response: SummarizeResponse = try await runner.run(
                        .summarizeText,
                        payload: ["title": "Pasted text", "text": trimmedText],
                        configuration: configuration
                    )
                    summary = response.summary
                    result = response
                    status = "Summary ready to copy."
                } else {
                    let response: SummarizeResponse = try await runner.run(
                        .summarizeFiles,
                        payload: ["paths": fileURLs.map(\.path)],
                        configuration: configuration
                    )
                    summary = response.summary
                    result = response
                    status = "Processed more file(s)"
                }
            } catch {
                errorText = error.localizedDescription
            }
        }
    }
}
