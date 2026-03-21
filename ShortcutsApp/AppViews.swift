import AppKit
import SwiftUI
import ShortcutsCore

struct MenuBarContent: View {
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button("Research List") { openWindow(id: "research-list") }
            Button("Research Table") { openWindow(id: "research-table") }
            Button("Summarize") { openWindow(id: "summarize") }
            Divider()
            Button("Settings") { openWindow(id: "settings") }
            Button("Quit") { NSApp.terminate(nil) }
        }
        .padding(12)
        .frame(width: 200)
    }
}

private struct SectionCard<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

private struct FileDropArea: View {
    let label: String
    var onDropURLs: ([URL]) -> Void

    var body: some View {
        RoundedRectangle(cornerRadius: 12, style: .continuous)
            .strokeBorder(style: StrokeStyle(lineWidth: 1, dash: [6]))
            .foregroundStyle(.secondary)
            .frame(minHeight: 84)
            .overlay(
                Text(label)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding()
            )
            .dropDestination(for: URL.self) { urls, _ in
                onDropURLs(urls)
                return true
            }
    }
}

@MainActor
private func chooseFiles(allowsMultiple: Bool) -> [URL] {
    let panel = NSOpenPanel()
    panel.canChooseFiles = true
    panel.canChooseDirectories = false
    panel.allowsMultipleSelection = allowsMultiple
    panel.resolvesAliases = true
    return panel.runModal() == .OK ? panel.urls : []
}

@MainActor
private func copyToPasteboard(_ text: String) {
    let pasteboard = NSPasteboard.general
    pasteboard.clearContents()
    pasteboard.setString(text, forType: .string)
}

@MainActor
private func openPath(_ path: String) {
    NSWorkspace.shared.open(URL(fileURLWithPath: path))
}

struct ResearchListWindow: View {
    @EnvironmentObject private var settings: SettingsStore
    private let runner = EngineRunner()

    @State private var inputText = ""
    @State private var question = ""
    @State private var isRunning = false
    @State private var status = "Paste a list or drop a UTF-8 text file."
    @State private var outputPath: String?
    @State private var errorText: String?

