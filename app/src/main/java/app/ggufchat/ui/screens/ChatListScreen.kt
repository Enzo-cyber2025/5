package app.ggufchat.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.ggufchat.data.Chat
import app.ggufchat.data.Repo
import app.ggufchat.data.Store
import app.ggufchat.util.Markdown
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatListScreen(
    onOpenChat: (String) -> Unit,
    onNewChat: (String) -> Unit,
    onModels: () -> Unit,
    onSettings: () -> Unit
) {
    val chats by Repo.chatsMeta.collectAsState()
    val models by Repo.models.collectAsState()
    var confirmDelete by remember { mutableStateOf<Chat?>(null) }
    var showNewChat by remember { mutableStateOf(false) }

    confirmDelete?.let { chat ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Excluir conversa?") },
            text = { Text("\"${chat.title}\" será apagada junto com as imagens anexadas.") },
            confirmButton = {
                TextButton(onClick = {
                    Store.deleteChat(chat.id)
                    if (Repo.chat.value?.id == chat.id) Repo.setChat(null)
                    confirmDelete = null
                }) { Text("Excluir", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { confirmDelete = null }) { Text("Cancelar") }
            }
        )
    }

    if (showNewChat) {
        NewChatDialog(
            models = models,
            onDismiss = { showNewChat = false },
            onCreate = { modelId, mmprojId ->
                showNewChat = false
                val id = Store.newId("chat")
                val now = System.currentTimeMillis()
                val m = models.firstOrNull { it.id == modelId }
                val chat = Chat(
                    id = id,
                    title = "Novo chat",
                    modelId = modelId,
                    mmprojId = mmprojId,
                    systemPrompt = m?.systemPrompt ?: "",
                    createdAt = now,
                    updatedAt = now,
                    nCtx = m?.nCtxDefault ?: 4096
                )
                Store.saveChat(chat)
                Repo.setChat(chat)
                Repo.refreshChatsMeta()
                onNewChat(id)
            }
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("GGUF Chat") },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                ),
                actions = {
                    IconButton(onClick = onModels) {
                        Icon(Icons.Filled.Memory, contentDescription = "Modelos")
                    }
                    IconButton(onClick = onSettings) {
                        Icon(Icons.Filled.Settings, contentDescription = "Ajustes")
                    }
                }
            )
        },
        floatingActionButton = {
            FilledTonalIconButton(onClick = { showNewChat = true }) {
                Icon(Icons.Filled.Add, contentDescription = "Novo chat")
            }
        }
    ) { pad ->
        if (chats.isEmpty()) {
            EmptyState(pad)
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 8.dp, bottom = 88.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(chats, key = { it.id }) { chat ->
                    ChatRow(
                        chat = chat,
                        modelName = models.firstOrNull { it.id == chat.modelId }?.name ?: chat.modelId,
                        onClick = { onOpenChat(chat.id) },
                        onDelete = { confirmDelete = chat }
                    )
                }
            }
        }
    }
}

@Composable
private fun EmptyState(pad: PaddingValues) {
    Box(
        Modifier
            .fillMaxSize()
            .padding(pad),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(
                Icons.Filled.SmartToy,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(bottom = 12.dp)
            )
            Text("Sem conversas ainda", style = MaterialTheme.typography.titleMedium)
            Text(
                "Toque em + para criar um chat e importar seus modelos GGUF em Modelos.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 32.dp, vertical = 8.dp)
            )
        }
    }
}

@Composable
private fun ChatRow(chat: Chat, modelName: String, onClick: () -> Unit, onDelete: () -> Unit) {
    val fmt = remember { SimpleDateFormat("dd/MM HH:mm", Locale.getDefault()) }
    Card(
        onClick = onClick,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    chat.title,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.padding(top = 2.dp))
                Text(
                    modelName + (if (chat.mmprojId.isNotBlank()) " + visão" else ""),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Text(
                fmt.format(Date(chat.updatedAt)),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(end = 4.dp)
            )
            IconButton(onClick = onDelete) {
                Icon(
                    Icons.Filled.DeleteOutline,
                    contentDescription = "Excluir",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun NewChatDialog(
    models: List<app.ggufchat.data.ChatModel>,
    onDismiss: () -> Unit,
    onCreate: (String, String) -> Unit
) {
    val llms = models.filter { it.isLlm }
    val vision = models.filter { it.isVisionProjector }
    var modelId by remember { mutableStateOf(llms.firstOrNull()?.id ?: "") }
    var mmprojId by remember { mutableStateOf("") }
    var modelOpen by remember { mutableStateOf(false) }
    var mmOpen by remember { mutableStateOf(false) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Novo chat") },
        text = {
            Column {
                if (llms.isEmpty()) {
                    Text(
                        "Nenhum modelo de texto importado. Vá em Modelos e importe um GGUF (llama, qwen, gemma…) " +
                                "e opcionalmente um projetor multimídia (mmproj) para suporte a imagens.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error
                    )
                } else {
                    ExposedDropdownMenuBox(expanded = modelOpen, onExpandedChange = { modelOpen = it }) {
                        OutlinedTextField(
                            value = llms.firstOrNull { it.id == modelId }?.name ?: "",
                            onValueChange = {},
                            readOnly = true,
                            label = { Text("Modelo de texto") },
                            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(modelOpen) },
                            modifier = Modifier
                                .menuAnchor()
                                .fillMaxWidth()
                        )
                        ExposedDropdownMenu(expanded = modelOpen, onDismissRequest = { modelOpen = false }) {
                            llms.forEach { m ->
                                DropdownMenuItem(
                                    text = { Text(m.name.ifBlank { m.fileName }) },
                                    onClick = {
                                        modelId = m.id
                                        modelOpen = false
                                    }
                                )
                            }
                        }
                    }
                    Spacer(Modifier.padding(top = 10.dp))
                    ExposedDropdownMenuBox(expanded = mmOpen, onExpandedChange = { mmOpen = it }) {
                        OutlinedTextField(
                            value = vision.firstOrNull { it.id == mmprojId }?.name ?: "(nenhum)",
                            onValueChange = {},
                            readOnly = true,
                            label = { Text("Projetor de visão (mmproj)") },
                            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(mmOpen) },
                            modifier = Modifier
                                .menuAnchor()
                                .fillMaxWidth()
                        )
                        ExposedDropdownMenu(expanded = mmOpen, onDismissRequest = { mmOpen = false }) {
                            DropdownMenuItem(
                                text = { Text("(nenhum)") },
                                onClick = { mmprojId = ""; mmOpen = false }
                            )
                            vision.forEach { m ->
                                DropdownMenuItem(
                                    text = { Text(m.name.ifBlank { m.fileName }) },
                                    onClick = { mmprojId = m.id; mmOpen = false }
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = llms.isNotEmpty(),
                onClick = { onCreate(modelId, mmprojId) }
            ) { Text("Criar") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancelar") }
        }
    )
}
