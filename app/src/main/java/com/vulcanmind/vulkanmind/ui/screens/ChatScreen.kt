package com.vulcanmind.vulkanmind.ui.screens

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.vulcanmind.vulkanmind.MainViewModel
import com.vulcanmind.vulkanmind.data.models.Message
import com.vulcanmind.vulkanmind.service.GenerationForegroundService
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileOutputStream

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(chatId: Long, viewModel: MainViewModel, onBack: () -> Unit, onOpenModels: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val messages by viewModel.getMessages(chatId).collectAsState(initial = emptyList())
    val chat by produceState(initialValue = null as com.vulcanmind.vulkanmind.data.models.Chat?, key1 = chatId) {
        value = viewModel.chatRepo.getChat(chatId)
    }

    var input by remember { mutableStateOf("") }
    var thinkingEnabled by remember { mutableStateOf(chat?.thinkingEnabled ?: true) }
    var searchEnabled by remember { mutableStateOf(chat?.searchEnabled ?: true) }
    var isGenerating by remember { mutableStateOf(false) }
    var streamingThinking by remember { mutableStateOf("") }
    var streamingPartial by remember { mutableStateOf("") }
    var attachedImageUri by remember { mutableStateOf<Uri?>(null) }
    var attachedImagePath by remember { mutableStateOf<String?>(null) }

    // Atualiza thinking/search quando chat muda
    LaunchedEffect(chat) {
        chat?.let {
            thinkingEnabled = it.thinkingEnabled
            searchEnabled = it.searchEnabled
        }
    }

    val listState = rememberLazyListState()
    LaunchedEffect(messages.size, streamingPartial) {
        if (messages.isNotEmpty() || streamingPartial.isNotBlank()) {
            listState.animateScrollToItem(if (messages.isNotEmpty()) messages.size - 1 else 0)
        }
    }

    // Observar GenerationForegroundService state para streaming com tela bloqueada
    // Para simplificar, polling via LaunchedEffect (em app real usar bind service flow)
    // Aqui simulamos: quando isGenerating, coletamos callbacks via viewModel?

    val imagePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            attachedImageUri = uri
            // Copia para cache para passar path nativo ao GGUF vision
            scope.launch {
                try {
                    val inputStream = ctx.contentResolver.openInputStream(uri)
                    val outFile = File(ctx.cacheDir, "vision_${System.currentTimeMillis()}.jpg")
                    inputStream?.use { ins -> FileOutputStream(outFile).use { outs -> ins.copyTo(outs) } }
                    attachedImagePath = outFile.absolutePath
                } catch (e: Exception) {
                    attachedImagePath = null
                }
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Column { Text(chat?.title ?: "Chat $chatId", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold); Text("${if (thinkingEnabled) "thinking " else ""}${if (searchEnabled) "• pesquisa" else ""} • Vulkan", style = MaterialTheme.typography.labelSmall) } },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.Default.ArrowBack, contentDescription = "Voltar") } },
                actions = {
                    IconButton(onClick = { imagePicker.launch("image/*") }) { Icon(Icons.Default.Image, contentDescription = "Multimodal") }
                    IconButton(onClick = onOpenModels) { Icon(Icons.Default.Memory, contentDescription = "GGUF") }
                }
            )
        },
        bottomBar = {
            Column(modifier = Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface).padding(8.dp)) {
                // Chips thinking/search por chat
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    FilterChip(selected = thinkingEnabled, onClick = {
                        thinkingEnabled = !thinkingEnabled
                        scope.launch { chat?.let { viewModel.chatRepo.updateChat(it.copy(thinkingEnabled = thinkingEnabled)) } }
                    }, label = { Text("Thinking") }, leadingIcon = { Icon(Icons.Default.Lightbulb, contentDescription = null, modifier = Modifier.size(16.dp)) })
                    FilterChip(selected = searchEnabled, onClick = {
                        searchEnabled = !searchEnabled
                        scope.launch { chat?.let { viewModel.chatRepo.updateChat(it.copy(searchEnabled = searchEnabled)) } }
                    }, label = { Text("Pesquisa Web") }, leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.size(16.dp)) })
                    if (attachedImageUri != null) {
                        AssistChip(onClick = { attachedImageUri = null; attachedImagePath = null }, label = { Text("Imagem anexada") }, leadingIcon = { Icon(Icons.Default.Image, contentDescription = null) })
                    }
                }
                Spacer(Modifier.height(6.dp))
                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
                    OutlinedTextField(
                        value = input,
                        onValueChange = { input = it },
                        modifier = Modifier.weight(1f),
                        placeholder = { Text("Digite sua mensagem…") },
                        minLines = 1,
                        maxLines = 5,
                        shape = RoundedCornerShape(24.dp)
                    )
                    Spacer(Modifier.width(8.dp))
                    FilledIconButton(
                        onClick = {
                            if (input.isBlank() || isGenerating) return@FilledIconButton
                            val prompt = input.trim()
                            input = ""
                            streamingThinking = ""
                            streamingPartial = ""
                            isGenerating = true
                            scope.launch {
                                // Salva mensagem user
                                viewModel.chatRepo.addMessage(Message(chatId = chatId, role = "user", content = prompt, hasImage = attachedImageUri != null, imagePath = attachedImagePath))
                                // Chama ForegroundService para gerar com tela bloqueada
                                GenerationForegroundService.startGenerate(ctx, chatId, prompt, thinkingEnabled, searchEnabled, attachedImagePath)
                                // Simula streaming local também (para UI imediata) - em app real viria do service flow
                                // Vamos fazer polling simples: aguarda 300ms e então simula streaming via LlamaBridge direto como fallback
                                kotlinx.coroutines.delay(350)
                                // Fallback local (caso service ainda não atualizou DB): usa ModelManager direto para streaming UI
                                // Aqui apenas aguardamos DB atualizar via Flow
                                // Timeout 30s
                                var elapsed = 0
                                while (elapsed < 30000 && isGenerating) {
                                    kotlinx.coroutines.delay(500)
                                    elapsed += 500
                                    // Checa se nova mensagem assistant chegou no DB
                                    val msgs = viewModel.chatRepo.getMessages(chatId)
                                    val last = msgs.lastOrNull()
                                    if (last?.role == "assistant" && last.content.isNotBlank() && last.timestamp > System.currentTimeMillis() - 10000) {
                                        // Nova geração chegou - encerra streaming
                                        isGenerating = false
                                        streamingPartial = ""
                                        streamingThinking = ""
                                        break
                                    }
                                }
                                // Fallback se DB não atualizou (service falhou) - encerra após 30s
                                if (isGenerating) isGenerating = false
                                attachedImageUri = null
                                attachedImagePath = null
                            }
                        },
                        enabled = input.isNotBlank() && !isGenerating,
                        modifier = Modifier.size(48.dp)
                    ) {
                        if (isGenerating) CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp, color = Color.White)
                        else Icon(Icons.Default.Send, contentDescription = "Enviar")
                    }
                }
                if (isGenerating) {
                    Row(modifier = Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Bolt, contentDescription = null, modifier = Modifier.size(14.dp), tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(4.dp))
                        Text("Gerando via Vulkan… pode bloquear a tela, continuará em segundo plano com WakeLock", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = {
                            // Stop generation
                            viewModel.modelManager.stopGeneration()
                            ctx.stopService(android.content.Intent(ctx, GenerationForegroundService::class.java).apply { action = GenerationForegroundService.ACTION_STOP })
                            isGenerating = false
                        }) { Text("Parar", style = MaterialTheme.typography.labelSmall) }
                    }
                }
            }
        }
    ) { pad ->
        LazyColumn(modifier = Modifier.fillMaxSize().padding(pad).padding(horizontal = 12.dp), state = listState, verticalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(top = 12.dp, bottom = 12.dp)) {
            items(messages, key = { it.id }) { msg ->
                MessageBubble(msg)
            }
            // Streaming placeholder
            if (isGenerating && streamingPartial.isBlank()) {
                item {
                    Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer), shape = RoundedCornerShape(18.dp)) {
                        Row(modifier = Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(10.dp))
                            Column {
                                Text("Gerando…", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
                                if (thinkingEnabled) Text("thinking ativo + ${if (searchEnabled) "pesquisa" else "sem pesquisa"} • Vulkan compute", style = MaterialTheme.typography.labelSmall)
                                if (streamingThinking.isNotBlank()) Text(streamingThinking.take(120), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            }
            if (streamingPartial.isNotBlank()) {
                item {
                    MessageBubble(Message(chatId = chatId, role = "assistant", content = streamingPartial, thinkingContent = streamingThinking.ifBlank { null }))
                }
            }
        }
    }
}

@Composable
fun MessageBubble(msg: Message) {
    val isUser = msg.role == "user"
    val bg = if (isUser) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant
    val align = if (isUser) Alignment.CenterEnd else Alignment.CenterStart
    var showThinking by remember { mutableStateOf(false) }

    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = align) {
        Column(modifier = Modifier.widthIn(max = 320.dp).clip(RoundedCornerShape(18.dp)).background(bg).padding(12.dp)) {
            if (!msg.thinkingContent.isNullOrBlank()) {
                Row(modifier = Modifier.fillMaxWidth().clickable { showThinking = !showThinking }, verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Psychology, contentDescription = null, modifier = Modifier.size(16.dp), tint = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.width(6.dp))
                    Text("Thinking", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.weight(1f))
                    Icon(if (showThinking) Icons.Default.ExpandLess else Icons.Default.ExpandMore, contentDescription = null, modifier = Modifier.size(16.dp))
                }
                AnimatedVisibility(visible = showThinking) {
                    Text(msg.thinkingContent, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp).background(Color.Black.copy(alpha = 0.06f), RoundedCornerShape(8.dp)).padding(8.dp))
                }
                Spacer(Modifier.height(6.dp))
                Divider()
                Spacer(Modifier.height(6.dp))
            }
            Text(msg.content, style = MaterialTheme.typography.bodyMedium)
            if (msg.hasImage && msg.imagePath != null) {
                Spacer(Modifier.height(6.dp))
                Card(shape = RoundedCornerShape(10.dp), colors = CardDefaults.cardColors(containerColor = Color.Black.copy(alpha = 0.05f))) {
                    Row(modifier = Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Image, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Imagem anexada • multimodal slot B", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault()).format(java.util.Date(msg.timestamp)), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f))
                if (msg.wasGeneratedWithScreenOff) {
                    Spacer(Modifier.width(6.dp))
                    Icon(Icons.Default.Lock, contentDescription = null, modifier = Modifier.size(12.dp), tint = MaterialTheme.colorScheme.primary)
                    Text("tela bloqueada", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                }
                if (msg.generationTimeMs != null) {
                    Spacer(Modifier.width(6.dp))
                    Text("${msg.generationTimeMs}ms", style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}
