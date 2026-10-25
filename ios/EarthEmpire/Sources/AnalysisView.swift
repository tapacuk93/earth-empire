import SwiftUI

/// What Claude found in the item: who (with the basis for each name), what, when, where, the
/// moments of the video (tap to seek), the transcript, objects and the rest.
struct AnalysisView: View {
    let analysis: Analysis
    let item: Item
    let playback: Playback
    @State private var showTranscript = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Analysis").font(.title3.bold()).accessibilityAddTraits(.isHeader)

            if let what = analysis.what { section("What", "text.alignleft") { Text(what) } }

            if let people = analysis.people, !people.isEmpty {
                section("Who", "person.2") {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(people.enumerated()), id: \.offset) { _, p in PersonRow(person: p, playback: playback) }
                    }
                }
            }

            if let when = analysis.time, !when.line.isEmpty {
                section("When", "calendar") { basisText(when.line, basis: when.basis) }
            }
            if let place = analysis.place, !place.line.isEmpty {
                section("Where", "mappin.and.ellipse") { basisText(place.line, basis: place.basis) }
            }

            if let events = analysis.events, !events.isEmpty {
                section("Timeline", "timeline.selection") {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(events.enumerated()), id: \.offset) { i, e in
                            EventRow(event: e, mediaCount: item.media.count, playback: playback)
                                .accessibilityIdentifier("event.\(i)")
                        }
                    }
                }
            }

            if let speech = analysis.speech, let t = speech.transcript, !t.isEmpty {
                section("Transcript" + (speech.language.map { " (\($0))" } ?? ""), "quote.bubble") {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(t)
                            .lineLimit(showTranscript ? nil : 4)
                            .textSelection(.enabled)
                            .accessibilityIdentifier("transcript")
                        if t.count > 180 {
                            Button(showTranscript ? "Show less" : "Show all") { showTranscript.toggle() }
                                .font(.subheadline)
                        }
                    }
                }
            }

            tags("Objects", "cube", analysis.objects)
            tags("Animals", "pawprint", analysis.animals)
            tags("Brands", "bag", analysis.brands)
            tags("On-screen text", "textformat", analysis.onScreenText)

            if let music = analysis.music { section("Music", "music.note") { Text(music) } }
            if let mood = analysis.mood, !mood.isEmpty { section("Mood", "face.smiling") { Text(mood) } }
            if let context = analysis.context, !context.isEmpty { section("Context", "info.circle") { Text(context) } }
            tags("Keywords", "tag", analysis.keywords)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("analysis.section")
    }

    private func section<Content: View>(_ title: String, _ symbol: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(title, systemImage: symbol)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .accessibilityAddTraits(.isHeader)
            content().font(.body)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func basisText(_ text: String, basis: String?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(text)
            if let basis { Text("From: \(basis)").font(.caption).foregroundStyle(.secondary) }
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private func tags(_ title: String, _ symbol: String, _ list: [String]?) -> some View {
        if let list, !list.isEmpty {
            section(title, symbol) {
                FlowLayout(spacing: 6) {
                    ForEach(list, id: \.self) { t in
                        Text(t).font(.subheadline)
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(list.joined(separator: ", "))
            }
        }
    }
}

struct PersonRow: View {
    let person: Analysis.Person
    let playback: Playback

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: person.who == nil ? "person.fill.questionmark" : "person.fill")
                .frame(width: 24)
                .foregroundStyle(Theme.accent)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text(person.who ?? "Unnamed").font(.body.weight(.semibold))
                if let d = person.description, person.who != nil || person.description != nil { Text(d).font(.callout) }
                HStack(spacing: 6) {
                    if let role = person.role { Text(role) }
                    if let basis = person.basis { Text(basis == "description only" ? "Not named" : "Named from \(basis)") }
                }
                .font(.caption).foregroundStyle(.secondary)
                if let first = person.appears?.first, let from = first.from {
                    Button("Appears at \(TimeFormat.clock(from))") { playback.seek(media: first.media ?? 0, to: from) }
                        .font(.caption)
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibility)
    }

    private var accessibility: String {
        var parts = [person.who ?? "An unnamed person"]
        if let d = person.description { parts.append(d) }
        if let r = person.role { parts.append(r) }
        if let b = person.basis { parts.append(b == "description only" ? "described, not named" : "named from the \(b)") }
        return parts.joined(separator: ", ")
    }
}

struct EventRow: View {
    let event: Analysis.Event
    let mediaCount: Int
    let playback: Playback

    var body: some View {
        Button {
            if let at = event.at { playback.seek(media: event.media ?? 0, to: at) }
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(event.at.map(TimeFormat.clock) ?? "–")
                    .font(.callout.monospacedDigit().weight(.semibold))
                    .foregroundStyle(Theme.accent)
                    .frame(minWidth: 44, alignment: .leading)
                VStack(alignment: .leading, spacing: 1) {
                    Text(event.text).font(.callout).multilineTextAlignment(.leading)
                    if mediaCount > 1, let m = event.media {
                        Text("Slide \(m + 1)").font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical, 6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(event.at.map(TimeFormat.spoken) ?? ""): \(event.text)")
        .accessibilityHint("Plays the video from this moment")
    }
}

enum TimeFormat {
    static func clock(_ s: Double) -> String {
        let t = max(0, Int(s.rounded(.down)))
        return String(format: "%d:%02d", t / 60, t % 60)
    }

    static func spoken(_ s: Double) -> String {
        let t = max(0, Int(s.rounded(.down)))
        return t < 60 ? "\(t) seconds" : "\(t / 60) minutes \(t % 60) seconds"
    }
}
