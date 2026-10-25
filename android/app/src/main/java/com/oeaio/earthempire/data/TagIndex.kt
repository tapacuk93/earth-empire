package com.oeaio.earthempire.data

/**
 * The tags of items the way `GET /v1/tags` derives them (lowercase, by kind), for sample mode,
 * where there is no server to ask.
 */
object TagIndex {
    fun tags(item: Item): List<Pair<String, String>> = buildList {
        item.categories.forEach { add(it to "category") }
        item.hashtags.forEach { add(it to "hashtag") }
        item.analysis?.let { a ->
            a.keywords.forEach { add(it to "keyword") }
            a.objects.forEach { add(it to "object") }
            a.animals.forEach { add(it to "animal") }
            a.brands.forEach { add(it to "brand") }
            a.where?.place?.let { add(it to "place") }
            a.where?.country?.let { add(it to "country") }
            a.mood?.let { add(it to "mood") }
            a.`when`?.occasion?.let { add(it to "occasion") }
            a.people.filter { it.basis in setOf("tag", "mention", "caption") }.mapNotNull { it.who }.forEach { add(it.removePrefix("@") to "person") }
        }
        item.location?.name?.let { add(it to "place") }
    }.map { it.first.trim().lowercase() to it.second }.filter { it.first.isNotEmpty() }.distinct()

    fun cloud(items: List<Item>): List<Tag> =
        items.flatMap(::tags).groupingBy { it }.eachCount()
            .map { (k, n) -> Tag(k.first, k.second, n) }
            .sortedWith(compareByDescending<Tag> { it.count }.thenBy { it.tag })

    /** One entry per tag text (a tag can come under two kinds), keeping its most common kind. */
    fun dedupe(tags: List<Tag>): List<Tag> =
        tags.groupBy { it.tag }.values.map { same -> same.maxBy { it.count } }
            .sortedWith(compareByDescending<Tag> { it.count }.thenBy { it.tag })
}
