package com.vulcanmind.vulkanmind.utils

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import com.vulcanmind.vulkanmind.data.models.Chat
import com.vulcanmind.vulkanmind.data.models.Message
import java.io.File
import java.text.SimpleDateFormat
import java.util.*

object ExportUtils {

    fun chatToMarkdown(chat: Chat, messages: List<Message>): String {
        val sb = StringBuilder()
        sb.appendLine("# ${chat.title}")
        sb.appendLine("_Exportado do VulcanMind Vulkan — ${SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.getDefault()).format(Date())}_")
        sb.appendLine()
        sb.appendLine("**Vulkan:** GGUF direto da memória • mmap zero-copy • 2 slots multimodais")
        sb.appendLine("**Thinking:** ${if (chat.thinkingEnabled) "ativo" else "desativado"} • **Pesquisa:** ${if (chat.searchEnabled) "ativa" else "desativada"}")
        sb.appendLine()
        sb.appendLine("---")
        sb.appendLine()
        for (m in messages) {
            val time = SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(m.timestamp))
            when (m.role) {
                "user" -> {
                    sb.appendLine("### 👤 Você [$time]")
                    sb.appendLine(m.content)
                    if (m.hasImage) sb.appendLine("\n*📎 Imagem anexada (multimodal)*")
                    sb.appendLine()
                }
                "assistant" -> {
                    sb.appendLine("### 🤖 Vulcan [$time]")
                    if (!m.thinkingContent.isNullOrBlank()) {
                        sb.appendLine("<details><summary>Thinking</summary>")
                        sb.appendLine()
                        sb.appendLine(m.thinkingContent)
                        sb.appendLine()
                        sb.appendLine("</details>")
                        sb.appendLine()
                    }
                    sb.appendLine(m.content)
                    if (m.wasGeneratedWithScreenOff) sb.appendLine("\n*🔒 Gerado com tela bloqueada*")
                    if (m.generationTimeMs != null) sb.appendLine("*⏱️ ${m.generationTimeMs}ms*")
                    sb.appendLine()
                }
                "system" -> {
                    sb.appendLine("> Sistema: ${m.content}")
                    sb.appendLine()
                }
            }
        }
        sb.appendLine("---")
        sb.appendLine("_Gerado por VulcanMind 7.0 Vulkan_")
        return sb.toString()
    }

    fun shareMarkdown(context: Context, markdown: String, chatTitle: String) {
        try {
            val file = File(context.cacheDir, "chat_${chatTitle.replace(Regex("[^a-zA-Z0-9]"), "_")}.md")
            file.writeText(markdown)
            val uri = FileProvider.getUriForFile(context, "${context.packageName}.provider", file)
            val intent = Intent(Intent.ACTION_SEND).apply {
                type = "text/markdown"
                putExtra(Intent.EXTRA_STREAM, uri)
                putExtra(Intent.EXTRA_SUBJECT, chatTitle)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            context.startActivity(Intent.createChooser(intent, "Compartilhar chat"))
        } catch (e: Exception) {
            android.util.Log.e("ExportUtils", "share fail", e)
        }
    }

    fun chatToJson(chat: Chat, messages: List<Message>): String {
        // Simple JSON export without serialization lib dependency for standalone
        val sb = StringBuilder()
        sb.appendLine("{")
        sb.appendLine("  \"title\": \"${chat.title.replace("\"", "\\\"")}\",")
        sb.appendLine("  \"exported_at\": ${System.currentTimeMillis()},")
        sb.appendLine("  \"messages\": [")
        messages.forEachIndexed { idx, m ->
            sb.append("    {\"role\":\"${m.role}\", \"content\":\"${m.content.replace("\"", "\\\"").replace("\n", "\\n").take(500)}\", \"ts\":${m.timestamp}}")
            if (idx < messages.size - 1) sb.append(",")
            sb.appendLine()
        }
        sb.appendLine("  ]")
        sb.appendLine("}")
        return sb.toString()
    }
}
