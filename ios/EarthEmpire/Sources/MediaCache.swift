import AVFoundation
import SwiftUI
import UIKit

/// Images and videos on disk under Caches/media, keyed by the URL's hash, plus decoded images in
/// memory. Anything shown once shows again offline.
actor MediaCache {
    static let shared = MediaCache()

    private let root: URL
    private nonisolated(unsafe) let memory = NSCache<NSURL, UIImage>()
    private var inFlight: [URL: Task<Data, Error>] = [:]
    private let session: URLSession

    init() {
        root = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appending(path: "media")
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        memory.totalCostLimit = 120 * 1024 * 1024
        let config = URLSessionConfiguration.default
        config.requestCachePolicy = .reloadIgnoringLocalCacheData // the disk files are the cache
        session = URLSession(configuration: config)
    }

    nonisolated func file(for url: URL) -> URL {
        let ext = url.pathExtension.isEmpty ? "bin" : url.pathExtension
        return root.appending(path: Hashing.sha256(url.absoluteString) + "." + ext)
    }

    /// A playable local file for a video URL if it is cached (or bundled), else nil.
    nonisolated func cachedFile(for url: URL) -> URL? {
        if url.isFileURL { return url }
        let f = file(for: url)
        return FileManager.default.fileExists(atPath: f.path) ? f : nil
    }

    func data(for url: URL) async throws -> Data {
        if url.isFileURL { return try Data(contentsOf: url) }
        let f = file(for: url)
        if let d = try? Data(contentsOf: f) { return d }
        if let task = inFlight[url] { return try await task.value }
        let session = session
        let task = Task<Data, Error> {
            let (data, response) = try await session.data(from: url)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 200
            guard (200..<300).contains(code) else {
                log.error("media \(url.absoluteString, privacy: .public) -> \(code)")
                throw APIError.status(code, url.path)
            }
            try? data.write(to: f, options: .atomic)
            return data
        }
        inFlight[url] = task
        defer { inFlight[url] = nil }
        return try await task.value
    }

    func image(for url: URL) async throws -> UIImage {
        if let img = memory.object(forKey: url as NSURL) { return img }
        let data = try await data(for: url)
        guard let img = UIImage(data: data)?.preparingForDisplay() ?? UIImage(data: data) else {
            throw APIError.status(0, url.path)
        }
        memory.setObject(img, forKey: url as NSURL, cost: data.count)
        return img
    }

    nonisolated func memoryImage(for url: URL) -> UIImage? { memory.object(forKey: url as NSURL) }

    /// Downloads a video in the background so the next play (and offline) uses the file.
    func prefetchVideo(_ url: URL) {
        guard !url.isFileURL, cachedFile(for: url) == nil, inFlight[url] == nil else { return }
        Task { _ = try? await data(for: url) }
    }

    func clear() {
        memory.removeAllObjects()
        try? FileManager.default.removeItem(at: root)
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }
}

/// An image from the archive, from the cache when it has it.
struct RemoteImage: View {
    let url: URL?
    var contentMode: ContentMode = .fill
    var accessibilityLabel: String? = nil

    @State private var image: UIImage?
    @State private var failed = false

    init(_ string: String?, contentMode: ContentMode = .fill, accessibilityLabel: String? = nil) {
        url = MediaURL.resolve(string)
        self.contentMode = contentMode
        self.accessibilityLabel = accessibilityLabel
    }

    init(url: URL?, contentMode: ContentMode = .fill, accessibilityLabel: String? = nil) {
        self.url = url.map(MediaURL.resolve)
        self.contentMode = contentMode
        self.accessibilityLabel = accessibilityLabel
    }

    var body: some View {
        ZStack {
            if let image = image ?? url.flatMap({ MediaCache.shared.memoryImage(for: $0) }) {
                Image(uiImage: image).resizable().aspectRatio(contentMode: contentMode)
            } else {
                Rectangle().fill(.quaternary)
                    .overlay {
                        if failed { Image(systemName: "photo").foregroundStyle(.secondary) }
                    }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityLabel ?? "")
        .accessibilityHidden(accessibilityLabel == nil)
        .task(id: url) {
            guard let url else { failed = true; return }
            do { image = try await MediaCache.shared.image(for: url) } catch { failed = true }
        }
    }
}

extension AVPlayer {
    /// A player for an archive video: the cached file when there is one, else the stream (and
    /// the file is fetched meanwhile for next time).
    static func archive(_ string: String) -> AVPlayer? {
        guard let url = MediaURL.resolve(string) else { return nil }
        if let local = MediaCache.shared.cachedFile(for: url) { return AVPlayer(url: local) }
        Task { await MediaCache.shared.prefetchVideo(url) }
        return AVPlayer(url: url)
    }
}
