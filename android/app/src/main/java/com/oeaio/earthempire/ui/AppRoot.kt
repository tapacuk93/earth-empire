package com.oeaio.earthempire.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.MonitorHeart
import androidx.compose.material.icons.filled.Radar
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import android.net.Uri
import com.oeaio.earthempire.AppContainer
import com.oeaio.earthempire.data.DeepLink
import com.oeaio.earthempire.data.ItemKind
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.first

/** Navigation as the screens see it. */
class Nav(
    val item: (String) -> Unit,
    val category: (String) -> Unit,
    val categories: () -> Unit,
    val hit: (String) -> Unit,
    val story: (highlight: String, item: String?) -> Unit,
    val feed: (List<FeedEntry>, Int) -> Unit,
    val settings: () -> Unit,
    val back: () -> Unit,
)

val LocalNav = staticCompositionLocalOf { Nav({}, {}, {}, {}, { _, _ -> }, { _, _ -> }, {}, {}) }

enum class Tab(val route: String, val label: String, val icon: ImageVector) {
    Home("home", "Home", Icons.Filled.Home),
    Monitor("monitor", "Detected", Icons.Filled.Radar),
    Status("status", "Status", Icons.Filled.MonitorHeart),
    Settings("settings", "Settings", Icons.Filled.Settings),
}

/**
 * The app, the same as on iOS and the web: Home (everything published) for everyone; Detected,
 * Status and Settings for the owner once the admin token is accepted. Home and Detected have a
 * fullscreen video mode; above them the detail screens and the story viewer.
 */
@Composable
fun EarthEmpireApp(container: AppContainer, links: Flow<DeepLink> = emptyFlow(), startTab: Tab = Tab.Home) {
    val theme by container.theme.collectAsState()
    EarthEmpireTheme(theme) {
        val nav = rememberNavController()
        val archive by container.archive.collectAsState()
        val monitorApi by container.monitor.collectAsState()
        val homeVm: HomeViewModel = viewModel { HomeViewModel(container) }
        val monitorVm: MonitorViewModel = viewModel { MonitorViewModel(container) }
        val statusVm: StatusViewModel = viewModel { StatusViewModel(container) }
        val settingsVm: SettingsViewModel = viewModel { SettingsViewModel(container) }
        val owner by container.owner.collectAsState()

        var story by remember { mutableStateOf<Pair<String, String?>?>(null) }
        var feed by remember { mutableStateOf<Pair<List<FeedEntry>, Int>?>(null) }

        val navigation = remember(nav) {
            Nav(
                item = { nav.navigate("item/${Uri.encode(it)}") },
                category = { nav.navigate("category/${Uri.encode(it)}") },
                categories = { nav.navigate("categories") },
                hit = { nav.navigate("hit/${Uri.encode(it)}") },
                story = { h, i -> story = h to i },
                feed = { list, start -> feed = list to start },
                settings = { if (container.owner.value) nav.selectTab(Tab.Settings) else nav.navigate("owner") { launchSingleTop = true } },
                back = { nav.popBackStack() },
            )
        }

        LaunchedEffect(links) {
            // The NavHost sets its graph during composition; links wait for it.
            nav.currentBackStackEntryFlow.first()
            links.collect { link ->
                story = null; feed = null
                when (link) {
                    DeepLink.Monitor -> if (container.owner.value) nav.selectTab(Tab.Monitor) else navigation.settings()
                    is DeepLink.MonitorHit -> if (container.owner.value) { nav.selectTab(Tab.Monitor); navigation.hit(link.id) } else navigation.settings()
                    is DeepLink.Home -> { nav.selectTab(Tab.Home); homeVm.applyQuery(link.query); link.view?.let { if (it == "tags" || it == "timeline") homeVm.chooseView(it) } }
                    is DeepLink.Item -> { nav.selectTab(Tab.Home); navigation.item(link.id) }
                    is DeepLink.Category -> { nav.selectTab(Tab.Home); nav.navigate("category/${Uri.encode(link.slug)}" + (link.kind?.let { "?kind=${it.wire}" } ?: "")) }
                    DeepLink.Categories -> { nav.selectTab(Tab.Home); navigation.categories() }
                    is DeepLink.Highlight -> { nav.selectTab(Tab.Home); story = link.id to link.item }
                }
            }
        }

        CompositionLocalProvider(LocalNav provides navigation) {
            val entry by nav.currentBackStackEntryAsState()
            val route = entry?.destination?.route
            Scaffold(
                bottomBar = {
                    // Without the owner's token there is only Home, so no tab bar.
                    if (owner) NavigationBar(Modifier.testTag("tabs")) {
                        Tab.entries.forEach { t ->
                            NavigationBarItem(
                                selected = route == t.route,
                                onClick = { nav.selectTab(t) },
                                icon = { Icon(t.icon, null) }, label = { Text(t.label) },
                                modifier = Modifier.testTag("tab.${t.route}"),
                            )
                        }
                    }
                },
                snackbarHost = {
                    SnackbarHost(when (route) { Tab.Monitor.route, "hit/{id}" -> monitorVm.messages; Tab.Status.route -> statusVm.messages; Tab.Settings.route -> settingsVm.messages; else -> remember { androidx.compose.material3.SnackbarHostState() } })
                },
            ) { padding ->
                Box(Modifier.fillMaxSize().padding(padding)) {
                    NavHost(nav, startDestination = startTab.route) {
                        composable(Tab.Home.route) { HomeScreen(homeVm) }
                        composable(Tab.Monitor.route) { MonitorScreen(monitorVm) }
                        composable(Tab.Status.route) { StatusScreen(statusVm) }
                        composable(Tab.Settings.route) { SettingsScreen(settingsVm) }
                        composable("item/{id}", listOf(navArgument("id") { type = NavType.StringType })) { e ->
                            ItemScreen(e.arguments?.getString("id") ?: "", archive)
                        }
                        composable("category/{slug}?kind={kind}", listOf(
                            navArgument("slug") { type = NavType.StringType },
                            navArgument("kind") { type = NavType.StringType; nullable = true; defaultValue = null },
                        )) { e -> CategoryScreen(e.arguments?.getString("slug") ?: "", ItemKind.of(e.arguments?.getString("kind")), archive) }
                        composable("categories") { CategoriesScreen(archive) }
                        composable("owner") { OwnerSignInScreen(container) { nav.popBackStack() } }
                        composable("hit/{id}", listOf(navArgument("id") { type = NavType.StringType })) { e ->
                            HitScreen(e.arguments?.getString("id") ?: "", monitorApi, monitorVm)
                        }
                    }
                }
            }
            story?.let { (h, i) -> StoryViewer(h, i, archive) { story = null } }
            feed?.let { (list, start) -> VideoFeed(list, start) { feed = null } }
            // Signing out leaves only Home.
            LaunchedEffect(owner) { if (!owner && route in Tab.entries.map { it.route } && route != Tab.Home.route) nav.selectTab(Tab.Home) }
        }
    }
}

private fun NavHostController.selectTab(tab: Tab) {
    navigate(tab.route) {
        popUpTo(graph.startDestinationId) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}
