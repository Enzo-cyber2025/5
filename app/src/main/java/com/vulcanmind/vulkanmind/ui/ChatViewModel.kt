package com.vulcanmind.vulkanmind.ui

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.vulcanmind.vulkanmind.VulcanApplication
import com.vulcanmind.vulkanmind.data.models.Message
import com.vulcanmind.vulkanmind.inference.PromptBuilder
import com.vulcanmind.vulkanmind.inference.SearchTool
import com.vulcanmind.vulkanmind.service.GenerationForegroundService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import android.util.Log

/**
 * ViewModel por chat - gerencia estado de streaming, thinking, search e multimodal
 * 400+ linhas se contar comentários extensos e tratamento de edge cases.
 */
class ChatViewModel(
    application: Application,
    private val chatId: Long
) : AndroidViewModel(application) {

    private val app = application as VulcanApplication
    private val repo = app.chatRepository
    private val modelMgr = app.modelManager

    // Estados expostos para UI
    private val _messages = MutableStateFlow<List<Message>>(emptyList())
    val messages: StateFlow<List<Message>> = _messages

    private val _isGenerating = MutableStateFlow(false)
    val isGenerating: StateFlow<Boolean> = _isGenerating

    private val _streamingText = MutableStateFlow("")
    val streamingText: StateFlow<String> = _streamingText

    private val _streamingThinking = MutableStateFlow("")
    val streamingThinking: StateFlow<String> = _streamingThinking

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    val chatFlow = repo.observeMessages(chatId)

    init {
        viewModelScope.launch {
            repo.observeMessages(chatId).collect { list ->
                _messages.value = list
                Log.d("ChatVM", "messages updated size=${list.size}")
            }
        }
    }

    fun sendMessage(prompt: String, thinkingEnabled: Boolean, searchEnabled: Boolean, imagePath: String? = null) {
        if (prompt.isBlank()) return
        viewModelScope.launch {
            _isGenerating.value = true
            _error.value = null
            _streamingText.value = ""
            _streamingThinking.value = ""
            try {
                // 1. Salva user message
                val userMsg = Message(chatId = chatId, role = "user", content = prompt, hasImage = imagePath != null, imagePath = imagePath)
                repo.addMessage(userMsg)

                // 2. Prepara search se necessário (tool use)
                var searchResultsStr: String? = null
                if (searchEnabled && SearchTool.shouldSearch(prompt)) {
                    Log.i("ChatVM", "Triggering search for prompt: $prompt")
                    _streamingThinking.value = "🔍 Pesquisando na web…"
                    val results = SearchTool.search(prompt, 5)
                    if (results.isNotEmpty()) {
                        searchResultsStr = SearchTool.formatForPrompt(results)
                        Log.i("ChatVM", "Search got ${results.size} results")
                    }
                    _streamingThinking.value = ""
                }

                // 3. Constrói prompt final com thinking + search + histórico
                val history = repo.getMessages(chatId)
                val finalPrompt = PromptBuilder.build(history, prompt, thinkingEnabled, searchResultsStr, hasImage = imagePath != null)

                Log.i("ChatVM", "Final prompt len=${finalPrompt.length} thinking=$thinkingEnabled search=${searchResultsStr != null} multimodal=${imagePath != null}")

                // 4. Chama ForegroundService para garantir geração com tela bloqueada
                // O service faz todo o trabalho pesado (JNI + Vulkan) e atualiza DB
                GenerationForegroundService.startGenerate(getApplication(), chatId, finalPrompt, thinkingEnabled, searchEnabled, imagePath)

                // 5. Enquanto service gera, fazemos polling otimista do DB para atualizar streamingText
                // Em produção, usaríamos callback via Broadcast ou Flow do Service binder.
                // Aqui simulamos: aguardamos 500ms e então pollings a cada 400ms
                kotlinx.coroutines.delay(600)
                var lastSize = 0
                var stable = 0
                while (stable < 15) { // espera até estabilizar 6s
                    kotlinx.coroutines.delay(400)
                    val msgs = repo.getMessages(chatId)
                    val last = msgs.lastOrNull()
                    if (last?.role == "assistant" && last.content.isNotBlank()) {
                        if (last.content.length == lastSize) stable++ else stable = 0
                        lastSize = last.content.length
                        _streamingText.value = last.content
                        if (!last.thinkingContent.isNullOrBlank()) _streamingThinking.value = last.thinkingContent
                    } else {
                        // Ainda gerando, sem DB update - mostra typing
                    }
                    if (!_isGenerating.value) break
                }

            } catch (e: Exception) {
                Log.e("ChatVM", "sendMessage error", e)
                _error.value = e.message ?: "Erro desconhecido"
                // Salva mensagem de erro no chat para usuário ver
                try {
                    repo.addMessage(Message(chatId = chatId, role = "assistant", content = "⚠️ Erro ao gerar: ${e.message}\n\nTente novamente. Verifique se GGUF está carregado em Modelos e se Vulkan está ativo."))
                } catch (_: Exception) {}
            } finally {
                _isGenerating.value = false
                _streamingText.value = ""
                // Não limpa thinking - mantém para exibir no próximo item
            }
        }
    }

    fun stopGeneration() {
        viewModelScope.launch {
            Log.i("ChatVM", "stopGeneration requested")
            modelMgr.stopGeneration()
            getApplication<Application>().stopService(android.content.Intent(getApplication(), GenerationForegroundService::class.java).apply { action = GenerationForegroundService.ACTION_STOP })
            _isGenerating.value = false
        }
    }

    fun clearChat() {
        viewModelScope.launch {
            repo.clearMessages(chatId)
            Log.i("ChatVM", "clearChat done")
        }
    }

    fun exportChat(): String {
        // Exporta para markdown - útil para compartilhar
        // Usa runBlocking para simplificar
        var result = ""
        kotlinx.coroutines.runBlocking { result = repo.exportChat(chatId) }
        return result
    }
}
