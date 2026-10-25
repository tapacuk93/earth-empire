package com.oeaio.earthempire.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.oeaio.earthempire.data.ArchiveApi
import com.oeaio.earthempire.data.Category
import com.oeaio.earthempire.data.Item
import com.oeaio.earthempire.data.ItemKind
import com.oeaio.earthempire.data.ItemQuery
import com.oeaio.earthempire.data.Pager
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CategoryScreen(slug: String, kind: ItemKind?, api: ArchiveApi) {
    val nav = LocalNav.current
    var category by remember { mutableStateOf<Category?>(null) }
    var items by remember { mutableStateOf<List<Item>>(emptyList()) }
    var error by remember { mutableStateOf<Throwable?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    val pager = remember(slug, kind, api) { Pager<Item>({ it.id }) { c -> val p = api.items(ItemQuery(kind = kind, category = slug), c, 30); p.items to p.next } }
    val scope = rememberCoroutineScope()
    suspend fun load() {
        try { pager.refresh(); items = pager.items; error = null } catch (e: Exception) { error = e }
        runCatching { category = api.categories().firstOrNull { it.slug == slug } }
    }
    LaunchedEffect(pager) { load() }
    Column(Modifier.fillMaxSize()) {
        TopAppBar(title = { Text(category?.name ?: slug) }, navigationIcon = { IconButton(onClick = nav.back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
        PullToRefreshBox(refreshing, { scope.launch { refreshing = true; load(); refreshing = false } }, Modifier.fillMaxSize()) {
            LazyVerticalGrid(GridCells.Adaptive(110.dp), horizontalArrangement = Arrangement.spacedBy(2.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                category?.description?.let { d -> item(span = { GridItemSpan(maxLineSpan) }) { Text(d, Modifier.padding(16.dp), style = MaterialTheme.typography.bodyMedium) } }
                error?.let { e -> item(span = { GridItemSpan(maxLineSpan) }) { ErrorBanner(e, Modifier.padding(16.dp)) { scope.launch { load() } } } }
                items(items, key = { it.id }) { ItemTile(it) { nav.item(it.id) } }
                if (!pager.isComplete && items.isNotEmpty()) item(span = { GridItemSpan(maxLineSpan) }) {
                    LaunchedEffect(items.size) { runCatching { pager.loadMore(); items = pager.items } }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CategoriesScreen(api: ArchiveApi) {
    val nav = LocalNav.current
    var list by remember { mutableStateOf<List<Category>>(emptyList()) }
    var error by remember { mutableStateOf<Throwable?>(null) }
    val scope = rememberCoroutineScope()
    suspend fun load() { try { list = api.categories(); error = null } catch (e: Exception) { error = e } }
    LaunchedEffect(api) { load() }
    Column(Modifier.fillMaxSize()) {
        TopAppBar(title = { Text("Categories") }, navigationIcon = { IconButton(onClick = nav.back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
        LazyColumn(contentPadding = PaddingValues(vertical = 8.dp)) {
            error?.let { e -> item { ErrorBanner(e, Modifier.padding(16.dp)) { scope.launch { load() } } } }
            items(list, key = { it.slug }) { c ->
                ListItem(
                    headlineContent = { Text(c.name) },
                    supportingContent = c.description?.let { { Text(it) } },
                    trailingContent = { Text("${c.count}") },
                    modifier = Modifier.fillMaxWidth().clickable { nav.category(c.slug) },
                )
            }
        }
    }
}
