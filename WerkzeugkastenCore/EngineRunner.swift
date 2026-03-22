import Foundation

@MainActor
public final class EngineRunner {
    private final class BundleMarker {}
    private static let moduleFileNames = [
        "__init__.py",
        "__main__.py",
        "cli.py",
        "codex_log.py",
        "core.py",
        "notion_export.py",
        "research_list.py",
        "research_table.py",
        "summarize.py",
    ]

    private let resourceURLOverride: URL?

    public init(resourceURLOverride: URL? = nil) {
        self.resourceURLOverride = resourceURLOverride
    }

    private var resourceURL: URL? {
        resourceURLOverride ?? Bundle(for: BundleMarker.self).resourceURL
    }

    public func preparedCommand(
        command: EngineCommand,
        payload: [String: Any],
        configuration: EngineConfiguration
    ) throws -> PreparedCommand {
        guard !command.requiresAPIKey || !configuration.apiKey.isEmpty else {
            throw EngineError.missingAPIKey
        }

        let interpreterURL = URL(fileURLWithPath: configuration.pythonInterpreterPath)
        guard FileManager.default.isExecutableFile(atPath: interpreterURL.path) else {
            throw EngineError.missingInterpreter(configuration.pythonInterpreterPath)
        }

        let moduleRoot = try resolvedModuleRoot()

        guard JSONSerialization.isValidJSONObject(payload) else {
            throw EngineError.invalidPayload("Invalid JSON payload.")
        }

        let stdinData = try JSONSerialization.data(withJSONObject: payload, options: [])
        var environment = ProcessInfo.processInfo.environment
        let existingPythonPath = environment["PYTHONPATH"].map { "\($0):" } ?? ""
        environment["PYTHONPATH"] = existingPythonPath + moduleRoot.path
        if command.requiresAPIKey {
            environment["OPENAI_API_KEY"] = configuration.apiKey
        } else {
            environment.removeValue(forKey: "OPENAI_API_KEY")
        }
        if configuration.jinaAPIKey.isEmpty {
            environment.removeValue(forKey: "WERKZEUGKASTEN_JINA_API_KEY")
        } else {
            environment["WERKZEUGKASTEN_JINA_API_KEY"] = configuration.jinaAPIKey
        }
        if configuration.notionToken.isEmpty {
            environment.removeValue(forKey: "WERKZEUGKASTEN_NOTION_API_TOKEN")
        } else {
            environment["WERKZEUGKASTEN_NOTION_API_TOKEN"] = configuration.notionToken
        }
        if configuration.notionParentPage.isEmpty {
            environment.removeValue(forKey: "WERKZEUGKASTEN_NOTION_PARENT_PAGE")
        } else {
            environment["WERKZEUGKASTEN_NOTION_PARENT_PAGE"] = configuration.notionParentPage
        }
        environment["WERKZEUGKASTEN_RESEARCH_MODEL"] = configuration.researchModel
        environment["WERKZEUGKASTEN_SUMMARY_MODEL"] = configuration.summaryModel

        return PreparedCommand(
            executableURL: interpreterURL,
            arguments: ["-m", "werkzeugkasten_engine", command.rawValue],
            environment: environment,
            workingDirectoryURL: moduleRoot,
            stdinData: stdinData
        )
    }

    public func run<Response: Decodable>(
        _ command: EngineCommand,
        payload: [String: Any],
        configuration: EngineConfiguration
    ) async throws -> Response {
        let prepared = try preparedCommand(command: command, payload: payload, configuration: configuration)

        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    let process = Process()
                    process.executableURL = prepared.executableURL
                    process.arguments = prepared.arguments
                    process.environment = prepared.environment
                    process.currentDirectoryURL = prepared.workingDirectoryURL

                    let stdinPipe = Pipe()
                    let stdoutPipe = Pipe()
                    let stderrPipe = Pipe()

                    process.standardInput = stdinPipe
                    process.standardOutput = stdoutPipe
                    process.standardError = stderrPipe

                    try process.run()

                    stdinPipe.fileHandleForWriting.write(prepared.stdinData)
                    stdinPipe.fileHandleForWriting.closeFile()

                    process.waitUntilExit()

                    let stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                    let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
                    let stderrText = String(data: stderrData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

                    guard process.terminationStatus == 0 else {
                        throw EngineError.processFailure(stderrText.isEmpty ? "Python command failed." : stderrText)
                    }

                    continuation.resume(returning: try Self.decode(Response.self, from: stdoutData))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    nonisolated public static func decode<Response: Decodable>(_ type: Response.Type, from data: Data) throws -> Response {
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            let raw = String(data: data, encoding: .utf8) ?? "<non-utf8>"
            throw EngineError.invalidResponse("Could not decode engine response: \(raw)")
        }
    }

    private func resolvedModuleRoot() throws -> URL {
        guard let resourceURL else {
            throw EngineError.missingResources
        }

        let packagedRoot = resourceURL.appendingPathComponent("werkzeugkasten_engine", isDirectory: true)
        if FileManager.default.fileExists(atPath: packagedRoot.appendingPathComponent("__main__.py").path) {
            return resourceURL
        }

        guard FileManager.default.fileExists(atPath: resourceURL.appendingPathComponent("__main__.py").path) else {
            throw EngineError.missingResources
        }

        return try stageFlatBundleResources(from: resourceURL)
    }

    private func stageFlatBundleResources(from resourceURL: URL) throws -> URL {
        let fileManager = FileManager.default
        let root = fileManager.temporaryDirectory
            .appendingPathComponent("werkzeugkasten-engine-bundle", isDirectory: true)
        let packageDirectory = root.appendingPathComponent("werkzeugkasten_engine", isDirectory: true)

        try fileManager.createDirectory(at: packageDirectory, withIntermediateDirectories: true)

        for name in Self.moduleFileNames {
            let sourceURL = resourceURL.appendingPathComponent(name)
            let destinationURL = packageDirectory.appendingPathComponent(name)
            guard fileManager.fileExists(atPath: sourceURL.path) else {
                throw EngineError.missingResources
            }
            if fileManager.fileExists(atPath: destinationURL.path) {
                try fileManager.removeItem(at: destinationURL)
            }
            try fileManager.copyItem(at: sourceURL, to: destinationURL)
        }

        return root
    }
}
