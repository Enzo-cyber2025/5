package app.arenatech.localai.data

import android.content.Context
import android.content.SharedPreferences

/** Lightweight app preferences (SharedPreferences). */
class Prefs private constructor(context: Context) {

    private val sp: SharedPreferences =
        context.applicationContext.getSharedPreferences("localai_prefs", Context.MODE_PRIVATE)

    var thinkingEnabled: Boolean
        get() = sp.getBoolean("thinking", true)
        set(v) { sp.edit().putBoolean("thinking", v).apply() }

    var researchEnabled: Boolean
        get() = sp.getBoolean("research", false)
        set(v) { sp.edit().putBoolean("research", v).apply() }

    /** Keep generating while the screen is locked (foreground service). */
    var generateWithScreenLocked: Boolean
        get() = sp.getBoolean("background", true)
        set(v) { sp.edit().putBoolean("background", v).apply() }

    var predictTokens: Int
        get() = sp.getInt("predict", 512)
        set(v) { sp.edit().putInt("predict", v.coerceIn(128, 4096)).apply() }

    var persona: String
        get() = sp.getString("persona", DEFAULT_PERSONA) ?: DEFAULT_PERSONA
        set(v) { sp.edit().putString("persona", v).apply() }

    companion object {
        const val DEFAULT_PERSONA =
            "Você é um assistente local inteligente e direto. Responda em português do Brasil, " +
                "a menos que o usuário peça outro idioma. Seja claro, útil e conciso."

        @Volatile private var _instance: Prefs? = null
        fun init(context: Context): Prefs =
            _instance ?: synchronized(this) { Prefs(context.applicationContext).also { _instance = it } }
        val instance: Prefs get() = checkNotNull(_instance) { "Prefs not initialized" }
    }
}
