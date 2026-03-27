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
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 14, weight: .semibold))
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 6)
    }
}

private struct WindowSurface<Content: View>: View {
    let minWidth: CGFloat
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        ZStack {
            Color(nsColor: .windowBackgroundColor)
                .ignoresSafeArea()

            RoundedRectangle(cornerRadius: 34, style: .continuous)
                .fill(Color.black.opacity(0.08))
                .blur(radius: 18)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)

            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            Color(red: 0.97, green: 0.97, blue: 0.95),
                            Color(red: 0.92, green: 0.92, blue: 0.88),
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .stroke(Color.white.opacity(0.82), lineWidth: 1)
                )
                .overlay(alignment: .topLeading) {
                    content
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                        .padding(.horizontal, 20)
                        .padding(.vertical, 16)
                }
                .padding(8)
        }
        .frame(minWidth: minWidth, alignment: .topLeading)
        .preferredColorScheme(.light)
    }
}

private struct PrimaryEditor: ViewModifier {
    let minHeight: CGFloat
    let maxHeight: CGFloat

    func body(content: Content) -> some View {
        content
            .font(.body.monospaced())
            .frame(minHeight: minHeight, maxHeight: maxHeight, alignment: .topLeading)
            .scrollContentBackground(.hidden)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(.white.opacity(0.8))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(.black.opacity(0.06), lineWidth: 1)
            )
    }
}

private extension View {
    func primaryEditor(minHeight: CGFloat, maxHeight: CGFloat = 260) -> some View {
        modifier(PrimaryEditor(minHeight: minHeight, maxHeight: maxHeight))
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
private func chooseSavePath(startingAt path: String, allowedContentTypes: [UTType] = [.plainText]) -> String? {
    let panel = NSSavePanel()
    panel.canCreateDirectories = true
    panel.allowedContentTypes = allowedContentTypes
    let url = URL(fileURLWithPath: path)
    panel.directoryURL = url.deletingLastPathComponent()
    panel.nameFieldStringValue = url.lastPathComponent
    return panel.runModal() == .OK ? panel.url?.path : nil
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

@MainActor
private func openURL(_ url: URL) {
    NSWorkspace.shared.open(url)
}

private func sanitizedOutputSlug(_ text: String) -> String {
    let slug = text.lowercased()
        .replacingOccurrences(of: "[^a-z0-9]+", with: "-", options: .regularExpression)
        .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
    return slug.isEmpty ? "research" : slug
}

private func suggestedResearchOutputPath(label: String) -> String {
    let formatter = DateFormatter()
    formatter.dateFormat = "yyyy-MM-dd_HH-mm"
    let fileName = "\(formatter.string(from: Date()))-\(sanitizedOutputSlug(label)).md"
    return FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Desktop", isDirectory: true)
        .appendingPathComponent(fileName)
        .path
}

private enum GeneratedColumnPolicy: String, CaseIterable, Identifiable {
    case merge
    case overwrite

    var id: String { rawValue }

    var title: String {
        switch self {
        case .merge: "Merge"
        case .overwrite: "Overwrite"
        }
    }
}

private struct CopyableTagList: View {
    let title: String
    let values: [String]
    private let columns = [GridItem(.adaptive(minimum: 140), alignment: .leading)]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Button("Copy all") {
                    copyToPasteboard(values.joined(separator: "\n"))
                }
                .disabled(values.isEmpty)
            }
            if values.isEmpty {
                Text("None")
                    .foregroundStyle(.secondary)
            } else {
                LazyVGrid(columns: columns, alignment: .leading, spacing: 8) {
                    ForEach(values, id: \.self) { value in
                        HStack(spacing: 6) {
                            Text(value)
                                .textSelection(.enabled)
                                .lineLimit(nil)
                            Button {
                                copyToPasteboard(value)
                            } label: {
                                Image(systemName: "doc.on.doc")
                            }
                            .buttonStyle(.plain)
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(Capsule(style: .continuous).fill(.tertiary.opacity(0.55)))
                    }
                }
            }
        }
    }
}

private struct OutputPathCard: View {
    let defaultPath: String
    @Binding var outputPath: String

