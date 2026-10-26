import SwiftUI

/// One video on Home's main screen: an item with a video, or a monitor hit the owner approved.
struct VideoTile: Identifiable, Hashable {
    var id: String
    var item: Item?
    var hit: PublishedHit?
    /// 1 (most important) ... 4.
    var level: Int
    /// Importance 0-1; orders tiles inside a section.
    var score: Double
    var cover: String?
    var date: String?
    var text: String
    /// What was heard in it.
    var audio: Audio
}

/// What sounds in a video. `heard`: the phrase spoken - its highlight's name (highlights are named
/// after what is said in them), a phrase the monitor matched, or for a found clip the words around
/// the match. Else the language spoken, the music, or none.
struct Audio: Hashable {
    enum Kind { case heard, speech, music, none }
    var kind: Kind
    var text: String
    var symbol: String { switch kind { case .music: "music.note"; case .none: "speaker.slash"; default: "waveform" } }

    static let names = ["uk": "Ukrainian", "ru": "Russian", "en": "English"]
    static func language(_ code: String?) -> String {
        guard let code, !code.isEmpty else { return "" }
        if code.count > 3 { return code.prefix(1).uppercased() + code.dropFirst() }
        return names[code] ?? Locale(identifier: "en").localizedString(forLanguageCode: code) ?? code
    }

    static func of(_ item: Item) -> Audio {
        var titles: [String] = []
        for h in item.highlights ?? [] { if let t = h.title?.trimmingCharacters(in: .whitespaces), !t.isEmpty, !titles.contains(t) { titles.append(t) } }
        if !titles.isEmpty { return Audio(kind: .heard, text: titles.joined(separator: " · ")) }
        let hits = item.detection?.hits ?? []
        var names: [String] = [], langs: [String] = []
        for h in hits where h.kind == "name" { if let p = h.phrase, !names.contains(p) { names.append(p) } }
        if !names.isEmpty { return Audio(kind: .heard, text: names.joined(separator: " · ")) }
        for h in hits where h.kind == "language" { let l = "\(language(h.lang)) speech"; if !langs.contains(l) { langs.append(l) } }
        if !langs.isEmpty { return Audio(kind: .speech, text: langs.joined(separator: " · ")) }
        if let s = item.analysis?.speech, let lang = s.language?.trimmingCharacters(in: .whitespaces), !(s.transcript ?? "").isEmpty,
           !["und", "unknown", "none", "n/a", "mul", "zxx"].contains(lang.lowercased()) {
            return Audio(kind: .speech, text: "\(language(lang.count <= 3 ? lang.lowercased() : lang)) speech")
        }
        if let m = item.music, let title = m.title { return Audio(kind: .music, text: [title, m.artist].compactMap { $0 }.joined(separator: " · ")) }
        if let m = item.analysis?.music, let first = m.split(whereSeparator: { $0 == ";" || $0 == "(" }).first {
            return Audio(kind: .music, text: first.trimmingCharacters(in: .whitespaces))
        }
        return Audio(kind: .none, text: "No speech detected")
    }
}

struct VideoSection: Identifiable, Hashable {
    var id: String
    var title: String
    var subtitle: String
    var tiles: [VideoTile]
    /// The best level among its videos.
    var level: Int
    var compact: Bool { level >= 3 }
}

/// Home's main screen, as on the web (web/src/videoSections.ts): every video (items with a video and
/// the approved monitor hits) in sections by subject - the AI facet that splits them best (themes),
/// then a second one (places) for the rest, then More videos. Importance orders sections and tiles
/// and sizes the tiles: the levels of CONTRACT.md "Home layout" (L1 largest), then `importance`.
/// Levels come from `/v1/layout`; without it they are derived the way the backend assigns them.
enum HomeSections {
    static let minTheme = 3

    /// A highlight is dedicated when it holds at most the median number of items (web/src/sections.ts).
    static func dedicated(_ highlights: [Highlight]) -> Set<String> {
        let counts = highlights.map(\.itemIds.count).sorted()
        guard !counts.isEmpty else { return [] }
        let mid = counts.count / 2
        let threshold = counts.count % 2 == 1 ? Double(counts[mid]) : Double(counts[mid - 1] + counts[mid]) / 2
        return Set(highlights.filter { Double($0.itemIds.count) <= threshold }.map(\.id))
    }

    static func level(of item: Item, highlights: [Highlight], dedicated: Set<String>) -> Int {
        if item.isRepost { return 3 }
        let mine = (item.highlights ?? []).map(\.id).filter { id in highlights.contains { $0.id == id } }
        if mine.isEmpty { return item.kind == .story ? 4 : 1 }
        return mine.contains(where: dedicated.contains) ? 1 : 2
    }

