package com.vulcanmind.vulkanmind.inference

import android.util.Log

/**
 * Thinking Engine - implementa raciocínio passo-a-passo com <think> tags
 * Inspirado em DeepSeek-R1, QwQ, etc. Gera bloco thinking colapsável na UI.
 */
object ThinkingEngine {

    private const val TAG = "ThinkingEngine"

    data class ThinkingConfig(
        val enabled: Boolean = true,
        val budgetTokens: Int = 512, // max tokens de thinking
        val showInUi: Boolean = true,
        val style: String = "structured" // structured | freeform | cot
    )

    fun buildPromptWithThinking(userPrompt: String, config: ThinkingConfig, history: String = "", hasSearchResults: Boolean = false): String {
        if (!config.enabled) return buildStandardPrompt(userPrompt, history, hasSearchResults)
        val thinkingInstruction = """
            |Você DEVE raciocinar passo-a-passo antes de responder. Use o formato:
            |<think>
            |1. Entenda o pedido do usuário
            |2. Liste fatos relevantes (use pesquisa se disponível)
            |3. Planeje estrutura da resposta
            |4. Verifique coerência e possíveis erros
            |</think>
            |Depois do </think>, dê a resposta final direta, sem repetir o thinking.
            |Orçamento: até ${config.budgetTokens} tokens de thinking.
        """.trimMargin()
        return if (history.isNotBlank()) {
            "$thinkingInstruction\n\nHistórico:\n$history\n\nUsuário: $userPrompt\n\nAssistente:"
        } else {
            "$thinkingInstruction\n\nUsuário: $userPrompt\n\nAssistente:"
        }
    }

    fun buildStandardPrompt(userPrompt: String, history: String, hasSearchResults: Boolean): String {
        val searchNote = if (hasSearchResults) "\n[Pesquisa web disponível - use os resultados se relevante]\n" else ""
        return if (history.isNotBlank()) {
            "$history$searchNote\nUsuário: $userPrompt\nAssistente:"
        } else {
            "$searchNote Usuário: $userPrompt\nAssistente:"
        }
    }

    fun extractThinking(fullOutput: String): Pair<String?, String> {
        // Extrai <think>...</think> se existir
        val thinkRegex = Regex("<think>(.*?)</think>", RegexOption.DOT_MATCHES_ALL)
        val match = thinkRegex.find(fullOutput)
        return if (match != null) {
            val thinking = match.groupValues[1].trim()
            val answer = fullOutput.replace(match.value, "").trim()
            Log.i(TAG, "Thinking extracted len=${thinking.length}")
            Pair(thinking, answer)
        } else {
            // Fallback: se não tem tag mas thinkingEnabled, considera primeira parte como thinking se tiver marcadores
            Pair(null, fullOutput.trim())
        }
    }

    fun buildPromptWithSearch(userPrompt: String, searchResults: String, thinkingEnabled: Boolean): String {
        val base = if (thinkingEnabled) {
            buildPromptWithThinking(userPrompt, ThinkingConfig(enabled = true), hasSearchResults = searchResults.isNotBlank())
        } else {
            buildStandardPrompt(userPrompt, "", searchResults.isNotBlank())
        }
        return if (searchResults.isNotBlank()) {
            "Resultados de pesquisa:\n$searchResults\n\n$base"
        } else base
    }
}
