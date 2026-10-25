import Foundation

// The shapes of CONTRACT.md ("The data"), decoded leniently: every field the backend may leave
// out is optional, an unknown `kind` still decodes, and `extra` keeps whatever JSON it holds.
// Keys are snake_case on the wire; the decoder converts them (`APIDecoding.decoder`).

enum ItemKind: String, Codable, CaseIterable, Hashable, Sendable {
    case post, carousel, reel, story
    case unknown

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = ItemKind(rawValue: raw) ?? .unknown
    }

    var label: String {
        switch self {
        case .post: "Post"
        case .carousel: "Carousel"
        case .reel: "Reel"
        case .story: "Story"
        case .unknown: "Item"
        }
    }

    var symbol: String {
        switch self {
        case .post: "photo"
        case .carousel: "square.on.square"
        case .reel: "play.rectangle"
        case .story: "circle.dashed"
        case .unknown: "questionmark.square"
        }
    }
}

struct Item: Codable, Identifiable, Hashable, Sendable {
    var id: String
    var kind: ItemKind
    var shortcode: String?
    var sourceUrl: String?
    var takenAt: String?
    var caption: String?
    var hashtags: [String]?
    var mentions: [String]?
    var taggedUsers: [TaggedUser]?
    var location: Location?
    var music: Music?
    var altText: String?
    var stickers: [Sticker]?
    var counts: Counts?
    var media: [Media]
    var highlights: [HighlightRef]?
    var repostOf: Repost?
    var categories: [String]?
    var summary: String?
    /// A few publishable sentences on who, what, when, where and context (the backend's).
    var description: String?
    var analysis: Analysis?
    var extra: JSONValue?
    var collectedAt: String?
    var updatedAt: String?
    var publishedAt: String?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = (try? c.decode(ItemKind.self, forKey: .kind)) ?? .unknown
        shortcode = try c.decodeIfPresent(String.self, forKey: .shortcode)
        sourceUrl = try c.decodeIfPresent(String.self, forKey: .sourceUrl)
        takenAt = try c.decodeIfPresent(String.self, forKey: .takenAt)
        caption = try c.decodeIfPresent(String.self, forKey: .caption)
        hashtags = try c.decodeIfPresent([String].self, forKey: .hashtags)
        mentions = try c.decodeIfPresent([String].self, forKey: .mentions)
        taggedUsers = try c.decodeIfPresent([TaggedUser].self, forKey: .taggedUsers)
        location = try c.decodeIfPresent(Location.self, forKey: .location)
        music = try c.decodeIfPresent(Music.self, forKey: .music)
        altText = try c.decodeIfPresent(String.self, forKey: .altText)
        stickers = try c.decodeIfPresent([Sticker].self, forKey: .stickers)
        counts = try c.decodeIfPresent(Counts.self, forKey: .counts)
        media = try c.decodeIfPresent([Media].self, forKey: .media) ?? []
        highlights = try c.decodeIfPresent([HighlightRef].self, forKey: .highlights)
        repostOf = try c.decodeIfPresent(Repost.self, forKey: .repostOf)
        categories = try c.decodeIfPresent([String].self, forKey: .categories)
        summary = try c.decodeIfPresent(String.self, forKey: .summary)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        analysis = try c.decodeIfPresent(Analysis.self, forKey: .analysis)
        extra = try c.decodeIfPresent(JSONValue.self, forKey: .extra)
        collectedAt = try c.decodeIfPresent(String.self, forKey: .collectedAt)
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
        publishedAt = try c.decodeIfPresent(String.self, forKey: .publishedAt)
    }

    var takenDate: Date? { takenAt.flatMap(ISODate.parse) }
    var isRepost: Bool { repostOf != nil }
    /// The picture that stands for the item in a grid: its first thumbnail, else the original's.
    var coverURL: URL? {
        let m = media.first ?? repostOf?.media?.first
        return URL(string: m?.poster ?? "")
    }

    /// What VoiceOver reads for the item wherever it appears as a tile: kind, what the analysis
    /// saw, and when.
    var accessibilityDescription: String {
        var parts = [isRepost ? "\(kind.label), repost of @\(repostOf?.author ?? "")" : kind.label]
        if let s = summary ?? description ?? analysis?.what ?? altText ?? caption { parts.append(s) }
        if let d = takenDate { parts.append(d.formatted(date: .long, time: .omitted)) }
        return parts.joined(separator: ". ")
    }
}

struct TaggedUser: Codable, Hashable, Sendable {
    var username: String
    var x: Double?
    var y: Double?
}

struct Location: Codable, Hashable, Sendable {
    var name: String?
    var id: String?
    var lat: Double?
    var lng: Double?
}

struct Music: Codable, Hashable, Sendable {
    var title: String?
    var artist: String?
    var line: String { [title, artist].compactMap { $0 }.joined(separator: " · ") }
}

struct Sticker: Codable, Hashable, Sendable {
    var type: String
    var text: String?
    var extra: JSONValue?
}

struct Counts: Codable, Hashable, Sendable {
    var likes: Int?
    var comments: Int?
    var views: Int?
    var plays: Int?
}

