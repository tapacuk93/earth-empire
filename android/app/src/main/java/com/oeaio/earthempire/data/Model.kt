package com.oeaio.earthempire.data

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull

// The shapes of CONTRACT.md ("The data"), decoded leniently: every field the backend may leave
// out has a default, unknown keys are ignored, an unknown `kind` still decodes, and `extra`
// keeps whatever JSON it holds.

val ContractJson = Json {
    ignoreUnknownKeys = true
    coerceInputValues = true
    explicitNulls = false
    isLenient = true
}

@Serializable(with = ItemKind.Serializer::class)
enum class ItemKind(val wire: String, val label: String) {
    Post("post", "Post"),
    Carousel("carousel", "Carousel"),
    Reel("reel", "Reel"),
    Story("story", "Story"),
    Unknown("unknown", "Item");

    companion object {
        val filters = listOf(Post, Carousel, Reel, Story)
        fun of(s: String?): ItemKind? = entries.firstOrNull { it.wire == s?.lowercase() }
    }

    object Serializer : KSerializer<ItemKind> {
        override val descriptor = PrimitiveSerialDescriptor("ItemKind", PrimitiveKind.STRING)
        override fun deserialize(decoder: Decoder) = of(decoder.decodeString()) ?: Unknown
        override fun serialize(encoder: Encoder, value: ItemKind) = encoder.encodeString(value.wire)
    }
}

@Serializable
data class Item(
    val id: String,
    val kind: ItemKind = ItemKind.Unknown,
    val shortcode: String? = null,
    @SerialName("source_url") val sourceUrl: String? = null,
    @SerialName("taken_at") val takenAt: String? = null,
    val caption: String? = null,
    val hashtags: List<String> = emptyList(),
    val mentions: List<String> = emptyList(),
    @SerialName("tagged_users") val taggedUsers: List<TaggedUser> = emptyList(),
    val location: Location? = null,
    val music: Music? = null,
    @SerialName("alt_text") val altText: String? = null,
    val stickers: List<Sticker> = emptyList(),
    val counts: JsonObject? = null,
    val media: List<Media> = emptyList(),
    val highlights: List<HighlightRef> = emptyList(),
    @SerialName("repost_of") val repostOf: Repost? = null,
    val categories: List<String> = emptyList(),
    val summary: String? = null,
    val description: String? = null,
    val analysis: Analysis? = null,
    val extra: JsonObject? = null,
    @SerialName("collected_at") val collectedAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("published_at") val publishedAt: String? = null,
) {
    val isRepost get() = repostOf != null

    fun count(key: String): Long? = counts.countOf(key)

    /**
     * Every media in the order the analysis numbers them: the item's own, then the original's
     * (CONTRACT "Analysis": `media` indices in `events` and `appears` count across both).
     */
    val allMedia: List<Media> get() = media + (repostOf?.media ?: emptyList())

    /** The picture that stands for the item in a grid. */
    val poster: String? get() = (media.firstOrNull() ?: repostOf?.media?.firstOrNull())?.poster

    val hasVideo get() = allMedia.any { it.isVideo }

    val accessibilityLabel: String
        get() = buildString {
            append(if (repostOf != null) "${kind.label}, repost of @${repostOf.author}" else kind.label)
            Dates.parse(takenAt)?.let { append(", "); append(Dates.long(it)) }
            (summary ?: caption)?.let { append(". "); append(it.take(140)) }
        }
}

@Serializable
data class TaggedUser(val username: String, val x: Double? = null, val y: Double? = null)

@Serializable
data class Location(val name: String? = null, val id: String? = null, val lat: Double? = null, val lng: Double? = null)

@Serializable
data class Music(val title: String? = null, val artist: String? = null) {
    val label get() = listOfNotNull(title, artist).joinToString(" · ")
}

@Serializable
data class Sticker(val type: String = "", val text: String? = null, val extra: JsonObject? = null)

@Serializable
data class Media(
    val type: String = "image",
    val url: String,
    val thumbnail: String? = null,
    val width: Int? = null,
    val height: Int? = null,
    val duration: Double? = null,
    val cover: String? = null,
    @SerialName("cover_at") val coverAt: Double? = null,
) {
    val isVideo get() = type == "video"

    /** A video's AI-chosen cover frame, else its thumbnail, else the file itself. */
    val poster: String get() = cover ?: thumbnail ?: url

    val aspect: Float
        get() = if (width != null && height != null && width > 0 && height > 0) width.toFloat() / height else 1f
}

@Serializable
data class HighlightRef(val id: String, val title: String? = null)

