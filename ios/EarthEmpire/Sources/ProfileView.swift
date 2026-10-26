import AVKit
import SwiftUI

/// Home: three pages side by side - the videos in sections (the main screen), then the timeline,
/// then the tags with the grid they filter. A search replaces them with its results.
struct ProfileView: View {
    @Environment(AppModel.self) private var model
    @State private var search = ""
    @State private var committedSearch = ""
    @State private var kind: ItemKind?
    @State private var category: String?
    @State private var tag: String?
    @State private var pager: Pager<Item>?
    @State private var timeline: Pager<Item>?
    @State private var hit: PublishedHit?
    @AppStorage(HomeMode.storageKey) private var mode: HomeMode = .videos
    @State private var showSettings = false

    private var query: ItemQuery {
        ItemQuery(kind: kind, category: category, highlight: nil, tag: tag, q: committedSearch.isEmpty ? nil : committedSearch)
    }

    var body: some View {
        Group {
            if !committedSearch.isEmpty {
                ScrollView { if let pager { ItemGrid(pager: pager) } }
            } else {
                TabView(selection: $mode) {
                    videos.tag(HomeMode.videos)
                    ScrollView { if let timeline { TimelineList(pager: timeline) } }
                        .accessibilityIdentifier("page.timeline")
                        .tag(HomeMode.timeline)
                    tagsPage.tag(HomeMode.tags)
                }
                .tabViewStyle(.page(indexDisplayMode: .always))
                .indexViewStyle(.page(backgroundDisplayMode: .always))
                .accessibilityIdentifier("home.pages")
            }
        }
        .refreshable {
            await model.loadHome()
            await pager?.refresh()
        }
        .navigationTitle(committedSearch.isEmpty ? mode.label : "Search")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $search, placement: .navigationBarDrawer(displayMode: .automatic),
                    prompt: "Search captions, people, places")
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                NavigationLink(value: Route.categories) {
                    Image(systemName: "square.grid.2x2")
                }
                .accessibilityLabel("Categories")
                .accessibilityIdentifier("toolbar.categories")
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button { showSettings = true } label: { Image(systemName: "gearshape") }
                    .accessibilityLabel("Settings")
                    .accessibilityIdentifier("toolbar.settings")
            }
        }
        .sheet(isPresented: $showSettings) { SettingsView() }
        .fullScreenCover(item: $hit) { HitPlayer(hit: $0) }
        .safeAreaInset(edge: .top) {
            if model.fellBackToSample || OfflineState.shared.isOffline {
                StatusStrip(text: model.fellBackToSample ? "API unreachable: showing sample data" : "Offline: showing saved items")
            }
        }
        .task { if model.profile == nil { await model.loadHome() } }
        .task(id: search) {
            try? await Task.sleep(nanoseconds: 350_000_000)
            if !Task.isCancelled { committedSearch = search.trimmingCharacters(in: .whitespaces) }
        }
        .task(id: QueryKey(query: query, generation: model.apiGeneration)) {
            let p = Pager.items(model.api, query)
            pager = p
            await p.loadIfNeeded()
        }
        .task(id: model.apiGeneration) {
            let p = Pager.items(model.api, ItemQuery())
            timeline = p
            await p.loadIfNeeded()
        }
        .onChange(of: model.pendingQuery) { _, q in
            guard let q else { return }
            search = q.q ?? ""
            committedSearch = search
            kind = q.kind
            category = q.category
            tag = q.tag
            if !q.isEmpty && (q.q ?? "").isEmpty { mode = .tags }
            model.pendingQuery = nil
        }
    }

    /// The main screen: only videos, in sections by importance.
    @ViewBuilder private var videos: some View {
        if let sections = model.videoSections {
            if sections.isEmpty {
                if let error = model.homeError {
                    ErrorBanner(error: error) { Task { await model.loadHome() } }.padding()
                } else {
                    ContentUnavailableView("Nothing is public yet", systemImage: "play.rectangle", description: Text("Videos appear here as they arrive."))
                }
            } else {
                VideoSectionsView(sections: sections) { hit = $0 }
            }
        } else if let error = model.homeError {
            ErrorBanner(error: error) { Task { await model.loadHome() } }.padding()
        } else {
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    /// The tags, the filters, and the grid they narrow.
    private var tagsPage: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                TagCloud(tags: model.tags, selected: $tag)
                    .padding(.horizontal)
                    .padding(.vertical, 10)
                if let tag {
                    Button { self.tag = nil } label: {
                        Label("#\(tag)", systemImage: "xmark.circle.fill")
                            .font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 12).padding(.vertical, 6)
                            .background(Theme.accent.opacity(0.2), in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal)
                    .padding(.bottom, 8)
                    .accessibilityLabel("Filtered by \(tag). Clear")
                    .accessibilityIdentifier("tag.selected")
                }
                FilterBar(kind: $kind, category: $category)
                    .padding(.bottom, 8)
                if let pager { ItemGrid(pager: pager) }
            }
        }
        .accessibilityIdentifier("page.tags")
    }

    private struct QueryKey: Hashable { var query: ItemQuery; var generation: Int }
}

struct StatusStrip: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.footnote.weight(.medium))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 6)
            .background(.yellow.opacity(0.85))
            .foregroundStyle(.black)
            .accessibilityIdentifier("status.strip")
    }
}

