package app.ggufchat.ui.screens

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Public
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import app.ggufchat.core.CoreEngine
import app.ggufchat.data.ChatMsg
import app.ggufchat.data.Repo
import app.ggufchat.data.Store
import app.ggufchat.ui.components.ChatBubble
import app.ggufchat.ui.components.ThinkingBox
import app.ggufchat.ui.components.ThumbnailsRow
import coil.compose.AsyncImage
import coil.request.ImageRequest
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    chatId: String,
    viewModel: ChatViewModel,
    onBack: () -> Unit,
    onOpenModels: () -> Unit,
    onOpenSettings: () -> Unit,
    onOpenAppSettings: () -> Unit,
    onNewChat: () -> Unit
) {
    val chat by Repo.chat.collectAsState()
    val active = chat?.takeIf { it.id == chatId }
    val models by Repo.models.collectAsState()
    val model = active?.modelId?.let { mid -> models.firstOrNull { it.id == mid } }
    val mmproj = active?.mmprojId?.let { mid -> models.firstOrNull { it.id == mid } }
    val busy = CoreEngine.activeChat.collectAsState().value == chatId
    val loading by CoreEngine.loadingModel.collectAsState()
    val live by Repo.liveText.collectAsState()

    if (active == null) {
        // chat apagado ou inexistente — volta
        LaunchedEffect(Unit) { onBack() }
        return
    }

    val liveTurn = live[chatId]
    val streamText = liveTurn?.text ?: ""
    val (liveThinking, liveAnswer) = splitThinkingLive(streamText)
    val showThinkingBox = busy && (liveThinking.isNotBlank() || viewModel.showLiveThinking)

    val listState = rememberLazyListState()
    LaunchedEffect(streamText.length, chat.msgs.size) {
        if (listState.layoutInfo.totalItemsCount > 0) {
            listState.animateScrollToItem(listState.layoutInfo.totalItemsCount - 1)
        }
    }

    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) {
        Repo.toast.collect { snackbar.showSnackbar(it) }
    }

    // mensagens a exibir: histórico + turno ao vivo
    val history = chat.msgs
    val showLiveBubble = streamText.isNotEmpty() || busy || loading != null

    val pickImages = rememberLauncherForActivityResult(
        ActivityResultContracts.GetMultipleContents()
    ) { uris: List<Uri> ->
        if (uris.isNotEmpty()) viewModel.attach(LocalContext.current, chatId, uris)
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            active.title.ifBlank { "Novo chat" },
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold
                        )
                        val label = model?.name ?: "sem modelo"
                        val sub = if (mmproj != null) "$label · 📷 ${mmproj.name}" else label
                        Text(
                            sub,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Filled.ArrowBack, contentDescription = "Voltar")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                ),
                actions = {
                    IconButton(onClick = onOpenModels) {
                        Icon(Icons.Filled.Tune, contentDescription = "Modelos")
                    }
                    IconButton(onClick = onOpenSettings) {
                        Icon(Icons.Filled.Settings, contentDescription = "Configurar chat")
                    }
                }
            )
        }
    ) { pad ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(pad)
        ) {
            if (loading != null && loading!!.first == active.modelId) {
                LinearProgressIndicator(
                    progress = loading!!.second,
                    modifier = Modifier.fillMaxWidth()
                )
            }

            if (history.isEmpty() && !showLiveBubble) {
                WelcomeHint(active.modelId.isBlank(), models.isEmpty())
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    itemsIndexed(history, key = { _, m -> m.id }) { idx, msg ->
                        val (thinking, answer) = splitThinkingStored(msg)
                        when (msg.role) {
                            "system" -> {}
                            "user" -> {
                                ChatBubble(isUser = true, text = msg.content)
                                if (msg.images.isNotEmpty()) {
                                    ThumbnailsRow(
                                        msg.images.filter { File(it).exists() },
                                        Modifier.padding(top = 2.dp, start = 2.dp)
                                    )
                                }
                            }
                            "assistant" -> {
                                val meta = msg.meta
                                val isErr = meta?.stopped == "error" ||
                                        (msg.content.isBlank() && meta != null)
                                val text = if (isErr) "⚠️ ${msg.content.ifBlank { "Falha na geração" }}" else answer
                                ChatBubble(
                                    isUser = false,
                                    text = text.ifBlank { " " },
                                    thinking = thinking,
                                    thinkingHidden = msg.id in viewModel.thinkingCollapsedIds,
                                    onToggleThinking = { viewModel.toggleThinking(msg.id) },
                                    onRetry = if (idx == history.lastIndex && !busy && !isErr) {
                                        { viewModel.retry(chatId) }
                                    } else null
                                )
                            }
                        }
                    }
                    if (showLiveBubble) {
                        item(key = "live") {
                            Column {
                                if (liveThinking.isNotBlank() || showThinkingBox) {
                                    ThinkingBox(
                                        thinking = liveThinking,
                                        hidden = !viewModel.showLiveThinking,
                                        onToggle = { viewModel.setLiveThinking(!viewModel.showLiveThinking) }
                                    )
                                    if (liveAnswer.isNotBlank()) Spacer(Modifier.padding(vertical = 4.dp))
                                }
                                if (busy && streamText.isEmpty()) {
                                    ThinkingBox(
                                        thinking = "preparando contexto…",
                                        hidden = false,
                                        onToggle = {}
                                    )
                                }
                                ChatBubble(isUser = false, text = liveAnswer.ifBlank { " " })
                                if (busy && streamText.isEmpty() && !showThinkingBox) {
                                    Text(
                                        "gerando…",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                        }
                    }
                }
            }

            ComposerBar(
                viewModel = viewModel,
                chatId = chatId,
                busy = busy,
                canAttach = mmproj != null,
                onPickImages = { pickImages.launch("image/*") }
            )
        }
    }
}

