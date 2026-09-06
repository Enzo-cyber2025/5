package app.arenatech.localai.data

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/**
 * Single source of truth for chats & messages. Thread-safe and updated by both
 * the UI and the foreground [app.arenatech.localai.service.GenerationService] so
 * responses keep streaming even while the screen is locked.
 */
class ChatStore private constructor(private val context: Context) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val lock = Any()

    private val _chats = linkedMapOf<String, Chat>()
    private val _revision = MutableStateFlow(0L)
    val revision: StateFlow<Long> = _revision.asStateFlow()

    private var saveJob: Job? = null

    private val dir: File get() = File(context.filesDir, "chats")
    private fun file() = File(dir, "chats.json")

    init { loadFromDisk() }

    private fun loadFromDisk() {
        val f = file()
        if (f.exists()) {
            runCatching {
                val arr = JSONObject(f.readText()).getJSONArray("chats")
                for (i in 0 until arr.length()) {
                    val c = Chat.fromJson(arr.getJSONObject(i))
                    _chats[c.id] = c
                }
            }
        }
        if (_chats.isEmpty()) {
            val id = UUID.randomUUID().toString()
            _chats[id] = Chat(id = id, title = "Novo chat", modelSlotId = ModelSlots.DEFAULT_SLOT_ID)
        }
        bump()
    }

    fun list(): List<Chat> = synchronized(lock) { _chats.values.sortedByDescending { it.updatedAt() } }

    fun listMeta(): List<ChatMeta> = synchronized(lock) {
        _chats.values.sortedByDescending { it.updatedAt() }.map {
            ChatMeta(it.id, it.title, it.modelSlotId, it.messages.lastOrNull()?.text ?: "", it.messageCount())
        }
    }

    fun get(id: String): Chat? = synchronized(lock) { _chats[id] }

    /** Safe snapshot of a chat's messages for rendering. */
    fun snapshot(chatId: String): List<Msg> = synchronized(lock) {
        (_chats[chatId]?.messages?.toList() ?: emptyList())
    }

    fun firstOrNew(): Chat = synchronized(lock) {
        if (_chats.isEmpty()) {
            val id = UUID.randomUUID().toString()
            _chats[id] = Chat(id = id, title = "Novo chat", modelSlotId = ModelSlots.DEFAULT_SLOT_ID)
        }
        _chats.values.first()
    }

    fun createChat(title: String, modelSlotId: String = ModelSlots.DEFAULT_SLOT_ID): Chat = synchronized(lock) {
        val c = Chat(id = UUID.randomUUID().toString(), title = title.trim().ifEmpty { "Novo chat" }, modelSlotId = modelSlotId)
        _chats[c.id] = c
        bump(); saveSoon()
        c
    }

    fun deleteChat(id: String) = synchronized(lock) {
        _chats.remove(id)
        bump(); saveSoon()
    }

    fun rename(id: String, newTitle: String) = synchronized(lock) {
        _chats[id]?.let { it.title = newTitle.trim().ifEmpty { "Novo chat" } }
        bump(); saveSoon()
    }

    fun setModelSlot(id: String, slotId: String) = synchronized(lock) {
        _chats[id]?.let { it.modelSlotId = slotId }
        bump(); saveSoon()
    }

    fun addUserMessage(chatId: String, text: String, imagePath: String? = null): Msg = synchronized(lock) {
        val c = _chats[chatId] ?: error("chat $chatId not found")
        val m = Msg(id = UUID.randomUUID().toString(), role = Roles.USER, text = text, imagePath = imagePath)
        c.messages.add(m); bump(); saveSoon(); m
    }

    fun beginAssistant(chatId: String): AssistantHandle = synchronized(lock) {
        val c = _chats[chatId] ?: error("chat $chatId not found")
        val m = Msg(id = UUID.randomUUID().toString(), role = Roles.ASSISTANT)
        c.messages.add(m); bump(); saveSoon()
        AssistantHandle(c.id, m.id)
    }

    fun appendAssistantText(chatId: String, msgId: String, chunk: String) = synchronized(lock) {
        val c = _chats[chatId] ?: return
        val idx = c.messages.indexOfFirst { it.id == msgId }
        if (idx >= 0) {
            c.messages[idx] = c.messages[idx].copy(text = c.messages[idx].text + chunk)
            bump()
        }
    }

    fun appendThinking(chatId: String, msgId: String, chunk: String) = synchronized(lock) {
        val c = _chats[chatId] ?: return
        val idx = c.messages.indexOfFirst { it.id == msgId }
        if (idx >= 0) {
            c.messages[idx] = c.messages[idx].copy(thinking = c.messages[idx].thinking + chunk)
            bump()
        }
    }

    fun addSystem(chatId: String, text: String) = synchronized(lock) {
        val c = _chats[chatId] ?: return
        c.messages.add(Msg(id = UUID.randomUUID().toString(), role = Roles.SYSTEM, text = text))
        bump(); saveSoon()
    }

    private fun bump() { _revision.value = _revision.value + 1 }

    private fun saveSoon() {
        saveJob?.cancel()
        saveJob = scope.launch { delay(350); persist() }
    }

    fun persistNow() { scope.launch { persist() } }

    private fun persist() {
        synchronized(lock) {
            runCatching {
                dir.mkdirs()
                val arr = JSONArray()
                _chats.values.sortedByDescending { it.updatedAt() }.forEach { arr.put(it.toJson()) }
                val tmp = File(dir, "chats.json.tmp")
                tmp.writeText(JSONObject().put("chats", arr).toString())
                tmp.renameTo(file())
            }
        }
    }

    fun updatedAtOf(id: String): Long = synchronized(lock) { _chats[id]?.updatedAt() ?: 0L }

    data class ChatMeta(val id: String, val title: String, val modelSlotId: String, val preview: String, val count: Int)

    inner class AssistantHandle(val chatId: String, val msgId: String)

    companion object {
        @Volatile private var _instance: ChatStore? = null
        fun init(context: Context): ChatStore =
            _instance ?: synchronized(this) { ChatStore(context.applicationContext).also { _instance = it } }
        val instance: ChatStore get() = checkNotNull(_instance) { "ChatStore not initialized" }
    }
}

private fun Chat.updatedAt(): Long {
    var last = createdAt
    for (m in messages) if (m.ts > last) last = m.ts
    return last
}
