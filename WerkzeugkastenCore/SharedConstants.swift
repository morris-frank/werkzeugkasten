import Foundation

public enum WerkzeugkastenConstants {
    public static let appBundleIdentifier = "com.mauricefrank.werkzeugkasten"
    public static let actionExtensionBundleIdentifier = "com.mauricefrank.werkzeugkasten.action"
    public static let keychainService = appBundleIdentifier
    public static let openAIKeychainAccount = "openai_api_key"
    public static let jinaKeychainAccount = "jina_api_key"
    public static let notionKeychainAccount = "notion_api_token"
    public static let openMeteoKeychainAccount = "open_meteo_key"
    public static let handoffURLScheme = "werkzeugkasten"
    public static var defaultPythonInterpreterPath: String {
        resolvedPythonInterpreterPath() ?? ""
    }
    public static let defaultResearchModel = "gpt-5.4"
    public static let defaultSummaryModel = "gpt-5.4"
    public static let defaultLookupModel = "gpt-5.4"
    public static let defaultPrimaryLanguage = "German"

    // Research List / Research Table run options — defaults and UserDefaults keys (persist across launches).
    public static let defaultResearchIncludeSources = false
    public static let defaultResearchIncludeSourceRaw = false
    public static let defaultResearchAutoTagging = false
    public static let defaultResearchNearestNeighbour = false
    public static let defaultResearchExportToNotion = false
    /// Raw value for `GeneratedColumnPolicy`-style merge/overwrite (engine + UI).
    public static let defaultResearchColumnPolicyRawValue = "merge"

    public static let researchRunIncludeSourcesKey = "researchRunIncludeSources"
    public static let researchRunIncludeSourceRawKey = "researchRunIncludeSourceRaw"
    public static let researchRunAutoTaggingKey = "researchRunAutoTagging"
    public static let researchRunNearestNeighbourKey = "researchRunNearestNeighbour"
    public static let researchRunExportToNotionKey = "researchRunExportToNotion"
    public static let researchRunSourcePolicyKey = "researchRunSourcePolicy"
    public static let researchRunSourceRawPolicyKey = "researchRunSourceRawPolicy"
    public static let researchRunTagPolicyKey = "researchRunTagPolicy"
    public static let researchRunNearestPolicyKey = "researchRunNearestPolicy"
    public static let researchRunRecordIDPolicyKey = "researchRunRecordIDPolicy"
    public static var defaultCodexDirectoryURL: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex", isDirectory: true)
    }
    public static var defaultCodexLogsDirectoryURL: URL {
        defaultCodexDirectoryURL.appendingPathComponent("archived_sessions", isDirectory: true)
    }

    public static func resolvedPythonInterpreterPath() -> String? {
        for candidate in pythonInterpreterCandidates() {
            if let resolved = resolveExecutablePath(candidate) {
                return resolved
            }
        }
        return nil
    }

    private static func pythonInterpreterCandidates() -> [String] {
        let environment = ProcessInfo.processInfo.environment
        return [
            environment["WERKZEUGKASTEN_PYTHON"],
            environment["PYTHON"],
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
            "python3",
            "python",
        ]
        .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
    }

    private static func resolveExecutablePath(_ candidate: String) -> String? {
        let fileManager = FileManager.default
        if candidate.hasPrefix("/") {
            return fileManager.isExecutableFile(atPath: candidate) ? candidate : nil
        }

        for directory in ProcessInfo.processInfo.environment["PATH"]?.split(separator: ":") ?? [] {
            let resolved = String(directory) + "/" + candidate
            if fileManager.isExecutableFile(atPath: resolved) {
                return resolved
            }
        }
        return nil
    }
}
