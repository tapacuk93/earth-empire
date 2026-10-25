import AVKit
import SwiftUI

/// One item: its media, caption and metadata, the original if it is a repost, and Claude's
/// analysis. Side by side on a wide screen, stacked on a phone.
struct ItemDetailView: View {
    let id: String
    var preview: Item?

    @Environment(AppModel.self) private var model
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var item: Item?
    @State private var error: Error?
    @State private var playback = Playback()

    var body: some View {
        Group {
            if let item = item ?? preview {
                content(item)
            } else if let error {
                ErrorBanner(error: error) { Task { await load() } }.padding()
            } else {
                ProgressView()
            }
        }
        .navigationTitle((item ?? preview)?.kind.label ?? "Item")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let i = item ?? preview {
                ToolbarItem(placement: .topBarTrailing) {
                    ShareLink(item: DeepLink.webURL(item: i.id)) { Image(systemName: "square.and.arrow.up") }
                        .accessibilityLabel("Share")
                }
            }
        }
        .task(id: id) { await load() }
        .onDisappear { playback.pauseAll() }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("item.detail")
    }

    private func load() async {
        do { item = try await model.api.item(id: id); error = nil } catch {
            log.error("item \(id, privacy: .public) failed: \(error.localizedDescription, privacy: .public)")
            if item == nil { self.error = error }
        }
    }

    @ViewBuilder
    private func content(_ item: Item) -> some View {
        if sizeClass == .regular {
            HStack(alignment: .top, spacing: 0) {
                MediaPager(media: displayMedia(item), item: item, playback: playback)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(.black)
                Divider()
                ScrollView { details(item).padding() }
                    .frame(width: 420)
            }
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    MediaPager(media: displayMedia(item), item: item, playback: playback)
                        .aspectRatio(pagerAspect(item), contentMode: .fit)
                        .background(.black)
                    details(item).padding()
                }
            }
            .refreshable { await load() }
        }
    }

    /// A repost whose own media is only a screenshot of the original plays the original.
    private func displayMedia(_ item: Item) -> [Media] {
        item.media.isEmpty ? (item.repostOf?.media ?? []) : item.media
    }

    private func pagerAspect(_ item: Item) -> CGFloat {
        let ratios = displayMedia(item).map(\.aspectRatio)
        return max(9.0 / 16.0, min(ratios.min() ?? 1, 1.91))
    }

    private func details(_ item: Item) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            ItemHeader(item: item)
            if let caption = item.caption, !caption.isEmpty {
                Text(caption).font(.body).textSelection(.enabled)
            }
            if let repost = item.repostOf { RepostCard(repost: repost) }
            if let summary = item.summary {
                Label { Text(summary) } icon: { Image(systemName: "sparkles") }
                    .font(.callout)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.accent.opacity(0.12), in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityLabel("Summary: \(summary)")
            }
            CategoryChips(item: item)
            HighlightChips(item: item)
            if let analysis = item.analysis {
                AnalysisView(analysis: analysis, item: item, playback: playback)
            }
            MetadataView(item: item)
        }
    }
}

/// The AVPlayers of an item's videos, by media index, so the event timeline can seek them.
@MainActor
@Observable
final class Playback {
    var page = 0
    private var players: [Int: AVPlayer] = [:]

    func player(_ index: Int, url: String) -> AVPlayer? {
        if let p = players[index] { return p }
        let p = AVPlayer.archive(url)
        players[index] = p
        return p
    }

