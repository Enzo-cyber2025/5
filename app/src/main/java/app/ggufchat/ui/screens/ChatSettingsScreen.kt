package app.ggufchat.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.ggufchat.core.CoreEngine
import app.ggufchat.data.Chat
import app.ggufchat.data.Repo
import app.ggufchat.data.Store
import kotlin.math.roundToInt

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatSettingsScreen(chatId: String, onBack: () -> Unit) {
    var chat by remember { mutableStateOf(Store.loadChat(chatId)) }
    val models by Repo.models.collectAsState()
    val llms = models.filter { it.isLlm }
    val vision = models.filter { it.isVisionProjector }
    var confirmDelete by remember { mutableStateOf(false) }

    if (chat == null) {
        LaunchedEffect(Unit) { onBack() }
        return
    }
    val c = chat!!
    var nCtxDraft by remember(c.id) { mutableIntStateOf(c.nCtx) }

    fun save(next: Chat, reset: Boolean = false) {
        chat = next
        Store.saveChat(next)
        Repo.setChat(next)
        Repo.refreshChatsMeta()
        if (reset) CoreEngine.resetChat(next.id)
    }

    confirmDelete.takeIf { it }?.let {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Excluir conversa?") },
            text = { Text("Isso apaga o histórico e as imagens anexadas deste chat.") },
            confirmButton = {
                TextButton(onClick = {
                    Store.deleteChat(chatId)
                    if (Repo.chat.value?.id == chatId) Repo.setChat(null)
                    onBack()
                }) { Text("Excluir", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancelar") } }
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Configurar chat") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Voltar") }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                ),
                actions = {
                    IconButton(onClick = { onBack() }) { Icon(Icons.Filled.Check, "Concluído") }
                }
            )
        }
    ) { pad ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(pad)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Spacer(Modifier.padding(2.dp))
            Text("Título", fontWeight = FontWeight.SemiBold)
            OutlinedTextField(
                value = c.title,
                onValueChange = { v -> save(c.copy(title = v)) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )

            Text("Modelo de texto (GGUF)", fontWeight = FontWeight.SemiBold)
            if (llms.isEmpty()) {
                Text(
                    "Nenhum modelo importado. Importe um GGUF primeiro.",
                    color = MaterialTheme.colorScheme.error
                )
            } else {
            ModelDropdown(
                label = llms.firstOrNull { it.id == c.modelId }?.name ?: "Selecionar modelo",
                items = llms.map { it.id to (it.name.ifBlank { it.fileName }) },
                selected = c.modelId,
                onChange = { save(c.copy(modelId = it), reset = true) }
            )
            }

            Text("Projetor de visão — mmproj (multimodal)", fontWeight = FontWeight.SemiBold)
            ModelDropdown(
                label = vision.firstOrNull { it.id == c.mmprojId }?.name ?: "(nenhum)",
                items = listOf("" to "(nenhum)") + vision.map { it.id to (it.name.ifBlank { it.fileName }) },
                selected = c.mmprojId,
                onChange = { save(c.copy(mmprojId = it), reset = true) }
            )
            Text(
                "Com um mmproj, este chat consegue entender imagens (modelos como llava, qwen-vl, minicpm-v, moondream).",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            Text("Instruções de sistema", fontWeight = FontWeight.SemiBold)
            OutlinedTextField(
                value = c.systemPrompt,
                onValueChange = { v -> save(c.copy(systemPrompt = v), reset = true) },
                modifier = Modifier.fillMaxWidth(),
                minLines = 2,
                maxLines = 5
            )

            Text("Contexto (n_ctx)", fontWeight = FontWeight.SemiBold)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Slider(
                    value = nCtxDraft.toFloat(),
                    onValueChange = { v -> nCtxDraft = v.roundToInt() / 512 * 512 },
                    onValueChangeFinished = { save(c.copy(nCtx = nCtxDraft), reset = true) },
                    valueRange = 1024f..32768f,
                    modifier = Modifier.weight(1f)
                )
                Text("$nCtxDraft", style = MaterialTheme.typography.labelLarge)
            }

            Text("Temperatura: ${"%.2f".format(c.temp)}", fontWeight = FontWeight.SemiBold)
            Slider(
                value = c.temp.toFloat(),
                onValueChange = { v -> save(c.copy(temp = v.toDouble())) },
                valueRange = 0f..2f
            )

            Text("Top-P: ${"%.2f".format(c.topP)}", fontWeight = FontWeight.SemiBold)
            Slider(
                value = c.topP.toFloat(),
                onValueChange = { v -> save(c.copy(topP = v.toDouble())) },
                valueRange = 0.1f..1f
            )

            Text("Top-K: ${c.topK}", fontWeight = FontWeight.SemiBold)
            Slider(
                value = c.topK.toFloat(),
                onValueChange = { v -> save(c.copy(topK = v.roundToInt())) },
                valueRange = 1f..100f
            )

            Text("Penalidade de repetição: ${"%.2f".format(c.repeatPenalty)}", fontWeight = FontWeight.SemiBold)
            Slider(
                value = c.repeatPenalty.toFloat(),
                onValueChange = { v -> save(c.copy(repeatPenalty = v.toDouble())) },
                valueRange = 1f..1.6f
            )

            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Flash attention", fontWeight = FontWeight.SemiBold)
                    Text(
                        "Acelera com GPU (recomendado no Vulkan)",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Switch(checked = c.flashAttn, onCheckedChange = { save(c.copy(flashAttn = it), reset = true) })
            }

            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Mostrar raciocínio do modelo", fontWeight = FontWeight.SemiBold)
                    Text(
                        "Exibe o bloco \"Pensando…\" quando o modelo usa marcadores de raciocínio",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Switch(checked = c.thinking, onCheckedChange = { save(c.copy(thinking = it)) })
            }

            Spacer(Modifier.padding(4.dp))
            OutlinedButton(
                onClick = {
                    save(c.copy(msgs = emptyList(), updatedAt = System.currentTimeMillis()), reset = true)
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Limpar histórico")
            }
            Button(
                onClick = { confirmDelete = true },
                colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Icon(Icons.Filled.Delete, contentDescription = null)
                Spacer(Modifier.padding(4.dp))
                Text("Excluir conversa")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ModelDropdown(
    label: String,
    items: List<Pair<String, String>>,
    selected: String,
    onChange: (String) -> Unit
) {
    var open by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = open, onExpandedChange = { open = it }) {
        OutlinedTextField(
            value = label,
            onValueChange = {},
            readOnly = true,
            singleLine = true,
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
            modifier = Modifier
                .menuAnchor()
                .fillMaxWidth()
        )
        ExposedDropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            items.forEach { (id, name) ->
                DropdownMenuItem(
                    text = { Text(name) },
                    onClick = { onChange(id); open = false }
                )
            }
        }
    }
}