    /// Without a score from the backend: engagement, people and events, as the web estimates it.
    static func estimate(_ item: Item) -> Double {
        let c = item.counts
        let reach = Double(c?.likes ?? 0) + Double(c?.views ?? 0) / 10 + Double(c?.plays ?? 0) / 10
        let engagement = min(1, log10(1 + reach) / 5)
        let people = min(1, Double(item.analysis?.people?.count ?? 0) / 3)
        let events = min(1, Double(item.analysis?.events?.count ?? 0) / 4)
        return min(1, 0.35 + 0.35 * engagement + 0.15 * people + 0.15 * events)
    }

    /// The facet that groups these videos best: the most of them in categories of at least three, none over 60%.
    static func themeFacet(_ facets: [Facet], ids: Set<String>) -> Facet? {
        var best: Facet?, bestN = 0
        for f in facets {
            let sizes = f.categories.map { $0.itemIds.filter(ids.contains).count }
            let total = sizes.reduce(0, +)
            let big = sizes.filter { $0 >= minTheme }
            let n = big.reduce(0, +)
            if total > 0, Double(sizes.max() ?? 0) / Double(total) <= 0.6, big.count >= 2, n > bestN { best = f; bestN = n }
        }
        return best
    }

    static func build(items: [Item], highlights: [Highlight], hits: [PublishedHit], layout: [LayoutTile]?, facets: [Facet]?) -> [VideoSection] {
        let given = Dictionary((layout ?? []).map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        let dedicated = dedicated(highlights)
        var tiles: [VideoTile] = items.filter { $0.videoURL != nil }.map { it in
            let g = given[it.id]
            let lv = g?.level.flatMap { (1...4).contains($0) ? $0 : nil } ?? level(of: it, highlights: highlights, dedicated: dedicated)
            return VideoTile(id: it.id, item: it, level: lv, score: it.importance ?? g?.importance ?? estimate(it),
                             cover: (it.media.first ?? it.repostOf?.media?.first)?.poster, date: it.takenAt,
                             text: it.summary ?? it.description ?? it.caption ?? "", audio: Audio.of(it))
        }
        for h in hits where h.clip != nil || h.frame != nil || h.video?.thumbnail != nil {
            tiles.append(VideoTile(id: h.id, hit: h, level: given[h.id]?.level ?? h.level ?? 2, score: h.confidence ?? 0.5,
                                   cover: h.frame ?? h.video?.thumbnail, date: h.video?.postedAt ?? h.foundAt,
                                   text: h.title, audio: Audio(kind: .heard, text: h.heard)))
        }

        // Sections by subject: each video in the biggest category of the facet that splits them best;
        // the ones left go through the next facet; categories under three videos give theirs back.
        var groups: [(id: String, title: String, about: String?, tiles: [VideoTile])] = []
        var rest = tiles
        var pool = facets ?? []
        for _ in 0..<2 where rest.count >= minTheme {
            guard let facet = themeFacet(pool, ids: Set(rest.map(\.id))) else { break }
            let cats = facet.categories.map { ($0, Set($0.itemIds)) }
            var byCat: [String: [VideoTile]] = [:], left: [VideoTile] = []
            for t in rest {
                if let home = cats.filter({ $0.1.contains(t.id) }).max(by: { $0.0.count < $1.0.count }) { byCat[home.0.id, default: []].append(t) } else { left.append(t) }
            }
            for (c, _) in cats {
                guard let list = byCat[c.id] else { continue }
                if list.count >= minTheme { groups.append(("\(facet.id):\(c.id)", c.name, c.description, list)) } else { left += list }
            }
            rest = left
            pool.removeAll { $0.id == facet.id }
        }
        if !rest.isEmpty { groups.append(("more", groups.isEmpty ? "Videos" : "More videos", nil, rest)) }

        // The most important sections first: their best level, then their weight.
        let lw = [1, 0.5, 0.25, 0.125]
        func weight(_ l: [VideoTile]) -> Double { l.reduce(0) { $0 + lw[$1.level - 1] * (0.5 + $1.score) } }
        func best(_ l: [VideoTile]) -> Int { l.map(\.level).min() ?? 4 }
        return groups.sorted { a, b in
            let (ma, mb) = (a.id == "more", b.id == "more")
            if ma != mb { return mb }
            return best(a.tiles) != best(b.tiles) ? best(a.tiles) < best(b.tiles) : weight(a.tiles) > weight(b.tiles)
        }.map { g in
            let sorted = g.tiles.sorted { a, b in
                a.level != b.level ? a.level < b.level : a.score != b.score ? a.score > b.score : (a.date ?? "") > (b.date ?? "")
            }
            return VideoSection(id: g.id, title: g.title, subtitle: about(g.tiles, g.about), tiles: sorted, level: best(g.tiles))
        }
    }

    private static func about(_ list: [VideoTile], _ what: String?) -> String {
        let dates = list.compactMap { $0.date.flatMap(ISODate.parse) }.sorted()
        let fmt = Date.FormatStyle().month(.abbreviated).year()
        var span: String?
        if let a = dates.first, let b = dates.last {
            let (x, y) = (a.formatted(fmt), b.formatted(fmt))
            span = x == y ? x : "\(x) – \(y)"
        }
        return [what, "\(list.count) video\(list.count == 1 ? "" : "s")", span].compactMap { $0 }.joined(separator: " · ")
    }

    // MARK: - Layout

    enum Size { case xl, wide, m
        var cells: (w: Int, h: Int) { switch self { case .xl: (2, 2); case .wide: (2, 1); case .m: (1, 1) } }
    }

    /// A tile's footprint in a grid `cols` wide: the first section's L1 videos lead (on a phone the
    /// first fills the width); every other section opens with one large tile.
    static func size(_ t: VideoTile, rank: Int, count n: Int, cols: Int, lead: Bool) -> Size {
        if cols < 2 || t.level >= 3 { return .m }
        let heroes = max(1, cols / 4)
        if lead && t.level == 1 { return rank < heroes && n >= 3 ? .xl : rank < heroes + cols / 2 && n > cols ? .wide : .m }
        return rank == 0 && n >= 4 && cols >= 4 ? .xl : rank == 0 && n >= 2 ? .wide : .m
    }

    /// Columns for a grid `w` points wide on an `h` point screen: about 160-260 each (two thirds for
    /// the lower levels), at least two; rows 4:5 but at most 36% of the screen height.
    static func grid(width w: CGFloat, height h: CGFloat, compact: Bool, gap: CGFloat) -> (cols: Int, col: CGFloat, row: CGFloat) {
        let min = Swift.max(160, Swift.min(260, w / 7)) * (compact ? 0.68 : 1)
        let cols = Swift.max(2, Int((w + gap) / (min + gap)))
        let col = (w - gap * CGFloat(cols - 1)) / CGFloat(cols)
        return (cols, col, Swift.min(col * 1.25, Swift.max(140, h * (compact ? 0.26 : 0.36))))
    }

    /// Dense packing, as CSS grid's `dense` flow: each tile in the first free spot from the top left.
    static func pack(_ sizes: [Size], cols: Int) -> [(col: Int, row: Int)] {
        var used: [[Bool]] = []
        func free(_ r: Int, _ c: Int, _ w: Int, _ h: Int) -> Bool {
            guard c + w <= cols else { return false }
            for y in r..<(r + h) where y < used.count { for x in c..<(c + w) where used[y][x] { return false } }
            return true
        }
        return sizes.map { s in
            let (w, h) = (min(s.cells.w, cols), s.cells.h)
            var r = 0
            while true {
                for c in 0..<cols where free(r, c, w, h) {
                    while used.count < r + h { used.append(Array(repeating: false, count: cols)) }
                    for y in r..<(r + h) { for x in c..<(c + w) { used[y][x] = true } }
                    return (c, r)
                }
                r += 1
            }
        }
    }
}

/// The main screen: sections of videos with a title and a subtitle, laid out for the screen.
struct VideoSectionsView: View {
    let sections: [VideoSection]
    var onHit: (PublishedHit) -> Void
    @State private var open: Set<String> = []
    private let gap: CGFloat = 6

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width - 24
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 28) {
                    ForEach(Array(sections.enumerated()), id: \.element.id) { i, s in
                        section(s, lead: i == 0, width: width, height: geo.size.height)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.top, 8)
                .padding(.bottom, 40)
            }
        }
        .accessibilityIdentifier("videos")
    }

    @ViewBuilder private func section(_ s: VideoSection, lead: Bool, width: CGFloat, height: CGFloat) -> some View {
        let g = HomeSections.grid(width: width, height: height, compact: s.compact, gap: gap)
        let sized = s.tiles.enumerated().map { ($0.element, HomeSections.size($0.element, rank: $0.offset, count: s.tiles.count, cols: g.cols, lead: lead)) }
        // Each section shows its first rows (the first four, the others two, three on a phone) until opened.
        let budget = open.contains(s.id) ? Int.max : g.cols * (lead ? 4 : g.cols <= 2 ? 3 : 2)
        let shown = Self.within(sized, budget: budget)
        let spots = HomeSections.pack(shown.map(\.1), cols: g.cols)
        let rows = zip(shown, spots).map { $1.row + $0.1.cells.h }.max() ?? 0
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(s.title).font(s.level == 1 ? .title.bold() : .title2.bold())
                    .accessibilityAddTraits(.isHeader)
                Text(s.subtitle).font(.subheadline).foregroundStyle(.secondary)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("section.\(s.id)")
            ZStack(alignment: .topLeading) {
                ForEach(Array(zip(shown, spots).enumerated()), id: \.element.0.0.id) { _, pair in
                    let ((t, z), spot) = pair
                    let w = CGFloat(min(z.cells.w, g.cols)) * g.col + CGFloat(min(z.cells.w, g.cols) - 1) * gap
                    let h = CGFloat(z.cells.h) * g.row + CGFloat(z.cells.h - 1) * gap
                    tile(t, size: z, compact: s.compact)
                        .frame(width: w, height: h)
                        .offset(x: CGFloat(spot.col) * (g.col + gap), y: CGFloat(spot.row) * (g.row + gap))
                }
            }
            .frame(width: width, height: CGFloat(rows) * g.row + CGFloat(max(0, rows - 1)) * gap, alignment: .topLeading)
            if shown.count < s.tiles.count {
                Button("Show all \(s.tiles.count)") { open.insert(s.id) }
                    .buttonStyle(.bordered)
                    .frame(maxWidth: .infinity)
                    .accessibilityIdentifier("section.\(s.id).more")
            }
        }
    }

    private static func within(_ sized: [(VideoTile, HomeSections.Size)], budget: Int) -> [(VideoTile, HomeSections.Size)] {
        var used = 0
        return sized.filter { used += $0.1.cells.w * $0.1.cells.h; return used <= budget }
    }

    @ViewBuilder private func tile(_ t: VideoTile, size: HomeSections.Size, compact: Bool) -> some View {
        let card = VideoCard(tile: t, size: size, compact: compact)
        if let item = t.item {
            NavigationLink(value: Route.item(item)) { card }
                .buttonStyle(.plain)
                .accessibilityIdentifier("video.\(t.id)")
        } else if let hit = t.hit {
            Button { onHit(hit) } label: { card }
                .buttonStyle(.plain)
                .accessibilityIdentifier("video.\(t.id)")
        }
    }
}

