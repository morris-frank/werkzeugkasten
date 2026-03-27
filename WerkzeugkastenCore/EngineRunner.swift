import Foundation

@MainActor
public final class EngineRunner {
    private final class BundleMarker {}

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
        guard configuration.mock || !command.requiresAPIKey || !configuration.apiKey.isEmpty else {
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

        let requestObject: [String: Any] = [
            "service": command.rawValue,
            "payload": payload,
            "config": [
                "api_key": configuration.apiKey,
                "jina_api_key": configuration.jinaAPIKey,
                "notion_token": configuration.notionToken,
                "notion_parent_page": configuration.notionParentPage,
                "open_meteo_api_key": configuration.openMeteoAPIKey,
                "research_model": configuration.researchModel,
                "summary_model": configuration.summaryModel,
                "lookup_model": configuration.lookupModel,
                "primary_language": configuration.primaryLanguage,
            ],
        ]
        let stdinData = try JSONSerialization.data(withJSONObject: requestObject, options: [])
        var environment = ProcessInfo.processInfo.environment
        let existingPythonPath = environment["PYTHONPATH"].map { "\($0):" } ?? ""
        environment["PYTHONPATH"] = existingPythonPath + moduleRoot.path
        if configuration.mock {
            environment["WERKZEUGKASTEN_MOCK"] = "1"
        } else {
            environment.removeValue(forKey: "WERKZEUGKASTEN_MOCK")
        }

        return PreparedCommand(
            executableURL: interpreterURL,
            arguments: ["-m", "werkzeugkasten", "run"],
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

                    let envelope = try Self.decode(EngineResponseEnvelope<Response>.self, from: stdoutData)
                    continuation.resume(returning: envelope.data)
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

        let packagedRoot = resourceURL.appendingPathComponent("src/werkzeugkasten", isDirectory: true)
        if FileManager.default.fileExists(atPath: packagedRoot.appendingPathComponent("__main__.py").path) {
            return resourceURL
        }

        let stagedRoot = try stageFlatBundleResources(from: resourceURL)
        guard FileManager.default.fileExists(
            atPath: stagedRoot.appendingPathComponent("src/werkzeugkasten/__main__.py").path
        ) else {
            throw EngineError.missingResources
        }
        return stagedRoot
    }

    private func stageFlatBundleResources(from resourceURL: URL) throws -> URL {
        let fileManager = FileManager.default
        let root = fileManager.temporaryDirectory
            .appendingPathComponent("werkzeugkasten-engine-bundle-\(UUID().uuidString)", isDirectory: true)

        let packageDirectory = root.appendingPathComponent("src/werkzeugkasten", isDirectory: true)
        try fileManager.createDirectory(at: packageDirectory, withIntermediateDirectories: true)

        guard let relativePaths = fileManager.subpaths(atPath: resourceURL.path) else {
            throw EngineError.missingResources
        }

        for relativePath in relativePaths where relativePath.hasSuffix(".py") {
            let sourceURL = resourceURL.appendingPathComponent(relativePath)
            let destinationURL = packageDirectory.appendingPathComponent(relativePath)
            try fileManager.createDirectory(
                at: destinationURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            if fileManager.fileExists(atPath: destinationURL.path) {
                try fileManager.removeItem(at: destinationURL)
            }
            try fileManager.copyItem(at: sourceURL, to: destinationURL)
        }

        guard fileManager.fileExists(atPath: packageDirectory.appendingPathComponent("__main__.py").path) else {
            throw EngineError.missingResources
        }

        return root
    }
}
