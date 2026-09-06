package app.arenatech.localai.engine

import android.content.Context
import app.arenatech.localai.data.ModelSlot
import com.arm.aichat.AiChat
import com.arm.aichat.InferenceEngine
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.runBlocking

/**
 * Process-wide façade over the native llama.cpp inference engine (lib module).
 *
 * The underlying library exposes exactly ONE model+context that lives inside a
 * single-threaded dispatcher, so we centralise every load/unload/generate call
 * here and share it between the Activity and the foreground [GenerationService]
 * (which keeps producing tokens while the screen is locked).
 */
object Engine {

    private var engine: InferenceEngine? = null
    private var contextRef: Context? = null

    /** Slot id of the model currently resident in the native context (null = none). */
    @Volatile var loadedSlotId: String? = null
        private set

    /** Chat whose conversation is currently resident in the native KV-cache. */
    @Volatile var loadedChatId: String? = null
        private set

    val nativeState: StateFlow<InferenceEngine.State>?
        get() = engine?.state

    @Synchronized
    fun ensure(context: Context) {
        if (engine == null) {
            contextRef = context.applicationContext
            engine = AiChat.getInferenceEngine(context.applicationContext)
        }
    }

    fun isNativeInitialized(): Boolean =
        engine?.state?.value is InferenceEngine.State.Initialized

    /** Waits until the native library has been loaded and its backends initialised. */
    suspend fun awaitNativeInitialized(timeoutMs: Long = 60_000) {
        if (engine == null) throw RuntimeException("Motor de inferência não foi iniciado. Reinicie o app.")
        var waited = 0L
        while (!isNativeInitialized() && waited < timeoutMs) {
            val s = engine?.state?.value
            if (s is InferenceEngine.State.Error) throw s.exception
            delay(120)
            waited += 120
        }
        if (!isNativeInitialized()) {
            throw RuntimeException("Falha ao iniciar o motor de inferência (nativo).")
        }
    }

    /** Loads [slot] into the engine and primes it with [systemPrompt]. Returns when ready. */
    suspend fun loadModel(slot: ModelSlot, systemPrompt: String, chatId: String) {
        val e = checkNotNull(engine) { "Engine not initialised" }
        e.loadModel(slot.modelPath)
        // setSystemPrompt must be called immediately after loading.
        if (systemPrompt.isNotBlank()) e.setSystemPrompt(systemPrompt)
        loadedSlotId = slot.id
        loadedChatId = chatId
    }

    suspend fun isSlotLoaded(slotId: String): Boolean = loadedSlotId == slotId

    fun isSlotLoadedSync(slotId: String): Boolean = loadedSlotId == slotId

    fun generate(text: String, predictLength: Int = 1024): Flow<String> =
        checkNotNull(engine) { "Engine not initialised" }.sendUserPrompt(text, predictLength)

    /** Stops a running generation (native loop is cancelled at a token boundary). */
    fun stop() {
        // Public lib API exposes no dedicated "halt keep model", so we unload and
        // mark nothing loaded; caller can simply not re-load to stop generation.
        unloadSync()
    }

    /** Unloads any resident model synchronously (used when clearing a slot/chat). */
    fun unloadSync() {
        val e = engine ?: return
        try {
            val st = e.state.value
            if (st is InferenceEngine.State.ModelReady ||
                st is InferenceEngine.State.Error
            ) {
                runCatching { e.cleanUp() }
            }
        } catch (_: Exception) {
        }
        loadedSlotId = null
        loadedChatId = null
    }

    fun shutdown() {
        val e = engine ?: return
        runCatching { e.destroy() }
        engine = null
        loadedSlotId = null
        loadedChatId = null
    }
}
