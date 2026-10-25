import XCTest
@testable import Earth_Empire

struct Thing: Identifiable, Sendable, Equatable { let id: Int }

/// A fake cursor API: `pages[cursor]` answers each call, and the calls are recorded.
actor FakePages {
    var pages: [String: ([Thing], String?)] = [:]
    var calls: [String?] = []
    var failNext = false
    var delay: UInt64 = 0

    init(_ pages: [String: ([Thing], String?)]) { self.pages = pages }

    func set(_ key: String, _ value: ([Thing], String?)) { pages[key] = value }
    func failOnce() { failNext = true }
    func setDelay(_ ms: UInt64) { delay = ms }

    func fetch(_ cursor: String?) async throws -> (items: [Thing], next: String?) {
        calls.append(cursor)
        if delay > 0 { try await Task.sleep(nanoseconds: delay * 1_000_000) }
        if failNext { failNext = false; throw URLError(.notConnectedToInternet) }
        let p = pages[cursor ?? "first"] ?? ([], nil)
        return (p.0, p.1)
    }
}

@MainActor
final class PagerTests: XCTestCase {
    private func things(_ r: ClosedRange<Int>) -> [Thing] { r.map(Thing.init) }

    func testPagesFollowCursorsUntilNextIsNull() async {
        let fake = FakePages(["first": (things(1...3), "c1"), "c1": (things(4...6), "c2"), "c2": (things(7...7), nil)])
        let pager = Pager<Thing> { try await fake.fetch($0) }
        await pager.loadIfNeeded()
        XCTAssertEqual(pager.items.map(\.id), [1, 2, 3])
        XCTAssertFalse(pager.reachedEnd)
        await pager.loadMore()
        await pager.loadMore()
        XCTAssertEqual(pager.items.map(\.id), Array(1...7))
        XCTAssertTrue(pager.reachedEnd)
        await pager.loadMore() // nothing more to ask for
        let calls = await fake.calls
        XCTAssertEqual(calls, [nil, "c1", "c2"])
    }

    func testLoadIfNeededLoadsOnce() async {
        let fake = FakePages(["first": (things(1...2), "c1")])
        let pager = Pager<Thing> { try await fake.fetch($0) }
        await pager.loadIfNeeded()
        await pager.loadIfNeeded()
        let calls = await fake.calls
        XCTAssertEqual(calls.count, 1)
    }

    func testDuplicatesAcrossPagesAreDropped() async {
        // New items arrived at the top between the two calls, so page two repeats item 3.
        let fake = FakePages(["first": (things(1...3), "c1"), "c1": (things(3...5), nil)])
        let pager = Pager<Thing> { try await fake.fetch($0) }
        await pager.loadMore()
        await pager.loadMore()
        XCTAssertEqual(pager.items.map(\.id), [1, 2, 3, 4, 5])
    }

    func testConcurrentLoadsAreCoalesced() async {
        let fake = FakePages(["first": (things(1...3), "c1"), "c1": (things(4...6), nil)])
        await fake.setDelay(50)
        let pager = Pager<Thing> { try await fake.fetch($0) }
        async let a: () = pager.loadMore()
        async let b: () = pager.loadMore()
        _ = await (a, b)
        let calls = await fake.calls
        XCTAssertEqual(calls, [nil])
        XCTAssertEqual(pager.items.map(\.id), [1, 2, 3])
    }

    func testFailureKeepsItemsAndRetryResumesAtTheSameCursor() async {
        let fake = FakePages(["first": (things(1...3), "c1"), "c1": (things(4...6), nil)])
        let pager = Pager<Thing> { try await fake.fetch($0) }
        await pager.loadMore()
        await fake.failOnce()
        await pager.loadMore()
        XCTAssertNotNil(pager.error)
        XCTAssertEqual(pager.items.map(\.id), [1, 2, 3])
        XCTAssertFalse(pager.reachedEnd)
        await pager.loadMore()
        XCTAssertNil(pager.error)
        XCTAssertEqual(pager.items.map(\.id), Array(1...6))
        let calls = await fake.calls
        XCTAssertEqual(calls, [nil, "c1", "c1"])
    }

    func testRefreshReplacesTheListFromTheTop() async {
        let fake = FakePages(["first": (things(1...3), "c1"), "c1": (things(4...6), nil)])
        let pager = Pager<Thing> { try await fake.fetch($0) }
        await pager.loadMore()
        await pager.loadMore()
        XCTAssertTrue(pager.reachedEnd)
        await fake.set("first", ([Thing(id: 0)] + things(1...2), "c0"))
        await pager.refresh()
        XCTAssertEqual(pager.items.map(\.id), [0, 1, 2])
        XCTAssertFalse(pager.reachedEnd)
        XCTAssertEqual(pager.next, "c0")
    }

    func testFailedRefreshKeepsWhatWasShown() async {
        let fake = FakePages(["first": (things(1...3), nil)])
        let pager = Pager<Thing> { try await fake.fetch($0) }
        await pager.loadMore()
        await fake.failOnce()
        await pager.refresh()
        XCTAssertEqual(pager.items.map(\.id), [1, 2, 3])
        XCTAssertNotNil(pager.error)
    }

