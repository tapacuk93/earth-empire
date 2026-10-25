import CryptoKit
import Foundation

/// Where the app reads the archive from.
///
/// - `EEAPIBase` (UserDefaults, so also the launch argument `-EEAPIBase <url>`): the API base;
///   default is the Info.plist's `EEAPIBase`, `https://api.empire.earth`. Before DNS moves, set it
///   to the backend's AWS hostname in Settings.
/// - `EESample` (UserDefaults / `-EESample YES`): read the bundled fixture instead of the API.
enum AppConfig {
    static let defaultBase = URL(string: Bundle.main.object(forInfoDictionaryKey: "EEAPIBase") as? String ?? "")
        ?? URL(string: "https://api.empire.earth")!

    static var apiBase: URL {
        get {
            if let s = UserDefaults.standard.string(forKey: "EEAPIBase"), let u = URL(string: s), u.scheme != nil { return u }
            return defaultBase
        }
        set { UserDefaults.standard.set(newValue.absoluteString, forKey: "EEAPIBase") }
    }

    static var useSample: Bool {
        get { UserDefaults.standard.bool(forKey: "EESample") }
        set { UserDefaults.standard.set(newValue, forKey: "EESample") }
    }

    /// The public site, for share links and Universal Links.
    static let site = URL(string: "https://empire.earth")!
    /// Media host whose keys the fixture carries under `Fixture/media/`.
    static let mediaHost = "media.empire.earth"
}

/// Media URLs as the app loads them: in sample mode, `https://media.empire.earth/<key>` comes
/// from the bundle's `Fixture/media/<key>`.
enum MediaURL {
    nonisolated(unsafe) static var sampleMode = false

    static func resolve(_ string: String?) -> URL? {
        guard let string, let url = URL(string: string) else { return nil }
        return resolve(url)
    }

    static func resolve(_ url: URL) -> URL {
        guard sampleMode, url.host == AppConfig.mediaHost,
              let root = Bundle.main.resourceURL?.appending(path: "Fixture/media") else { return url }
        let local = root.appending(path: String(url.path.dropFirst()))
        return FileManager.default.fileExists(atPath: local.path) ? local : url
    }
}

enum Hashing {
    static func sha256(_ s: String) -> String {
        SHA256.hash(data: Data(s.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func safeName(_ s: String) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_-."))
        let cleaned = String(s.unicodeScalars.map { allowed.contains($0) ? Character($0) : "_" })
        return cleaned.isEmpty || cleaned.count > 100 ? sha256(s) : cleaned
    }
}