    func seek(media: Int, to seconds: Double) {
        page = media
        guard let p = players[media] else { pendingSeek = (media, seconds); return }
        p.seek(to: CMTime(seconds: seconds, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
        p.play()
    }

    var pendingSeek: (Int, Double)?

    func pauseAll(except index: Int? = nil) {
        for (i, p) in players where i != index { p.pause() }
    }
}

struct MediaPager: View {
    let media: [Media]
    let item: Item
    @Bindable var playback: Playback

    var body: some View {
        TabView(selection: $playback.page) {
            ForEach(Array(media.enumerated()), id: \.offset) { index, m in
                Group {
                    switch m.type {
                    case .image:
                        RemoteImage(m.url, contentMode: .fit, accessibilityLabel: label(index))
                    case .video:
                        VideoPage(media: m, index: index, playback: playback, label: label(index))
                    }
                }
                .tag(index)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: media.count > 1 ? .always : .never))
        .onChange(of: playback.page) { _, page in playback.pauseAll(except: page) }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("media.pager")
    }

    private func label(_ index: Int) -> String {
        var parts: [String] = []
        if media.count > 1 { parts.append("\(index + 1) of \(media.count)") }
        if index == 0, let alt = item.altText { parts.append(alt) }
        if let what = item.analysis?.what { parts.append(what) } else if let s = item.summary { parts.append(s) }
        return parts.joined(separator: ". ")
    }
}

/// A video with its poster until it plays.
struct VideoPage: View {
    let media: Media
    let index: Int
    let playback: Playback
    let label: String
    @State private var started = false

    var body: some View {
        ZStack {
            if started, let player = playback.player(index, url: media.url) {
                VideoPlayer(player: player)
                    .accessibilityLabel("Video. \(label)")
            } else {
                RemoteImage(media.thumbnail, contentMode: .fit, accessibilityLabel: nil)
                Button {
                    started = true
                    playback.player(index, url: media.url)?.play()
                } label: {
                    Image(systemName: "play.circle.fill")
                        .font(.system(size: 64))
                        .symbolRenderingMode(.palette)
                        .foregroundStyle(.white, .black.opacity(0.4))
                }
                .accessibilityLabel("Play video. \(label)")
                .accessibilityIdentifier("video.play")
            }
        }
        .onChange(of: playback.pendingSeek?.0) { _, m in
            if m == index, let (_, t) = playback.pendingSeek {
                started = true
                playback.pendingSeek = nil
                playback.seek(media: index, to: t)
            }
        }
    }
}

struct ItemHeader: View {
    let item: Item
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: 10) {
            RemoteImage(model.profile?.avatar)
                .frame(width: 36, height: 36)
                .clipShape(Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(model.profile?.username ?? "").font(.subheadline.weight(.semibold))
                if let loc = item.location?.name {
                    Label(loc, systemImage: "mappin.and.ellipse").font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Label(item.kind.label, systemImage: item.kind.symbol).font(.caption.weight(.medium))
                if let d = item.takenDate {
                    Text(d.formatted(date: .abbreviated, time: .shortened)).font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// The original of a repost, credited to its author.
struct RepostCard: View {
    let repost: Repost

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label {
                Text("Original by **@\(repost.author)**") + Text(repost.authorName.map { " · \($0)" } ?? "")
            } icon: { Image(systemName: "arrow.2.squarepath") }
                .font(.subheadline)
            HStack(alignment: .top, spacing: 10) {
                if let m = repost.media?.first {
                    RemoteImage(m.thumbnail ?? m.url)
                        .frame(width: 64, height: 84)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .accessibilityHidden(true)
                }
                VStack(alignment: .leading, spacing: 4) {
                    if let c = repost.caption { Text(c).font(.callout).lineLimit(4) }
                    if let d = repost.takenAt.flatMap(ISODate.parse) {
                        Text(d.formatted(date: .abbreviated, time: .omitted)).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            if let s = repost.sourceUrl, let url = URL(string: s) {
                Link(destination: url) {
                    Label("View on Instagram", systemImage: "arrow.up.right.square")
                        .font(.subheadline.weight(.semibold))
                }
                .accessibilityIdentifier("repost.link")
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Repost. Original by @\(repost.author)")
        .accessibilityIdentifier("repost.card")
    }
}

struct CategoryChips: View {
    let item: Item
    @Environment(AppModel.self) private var model

    var body: some View {
        if let cats = item.categories, !cats.isEmpty {
            FlowLayout(spacing: 6) {
                ForEach(cats, id: \.self) { slug in
                    NavigationLink(value: Route.category(slug)) {
                        Text("#" + (model.category(slug)?.name ?? slug))
                            .font(.subheadline.weight(.medium))
                            .padding(.horizontal, 10).padding(.vertical, 5)
                            .background(Theme.accent.opacity(0.15), in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Category \(model.category(slug)?.name ?? slug)")
                    .accessibilityIdentifier("chip.category.\(slug)")
                }
            }
        }
    }
}

struct HighlightChips: View {
    let item: Item
    @Environment(AppModel.self) private var model

    var body: some View {
        if let hls = item.highlights, !hls.isEmpty {
            FlowLayout(spacing: 6) {
                ForEach(hls, id: \.id) { h in
                    Button { model.story = StoryRequest(highlightID: h.id, itemID: item.id) } label: {
                        Label(h.title ?? "Highlight", systemImage: "circle.circle")
                            .font(.subheadline.weight(.medium))
                            .padding(.horizontal, 10).padding(.vertical, 5)
                            .background(.quaternary, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Highlight \(h.title ?? "")")
                    .accessibilityIdentifier("chip.highlight.\(h.id)")
                }
            }
        }
    }
}

struct MetadataView: View {
    let item: Item

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let c = item.counts {
                HStack(spacing: 14) {
                    count(c.likes, "heart")
                    count(c.comments, "bubble.right")
                    count(c.views, "eye")
                    count(c.plays, "play")
                }
                .font(.subheadline)
            }
            if let m = item.music, !m.line.isEmpty { row("music.note", m.line) }
            if let tagged = item.taggedUsers, !tagged.isEmpty {
                row("person.crop.square", "Tagged: " + tagged.map { "@" + $0.username }.joined(separator: ", "))
            }
            if let mentions = item.mentions, !mentions.isEmpty {
                row("at", mentions.map { "@" + $0 }.joined(separator: " "))
            }
            if let tags = item.hashtags, !tags.isEmpty {
                row("number", tags.map { "#" + $0 }.joined(separator: " "))
            }
            ForEach(Array((item.stickers ?? []).enumerated()), id: \.offset) { _, s in
                row("face.smiling", "\(s.type.capitalized) sticker" + (s.text.map { ": \($0)" } ?? ""))
            }
            if let alt = item.altText { row("text.below.photo", "Alt text: \(alt)") }
            if let s = item.sourceUrl, let url = URL(string: s) {
                Link(destination: url) { Label("Open on Instagram", systemImage: "arrow.up.right.square") }
                    .font(.subheadline)
            }
            if let a = item.analysis, let model = a.model {
                Text("Analyzed by \(model)" + (a.analyzedAt.flatMap(ISODate.parse).map { " on \($0.formatted(date: .abbreviated, time: .omitted))" } ?? ""))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .foregroundStyle(.primary)
    }

    @ViewBuilder private func count(_ n: Int?, _ symbol: String) -> some View {
        if let n {
            Label(n.formatted(.number.notation(.compactName)), systemImage: symbol)
                .accessibilityLabel("\(n) \(symbol == "heart" ? "likes" : symbol == "bubble.right" ? "comments" : symbol == "eye" ? "views" : "plays")")
        }
    }

    private func row(_ symbol: String, _ text: String) -> some View {
        Label(text, systemImage: symbol).font(.subheadline)
    }
}

/// Lays chips out in lines, wrapping as the width runs out.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, line: CGFloat = 0, maxX: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width { x = 0; y += line + spacing; line = 0 }
            x += size.width + spacing
            maxX = max(maxX, x - spacing)
            line = max(line, size.height)
        }
        return CGSize(width: min(maxX, width), height: y + line)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, line: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX { x = bounds.minX; y += line + spacing; line = 0 }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            line = max(line, size.height)
        }
    }
}
