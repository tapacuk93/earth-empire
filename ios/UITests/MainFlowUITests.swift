import XCTest

/// The main flows on the bundled fixture (`-EESample YES`): no network.
///
/// With `EE_SHOT_DIR` set (through `TEST_RUNNER_EE_SHOT_DIR`), each flow also saves a screenshot
/// of the screen it reaches there.
final class MainFlowUITests: XCTestCase {
    private let reel = "ig_3400000000000000012"
    private let carousel = "ig_3400000000000000010"
    private let repostPost = "ig_3400000000000000005"
    private let travel = "hl_17900000000000001"

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    /// `mode` pins the home page shown first (videos, timeline or tags) for the run (nil: whatever
    /// the settings hold).
    private func launch(open url: String? = nil, mode: String? = "timeline") -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-EESample", "YES", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        if let mode { app.launchArguments += ["-EEHomeMode", mode] }
        if let url { app.launchArguments += ["-EEOpenURL", url] } else { app.launchArguments += ["-EEOpenURL", ""] }
        app.launch()
        return app
    }

    private func shot(_ name: String, settle: TimeInterval = 1.0) {
        guard let dir = ProcessInfo.processInfo.environment["EE_SHOT_DIR"], !dir.isEmpty else { return }
        Thread.sleep(forTimeInterval: settle)
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(dir)/\(name).png"))
    }

    /// Scrolls the page until `el` is on screen: up first (it is usually below), then back down.
    @discardableResult
    private func reveal(_ app: XCUIApplication, _ el: XCUIElement) -> XCUIElement {
        for _ in 0..<6 where !(el.waitForExistence(timeout: 1.5) && el.isHittable) { app.swipeUp() }
        for _ in 0..<8 where !(el.exists && el.isHittable) { app.swipeDown() }
        return el
    }

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    func testHomeShowsOnlyVideosInSections() {
        let app = launch(mode: "videos")
        XCTAssertTrue(element(app, "video.\(reel)").waitForExistence(timeout: 15))
        XCTAssertFalse(element(app, "section.featured").exists, "sections are subjects, not levels")
        XCTAssertTrue(element(app, "video.\(reel)").label.contains("Audio: "), "every card says what sounds in it")
        XCTAssertFalse(element(app, "video.ig_3400000000000000007").exists, "a photo post is not a video")
        XCTAssertFalse(element(app, "profile.header").exists)
        shot("01-home")
        let tile = element(app, "video.\(reel)")
        XCTAssertTrue(tile.waitUntilHittable())
        tile.tap()
        XCTAssertTrue(element(app, "media.pager").waitForExistence(timeout: 10))
    }

    func testTagCloudFiltersItems() {
        let app = launch(mode: "tags")
        let surf = element(app, "tag.surf")
        XCTAssertTrue(surf.waitForExistence(timeout: 15))
        XCTAssertTrue(element(app, "tag.@marta.waves").exists, "a person the post named is a tag")
        shot("11-tag-cloud")
        surf.tap()
        XCTAssertTrue(element(app, "tag.selected").waitForExistence(timeout: 5))
        let tile = element(app, "grid.item.\(reel)")
        for _ in 0..<6 where !tile.waitForExistence(timeout: 2) { app.swipeUp() }
        XCTAssertTrue(tile.exists)
        XCTAssertFalse(element(app, "grid.item.ig_3400000000000000006").waitForExistence(timeout: 2))
        shot("12-tag-filtered")
        element(app, "tag.selected").tap()
        XCTAssertFalse(element(app, "tag.selected").waitForExistence(timeout: 2))
    }

    func testHomePagesSideBySide() {
        let app = launch(mode: "videos")
        XCTAssertTrue(element(app, "video.\(reel)").waitForExistence(timeout: 15))
        let pages = app.scrollViews.firstMatch
        pages.swipeLeft()
        XCTAssertTrue(element(app, "timeline.month.2026-10").waitForExistence(timeout: 10))
        shot("13-timeline")
        pages.swipeLeft()
        XCTAssertTrue(element(app, "tag.cloud").waitForExistence(timeout: 10))
        pages.swipeRight()
        pages.swipeRight()
        XCTAssertTrue(element(app, "video.\(reel)").waitForExistence(timeout: 10))
    }

    func testKindFilterShowsOnlyThatKind() {
        let app = launch(mode: "tags")
        XCTAssertTrue(element(app, "tag.cloud").waitForExistence(timeout: 15))
        // The grid is below the tag cloud; a lazy grid has its tiles only once they scroll in.
        let tile = element(app, "grid.item.\(reel)")
        for _ in 0..<6 where !tile.waitForExistence(timeout: 2) { app.swipeUp() }
        XCTAssertTrue(tile.exists)
        reveal(app, element(app, "filter.kind.carousel")).tap()
        XCTAssertTrue(reveal(app, element(app, "grid.item.\(carousel)")).exists)
        XCTAssertFalse(element(app, "grid.item.\(reel)").waitForExistence(timeout: 2))
        shot("02-filter-carousels")
        reveal(app, element(app, "filter.kind.all")).tap()
        XCTAssertTrue(reveal(app, element(app, "grid.item.\(reel)")).exists)
    }

    func testItemShowsAnalysisAndTimelineSeeksVideo() {
        let app = launch()
        let tile = element(app, "grid.item.\(reel)")
        XCTAssertTrue(tile.waitForExistence(timeout: 15))
        tile.tap()
        XCTAssertTrue(element(app, "media.pager").waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["@marta.waves"].waitForExistence(timeout: 10), "a person named from the tag")
        shot("03-item-reel")
        let event = element(app, "event.2")
        for _ in 0..<6 where !event.isHittable { app.swipeUp() }
        XCTAssertTrue(event.exists)
        shot("04-item-analysis")
        event.tap()
        // Seeking starts the player: the poster's play button gives way to the video.
        for _ in 0..<8 { app.swipeDown() }
        XCTAssertFalse(element(app, "video.play").waitForExistence(timeout: 2))
        XCTAssertTrue(element(app, "transcript").exists)
    }

    func testCategoryChipOpensCategoryPage() {
        let app = launch()
        element(app, "grid.item.\(reel)").tapWhenReady()
        let chip = element(app, "chip.category.surf")
        XCTAssertTrue(chip.waitForExistence(timeout: 10))
        for _ in 0..<4 where !chip.isHittable { app.swipeUp() }
        chip.tap()
        XCTAssertTrue(element(app, "category.page").waitForExistence(timeout: 10))
        XCTAssertTrue(app.navigationBars["Surf"].waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "grid.item.\(reel)").waitForExistence(timeout: 10))
        shot("05-category-surf")
    }

    func testCategoriesList() {
        let app = launch()
        XCTAssertTrue(element(app, "home.pages").waitForExistence(timeout: 15))
        let food = element(app, "category.food")
        // The toolbar can take a moment to accept taps after launch; tap again if the list
        // did not open.
        for _ in 0..<3 where !food.exists {
            element(app, "toolbar.categories").tap()
            _ = food.waitForExistence(timeout: 5)
        }
        XCTAssertTrue(food.exists)
        shot("06-categories")
        food.tap()
        XCTAssertTrue(app.navigationBars["Food"].waitForExistence(timeout: 5))
    }

    func testHighlightStoryViewer() {
        let app = launch(open: "earthempire://highlight/\(travel)")
        XCTAssertTrue(element(app, "story.viewer").waitForExistence(timeout: 15))
        XCTAssertEqual(element(app, "story.title").label, "Travel")
        let progress = element(app, "story.progress")
        XCTAssertTrue(progress.waitForExistence(timeout: 10))
        XCTAssertTrue(progress.label.hasPrefix("Story 1 of"), progress.label)
        shot("07-story-viewer", settle: 1.5)
        element(app, "story.next").tap()
        XCTAssertTrue(progress.label.hasPrefix("Story 2 of"), progress.label)
        element(app, "story.previous").tap()
        XCTAssertTrue(progress.label.hasPrefix("Story 1 of"), progress.label)
        element(app, "story.close").tap()
        XCTAssertTrue(element(app, "home.pages").waitForExistence(timeout: 5))
    }

    func testSearchFindsByAnalysis() {
        let app = launch()
        XCTAssertTrue(element(app, "grid.item.\(reel)").waitForExistence(timeout: 15))
        let field = app.searchFields.firstMatch
        if !field.exists { app.swipeDown() }
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText("varenyky")
        XCTAssertTrue(element(app, "grid.item.ig_3400000000000000006").waitForExistence(timeout: 10))
        XCTAssertFalse(element(app, "grid.item.\(reel)").waitForExistence(timeout: 2))
        shot("08-search")
    }

    func testRepostCreditsTheOriginal() {
        let app = launch(open: "earthempire://item/\(repostPost)")
        let card = element(app, "repost.card")
        XCTAssertTrue(card.waitForExistence(timeout: 15))
        XCTAssertTrue(element(app, "repost.link").exists)
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "@alex.films")).firstMatch.exists)
        shot("09-repost")
    }

    func testDeepLinkToHighlightOpensStory() {
        let app = launch(open: "https://empire.earth/highlight/hl_17900000000000003?item=ig_3400000000000000011")
        XCTAssertTrue(element(app, "story.viewer").waitForExistence(timeout: 15))
        XCTAssertEqual(element(app, "story.title").label, "Surf")
        XCTAssertTrue(element(app, "story.repost").waitForExistence(timeout: 5), "the shared reel is credited")
        shot("10-story-repost", settle: 1.5)
    }
}

private extension XCUIElement {
    func waitUntilHittable(timeout: TimeInterval = 10) -> Bool {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end { if exists && isHittable { return true }; Thread.sleep(forTimeInterval: 0.2) }
        return false
    }

    func tapWhenReady(timeout: TimeInterval = 15) {
        XCTAssertTrue(waitForExistence(timeout: timeout))
        tap()
    }
}
