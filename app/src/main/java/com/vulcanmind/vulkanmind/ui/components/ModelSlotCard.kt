package com.vulcanmind.vulkanmind.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.vulcanmind.vulkanmind.inference.ModelManager

@Composable
fun ModelSlotCard(
    slot: Int,
    state: ModelManager.SlotState,
    onImport: () -> Unit,
    onRemove: () -> Unit,
    modifier: Modifier = Modifier
) {
    val label = if (slot == 0) "Slot A — LLM" else "Slot B — Vision"
    val iconTint = if (slot == 0) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.secondary
    Card(modifier = modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp), elevation = CardDefaults.cardElevation(2.dp)) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Memory, contentDescription = null, tint = iconTint)
                Spacer(Modifier.width(8.dp))
                Text(label, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Spacer(Modifier.weight(1f))
                if (state.isLoaded) Icon(Icons.Default.CheckCircle, contentDescription = null, tint = iconTint)
                else Icon(Icons.Default.Error, contentDescription = null, tint = MaterialTheme.colorScheme.error)
            }
            Spacer(Modifier.height(8.dp))
            if (state.isLoaded) {
                Text(state.name ?: "GGUF carregado", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                Text("${state.sizeBytes / (1024*1024)} MB • mmap direto • Vulkan", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                Text(state.path ?: "", style = MaterialTheme.typography.labelSmall, maxLines = 2)
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = onRemove, modifier = Modifier.weight(1f)) { Text("Remover") }
                    Button(onClick = onImport, modifier = Modifier.weight(1f)) { Text("Trocar") }
                }
            } else {
                Text("Nenhum GGUF neste slot", style = MaterialTheme.typography.bodySmall)
                Text(if (slot == 0) "LLM principal (ex: Qwen2-7B.gguf)" else "Vision projector (ex: mmproj.gguf)", style = MaterialTheme.typography.labelSmall)
                Spacer(Modifier.height(10.dp))
                Button(onClick = onImport, modifier = Modifier.fillMaxWidth()) { Text("Importar GGUF ${if (slot == 0) "A" else "B"}") }
            }
            // Vulkan tag
            Spacer(Modifier.height(6.dp))
            VulkanBadge(isActive = state.vulkan || state.isLoaded)
        }
    }
}

@Composable
fun DualSlotRow(stateA: ModelManager.SlotState, stateB: ModelManager.SlotState, onImportA: () -> Unit, onImportB: () -> Unit, onRemoveA: () -> Unit, onRemoveB: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        ModelSlotCard(slot = 0, state = stateA, onImport = onImportA, onRemove = onRemoveA)
        ModelSlotCard(slot = 1, state = stateB, onImport = onImportB, onRemove = onRemoveB)
    }
}