@Serializable
data class Repost(
    val author: String = "",
    @SerialName("author_name") val authorName: String? = null,
    val shortcode: String? = null,
    @SerialName("source_url") val sourceUrl: String? = null,
    @SerialName("taken_at") val takenAt: String? = null,
    val caption: String? = null,
    val media: List<Media> = emptyList(),
)

@Serializable
data class Analysis(
    val people: List<Person> = emptyList(),
    val what: String? = null,
    val events: List<Event> = emptyList(),
    val `when`: When? = null,
    val where: Where? = null,
    val objects: List<String> = emptyList(),
    val animals: List<String> = emptyList(),
    val brands: List<String> = emptyList(),
    @SerialName("on_screen_text") val onScreenText: List<String> = emptyList(),
    val speech: Speech? = null,
    val music: String? = null,
    val mood: String? = null,
    val language: String? = null,
    val context: String? = null,
    val keywords: List<String> = emptyList(),
    val model: String? = null,
    @SerialName("analyzed_at") val analyzedAt: String? = null,
)

@Serializable
data class Person(
    val who: String? = null,
    val description: String? = null,
    val basis: String? = null,
    val role: String? = null,
    val appears: List<Span> = emptyList(),
)

@Serializable
data class Span(val media: Int = 0, val from: Double? = null, val to: Double? = null)

@Serializable
data class Event(val media: Int = 0, val at: Double = 0.0, val text: String = "")

@Serializable
data class When(
    val date: String? = null,
    @SerialName("time_of_day") val timeOfDay: String? = null,
    val season: String? = null,
    val occasion: String? = null,
    val basis: String? = null,
)

@Serializable
data class Where(
    val place: String? = null,
    val kind: String? = null,
    val country: String? = null,
    val basis: String? = null,
)

@Serializable
data class Speech(val language: String? = null, val transcript: String? = null)

@Serializable
data class Highlight(
    val id: String,
    val title: String = "",
    val cover: String? = null,
    @SerialName("item_ids") val itemIds: List<String> = emptyList(),
    @SerialName("updated_at") val updatedAt: String? = null,
    // Which part of Home it belongs to (provisional; see Sections.kt).
    val section: kotlinx.serialization.json.JsonElement? = null,
    val kind: String? = null,
    val dedicated: Boolean? = null,
)

@Serializable
data class Category(val slug: String, val name: String = "", val description: String? = null, val count: Int = 0)

@Serializable
data class Profile(
    val username: String = "",
    @SerialName("full_name") val fullName: String? = null,
    val bio: String? = null,
    val avatar: String? = null,
    val links: List<String> = emptyList(),
    val counts: JsonObject? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
) {
    fun count(key: String): Long? = counts.countOf(key)
}

@Serializable
data class Tag(val tag: String, val kind: String = "keyword", val count: Int = 0)

// Response envelopes.
@Serializable
data class ItemPage(val items: List<Item> = emptyList(), val next: String? = null)

@Serializable
data class HighlightList(val highlights: List<Highlight> = emptyList())

@Serializable
data class CategoryList(val categories: List<Category> = emptyList())

@Serializable
data class TagList(val tags: List<Tag> = emptyList())

/** What the home grid asks `GET /v1/items` for. */
data class ItemQuery(
    val kind: ItemKind? = null,
    val category: String? = null,
    val highlight: String? = null,
    val tag: String? = null,
    val q: String? = null,
) {
    val isEmpty get() = kind == null && category.isNullOrEmpty() && highlight.isNullOrEmpty() && tag.isNullOrEmpty() && q.isNullOrEmpty()

    fun params(): List<Pair<String, String>> = buildList {
        kind?.let { add("kind" to it.wire) }
        category?.takeIf { it.isNotEmpty() }?.let { add("category" to it) }
        highlight?.takeIf { it.isNotEmpty() }?.let { add("highlight" to it) }
        tag?.takeIf { it.isNotEmpty() }?.let { add("tag" to it) }
        q?.takeIf { it.isNotBlank() }?.let { add("q" to it.trim()) }
    }
}

/** A fixture: the same shapes as the API, all in one file (ios/Fixture/fixture.json). */
@Serializable
data class Fixture(
    val profile: Profile = Profile(),
    val highlights: List<Highlight> = emptyList(),
    val categories: List<Category> = emptyList(),
    val items: List<Item> = emptyList(),
)

/** A count the source showed, whatever number type it came as; absent when it was not shown. */
fun JsonObject?.countOf(key: String): Long? =
    (this?.get(key) as? JsonPrimitive)?.doubleOrNull?.toLong()
