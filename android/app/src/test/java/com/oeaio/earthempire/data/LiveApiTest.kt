package com.oeaio.earthempire.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith

/** The live client against a local server: requests, errors, and the offline copy. */
@RunWith(AndroidJUnit4::class)
class LiveApiTest {
    @get:Rule val tmp = TemporaryFolder()
    private val server = MockWebServer().apply { start() }
    private val client = OkHttpClient()

    @After fun stop() = runCatching { server.shutdown() }.let { }

    @Test fun requestsTheContractPaths() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"items":[{"id":"ig_1","kind":"post"}],"next":"abc"}"""))
        val api = LiveApi(server.url("/").toString(), client, OfflineStore(tmp.newFolder()))
        val page = api.items(ItemQuery(kind = ItemKind.Post, q = "sea cat"), before = "xyz", limit = 30)
        assertEquals("abc", page.next)
        val req = server.takeRequest()
        assertEquals("/v1/items?kind=post&q=sea%20cat&before=xyz&limit=30", req.path)
    }

    @Test fun notFoundIsReported() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(404))
        val api = LiveApi(server.url("/").toString(), client, null)
        try { api.item("ig_x"); fail() } catch (e: ApiException.NotFound) { }
    }

    @Test fun offlineFallsBackToTheLastAnswer() = runBlocking {
        val store = OfflineStore(tmp.newFolder())
        server.enqueue(MockResponse().setBody("""{"username":"earth","counts":{"posts":5}}"""))
        server.enqueue(MockResponse().setBody("""{"id":"ig_9","kind":"reel"}"""))
        val base = server.url("/").toString()
        val api = LiveApi(base, client, store)
        assertEquals("earth", api.profile().username)
        api.item("ig_9")
        assertFalse(api.offline.value)
        server.shutdown()
        val again = LiveApi(base, client, store)
        assertEquals(5L, again.profile().count("posts"))
        assertEquals(ItemKind.Reel, again.item("ig_9").kind)
        assertTrue(again.offline.value)
    }

    @Test fun monitorFallsBackToTheMockUntilTheEndpointsExist() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(404))
        val api = FallbackMonitorApi(LiveMonitorApi(server.url("/").toString(), client), MockMonitorApi(0))
        assertTrue(api.hits(null).hits.isNotEmpty())
        assertTrue(api.isMock)
        assertEquals("/v1/monitor?limit=30", server.takeRequest().path)
    }

    @Test fun ownerCallsSendTheAdminToken() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"phrases":[{"text":"тарас","variants":["тараса"]}]}"""))
        server.enqueue(MockResponse().setResponseCode(401))
        val api = LiveMonitorApi(server.url("/").toString(), client)
        assertEquals(listOf("тараса"), api.savePhrases(listOf("тарас"), "secret")[0].variants)
        val put = server.takeRequest()
        assertEquals("PUT", put.method)
        assertEquals("Bearer secret", put.getHeader("Authorization"))
        assertEquals("""{"phrases":[{"text":"тарас"}]}""", put.body.readUtf8())
        assertFalse(api.checkToken("wrong"))
        assertEquals("/v1/admin/me", server.takeRequest().path)
    }
}
