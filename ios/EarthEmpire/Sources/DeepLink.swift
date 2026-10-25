import Foundation

/// A place in the archive, from an empire.earth URL (Universal Link) or an `earthempire://` one.
///
/// The paths are the site's routes (web/src/main.tsx):
///   /                          the profile; `?q=`, `?kind=`, `?category=` filter its grid
///   /item/<id>                 an item (also /i/<id>, /items/<id>, /p/<id>, /reel/<id>)
///   /category/<slug>           a category (also /c/<slug>, /categories/<slug>)
///   /highlight/<id>?item=<id>  a highlight in the story viewer, at one story (also /highlight/<id>/<item>)
/// plus /categories (every category) and /search?q=…, which the app alone has.
/// `earthempire://item/<id>` and the like take the same paths with the first one as the host.
enum DeepLink: Equatable {
    case home
    case item(String)
    case category(String)
    case categories
    case highlight(String, item: String?)
    /// The home grid with filters (`/?q=…&kind=…&category=…`).
    case grid(ItemQuery)

    static func parse(_ url: URL) -> DeepLink? {
        var parts = url.pathComponents.filter { $0 != "/" && !$0.isEmpty }
        if url.scheme == "earthempire", let host = url.host, !host.isEmpty {
            parts.insert(host, at: 0)
        } else if let host = url.host?.lowercased(), url.scheme?.hasPrefix("http") == true {
            guard host == "empire.earth" || host.hasSuffix(".empire.earth") || host.hasSuffix("cloudfront.net")
                    || host == "localhost" else { return nil }
        } else if url.scheme != "earthempire" {
            return nil
        }
        // A hash route (`/#/item/x`) reads like a path.
        if let fragment = url.fragment, fragment.hasPrefix("/") {
            parts += fragment.split(separator: "/").map(String.init)
        }
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func param(_ name: String) -> String? {
            query.first(where: { $0.name == name })?.value.flatMap { $0.isEmpty ? nil : $0 }
        }
        let q = param("q")

        guard let first = parts.first?.lowercased() else {
            let grid = ItemQuery(kind: param("kind").flatMap(ItemKind.init(rawValue:)), category: param("category"), q: q)
            return grid.isEmpty ? .home : .grid(grid)
        }
        let second = parts.count > 1 ? parts[1] : nil
        switch first {
        case "item", "items", "i", "p", "reel", "reels", "post", "tv":
            return second.map { .item(normalizeItemID($0)) }
        case "category", "categories", "c":
            if let second { return .category(second) }
            return .categories
        case "highlight", "highlights", "h":
            let item = parts.count > 2 ? parts[2] : param("item")
            return second.map { .highlight($0, item: item.map(normalizeItemID)) }
        case "stories":
            if second == "highlights", parts.count > 2 { return .highlight(parts[2], item: nil) }
            return second.map { .item(normalizeItemID($0)) }
        case "search":
            return .grid(ItemQuery(q: q ?? second ?? ""))
        default:
            return nil
        }
    }

    /// Item ids are `ig_<pk>`; a bare pk gets the prefix.
    static func normalizeItemID(_ s: String) -> String {
        s.allSatisfy(\.isNumber) ? "ig_" + s : s
    }

    /// The site URL for an item, for sharing.
    static func webURL(item id: String) -> URL { AppConfig.site.appending(path: "item").appending(path: id) }
    static func webURL(category slug: String) -> URL { AppConfig.site.appending(path: "category").appending(path: slug) }
    static func webURL(highlight id: String, item: String? = nil) -> URL {
        let url = AppConfig.site.appending(path: "highlight").appending(path: id)
        return item.map { url.appending(queryItems: [URLQueryItem(name: "item", value: $0)]) } ?? url
    }
}
