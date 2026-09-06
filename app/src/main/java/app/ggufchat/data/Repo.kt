package app.ggufchat.data

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow

/** Estado reativo do app + persistência. */
object Repo {
    private val _models = MutableStateFlow<List<ChatModel>>(emptyList())
    val models: StateFlow<List<ChatModel>> = _models.asStateFlow()

    private val _settings = MutableStateFlow(AppSettings())
    val settings: StateFlow<AppSettings> = _settings.asStateFlow()

    /** Chat em uso na tela (streaming ao vivo fica em [liveText]). */
    private val _chat = MutableStateFlow<Chat?>(null)
    val chat: StateFlow<Chat?> = _chat.asStateFlow()

    private val _chatsMeta = MutableStateFlow<List<Chat>>(emptyList())
    val chatsMeta: StateFlow<List<Chat>> = _chatsMeta.asStateFlow()

    /** texto do turno do assistente em andamento (por chat) */
    private val _liveText = MutableStateFlow<Map<String, LiveTurn>>(emptyMap())
    val liveText: StateFlow<Map<String, LiveTurn>> = _liveText.asStateFlow()

    /** mensagens curtas para snackbar/toast (qualquer thread) */
    private val _toast = MutableSharedFlow<String>(extraBufferCapacity = 32)
    val toast: SharedFlow<String> = _toast.asSharedFlow()

    fun toast(msg: String) {
        _toast.tryEmit(msg)
    }

    data class LiveTurn(
        val chatId: String,
        var text: String = "",
        var partial: Boolean = true,
        var stopped: String? = null,
        var tokens: Long = 0,
        var tps: Double = 0.0,
        var error: String? = null
    )

    fun boot() {
        _models.value = Store.loadModels()
        _settings.value = Store.loadSettings()
        _chatsMeta.value = Store.loadChatsMeta()
        if (_chat.value == null && _chatsMeta.value.isNotEmpty()) {
            _chat.value = _chatsMeta.value.first()
        }
    }

    fun refreshChatsMeta() {
        _chatsMeta.value = Store.loadChatsMeta()
    }

    fun modelById(id: String): ChatModel? = _models.value.firstOrNull { it.id == id }

    fun mmprojById(id: String): ChatModel? = _models.value.firstOrNull { it.id == id && it.isVisionProjector }

    fun openChat(id: String): Chat? {
        val c = Store.loadChat(id) ?: return null
        _chat.value = c
        return c
    }

    fun setChat(c: Chat) {
        _chat.value = c
    }

    fun updateChat(id: String, transform: (Chat) -> Chat) {
        val cur = _chat.value?.takeIf { it.id == id } ?: Store.loadChat(id) ?: return
        val next = transform(cur)
        if (_chat.value?.id == id) _chat.value = next
        Store.saveChat(next)
        refreshChatsMeta()
    }

    fun addModels(models: List<ChatModel>) {
        val existing = _models.value
        val merged = existing.filter { m -> models.none { it.id == m.id } } + models
        _models.value = merged
        Store.saveModels(merged)
    }

    fun removeModel(id: String) {
        _models.value = _models.value.filterNot { it.id == id }
        Store.saveModels(_models.value)
    }

    fun updateModel(m: ChatModel) {
        _models.value = _models.value.map { if (it.id == m.id) m else it }
        Store.saveModels(_models.value)
    }

    fun updateSettings(s: AppSettings) {
        _settings.value = s
        Store.saveSettings(s)
    }

    fun live(chatId: String): LiveTurn {
        val map = _liveText.value
        return map[chatId] ?: LiveTurn(chatId).also { _liveText.value = map + (chatId to it) }
    }

    fun updateLive(chatId: String, transform: (LiveTurn) -> Unit) {
        val map = _liveText.value.toMutableMap()
        val turn = map[chatId] ?: LiveTurn(chatId).also { map[chatId] = it }
        transform(turn)
        _liveText.value = map
    }

    fun clearLive(chatId: String) {
        _liveText.value = _liveText.value - chatId
    }

    /** Encontra o último índice de mensagens (contador). */
    fun nextMsgId(chat: Chat): Long = (chat.msgs.maxOfOrNull { it.id } ?: 0L) + 1
}
