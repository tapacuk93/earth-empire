import AVFoundation
import SwiftUI

@main
struct EarthEmpireApp: App {
    @State private var model = AppModel()

    init() {
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .moviePlayback)
        URLCache.shared = URLCache(memoryCapacity: 16 << 20, diskCapacity: 256 << 20)
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .tint(Theme.accent)
                .onOpenURL { model.open(url: $0) }
                .onContinueUserActivity(NSUserActivityTypeBrowsingWeb) { activity in
                    if let url = activity.webpageURL { model.open(url: url) }
                }
        }
    }
}

enum Theme {
    static let accent = Color(red: 0.12, green: 0.55, blue: 0.45)
    static let ring = LinearGradient(colors: [.orange, .pink, .purple], startPoint: .bottomLeading, endPoint: .topTrailing)
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationStack(path: $model.path) {
            ProfileView()
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .item(let id, let preview): ItemDetailView(id: id, preview: preview)
                    case .category(let slug): CategoryView(slug: slug)
                    case .categories: CategoriesView()
                    }
                }
        }
        .fullScreenCover(item: $model.story) { request in
            StoryViewer(request: request)
                .environment(model)
        }
        .task {
            // A link given at launch by UI tests: `-EEOpenURL earthempire://item/…`.
            if let s = UserDefaults.standard.string(forKey: "EEOpenURL"), let url = URL(string: s) {
                try? await Task.sleep(nanoseconds: 300_000_000)
                model.open(url: url)
            }
        }
    }
}