/** Separa raciocínio/resposta do histórico (marcadores fechados já armazenados). */
private fun splitThinkingStored(msg: ChatMsg): Pair<String, String> {
    val c = msg.content
    val m = Regex("<think>([\\s\\S]*?)</think>", RegexOption.IGNORE_CASE).find(c)
    if (m != null) return m.groupValues[1].trim() to c.removeRange(m.range).trim()
    val m2 = Regex("<\\|thinking\\|>([\\s\\S]*?)<\\|/thinking\\|>").find(c)
    if (m2 != null) return m2.groupValues[1].trim() to c.removeRange(m2.range).trim()
    val m3 = Regex("<\\|start_thinking\\|>([\\s\\S]*?)<\\|end_thinking\\|>").find(c)
    if (m3 != null) return m3.groupValues[1].trim() to c.removeRange(m3.range).trim()
    return "" to c.trim()
}

/** Separa raciocínio em streaming: enquanto o marcador não fechou, tudo é thinking. */
private fun splitThinkingLive(raw: String): Pair<String, String> {
    if (raw.isBlank()) return "" to ""
    val opens = listOf("<think>", "<|thinking|>", "<|start_thinking|>")
    val closes = listOf("</think>", "<|/thinking|>", "<|end_thinking|>")
    for (i in opens.indices) {
        val op = opens[i]
        val cl = closes[i]
        val idxOp = raw.indexOf(op)
        if (idxOp >= 0) {
            val idxCl = raw.indexOf(cl, idxOp)
            if (idxCl < 0) return raw.substring(idxOp + op.length).trim() to ""
            return raw.substring(idxOp + op.length, idxCl).trim() to
                    raw.substring(idxCl + cl.length).trim()
        }
        // começou pelo token sem abrir (raro): mostra tudo como texto
    }
    return "" to raw.trim()
}

@Composable
private fun WelcomeHint(noModel: Boolean, noModels: Boolean) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("💬", style = MaterialTheme.typography.displaySmall)
        Spacer(Modifier.padding(8.dp))
        Text(
            if (noModel) "Importe um modelo GGUF (Modelos/⚙ no topo) e configure este chat."
            else "Escreva sua primeira mensagem. Anexe imagens se houver um projetor de visão (mmproj) ativo.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun ComposerBar(
    viewModel: ChatViewModel,
    chatId: String,
    busy: Boolean,
    canAttach: Boolean,
    onPickImages: () -> Unit
) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 3.dp
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .imePadding()
                .padding(horizontal = 10.dp, vertical = 8.dp)
        ) {
            if (viewModel.attachedImages.isNotEmpty()) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState())
                        .padding(bottom = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    viewModel.attachedImages.forEach { path ->
                        Box {
                            AsyncImage(
                                model = ImageRequest.Builder(LocalContext.current)
                                    .data(File(path)).crossfade(true).build(),
                                contentDescription = "anexo",
                                contentScale = ContentScale.Crop,
                                modifier = Modifier
                                    .size(72.dp)
                                    .clip(RoundedCornerShape(8.dp))
                            )
                            IconButton(
                                onClick = { viewModel.removeImage(path) },
                                modifier = Modifier
                                    .size(22.dp)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.surface)
                            ) {
                                Icon(Icons.Filled.Close, contentDescription = "remover", Modifier.size(14.dp))
                            }
                        }
                    }
                }
            }
            Row(verticalAlignment = Alignment.Bottom) {
                IconButton(onClick = onPickImages, enabled = canAttach && !busy) {
                    Icon(
                        Icons.Filled.AttachFile,
                        contentDescription = if (canAttach) "Anexar imagem" else "Sem projetor de visão neste chat",
                        tint = if (canAttach) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f)
                    )
                }
                OutlinedTextField(
                    value = viewModel.input,
                    onValueChange = { viewModel.setInput(it) },
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("Mensagem… (Imagem? use o clipe; 🔎 pesquisa a web)") },
                    maxLines = 6
                )
                if (busy) {
                    IconButton(onClick = { viewModel.stop(chatId) }) {
                        Icon(Icons.Filled.Stop, contentDescription = "Parar", tint = MaterialTheme.colorScheme.error)
                    }
                } else {
                    IconButton(
                        onClick = { viewModel.send(chatId) },
                        enabled = viewModel.input.isNotBlank() || viewModel.attachedImages.isNotEmpty()
                    ) {
                        Icon(Icons.Filled.Send, contentDescription = "Enviar")
                    }
                }
            }
            Row(
                Modifier.padding(start = 8.dp, top = 2.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    Icons.Filled.Public,
                    contentDescription = null,
                    Modifier.size(14.dp),
                    tint = if (viewModel.webSearchEnabled) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    if (viewModel.webSearchEnabled) "Pesquisa na web ativa — consulte fontes antes de responder."
                    else "Pesquisa na web desativada",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (viewModel.webSearchEnabled) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .clickable { viewModel.setWebSearch(!viewModel.webSearchEnabled) }
                        .padding(4.dp)
                )
                if (viewModel.searchingWeb) {
                    CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 2.dp)
                }
            }
        }
    }
}
