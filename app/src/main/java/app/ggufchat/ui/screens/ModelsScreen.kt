package app.ggufchat.ui.screens

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.ggufchat.core.CoreEngine
import app.ggufchat.data.ChatModel
import app.ggufchat.data.Repo
import app.ggufchat.data.Store
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ModelsScreen(onBack: () -> Unit) {
    val models by Repo.models.collectAsState()
    val device by CoreEngine.device.collectAsState()
    var importing by remember { mutableStateOf(false) }
    var importProgress by remember { mutableStateOf("") }
    var confirmDelete by remember { mutableStateOf<ChatModel?>(null) }
    var renameTarget by remember { mutableStateOf<ChatModel?>(null) }
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    val open = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenMultipleDocuments()
    ) { uris ->
        if (uris.isNotEmpty()) {
            scope.launch { importUris(uris) }
        }
    }

    suspend fun importUris(uris: List<Uri>) {
        val ctx = Store.appContext
        importing = true
        val added = ArrayList<ChatModel>()
        try {
            for ((i, uri) in uris.withIndex()) {
                importProgress = "Copiando ${i + 1}/${uris.size}…"
                val name = uri.lastPathSegment?.substringAfterLast('/') ?: "modelo.gguf"
                if (!name.endsWith(".gguf", ignoreCase = true)) {
                    Repo.toast("$name não é um arquivo .gguf")
                    continue
                }
                val dest = File(Store.modelsDir(), name)
                val ok = withContext(Dispatchers.IO) {
                    runCatching {
                        ctx.contentResolver.openInputStream(uri)?.use { ins ->
                            dest.outputStream().use { out -> ins.copyTo(out) }
                        } != null && dest.length() > 0
                    }.getOrDefault(false)
                }
                if (!ok) {
                    Repo.toast("Falha ao copiar $name")
                    continue
                }
                importProgress = "Analisando ${name}…"
                val probe = withContext(Dispatchers.Default) { CoreEngine.probe(dest.absolutePath) }
                if (!probe.ok) {
                    Repo.toast("Arquivo inválido: ${probe.error ?: name}")
                    dest.delete()
                    continue
                }
                val m = ChatModel(
                    id = Store.slugFromFileName(name) + "-" + dest.name.hashCode().toString(16).take(4),
                    name = probe.name.ifBlank { name.removeSuffix(".gguf") },
                    fileName = name,
                    file = dest.absolutePath,
                    size = probe.size,
                    arch = probe.arch,
                    isLlm = probe.is_llm,
                    createdAt = System.currentTimeMillis(),
                    nCtxDefault = 4096,
                    threads = 4
                )
                added.add(m)
            }
            if (added.isNotEmpty()) {
                Repo.addModels(added)
                Repo.toast("${added.size} modelo(s) importado(s)")
            }
        } finally {
            importing = false
            importProgress = ""
        }
    }

    confirmDelete?.let { m ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Remover modelo?") },
            text = { Text("O arquivo \"${m.fileName}\" será apagado do armazenamento do app.") },
            confirmButton = {
                TextButton(onClick = {
                    CoreEngine.scope.launch {
                        runCatching { File(m.file).delete() }
                        Repo.removeModel(m.id)
                    }
                    confirmDelete = null
                }) { Text("Remover", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Cancelar") } }
        )
    }

    renameTarget?.let { m ->
        RenameDialog(m, onDismiss = { renameTarget = null }, onRename = { newName ->
            Repo.updateModel(m.copy(name = newName))
            renameTarget = null
        })
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Modelos GGUF") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Voltar")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                )
            )
        }
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            DeviceCard(device)
            Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) {
                Text("Modelos locais (GGUF)", style = MaterialTheme.typography.titleMedium)
                Text(
                    "Importados diretamente do armazenamento do aparelho. " +
                            "Cada modelo fica armazenado dentro do app e roda 100% local.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (importing) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                    Text(
                        importProgress,
                        modifier = Modifier.padding(start = 10.dp),
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            }
            LazyColumn(
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.weight(1f)
            ) {
                items(models, key = { it.id }) { m ->
                    ModelRow(
                        m,
                        onDelete = { confirmDelete = m },
                        onRename = { renameTarget = m }
                    )
                }
            }
            Button(
                onClick = {
                    open.launch(arrayOf("application/octet-stream", "application/gguf", "*/*"))
                },
                enabled = !importing,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp)
            ) {
                Icon(Icons.Filled.Add, contentDescription = null)
                Spacer(Modifier.padding(4.dp))
                Text("Importar GGUF do aparelho (pode escolher vários)")
            }
        }
    }
}

@Composable
private fun DeviceCard(device: app.ggufchat.data.DeviceInfo?) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainer
        ),
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp)
    ) {
        Column(Modifier.padding(12.dp)) {
            Text("Motor", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
            when {
                device == null -> Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
                    Text(" verificando…", style = MaterialTheme.typography.bodyMedium)
                }
                !device.ok -> Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.Warning, contentDescription = null, tint = MaterialTheme.colorScheme.error)
                    Text(
                        " ${device.error ?: "erro"}\nO Vulkan não está disponível — os modelos vão rodar em CPU (lentos).",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                else -> Column {
                    if (device.vulkan) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.Star, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                            Text(
                                " Vulkan ativo: ${device.gpuName}",
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.SemiBold
                            )
                        }
                        Text(
                            "GPU: ${Store.sizeText(device.gpuTotal)} total · ${Store.sizeText(device.gpuFree)} livre · llama.cpp ${device.llama}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    } else {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.Warning, contentDescription = null, tint = MaterialTheme.colorScheme.error)
                            Text(
                                " Vulkan indisponível — CPU apenas",
                                style = MaterialTheme.typography.bodyMedium
                            )
                        }
                        Text(
                            "Este aparelho não expõe uma GPU Vulkan ao app; a inferência usará a CPU.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ModelRow(m: ChatModel, onDelete: () -> Unit, onRename: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainer
        )
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    if (m.isVisionProjector) Icons.Filled.CameraAlt else Icons.Filled.Memory,
                    contentDescription = null,
                    tint = if (m.isVisionProjector) MaterialTheme.colorScheme.secondary
                    else MaterialTheme.colorScheme.primary
                )
                Column(Modifier.padding(start = 10.dp).weight(1f)) {
                    Text(m.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                    Text(
                        "${m.fileName} · ${Store.sizeText(m.size)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1
                    )
                }
                IconButton(onClick = onRename) {
                    Icon(Icons.Filled.Edit, contentDescription = "Renomear", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                IconButton(onClick = onDelete) {
                    Icon(Icons.Filled.DeleteOutline, contentDescription = "Remover", tint = MaterialTheme.colorScheme.error)
                }
            }
            Row {
                if (m.isLlm) {
                    AssistChip(onClick = {}, label = { Text("texto") })
                }
                if (m.isVisionProjector) {
                    AssistChip(
                        onClick = {},
                        label = { Text(if (m.isLlm && m.forceMmproj) "forçado como mmproj (multimodal)" else "mmproj (multimodal)") }
                    )
                }
                if (m.arch.isNotBlank()) {
                    AssistChip(onClick = {}, label = { Text(m.arch) })
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RenameDialog(m: ChatModel, onDismiss: () -> Unit, onRename: (String) -> Unit) {
    var name by remember { mutableStateOf(m.name) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Renomear modelo") },
        text = {
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                singleLine = true,
                label = { Text("Nome exibido") }
            )
        },
        confirmButton = {
            TextButton(onClick = { onRename(name.trim().ifBlank { m.fileName }) }, enabled = name.isNotBlank()) {
                Text("Salvar")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } }
    )
}
