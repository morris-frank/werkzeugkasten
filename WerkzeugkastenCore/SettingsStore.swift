import Foundation
import Combine
import Security

@MainActor
public final class SettingsStore: ObservableObject {
    @Published public var apiKey: String
    @Published public var jinaAPIKey: String
    @Published public var notionToken: String
    @Published public var openMeteoAPIKey: String
    @Published public var notionParentPage: String
    @Published public var researchModel: String
    @Published public var summaryModel: String
    @Published public var summaryMirrorLanguages: String
    @Published public var pythonInterpreterPath: String
    @Published public private(set) var keychainIssue: String?

    private let defaults: UserDefaults
    private let keychainService: String
    private let openAIKeychainAccount: String
    private let jinaKeychainAccount: String
    private let notionKeychainAccount: String
    private let openMeteoKeychainAccount: String
    private let keychainAccessGroup: String?

    public init(
        defaults: UserDefaults = .standard,
        keychainService: String = WerkzeugkastenConstants.keychainService,
        openAIKeychainAccount: String = WerkzeugkastenConstants.openAIKeychainAccount,
        jinaKeychainAccount: String = WerkzeugkastenConstants.jinaKeychainAccount,
        notionKeychainAccount: String = WerkzeugkastenConstants.notionKeychainAccount,
        openMeteoKeychainAccount: String = WerkzeugkastenConstants.openMeteoKeychainAccount,
        keychainAccessGroup: String? = nil,
        requireSharedCapabilities _: Bool = false
    ) {
        self.defaults = defaults
        self.keychainService = keychainService
        self.openAIKeychainAccount = openAIKeychainAccount
        self.jinaKeychainAccount = jinaKeychainAccount
        self.notionKeychainAccount = notionKeychainAccount
        self.openMeteoKeychainAccount = openMeteoKeychainAccount
        self.keychainAccessGroup = keychainAccessGroup
        self.notionParentPage = Self.loadDefault("notionParentPage", from: self.defaults) ?? ""
        self.researchModel = Self.loadDefault("researchModel", from: self.defaults) ?? WerkzeugkastenConstants.defaultResearchModel
        self.summaryModel = Self.loadDefault("summaryModel", from: self.defaults) ?? WerkzeugkastenConstants.defaultSummaryModel
        self.summaryMirrorLanguages =
            Self.loadDefault(WerkzeugkastenConstants.summaryMirrorLanguagesKey, from: self.defaults)
            ?? WerkzeugkastenConstants.defaultSummaryMirrorLanguages
        self.pythonInterpreterPath = Self.loadDefault("pythonInterpreterPath", from: self.defaults) ?? WerkzeugkastenConstants.defaultPythonInterpreterPath
        self.keychainIssue = nil
        var resolvedKeychainIssue: String?

        do {
            self.apiKey = try KeychainStore.load(
                service: keychainService,
                account: openAIKeychainAccount,
                accessGroup: keychainAccessGroup
            ) ?? ""
        } catch {
            self.apiKey = ""
            resolvedKeychainIssue = Self.describeKeychainFailure(
                error,
                accessGroup: keychainAccessGroup,
                fallback: resolvedKeychainIssue
            )
        }

        do {
            self.jinaAPIKey = try KeychainStore.load(
                service: keychainService,
                account: jinaKeychainAccount,
                accessGroup: keychainAccessGroup
            ) ?? ""
        } catch {
            self.jinaAPIKey = ""
            resolvedKeychainIssue = Self.describeKeychainFailure(
                error,
                accessGroup: keychainAccessGroup,
                fallback: resolvedKeychainIssue
            )
        }

        do {
            self.notionToken = try KeychainStore.load(
                service: keychainService,
                account: notionKeychainAccount,
                accessGroup: keychainAccessGroup
            ) ?? ""
        } catch {
            self.notionToken = ""
            resolvedKeychainIssue = Self.describeKeychainFailure(
                error,
                accessGroup: keychainAccessGroup,
                fallback: resolvedKeychainIssue
            )
        }

        do {
            self.openMeteoAPIKey = try KeychainStore.load(
                service: keychainService,
                account: openMeteoKeychainAccount,
                accessGroup: keychainAccessGroup
            ) ?? ""
        } catch {
            self.openMeteoAPIKey = ""
            resolvedKeychainIssue = Self.describeKeychainFailure(
                error,
                accessGroup: keychainAccessGroup,
                fallback: resolvedKeychainIssue
            )
        }
        self.keychainIssue = resolvedKeychainIssue
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
        let normalizedSummaryMirrorLanguages = summaryMirrorLanguages.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedInterpreter = pythonInterpreterPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedAPIKey = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedJinaAPIKey = jinaAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedNotionToken = notionToken.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedOpenMeteoAPIKey = openMeteoAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedNotionParentPage = notionParentPage.trimmingCharacters(in: .whitespacesAndNewlines)

        defaults.set(normalizedResearchModel.isEmpty ? WerkzeugkastenConstants.defaultResearchModel : normalizedResearchModel, forKey: "researchModel")
        defaults.set(normalizedSummaryModel.isEmpty ? WerkzeugkastenConstants.defaultSummaryModel : normalizedSummaryModel, forKey: "summaryModel")
        defaults.set(
            normalizedSummaryMirrorLanguages.isEmpty ? WerkzeugkastenConstants.defaultSummaryMirrorLanguages : normalizedSummaryMirrorLanguages,
            forKey: WerkzeugkastenConstants.summaryMirrorLanguagesKey
        )
        defaults.set(normalizedInterpreter.isEmpty ? WerkzeugkastenConstants.defaultPythonInterpreterPath : normalizedInterpreter, forKey: "pythonInterpreterPath")
        defaults.set(normalizedNotionParentPage, forKey: "notionParentPage")

        do {
            if normalizedAPIKey.isEmpty {
                try KeychainStore.delete(service: keychainService, account: openAIKeychainAccount, accessGroup: keychainAccessGroup)
            } else {
                try KeychainStore.save(value: normalizedAPIKey, service: keychainService, account: openAIKeychainAccount, accessGroup: keychainAccessGroup)
            }

            if normalizedJinaAPIKey.isEmpty {
                try KeychainStore.delete(service: keychainService, account: jinaKeychainAccount, accessGroup: keychainAccessGroup)
            } else {
                try KeychainStore.save(value: normalizedJinaAPIKey, service: keychainService, account: jinaKeychainAccount, accessGroup: keychainAccessGroup)
            }

            if normalizedNotionToken.isEmpty {
                try KeychainStore.delete(service: keychainService, account: notionKeychainAccount, accessGroup: keychainAccessGroup)
            } else {
                try KeychainStore.save(value: normalizedNotionToken, service: keychainService, account: notionKeychainAccount, accessGroup: keychainAccessGroup)
            }

            if normalizedOpenMeteoAPIKey.isEmpty {
                try KeychainStore.delete(service: keychainService, account: openMeteoKeychainAccount, accessGroup: keychainAccessGroup)
            } else {
                try KeychainStore.save(value: normalizedOpenMeteoAPIKey, service: keychainService, account: openMeteoKeychainAccount, accessGroup: keychainAccessGroup)
            }
        } catch let error as EngineError {
            throw error
        } catch {
            throw EngineError.keychainAccessFailure(
                Self.describeKeychainFailure(error, accessGroup: keychainAccessGroup)
            )
        }

        apiKey = normalizedAPIKey
        jinaAPIKey = normalizedJinaAPIKey
        notionToken = normalizedNotionToken
        openMeteoAPIKey = normalizedOpenMeteoAPIKey
        notionParentPage = normalizedNotionParentPage
        researchModel = defaults.string(forKey: "researchModel") ?? WerkzeugkastenConstants.defaultResearchModel
        summaryModel = defaults.string(forKey: "summaryModel") ?? WerkzeugkastenConstants.defaultSummaryModel
        summaryMirrorLanguages =
            defaults.string(forKey: WerkzeugkastenConstants.summaryMirrorLanguagesKey)
            ?? WerkzeugkastenConstants.defaultSummaryMirrorLanguages
        pythonInterpreterPath = defaults.string(forKey: "pythonInterpreterPath") ?? WerkzeugkastenConstants.defaultPythonInterpreterPath
    }

