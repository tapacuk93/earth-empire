import AICoinKit
import Foundation

/// What the App Store storefront allows this app to show (AICoinStorefront, from AICoinKit).
///
/// The app makes no AI calls itself: the backend analyses every item once, with Claude and, when
/// Claude's side fails, Gemini or OpenAI, and the app only shows the result. On the China mainland
/// storefront OpenAI may not be named, so the "Analyzed by" credit is left out when OpenAI wrote it.
enum StorefrontRules {
    /// The proxy provider behind an analysis: its own `provider`, else read from the model name.
    static func proxyProvider(model: String?, provider: String?) -> String? {
        if let p = provider?.trimmingCharacters(in: .whitespaces).lowercased(), !p.isEmpty { return p }
        guard let m = model?.trimmingCharacters(in: .whitespaces).lowercased(), !m.isEmpty else { return nil }
        if m.hasPrefix("claude") { return "anthropic" }
        if m.hasPrefix("gemini") { return "google" }
        let openAI = ["gpt", "chatgpt", "o1", "o3", "o4", "dall-e", "dall·e", "whisper", "openai", "tts-", "text-embedding"]
        if openAI.contains(where: { m.hasPrefix($0) }) { return "openai" }
        return nil
    }

    /// The model to credit under an item, or nil when there is none or the storefront withholds
    /// its provider.
    static func creditedModel(_ analysis: Analysis) -> String? {
        guard let model = analysis.model, !model.isEmpty else { return nil }
        if let provider = proxyProvider(model: model, provider: analysis.provider),
           !AICoinStorefront.allows(proxyProvider: provider) { return nil }
        return model
    }
}
