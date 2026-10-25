import SwiftUI

/// Every category Claude sorted the archive into, by count.
struct CategoriesView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        List(model.categories) { c in
            NavigationLink(value: Route.category(c.slug)) {
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(c.name).font(.headline)
                        Spacer()
                        Text("\(c.count ?? 0)").font(.subheadline.monospacedDigit()).foregroundStyle(.secondary)
                    }
                    if let d = c.description { Text(d).font(.subheadline).foregroundStyle(.secondary) }
                }
                .padding(.vertical, 2)
                .accessibilityElement(children: .combine)
            }
            .accessibilityIdentifier("category.\(c.slug)")
        }
        .overlay {
            if model.categories.isEmpty { ProgressView() }
        }
        .refreshable { await model.loadHome() }
        .navigationTitle("Categories")
        .task { if model.categories.isEmpty { await model.loadHome() } }
    }
}

/// One category: what it is, and its items with the kind filter.
struct CategoryView: View {
    let slug: String
    @Environment(AppModel.self) private var model
    @State private var kind: ItemKind?
    @State private var pager: Pager<Item>?

    var body: some View {
        let c = model.category(slug)
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: 6) {
                    if let d = c?.description { Text(d).font(.body) }
                    if let n = c?.count { Text("\(n) items").font(.subheadline).foregroundStyle(.secondary) }
                }
                .padding()
                FilterBar(kind: $kind, category: .constant(slug), showsCategories: false)
                    .padding(.bottom, 8)
                if let pager { ItemGrid(pager: pager) }
            }
        }
        .refreshable { await pager?.refresh() }
        .navigationTitle(c?.name ?? slug.capitalized)
        .toolbar {
            ShareLink(item: DeepLink.webURL(category: slug)) { Image(systemName: "square.and.arrow.up") }
                .accessibilityLabel("Share")
        }
        .task(id: [kind?.rawValue ?? "", String(model.apiGeneration)]) {
            let p = Pager.items(model.api, ItemQuery(kind: kind, category: slug))
            pager = p
            await p.loadIfNeeded()
        }
        .task { if model.categories.isEmpty { await model.loadHome() } }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("category.page")
    }
}

/// Where the archive comes from, and the caches.
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var base = AppConfig.apiBase.absoluteString
    @State private var sample = AppConfig.useSample
    @AppStorage(HomeMode.storageKey) private var mode: HomeMode = .tags

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Sample data", isOn: $sample)
                        .accessibilityIdentifier("settings.sample")
                    TextField("API base", text: $base)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .disabled(sample)
                    Button("Use \(AppConfig.defaultBase.absoluteString)") { base = AppConfig.defaultBase.absoluteString }
                        .disabled(sample)
                } header: {
                    Text("Source")
                } footer: {
                    Text("The public read API. Before empire.earth moves to AWS, use the backend's AWS hostname. Sample data is the bundled development fixture.")
                }
                Section("Home") {
                    Picker("Show", selection: $mode) {
                        ForEach(HomeMode.allCases) { Text($0.label).tag($0) }
                    }
                    .accessibilityIdentifier("settings.mode")
                }
                Section("Cache") {
                    Button("Clear saved items and media", role: .destructive) {
                        ResponseCache.shared.clear()
                        Task { await MediaCache.shared.clear() }
                    }
                }
                Section {
                    Link("empire.earth", destination: AppConfig.site)
                    Text("Every item is analyzed by Claude: who appears, what happens, when and where, what is said.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        if let u = URL(string: base.trimmingCharacters(in: .whitespaces)), u.scheme != nil { AppConfig.apiBase = u }
                        model.reconfigure(sample: sample)
                        dismiss()
                        Task { await model.loadHome() }
                    }
                    .accessibilityIdentifier("settings.done")
                }
            }
        }
    }
}
