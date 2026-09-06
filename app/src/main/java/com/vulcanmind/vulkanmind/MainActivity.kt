package com.vulcanmind.vulkanmind

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.vulcanmind.vulkanmind.ui.screens.ChatListScreen
import com.vulcanmind.vulkanmind.ui.screens.ChatScreen
import com.vulcanmind.vulkanmind.ui.screens.ModelImportScreen
import com.vulcanmind.vulkanmind.ui.screens.SettingsScreen
import com.vulcanmind.vulkanmind.ui.theme.VulcanTheme

class MainActivity : ComponentActivity() {

    private val app by lazy { application as VulcanApplication }

    private val viewModel: MainViewModel by viewModels {
        object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                return MainViewModel(app) as T
            }
        }
    }

    private val requestPermissionLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        Log.i("MainActivity", "POST_NOTIFICATIONS granted=$granted")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Permissão notificação para foreground service com tela bloqueada
        if (Build.VERSION.SDK_INT >= 33) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

        // Handle share GGUF
        handleIntent(intent)

        setContent {
            VulcanTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    AppNav(viewModel)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        if (intent?.action == Intent.ACTION_VIEW || intent?.action == Intent.ACTION_SEND) {
            val uri: Uri? = intent.data ?: intent.getParcelableExtra(Intent.EXTRA_STREAM)
            if (uri != null) {
                Log.i("MainActivity", "Received GGUF share uri=$uri")
                viewModel.pendingImportUri = uri
            }
        }
    }
}

@Composable
fun AppNav(vm: MainViewModel) {
    val nav = rememberNavController()
    var selectedChatId by remember { mutableStateOf<Long?>(null) }

    NavHost(navController = nav, startDestination = "chats") {
        composable("chats") {
            ChatListScreen(
                viewModel = vm,
                onOpenChat = { chatId ->
                    selectedChatId = chatId
                    nav.navigate("chat/$chatId")
                },
                onOpenModels = { nav.navigate("models") },
                onOpenSettings = { nav.navigate("settings") }
            )
        }
        composable("chat/{chatId}") { backStack ->
            val chatId = backStack.arguments?.getString("chatId")?.toLongOrNull() ?: selectedChatId ?: return@composable
            ChatScreen(
                chatId = chatId,
                viewModel = vm,
                onBack = { nav.popBackStack() },
                onOpenModels = { nav.navigate("models") }
            )
        }
        composable("models") {
            ModelImportScreen(viewModel = vm, onBack = { nav.popBackStack() })
        }
        composable("settings") {
            SettingsScreen(viewModel = vm, onBack = { nav.popBackStack() })
        }
    }
}

class MainViewModel(private val app: VulcanApplication) : ViewModel() {
    val chatRepo = app.chatRepository
    val modelManager = app.modelManager
    val chats = chatRepo.observeChats()
    var pendingImportUri: Uri? by mutableStateOf(null)

    // UI toggles globais por chat (persistidos no Chat entity)
    var thinkingEnabled by mutableStateOf(true)
    var searchEnabled by mutableStateOf(true)

    fun getMessages(chatId: Long) = chatRepo.observeMessages(chatId)
}
