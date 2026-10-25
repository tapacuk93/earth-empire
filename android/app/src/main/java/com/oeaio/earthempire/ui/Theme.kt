package com.oeaio.earthempire.ui

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

// The iOS app's accent (0.12, 0.55, 0.45) and story ring.
val Accent = Color(0xFF1F8C73)
val Ring = Brush.linearGradient(listOf(Color(0xFFFF9500), Color(0xFFFF2D55), Color(0xFFAF52DE)))

private val Light = lightColorScheme(
    primary = Accent, onPrimary = Color.White,
    primaryContainer = Color(0xFFBDEFE0), onPrimaryContainer = Color(0xFF00201A),
    secondary = Color(0xFF4A635B), tertiary = Color(0xFF3F6375),
)
private val Dark = darkColorScheme(
    primary = Color(0xFF7BD8BD), onPrimary = Color(0xFF00382D),
    primaryContainer = Color(0xFF005141), onPrimaryContainer = Color(0xFFBDEFE0),
    secondary = Color(0xFFB1CCC2), tertiary = Color(0xFFA7CBDF),
)

/** [mode] is "system", "light" or "dark"; [dynamic] uses the wallpaper's colors on Android 12+. */
@Composable
fun EarthEmpireTheme(mode: String = "system", dynamic: Boolean = false, content: @Composable () -> Unit) {
    val dark = when (mode) { "dark" -> true; "light" -> false; else -> isSystemInDarkTheme() }
    val scheme = when {
        dynamic && Build.VERSION.SDK_INT >= 31 -> if (dark) dynamicDarkColorScheme(LocalContext.current) else dynamicLightColorScheme(LocalContext.current)
        dark -> Dark
        else -> Light
    }
    MaterialTheme(colorScheme = scheme, content = content)
}

fun tagColor(kind: String): Color = when (kind) {
    "category" -> Accent
    "place", "country" -> Color(0xFF2F7FD0)
    "person" -> Color(0xFFD9822B)
    "object", "brand" -> Color(0xFF7A5BC7)
    "animal" -> Color(0xFF8C6D1F)
    "hashtag" -> Color(0xFFC2185B)
    "mood", "occasion" -> Color(0xFF00838F)
    else -> Color(0xFF607D8B)
}

fun statusColor(status: String): Color = when (status) {
    "ok" -> Color(0xFF2E9E5B)
    "degraded" -> Color(0xFFE0A100)
    "down" -> Color(0xFFD93A3A)
    else -> Color(0xFF8A8F98)
}
