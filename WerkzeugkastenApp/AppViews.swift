import AppKit
import SwiftUI
import UniformTypeIdentifiers
import WerkzeugkastenCore

struct MenuBarContent: View {
    @Environment(\.openWindow) private var openWindow
    @EnvironmentObject private var windowCoordinator: WindowCoordinator

    private func show(_ sceneID: WindowSceneID) {
        windowCoordinator.openAndActivate(sceneID, openWindow: openWindow)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button("Research List") { show(.researchList) }
            Button("Research Table") { show(.researchTable) }
            Button("Summarize") { show(.summarize) }
            Button("Prettify Codex Log") { show(.prettifyCodexLog) }
            Divider()
            Button("Settings") { show(.settings) }
            Button("Quit") { NSApp.terminate(nil) }
        }
        .padding(12)
        .frame(width: 220)
    }
}

private struct SectionCard<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.system(size: 15, weight: .semibold))
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(.quaternary.opacity(0.3))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(.white.opacity(0.06))
        )
    }
}

private struct WindowSurface<Content: View>: View {
    let minWidth: CGFloat
    @ViewBuilder let content: Content

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(nsColor: .windowBackgroundColor),
                    Color(nsColor: .underPageBackgroundColor).opacity(0.82),
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            content
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .padding(20)
        }
        .frame(minWidth: minWidth, alignment: .topLeading)
    }
}

private struct StatusBanner: View {
    let message: String
    let tint: Color

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Circle()
                .fill(tint)
                .frame(width: 8, height: 8)
                .padding(.top, 6)
            Text(message)
                .fixedSize(horizontal: false, vertical: true)
        }
        .foregroundStyle(tint)
        .font(.callout)
    }
}

private struct SettingsFieldRow<Field: View>: View {
    let title: String
    @ViewBuilder let field: Field

