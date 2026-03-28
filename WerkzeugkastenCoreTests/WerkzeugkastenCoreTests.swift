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

    func testFinderActionHandoffRoundTripsFileURLs() throws {
        let urls = [
            URL(fileURLWithPath: "/tmp/one.txt"),
            URL(fileURLWithPath: "/tmp/two.txt"),
        ]

        let handoffURL = try FinderActionHandoff.makeSummarizeURL(fileURLs: urls)
        let decodedURLs = try FinderActionHandoff.parseSummarizeURL(handoffURL)

        XCTAssertEqual(decodedURLs, urls)
    }

    @MainActor
    func testPreparedCommandInjectsEnvironment() throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        let packageDirectory = temp.appendingPathComponent("src/werkzeugkasten")
        try FileManager.default.createDirectory(at: packageDirectory, withIntermediateDirectories: true)
        try "print('ok')".write(to: packageDirectory.appendingPathComponent("__main__.py"), atomically: true, encoding: .utf8)

        let configuration = EngineConfiguration(
            openAIKey: "openai-key",
            jinaAPIKey: "jina-key",
            notionApiToken: "notion-api-token",
            notionParentPage: "parent-page",
            openMeteoKey: "openmeteo-key",
            researchModel: "research-model",
            summaryModel: "summary-model",
            lookupModel: "lookup-model",
            primaryLanguage: "French",
            mock: false,
            pythonInterpreterPath: "/bin/echo"
        )

        let prepared = try EngineRunner(resourceURLOverride: temp).preparedCommand(
            command: .summarizeText,
            payload: ["title": "Note", "text": "Hello"],
            configuration: configuration
        )

        XCTAssertEqual(prepared.arguments, ["-m", "werkzeugkasten", "run"])
        let request = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: prepared.stdinData) as? [String: Any]
        )
        XCTAssertEqual(request["service"] as? String, "summarize-text")
        let config = try XCTUnwrap(request["config"] as? [String: String])
        XCTAssertEqual(config["openai_key"], "openai-key")
        XCTAssertEqual(config["jina_api_key"], "jina-key")
        XCTAssertEqual(config["notion_api_token"], "notion-api-token")
        XCTAssertEqual(config["notion_parent_page"], "parent-page")
        XCTAssertEqual(config["open_meteo_key"], "openmeteo-key")
        XCTAssertEqual(config["research_model"], "research-model")
        XCTAssertEqual(config["summary_model"], "summary-model")
        XCTAssertEqual(config["lookup_model"], "lookup-model")
        XCTAssertEqual(config["primary_language"], "French")
        XCTAssertEqual(prepared.workingDirectoryURL, temp)
    }

    @MainActor
    func testPreparedCommandSkipsAPIKeyForPrettifyCodexLog() throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        let packageDirectory = temp.appendingPathComponent("src/werkzeugkasten")
        try FileManager.default.createDirectory(at: packageDirectory, withIntermediateDirectories: true)
        try "print('ok')".write(to: packageDirectory.appendingPathComponent("__main__.py"), atomically: true, encoding: .utf8)

        let configuration = EngineConfiguration(
            openAIKey: "",
            jinaAPIKey: "",
            notionApiToken: "",
            notionParentPage: "",
            openMeteoKey: "",
            researchModel: "research-model",
            summaryModel: "summary-model",
            lookupModel: "lookup-model",
            primaryLanguage: "French",
            mock: false,
            pythonInterpreterPath: "/bin/echo"
        )

        let prepared = try EngineRunner(resourceURLOverride: temp).preparedCommand(
            command: .prettifyCodexLog,
            payload: ["path": "/tmp/session.jsonl"],
            configuration: configuration
        )

        XCTAssertEqual(prepared.arguments, ["-m", "werkzeugkasten", "run"])
        let request = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: prepared.stdinData) as? [String: Any]
        )
        XCTAssertEqual(request["service"] as? String, "prettify-codex-log")
        let config = try XCTUnwrap(request["config"] as? [String: String])
        XCTAssertEqual(config["api_key"], "")
    }

    func testDecodeResponse() throws {
        let data = Data(#"{"data":{"summary":"Summary\nOk","content":"Content","token_count":100,"input_tokens":50,"output_tokens":50,"sources":null}}"#.utf8)
        let decoded = try EngineRunner.decode(EngineResponseEnvelope<SummarizeResponse>.self, from: data)
        XCTAssertEqual(decoded.data.summary, "Summary\nOk")
        XCTAssertEqual(decoded.data.content, "Content")
        XCTAssertEqual(decoded.data.tokenCount, 100)
        XCTAssertEqual(decoded.data.inputTokens, 50)
        XCTAssertEqual(decoded.data.outputTokens, 50)
        XCTAssertEqual(decoded.data.sources, nil)
    }

    @MainActor
    func testPreparedCommandStagesFlatBundleResources() throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)

        try FileManager.default.createDirectory(at: temp.appendingPathComponent("service"), withIntermediateDirectories: true)
        try "print('ok')".write(to: temp.appendingPathComponent("__main__.py"), atomically: true, encoding: .utf8)
        try "print('ok')".write(to: temp.appendingPathComponent("service/helper.py"), atomically: true, encoding: .utf8)

        let configuration = EngineConfiguration(
            openAIKey: "openai-key",
            jinaAPIKey: "",
            notionApiToken: "",
            notionParentPage: "",
            openMeteoKey: "",
            researchModel: "research-model",
            summaryModel: "summary-model",
            lookupModel: "lookup-model",
            primaryLanguage: "French",
            mock: false,
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
                    .appendingPathComponent("src/werkzeugkasten/__main__.py")
                    .path
            )
        )
        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: prepared.workingDirectoryURL!
                    .appendingPathComponent("src/werkzeugkasten/service/helper.py")
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
        let openAIAccount = "openai_api_key"
        let jinaAccount = "jina_api_key"
        let notionAccount = "notion_api_token"
        let openMeteoAccount = "open_meteo_key"

        try? KeychainStore.delete(service: service, account: openAIAccount)
        try? KeychainStore.delete(service: service, account: jinaAccount)
        try? KeychainStore.delete(service: service, account: notionAccount)
        try? KeychainStore.delete(service: service, account: openMeteoAccount)

        let store = SettingsStore(
            defaults: defaults,
            keychainService: service,
            openAIKeychainAccount: openAIAccount,
            jinaKeychainAccount: jinaAccount,
            notionKeychainAccount: notionAccount,
            openMeteoKeychainAccount: openMeteoAccount,
            keychainAccessGroup: nil,
            requireSharedCapabilities: false
        )
        store.openAIKey = "secret"
        store.jinaAPIKey = "jina-secret"
        store.notionApiToken = "notion-secret"
        store.openMeteoKey = "openmeteo-secret"
        store.notionParentPage = "parent-id"
        store.researchModel = "research"
        store.summaryModel = "summary"
        store.lookupModel = "lookup-model"
        store.primaryLanguage = "French"
        store.mock = true
        store.pythonInterpreterPath = "/bin/echo"
        try store.save()

        let reloaded = SettingsStore(
            defaults: defaults,
            keychainService: service,
            openAIKeychainAccount: openAIAccount,
            jinaKeychainAccount: jinaAccount,
            notionKeychainAccount: notionAccount,
            openMeteoKeychainAccount: openMeteoAccount,
            keychainAccessGroup: nil,
            requireSharedCapabilities: false
        )

        XCTAssertEqual(reloaded.openAIKey, "secret")
        XCTAssertEqual(reloaded.jinaAPIKey, "jina-secret")
        XCTAssertEqual(reloaded.notionApiToken, "notion-secret")
        XCTAssertEqual(reloaded.openMeteoKey, "openmeteo-secret")
        XCTAssertEqual(reloaded.notionParentPage, "parent-id")
        XCTAssertEqual(reloaded.researchModel, "research")
        XCTAssertEqual(reloaded.summaryModel, "summary")
        XCTAssertEqual(reloaded.lookupModel, "lookup-model")
        XCTAssertEqual(reloaded.primaryLanguage, "French")
        XCTAssertTrue(reloaded.mock)
        XCTAssertEqual(reloaded.pythonInterpreterPath, "/bin/echo")

        try? KeychainStore.delete(service: service, account: openAIAccount)
        try? KeychainStore.delete(service: service, account: jinaAccount)
        try? KeychainStore.delete(service: service, account: notionAccount)
        try? KeychainStore.delete(service: service, account: openMeteoAccount)
        defaults.removePersistentDomain(forName: suiteName)
    }

    func testEngineCommandRequirements() {
        XCTAssertFalse(EngineCommand.prettifyCodexLog.requiresAPIKey)
        XCTAssertFalse(EngineCommand.inspectTable.requiresAPIKey)
        XCTAssertTrue(EngineCommand.summarizeText.requiresAPIKey)
    }

    @MainActor
    func testPreparedCommandAllowsMockRequestsWithoutAPIKey() throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        let packageDirectory = temp.appendingPathComponent("src/werkzeugkasten")
        try FileManager.default.createDirectory(at: packageDirectory, withIntermediateDirectories: true)
        try "print('ok')".write(to: packageDirectory.appendingPathComponent("__main__.py"), atomically: true, encoding: .utf8)

        let configuration = EngineConfiguration(
            openAIKey: "",
            jinaAPIKey: "",
            notionApiToken: "",
            notionParentPage: "",
            openMeteoKey: "",
            researchModel: "research-model",
            summaryModel: "summary-model",
            lookupModel: "lookup-model",
            primaryLanguage: "French",
            mock: true,
            pythonInterpreterPath: "/bin/echo"
        )

        let prepared = try EngineRunner(resourceURLOverride: temp).preparedCommand(
            command: .summarizeText,
            payload: ["text": "Hello"],
            configuration: configuration
        )

        let request = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: prepared.stdinData) as? [String: Any]
        )
        XCTAssertEqual(request["service"] as? String, "summarize-text")
        XCTAssertEqual(prepared.environment["WERKZEUGKASTEN_MOCK"], "1")
    }
}
