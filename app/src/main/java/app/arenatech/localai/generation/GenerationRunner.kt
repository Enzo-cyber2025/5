package app.arenatech.localai.generation

import app.arenatech.localai.data.ChatStore
import app.arenatech.localai.data.ModelStore
import app.arenatech.localai.data.Prefs
import app.arenatech.localai.data.Roles
import app.arenatech.localai.engine.Engine
import app.arenatech.localai.tools.WebSearch
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch

/**
 * Orchestrates a full generation turn: ensures the right GGUF model is resident,
 * optionally runs the web "pesquisa" tool and the "thinking" pass, then streams
 * the final answer into the [ChatStore]. Runs on a process-wide scope so it can
 * continue while the screen is locked (driven by the foreground service).
 */
object GenerationRunner {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @Volatile private var job: Job? = null

    enum class Phase { IDLE, LOADING, GENERATING, ERROR }

    data class Status(val phase: Phase, val chatId: String? = null, val message: String = "")

    private val _status = MutableStateFlow(Status(Phase.IDLE))
    val status: StateFlow<Status> = _status.asStateFlow()

    val isRunning: Boolean get() = _status.value.phase == Phase.LOADING || _status.value.phase == Phase.GENERATING

    /** Kicks off a turn for the chat's most recent user message. */
    fun start(chatId: String, research: Boolean, thinking: Boolean) {
        if (job?.isActive == true) return
        job = scope.launch {
            try {
                run(chatId, research, thinking)
            } catch (ce: CancellationException) {
                _status.value = Status(Phase.IDLE, chatId)
                throw ce
            } catch (t: Throwable) {
                _status.value = Status(Phase.ERROR, chatId, t.message ?: t.javaClass.simpleName)
                ChatStore.instance.addSystem(chatId, "❌ ${t.message ?: t.javaClass.simpleName}")
            }
        }
    }

    suspend fun stopAndJoin() {
        job?.cancelAndJoin()
        _status.value = Status(Phase.IDLE)
    }

    private suspend fun run(chatId: String, research: Boolean, thinking: Boolean) {
        val store = ChatStore.instance
        val chat = store.get(chatId) ?: return
        val lastUser = store.snapshot(chatId).lastOrNull { it.role == Roles.USER }
            ?: return

        val slot = ModelStore.instance.get(chat.modelSlotId)
        if (slot.isEmpty) {
            store.addSystem(chatId, "⚠️ Este chat não tem um modelo GGUF atribuído. Importe um modelo primeiro.")
            _status.value = Status(Phase.ERROR, chatId, "Sem modelo GGUF atribuído")
            return
        }

        _status.value = Status(Phase.LOADING, chatId, "Carregando ${slot.sourceName}…")

        // Make sure the native engine is up and the correct model is resident.
        Engine.awaitNativeInitialized()
        // A resident model owns a live KV-cache conversation for a single chat, so
        // switching slot or chat requires a reload to reset that context.
        val needLoad = !Engine.isSlotLoadedSync(slot.id) || Engine.loadedChatId != chatId
        if (needLoad) {
            Engine.unloadSync()
            Engine.loadModel(slot, Prefs.instance.persona, chatId)
        }

        _status.value = Status(Phase.GENERATING, chatId, "Gerando…")

        var userText = lastUser.text
        // --- "pesquisa" tool ------------------------------------------------
        if (research && userText.isNotBlank()) {
            store.addSystem(chatId, "🔎 Pesquisando: \"${userText.take(120)}\"…")
            val results = WebSearch.search(userText)
            if (results.isNotBlank() && !results.startsWith("Nenhum") && !results.startsWith("Erro") && !results.startsWith("Sem resultado")) {
                store.addSystem(chatId, results.take(900))
            }
            userText = buildResearchPrompt(userText, results)
        }

        val handle = store.beginAssistant(chatId)

        // --- "thinking" pass (chain-of-thought) ------------------------------
        if (thinking) {
            store.appendThinking(chatId, handle.msgId, "")
            collectTokens(
                Engine.generate(buildThinkingPrompt(userText)),
                onChunk = { store.appendThinking(chatId, handle.msgId, it) }
            )
            val acc = store.snapshot(chatId).lastOrNull { it.id == handle.msgId }?.thinking.orEmpty()
            store.appendThinking(chatId, handle.msgId, "\n\n[Resposta final abaixo]\n")
            // Keep reasoning short marker.
            if (acc.isBlank()) store.appendThinking(chatId, handle.msgId, "(sem raciocínio explícito)")
        }

        // --- final answer ----------------------------------------------------
        val finalPrompt = if (thinking) {
            "Com base no raciocínio acima, responda agora de forma final, clara e direta."
        } else userText

        collectTokens(
            Engine.generate(finalPrompt, Prefs.instance.predictTokens),
            onChunk = { store.appendAssistantText(chatId, handle.msgId, it) }
        )

        _status.value = Status(Phase.IDLE, chatId)
    }

    private suspend fun collectTokens(flow: kotlinx.coroutines.flow.Flow<String>, onChunk: (String) -> Unit) {
        flow
            .catch { e -> /* generation hiccups surfaced via empty output */ }
            .collect { token -> if (token.isNotEmpty()) onChunk(token) }
    }

    private fun buildResearchPrompt(question: String, results: String): String =
        buildString {
            append("RESULTADOS DA PESQUISA (use estes dados, cite quando útil):\n")
            append(results.take(1200))
            append("\n\nPERGUNTA DO USUÁRIO:\n")
            append(question)
        }

    private fun buildThinkingPrompt(prompt: String): String =
        "Raciocine passo a passo sobre a seguinte tarefa. Seja metódico. Tarefa:\n$prompt"
}