struct FilterBar: View {
    @Environment(AppModel.self) private var model
    @Binding var kind: ItemKind?
    @Binding var category: String?
    var showsCategories = true

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                chip("All", symbol: "square.grid.3x3", selected: kind == nil, id: "all") { kind = nil }
                ForEach([ItemKind.post, .carousel, .reel, .story], id: \.self) { k in
                    chip(k.label + "s", symbol: k.symbol, selected: kind == k, id: k.rawValue) { kind = kind == k ? nil : k }
                }
                if showsCategories, !model.categories.isEmpty {
                    Divider().frame(height: 20)
                    Menu {
                        Button("Every category") { category = nil }
                        ForEach(model.categories) { c in
                            Button { category = c.slug } label: {
                                if category == c.slug {
                                    Label("\(c.name) (\(c.count ?? 0))", systemImage: "checkmark")
                                } else {
                                    Text("\(c.name) (\(c.count ?? 0))")
                                }
                            }
                        }
                    } label: {
                        Label(category.flatMap { model.category($0)?.name } ?? "Category", systemImage: "tag")
                            .font(.subheadline.weight(.medium))
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .background(category == nil ? AnyShapeStyle(.quaternary) : AnyShapeStyle(Theme.accent.opacity(0.25)), in: Capsule())
                    }
                    .accessibilityIdentifier("filter.category")
                }
            }
            .padding(.horizontal)
        }
    }

    private func chip(_ title: String, symbol: String, selected: Bool, id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.subheadline.weight(.medium))
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(selected ? AnyShapeStyle(Theme.accent) : AnyShapeStyle(.quaternary), in: Capsule())
                .foregroundStyle(selected ? .white : .primary)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityIdentifier("filter.kind.\(id)")
    }
}

/// The grid of items for a pager, with paging as it scrolls and its state at the bottom.
struct ItemGrid: View {
    @Bindable var pager: Pager<Item>
    @Environment(\.horizontalSizeClass) private var sizeClass

    var body: some View {
        let columns = [GridItem(.adaptive(minimum: sizeClass == .regular ? 200 : 110), spacing: 2)]
        LazyVGrid(columns: columns, spacing: 2) {
            ForEach(pager.items) { item in
                NavigationLink(value: Route.item(item)) {
                    ItemTile(item: item)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("grid.item.\(item.id)")
                .onAppear { pager.onAppear(item) }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("grid")
        Group {
            if pager.isLoading {
                ProgressView().padding(24)
            } else if let error = pager.error {
                ErrorBanner(error: error) { Task { await pager.loadMore() } }.padding()
            } else if pager.loadedOnce && pager.items.isEmpty {
                ContentUnavailableView("Nothing here", systemImage: "square.dashed",
                                       description: Text("No items match."))
                    .padding(.top, 40)
            } else if pager.reachedEnd && !pager.items.isEmpty {
                Text("\(pager.items.count) items").font(.footnote).foregroundStyle(.secondary).padding(24)
            }
        }
        .frame(maxWidth: .infinity)
    }
}

struct ItemTile: View {
    let item: Item

    var body: some View {
        Color.clear
            .aspectRatio(3.0 / 4.0, contentMode: .fit)
            .overlay { RemoteImage(url: item.coverURL) }
            .clipped()
            .overlay(alignment: .topTrailing) {
                HStack(spacing: 4) {
                    if item.isRepost { Image(systemName: "arrow.2.squarepath") }
                    if item.kind != .post { Image(systemName: item.kind.symbol) }
                }
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.white)
                .shadow(radius: 2)
                .padding(6)
            }
            .contentShape(Rectangle())
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(item.accessibilityDescription)
            .accessibilityAddTraits(.isButton)
    }
}

struct ErrorBanner: View {
    let error: Error
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 8) {
            Label(error.localizedDescription, systemImage: "wifi.exclamationmark")
                .font(.callout)
                .multilineTextAlignment(.center)
            Button("Try again", action: retry).buttonStyle(.bordered)
        }
        .frame(maxWidth: .infinity)
        .accessibilityIdentifier("error.banner")
    }
}

/// A clip the monitor found elsewhere, full screen.
struct HitPlayer: View {
    let hit: PublishedHit
    @Environment(\.dismiss) private var dismiss
    @State private var player: AVPlayer?

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Color.black.ignoresSafeArea()
            if let player { VideoPlayer(player: player).ignoresSafeArea() } else { RemoteImage(hit.frame ?? hit.video?.thumbnail, contentMode: .fit) }
            VStack(alignment: .leading, spacing: 4) {
                Text("Found by AI").font(.caption.weight(.heavy)).foregroundStyle(.orange)
                Text(hit.title).font(.headline)
                Text(hit.what).font(.subheadline).opacity(0.85)
            }
            .foregroundStyle(.white)
            .padding(12)
            .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 14))
            .padding()
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
            Button { dismiss() } label: {
                Image(systemName: "xmark").font(.headline).padding(12).background(.ultraThinMaterial, in: Circle())
            }
            .accessibilityLabel("Close")
            .accessibilityIdentifier("hit.close")
            .padding()
        }
        .onAppear {
            if let clip = MediaURL.resolve(hit.clip) { player = AVPlayer(url: clip); player?.play() }
        }
        .onDisappear { player?.pause() }
        .accessibilityIdentifier("hit.player")
    }
}
