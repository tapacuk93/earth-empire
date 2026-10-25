import SwiftUI

/// The account's home: header, highlights, filters, the grid, search.
struct ProfileView: View {
    @Environment(AppModel.self) private var model
    @State private var search = ""
    @State private var committedSearch = ""
    @State private var kind: ItemKind?
    @State private var category: String?
    @State private var pager: Pager<Item>?
    @State private var showSettings = false

    private var query: ItemQuery {
        ItemQuery(kind: kind, category: category, highlight: nil, q: committedSearch.isEmpty ? nil : committedSearch)
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0, pinnedViews: []) {
                if committedSearch.isEmpty {
                    ProfileHeader()
                        .padding(.horizontal)
                        .padding(.top, 8)
                    HighlightsRow()
                        .padding(.vertical, 12)
                }
                FilterBar(kind: $kind, category: $category)
                    .padding(.bottom, 8)
                if let error = model.homeError, model.profile == nil {
                    ErrorBanner(error: error) { Task { await model.loadHome() } }
                        .padding()
                }
                if let pager {
                    ItemGrid(pager: pager)
                }
            }
        }
        .refreshable {
            await model.loadHome()
            await pager?.refresh()
        }
        .navigationTitle(model.profile?.username ?? "Earth Empire")
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
        .onChange(of: model.pendingQuery) { _, q in
            guard let q else { return }
            search = q.q ?? ""
            committedSearch = search
            kind = q.kind
            category = q.category
            model.pendingQuery = nil
        }
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

struct ProfileHeader: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let p = model.profile
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 20) {
                RemoteImage(p?.avatar, accessibilityLabel: nil)
                    .frame(width: 86, height: 86)
                    .clipShape(Circle())
                    .overlay(Circle().strokeBorder(Theme.ring, lineWidth: 3).padding(-5))
                    .padding(5)
                    .accessibilityHidden(true)
                ViewThatFits {
                    HStack(spacing: 18) { counts }
                    VStack(alignment: .leading, spacing: 4) { counts }
                }
                .frame(maxWidth: .infinity)
            }
            if let name = p?.fullName { Text(name).font(.headline) }
            if let bio = p?.bio { Text(bio).font(.subheadline) }
            ForEach(p?.links ?? [], id: \.self) { link in
                if let url = URL(string: link) {
                    Link(url.host ?? link, destination: url).font(.subheadline.weight(.semibold))
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("profile.header")
        .redacted(reason: p == nil ? .placeholder : [])
    }

    @ViewBuilder private var counts: some View {
        let c = model.profile?.counts
        stat(c?.posts, "posts")
        stat(c?.followers, "followers")
        stat(c?.following, "following")
    }

    private func stat(_ n: Int?, _ label: String) -> some View {
        VStack(spacing: 2) {
            Text(n.map { $0.formatted(.number.notation(.compactName)) } ?? "–").font(.headline)
            Text(label).font(.caption).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }
}

struct HighlightsRow: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if !model.highlights.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 16) {
                    ForEach(model.highlights) { h in
                        Button { model.story = StoryRequest(highlightID: h.id, itemID: nil) } label: {
                            VStack(spacing: 6) {
                                RemoteImage(h.cover)
                                    .frame(width: 64, height: 64)
                                    .clipShape(Circle())
                                    .overlay(Circle().strokeBorder(.secondary.opacity(0.4), lineWidth: 1).padding(-4))
                                    .padding(4)
                                Text(h.title).font(.caption).lineLimit(1).frame(maxWidth: 76)
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Highlight \(h.title), \(h.itemIds.count) stories")
                        .accessibilityIdentifier("highlight.\(h.id)")
                    }
                }
                .padding(.horizontal)
            }
        }
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
