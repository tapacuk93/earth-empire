import Foundation
import Observation
import SwiftUI

/// What the home screen shows under the highlights, remembered in settings.
enum HomeMode: String, CaseIterable, Identifiable {
    case tags, timeline
    var id: String { rawValue }
    var label: String { self == .tags ? "Tag cloud" : "Chronological" }
    static let storageKey = "EEHomeMode"
}

enum Route: Hashable {
    case item(String, preview: Item?)
    case category(String)
    case categories

    static func item(_ item: Item) -> Route { .item(item.id, preview: item) }
}

struct StoryRequest: Identifiable, Equatable {
    var highlightID: String
    var itemID: String?
    var id: String { highlightID + (itemID ?? "") }
}

/// The app's state: the API in use, the profile, highlights and categories, the navigation path
/// and the open story viewer.
@MainActor
@Observable
final class AppModel {
    private(set) var api: ArchiveAPI
    private(set) var usingSample: Bool
    private(set) var fellBackToSample = false
    /// Bumped whenever `api` changes, so screens reload from the new one.
    private(set) var apiGeneration = 0

    var profile: Profile?
    var highlights: [Highlight] = []
    var categories: [Category] = []
    var tags: [Tag] = []
    var homeError: Error?
    var path = NavigationPath()
    var story: StoryRequest?
    /// Filters a link asked for, for the home grid to take up.
    var pendingQuery: ItemQuery?

    init() {
        usingSample = AppConfig.useSample
        api = Self.makeAPI(sample: AppConfig.useSample)
        MediaURL.sampleMode = usingSample
    }

    private static func makeAPI(sample: Bool) -> ArchiveAPI {
        if sample, let s = try? SampleAPI.bundled() { return s }
        return LiveAPI(base: AppConfig.apiBase)
    }

    /// Switches between the live API and the sample fixture (Settings), and starts over.
    func reconfigure(sample: Bool) {
        AppConfig.useSample = sample
        usingSample = sample
        fellBackToSample = false
        MediaURL.sampleMode = sample
        api = Self.makeAPI(sample: sample)
        apiGeneration += 1
        profile = nil
        highlights = []
        categories = []
        tags = []
        path = NavigationPath()
    }

    func loadHome() async {
        do {
            async let p = api.profile()
            async let h = api.highlights()
            async let c = api.categories()
            let (profile, highlights, categories) = try await (p, h, c)
            self.profile = profile
            self.highlights = highlights
            self.categories = categories
            homeError = nil
            do { tags = try await api.tags(limit: 300) } catch {
                log.error("tags failed: \(error.localizedDescription, privacy: .public)")
            }
        } catch {
            log.error("home failed: \(error.localizedDescription, privacy: .public)")
            #if DEBUG
            // While the API is not live yet, a development build shows the fixture rather than an
            // empty screen. A release build never shows sample data as the archive.
            if !usingSample, profile == nil, let sample = try? SampleAPI.bundled() {
                log.notice("falling back to the sample fixture")
                api = sample
                apiGeneration += 1
                usingSample = true
                fellBackToSample = true
                MediaURL.sampleMode = true
                await loadHome()
                return
            }
            #endif
            homeError = error
        }
    }

    func category(_ slug: String) -> Category? { categories.first { $0.slug == slug } }
    func highlight(_ id: String) -> Highlight? { highlights.first { $0.id == id } }

    func open(_ link: DeepLink) {
        log.info("open link \(String(describing: link), privacy: .public)")
        story = nil
        switch link {
        case .home:
            path = NavigationPath()
        case .item(let id):
            path = NavigationPath()
            path.append(Route.item(id, preview: nil))
        case .category(let slug):
            path = NavigationPath()
            path.append(Route.category(slug))
        case .categories:
            path = NavigationPath()
            path.append(Route.categories)
        case .highlight(let id, let item):
            path = NavigationPath()
            story = StoryRequest(highlightID: id, itemID: item)
        case .grid(let query):
            path = NavigationPath()
            pendingQuery = query
        }
    }

    func open(url: URL) {
        if let link = DeepLink.parse(url) { open(link) } else { log.notice("unhandled url \(url.absoluteString, privacy: .public)") }
    }
}
