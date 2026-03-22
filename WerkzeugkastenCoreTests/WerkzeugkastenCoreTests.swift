import XCTest
@testable import WerkzeugkastenCore

final class WerkzeugkastenCoreTests: XCTestCase {
    func testParseResearchItems() {
        XCTAssertEqual(
            InputNormalizer.parseResearchItems("- Apple\n2. Banana\n* Cherry"),
            ["Apple", "Banana", "Cherry"]
        )
    }

    func testUniqueFileURLs() {
        let first = URL(fileURLWithPath: "/tmp/example.txt")
        XCTAssertEqual(InputNormalizer.uniqueFileURLs([first, first]).count, 1)
    }

    func testPreparedCommandInjectsEnvironment() throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        let packageDirectory = temp.appendingPathComponent("werkzeugkasten_engine")
        try FileManager.default.createDirectory(at: packageDirectory, withIntermediateDirectories: true)
        try "print('ok')".write(to: packageDirectory.appendingPathComponent("__main__.py"), atomically: true, encoding: .utf8)

        let configuration = EngineConfiguration(
            apiKey: "key",
            researchModel: "research-model",
            summaryModel: "summary-model",
            pythonInterpreterPath: "/bin/echo"
        )

        let prepared = try EngineRunner(resourceURLOverride: temp).preparedCommand(
            command: .summarizeText,
            payload: ["title": "Note", "text": "Hello"],
            configuration: configuration
        )

        XCTAssertEqual(prepared.arguments, ["-m", "werkzeugkasten_engine", "summarize-text"])
        XCTAssertEqual(prepared.environment["OPENAI_API_KEY"], "key")
        XCTAssertEqual(prepared.environment["WERKZEUGKASTEN_RESEARCH_MODEL"], "research-model")
        XCTAssertEqual(prepared.environment["WERKZEUGKASTEN_SUMMARY_MODEL"], "summary-model")
        XCTAssertEqual(prepared.workingDirectoryURL, temp)
    }

    func testPreparedCommandSkipsAPIKeyForPrettifyCodexLog() throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        let packageDirectory = temp.appendingPathComponent("werkzeugkasten_engine")
        try FileManager.default.createDirectory(at: packageDirectory, withIntermediateDirectories: true)
        try "print('ok')".write(to: packageDirectory.appendingPathComponent("__main__.py"), atomically: true, encoding: .utf8)

        let configuration = EngineConfiguration(
            apiKey: "",
            researchModel: "research-model",
            summaryModel: "summary-model",
            pythonInterpreterPath: "/bin/echo"
        )

        let prepared = try EngineRunner(resourceURLOverride: temp).preparedCommand(
            command: .prettifyCodexLog,
            payload: ["path": "/tmp/session.jsonl"],
            configuration: configuration
        )

        XCTAssertEqual(prepared.arguments, ["-m", "werkzeugkasten_engine", "prettify-codex-log"])
        XCTAssertNil(prepared.environment["OPENAI_API_KEY"])
    }

    func testDecodeResponse() throws {
        let data = Data(#"{"summary_markdown":"Summary\nOk"}"#.utf8)
        let decoded = try EngineRunner.decode(SummarizeTextResponse.self, from: data)
        XCTAssertEqual(decoded.summaryMarkdown, "Summary\nOk")
    }

    func testPreparedCommandStagesFlatBundleResources() throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)

        for name in ["__init__.py", "__main__.py", "cli.py", "codex_log.py", "core.py", "research_list.py", "research_table.py", "summarize.py"] {
            try "print('ok')".write(to: temp.appendingPathComponent(name), atomically: true, encoding: .utf8)
        }

        let configuration = EngineConfiguration(
            apiKey: "key",
            researchModel: "research-model",
            summaryModel: "summary-model",
            pythonInterpreterPath: "/bin/echo"
        )

        let prepared = try EngineRunner(resourceURLOverride: temp).preparedCommand(
            command: .summarizeText,
            payload: ["title": "Note", "text": "Hello"],
            configuration: configuration
        )

        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: prepared.workingDirectoryURL!
                    .appendingPathComponent("werkzeugkasten_engine/__main__.py")
                    .path
            )
        )
    }

    @MainActor
    func testSettingsStorePersistsValues() throws {
        let suiteName = "tests.werkzeugkasten.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        let service = "tests.werkzeugkasten.service.\(UUID().uuidString)"
        let account = "OPENAI_API_KEY"

        try? KeychainStore.delete(service: service, account: account)

        let store = SettingsStore(
            defaults: defaults,
            keychainService: service,
            keychainAccount: account,
            keychainAccessGroup: nil,
            requireSharedCapabilities: false
        )
        store.apiKey = "secret"
        store.researchModel = "research"
        store.summaryModel = "summary"
        store.pythonInterpreterPath = "/bin/echo"
        try store.save()

        let reloaded = SettingsStore(
            defaults: defaults,
            keychainService: service,
            keychainAccount: account,
            keychainAccessGroup: nil,
            requireSharedCapabilities: false
        )

        XCTAssertEqual(reloaded.apiKey, "secret")
        XCTAssertEqual(reloaded.researchModel, "research")
        XCTAssertEqual(reloaded.summaryModel, "summary")
        XCTAssertEqual(reloaded.pythonInterpreterPath, "/bin/echo")

        try? KeychainStore.delete(service: service, account: account)
        defaults.removePersistentDomain(forName: suiteName)
    }

    func testEngineCommandRequirements() {
        XCTAssertFalse(EngineCommand.prettifyCodexLog.requiresAPIKey)
        XCTAssertTrue(EngineCommand.summarizeText.requiresAPIKey)
    }
}
