import Foundation
import Observation

/// Cursor paging over `GET /v1/items` (or anything shaped like it): `{"items": [...], "next":
/// cursor | null}`, the cursor going back as `before`.
///
/// - one load at a time; a load asked for while one runs is dropped;
/// - items already shown are not repeated if a later page carries them again (new items arrived
///   at the top meanwhile);
/// - `refresh()` starts over from the newest, and its answer replaces the list only when it
///   arrives, so pull-to-refresh never blanks the grid;
/// - a failed load keeps what was shown and records the error; `loadMore()` retries.
@MainActor
@Observable
final class Pager<Element: Identifiable & Sendable> where Element.ID: Sendable {
    typealias Fetch = @Sendable (_ cursor: String?) async throws -> (items: [Element], next: String?)

    private(set) var items: [Element] = []
    private(set) var next: String?
    private(set) var isLoading = false
    private(set) var reachedEnd = false
    private(set) var error: Error?
    private(set) var loadedOnce = false

    private let fetch: Fetch
    private var generation = 0

    init(fetch: @escaping Fetch) {
        self.fetch = fetch
    }

    var canLoadMore: Bool { !reachedEnd && !isLoading }

    /// The first page, if nothing is loaded yet.
    func loadIfNeeded() async {
        guard !loadedOnce, !isLoading else { return }
        await loadMore()
    }

    func loadMore() async {
        guard canLoadMore else { return }
        isLoading = true
        let gen = generation
        let cursor = loadedOnce ? next : nil
        do {
            let page = try await fetch(cursor)
            guard gen == generation else { return }
            append(page.items)
            next = page.next
            reachedEnd = page.next == nil
            error = nil
        } catch {
            guard gen == generation else { return }
            if !(error is CancellationError) { self.error = error }
        }
        loadedOnce = true
        isLoading = false
    }

    /// Loads the first page again and replaces the list with it.
    func refresh() async {
        generation += 1
        let gen = generation
        isLoading = true
        do {
            let page = try await fetch(nil)
            guard gen == generation else { return }
            items = []
            append(page.items)
            next = page.next
            reachedEnd = page.next == nil
            error = nil
        } catch {
            guard gen == generation else { return }
            if !(error is CancellationError) { self.error = error }
        }
        loadedOnce = true
        isLoading = false
    }

    /// Call as each element appears: loads the next page when the end comes near.
    func onAppear(_ element: Element, threshold: Int = 6) {
        guard canLoadMore, let i = items.firstIndex(where: { $0.id == element.id }),
              i >= items.count - threshold else { return }
        Task { await loadMore() }
    }

    private func append(_ new: [Element]) {
        var seen = Set(items.map(\.id))
        for e in new where seen.insert(e.id).inserted { items.append(e) }
    }
}

extension Pager where Element == Item {
    /// A pager over the archive's items for one query.
    static func items(_ api: ArchiveAPI, _ query: ItemQuery, pageSize: Int = 24) -> Pager<Item> {
        Pager { cursor in
            let page = try await api.items(query, before: cursor, limit: pageSize)
            return (page.items, page.next)
        }
    }
}