    public func configuration() throws -> EngineConfiguration {
        let normalizedInterpreter = pythonInterpreterPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard FileManager.default.isExecutableFile(atPath: normalizedInterpreter) else {
            throw EngineError.missingInterpreter(normalizedInterpreter)
        }

        let trimmedMirror = summaryMirrorLanguages.trimmingCharacters(in: .whitespacesAndNewlines)
        let resolvedMirror = trimmedMirror.isEmpty ? WerkzeugkastenConstants.defaultSummaryMirrorLanguages : trimmedMirror

        return EngineConfiguration(
            apiKey: apiKey.trimmingCharacters(in: .whitespacesAndNewlines),
            jinaAPIKey: jinaAPIKey.trimmingCharacters(in: .whitespacesAndNewlines),
            notionToken: notionToken.trimmingCharacters(in: .whitespacesAndNewlines),
            notionParentPage: notionParentPage.trimmingCharacters(in: .whitespacesAndNewlines),
            openMeteoAPIKey: openMeteoAPIKey.trimmingCharacters(in: .whitespacesAndNewlines),
            researchModel: researchModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? WerkzeugkastenConstants.defaultResearchModel : researchModel.trimmingCharacters(in: .whitespacesAndNewlines),
            summaryModel: summaryModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? WerkzeugkastenConstants.defaultSummaryModel : summaryModel.trimmingCharacters(in: .whitespacesAndNewlines),
            summaryMirrorLanguages: resolvedMirror,
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
