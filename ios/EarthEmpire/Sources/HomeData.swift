import Foundation

/// One tile of `GET /v1/layout` (CONTRACT.md "Home layout"): what Home reads of it.
struct LayoutTile: Decodable, Hashable, Sendable {
    var id: String
    var kind: String?
    var level: Int?
    var importance: Double?
}

struct LayoutResponse: Decodable {
    struct Halves: Decodable { var top: [LayoutTile]?; var bottom: [LayoutTile]? }
    var tiles: [LayoutTile]?
    var halves: Halves?
}

/// An AI-defined grouping (`GET /v1/facets`), e.g. Themes, with its categories.
struct Facet: Decodable, Hashable, Sendable {
    var id: String
    var name: String
    var description: String?
    var categories: [FacetCategory]
}

struct FacetCategory: Decodable, Hashable, Sendable {
    var id: String
    var name: String
    var description: String?
    var count: Int
    var itemIds: [String]
}

struct FacetList: Decodable { var facets: [Facet] }

/// A moment the monitor found in a public video elsewhere, approved for Home (`GET /v1/published`).
struct PublishedHit: Decodable, Hashable, Identifiable, Sendable {
    struct Video: Decodable, Hashable, Sendable { var title: String?; var url: String?; var postedAt: String?; var thumbnail: String? }
    struct Source: Decodable, Hashable, Sendable { var name: String? }
    struct Excerpt: Decodable, Hashable, Sendable { var text: String?; var language: String? }
    var id: String
    var kind: String?
    var phrase: String?
    var matched: String?
    var confidence: Double?
    var level: Int?
    var platform: String?
    var account: String?
    var source: Source?
    var video: Video?
    var excerpt: Excerpt?
    var clip: String?
    var frame: String?
    var foundAt: String?

    /// What was heard, as the web shows it: a quoted name or the language.
    var what: String {
        if kind == "language" { return "\(["uk": "Ukrainian", "ru": "Russian", "en": "English"][matched ?? ""] ?? matched ?? "") speech" }
        return "“\(matched ?? phrase ?? "")”"
    }
    /// What sounds in the clip, as short as a highlight name: the words around the match in the
    /// transcript (two on each side), else the first words, else the match itself (web: heardOf).
    var heard: String {
        let words = (excerpt?.text ?? "").split(whereSeparator: \.isWhitespace).map(String.init)
        let strip = { (w: String) in w.trimmingCharacters(in: .punctuationCharacters.union(.symbols)) }
        let key = kind == "name" ? (matched ?? phrase ?? "").lowercased().split(separator: " ").first.map(String.init) ?? "" : ""
        if !key.isEmpty, let at = words.firstIndex(where: { $0.lowercased().contains(key) }) {
            return words[max(0, at - 2)..<min(words.count, at + 3)].map(strip).filter { !$0.isEmpty }.joined(separator: " ")
        }
        if !words.isEmpty { return words.prefix(6).map(strip).filter { !$0.isEmpty }.joined(separator: " ") + (words.count > 6 ? "…" : "") }
        return kind == "language" ? what : matched ?? phrase ?? ""
    }
    var title: String { video?.title ?? "\(what) in \(source?.name ?? account ?? platform ?? "a video")" }
}

struct PublishedList: Decodable { var hits: [PublishedHit]? }
