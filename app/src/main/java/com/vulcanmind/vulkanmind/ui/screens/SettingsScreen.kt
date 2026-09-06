package com.vulcanmind.vulkanmind.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.BatteryAlert
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import com.vulcanmind.vulkanmind.MainViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(viewModel: MainViewModel, onBack: () -> Unit) {
    val ctx = LocalContext.current
    var thinking by remember { mutableStateOf(viewModel.thinkingEnabled) }
    var search by remember { mutableStateOf(viewModel.searchEnabled) }
    val deviceInfo = remember { viewModel.modelManager.getDeviceInfo() }
    val vulkan = remember { viewModel.modelManager.getVulkanStatus() }

    Scaffold(topBar = {
        TopAppBar(title = { Text("Configurações", fontWeight = FontWeight.Bold) }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.Default.ArrowBack, contentDescription = null) } })
    }) { pad ->
        Column(modifier = Modifier.fillMaxSize().padding(pad).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {

            Card(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp)) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text("Ferramentas", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(10.dp))
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Column {
                            Text("Thinking (raciocínio)", style = MaterialTheme.typography.bodyMedium)
                            Text("Mostra bloco <think> colapsável", style = MaterialTheme.typography.labelSmall)
                        }
                        Switch(checked = thinking, onCheckedChange = { thinking = it; viewModel.thinkingEnabled = it })
                    }
                    Divider(modifier = Modifier.padding(vertical = 10.dp))
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Column {
                            Text("Pesquisa Web", style = MaterialTheme.typography.bodyMedium)
                            Text("Tool automática via DuckDuckGo + Wiki", style = MaterialTheme.typography.labelSmall)
                        }
                        Switch(checked = search, onCheckedChange = { search = it; viewModel.searchEnabled = it })
                    }
                }
            }

            Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer), shape = RoundedCornerShape(16.dp)) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row {
                        Icon(Icons.Default.BatteryAlert, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Geração com tela bloqueada", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.height(6.dp))
                    Text("Ativado via ForegroundService + PARTIAL_WAKE_LOCK. O sistema mantém CPU acordada mesmo com display off. Notificação persistente garante que o Android não mate o processo.", style = MaterialTheme.typography.bodySmall)
                    Spacer(Modifier.height(10.dp))
                    Button(onClick = {
                        // Pedir para ignorar otimização de bateria
                        try {
                            val pm = ctx.getSystemService(android.content.Context.POWER_SERVICE) as PowerManager
                            if (!pm.isIgnoringBatteryOptimizations(ctx.packageName)) {
                                val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                                    data = Uri.parse("package:${ctx.packageName}")
                                }
                                ctx.startActivity(intent)
                            }
                        } catch (_: Exception) {
                            ctx.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                        }
                    }, modifier = Modifier.fillMaxWidth()) {
                        Text("Desativar otimização de bateria (recomendado)")
                    }
                    Text("Sem isso, alguns fabricantes pausam o app com tela bloqueada. Com WakeLock + foreground, continua gerando.", style = MaterialTheme.typography.labelSmall)
                }
            }

            Card(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp)) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text("Dispositivo & Vulkan", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(6.dp))
                    Text(vulkan, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(6.dp))
                    Text(deviceInfo, style = MaterialTheme.typography.bodySmall)
                    Spacer(Modifier.height(6.dp))
                    Text("APIs: Vulkan 1.3 + GGML_VULKAN=ON + mmap zero-copy + OkHttp + Room + DataStore + ForegroundService", style = MaterialTheme.typography.labelSmall)
                }
            }

            Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant), shape = RoundedCornerShape(16.dp)) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text("Sobre • VulcanMind 7.0", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
                    Text("UI gráfica com chats organizados. Importe 2 GGUFs multimodais (LLM + Vision) que rodam diretamente da memória via Vulkan. Thinking e pesquisa como tools. Geração continua com tela bloqueada.\n\nCompilado via GitHub Actions + Gradle 8.7 + NDK 26 + Vulkan. Sem código fonte no release — apenas APK.", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}
