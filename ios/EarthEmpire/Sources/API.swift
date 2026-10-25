import Foundation
import OSLog

let log = Logger(subsystem: "com.oeaio.earthempire", category: "app")

/// What the grid asks the API for (`GET /v1/items?kind=&category=&highlight=&q=`).
struct ItemQuery: Hashable, Sendable {
    var kind: ItemKind?
    var category: String?
    var highlight: String?
    /// A tag from the cloud (`tag=`, any kind, case-insensitive).
    var tag: String?
    var q: String?

    var isEmpty: Bool { kind == nil && category == nil && highlight == nil && tag == nil && (q ?? "").isEmpty }
}

/// The public read API of CONTRACT.md. Two implementations: `LiveAPI` over HTTP, `SampleAPI` over
/// the bundled fixture.
protocol ArchiveAPI: Sendable {
    func profile() async throws -> Profile
    func items(_ query: ItemQuery, before: String?, limit: Int) async throws -> ItemPage
    func item(id: String) async throws -> Item
    func highlights() async throws -> [Highlight]
    func categories() async throws -> [Category]
    /// The tag cloud, by count.
    func tags(limit: Int) async throws -> [Tag]
}

enum APIError: LocalizedError {
    case status(Int, String)
    case notFound(String)

    var errorDescription: String? {
        switch self {
        case .status(let code, let path): "The archive answered \(code) for \(path)."
        case .notFound(let what): "\(what) is not in the archive."
        }
    }
}

/// `https://api.empire.earth/v1/...`, or whatever base the settings name (the backend's AWS
/// hostname before DNS moves).
///
/// Offline: every successful response is kept on disk under its URL, and every item it carried
/// under the item's id; when the network fails, those answer instead, so anything already seen
/// still opens.
final class LiveAPI: ArchiveAPI, @unchecked Sendable {
    let base: URL
    private let session: URLSession
    private let cache: ResponseCache

    init(base: URL, session: URLSession = .shared, cache: ResponseCache = .shared) {
        self.base = base
        self.session = session
        self.cache = cache
    }

    func profile() async throws -> Profile {
        try await get("v1/profile")
    }

    func items(_ query: ItemQuery, before: String?, limit: Int) async throws -> ItemPage {
        var q: [URLQueryItem] = []
        if let k = query.kind { q.append(.init(name: "kind", value: k.rawValue)) }
        if let c = query.category { q.append(.init(name: "category", value: c)) }
        if let h = query.highlight { q.append(.init(name: "highlight", value: h)) }
        if let t = query.tag { q.append(.init(name: "tag", value: t)) }
        if let s = query.q, !s.isEmpty { q.append(.init(name: "q", value: s)) }
        if let b = before { q.append(.init(name: "before", value: b)) }
        q.append(.init(name: "limit", value: String(limit)))
        let page: ItemPage = try await get("v1/items", query: q)
        cache.store(items: page.items)
        return page
    }

    func item(id: String) async throws -> Item {
        do {
            let item: Item = try await get("v1/items/\(id)")
            cache.store(items: [item])
            return item
        } catch {
            if let item = cache.item(id: id) { return item }
            throw error
        }
    }

    func highlights() async throws -> [Highlight] {
        let list: HighlightList = try await get("v1/highlights")
        return list.highlights
    }

    func categories() async throws -> [Category] {
        let list: CategoryList = try await get("v1/categories")
        return list.categories
    }

    /// `GET /v1/tags`; where the backend has none yet (404), the cloud is computed here from the
    /// newest items.
    func tags(limit: Int) async throws -> [Tag] {
        do {
            let list: TagList = try await get("v1/tags", query: [.init(name: "limit", value: String(limit))])
            return list.tags
        } catch APIError.notFound {
            log.notice("no /v1/tags: computing tags from items")
            var items: [Item] = []
            var cursor: String?
            repeat {
                let page = try await self.items(ItemQuery(), before: cursor, limit: 100)
                items += page.items
                cursor = page.next
            } while cursor != nil && items.count < 1000
            return Array(TagIndex.cloud(items).prefix(limit))
        }
    }

