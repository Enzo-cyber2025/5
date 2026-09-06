package com.vulcanmind.vulkanmind.ui.screens

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.vulcanmind.vulkanmind.MainViewModel
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ModelImportScreen(viewModel: MainViewModel, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var loadingSlot by remember { mutableStateOf<Int?>(null) }
    var message by remember { mutableStateOf<String?>(null) }

    val slotA = viewModel.modelManager.getSlotState(0)
    val slotB = viewModel.modelManager.getSlotState(1)
    val vulkan = viewModel.modelManager.getVulkanStatus()
    val deviceInfo = viewModel.modelManager.getDeviceInfo()

    var currentPickerSlot by remember { mutableStateOf(0) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) {
            scope.launch {
                loadingSlot = currentPickerSlot
                message = "Importando GGUF slot $currentPickerSlot… mmap direto da memória via Vulkan"
                val res = viewModel.modelManager.importGguf(uri, currentPickerSlot)
                loadingSlot = null
                message = if (res.isSuccess) "✅ GGUF importado slot $currentPickerSlot — Vulkan pronto" else "❌ Falha: ${res.exceptionOrNull()?.message}"
            }
        }
    }

    // Se veio via share intent
    LaunchedEffect(viewModel.pendingImportUri) {
        viewModel.pendingImportUri?.let { uri ->
            // auto import para slot A
            loadingSlot = 0
            viewModel.modelManager.importGguf(uri, 0)
            loadingSlot = null
            viewModel.pendingImportUri = null
        }
    }

    Scaffold(topBar = {
        TopAppBar(title = { Text("Importar GGUFs • Vulkan", fontWeight = FontWeight.Bold) }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.Default.ArrowBack, contentDescription = null) } })
    }) { pad ->
        Column(modifier = Modifier.fillMaxSize().padding(pad).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {

            Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer), shape = RoundedCornerShape(16.dp)) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Bolt, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(8.dp))
                        Text(vulkan, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(deviceInfo, style = MaterialTheme.typography.bodySmall)
                    Spacer(Modifier.height(6.dp))
                    Text("Até 2 GGUFs simultâneos • Slot A = LLM principal • Slot B = Vision/multimodal • Ambos via mmap zero-copy + Vulkan compute shaders", style = MaterialTheme.typography.labelSmall)
                }
            }

            // Slot A
            Card(modifier = Modifier.fillMaxWidth(), elevation = CardDefaults.cardElevation(2.dp), shape = RoundedCornerShape(16.dp)) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Memory, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(8.dp))
                        Text("Slot A — LLM Principal", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.weight(1f))
                        if (slotA.isLoaded) Icon(Icons.Default.CheckCircle, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    }
                    Spacer(Modifier.height(8.dp))
                    if (slotA.isLoaded) {
                        Text(slotA.name ?: "modelo", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                        Text("${slotA.sizeBytes / (1024*1024)} MB • ${slotA.path}", style = MaterialTheme.typography.bodySmall, maxLines = 2)
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = { scope.launch { viewModel.modelManager.unload(0) } }) { Text("Remover") }
                            Button(onClick = { currentPickerSlot = 0; picker.launch("*/*") }) { Text("Trocar GGUF") }
                        }
                    } else {
                        Text("Nenhum GGUF carregado. Importe um .gguf (ex: Qwen2-7B, Llama-3.1-8B)", style = MaterialTheme.typography.bodySmall)
                        Spacer(Modifier.height(10.dp))
                        Button(onClick = { currentPickerSlot = 0; picker.launch("*/*") }, modifier = Modifier.fillMaxWidth(), enabled = loadingSlot == null) {
                            if (loadingSlot == 0) CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                            else Icon(Icons.Default.FileOpen, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text("Importar GGUF para Slot A")
                        }
                        Text("Diretamente da memória - usa ParcelFileDescriptor + mmap, sem copiar para heap", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }

            // Slot B
            Card(modifier = Modifier.fillMaxWidth(), elevation = CardDefaults.cardElevation(2.dp), shape = RoundedCornerShape(16.dp)) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Image, contentDescription = null, tint = MaterialTheme.colorScheme.secondary)
                        Spacer(Modifier.width(8.dp))
                        Text("Slot B — Vision / Multimodal", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.weight(1f))
                        if (slotB.isLoaded) Icon(Icons.Default.CheckCircle, contentDescription = null, tint = MaterialTheme.colorScheme.secondary)
                    }
                    Spacer(Modifier.height(8.dp))
                    if (slotB.isLoaded) {
                        Text(slotB.name ?: "modelo vision", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                        Text("${slotB.sizeBytes / (1024*1024)} MB • ${slotB.path}", style = MaterialTheme.typography.bodySmall, maxLines = 2)
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = { scope.launch { viewModel.modelManager.unload(1) } }) { Text("Remover") }
                            Button(onClick = { currentPickerSlot = 1; picker.launch("*/*") }) { Text("Trocar GGUF") }
                        }
                    } else {
                        Text("Opcional. Para multimodal: carregue projector/encoder (ex: mmproj, llava, qwen-vl)", style = MaterialTheme.typography.bodySmall)
                        Spacer(Modifier.height(10.dp))
                        Button(onClick = { currentPickerSlot = 1; picker.launch("*/*") }, modifier = Modifier.fillMaxWidth(), enabled = loadingSlot == null, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.secondary)) {
                            if (loadingSlot == 1) CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                            else Icon(Icons.Default.FileOpen, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text("Importar GGUF Multimodal Slot B")
                        }
                        Text("Slot B roda junto com A — inferência conjunta Vulkan: LLM + Vision", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }

            if (message != null) {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer), shape = RoundedCornerShape(12.dp)) {
                    Text(message!!, modifier = Modifier.padding(12.dp), style = MaterialTheme.typography.bodySmall)
                }
            }

            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant), shape = RoundedCornerShape(12.dp)) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("Como importar", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(6.dp))
                    Text("1. Baixe um .gguf (ex: do Hugging Face) para Downloads\n2. Toque em Importar e selecione o arquivo\n3. O app faz mmap direto da memória (zero-copy) e registra no VkDevice\n4. Pronto — organize conversas em chats com thinking + pesquisa", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}
