import Foundation

public struct EngineConfiguration: Equatable, Sendable {
    public var openAIKey: String
    public var jinaAPIKey: String
    public var notionApiToken: String
    public var notionParentPage: String
    public var openMeteoKey: String
    public var researchModel: String
    public var summaryModel: String
    public var lookupModel: String
    public var primaryLanguage: String
    public var mock: Bool
    public var pythonInterpreterPath: String

    public init(
        openAIKey: String,
        jinaAPIKey: String,
        notionApiToken: String,
        notionParentPage: String,
        openMeteoKey: String,
        researchModel: String,
        summaryModel: String,
        lookupModel: String,
        primaryLanguage: String,
        mock: Bool,
        pythonInterpreterPath: String
    ) {
        self.openAIKey = openAIKey
        self.jinaAPIKey = jinaAPIKey
        self.notionApiToken = notionApiToken
        self.notionParentPage = notionParentPage
        self.openMeteoKey = openMeteoKey
        self.researchModel = researchModel
        self.summaryModel = summaryModel
        self.lookupModel = lookupModel
        self.primaryLanguage = primaryLanguage
        self.mock = mock
        self.pythonInterpreterPath = pythonInterpreterPath
    }
}

public enum EngineCommand: String, Sendable {
    case researchList = "research-list"
    case inspectTable = "inspect-table"
    case researchTable = "research-table"
    case summarizeFiles = "summarize-files"
    case summarizeText = "summarize-text"
    case prettifyCodexLog = "prettify-codex-log"

    public var requiresAPIKey: Bool {
        switch self {
        case .inspectTable, .prettifyCodexLog:
            return false
        case .researchList, .researchTable, .summarizeFiles, .summarizeText:
            return true
        }
    }
}

public struct PreparedCommand: Equatable, Sendable {
    public var executableURL: URL
    public var arguments: [String]
    public var environment: [String: String]
    public var workingDirectoryURL: URL?
    public var stdinData: Data

    public init(
        executableURL: URL,
        arguments: [String],
        environment: [String: String],
        workingDirectoryURL: URL?,
        stdinData: Data
    ) {
        self.executableURL = executableURL
        self.arguments = arguments
        self.environment = environment
        self.workingDirectoryURL = workingDirectoryURL
        self.stdinData = stdinData
    }
}

public struct EngineResponseEnvelope<Response: Decodable>: Decodable {
    public let data: Response
}

public struct ResearchListResponse: Decodable, Equatable, Sendable {
    public let outputPath: String
    public let itemCount: Int
    public let completedCount: Int
    public let headers: [String]
    public let questionColumns: [String]
    public let attributeColumns: [String]

    enum CodingKeys: String, CodingKey {
        case outputPath = "output_path"
        case itemCount = "item_count"
        case completedCount = "completed_count"
        case headers
        case questionColumns = "question_columns"
        case attributeColumns = "attribute_columns"
    }
}

public struct TablePreview: Decodable, Equatable, Sendable {
    public let format: String
    public let headers: [String]
    public let rowCount: Int
    public let questionColumns: [String]
    public let attributeColumns: [String]
    public let exampleKey: String
    public let objectType: String

    public init(
        format: String,
        headers: [String],
        rowCount: Int,
        questionColumns: [String],
        attributeColumns: [String],
        exampleKey: String,
        objectType: String
    ) {
        self.format = format
        self.headers = headers
        self.rowCount = rowCount
        self.questionColumns = questionColumns
        self.attributeColumns = attributeColumns
        self.exampleKey = exampleKey
        self.objectType = objectType
    }

    enum CodingKeys: String, CodingKey {
        case format = "format"
        case headers
        case rowCount = "row_count"
        case questionColumns = "question_columns"
        case attributeColumns = "attribute_columns"
        case exampleKey = "example_key"
        case objectType = "object_type"
    }
}

public struct ResearchTableResponse: Decodable, Equatable, Sendable {
    public let outputPath: String
    public let format: String
    public let headers: [String]
    public let rowCount: Int
    public let questionColumns: [String]
    public let attributeColumns: [String]
    public let exampleKey: String
    public let objectType: String

    enum CodingKeys: String, CodingKey {
        case outputPath = "output_path"
        case format = "format"
        case headers
        case rowCount = "row_count"
        case questionColumns = "question_columns"
        case attributeColumns = "attribute_columns"
        case exampleKey = "example_key"
        case objectType = "object_type"
    }
}

public struct SummarizeResponse: Decodable, Equatable, Sendable {
    public let summary: String
    public let content: String
    public let tokenCount: Int
    public let inputTokens: Int
    public let outputTokens: Int

    enum CodingKeys: String, CodingKey {
        case summary = "summary"
        case content = "content"
        case tokenCount = "token_count"
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
    }
}

public struct PrettifyCodexLogResponse: Decodable, Equatable, Sendable {
    public let outputPath: String
    public let completedTurnCount: Int
    public let imageCount: Int
    public let toolCallCount: Int
    public let totalTokenCount: Int?

    enum CodingKeys: String, CodingKey {
        case outputPath = "output_path"
        case completedTurnCount = "completed_turn_count"
        case imageCount = "image_count"
        case toolCallCount = "tool_call_count"
        case totalTokenCount = "total_token_count"
    }
}

public enum EngineError: LocalizedError, Equatable {
    case missingAPIKey
    case missingInterpreter(String)
    case missingResources
    case sharedSettingsUnavailable(String)
    case keychainAccessFailure(String)
    case invalidPayload(String)
    case processFailure(String)
    case invalidResponse(String)

    public var errorDescription: String? {
        switch self {
        case .missingAPIKey:
            return "Set an OpenAI API key in Settings."
        case .missingInterpreter(let path):
            return "Python interpreter not found or not executable: \(path)"
        case .missingResources:
            return "Bundled Python resources are missing."
        case .sharedSettingsUnavailable(let message):
            return message
        case .keychainAccessFailure(let message):
            return message
        case .invalidPayload(let message):
            return message
        case .processFailure(let message):
            return message
        case .invalidResponse(let message):
            return message
        }
    }
}