    var body: some View {
        GridRow {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 148, alignment: .leading)
            field
        }
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
private func chooseFiles(allowsMultiple: Bool, allowedContentTypes: [UTType] = []) -> [URL] {
    let panel = NSOpenPanel()
    panel.canChooseFiles = true
    panel.canChooseDirectories = false
    panel.allowsMultipleSelection = allowsMultiple
    panel.resolvesAliases = true
    if !allowedContentTypes.isEmpty {
        panel.allowedContentTypes = allowedContentTypes
    }
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
        WindowSurface(minWidth: 560) {
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
                .frame(maxWidth: .infinity, alignment: .leading)
            }
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
        WindowSurface(minWidth: 600) {
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
                .frame(maxWidth: .infinity, alignment: .leading)
            }
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
        WindowSurface(minWidth: 600) {
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
                .frame(maxWidth: .infinity, alignment: .leading)
            }
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

struct PrettifyCodexLogWindow: View {
    @EnvironmentObject private var settings: SettingsStore
    private let runner = EngineRunner()

    @State private var logURL: URL?
    @State private var isRunning = false
    @State private var status = "Choose a Codex `.jsonl` session log to generate a markdown transcript."
    @State private var outputPath: String?
    @State private var errorText: String?

    var body: some View {
        WindowSurface(minWidth: 580) {
            VStack(alignment: .leading, spacing: 16) {
                SectionCard(title: "Log") {
                    FileDropArea(label: "Drop a Codex `.jsonl` session log here") { urls in
                        selectLog(urls.first)
                    }
                    HStack {
                        Button("Choose Log") {
                            let jsonlType = UTType(filenameExtension: "jsonl") ?? .json
                            selectLog(chooseFiles(allowsMultiple: false, allowedContentTypes: [jsonlType]).first)
                        }
                        if logURL != nil {
                            Button("Clear") {
                                logURL = nil
                                outputPath = nil
                            }
                        }
                    }
                    if let logURL {
                        Text(logURL.path)
                            .font(.caption.monospaced())
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
                    HStack {
                        Button("Prettify Codex Log") { run() }
                            .disabled(isRunning || logURL == nil)
                        if let outputPath {
                            Button("Open Output") { openPath(outputPath) }
                        }
                    }
                }
            }
        }
    }

    private func selectLog(_ url: URL?) {
        guard let url else { return }
        guard url.pathExtension.lowercased() == "jsonl" else {
            errorText = "Choose a `.jsonl` Codex session log."
            return
        }
        logURL = url
        outputPath = nil
        errorText = nil
        status = "Loaded \(url.lastPathComponent)"
    }

    private func run() {
        guard let logURL else { return }
        Task {
            isRunning = true
            errorText = nil
            status = "Generating transcript..."
            defer { isRunning = false }

            do {
                let response: PrettifyCodexLogResponse = try await runner.run(
                    .prettifyCodexLog,
                    payload: ["path": logURL.path],
                    configuration: try settings.configuration()
                )
                outputPath = response.outputPath
                status = "Wrote \(URL(fileURLWithPath: response.outputPath).lastPathComponent) with \(response.completedTurnCount) completed turn(s)."
            } catch {
                outputPath = nil
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
        WindowSurface(minWidth: 620) {
            VStack(alignment: .leading, spacing: 16) {
                SectionCard(title: "Shared Configuration") {
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 12) {
                        SettingsFieldRow(title: "OpenAI API Key") {
                            SecureField("sk-proj-...", text: $settings.apiKey)
                                .textFieldStyle(.roundedBorder)
                        }
                        SettingsFieldRow(title: "Research model") {
                            TextField("gpt-5.4", text: $settings.researchModel)
                                .textFieldStyle(.roundedBorder)
                        }
                        SettingsFieldRow(title: "Summary model") {
                            TextField("gpt-5.4", text: $settings.summaryModel)
                                .textFieldStyle(.roundedBorder)
                        }
                        SettingsFieldRow(title: "Python interpreter") {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    TextField("/opt/homebrew/bin/python3", text: $settings.pythonInterpreterPath)
                                        .textFieldStyle(.roundedBorder)
                                    Button("Browse") {
                                        settings.pythonInterpreterPath = chooseFiles(allowsMultiple: false).first?.path ?? settings.pythonInterpreterPath
                                    }
                                }
                                if !settings.suggestedPythonInterpreterPath.isEmpty && settings.pythonInterpreterPath != settings.suggestedPythonInterpreterPath {
                                    Button("Use detected interpreter") {
                                        settings.pythonInterpreterPath = settings.suggestedPythonInterpreterPath
                                    }
                                    .buttonStyle(.link)
                                }
                            }
                        }
                    }
                }

                SectionCard(title: "Status") {
                    if settings.interpreterIsReachable {
                        StatusBanner(message: "Interpreter found and executable.", tint: .secondary)
                    } else {
                        StatusBanner(message: "Interpreter path is not executable yet.", tint: .red)
                    }

                    if let sharedSettingsIssue = settings.sharedSettingsIssue {
                        StatusBanner(message: sharedSettingsIssue, tint: .orange)
                    }

                    if let keychainIssue = settings.keychainIssue {
                        StatusBanner(message: keychainIssue, tint: .orange)
                    }

                    if let errorText {
                        StatusBanner(message: errorText, tint: .red)
                    } else {
                        Text(statusText)
                            .foregroundStyle(.secondary)
                    }
                }

                SectionCard(title: "Finder Extension") {
                    Text("Enable “Summarize with Werkzeugkasten” in System Settings > Privacy & Security > Extensions if Finder does not show it immediately.")
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                HStack {
                    Spacer()
                    Button("Save Settings") {
                        do {
                            try settings.save()
                            statusText = "Saved."
                            errorText = nil
                        } catch {
                            errorText = error.localizedDescription
                        }
                    }
                    .keyboardShortcut(.defaultAction)
                }
            }
        }
    }
}
