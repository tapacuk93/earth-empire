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

    /// `mode` pins the home screen's tag cloud / chronological switch for the run (nil: whatever
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

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    func testHomeShowsProfileHighlightsAndGrid() {
        let app = launch()
        XCTAssertTrue(element(app, "profile.header").waitForExistence(timeout: 15))
        XCTAssertTrue(element(app, "highlight.\(travel)").waitForExistence(timeout: 10))
        XCTAssertTrue(element(app, "grid.item.\(reel)").waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Earth Empire"].exists)
        shot("01-home")
    }

    func testTagCloudFiltersItems() {
        let app = launch(mode: "tags")
        let surf = element(app, "tag.surf")
        XCTAssertTrue(surf.waitForExistence(timeout: 15))
        XCTAssertTrue(element(app, "tag.@marta.waves").exists, "a person the post named is a tag")
        shot("11-tag-cloud")
        surf.tap()
        XCTAssertTrue(element(app, "tag.selected").waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "grid.item.\(reel)").waitForExistence(timeout: 10))
        XCTAssertFalse(element(app, "grid.item.ig_3400000000000000006").waitForExistence(timeout: 2))
        shot("12-tag-filtered")
        element(app, "tag.selected").tap()
        XCTAssertFalse(element(app, "tag.selected").waitForExistence(timeout: 2))
    }

    func testHomeModeSwitch() {
        let app = launch(mode: nil)
        let picker = element(app, "home.mode")
        XCTAssertTrue(picker.waitForExistence(timeout: 15))
        app.buttons["Chronological"].tap()
        XCTAssertTrue(element(app, "timeline.month.2026-10").waitForExistence(timeout: 10))
        shot("13-chronological")
        app.buttons["Tag cloud"].tap()
        XCTAssertTrue(element(app, "tag.cloud").waitForExistence(timeout: 10))
    }

    func testKindFilterShowsOnlyThatKind() {
        let app = launch()
        XCTAssertTrue(element(app, "grid.item.\(reel)").waitForExistence(timeout: 15))
        element(app, "filter.kind.carousel").tap()
        XCTAssertTrue(element(app, "grid.item.\(carousel)").waitForExistence(timeout: 10))
        XCTAssertFalse(element(app, "grid.item.\(reel)").waitForExistence(timeout: 2))
        shot("02-filter-carousels")
        element(app, "filter.kind.all").tap()
        XCTAssertTrue(element(app, "grid.item.\(reel)").waitForExistence(timeout: 10))
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
        XCTAssertTrue(element(app, "profile.header").waitForExistence(timeout: 15))
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
        let app = launch()
        let ring = element(app, "highlight.\(travel)")
        XCTAssertTrue(ring.waitForExistence(timeout: 15))
        ring.tap()
        XCTAssertTrue(element(app, "story.viewer").waitForExistence(timeout: 10))
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
        XCTAssertTrue(element(app, "profile.header").waitForExistence(timeout: 5))
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
    func tapWhenReady(timeout: TimeInterval = 15) {
        XCTAssertTrue(waitForExistence(timeout: timeout))
        tap()
    }
}
