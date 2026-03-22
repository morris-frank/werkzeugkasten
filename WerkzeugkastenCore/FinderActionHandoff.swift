import Foundation

public enum FinderActionHandoff {
    private enum CodingKeys {
        static let payload = "payload"
    }

    public static let route = "summarize-files"

    public static func makeSummarizeURL(fileURLs: [URL]) throws -> URL {
        let paths = InputNormalizer.uniqueFileURLs(fileURLs).map(\.path)
        guard !paths.isEmpty else {
            throw EngineError.invalidPayload("No files were provided to the Finder action.")
        }

        let payloadData = try JSONEncoder().encode(paths)
        let payload = payloadData.base64EncodedString()

        var components = URLComponents()
        components.scheme = WerkzeugkastenConstants.handoffURLScheme
        components.host = route
        components.queryItems = [URLQueryItem(name: CodingKeys.payload, value: payload)]

        guard let url = components.url else {
            throw EngineError.invalidPayload("Could not build the Finder handoff URL.")
        }

        return url
    }

    public static func parseSummarizeURL(_ url: URL) throws -> [URL] {
        guard url.scheme?.caseInsensitiveCompare(WerkzeugkastenConstants.handoffURLScheme) == .orderedSame else {
            throw EngineError.invalidPayload("Unsupported handoff URL scheme.")
        }

        guard url.host == route else {
            throw EngineError.invalidPayload("Unsupported handoff route.")
        }

        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        guard
            let payload = components?.queryItems?.first(where: { $0.name == CodingKeys.payload })?.value,
            let data = Data(base64Encoded: payload)
        else {
            throw EngineError.invalidPayload("The Finder handoff did not include a valid file payload.")
        }

        let paths = try JSONDecoder().decode([String].self, from: data)
        let urls = InputNormalizer.uniqueFileURLs(paths.map { URL(fileURLWithPath: $0) })
        guard !urls.isEmpty else {
            throw EngineError.invalidPayload("The Finder handoff did not include any files.")
        }
        return urls
    }
}
