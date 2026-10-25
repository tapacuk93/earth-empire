package com.oeaio.earthempire.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Science
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.oeaio.earthempire.data.MediaUrls

/** A remote picture (resolved for sample mode), with a neutral placeholder while it loads. */
@Composable
fun RemoteImage(url: String?, description: String?, modifier: Modifier = Modifier, scale: ContentScale = ContentScale.Crop) {
    Box(modifier.background(MaterialTheme.colorScheme.surfaceVariant)) {
        if (url != null) AsyncImage(MediaUrls.resolve(url), description, Modifier.matchParentSize(), contentScale = scale)
    }
}

@Composable
fun Avatar(url: String?, size: Dp, ring: Boolean = false, description: String? = null) {
    val inner = @Composable {
        RemoteImage(url, description, Modifier.size(size).clip(CircleShape))
    }
    if (ring) Box(Modifier.size(size + 8.dp).border(2.5.dp, Ring, CircleShape), contentAlignment = Alignment.Center) { inner() }
    else inner()
}

@Composable
fun Banner(icon: ImageVector, text: String, tint: Color, modifier: Modifier = Modifier, action: String? = null, tag: String = "banner", onAction: (() -> Unit)? = null) {
    Surface(color = tint.copy(alpha = 0.14f), shape = RoundedCornerShape(12.dp), modifier = modifier.fillMaxWidth().testTag(tag).semantics { liveRegion = LiveRegionMode.Polite }) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Icon(icon, null, tint = tint)
            Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            if (action != null && onAction != null) TextButton(onClick = onAction) { Text(action) }
        }
    }
}

@Composable
fun OfflineBanner(modifier: Modifier = Modifier) =
    Banner(Icons.Filled.CloudOff, "Offline: showing what was saved last time.", Color(0xFF8A8F98), modifier, tag = "banner.offline")

@Composable
fun SampleBanner(text: String, modifier: Modifier = Modifier) =
    Banner(Icons.Filled.Science, text, Color(0xFF7A5BC7), modifier, tag = "banner.sample")

@Composable
fun ErrorBanner(error: Throwable, modifier: Modifier = Modifier, onRetry: () -> Unit) =
    Banner(Icons.Filled.Warning, error.message ?: "Something went wrong.", MaterialTheme.colorScheme.error, modifier, "Retry", "banner.error", onRetry)

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, style = MaterialTheme.typography.titleMedium, modifier = modifier.semantics { heading() })
}

@Composable
fun LabeledText(label: String, text: String, modifier: Modifier = Modifier, basis: String? = null) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(text, style = MaterialTheme.typography.bodyMedium)
        basis?.let { Text("Basis: $it", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}
