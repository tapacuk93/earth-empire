import SwiftUI
import UIKit

/// The tags of the archive's analyses, each sized by how many items have it. Tapping one filters
/// the grid; tapping it again clears the filter.
struct TagCloud: View {
    let tags: [Tag]
    @Binding var selected: String?
    var maxTags = 60
    @State private var showAll = false

    /// One entry per tag text (a tag can come under two kinds), the most common first, then
    /// shown alphabetically.
    private var shown: [Tag] {
        var best: [String: Tag] = [:]
        for t in tags where (best[t.tag]?.count ?? -1) < t.count { best[t.tag] = t }
        let top = best.values.sorted { $0.count != $1.count ? $0.count > $1.count : $0.tag < $1.tag }
        return Array(top.prefix(showAll ? 300 : maxTags)).sorted { $0.tag < $1.tag }
    }

    var body: some View {
        let list = shown
        let counts = list.map(\.count)
        let lo = Double(counts.min() ?? 1), hi = Double(counts.max() ?? 1)
        VStack(alignment: .leading, spacing: 8) {
            if tags.isEmpty {
                Text("Tags appear once items are analyzed.")
                    .font(.footnote).foregroundStyle(.secondary)
            } else {
                FlowLayout(spacing: 8) {
                    ForEach(list) { t in
                        TagButton(tag: t, weight: Self.weight(t.count, lo: lo, hi: hi), isSelected: selected == t.tag) {
                            toggle(t.tag)
                        }
                    }
                }
                if Set(tags.map(\.tag)).count > maxTags {
                    Button(showAll ? "Fewer tags" : "More tags") { showAll.toggle() }
                        .font(.footnote.weight(.semibold))
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("tag.cloud")
    }

    private func toggle(_ tag: String) { selected = selected == tag ? nil : tag }

    /// 0...1 on a log scale, so a few very common tags do not shrink the rest to nothing.
    static func weight(_ count: Int, lo: Double, hi: Double) -> Double {
        guard hi > lo else { return 0.5 }
        let c: Double = Foundation.log(Double(count)) - Foundation.log(lo)
        return c / (Foundation.log(hi) - Foundation.log(lo))
    }
}

struct TagButton: View {
    let tag: Tag
    /// 0...1, how common it is among the tags shown.
    let weight: Double
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        let size = UIFontMetrics(forTextStyle: .body).scaledValue(for: 13 + 15 * weight)
        Button(action: action) {
            Text(tag.tag)
                .font(.system(size: size, weight: weight > 0.6 ? .bold : weight > 0.3 ? .semibold : .regular))
                .foregroundStyle(isSelected ? Color.white : TagButton.color(tag.kind))
                .padding(.horizontal, 6).padding(.vertical, 2)
                .background(isSelected ? Theme.accent : .clear, in: RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(tag.tag), \(tag.kind), \(tag.count) \(tag.count == 1 ? "item" : "items")")
        .accessibilityAddTraits(isSelected ? .isSelected : [])
        .accessibilityIdentifier("tag.\(tag.tag)")
    }

    static func color(_ kind: String) -> Color {
        switch kind {
        case "category": Theme.accent
        case "person": .purple
        case "place", "country": .blue
        case "mood", "occasion": .orange
        case "hashtag": .pink
        default: .primary
        }
    }
}

/// Everything in date order, newest first, under a heading for each month.
struct TimelineList: View {
    @Bindable var pager: Pager<Item>
    @Environment(\.horizontalSizeClass) private var sizeClass

    private struct Month: Identifiable {
        var id: String
        var title: String
        var items: [Item]
    }

    private var months: [Month] {
        var out: [Month] = []
        let cal = Calendar(identifier: .gregorian)
        for item in pager.items {
            let date = item.takenDate ?? .distantPast
            let c = cal.dateComponents(in: TimeZone(identifier: "UTC")!, from: date)
            let id = String(format: "%04d-%02d", c.year ?? 0, c.month ?? 0)
            if out.last?.id == id { out[out.count - 1].items.append(item) } else {
                out.append(Month(id: id, title: date.formatted(.dateTime.month(.wide).year()), items: [item]))
            }
        }
        return out
    }

    var body: some View {
        let columns = [GridItem(.adaptive(minimum: sizeClass == .regular ? 200 : 110), spacing: 2)]
        ForEach(months) { month in
            Text(month.title)
                .font(.headline)
                .padding(.horizontal)
                .padding(.top, 14).padding(.bottom, 6)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("timeline.month.\(month.id)")
            LazyVGrid(columns: columns, spacing: 2) {
                ForEach(month.items) { item in
                    NavigationLink(value: Route.item(item)) {
                        ItemTile(item: item)
                            .overlay(alignment: .bottomLeading) {
                                if let d = item.takenDate {
                                    Text(d.formatted(.dateTime.day().month(.abbreviated)))
                                        .font(.caption2.weight(.semibold))
                                        .foregroundStyle(.white)
                                        .shadow(radius: 2)
                                        .padding(5)
                                        .accessibilityHidden(true)
                                }
                            }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("grid.item.\(item.id)")
                    .onAppear { pager.onAppear(item) }
                }
            }
        }
        if pager.isLoading {
            ProgressView().padding(24).frame(maxWidth: .infinity)
        } else if let error = pager.error {
            ErrorBanner(error: error) { Task { await pager.loadMore() } }.padding()
        }
    }
}
