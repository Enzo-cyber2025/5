package app.ggufchat.ui.screens

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
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.ggufchat.data.Repo

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(onBack: () -> Unit) {
    val s by Repo.settings.collectAsState()
    var themeOpen by remember { mutableStateOf(false) }

    fun set(block: (app.ggufchat.data.AppSettings) -> app.ggufchat.data.AppSettings) {
        Repo.updateSettings(block(s))
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Ajustes") },
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
        Column(
            Modifier
                .fillMaxSize()
                .padding(pad)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 18.dp),
        ) {
            Spacer(Modifier.padding(6.dp))
            SectionTitle("Geração")
            SettingRow(
                title = "Continuar com a tela bloqueada",
                desc = "Mantém a geração rodando em segundo plano (notificação + wake lock) mesmo com a tela desligada."
            ) {
                Switch(checked = s.bgGenerate, onCheckedChange = { set { it.copy(bgGenerate = it) } })
            }

            Spacer(Modifier.padding(6.dp))
            SectionTitle("Modelos")
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(Modifier.weight(1f)) {
                    Text("Threads de CPU: ${s.cpuThreads}", fontWeight = FontWeight.SemiBold)
                    Text(
                        "Paralelismo para partes em CPU (quanto maior o modelo, mais útil).",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            Slider(
                value = s.cpuThreads.toFloat(),
                onValueChange = { v -> set { it.copy(cpuThreads = v.toInt().coerceIn(1, 16)) } },
                valueRange = 1f..16f,
                steps = 14
            )

            Spacer(Modifier.padding(10.dp))
            SectionTitle("Interface")
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Tema", fontWeight = FontWeight.SemiBold)
                }
                ExposedDropdownMenuBox(expanded = themeOpen, onExpandedChange = { themeOpen = it }) {
                    OutlinedTextField(
                        value = when (s.theme) {
                            "dark" -> "Escuro"
                            "light" -> "Claro"
                            else -> "Sistema"
                        },
                        onValueChange = {},
                        readOnly = true,
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(themeOpen) },
                        modifier = Modifier.menuAnchor()
                    )
                    ExposedDropdownMenu(expanded = themeOpen, onDismissRequest = { themeOpen = false }) {
                        DropdownMenuItem(text = { Text("Sistema") }, onClick = { set { it.copy(theme = "system") }; themeOpen = false })
                        DropdownMenuItem(text = { Text("Escuro") }, onClick = { set { it.copy(theme = "dark") }; themeOpen = false })
                        DropdownMenuItem(text = { Text("Claro") }, onClick = { set { it.copy(theme = "light") }; themeOpen = false })
                    }
                }
            }
            SettingRow(
                title = "Recolher blocos de raciocínio",
                desc = "Esconde automaticamente o conteúdo de \"Pensando…\""
            ) {
                Switch(checked = s.hideThinking, onCheckedChange = { on -> set { it.copy(hideThinking = on) } })
            }
            SettingRow(
                title = "Ferramenta de pesquisa na web",
                desc = "Mostra o seletor 🔎 que consulta a internet e injeta fontes na conversa."
            ) {
                Switch(checked = s.searchEnabled, onCheckedChange = { on -> set { it.copy(searchEnabled = on) } })
            }
            Spacer(Modifier.padding(16.dp))
            Text(
                "GGUF Chat · 100% local · llama.cpp + Vulkan · modelos GGUF importados do aparelho",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.padding(12.dp))
        }
    }
}

@Composable
private fun SectionTitle(t: String) {
    Text(
        t,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(bottom = 4.dp)
    )
}

@Composable
private fun SettingRow(
    title: String,
    desc: String,
    content: @Composable () -> Unit
) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, fontWeight = FontWeight.SemiBold)
            Text(
                desc,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Spacer(Modifier.padding(horizontal = 8.dp))
        content()
    }
}