    var body: some View {
        SectionCard(title: "Output") {
            TextField("Output Path", text: $outputPath)
                .textFieldStyle(.roundedBorder)
                .controlSize(.regular)
                .font(.body.monospaced())
            HStack {
                Button("Choose…") {
                    if let chosen = chooseSavePath(startingAt: outputPath.isEmpty ? defaultPath : outputPath) {
                        outputPath = chosen
                    }
                }
                Button("Reset") {
                    outputPath = defaultPath
                }
                Spacer()
                Text("Edit this path to override the generated markdown file name.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct ResearchRunOptionsState: Equatable {
    var includeSources: Bool
    var includeSourceRaw: Bool
    var autoTagging: Bool
    var nearestNeighbour: Bool
    var exportToNotion: Bool
    var sourcePolicy: GeneratedColumnPolicy
    var sourceRawPolicy: GeneratedColumnPolicy
    var tagPolicy: GeneratedColumnPolicy
    var nearestPolicy: GeneratedColumnPolicy
    var recordIDPolicy: GeneratedColumnPolicy

    init(
        includeSources: Bool = WerkzeugkastenConstants.defaultResearchIncludeSources,
        includeSourceRaw: Bool = WerkzeugkastenConstants.defaultResearchIncludeSourceRaw,
        autoTagging: Bool = WerkzeugkastenConstants.defaultResearchAutoTagging,
        nearestNeighbour: Bool = WerkzeugkastenConstants.defaultResearchNearestNeighbour,
        exportToNotion: Bool = WerkzeugkastenConstants.defaultResearchExportToNotion,
        sourcePolicy: GeneratedColumnPolicy = GeneratedColumnPolicy(rawValue: WerkzeugkastenConstants.defaultResearchColumnPolicyRawValue) ?? .merge,
        sourceRawPolicy: GeneratedColumnPolicy = GeneratedColumnPolicy(rawValue: WerkzeugkastenConstants.defaultResearchColumnPolicyRawValue) ?? .merge,
        tagPolicy: GeneratedColumnPolicy = GeneratedColumnPolicy(rawValue: WerkzeugkastenConstants.defaultResearchColumnPolicyRawValue) ?? .merge,
        nearestPolicy: GeneratedColumnPolicy = GeneratedColumnPolicy(rawValue: WerkzeugkastenConstants.defaultResearchColumnPolicyRawValue) ?? .merge,
        recordIDPolicy: GeneratedColumnPolicy = GeneratedColumnPolicy(rawValue: WerkzeugkastenConstants.defaultResearchColumnPolicyRawValue) ?? .merge
    ) {
        self.includeSources = includeSources
        self.includeSourceRaw = includeSourceRaw
        self.autoTagging = autoTagging
        self.nearestNeighbour = nearestNeighbour
        self.exportToNotion = exportToNotion
        self.sourcePolicy = sourcePolicy
        self.sourceRawPolicy = sourceRawPolicy
        self.tagPolicy = tagPolicy
        self.nearestPolicy = nearestPolicy
        self.recordIDPolicy = recordIDPolicy
    }

    static func load(from defaults: UserDefaults = .standard) -> ResearchRunOptionsState {
        func storedBool(_ key: String, default def: Bool) -> Bool {
            if defaults.object(forKey: key) == nil { return def }
            return defaults.bool(forKey: key)
        }
        func storedPolicy(_ key: String) -> GeneratedColumnPolicy {
            let raw = defaults.string(forKey: key) ?? WerkzeugkastenConstants.defaultResearchColumnPolicyRawValue
            return GeneratedColumnPolicy(rawValue: raw) ?? .merge
        }
        return ResearchRunOptionsState(
            includeSources: storedBool(WerkzeugkastenConstants.researchRunIncludeSourcesKey, default: WerkzeugkastenConstants.defaultResearchIncludeSources),
            includeSourceRaw: storedBool(WerkzeugkastenConstants.researchRunIncludeSourceRawKey, default: WerkzeugkastenConstants.defaultResearchIncludeSourceRaw),
            autoTagging: storedBool(WerkzeugkastenConstants.researchRunAutoTaggingKey, default: WerkzeugkastenConstants.defaultResearchAutoTagging),
            nearestNeighbour: storedBool(WerkzeugkastenConstants.researchRunNearestNeighbourKey, default: WerkzeugkastenConstants.defaultResearchNearestNeighbour),
            exportToNotion: storedBool(WerkzeugkastenConstants.researchRunExportToNotionKey, default: WerkzeugkastenConstants.defaultResearchExportToNotion),
            sourcePolicy: storedPolicy(WerkzeugkastenConstants.researchRunSourcePolicyKey),
            sourceRawPolicy: storedPolicy(WerkzeugkastenConstants.researchRunSourceRawPolicyKey),
            tagPolicy: storedPolicy(WerkzeugkastenConstants.researchRunTagPolicyKey),
            nearestPolicy: storedPolicy(WerkzeugkastenConstants.researchRunNearestPolicyKey),
            recordIDPolicy: storedPolicy(WerkzeugkastenConstants.researchRunRecordIDPolicyKey)
        )
    }

    func save(to defaults: UserDefaults = .standard) {
        defaults.set(includeSources, forKey: WerkzeugkastenConstants.researchRunIncludeSourcesKey)
        defaults.set(includeSourceRaw, forKey: WerkzeugkastenConstants.researchRunIncludeSourceRawKey)
        defaults.set(autoTagging, forKey: WerkzeugkastenConstants.researchRunAutoTaggingKey)
        defaults.set(nearestNeighbour, forKey: WerkzeugkastenConstants.researchRunNearestNeighbourKey)
        defaults.set(exportToNotion, forKey: WerkzeugkastenConstants.researchRunExportToNotionKey)
        defaults.set(sourcePolicy.rawValue, forKey: WerkzeugkastenConstants.researchRunSourcePolicyKey)
        defaults.set(sourceRawPolicy.rawValue, forKey: WerkzeugkastenConstants.researchRunSourceRawPolicyKey)
        defaults.set(tagPolicy.rawValue, forKey: WerkzeugkastenConstants.researchRunTagPolicyKey)
        defaults.set(nearestPolicy.rawValue, forKey: WerkzeugkastenConstants.researchRunNearestPolicyKey)
        defaults.set(recordIDPolicy.rawValue, forKey: WerkzeugkastenConstants.researchRunRecordIDPolicyKey)
    }

    mutating func setIncludeSources(_ value: Bool) {
        includeSources = value
        if !value {
            includeSourceRaw = false
        }
    }

    mutating func setIncludeSourceRaw(_ value: Bool) {
        includeSourceRaw = value
        if value {
            includeSources = true
        }
    }

    mutating func setAutoTagging(_ value: Bool) {
        autoTagging = value
        if !value {
            nearestNeighbour = false
        }
    }

    mutating func setNearestNeighbour(_ value: Bool) {
        nearestNeighbour = value
        if value {
            autoTagging = true
        }
    }

    var payload: [String: Any] {
        [
            "include_sources": includeSources || includeSourceRaw,
            "include_source_raw": includeSourceRaw,
            "auto_tagging": autoTagging || nearestNeighbour,
            "nearest_neighbour": nearestNeighbour,
            "export_to_notion": exportToNotion,
            "source_column_policy": sourcePolicy.rawValue,
            "source_raw_column_policy": sourceRawPolicy.rawValue,
            "tag_column_policy": tagPolicy.rawValue,
            "nearest_column_policy": nearestPolicy.rawValue,
            "record_id_column_policy": recordIDPolicy.rawValue,
        ]
    }
}

private struct ResearchOptionsCard: View {
    @Binding var options: ResearchRunOptionsState
    let collisions: Set<String>
    let objectType: String

    var body: some View {
        SectionCard(title: "Options") {
            Toggle("Include Sources", isOn: Binding(
                get: { options.includeSources },
                set: { options.setIncludeSources($0) }
            ))
            Toggle("Include Sources[RAW]", isOn: Binding(
                get: { options.includeSourceRaw },
                set: { options.setIncludeSourceRaw($0) }
            ))
            Toggle("Auto Tagging", isOn: Binding(
                get: { options.autoTagging },
                set: { options.setAutoTagging($0) }
            ))
            Toggle("Nearest Neighbour", isOn: Binding(
                get: { options.nearestNeighbour },
                set: { options.setNearestNeighbour($0) }
            ))
            Toggle("Export to Notion", isOn: $options.exportToNotion)
            collisionControl(title: "Sources", enabled: options.includeSources, selection: $options.sourcePolicy)
            collisionControl(title: "Sources[RAW]", enabled: options.includeSourceRaw, selection: $options.sourceRawPolicy)
            collisionControl(title: "Tags", enabled: options.autoTagging || options.nearestNeighbour, selection: $options.tagPolicy)
            collisionControl(title: "Closest \(objectType.capitalized)", enabled: options.nearestNeighbour, selection: $options.nearestPolicy)
            collisionControl(title: "Record ID", enabled: options.exportToNotion, selection: $options.recordIDPolicy)
            Text("`Sources[RAW]` fetches source pages through Jina and can make the output much larger. `Nearest Neighbour` uses a second pass over the generated table and depends on `Auto Tagging`.")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private func collisionControl(title: String, enabled: Bool, selection: Binding<GeneratedColumnPolicy>) -> some View {
        if enabled && collisions.contains(title) {
            HStack {
                Text("\(title) exists")
                    .foregroundStyle(.secondary)
                Picker("", selection: selection) {
                    ForEach(GeneratedColumnPolicy.allCases) { policy in
                        Text(policy.title).tag(policy)
                    }
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 220)
            }
        }
    }
}

struct ResearchListWindow: View {
    @EnvironmentObject private var settings: SettingsStore
    private let runner = EngineRunner()

    @State private var inputText = ""
    @State private var question = ""
    @State private var isRunning = false
    @State private var status = "Paste a list or drop a UTF-8 text file."
    @State private var outputPath = ""
    @State private var errorText: String?
    @State private var options = ResearchRunOptionsState.load()

    private var parsedItems: [String] {
        InputNormalizer.parseResearchItems(inputText)
    }

    private var defaultOutputPath: String {
        let label = question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "research-list" : question
        return suggestedResearchOutputPath(label: label)
    }

    private var detectedHeaders: [String] {
        let trimmed = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return ["Item"] }
        let header = trimmed.hasSuffix("?") ? trimmed : "\(trimmed)?"
        return ["Item", header]
    }

    private var collisionColumns: Set<String> {
        Set(detectedHeaders)
    }

    private var hasWrittenOutput: Bool {
        !outputPath.isEmpty && FileManager.default.fileExists(atPath: outputPath)
    }

    var body: some View {
        WindowSurface(minWidth: 560, title: "Research List") {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    SectionCard(title: "Input") {
                        TextEditor(text: $inputText)
                            .primaryEditor(minHeight: 180, maxHeight: 220)
                        FileDropArea(label: "Drop a text file here") { urls in
                            loadTextFile(urls.first)
                        }
                        Button("Choose File") {
                            loadTextFile(chooseFiles(allowsMultiple: false).first)
                        }
                    }

                    SectionCard(title: "Question") {
                        TextField("Question", text: $question)
                            .textFieldStyle(.roundedBorder)
                            .controlSize(.large)
                        Text("\(parsedItems.count) parsed item(s)")
                            .foregroundStyle(.secondary)
                        CopyableTagList(title: "Parsed Items", values: parsedItems)
                    }

                    OutputPathCard(defaultPath: defaultOutputPath, outputPath: $outputPath)

                    ResearchOptionsCard(options: $options, collisions: collisionColumns, objectType: "item")

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
                            if hasWrittenOutput {
                                Button("Open Output") { openPath(outputPath) }
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .onAppear { seedOutputPathIfNeeded(force: true) }
        .onChange(of: question) {
            seedOutputPathIfNeeded(force: false)
        }
        .onChange(of: options) { _, new in
            new.save()
        }
    }

    private func loadTextFile(_ url: URL?) {
        guard let url else { return }
        do {
            inputText = try InputNormalizer.loadTextFile(url)
            status = "Loaded \(url.lastPathComponent)"
            errorText = nil
            seedOutputPathIfNeeded(force: false)
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func seedOutputPathIfNeeded(force: Bool) {
        if force || outputPath.isEmpty {
            outputPath = defaultOutputPath
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
                    payload: [
                        "items": items,
                        "question": question,
                        "output_path": outputPath,
                    ].merging(options.payload) { _, new in new },
                    configuration: try settings.configuration()
                )
                outputPath = response.outputPath
                status = "Wrote \(URL(fileURLWithPath: response.outputPath).lastPathComponent)"
            } catch {
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
    @State private var outputPath = ""
    @State private var errorText: String?
    @State private var options = ResearchRunOptionsState.load()

    private var defaultOutputPath: String {
        let label = sourceName == "pasted-table" ? "research-table" : URL(fileURLWithPath: sourceName).deletingPathExtension().lastPathComponent
        return suggestedResearchOutputPath(label: label)
    }

    private var collisionColumns: Set<String> {
        Set(preview?.headers ?? [])
    }

    private var hasWrittenOutput: Bool {
        !outputPath.isEmpty && FileManager.default.fileExists(atPath: outputPath)
    }

    var body: some View {
        WindowSurface(minWidth: 600, title: "Research Table") {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    SectionCard(title: "Input") {
                        TextEditor(text: $inputText)
                            .primaryEditor(minHeight: 180, maxHeight: 240)
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
                            CopyableTagList(title: "Question Columns", values: preview.questionColumns)
                            CopyableTagList(title: "Attribute Columns", values: preview.attributeColumns)
                        }
                    }

                    OutputPathCard(defaultPath: defaultOutputPath, outputPath: $outputPath)

                    ResearchOptionsCard(
                        options: $options,
                        collisions: collisionColumns,
                        objectType: preview?.objectType ?? "object"
                    )

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
                            if hasWrittenOutput {
                                Button("Open Output") { openPath(outputPath) }
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .onAppear { seedOutputPathIfNeeded(force: true) }
        .onChange(of: options) { _, new in
            new.save()
        }
    }

    private func loadTextFile(_ url: URL?) {
        guard let url else { return }
        do {
            inputText = try InputNormalizer.loadTextFile(url)
            sourceName = url.lastPathComponent
            status = "Loaded \(url.lastPathComponent)"
            errorText = nil
            outputPath = defaultOutputPath
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
                seedOutputPathIfNeeded(force: false)
            } catch {
                preview = nil
                errorText = error.localizedDescription
            }
        }
    }

    private func seedOutputPathIfNeeded(force: Bool) {
        if force || outputPath.isEmpty {
            outputPath = defaultOutputPath
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
                    payload: [
                        "raw_table_text": inputText,
                        "source_name": sourceName,
                        "output_path": outputPath,
                    ].merging(options.payload) { _, new in new },
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
                errorText = error.localizedDescription
            }
        }
    }
}

struct SummarizeWindow: View {
    @EnvironmentObject private var settings: SettingsStore
    @EnvironmentObject private var session: SummarizeSession

    var body: some View {
        WindowSurface(minWidth: 600, title: "Summarize") {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    SectionCard(title: "Input") {
                        TextEditor(text: $session.inputText)
                            .primaryEditor(minHeight: 180, maxHeight: 220)
                        FileDropArea(label: "Drop one or more files here") { urls in
                            session.addFiles(urls)
                        }
                        HStack {
                            Button("Choose File(s)") {
                                session.addFiles(chooseFiles(allowsMultiple: true))
                            }
                            if !session.fileURLs.isEmpty {
                                Button("Clear Files") {
                                    session.clearFiles()
                                }
                            }
                        }
                        if !session.fileURLs.isEmpty {
                            ForEach(session.fileURLs, id: \.path) { url in
                                Text(url.path)
                                    .font(.caption.monospaced())
                            }
                        }
                    }

                    SectionCard(title: "Run") {
                        if session.isRunning {
                            ProgressView()
                        }
                        if let errorText = session.errorText {
                            Text(errorText)
                                .foregroundStyle(.red)
                        } else {
                            Text(session.status)
                                .foregroundStyle(.secondary)
                        }
                        Button("Summarize") { session.run(using: settings) }
                            .disabled(session.isRunning || (session.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && session.fileURLs.isEmpty))
                    }

                    if !session.summaryMarkdown.isEmpty {
                        SectionCard(title: "Summary") {
                            TextEditor(text: .constant(session.summaryMarkdown))
                                .font(.body.monospaced())
                                .frame(minHeight: 200)
                            Button("Copy Summary") {
                                copyToPasteboard(session.summaryMarkdown)
                            }
                        }
                    }

                    if let fileResult = session.fileResult, !fileResult.files.isEmpty || !fileResult.failures.isEmpty {
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
        .onOpenURL { url in
            session.handleFinderHandoff(url, settings: settings)
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
        WindowSurface(minWidth: 580, title: "Prettify Codex Log") {
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
                        Button("Open Codex Logs") {
                            openURL(defaultCodexLogLocation)
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

    private var defaultCodexLogLocation: URL {
        let logs = WerkzeugkastenConstants.defaultCodexLogsDirectoryURL
        let codex = WerkzeugkastenConstants.defaultCodexDirectoryURL
        let fileManager = FileManager.default
        if fileManager.fileExists(atPath: logs.path) {
            return logs
        }
        if fileManager.fileExists(atPath: codex.path) {
            return codex
        }
        return fileManager.homeDirectoryForCurrentUser
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
    @State private var statusText = "Saved settings are used by Werkzeugkasten when it runs tasks."
    @State private var errorText: String?

    var body: some View {
        WindowSurface(minWidth: 620, title: "Settings") {
            VStack(alignment: .leading, spacing: 16) {
                SectionCard(title: "Shared Configuration") {
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 12) {
                        SettingsFieldRow(title: "OpenAI API Key") {
                            SecureField("sk-proj-...", text: $settings.apiKey)
                                .textFieldStyle(.roundedBorder)
                                .controlSize(.large)
                        }
                        SettingsFieldRow(title: "Jina API Key") {
                            SecureField("jina_...", text: $settings.jinaAPIKey)
                                .textFieldStyle(.roundedBorder)
                                .controlSize(.large)
                        }
                        SettingsFieldRow(title: "Notion API Token") {
                            SecureField("secret_...", text: $settings.notionToken)
                                .textFieldStyle(.roundedBorder)
                                .controlSize(.large)
                        }
                        SettingsFieldRow(title: "Open-Meteo API Key") {
                            SecureField("openmeteo_...", text: $settings.openMeteoAPIKey)
                                .textFieldStyle(.roundedBorder)
                                .controlSize(.large)
                        }
                        SettingsFieldRow(title: "Notion Parent Page") {
                            TextField("Page URL or UUID", text: $settings.notionParentPage)
                                .textFieldStyle(.roundedBorder)
                                .controlSize(.large)
                        }
                        SettingsFieldRow(title: "Research model") {
                            TextField("gpt-5.4", text: $settings.researchModel)
                                .textFieldStyle(.roundedBorder)
                                .controlSize(.large)
                        }
                        SettingsFieldRow(title: "Summary model") {
                            TextField("gpt-5.4", text: $settings.summaryModel)
                                .textFieldStyle(.roundedBorder)
                                .controlSize(.large)
                        }
                        SettingsFieldRow(title: "Lookup model") {
                            TextField("gpt-5.4", text: $settings.lookupModel)
                                .textFieldStyle(.roundedBorder)
                                .controlSize(.large)
                        }
                        SettingsFieldRow(title: "Primary language") {
                            VStack(alignment: .leading, spacing: 6) {
                                TextField("German", text: $settings.primaryLanguage)
                                    .textFieldStyle(.roundedBorder)
                                    .controlSize(.large)
                                Text("The summary matches the source when it is in this language; otherwise it uses English.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        SettingsFieldRow(title: "Python interpreter") {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    TextField("/opt/homebrew/bin/python3", text: $settings.pythonInterpreterPath)
                                        .textFieldStyle(.roundedBorder)
                                        .controlSize(.large)
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
                    Text("Enable “Summarize with Werkzeugkasten” in System Settings > Privacy & Security > Extensions if Finder does not show it immediately. Finder launches the app, and the app performs the summary with your saved settings.")
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
