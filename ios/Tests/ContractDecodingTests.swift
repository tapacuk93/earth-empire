import XCTest
@testable import Earth_Empire

/// The shapes of CONTRACT.md, as the API will send them.
final class ContractDecodingTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try APIDecoding.decoder.decode(T.self, from: Data(json.utf8))
    }

    func testFullItemFromContract() throws {
        let item = try decode(Item.self, """
        {
          "id": "ig_3400000000000000012", "kind": "reel", "shortcode": "DQs1rFa",
          "source_url": "https://www.instagram.com/reel/DQs1rFa/",
          "taken_at": "2024-05-01T12:00:00Z", "caption": "Dawn #surf with @marta",
          "hashtags": ["surf"], "mentions": ["marta"],
          "tagged_users": [{"username": "marta", "x": 0.5, "y": 0.3}],
          "location": {"name": "Ericeira", "id": "1", "lat": 38.9, "lng": -9.4},
          "music": {"title": "Song", "artist": "Band"},
          "alt_text": null,
          "stickers": [{"type": "poll", "text": "Yes?", "extra": {"options": ["a", "b"], "n": 2}}],
          "counts": {"likes": 10, "plays": 300},
          "media": [{"type": "video", "url": "https://media.empire.earth/items/x/0.mp4",
                     "thumbnail": "https://media.empire.earth/items/x/0.thumb.jpg",
                     "width": 1080, "height": 1920, "duration": 12.3}],
          "highlights": [{"id": "hl_1", "title": "Travel"}],
          "repost_of": null,
          "categories": ["surf", "travel"], "summary": "One sentence.",
          "analysis": {
            "people": [{"who": "@marta", "description": "surfer", "basis": "tag", "role": "surfer",
                        "appears": [{"media": 0, "from": 1.5, "to": 8.0}]},
                       {"who": null, "description": "a lifeguard", "basis": "description only", "role": null, "appears": []}],
            "what": "Surfing.",
            "events": [{"media": 0, "at": 3.2, "text": "Wave"}],
            "when": {"date": "2024-05-01", "time_of_day": "dawn", "season": "spring", "occasion": null, "basis": "taken_at"},
            "where": {"place": "Ribeira d'Ilhas", "kind": "beach", "country": "Portugal", "basis": "location"},
            "objects": ["board"], "animals": [], "brands": [], "on_screen_text": ["Ericeira"],
            "speech": {"language": "en", "transcript": "Go go go"},
            "music": null, "mood": "joyful", "language": "en", "context": "Series.",
            "keywords": ["surf"], "model": "claude", "analyzed_at": "2024-05-02T00:00:00Z"
          },
          "extra": {"anything": [1, "two", true, null]},
          "collected_at": "2024-05-01T13:00:00Z", "updated_at": "2024-05-02T00:00:00Z"
        }
        """)
        XCTAssertEqual(item.kind, .reel)
        XCTAssertEqual(item.sourceUrl, "https://www.instagram.com/reel/DQs1rFa/")
        XCTAssertEqual(item.taggedUsers?.first?.x, 0.5)
        XCTAssertEqual(item.media.first?.type, .video)
        XCTAssertEqual(item.media.first?.duration, 12.3)
        XCTAssertEqual(item.media.first?.aspectRatio ?? 0, 1080.0 / 1920.0, accuracy: 0.001)
        XCTAssertEqual(item.counts?.plays, 300)
        XCTAssertNil(item.counts?.views)
        XCTAssertNil(item.repostOf)
        XCTAssertEqual(item.highlights?.first?.title, "Travel")
        XCTAssertEqual(item.takenDate, ISODate.parse("2024-05-01T12:00:00Z"))
        let a = try XCTUnwrap(item.analysis)
        XCTAssertEqual(a.people?.count, 2)
        XCTAssertEqual(a.people?[0].basis, "tag")
        XCTAssertEqual(a.people?[0].appears?.first?.from, 1.5)
        XCTAssertNil(a.people?[1].who)
        XCTAssertEqual(a.people?[1].displayName, "a lifeguard")
        XCTAssertEqual(a.time?.timeOfDay, "dawn")
        XCTAssertEqual(a.place?.place, "Ribeira d'Ilhas")
        XCTAssertEqual(a.onScreenText, ["Ericeira"])
        XCTAssertEqual(a.events?.first?.at, 3.2)
        XCTAssertEqual(a.speech?.transcript, "Go go go")
        XCTAssertEqual(item.stickers?.first?.extra, .object(["options": .array([.string("a"), .string("b")]), "n": .number(2)]))
        XCTAssertEqual(item.extra, .object(["anything": .array([.number(1), .string("two"), .bool(true), .null])]))
    }

    func testMinimalStoryWithRepostAndNulls() throws {
        let item = try decode(Item.self, """
        {"id": "ig_1", "kind": "story", "shortcode": null, "source_url": null, "taken_at": "2024-05-01T12:00:00.250Z",
         "caption": null, "media": [{"type": "image", "url": "https://media.empire.earth/items/ig_1/0.jpg"}],
         "repost_of": {"author": "nazare.daily", "author_name": "Nazaré", "shortcode": "abc",
                       "source_url": "https://www.instagram.com/reel/abc/", "taken_at": "2024-04-30T00:00:00Z",
                       "caption": "Big waves", "media": [{"type": "video", "url": "https://media.empire.earth/items/ig_1/orig.0.mp4", "duration": null}]},
         "analysis": null}
        """)
        XCTAssertEqual(item.kind, .story)
        XCTAssertNil(item.shortcode)
        XCTAssertNil(item.analysis)
        XCTAssertNil(item.categories)
        XCTAssertNotNil(item.takenDate, "fractional seconds parse too")
        XCTAssertTrue(item.isRepost)
        XCTAssertEqual(item.repostOf?.author, "nazare.daily")
        XCTAssertEqual(item.repostOf?.media?.first?.type, .video)
        XCTAssertTrue(item.accessibilityDescription.contains("repost of @nazare.daily"))
    }

    func testUnknownKindAndMissingMediaStillDecode() throws {
        let item = try decode(Item.self, #"{"id": "ig_2", "kind": "guide"}"#)
        XCTAssertEqual(item.kind, .unknown)
        XCTAssertEqual(item.media, [])
        XCTAssertNil(item.coverURL)
    }

    func testListsAndProfile() throws {
        let page = try decode(ItemPage.self, #"{"items": [{"id": "ig_1", "kind": "post", "media": []}], "next": "abc"}"#)
        XCTAssertEqual(page.items.map(\.id), ["ig_1"])
        XCTAssertEqual(page.next, "abc")
        let last = try decode(ItemPage.self, #"{"items": [], "next": null}"#)
        XCTAssertNil(last.next)

        let hl = try decode(HighlightList.self, """
        {"highlights": [{"id": "hl_1", "title": "Travel", "cover": "https://media.empire.earth/highlights/hl_1/cover.jpg",
                         "item_ids": ["ig_2", "ig_1"], "updated_at": "2024-01-01T00:00:00Z"}]}
        """)
        XCTAssertEqual(hl.highlights.first?.itemIds, ["ig_2", "ig_1"])

        let cats = try decode(CategoryList.self, #"{"categories": [{"slug": "travel", "name": "Travel", "description": "Trips", "count": 42}]}"#)
        XCTAssertEqual(cats.categories.first?.count, 42)

        let profile = try decode(Profile.self, """
        {"username": "earthempire", "full_name": "Earth Empire", "bio": "Hi", "avatar": "https://media.empire.earth/profile/avatar.jpg",
         "links": ["https://empire.earth"], "counts": {"posts": 1, "followers": 2, "following": 3}, "updated_at": "2024-01-01T00:00:00Z"}
        """)
        XCTAssertEqual(profile.fullName, "Earth Empire")
        XCTAssertEqual(profile.counts?.following, 3)
    }

    /// The bundled fixture is the contract's shapes; it all decodes and round-trips through the
    /// offline cache's encoding.
    func testFixtureDecodesAndRoundTrips() throws {
        let api = try SampleAPI.bundled()
        let f = api.fixture
        XCTAssertGreaterThan(f.items.count, 10)
        XCTAssertFalse(f.highlights.isEmpty)
        XCTAssertFalse(f.categories.isEmpty)
        for kind in [ItemKind.post, .carousel, .reel, .story] {
            XCTAssertTrue(f.items.contains { $0.kind == kind }, "fixture has a \(kind)")
        }
        XCTAssertTrue(f.items.contains { $0.isRepost })
        XCTAssertTrue(f.items.allSatisfy { $0.id.hasPrefix("ig_") })
        for h in f.highlights {
            for id in h.itemIds { XCTAssertTrue(f.items.contains { $0.id == id }, "\(h.title) lists \(id)") }
        }

        let data = try APIDecoding.encoder.encode(f.items)
        let back = try APIDecoding.decoder.decode([Item].self, from: data)
        XCTAssertEqual(back, f.items)
    }

    func testResponseCacheKeepsItemsForOffline() throws {
        let dir = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        let cache = ResponseCache(root: dir)
        let item = try decode(Item.self, #"{"id": "ig_9", "kind": "post", "caption": "kept", "media": []}"#)
        cache.store(items: [item])
        XCTAssertEqual(cache.item(id: "ig_9")?.caption, "kept")
        let url = URL(string: "https://api.empire.earth/v1/profile")!
        cache.store(Data("{}".utf8), for: url)
        XCTAssertEqual(cache.data(for: url), Data("{}".utf8))
        cache.clear()
        XCTAssertNil(cache.item(id: "ig_9"))
    }

    func testLiveAPIBuildsContractURLs() {
        let api = LiveAPI(base: URL(string: "https://abc.execute-api.us-east-1.amazonaws.com")!)
        let url = api.url("v1/items", query: [.init(name: "kind", value: "reel"), .init(name: "before", value: "c 1")])
        XCTAssertEqual(url.absoluteString, "https://abc.execute-api.us-east-1.amazonaws.com/v1/items?kind=reel&before=c%201")
    }
}
