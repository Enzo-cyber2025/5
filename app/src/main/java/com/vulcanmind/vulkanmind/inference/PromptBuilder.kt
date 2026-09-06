package com.vulcanmind.vulkanmind.inference

import com.vulcanmind.vulkanmind.data.models.Message

object PromptBuilder {

    private const val SYSTEM_BASE = """Você é VulcanMind Vulkan — um assistente que roda GGUFs diretamente da memória via Vulkan.
Regras:
- Seja útil, direto e em português (a menos que usuário peça outro idioma).
- Quando thinking estiver ativo, raciocine passo-a-passo dentro de <think>.
- Quando houver resultados de pesquisa, use-os e cite fontes.
- Para multimodal (imagem), descreva o que vê com base nos embeddings do slot B.
- Nunca invente que não tem Vulkan se o status for VULKAN_ATIVO.
"""

    fun build(
        chatHistory: List<Message>,
        userPrompt: String,
        thinkingEnabled: Boolean,
        searchResults: String? = null,
        systemPrompt: String? = null,
        hasImage: Boolean = false
    ): String {
        val sb = StringBuilder()
        sb.appendLine(SYSTEM_BASE)
        if (!systemPrompt.isNullOrBlank() && systemPrompt != SYSTEM_BASE) {
            sb.appendLine("Sistema custom: $systemPrompt")
        }
        if (hasImage) sb.appendLine("[Imagem anexada — vision encoder slot B ativo via Vulkan]")
        if (!searchResults.isNullOrBlank()) {
            sb.appendLine(searchResults)
        }
        // Histórico: últimas 12 mensagens (para não estourar contexto)
        val recent = chatHistory.takeLast(12)
        for (m in recent) {
            when (m.role) {
                "user" -> sb.appendLine("Usuário: ${m.content}")
                "assistant" -> sb.appendLine("Assistente: ${m.content}")
                "system" -> sb.appendLine("Sistema: ${m.content}")
            }
        }
        var finalUser = userPrompt
        if (thinkingEnabled) {
            finalUser = ThinkingEngine.buildPromptWithThinking(userPrompt, ThinkingEngine.ThinkingConfig(true), history = "", hasSearchResults = !searchResults.isNullOrBlank())
            // prompt builder já inclui thinking instruction, mas mantemos histórico acima
            sb.appendLine(finalUser)
        } else {
            sb.appendLine("Usuário: $userPrompt")
            sb.appendLine("Assistente:")
        }
        return sb.toString()
    }

    fun buildSimple(userPrompt: String): String {
        return "$SYSTEM_BASE\nUsuário: $userPrompt\nAssistente:"
    }
}
