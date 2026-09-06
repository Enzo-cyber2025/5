package app.arenatech.localai.data

import org.json.JSONArray
import org.json.JSONObject

/** Role of a chat message. */
object Roles {
    const val USER = "user"
    const val ASSISTANT = "assistant"
    const val THINKING = "thinking"   // tool / reasoning trace shown collapsed
    const val SYSTEM = "system"       // import/status/error notices
}

data class Msg(
    val id: String,
    val role: String,
    val text: String = "",
    val thinking: String = "",
    val imagePath: String? = null,
    val ts: Long = System.currentTimeMillis(),
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("role", role)
        put("text", text)
        put("thinking", thinking)
        if (imagePath != null) put("imagePath", imagePath)
        put("ts", ts)
    }

    companion object {
        fun fromJson(o: JSONObject): Msg = Msg(
            id = o.getString("id"),
            role = o.getString("role"),
            text = o.optString("text"),
            thinking = o.optString("thinking"),
            imagePath = if (o.has("imagePath")) o.getString("imagePath") else null,
            ts = o.optLong("ts", System.currentTimeMillis()),
        )
    }
}

data class Chat(
    val id: String,
    var title: String,
    var modelSlotId: String,     // which imported GGUF model this chat uses
    val createdAt: Long = System.currentTimeMillis(),
    val messages: MutableList<Msg> = mutableListOf(),
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("title", title)
        put("modelSlotId", modelSlotId)
        put("createdAt", createdAt)
        put("messages", JSONArray().also { arr -> messages.forEach { arr.put(it.toJson()) } })
    }

    fun messageCount(): Int = messages.count { it.role == Roles.USER || it.role == Roles.ASSISTANT }

    companion object {
        fun fromJson(o: JSONObject): Chat = Chat(
            id = o.getString("id"),
            title = o.getString("title"),
            modelSlotId = o.optString("modelSlotId", ModelSlots.DEFAULT_SLOT_ID),
            createdAt = o.optLong("createdAt", System.currentTimeMillis()),
            messages = (o.optJSONArray("messages")?.let { arr ->
                (0 until arr.length()).mapNotNull { i -> Msg.fromJson(arr.getJSONObject(i)) }
            } ?: emptyList()).toMutableList(),
        )
    }
}
