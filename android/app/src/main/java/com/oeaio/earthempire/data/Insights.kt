package com.oeaio.earthempire.data

import java.time.YearMonth
import java.time.ZoneOffset

/**
 * What Home's infographics show, computed from the loaded items: a band of items per month, the
 * places on a map, tag and category bars, and per section panel its counts, people, places and
 * key moments.
 */
object Insights {
    data class Month(val month: YearMonth, val items: List<Item>, val hits: Int = 0) { val count get() = items.size + hits }

    /** Every month from the first item to the last, empty months included, oldest first. */
    fun months(items: List<Item>, hits: List<MonitorHit> = emptyList()): List<Month> {
        fun ym(s: String?) = Dates.parse(s)?.atZone(ZoneOffset.UTC)?.let { YearMonth.from(it) }
        val byMonth = items.groupBy { ym(it.takenAt) }.filterKeys { it != null }
        val hitMonths = hits.groupBy { ym(it.publishedAt ?: it.foundAt) }.filterKeys { it != null }.mapValues { it.value.size }
        val all = (byMonth.keys + hitMonths.keys).filterNotNull()
        if (all.isEmpty()) return emptyList()
        var m = all.min(); val last = all.max()
        return buildList {
            while (m <= last) {
                add(Month(m, byMonth[m].orEmpty().sortedBy { it.takenAt }, hitMonths[m] ?: 0)); m = m.plusMonths(1)
            }
        }
    }

    data class Place(val name: String, val lat: Double?, val lng: Double?, val items: List<Item>) { val count get() = items.size }

    /** Places by count: the item's location (with coordinates), else the analysis's place. */
    fun places(items: List<Item>): List<Place> {
        val groups = LinkedHashMap<String, MutableList<Item>>()
        val coords = HashMap<String, Pair<Double, Double>>()
        for (i in items) {
            val name = i.location?.name ?: i.analysis?.where?.place ?: continue
            val key = name.trim()
            groups.getOrPut(key) { mutableListOf() } += i
            val lat = i.location?.lat; val lng = i.location?.lng
            if (lat != null && lng != null && !(lat == 0.0 && lng == 0.0)) coords[key] = lat to lng
        }
        return groups.map { (k, v) -> Place(k, coords[k]?.first, coords[k]?.second, v) }
            .sortedWith(compareByDescending<Place> { it.count }.thenBy { it.name })
    }

    data class Bar(val label: String, val count: Int, val kind: String? = null)

    fun tagBars(tags: List<Tag>, max: Int = 12): List<Bar> =
        TagIndex.dedupe(tags).filter { it.kind != "category" }.take(max).map { Bar(it.tag, it.count, it.kind) }

    fun categoryBars(categories: List<Category>, max: Int = 10): List<Bar> =
        categories.filter { it.count > 0 }.sortedByDescending { it.count }.take(max).map { Bar(it.name.ifEmpty { it.slug }, it.count, it.slug) }

    data class Person(val who: String, val basis: String?, val count: Int)
    data class Moment(val item: Item, val media: Int, val at: Double, val text: String)

    data class Panel(
        val section: Section,
        val highlight: Highlight?,
        val items: List<Item>,
        val hits: List<MonitorHit>,
    ) {
        val title get() = highlight?.title ?: "Detected and published"
        val videos get() = items.count { it.hasVideo } + hits.count { it.playable != null }
        val first get() = items.mapNotNull { Dates.parse(it.takenAt) }.minOrNull()
        val last get() = items.mapNotNull { Dates.parse(it.takenAt) }.maxOrNull()

        /** People the posts themselves named (tag, mention, caption, speech, on-screen text), by how often. */
        val people: List<Person>
            get() = items.flatMap { it.analysis?.people.orEmpty() }.filter { it.who != null && it.basis != "description only" }
                .groupBy { it.who!!.trim() }.map { (who, ps) -> Person(who, ps.mapNotNull { it.basis }.groupingBy { it }.eachCount().maxByOrNull { it.value }?.key, ps.size) }
                .sortedWith(compareByDescending<Person> { it.count }.thenBy { it.who })

        val places get() = places(items)

        /** The analysis's video moments, one or two per item, newest items first. */
        val moments: List<Moment>
            get() = items.sortedByDescending { it.takenAt }.flatMap { i ->
                i.analysis?.events.orEmpty().filter { i.allMedia.getOrNull(it.media)?.isVideo == true }.take(2).map { Moment(i, it.media, it.at, it.text) }
            }
    }

    /**
     * The panels of Home: each dedicated highlight, then each common one, with its items in the
     * highlight's order; published hits join a "Detected" panel of their section; archive items in
     * no highlight make the last common panel.
     */
    fun panels(items: List<Item>, highlights: List<Highlight>, published: List<MonitorHit>): List<Panel> {
        val byId = items.associateBy { it.id }
        val used = HashSet<String>()
        fun highlightItems(h: Highlight): List<Item> {
            val listed = h.itemIds.mapNotNull { byId[it] }
            val tagged = items.filter { i -> i.highlights.any { it.id == h.id } && i.id !in h.itemIds }.sortedBy { it.takenAt }
            return (listed + tagged).also { l -> used += l.map { it.id } }
        }
        val out = mutableListOf<Panel>()
        for (section in Section.entries) {
            val hits = published.filter { it.homeSection == section }
            if (hits.isNotEmpty()) out += Panel(section, null, emptyList(), hits)
            highlights.filter { it.homeSection == section }.forEach { h ->
                val list = highlightItems(h)
                if (list.isNotEmpty()) out += Panel(section, h, list, emptyList())
            }
        }
        val rest = items.filter { it.id !in used }.sortedByDescending { it.takenAt }
        if (rest.isNotEmpty()) out += Panel(Section.Common, Highlight("posts", "Posts and reels"), rest, emptyList())
        return out
    }
}

/** Orders a highlight's stories by its `item_ids`; stories it does not list go last, oldest first. */
fun orderStories(items: List<Item>, ids: List<String>): List<Item> {
    val pos = ids.withIndex().associate { it.value to it.index }
    return items.sortedWith(compareBy<Item> { pos[it.id] ?: Int.MAX_VALUE }.thenBy { it.takenAt })
}