struct Media: Codable, Hashable, Sendable {
    enum Kind: String, Codable, Sendable { case image, video }
    var type: Kind
    var url: String
    var thumbnail: String?
    var width: Double?
    var height: Double?
    var duration: Double?
    /// Video only: the frame Claude picked as the best-looking, at full size, and its time.
    var cover: String?
    var coverAt: Double?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = (try? c.decode(Kind.self, forKey: .type)) ?? .image
        url = try c.decode(String.self, forKey: .url)
        thumbnail = try c.decodeIfPresent(String.self, forKey: .thumbnail)
        width = try c.decodeIfPresent(Double.self, forKey: .width)
        height = try c.decodeIfPresent(Double.self, forKey: .height)
        duration = try c.decodeIfPresent(Double.self, forKey: .duration)
        cover = try c.decodeIfPresent(String.self, forKey: .cover)
        coverAt = try c.decodeIfPresent(Double.self, forKey: .coverAt)
    }

    /// The picture that stands for this media: a video's chosen cover, else its thumbnail; an
    /// image's thumbnail, else the image.
    var poster: String { cover ?? thumbnail ?? url }

    var aspectRatio: CGFloat {
        guard let w = width, let h = height, w > 0, h > 0 else { return 1 }
        return CGFloat(w / h)
    }
}

struct HighlightRef: Codable, Hashable, Sendable {
    var id: String
    var title: String?
}

struct Repost: Codable, Hashable, Sendable {
    var author: String
    var authorName: String?
    var shortcode: String?
    var sourceUrl: String?
    var takenAt: String?
    var caption: String?
    var media: [Media]?
}

struct Analysis: Codable, Hashable, Sendable {
    var people: [Person]?
    var what: String?
    var events: [Event]?
    var time: When?
    var place: Where?
    var objects: [String]?
    var animals: [String]?
    var brands: [String]?
    var onScreenText: [String]?
    var speech: Speech?
    var music: String?
    var mood: String?
    var language: String?
    var context: String?
    var keywords: [String]?
    var model: String?
    var analyzedAt: String?

    enum CodingKeys: String, CodingKey {
        case people, what, events, objects, animals, brands, onScreenText, speech, music, mood,
             language, context, keywords, model, analyzedAt
        case time = "when"
        case place = "where"
    }

    struct Person: Codable, Hashable, Sendable {
        var who: String?
        var description: String?
        var basis: String?
        var role: String?
        var appears: [Appearance]?

        /// The name if the post gave one, else the description - never a guess from a face.
        var displayName: String { who ?? description ?? "Someone" }
    }

    struct Appearance: Codable, Hashable, Sendable {
        var media: Int?
        var from: Double?
        var to: Double?
    }

    struct Event: Codable, Hashable, Sendable {
        var media: Int?
        var at: Double?
        var text: String
    }

    struct When: Codable, Hashable, Sendable {
        var date: String?
        var timeOfDay: String?
        var season: String?
        var occasion: String?
        var basis: String?
        var line: String { [date, timeOfDay, season, occasion].compactMap { $0 }.joined(separator: " · ") }
    }

    struct Where: Codable, Hashable, Sendable {
        var place: String?
        var kind: String?
        var country: String?
        var basis: String?
        var line: String { [place, kind, country].compactMap { $0 }.joined(separator: " · ") }
    }

    struct Speech: Codable, Hashable, Sendable {
        var language: String?
        var transcript: String?
    }
}

struct Highlight: Codable, Identifiable, Hashable, Sendable {
    var id: String
    var title: String
    var cover: String?
    var itemIds: [String]
    var updatedAt: String?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        cover = try c.decodeIfPresent(String.self, forKey: .cover)
        itemIds = try c.decodeIfPresent([String].self, forKey: .itemIds) ?? []
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
    }
}

struct Category: Codable, Identifiable, Hashable, Sendable {
    var slug: String
    var name: String
    var description: String?
    var count: Int?
    var id: String { slug }
}

struct Profile: Codable, Hashable, Sendable {
    var username: String
    var fullName: String?
    var bio: String?
    var avatar: String?
    var links: [String]?
    var counts: ProfileCounts?
    var updatedAt: String?

    struct ProfileCounts: Codable, Hashable, Sendable {
        var posts: Int?
        var followers: Int?
        var following: Int?
    }
}

// The list envelopes.

struct ItemPage: Codable, Sendable {
    var items: [Item]
    var next: String?
}

struct HighlightList: Codable, Sendable { var highlights: [Highlight] }
struct TagList: Codable, Sendable { var tags: [Tag] }

/// A tag-cloud entry (`GET /v1/tags`): lowercase, of one kind, with how many items have it.
struct Tag: Codable, Hashable, Identifiable, Sendable {
    var tag: String
    var kind: String
    var count: Int
    var id: String { kind + ":" + tag }
}
struct CategoryList: Codable, Sendable { var categories: [Category] }

/// Any JSON, for `extra` and sticker payloads the contract leaves open.
enum JSONValue: Codable, Hashable, Sendable {
    case string(String), number(Double), bool(Bool), object([String: JSONValue]), array([JSONValue]), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .object(let o): try c.encode(o)
        case .array(let a): try c.encode(a)
        case .null: try c.encodeNil()
        }
    }
}

enum APIDecoding {
    static var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    static var encoder: JSONEncoder {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }
}

enum ISODate {
    private static let plain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    private static let fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static func parse(_ s: String) -> Date? { plain.date(from: s) ?? fractional.date(from: s) }
}
