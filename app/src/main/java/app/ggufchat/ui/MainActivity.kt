package app.ggufchat.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import app.ggufchat.data.Repo
import app.ggufchat.ui.screens.ChatListScreen
import app.ggufchat.ui.screens.ChatScreen
import app.ggufchat.ui.screens.ChatSettingsScreen
import app.ggufchat.ui.screens.ModelsScreen
import app.ggufchat.ui.screens.SettingsScreen
import app.ggufchat.ui.theme.GgufTheme
import kotlinx.coroutines.flow.MutableStateFlow

/** Pedidos de navegação vindos de fora da UI (notificações, etc.). */
object NavRequests {
    val pendingChat = MutableStateFlow<String?>(null)

    fun openChat(id: String) {
        pendingChat.value = id
    }
}

class MainActivity : ComponentActivity() {

    private val notifPermLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        WindowCompat.setDecorFitsSystemWindows(window, false)

        handleIntent(intent)

        setContent {
            val settings by Repo.settings.collectAsState()
            val dark = when (settings.theme) {
                "dark" -> true
                "light" -> false
                else -> isSystemInDarkTheme()
            }
            GgufTheme(darkTheme = dark) {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    AppNav()
                }
            }
        }
        ensureNotificationPermission()
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        val chatId = intent?.getStringExtra(EXTRA_CHAT)
        if (!chatId.isNullOrBlank()) NavRequests.openChat(chatId)
    }

    private fun ensureNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    companion object {
        const val EXTRA_CHAT = "chat_id"
    }
}

@androidx.compose.runtime.Composable
private fun AppNav() {
    val nav = rememberNavController()
    val lastChatId by Repo.chat.collectAsStateWithLifecycle()
    val start = remember {
        if (lastChatId != null) "chat/${lastChatId!!.id}" else "chats"
    }

    // navegação a pedido (ex.: notificação de conclusão / retomar chat)
    LaunchedEffect(Unit) {
        NavRequests.pendingChat.collect { id ->
            if (id != null) {
                NavRequests.pendingChat.value = null
                if (Repo.openChat(id) != null) {
                    nav.navigate("chat/$id") {
                        popUpTo(nav.graph.startDestinationId) { inclusive = false }
                        launchSingleTop = true
                    }
                }
            }
        }
    }

    NavHost(navController = nav, startDestination = start) {
        composable("chats") {
            ChatListScreen(
                onOpenChat = { id ->
                    Repo.openChat(id)
                    nav.navigate("chat/$id") {
                        popUpTo("chats") { inclusive = false }
                    }
                },
                onNewChat = { id ->
                    Repo.openChat(id)
                    nav.navigate("chat/$id/edit") {
                        popUpTo("chats")
                    }
                },
                onModels = { nav.navigate("models") },
                onSettings = { nav.navigate("settings") }
            )
        }
        composable("chat/{chatId}") { back ->
            val id = back.arguments?.getString("chatId") ?: return@composable
            LaunchedEffect(id) {
                if (Repo.chat.value?.id != id) {
                    if (Repo.openChat(id) == null) nav.popBackStack()
                }
            }
            ChatScreen(
                chatId = id,
                viewModel = viewModel(key = "chat-$id"),
                onBack = { nav.popBackStack() },
                onOpenModels = { nav.navigate("models") },
                onOpenSettings = { nav.navigate("chat/$id/edit") },
                onOpenAppSettings = { nav.navigate("settings") },
                onNewChat = {
                    nav.navigate("chats") { popUpTo("chats") { inclusive = false } }
                }
            )
        }
        composable("chat/{chatId}/edit") { back ->
            val id = back.arguments?.getString("chatId") ?: return@composable
            ChatSettingsScreen(
                chatId = id,
                onBack = { nav.popBackStack() }
            )
        }
        composable("models") {
            ModelsScreen(onBack = { nav.popBackStack() })
        }
        composable("settings") {
            SettingsScreen(onBack = { nav.popBackStack() })
        }
    }
}
