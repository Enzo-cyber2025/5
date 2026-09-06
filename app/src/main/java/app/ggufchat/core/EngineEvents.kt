package app.ggufchat.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Evento nativo já decodificado. */
sealed class NativeEvent {
    abstract val token: Long
    val json: String = ""

    data class Token(override val token: Long, val text: String, val json: String = "") : NativeEvent()
    data class Done(
        override val token: Long,
        val text: String,
        val reason: String,
        val n: Long,
        val tps: Double,
        val json: String = ""
    ) : NativeEvent()
    data class Error(
        override val token: Long,
        val code: String,
        val message: String,
        val json: String = ""
    ) : NativeEvent()
    data class Note(override val token: Long, val code: String, val json: String = "") : NativeEvent()
    data class Progress(override val token: Long, val p: Float, val json: String = "") : NativeEvent()
    data class ModelLoaded(override val token: Long, val model: Long, val json: String = "") : NativeEvent()
    data class SessionReady(override val token: Long, val session: Long, val json: String = "") : NativeEvent()
    data class Unknown(override val token: Long, val json: String) : NativeEvent()

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun parse(raw: String): NativeEvent {
            val root = runCatching { json.parseToJsonElement(raw).jsonObject }
                .getOrNull()
                ?: return Unknown(0, raw)
            fun str(k: String): String =
                (root[k] as? JsonElement)?.let { runCatching { it.jsonPrimitive.content }.getOrDefault("") } ?: ""
            fun lng(k: String): Long =
                (root[k] as? JsonElement)?.let { runCatching { it.jsonPrimitive.content.toLong() }.getOrDefault(0L) } ?: 0L
            fun dbl(k: String): Double =
                (root[k] as? JsonElement)?.let { runCatching { it.jsonPrimitive.content.toDouble() }.getOrDefault(0.0) } ?: 0.0
            val token = lng("token")
            return when (str("e")) {
                "tok" -> Token(token, str("t"), raw)
                "done" -> Done(token, str("text"), str("reason"), lng("n"), dbl("tps"), raw)
                "error" -> Error(token, str("code"), str("message"), raw)
                "note" -> Note(token, str("code"), raw)
                "model_progress" -> Progress(token, runCatching { str("p").toFloat() }.getOrDefault(0f), raw)
                "model_loaded" -> ModelLoaded(token, lng("model"), raw)
                "session_ready" -> SessionReady(token, lng("session"), raw)
                else -> Unknown(token, raw)
            }
        }
    }
}
