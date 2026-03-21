import Foundation

public enum InputNormalizer {
    public static func parseResearchItems(_ text: String) -> [String] {
        text
            .split(whereSeparator: \.isNewline)
            .map { line in
                line
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                    .replacingOccurrences(
                        of: #"^\s*(?:[-*+]\s+|\d+[.)]\s+)"#,
                        with: "",
                        options: .regularExpression
                    )
                    .trimmingCharacters(in: .whitespacesAndNewlines)
            }
            .filter { !$0.isEmpty && $0.rangeOfCharacter(from: .alphanumerics) != nil }
    }

    public static func uniqueFileURLs(_ urls: [URL]) -> [URL] {
        var seen = Set<String>()
        var output: [URL] = []
        for url in urls {
            let standardized = url.standardizedFileURL
            if seen.insert(standardized.path).inserted {
                output.append(standardized)
            }
        }
        return output
    }

    public static func loadTextFile(_ url: URL) throws -> String {
        try String(contentsOf: url, encoding: .utf8)
    }
}
