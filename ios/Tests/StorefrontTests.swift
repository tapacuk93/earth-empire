import AICoinKit
import XCTest
@testable import Earth_Empire

/// On the China mainland storefront nothing names OpenAI; elsewhere everything is as before.
final class StorefrontTests: XCTestCase {
    override func tearDown() {
        AICoinStorefront.override(nil)
        super.tearDown()
    }

    private func analysis(_ model: String?, _ provider: String? = nil) -> Analysis {
        var a = try! APIDecoding.decoder.decode(Analysis.self, from: Data("{}".utf8))
        a.model = model
        a.provider = provider
        return a
    }

    func testProviderFromModelName() {
        XCTAssertEqual(StorefrontRules.proxyProvider(model: "gpt-5", provider: nil), "openai")
        XCTAssertEqual(StorefrontRules.proxyProvider(model: "whisper-1", provider: nil), "openai")
        XCTAssertEqual(StorefrontRules.proxyProvider(model: "claude-sonnet-5-5", provider: nil), "anthropic")
        XCTAssertEqual(StorefrontRules.proxyProvider(model: "gemini-3.5-flash", provider: nil), "google")
        XCTAssertEqual(StorefrontRules.proxyProvider(model: "x", provider: "OpenAI"), "openai")
    }

    func testChinaHidesOpenAICreditOnly() {
        AICoinStorefront.override("CHN")
        XCTAssertNil(StorefrontRules.creditedModel(analysis("gpt-5", "openai")))
        XCTAssertNil(StorefrontRules.creditedModel(analysis("gpt-5")))
        XCTAssertNil(StorefrontRules.creditedModel(analysis("gpt-5-2025-08-07", nil)))
        XCTAssertEqual(StorefrontRules.creditedModel(analysis("claude-sonnet-5-5", "anthropic")), "claude-sonnet-5-5")
        XCTAssertEqual(StorefrontRules.creditedModel(analysis("gemini-3.5-flash", "google")), "gemini-3.5-flash")
    }

    func testOtherStorefrontsShowEveryCredit() {
        AICoinStorefront.override("USA")
        XCTAssertEqual(StorefrontRules.creditedModel(analysis("gpt-5", "openai")), "gpt-5")
        XCTAssertEqual(StorefrontRules.creditedModel(analysis("claude-opus-5-5")), "claude-opus-5-5")
        XCTAssertNil(StorefrontRules.creditedModel(analysis(nil)))
    }

    func testProviderDecodes() throws {
        let a = try APIDecoding.decoder.decode(Analysis.self, from: Data(#"{"model": "gpt-5", "provider": "openai"}"#.utf8))
        XCTAssertEqual(a.provider, "openai")
    }

    func testRequestsCarryTheStorefront() {
        let api = LiveAPI(base: URL(string: "https://api.example.test")!)
        AICoinStorefront.override("CHN")
        XCTAssertEqual(api.request(api.url("v1/items")).value(forHTTPHeaderField: AICoinStorefront.headerName), "CHN")
        XCTAssertEqual(api.request(api.url("v1/items")).value(forHTTPHeaderField: "Accept"), "application/json")
    }
}
