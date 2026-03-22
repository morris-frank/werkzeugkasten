import Foundation
import Combine
import Security

@MainActor
public final class SettingsStore: ObservableObject {
    @Published public var apiKey: String
    @Published public var researchModel: String
    @Published public var summaryModel: String
    @Published public var pythonInterpreterPath: String
    @Published public private(set) var keychainIssue: String?

    private let defaults: UserDefaults
    private let keychainService: String
    private let keychainAccount: String
    private let keychainAccessGroup: String?

    public init(
        defaults: UserDefaults = .standard,
        keychainService: String = WerkzeugkastenConstants.keychainService,
        keychainAccount: String = WerkzeugkastenConstants.keychainAccount,
        keychainAccessGroup: String? = nil,
        requireSharedCapabilities _: Bool = false
    ) {
        self.defaults = defaults
        self.keychainService = keychainService
        self.keychainAccount = keychainAccount
        self.keychainAccessGroup = keychainAccessGroup
        self.researchModel = Self.loadDefault("researchModel", from: self.defaults) ?? WerkzeugkastenConstants.defaultResearchModel
        self.summaryModel = Self.loadDefault("summaryModel", from: self.defaults) ?? WerkzeugkastenConstants.defaultSummaryModel
        self.pythonInterpreterPath = Self.loadDefault("pythonInterpreterPath", from: self.defaults) ?? WerkzeugkastenConstants.defaultPythonInterpreterPath
        self.keychainIssue = nil

        do {
            self.apiKey = try KeychainStore.load(
                service: keychainService,
                account: keychainAccount,
                accessGroup: keychainAccessGroup
            ) ?? ""
        } catch {
            self.apiKey = ""
            self.keychainIssue = Self.describeKeychainFailure(
                error,
                accessGroup: keychainAccessGroup,
                fallback: self.keychainIssue
            )
        }
    }

    private static func loadDefault(_ key: String, from defaults: UserDefaults) -> String? {
        defaults.string(forKey: key)
    }

    public var interpreterIsReachable: Bool {
        FileManager.default.isExecutableFile(atPath: pythonInterpreterPath.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    public var suggestedPythonInterpreterPath: String {
        WerkzeugkastenConstants.defaultPythonInterpreterPath
    }

    public func save() throws {
        let normalizedResearchModel = researchModel.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedSummaryModel = summaryModel.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedInterpreter = pythonInterpreterPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedAPIKey = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)

        defaults.set(normalizedResearchModel.isEmpty ? WerkzeugkastenConstants.defaultResearchModel : normalizedResearchModel, forKey: "researchModel")
        defaults.set(normalizedSummaryModel.isEmpty ? WerkzeugkastenConstants.defaultSummaryModel : normalizedSummaryModel, forKey: "summaryModel")
        defaults.set(normalizedInterpreter.isEmpty ? WerkzeugkastenConstants.defaultPythonInterpreterPath : normalizedInterpreter, forKey: "pythonInterpreterPath")

        do {
            if normalizedAPIKey.isEmpty {
                try KeychainStore.delete(service: keychainService, account: keychainAccount, accessGroup: keychainAccessGroup)
            } else {
                try KeychainStore.save(value: normalizedAPIKey, service: keychainService, account: keychainAccount, accessGroup: keychainAccessGroup)
            }
        } catch let error as EngineError {
            throw error
        } catch {
            throw EngineError.keychainAccessFailure(
                Self.describeKeychainFailure(error, accessGroup: keychainAccessGroup)
            )
        }

        apiKey = normalizedAPIKey
        researchModel = defaults.string(forKey: "researchModel") ?? WerkzeugkastenConstants.defaultResearchModel
        summaryModel = defaults.string(forKey: "summaryModel") ?? WerkzeugkastenConstants.defaultSummaryModel
        pythonInterpreterPath = defaults.string(forKey: "pythonInterpreterPath") ?? WerkzeugkastenConstants.defaultPythonInterpreterPath
    }

    public func configuration() throws -> EngineConfiguration {
        let normalizedInterpreter = pythonInterpreterPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard FileManager.default.isExecutableFile(atPath: normalizedInterpreter) else {
            throw EngineError.missingInterpreter(normalizedInterpreter)
        }

        return EngineConfiguration(
            apiKey: apiKey.trimmingCharacters(in: .whitespacesAndNewlines),
            researchModel: researchModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? WerkzeugkastenConstants.defaultResearchModel : researchModel.trimmingCharacters(in: .whitespacesAndNewlines),
            summaryModel: summaryModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? WerkzeugkastenConstants.defaultSummaryModel : summaryModel.trimmingCharacters(in: .whitespacesAndNewlines),
            pythonInterpreterPath: normalizedInterpreter
        )
    }

    private static func describeKeychainFailure(_ error: Error, accessGroup: String?, fallback: String? = nil) -> String {
        let nsError = error as NSError
        let osStatus = OSStatus(nsError.code)
        let details = SecCopyErrorMessageString(osStatus, nil) as String? ?? error.localizedDescription
        if let accessGroup {
            return "Shared keychain access failed for `\(accessGroup)`: \(details)"
        }
        return fallback ?? "Keychain access failed: \(details)"
    }
}
