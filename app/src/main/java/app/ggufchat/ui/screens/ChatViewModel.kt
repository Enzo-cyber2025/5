package app.ggufchat.ui.screens

import android.content.Context
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import app.ggufchat.core.CoreEngine
import app.ggufchat.core.WebSearch
import app.ggufchat.data.Chat
import app.ggufchat.data.Repo
import app.ggufchat.data.Store
import kotlinx.coroutines.launch

/** Estado da tela de conversa (sobrevive a rotações; o trabalho pesado vive no CoreEngine). */
class ChatViewModel : ViewModel() {

    var input by mutableStateOf("")
        private set
    var attachedImages by mutableStateOf<List<String>>(emptyList())
        private set
    var webSearchEnabled by mutableStateOf(false)
        private set
    var searchingWeb by mutableStateOf(false)
        private set
    var sending by mutableStateOf(false)
        private set
    var thinkingCollapsedIds by mutableStateOf<Set<Long>>(emptySet())
        private set
    var showLiveThinking by mutableStateOf(false)
        private set

    fun setInput(v: String) { input = v }
    fun setWebSearch(v: Boolean) { webSearchEnabled = v }
    fun toggleThinking(msgId: Long) {
        thinkingCollapsedIds = if (msgId in thinkingCollapsedIds)
            thinkingCollapsedIds - msgId else thinkingCollapsedIds + msgId
    }
    fun setLiveThinking(v: Boolean) { showLiveThinking = v }

    fun addImage(path: String) {
        if (attachedImages.size >= 6) {
            Repo.toast("Máximo de 6 imagens por mensagem")
            return
        }
        attachedImages = attachedImages + path
    }

    fun removeImage(path: String) {
        attachedImages = attachedImages - path
    }

    fun clearDraft() {
        input = ""
        attachedImages = emptyList()
        webSearchEnabled = false
    }

    /** Anexa imagens escolhidas na UI (já copiadas para o armazenamento interno). */
    fun attach(context: Context, chatId: String, uris: List<Uri>) {
        CoreEngine.scope.launch {
            val added = ArrayList<String>()
            for (uri in uris) {
                if (attachedImages.size + added.size >= 6) break
                val path = try {
                    context.contentResolver.openInputStream(uri)?.use { ins ->
                        Store.storeImage(chatId, ins)
                    }
                } catch (e: Exception) {
                    null
                }
                if (path != null) added.add(path)
            }
            if (added.isNotEmpty()) {
                attachedImages = attachedImages + added
                Repo.toast("${added.size} imagem(ns) anexada(s)")
            } else {
                Repo.toast("Não foi possível ler a imagem")
            }
        }
    }

    private fun chatOrNull(chatId: String): Chat? =
        Repo.chat.value?.takeIf { it.id == chatId } ?: Store.loadChat(chatId)

    fun send(chatId: String) {
        val chat = chatOrNull(chatId) ?: run { Repo.toast("Chat indisponível"); return }
        val text = input.trim()
        val images = attachedImages
        if (text.isEmpty() && images.isEmpty()) return
        if (CoreEngine.activeGen.value != null) {
            Repo.toast("Aguarde a resposta atual terminar")
            return
        }
        sending = true
        if (webSearchEnabled && text.isNotEmpty() && images.isEmpty()) {
            searchingWeb = true
            CoreEngine.scope.launch {
                val results = WebSearch.search(text, max = 5)
                searchingWeb = false
                val finalPrompt = WebSearch.buildPrompt(text, results)
                val r = CoreEngine.generate(chatId, finalPrompt, emptyList())
                sending = false
                if (r.ok) { clearDraft(); if (r.reason == "ctx_full") Repo.toast("Contexto cheio — reduza o histórico") }
                else Repo.toast(r.error ?: "Falha na geração")
            }
        } else {
            val finalText = text
            CoreEngine.scope.launch {
                val r = CoreEngine.generate(chatId, finalText, images)
                sending = false
                if (r.ok) { clearDraft(); if (r.reason == "ctx_full") Repo.toast("Contexto cheio — reduza o histórico") }
                else Repo.toast(r.error ?: "Falha na geração")
            }
        }
    }

    fun stop(chatId: String) {
        CoreEngine.stop(chatId)
    }

    /** Remove o último turno e regenera. */
    fun retry(chatId: String) {
        val chat = chatOrNull(chatId) ?: return
        val msgs = chat.msgs
        if (msgs.isEmpty()) return
        var dropFrom = msgs.size - 1
        var lastUser: app.ggufchat.data.ChatMsg? = null
        var lastUserIndex = -1
        for (i in msgs.indices.reversed()) {
            if (msgs[i].role == "user") { lastUser = msgs[i]; lastUserIndex = i; break }
        }
        if (lastUserIndex < 0) return
        dropFrom = lastUserIndex
        CoreEngine.scope.launch {
            Store.saveChat(chat.copy(msgs = msgs.subList(0, dropFrom), updatedAt = System.currentTimeMillis()))
            Repo.setChat(Store.loadChat(chatId))
            Repo.refreshChatsMeta()
            CoreEngine.resetChat(chatId)
            lastUser?.let { CoreEngine.generate(chatId, it.content, it.images) }
        }
    }
}
