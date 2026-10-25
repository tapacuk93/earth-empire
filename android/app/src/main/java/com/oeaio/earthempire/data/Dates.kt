package com.oeaio.earthempire.data

import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale

object Dates {
    /** ISO 8601 (UTC "Z" or with an offset, with or without fractions), or a bare date. */
    fun parse(s: String?): Instant? {
        if (s.isNullOrBlank()) return null
        return runCatching { Instant.parse(s) }.getOrNull()
            ?: runCatching { OffsetDateTime.parse(s).toInstant() }.getOrNull()
            ?: runCatching { LocalDate.parse(s.take(10)).atStartOfDay(ZoneId.of("UTC")).toInstant() }.getOrNull()
    }

    var zone: ZoneId = ZoneId.systemDefault()

    fun long(i: Instant): String =
        DateTimeFormatter.ofLocalizedDate(FormatStyle.LONG).withLocale(Locale.getDefault()).format(i.atZone(zone))

    fun medium(i: Instant): String =
        DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM).withLocale(Locale.getDefault()).format(i.atZone(zone))

    fun dateTime(i: Instant): String =
        DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM, FormatStyle.SHORT).withLocale(Locale.getDefault()).format(i.atZone(zone))

    fun monthTitle(i: Instant): String =
        DateTimeFormatter.ofPattern("LLLL yyyy", Locale.getDefault()).format(i.atZone(zone))

    /** "1:05" / "1:02:03" for a time in a video. */
    fun clock(seconds: Double): String {
        val t = seconds.toLong().coerceAtLeast(0)
        val h = t / 3600; val m = (t % 3600) / 60; val s = t % 60
        return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
    }

    fun compact(n: Long): String = when {
        n >= 1_000_000 -> "%.1fM".format(Locale.US, n / 1_000_000.0).replace(".0M", "M")
        n >= 10_000 -> "%dK".format(n / 1000)
        n >= 1_000 -> "%.1fK".format(Locale.US, n / 1000.0).replace(".0K", "K")
        else -> n.toString()
    }
}