    func url(_ path: String, query: [URLQueryItem] = []) -> URL {
        var c = URLComponents(url: base.appending(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { c.queryItems = query }
        return c.url!
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        let url = url(path, query: query)
        do {
            var request = URLRequest(url: url, timeoutInterval: 20)
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            let (data, response) = try await session.data(for: request)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard (200..<300).contains(code) else {
                log.error("GET \(url.absoluteString, privacy: .public) -> \(code)")
                if code == 404 { throw APIError.notFound(path) }
                throw APIError.status(code, path)
            }
            let value = try APIDecoding.decoder.decode(T.self, from: data)
            cache.store(data, for: url)
            if OfflineState.shared.isOffline { OfflineState.shared.markOnline() }
            return value
        } catch let error as URLError {
            log.error("GET \(url.absoluteString, privacy: .public) failed: \(error.localizedDescription, privacy: .public); trying the cache")
            if let data = cache.data(for: url), let value = try? APIDecoding.decoder.decode(T.self, from: data) {
                OfflineState.shared.markOffline()
                return value
            }
            throw error
        }
    }
}

/// Raw API responses and single items on disk, for offline use.
final class ResponseCache: @unchecked Sendable {
    static let shared = ResponseCache()
    let root: URL
    private let fm = FileManager.default

    init(root: URL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appending(path: "api")) {
        self.root = root
        try? fm.createDirectory(at: root.appending(path: "responses"), withIntermediateDirectories: true)
        try? fm.createDirectory(at: root.appending(path: "items"), withIntermediateDirectories: true)
    }

    private func file(for url: URL) -> URL {
        root.appending(path: "responses").appending(path: Hashing.sha256(url.absoluteString) + ".json")
    }

    private func file(item id: String) -> URL {
        root.appending(path: "items").appending(path: Hashing.safeName(id) + ".json")
    }

    func store(_ data: Data, for url: URL) { try? data.write(to: file(for: url), options: .atomic) }
    func data(for url: URL) -> Data? { try? Data(contentsOf: file(for: url)) }

    func store(items: [Item]) {
        let encoder = APIDecoding.encoder
        for item in items {
            if let data = try? encoder.encode(item) { try? data.write(to: file(item: item.id), options: .atomic) }
        }
    }

    func item(id: String) -> Item? {
        guard let data = try? Data(contentsOf: file(item: id)) else { return nil }
        return try? APIDecoding.decoder.decode(Item.self, from: data)
    }

    func clear() {
        try? fm.removeItem(at: root)
        try? fm.createDirectory(at: root.appending(path: "responses"), withIntermediateDirectories: true)
        try? fm.createDirectory(at: root.appending(path: "items"), withIntermediateDirectories: true)
    }
}

/// Whether the last answer came from the disk cache rather than the network.
@Observable
final class OfflineState: @unchecked Sendable {
    static let shared = OfflineState()
    private(set) var isOffline = false

    func markOffline() { Task { @MainActor in self.isOffline = true } }
    func markOnline() { Task { @MainActor in self.isOffline = false } }
}

/// The bundled development fixture (`Fixture/fixture.json`, the shapes of CONTRACT.md), served
/// with the API's own filtering and cursor paging so the app behaves as it will on the live API.
final class SampleAPI: ArchiveAPI, @unchecked Sendable {
    struct Fixture: Codable {
        var profile: Profile
        var highlights: [Highlight]
        var categories: [Category]
        var items: [Item]
    }

    let fixture: Fixture
    /// Milliseconds each call waits, so loading states are visible as on a network.
    var latency: UInt64 = 150

    init(data: Data) throws {
        fixture = try APIDecoding.decoder.decode(Fixture.self, from: data)
    }

    static func bundled() throws -> SampleAPI {
        guard let url = Bundle.main.url(forResource: "fixture", withExtension: "json", subdirectory: "Fixture") else {
            throw APIError.notFound("The sample fixture")
        }
        return try SampleAPI(data: Data(contentsOf: url))
    }

    private func wait() async { try? await Task.sleep(nanoseconds: latency * 1_000_000) }

    func profile() async throws -> Profile { await wait(); return fixture.profile }
    func highlights() async throws -> [Highlight] { await wait(); return fixture.highlights }
    func categories() async throws -> [Category] { await wait(); return fixture.categories }
    func tags(limit: Int) async throws -> [Tag] { await wait(); return Array(TagIndex.cloud(fixture.items).prefix(limit)) }

    func item(id: String) async throws -> Item {
        await wait()
        guard let item = fixture.items.first(where: { $0.id == id }) else { throw APIError.notFound("Item \(id)") }
        return item
    }

    func items(_ query: ItemQuery, before: String?, limit: Int) async throws -> ItemPage {
        await wait()
        return Self.page(fixture.items, query: query, before: before, limit: limit)
    }

    /// Newest first; `before` is the id of the last item of the previous page.
    static func page(_ all: [Item], query: ItemQuery, before: String?, limit: Int) -> ItemPage {
        var list = all.sorted { ($0.takenAt ?? "") > ($1.takenAt ?? "") }.filter { matches($0, query) }
        if let before, let i = list.firstIndex(where: { $0.id == before }) {
            list = Array(list[(i + 1)...])
        }
        let page = Array(list.prefix(max(1, limit)))
        let next = list.count > page.count ? page.last?.id : nil
        return ItemPage(items: page, next: next)
    }

    static func matches(_ item: Item, _ query: ItemQuery) -> Bool {
        if let k = query.kind, item.kind != k { return false }
        if let c = query.category, !(item.categories ?? []).contains(c) { return false }
        if let h = query.highlight, !(item.highlights ?? []).contains(where: { $0.id == h }) { return false }
        if let t = query.tag, !TagIndex.tags(for: item).contains(where: { $0.tag == TagIndex.normalize(t) }) { return false }
        if let q = query.q?.trimmingCharacters(in: .whitespaces).lowercased(), !q.isEmpty {
            let a = item.analysis
            let haystack: [String?] = [
                item.caption, item.summary, item.description, item.location?.name, a?.what, a?.context,
                a?.place?.place, a?.speech?.transcript, item.repostOf?.author, item.repostOf?.caption,
            ]
            let lists: [[String]?] = [item.hashtags, item.highlights?.compactMap(\.title), a?.keywords,
                                      a?.objects, a?.people?.compactMap(\.who), item.categories]
            let text = (haystack.compactMap { $0 } + lists.compactMap { $0 }.flatMap { $0 }).joined(separator: "\n").lowercased()
            return text.contains(q)
        }
        return true
    }
}
