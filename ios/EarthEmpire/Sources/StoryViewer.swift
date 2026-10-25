import AVKit
import SwiftUI

/// A highlight played like Instagram's stories: progress bars, tap right for the next story and
/// left for the previous one, hold to pause, swipe sideways to the next highlight, swipe down
/// to close.
struct StoryViewer: View {
    let request: StoryRequest
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var highlightID: String = ""
    @State private var stories: [Item] = []
    @State private var index = 0
    @State private var progress: Double = 0
    @State private var paused = false
    @State private var loading = true
    @State private var error: Error?
    @State private var player: AVPlayer?
    @State private var drag: CGSize = .zero

    static let imageSeconds = 5.0

    private var highlight: Highlight? { model.highlight(highlightID) }
    private var current: Item? { stories.indices.contains(index) ? stories[index] : nil }

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.black.ignoresSafeArea()
                if let item = current {
                    storyMedia(item)
                        .frame(width: geo.size.width, height: geo.size.height)
                        .clipped()
                } else if loading {
                    ProgressView().tint(.white)
                } else if let error {
                    Text(error.localizedDescription).foregroundStyle(.white).padding()
                }
                tapZones(width: geo.size.width)
                VStack(spacing: 0) {
                    topBar
                    Spacer()
                    if let item = current { bottomBar(item) }
                }
            }
            .offset(y: max(0, drag.height))
            .scaleEffect(1 - min(0.15, max(0, drag.height) / 2000))
            .gesture(swipe)
        }
        .statusBarHidden()
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("story.viewer")
        .task {
            highlightID = request.highlightID
            if model.highlights.isEmpty { await model.loadHome() }
            await load(startAt: request.itemID)
        }
        .task(id: TickKey(id: current?.id, paused: paused)) { await tick() }
        .onDisappear { player?.pause() }
    }

    private struct TickKey: Hashable { var id: String?; var paused: Bool }

    // MARK: Loading

    private func load(startAt itemID: String?) async {
        loading = true
        error = nil
        player?.pause()
        player = nil
        var items: [Item] = []
        do {
            var cursor: String?
            repeat {
                let page = try await model.api.items(ItemQuery(highlight: highlightID), before: cursor, limit: 50)
                items += page.items
                cursor = page.next
            } while cursor != nil && items.count < 500
        } catch {
            log.error("highlight \(highlightID, privacy: .public) failed: \(error.localizedDescription, privacy: .public)")
            // Offline: whatever stories of it are cached, by the highlight's own order.
            if let h = highlight {
                for id in h.itemIds { if let i = try? await model.api.item(id: id) { items.append(i) } }
            }
            if items.isEmpty { self.error = error }
        }
        stories = Self.order(items, by: highlight?.itemIds ?? [])
        index = itemID.flatMap { id in stories.firstIndex { $0.id == id } } ?? 0
        progress = 0
        loading = false
        preparePlayer()
    }

    /// The highlight's own order (`item_ids`); anything it does not list goes last, oldest first.
    static func order(_ items: [Item], by ids: [String]) -> [Item] {
        let rank = Dictionary(ids.enumerated().map { ($1, $0) }, uniquingKeysWith: { a, _ in a })
        return items.sorted { a, b in
            switch (rank[a.id], rank[b.id]) {
            case let (x?, y?): return x < y
            case (_?, nil): return true
            case (nil, _?): return false
            default: return (a.takenAt ?? "") < (b.takenAt ?? "")
            }
        }
    }

    // MARK: Playback

    private var duration: Double {
        guard let m = current.flatMap(storyMediaItem) else { return Self.imageSeconds }
        return m.type == .video ? max(1, m.duration ?? Self.imageSeconds) : Self.imageSeconds
    }

    private func storyMediaItem(_ item: Item) -> Media? { item.media.first ?? item.repostOf?.media?.first }

    private func preparePlayer() {
        player?.pause()
        if let m = current.flatMap(storyMediaItem), m.type == .video {
            player = AVPlayer.archive(m.url)
            player?.play()
        } else {
            player = nil
        }
    }

    private func tick() async {
        guard current != nil, !paused else { player?.pause(); return }
        player?.play()
        let step = 0.05
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: UInt64(step * 1_000_000_000))
            if Task.isCancelled { return }
            if let player, player.timeControlStatus == .playing {
                progress = min(1, player.currentTime().seconds / duration)
            } else if player == nil {
                progress = min(1, progress + step / duration)
            }
            if progress >= 1 { next(); return }
        }
    }

    private func next() {
        if index + 1 < stories.count {
            index += 1
            progress = 0
            preparePlayer()
        } else {
            nextHighlight(1)
        }
    }

    private func previous() {
        if index > 0 {
            index -= 1
            progress = 0
            preparePlayer()
        } else if !nextHighlight(-1) {
            progress = 0
            player?.seek(to: .zero)
        }
    }

    /// Moves to the next (or previous) highlight in the profile's order; closes after the last.
    @discardableResult
    private func nextHighlight(_ step: Int) -> Bool {
        guard let i = model.highlights.firstIndex(where: { $0.id == highlightID }),
              model.highlights.indices.contains(i + step) else {
            if step > 0 { close() }
            return false
        }
        highlightID = model.highlights[i + step].id
        stories = []
        index = 0
        Task { await load(startAt: nil) }
        return true
    }

    private func close() {
        player?.pause()
        dismiss()
    }

    // MARK: Views

    @ViewBuilder
    private func storyMedia(_ item: Item) -> some View {
        let m = storyMediaItem(item)
        ZStack {
            if let m {
                if m.type == .video, let player {
                    StoryPlayerView(player: player)
                } else {
                    RemoteImage(m.type == .video ? m.poster : m.url, contentMode: .fit)
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Story \(index + 1) of \(stories.count). \(item.accessibilityDescription)")
        .accessibilityIdentifier("story.media.\(item.id)")
    }

    private func tapZones(width: CGFloat) -> some View {
        HStack(spacing: 0) {
            Color.clear.contentShape(Rectangle())
                .frame(width: width / 3)
                .onTapGesture { previous() }
                .accessibilityLabel("Previous story")
                .accessibilityAddTraits(.isButton)
                .accessibilityIdentifier("story.previous")
            Color.clear.contentShape(Rectangle())
                .onTapGesture { next() }
                .accessibilityLabel("Next story")
                .accessibilityAddTraits(.isButton)
                .accessibilityIdentifier("story.next")
        }
        .onLongPressGesture(minimumDuration: 0.25, maximumDistance: 20, perform: {}, onPressingChanged: { pressing in
            paused = pressing
        })
    }

    private var topBar: some View {
        VStack(spacing: 10) {
            HStack(spacing: 3) {
                ForEach(stories.indices, id: \.self) { i in
                    GeometryReader { g in
                        Capsule().fill(.white.opacity(0.35))
                            .overlay(alignment: .leading) {
                                Capsule().fill(.white)
                                    .frame(width: g.size.width * (i < index ? 1 : i == index ? progress : 0))
                            }
                    }
                    .frame(height: 2.5)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Story \(index + 1) of \(stories.count)")
            .accessibilityIdentifier("story.progress")
            HStack(spacing: 10) {
                RemoteImage(highlight?.cover)
                    .frame(width: 32, height: 32)
                    .clipShape(Circle())
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 0) {
                    Text(highlight?.title ?? "").font(.subheadline.weight(.semibold))
                        .accessibilityIdentifier("story.title")
                    if let d = current?.takenDate {
                        Text(d.formatted(.relative(presentation: .named))).font(.caption).opacity(0.8)
                    }
                }
                Spacer()
                if paused { Image(systemName: "pause.fill").accessibilityLabel("Paused") }
                Button { close() } label: {
                    Image(systemName: "xmark").font(.title3.weight(.semibold)).padding(8)
                }
                .accessibilityLabel("Close")
                .accessibilityIdentifier("story.close")
            }
            .foregroundStyle(.white)
        }
        .padding(.horizontal, 10)
        .padding(.top, 8)
        .shadow(color: .black.opacity(0.4), radius: 3)
    }

    private func bottomBar(_ item: Item) -> some View {
        HStack {
            if let r = item.repostOf {
                if let s = r.sourceUrl, let url = URL(string: s) {
                    Link(destination: url) {
                        Label("Reel by @\(r.author)", systemImage: "arrow.2.squarepath")
                    }
                    .accessibilityIdentifier("story.repost")
                } else {
                    Label("By @\(r.author)", systemImage: "arrow.2.squarepath")
                }
            } else if let s = item.summary {
                Text(s).lineLimit(2)
            }
            Spacer()
            Button {
                close()
                model.path.append(Route.item(item))
            } label: {
                Label("Details", systemImage: "sparkles")
            }
            .accessibilityHint("Opens the item with its analysis")
            .accessibilityIdentifier("story.details")
        }
        .font(.subheadline.weight(.semibold))
        .foregroundStyle(.white)
        .padding(.horizontal, 12).padding(.vertical, 10)
        .background(.black.opacity(0.35), in: Capsule())
        .padding(.horizontal, 10)
        .padding(.bottom, 8)
    }

    private var swipe: some Gesture {
        DragGesture(minimumDistance: 24)
            .onChanged { v in
                if abs(v.translation.height) > abs(v.translation.width) { drag = v.translation; paused = true }
            }
            .onEnded { v in
                paused = false
                let dx = v.translation.width, dy = v.translation.height
                if dy > 120, dy > abs(dx) { close(); return }
                withAnimation(reduceMotion ? nil : .spring) { drag = .zero }
                if abs(dx) > 80, abs(dx) > abs(dy) { nextHighlight(dx < 0 ? 1 : -1) }
            }
    }
}

/// A bare video layer, without the system controls (stories have their own).
struct StoryPlayerView: UIViewRepresentable {
    let player: AVPlayer

    func makeUIView(context: Context) -> PlayerLayerView {
        let v = PlayerLayerView()
        v.playerLayer.videoGravity = .resizeAspect
        v.playerLayer.player = player
        return v
    }

    func updateUIView(_ v: PlayerLayerView, context: Context) { v.playerLayer.player = player }

    final class PlayerLayerView: UIView {
        override class var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }
}
