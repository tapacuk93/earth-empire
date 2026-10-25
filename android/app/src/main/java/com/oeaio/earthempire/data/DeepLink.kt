package com.oeaio.earthempire.data

import android.net.Uri

/**
 * A place in the app, from an empire.earth URL (App Link) or an `earthempire://` one.
 *
 * The paths are the site's routes (web/src/main.tsx), the same ones the iOS app takes:
 *   /                          the archive home; `?q=`, `?kind=`, `?category=`, `?tag=`, `?view=`
 *   /item/<id>                 an item (also /i/<id>, /items/<id>, /p/<id>, /reel/<id>)
 *   /category/<slug>           a category (also /c/<slug>, /categories/<slug>); `?kind=`
 *   /highlight/<id>?item=<id>  a highlight in the story viewer (also /highlight/<id>/<item>)
 *   /search?q=…                the home grid searched
 *   /monitor                   the monitor (the app's main tab), /monitor/<hit id> one hit
 * `earthempire://item/<id>` and the like take the same paths with the first one as the host.
 */
sealed interface DeepLink {
    data object Monitor : DeepLink
    data class MonitorHit(val id: String) : DeepLink
    data class Home(val query: ItemQuery = ItemQuery(), val view: String? = null) : DeepLink
    data class Item(val id: String) : DeepLink
    data class Category(val slug: String, val kind: ItemKind? = null) : DeepLink
    data object Categories : DeepLink
    data class Highlight(val id: String, val item: String? = null) : DeepLink

    companion object {
        const val SITE = "https://empire.earth"

        fun parse(url: String): DeepLink? = runCatching { parse(Uri.parse(url)) }.getOrNull()

        fun parse(uri: Uri): DeepLink? {
            val scheme = uri.scheme?.lowercase() ?: return null
            val parts = uri.pathSegments.filter { it.isNotEmpty() }.toMutableList()
            when {
                scheme == "earthempire" -> uri.host?.takeIf { it.isNotEmpty() }?.let { parts.add(0, it) }
                scheme == "http" || scheme == "https" -> {
                    val host = uri.host?.lowercase() ?: return null
                    if (!(host == "empire.earth" || host.endsWith(".empire.earth") || host.endsWith("cloudfront.net") || host == "localhost")) return null
                }
                else -> return null
            }
            // A hash route (`/#/item/x`) reads like a path.
            uri.fragment?.takeIf { it.startsWith("/") }?.let { f -> parts += f.split("/").filter { it.isNotEmpty() } }

            fun param(name: String) = uri.getQueryParameter(name)?.takeIf { it.isNotEmpty() }
            val q = param("q")
            val first = parts.firstOrNull()?.lowercase()
                ?: return Home(ItemQuery(ItemKind.of(param("kind")), param("category"), null, param("tag"), q), param("view"))
            val second = parts.getOrNull(1)
            return when (first) {
                "item", "items", "i", "p", "reel", "reels", "post", "tv" -> second?.let { Item(normalizeItemId(it)) }
                "category", "categories", "c" -> if (second != null) Category(second, ItemKind.of(param("kind"))) else Categories
                "highlight", "highlights", "h" -> second?.let { Highlight(it, (parts.getOrNull(2) ?: param("item"))?.let(::normalizeItemId)) }
                "stories" -> if (second == "highlights" && parts.size > 2) Highlight(parts[2]) else second?.let { Item(normalizeItemId(it)) }
                "search" -> Home(ItemQuery(q = q ?: second ?: ""))
                "monitor" -> if (second != null) MonitorHit(second) else Monitor
                "archive" -> Home()
                else -> null
            }
        }

        /** Item ids are `ig_<pk>`; a bare pk gets the prefix. */
        fun normalizeItemId(s: String) = if (s.isNotEmpty() && s.all { it.isDigit() }) "ig_$s" else s

        fun webUrl(link: DeepLink): String = when (link) {
            is Item -> "$SITE/item/${Uri.encode(link.id)}"
            is Category -> "$SITE/category/${Uri.encode(link.slug)}"
            is Highlight -> "$SITE/highlight/${Uri.encode(link.id)}" + (link.item?.let { "?item=${Uri.encode(it)}" } ?: "")
            is MonitorHit -> "$SITE/monitor/${Uri.encode(link.id)}"
            Monitor -> "$SITE/monitor"
            Categories -> "$SITE/categories"
            is Home -> SITE + "/" + link.query.params().joinToString("&", prefix = if (link.query.isEmpty) "" else "?") { (k, v) -> "$k=${Uri.encode(v)}" }
        }
    }
}