struct VideoCard: View {
    let tile: VideoTile
    let size: HomeSections.Size
    let compact: Bool

    var body: some View {
        Color.clear
            .overlay { RemoteImage(tile.cover) }
            .overlay(alignment: .bottomLeading) { caption }
            .overlay(alignment: .topLeading) { audioChip }
            .overlay(alignment: .topTrailing) {
                if tile.hit != nil {
                    Text("AI").font(.caption2.weight(.heavy)).padding(.horizontal, 7).padding(.vertical, 2)
                        .background(Color.orange, in: Capsule()).foregroundStyle(.black).padding(6)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: size == .xl ? 14 : 10, style: .continuous))
            .contentShape(Rectangle())
            .accessibilityElement(children: .ignore)
            .accessibilityLabel([tile.hit != nil ? "Found by AI" : nil, tile.text, "Audio: \(tile.audio.text)", tile.date.flatMap(ISODate.parse)?.formatted(date: .long, time: .omitted)].compactMap { $0 }.joined(separator: ", "))
            .accessibilityAddTraits(.isButton)
    }

    /// The audio detected, top left; a match by the monitor stands out.
    private var audioChip: some View {
        let detected = tile.audio.kind == .heard
        return Group {
            if detected { Text("“\(tile.audio.text)”").bold() } else { Label(tile.audio.text, systemImage: tile.audio.symbol) }
        }
            .font(size == .xl ? .footnote.weight(.semibold) : .caption2.weight(.semibold))
            .lineLimit(1)
            .padding(.horizontal, 8).padding(.vertical, 3)
            .foregroundStyle(detected ? .black : .white)
            .background(detected ? AnyShapeStyle(Color.orange) : AnyShapeStyle(.black.opacity(0.55)), in: Capsule())
            .opacity(tile.audio.kind == .none ? 0.75 : 1)
            .padding(size == .xl ? 10 : 6)
            .padding(.trailing, tile.hit != nil ? 30 : 0)
            .accessibilityIdentifier("audio.\(tile.id)")
    }

    private var caption: some View {
        VStack(alignment: .leading, spacing: 2) {
            if let d = tile.date.flatMap(ISODate.parse) {
                Text(d.formatted(date: .abbreviated, time: .omitted)).font(size == .xl ? .footnote.bold() : .caption.bold()).opacity(0.9)
            }
        }
        .foregroundStyle(.white)
        .padding(.horizontal, size == .xl ? 14 : compact ? 7 : 10)
        .padding(.bottom, size == .xl ? 12 : compact ? 6 : 8)
        .padding(.top, size == .xl ? 30 : 20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(LinearGradient(colors: [.clear, .black.opacity(0.78)], startPoint: .top, endPoint: .bottom))
    }
}