    func testEmptyFirstPage() async {
        let fake = FakePages([:])
        let pager = Pager<Thing> { try await fake.fetch($0) }
        await pager.loadIfNeeded()
        XCTAssertTrue(pager.loadedOnce)
        XCTAssertTrue(pager.items.isEmpty)
        XCTAssertTrue(pager.reachedEnd)
    }

    /// The sample API pages and filters like the live one: walking every page of the archive
    /// gives each item once, newest first.
    func testSampleAPIPagesThroughTheFixture() async throws {
        let api = try SampleAPI.bundled()
        api.latency = 0
        let pager = Pager<Item>.items(api, ItemQuery(), pageSize: 4)
        await pager.loadMore()
        XCTAssertEqual(pager.items.count, 4)
        while !pager.reachedEnd { await pager.loadMore() }
        XCTAssertEqual(pager.items.count, api.fixture.items.count)
        XCTAssertEqual(Set(pager.items.map(\.id)).count, pager.items.count)
        let dates = pager.items.compactMap(\.takenAt)
        XCTAssertEqual(dates, dates.sorted(by: >))

        let reels = try await api.items(ItemQuery(kind: .reel), before: nil, limit: 50)
        XCTAssertTrue(reels.items.allSatisfy { $0.kind == .reel })
        XCTAssertFalse(reels.items.isEmpty)
        let food = try await api.items(ItemQuery(category: "food"), before: nil, limit: 50)
        XCTAssertTrue(food.items.allSatisfy { $0.categories?.contains("food") == true })
        let search = try await api.items(ItemQuery(q: "varenyky"), before: nil, limit: 50)
        XCTAssertEqual(search.items.count, 1)
        let byPerson = try await api.items(ItemQuery(q: "marta"), before: nil, limit: 50)
        XCTAssertFalse(byPerson.items.isEmpty)
    }

    func testStoryOrderFollowsTheHighlight() throws {
        let api = try SampleAPI.bundled()
        let h = try XCTUnwrap(api.fixture.highlights.first { $0.itemIds.count > 1 })
        let items = api.fixture.items.filter { i in h.itemIds.contains(i.id) }
        XCTAssertEqual(StoryViewer.order(items.shuffled(), by: h.itemIds).map(\.id), h.itemIds)
    }
}

final class DeepLinkTests: XCTestCase {
    private func parse(_ s: String) -> DeepLink? { DeepLink.parse(URL(string: s)!) }

    func testSiteRoutes() {
        XCTAssertEqual(parse("https://empire.earth/"), .home)
        XCTAssertEqual(parse("https://empire.earth"), .home)
        XCTAssertEqual(parse("https://empire.earth/item/ig_123"), .item("ig_123"))
        XCTAssertEqual(parse("https://www.empire.earth/p/ig_123"), .item("ig_123"))
        XCTAssertEqual(parse("https://empire.earth/reel/123"), .item("ig_123"))
        XCTAssertEqual(parse("https://empire.earth/category/travel"), .category("travel"))
        XCTAssertEqual(parse("https://empire.earth/categories"), .categories)
        XCTAssertEqual(parse("https://empire.earth/highlight/hl_1"), .highlight("hl_1", item: nil))
        XCTAssertEqual(parse("https://empire.earth/highlight/hl_1/ig_5"), .highlight("hl_1", item: "ig_5"))
        XCTAssertEqual(parse("https://empire.earth/stories/highlights/hl_1"), .highlight("hl_1", item: nil))
        XCTAssertEqual(parse("https://empire.earth/highlight/hl_1?item=ig_5"), .highlight("hl_1", item: "ig_5"))
        XCTAssertEqual(parse("https://empire.earth/search?q=surf"), .grid(ItemQuery(q: "surf")))
        XCTAssertEqual(parse("https://empire.earth/?q=lisbon"), .grid(ItemQuery(q: "lisbon")))
        XCTAssertEqual(parse("https://empire.earth/?kind=reel&category=food"), .grid(ItemQuery(kind: .reel, category: "food")))
        XCTAssertEqual(parse("https://empire.earth/?q="), .home)
        XCTAssertEqual(parse("https://empire.earth/#/item/ig_7"), .item("ig_7"))
    }

    func testAppSchemeAndForeignHosts() {
        XCTAssertEqual(parse("earthempire://item/ig_1"), .item("ig_1"))
        XCTAssertEqual(parse("earthempire://highlight/hl_2"), .highlight("hl_2", item: nil))
        XCTAssertEqual(parse("earthempire://category/food"), .category("food"))
        XCTAssertNil(parse("https://example.com/item/ig_1"))
        XCTAssertNil(parse("https://empire.earth/unknown/thing"))
    }

    func testShareURLsRoundTrip() {
        XCTAssertEqual(DeepLink.parse(DeepLink.webURL(item: "ig_1")), .item("ig_1"))
        XCTAssertEqual(DeepLink.parse(DeepLink.webURL(category: "food")), .category("food"))
        XCTAssertEqual(DeepLink.parse(DeepLink.webURL(highlight: "hl_1")), .highlight("hl_1", item: nil))
        XCTAssertEqual(DeepLink.parse(DeepLink.webURL(highlight: "hl_1", item: "ig_2")), .highlight("hl_1", item: "ig_2"))
    }
}
