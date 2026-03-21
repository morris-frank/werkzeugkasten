import Foundation
import Combine

@MainActor
public final class SettingsStore: ObservableObject {
    @Published public var apiKey: String
    @Published public var researchModel: String
    @Published public var summaryModel: String
    @Published public var pythonInterpreterPath: String

    private let defaults: UserDefaults
    private let keychainService: String
    private let keychainAccount: String
    private let keychainAccessGroup: String?

    public init(
        defaults: UserDefaults? = UserDefaults(suiteName: ShortcutsConstants.appGroup),
        keychainService: String = ShortcutsConstants.keychainService,
        keychainAccount: String = ShortcutsConstants.keychainAccount,
        keychainAccessGroup: String? = Bundle.main.object(forInfoDictionaryKey: "ShortcutsKeychainAccessGroup") as? String
    ) {
        self.defaults = defaults ?? .standard
        self.keychainService = keychainService
        self.keychainAccount = keychainAccount
        self.keychainAccessGroup = keychainAccessGroup
        self.researchModel = Self.loadDefault("researchModel", from: defaults) ?? ShortcutsConstants.defaultResearchModel
        self.summaryModel = Self.loadDefault("summaryModel", from: defaults) ?? ShortcutsConstants.defaultSummaryModel
        self.pythonInterpreterPath = Self.loadDefault("pythonInterpreterPath", from: defaults) ?? ShortcutsConstants.defaultPythonInterpreterPath
        self.apiKey = (try? KeychainStore.load(service: keychainService, account: keychainAccount, accessGroup: keychainAccessGroup)) ?? ""
    }

    private static func loadDefault(_ key: String, from defaults: UserDefaults?) -> String? {
        defaults?.string(forKey: key)
    }

    public var interpreterIsReachable: Bool {
        FileManager.default.isExecutableFile(atPath: pythonInterpreterPath.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    public func save() throws {
        let normalizedResearchModel = researchModel.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedSummaryModel = summaryModel.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedInterpreter = pythonInterpreterPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedAPIKey = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)

        defaults.set(normalizedResearchModel.isEmpty ? ShortcutsConstants.defaultResearchModel : normalizedResearchModel, forKey: "researchModel")
        defaults.set(normalizedSummaryModel.isEmpty ? ShortcutsConstants.defaultSummaryModel : normalizedSummaryModel, forKey: "summaryModel")
        defaults.set(normalizedInterpreter.isEmpty ? ShortcutsConstants.defaultPythonInterpreterPath : normalizedInterpreter, forKey: "pythonInterpreterPath")

        if normalizedAPIKey.isEmpty {
            try KeychainStore.delete(service: keychainService, account: keychainAccount, accessGroup: keychainAccessGroup)
        } else {
            try KeychainStore.save(value: normalizedAPIKey, service: keychainService, account: keychainAccount, accessGroup: keychainAccessGroup)
        }

        apiKey = normalizedAPIKey
        researchModel = defaults.string(forKey: "researchModel") ?? ShortcutsConstants.defaultResearchModel
        summaryModel = defaults.string(forKey: "summaryModel") ?? ShortcutsConstants.defaultSummaryModel
        pythonInterpreterPath = defaults.string(forKey: "pythonInterpreterPath") ?? ShortcutsConstants.defaultPythonInterpreterPath
    }

    public func configuration() throws -> EngineConfiguration {
        let normalizedAPIKey = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedAPIKey.isEmpty else {
            throw EngineError.missingAPIKey
        }

        let normalizedInterpreter = pythonInterpreterPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard FileManager.default.isExecutableFile(atPath: normalizedInterpreter) else {
            throw EngineError.missingInterpreter(normalizedInterpreter)
        }

        return EngineConfiguration(
            apiKey: normalizedAPIKey,
            researchModel: researchModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? ShortcutsConstants.defaultResearchModel : researchModel.trimmingCharacters(in: .whitespacesAndNewlines),
            summaryModel: summaryModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? ShortcutsConstants.defaultSummaryModel : summaryModel.trimmingCharacters(in: .whitespacesAndNewlines),
            pythonInterpreterPath: normalizedInterpreter
        )
    }
}
