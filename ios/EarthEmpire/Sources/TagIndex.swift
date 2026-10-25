import Foundation

/// The tag cloud computed on the device, the same way the backend builds `GET /v1/tags`
/// (backend/ee/analysis.py `tags_for`): lowercase tags from the categories, the analysis and the
/// caption, people only when the post itself named them. Used by the sample data and by a
/// backend without `/v1/tags`.
enum TagIndex {
    struct Entry: Hashable { var tag: String; var kind: String }

    static let namingBases: Set<String> = ["tag", "mention", "caption"]

    static func normalize(_ s: String) -> String {
        var v = s.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        while v.hasPrefix("#") { v.removeFirst() }
        return String(v.split(whereSeparator: \.isWhitespace).joined(separator: " ").prefix(60))
    }

    static func tags(for item: Item) -> Set<Entry> {
        var out = Set<Entry>()
        func add(_ value: String?, _ kind: String) {
            guard let value else { return }
            let v = normalize(value)
            if v.count > 1 { out.insert(Entry(tag: v, kind: kind)) }
        }
        let a = item.analysis
        for c in item.categories ?? [] { add(c, "category") }
        for k in a?.keywords ?? [] { add(k, "keyword") }
        for o in a?.objects ?? [] { add(o, "object") }
        for o in a?.animals ?? [] { add(o, "animal") }
        for o in a?.brands ?? [] { add(o, "brand") }
        add(a?.place?.place, "place")
        add(a?.place?.country, "country")
        add(item.location?.name, "place")
        for h in item.hashtags ?? [] { add(h, "hashtag") }
        for p in a?.people ?? [] where p.who != nil && namingBases.contains(p.basis ?? "") { add(p.who, "person") }
        add(a?.mood, "mood")
        add(a?.time?.occasion, "occasion")
        return out
    }

    /// Every tag with the number of items that have it, most common first.
    static func cloud(_ items: [Item]) -> [Tag] {
        var counts: [Entry: Int] = [:]
        for item in items { for e in tags(for: item) { counts[e, default: 0] += 1 } }
        return counts.map { Tag(tag: $0.key.tag, kind: $0.key.kind, count: $0.value) }
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.tag < $1.tag }
    }
}
