import Foundation
import WerkzeugkastenCore

@MainActor
final class SummarizeSession: ObservableObject {
    @Published var inputText = ""
    @Published var fileURLs: [URL] = []
    @Published var isRunning = false
    @Published var status = "Paste text for an in-app summary or drop one or more files."
    @Published var summaryMarkdown = ""
    @Published var fileResult: SummarizeFilesResponse?
    @Published var errorText: String?

    private let runner = EngineRunner()

    func addFiles(_ urls: [URL]) {
        fileURLs = InputNormalizer.uniqueFileURLs(fileURLs + urls)
        status = "Loaded \(fileURLs.count) file(s)"
        errorText = nil
    }

    func clearFiles() {
        fileURLs.removeAll()
        fileResult = nil
        if inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            status = "Paste text for an in-app summary or drop one or more files."
        }
    }

    func handleFinderHandoff(_ url: URL, settings: SettingsStore) {
        do {
            let incomingURLs = try FinderActionHandoff.parseSummarizeURL(url)
            inputText = ""
            summaryMarkdown = ""
            fileResult = nil
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
            summaryMarkdown = ""
            fileResult = nil
            defer { isRunning = false }

            do {
                let configuration = try settings.configuration()
                let trimmedText = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
                if !trimmedText.isEmpty {
                    let response: SummarizeTextResponse = try await runner.run(
                        .summarizeText,
                        payload: ["title": "Pasted text", "text": trimmedText],
                        configuration: configuration
                    )
                    summaryMarkdown = response.summaryMarkdown
                    status = "Summary ready to copy."
                } else {
                    let response: SummarizeFilesResponse = try await runner.run(
                        .summarizeFiles,
                        payload: ["paths": fileURLs.map(\.path)],
                        configuration: configuration
                    )
                    fileResult = response
                    status = "Processed \(response.files.count) file(s)"
                    if !response.failures.isEmpty {
                        errorText = response.failures.map { "\($0.inputPath): \($0.error)" }.joined(separator: "\n")
                    }
                }
            } catch {
                errorText = error.localizedDescription
            }
        }
    }
}
