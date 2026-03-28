import Foundation
import Combine
import Security

@MainActor
public final class SettingsStore: ObservableObject {
    @Published public var openAIKey: String
    @Published public var jinaAPIKey: String
    @Published public var notionToken: String
    @Published public var openMeteoKey: String
    @Published public var notionParentPage: String
    @Published public var researchModel: String
    @Published public var summaryModel: String
    @Published public var lookupModel: String
    @Published public var primaryLanguage: String
    @Published public var mock: Bool
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
        self.lookupModel = Self.loadDefault("lookupModel", from: self.defaults) ?? WerkzeugkastenConstants.defaultLookupModel
        self.primaryLanguage = Self.loadDefault("primaryLanguage", from: self.defaults) ?? WerkzeugkastenConstants.defaultPrimaryLanguage
        self.mock = self.defaults.bool(forKey: "mock")
        self.pythonInterpreterPath = Self.loadDefault("pythonInterpreterPath", from: self.defaults) ?? WerkzeugkastenConstants.defaultPythonInterpreterPath
        self.keychainIssue = nil
        var resolvedKeychainIssue: String?

        do {
            self.openAIKey = try KeychainStore.load(
                service: keychainService,
                account: openAIKeychainAccount,
                accessGroup: keychainAccessGroup
            ) ?? ""
        } catch {
            self.openAIKey = ""
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
            self.openMeteoKey = try KeychainStore.load(
                service: keychainService,
                account: openMeteoKeychainAccount,
                accessGroup: keychainAccessGroup
            ) ?? ""
        } catch {
            self.openMeteoKey = ""
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
        let nInterpreter = pythonInterpreterPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let nPrimaryLanguage = primaryLanguage.trimmingCharacters(in: .whitespacesAndNewlines)
        let nResearchModel = researchModel.trimmingCharacters(in: .whitespacesAndNewlines)
        let nSummaryModel = summaryModel.trimmingCharacters(in: .whitespacesAndNewlines)
        let nLookupModel = lookupModel.trimmingCharacters(in: .whitespacesAndNewlines)
        let nOpenAIKey = openAIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let nJinaAPIKey = jinaAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let nNotionToken = notionToken.trimmingCharacters(in: .whitespacesAndNewlines)
        let nOpenMeteoKey = openMeteoKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let nNotionParentPage = notionParentPage.trimmingCharacters(in: .whitespacesAndNewlines)

        defaults.set(nResearchModel.isEmpty ? WerkzeugkastenConstants.defaultResearchModel : nResearchModel, forKey: "researchModel")
        defaults.set(nSummaryModel.isEmpty ? WerkzeugkastenConstants.defaultSummaryModel : nSummaryModel, forKey: "summaryModel")
        defaults.set(
            nLookupModel.isEmpty ? WerkzeugkastenConstants.defaultLookupModel : nLookupModel,
            forKey: "lookupModel"
        )
        defaults.set(nPrimaryLanguage.isEmpty ? WerkzeugkastenConstants.defaultPrimaryLanguage : nPrimaryLanguage, forKey: "primaryLanguage")
        defaults.set(mock, forKey: "mock")
        defaults.set(nInterpreter.isEmpty ? WerkzeugkastenConstants.defaultPythonInterpreterPath : nInterpreter, forKey: "pythonInterpreterPath")
        defaults.set(nNotionParentPage, forKey: "notionParentPage")

        do {
            if nOpenAIKey.isEmpty {
                try KeychainStore.delete(service: keychainService, account: openAIKeychainAccount, accessGroup: keychainAccessGroup)
            } else {
                try KeychainStore.save(value: nOpenAIKey, service: keychainService, account: openAIKeychainAccount, accessGroup: keychainAccessGroup)
            }

            if nJinaAPIKey.isEmpty {
                try KeychainStore.delete(service: keychainService, account: jinaKeychainAccount, accessGroup: keychainAccessGroup)
            } else {
                try KeychainStore.save(value: nJinaAPIKey, service: keychainService, account: jinaKeychainAccount, accessGroup: keychainAccessGroup)
            }

            if nNotionToken.isEmpty {
                try KeychainStore.delete(service: keychainService, account: notionKeychainAccount, accessGroup: keychainAccessGroup)
            } else {
                try KeychainStore.save(value: nNotionToken, service: keychainService, account: notionKeychainAccount, accessGroup: keychainAccessGroup)
            }

            if nOpenMeteoKey.isEmpty {
                try KeychainStore.delete(service: keychainService, account: openMeteoKeychainAccount, accessGroup: keychainAccessGroup)
            } else {
                try KeychainStore.save(value: nOpenMeteoKey, service: keychainService, account: openMeteoKeychainAccount, accessGroup: keychainAccessGroup)
            }
        } catch let error as EngineError {
            throw error
        } catch {
            throw EngineError.keychainAccessFailure(
                Self.describeKeychainFailure(error, accessGroup: keychainAccessGroup)
            )
        }

        openAIKey = nOpenAIKey
        jinaAPIKey = nJinaAPIKey
        notionToken = nNotionToken
        openMeteoKey = nOpenMeteoKey
        notionParentPage = nNotionParentPage
        researchModel = defaults.string(forKey: "researchModel") ?? WerkzeugkastenConstants.defaultResearchModel
        summaryModel = defaults.string(forKey: "summaryModel") ?? WerkzeugkastenConstants.defaultSummaryModel
        lookupModel = defaults.string(forKey: "lookupModel") ?? WerkzeugkastenConstants.defaultLookupModel
        primaryLanguage = defaults.string(forKey: "primaryLanguage") ?? WerkzeugkastenConstants.defaultPrimaryLanguage
        mock = defaults.bool(forKey: "mock")
        pythonInterpreterPath = defaults.string(forKey: "pythonInterpreterPath") ?? WerkzeugkastenConstants.defaultPythonInterpreterPath
    }

    public func configuration() throws -> EngineConfiguration {
        let nInterpreter = pythonInterpreterPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard FileManager.default.isExecutableFile(atPath: nInterpreter) else {
            throw EngineError.missingInterpreter(nInterpreter)
        }

        let trimmedLanguage = primaryLanguage.trimmingCharacters(in: .whitespacesAndNewlines)
        let resolvedLanguage = trimmedLanguage.isEmpty ? WerkzeugkastenConstants.defaultPrimaryLanguage : trimmedLanguage

        return EngineConfiguration(
            openAIKey: openAIKey.trimmingCharacters(in: .whitespacesAndNewlines),
            jinaAPIKey: jinaAPIKey.trimmingCharacters(in: .whitespacesAndNewlines),
            notionToken: notionToken.trimmingCharacters(in: .whitespacesAndNewlines),
            notionParentPage: notionParentPage.trimmingCharacters(in: .whitespacesAndNewlines),
            openMeteoKey: openMeteoKey.trimmingCharacters(in: .whitespacesAndNewlines),
            researchModel: researchModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? WerkzeugkastenConstants.defaultResearchModel : researchModel.trimmingCharacters(in: .whitespacesAndNewlines),
            summaryModel: summaryModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? WerkzeugkastenConstants.defaultSummaryModel : summaryModel.trimmingCharacters(in: .whitespacesAndNewlines),
            lookupModel: lookupModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? WerkzeugkastenConstants.defaultLookupModel : lookupModel.trimmingCharacters(in: .whitespacesAndNewlines),
            primaryLanguage: resolvedLanguage,
            mock: mock,
            pythonInterpreterPath: nInterpreter
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
