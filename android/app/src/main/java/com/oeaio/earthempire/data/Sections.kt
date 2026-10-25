package com.oeaio.earthempire.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * Home's two parts: the owner's dedicated highlights first, then the common ones.
 *
 * PROVISIONAL until CONTRACT.md defines sections, read the same way as the site
 * (web/src/sections.ts): a highlight is dedicated when the API marks it (`section: "dedicated"`,
 * `kind: "dedicated"` or `dedicated: true`); every other highlight is common. A published hit goes
 * to the part in its `section` (default common); `suggested_section` is the monitor's suggestion,
 * a string or `{"section", "reason"}`.
 */
enum class Section(val wire: String, val title: String) {
    Dedicated("dedicated", "About the owner"),
    Common("common", "Everything else");

    companion object {
        fun of(e: JsonElement?): Section? = when (e) {
            is JsonPrimitive -> parse(e.contentOrNull)
            is JsonObject -> of(e["id"] ?: e["section"])
            else -> null
        }

        fun parse(s: String?) = when (s?.lowercase()) { "dedicated", "owner" -> Dedicated; "common" -> Common; else -> null }
    }
}

val Highlight.homeSection: Section
    get() = Section.of(section) ?: Section.parse(kind) ?: if (dedicated == true) Section.Dedicated else Section.Common

val MonitorHit.homeSection: Section get() = Section.of(section) ?: Section.Common

/** The monitor's suggestion for where a hit belongs, and why. */
data class SectionSuggestion(val section: Section, val reason: String?)

val MonitorHit.suggestion: SectionSuggestion?
    get() {
        val s = Section.of(suggestedSection) ?: return null
        val reason = ((suggestedSection as? JsonObject)?.get("reason") as? JsonPrimitive)?.contentOrNull ?: sectionReason
        return SectionSuggestion(s, reason)
    }

@Serializable
data class PhraseSuggestion(val text: String, val reason: String? = null, val highlight: String? = null)

@Serializable
data class PhraseSuggestions(val suggestions: List<PhraseSuggestion> = emptyList())

@Serializable
@Suppress("unused")
private class RejectBody(@SerialName("text") val text: String)