    private var parsedItems: [String] {
        InputNormalizer.parseResearchItems(inputText)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                SectionCard(title: "Input") {
                    TextEditor(text: $inputText)
                        .font(.body.monospaced())
                        .frame(minHeight: 180)
                    FileDropArea(label: "Drop a text file here") { urls in
                        loadTextFile(urls.first)
                    }
                    Button("Choose File") {
                        loadTextFile(chooseFiles(allowsMultiple: false).first)
                    }
                }

                SectionCard(title: "Question") {
                    TextField("Question", text: $question)
                    Text("\(parsedItems.count) parsed item(s)")
                        .foregroundStyle(.secondary)
                }

                SectionCard(title: "Run") {
                    if isRunning {
                        ProgressView()
                    }
                    if let errorText {
                        Text(errorText)
                            .foregroundStyle(.red)
                    } else {
                        Text(status)
                            .foregroundStyle(.secondary)
                    }
                    HStack {
                        Button("Run Research") { run() }
                            .disabled(isRunning || parsedItems.isEmpty || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        if let outputPath {
                            Button("Open Output") { openPath(outputPath) }
                        }
                    }
                }
            }
            .padding(16)
        }
    }

    private func loadTextFile(_ url: URL?) {
        guard let url else { return }
        do {
            inputText = try InputNormalizer.loadTextFile(url)
            status = "Loaded \(url.lastPathComponent)"
            errorText = nil
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func run() {
        let items = parsedItems
        Task {
            isRunning = true
            errorText = nil
            status = "Running research for \(items.count) item(s)..."
            defer { isRunning = false }
            do {
                let response: ResearchListResponse = try await runner.run(
                    .researchList,
                    payload: ["items": items, "question": question],
                    configuration: try settings.configuration()
                )
                outputPath = response.outputPath
                status = "Wrote \(URL(fileURLWithPath: response.outputPath).lastPathComponent)"
            } catch {
                outputPath = nil
                errorText = error.localizedDescription
            }
        }
    }
}

struct ResearchTableWindow: View {
    @EnvironmentObject private var settings: SettingsStore
    private let runner = EngineRunner()

    @State private var inputText = ""
    @State private var sourceName = "pasted-table"
    @State private var preview: TablePreview?
    @State private var isRunning = false
    @State private var isInspecting = false
    @State private var status = "Paste a CSV/Markdown table or drop a file."
    @State private var outputPath: String?
    @State private var errorText: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                SectionCard(title: "Input") {
                    TextEditor(text: $inputText)
                        .font(.body.monospaced())
                        .frame(minHeight: 200)
                    FileDropArea(label: "Drop a CSV or Markdown file here") { urls in
                        loadTextFile(urls.first)
                    }
                    HStack {
                        Button("Choose File") {
                            loadTextFile(chooseFiles(allowsMultiple: false).first)
                        }
                        Button("Detect Columns") {
                            inspectInput()
                        }
                        .disabled(isInspecting || inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }

                if let preview {
                    SectionCard(title: "Detected Structure") {
                        Text("Format: \(preview.detectedFormat)")
                        Text("Rows: \(preview.rowCount)")
                        Text("Key column: \(preview.keyHeader)")
                        Text("Question columns: \(preview.questionColumns.joined(separator: ", ").isEmpty ? "none" : preview.questionColumns.joined(separator: ", "))")
                        Text("Attribute columns: \(preview.attributeColumns.joined(separator: ", ").isEmpty ? "none" : preview.attributeColumns.joined(separator: ", "))")
                    }
                }

                SectionCard(title: "Run") {
                    if isRunning || isInspecting {
                        ProgressView()
                    }
                    if let errorText {
                        Text(errorText)
                            .foregroundStyle(.red)
                    } else {
                        Text(status)
                            .foregroundStyle(.secondary)
                    }
                    HStack {
                        Button("Run Table Research") { run() }
                            .disabled(isRunning || inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        if let outputPath {
                            Button("Open Output") { openPath(outputPath) }
                        }
                    }
                }
            }
            .padding(16)
        }
    }

    private func loadTextFile(_ url: URL?) {
        guard let url else { return }
        do {
            inputText = try InputNormalizer.loadTextFile(url)
            sourceName = url.lastPathComponent
            status = "Loaded \(url.lastPathComponent)"
            errorText = nil
            inspectInput()
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func inspectInput() {
        Task {
            isInspecting = true
            errorText = nil
            defer { isInspecting = false }
            do {
                preview = try await runner.run(
                    .inspectTable,
                    payload: ["raw_table_text": inputText, "source_name": sourceName],
                    configuration: try settings.configuration()
                )
                status = "Detected \(preview?.rowCount ?? 0) row(s)"
            } catch {
                preview = nil
                errorText = error.localizedDescription
            }
        }
    }

    private func run() {
        Task {
            isRunning = true
            errorText = nil
            status = "Researching table rows..."
            defer { isRunning = false }
            do {
                let response: ResearchTableResponse = try await runner.run(
                    .researchTable,
                    payload: ["raw_table_text": inputText, "source_name": sourceName],
                    configuration: try settings.configuration()
                )
                outputPath = response.outputPath
                status = "Wrote \(URL(fileURLWithPath: response.outputPath).lastPathComponent)"
                preview = TablePreview(
                    sourceName: sourceName,
                    detectedFormat: response.detectedFormat,
                    headers: response.headers,
                    keyHeader: response.headers.first ?? "",
                    rowCount: response.rowCount,
                    questionColumns: response.questionColumns,
                    attributeColumns: response.attributeColumns,
                    exampleKey: preview?.exampleKey ?? "",
                    objectType: preview?.objectType ?? ""
                )
            } catch {
                outputPath = nil
                errorText = error.localizedDescription
            }
        }
    }
}

struct SummarizeWindow: View {
    @EnvironmentObject private var settings: SettingsStore
    private let runner = EngineRunner()

    @State private var inputText = ""
    @State private var fileURLs: [URL] = []
    @State private var isRunning = false
    @State private var status = "Paste text for an in-app summary or drop one or more files."
    @State private var summaryMarkdown = ""
    @State private var fileResult: SummarizeFilesResponse?
    @State private var errorText: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                SectionCard(title: "Input") {
                    TextEditor(text: $inputText)
                        .font(.body.monospaced())
                        .frame(minHeight: 180)
                    FileDropArea(label: "Drop one or more files here") { urls in
                        fileURLs = InputNormalizer.uniqueFileURLs(fileURLs + urls)
                        status = "Loaded \(fileURLs.count) file(s)"
                        errorText = nil
                    }
                    HStack {
                        Button("Choose File(s)") {
                            fileURLs = InputNormalizer.uniqueFileURLs(fileURLs + chooseFiles(allowsMultiple: true))
                            status = "Loaded \(fileURLs.count) file(s)"
                        }
                        if !fileURLs.isEmpty {
                            Button("Clear Files") {
                                fileURLs.removeAll()
                            }
                        }
                    }
                    if !fileURLs.isEmpty {
                        ForEach(fileURLs, id: \.path) { url in
                            Text(url.path)
                                .font(.caption.monospaced())
                        }
                    }
                }

                SectionCard(title: "Run") {
                    if isRunning {
                        ProgressView()
                    }
                    if let errorText {
                        Text(errorText)
                            .foregroundStyle(.red)
                    } else {
                        Text(status)
                            .foregroundStyle(.secondary)
                    }
                    Button("Summarize") { run() }
                        .disabled(isRunning || (inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && fileURLs.isEmpty))
                }

                if !summaryMarkdown.isEmpty {
                    SectionCard(title: "Summary") {
                        TextEditor(text: .constant(summaryMarkdown))
                            .font(.body.monospaced())
                            .frame(minHeight: 200)
                        Button("Copy Summary") {
                            copyToPasteboard(summaryMarkdown)
                        }
                    }
                }

                if let fileResult, !fileResult.files.isEmpty || !fileResult.failures.isEmpty {
                    SectionCard(title: "File Results") {
                        ForEach(fileResult.files) { file in
                            HStack {
                                Text(URL(fileURLWithPath: file.summaryPath).lastPathComponent)
                                Spacer()
                                Button("Open") { openPath(file.summaryPath) }
                            }
                        }
                        ForEach(fileResult.failures) { failure in
                            Text("\(failure.inputPath): \(failure.error)")
                                .foregroundStyle(.red)
                        }
                    }
                }
            }
            .padding(16)
        }
    }

    private func run() {
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

struct SettingsWindow: View {
    @EnvironmentObject private var settings: SettingsStore
    @State private var statusText = "Saved settings are shared with the Finder action."
    @State private var errorText: String?

    var body: some View {
        Form {
            TextField("OpenAI API Key", text: $settings.apiKey)
            TextField("Research model", text: $settings.researchModel)
            TextField("Summary model", text: $settings.summaryModel)
            TextField("Python interpreter", text: $settings.pythonInterpreterPath)

            if settings.interpreterIsReachable {
                Text("Interpreter found.")
                    .foregroundStyle(.secondary)
            } else {
                Text("Interpreter path is not executable yet.")
                    .foregroundStyle(.red)
            }

            Text("Enable “Summarize with Shortcuts” in System Settings > Privacy & Security > Extensions if Finder does not show it immediately.")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if let errorText {
                Text(errorText)
                    .foregroundStyle(.red)
            } else {
                Text(statusText)
                    .foregroundStyle(.secondary)
            }

            Button("Save Settings") {
                do {
                    try settings.save()
                    statusText = "Saved."
                    errorText = nil
                } catch {
                    errorText = error.localizedDescription
                }
            }
        }
        .padding(16)
    }
}
