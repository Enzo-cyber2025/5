package com.vulcanmind.vulkanmind.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Lightbulb
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.vulcanmind.vulkanmind.MainViewModel
import com.vulcanmind.vulkanmind.data.models.Chat
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatListScreen(
    viewModel: MainViewModel,
    onOpenChat: (Long) -> Unit,
    onOpenModels: () -> Unit,
    onOpenSettings: () -> Unit
) {
    val chats by viewModel.chats.collectAsState(initial = emptyList())
    val scope = rememberCoroutineScope()
    var vulkanStatus by remember { mutableStateOf(viewModel.modelManager.getVulkanStatus()) }

    // Poll Vulkan status
    LaunchedEffect(Unit) {
        // atualiza a cada 3s
        while (true) {
            kotlinx.coroutines.delay(3000)
            vulkanStatus = viewModel.modelManager.getVulkanStatus()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("VulcanMind 7.0 — Vulkan GGUF", fontWeight = FontWeight.Black) },
                actions = {
                    IconButton(onClick = onOpenModels) { Icon(Icons.Default.Memory, contentDescription = "GGUFs") }
                    IconButton(onClick = onOpenSettings) { Icon(Icons.Default.Settings, contentDescription = "Settings") }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = {
                scope.launch {
                    val id = viewModel.chatRepo.createChat(title = "Chat ${SimpleDateFormat("dd/MM HH:mm", Locale.getDefault()).format(Date())}", thinking = viewModel.thinkingEnabled, search = viewModel.searchEnabled)
                    onOpenChat(id)
                }
            }, containerColor = MaterialTheme.colorScheme.primary) {
                Icon(Icons.Default.Add, contentDescription = "Novo Chat")
            }
        }
    ) { pad ->
        Column(modifier = Modifier.fillMaxSize().padding(pad).padding(16.dp)) {

            // Vulkan banner - destaque de que roda GGUF direto da memória via Vulkan
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = if (vulkanStatus.contains("ATIVO")) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.errorContainer),
                shape = RoundedCornerShape(16.dp)
            ) {
                Row(modifier = Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Lightbulb, contentDescription = null, modifier = Modifier.size(28.dp))
                    Spacer(Modifier.width(10.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(vulkanStatus, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text("GGUF direto da memória • mmap zero-copy • 2 slots multimodais • thinking + pesquisa", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            Spacer(Modifier.height(12.dp))

            // Slots preview
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                val slotA = viewModel.modelManager.getSlotState(0)
                val slotB = viewModel.modelManager.getSlotState(1)
                SlotPreview(modifier = Modifier.weight(1f), label = "Slot A — LLM", state = slotA)
                SlotPreview(modifier = Modifier.weight(1f), label = "Slot B — Vision", state = slotB)
            }

            Spacer(Modifier.height(12.dp))

            // Toggles thinking/search globais
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                FilterChip(selected = viewModel.thinkingEnabled, onClick = { viewModel.thinkingEnabled = !viewModel.thinkingEnabled }, label = { Text("Thinking") }, leadingIcon = { Icon(Icons.Default.Lightbulb, contentDescription = null, modifier = Modifier.size(16.dp)) })
                FilterChip(selected = viewModel.searchEnabled, onClick = { viewModel.searchEnabled = !viewModel.searchEnabled }, label = { Text("Pesquisa") })
                Spacer(Modifier.weight(1f))
                Text("${chats.size} chats", style = MaterialTheme.typography.labelMedium)
            }

            Spacer(Modifier.height(8.dp))

            if (chats.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("Nenhum chat ainda", style = MaterialTheme.typography.titleMedium)
                        Text("Toque + para criar — organizado em chats", style = MaterialTheme.typography.bodyMedium)
                        Spacer(Modifier.height(12.dp))
                        OutlinedButton(onClick = onOpenModels) { Text("Importar 2 GGUFs Multimodais") }
                    }
                }
            } else {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxSize()) {
                    items(chats, key = { it.id }) { chat ->
                        ChatRow(chat = chat, onClick = { onOpenChat(chat.id) }, onDelete = {
                            scope.launch { viewModel.chatRepo.deleteChat(chat.id) }
                        })
                    }
                }
            }
        }
    }
}

@Composable
fun SlotPreview(modifier: Modifier, label: String, state: com.vulcanmind.vulkanmind.inference.ModelManager.SlotState) {
    Card(modifier = modifier, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant), shape = RoundedCornerShape(12.dp)) {
        Column(modifier = Modifier.padding(10.dp)) {
            Text(label, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(4.dp))
            if (state.isLoaded) {
                Text(state.name ?: "carregado", maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold)
                Text("${(state.sizeBytes / (1024*1024))} MB • Vulkan", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
            } else {
                Text("vazio", style = MaterialTheme.typography.bodySmall)
                Text("toque em Memória > Importar", style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

@Composable
fun ChatRow(chat: Chat, onClick: () -> Unit, onDelete: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick), elevation = CardDefaults.cardElevation(2.dp), shape = RoundedCornerShape(14.dp)) {
        Row(modifier = Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(chat.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(2.dp))
                Text(SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.getDefault()).format(Date(chat.updatedAt)), style = MaterialTheme.typography.labelSmall)
                Spacer(Modifier.height(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (chat.thinkingEnabled) AssistChip(onClick = {}, label = { Text("thinking", style = MaterialTheme.typography.labelSmall) })
                    if (chat.searchEnabled) AssistChip(onClick = {}, label = { Text("pesquisa", style = MaterialTheme.typography.labelSmall) })
                }
            }
            IconButton(onClick = onDelete) { Icon(Icons.Default.Delete, contentDescription = "Apagar", tint = MaterialTheme.colorScheme.error) }
        }
    }
}
