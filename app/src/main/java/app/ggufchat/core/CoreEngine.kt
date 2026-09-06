package app.ggufchat.core

import app.ggufchat.data.Chat
import app.ggufchat.data.ChatModel
import app.ggufchat.data.ChatMsg
import app.ggufchat.data.DeviceInfo
import app.ggufchat.data.MsgMeta
import app.ggufchat.data.ProbeInfo
import app.ggufchat.data.Repo
import app.ggufchat.data.Store
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.withContext
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.shareIn
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

/**
 * Orquestra o motor nativo: modelos, sessões (KV cache), warm-up, geração,
 * streaming e persistência. Também acorda o [app.ggufchat.service.GenService]
 * quando a geração precisa continuar com a tela bloqueada.
 */
object CoreEngine : EngineListener {

    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val json = Json { ignoreUnknownKeys = true }

    // ---------- estado ----------
    private val _device = MutableStateFlow<DeviceInfo?>(null)
    val device: StateFlow<DeviceInfo?> = _device.asStateFlow()

    private val _nativeModelHandles = MutableStateFlow<Map<String, Long>>(emptyMap()) // modelId -> handle
    val nativeModelHandles: StateFlow<Map<String, Long>> = _nativeModelHandles.asStateFlow()

    private val _loadingModel = MutableStateFlow<Pair<String, Float>?>(null) // (modelId, progress)
    val loadingModel: StateFlow<Pair<String, Float>?> = _loadingModel.asStateFlow()

    private val _activeChat = MutableStateFlow<String?>(null) // chat com geração ativa
    val activeChat: StateFlow<String?> = _activeChat.asStateFlow()

    data class ActiveGen(val chatId: String, val modelName: String, val token: Long, val startedAt: Long)
    private val _activeGen = MutableStateFlow<ActiveGen?>(null)
    val activeGen: StateFlow<ActiveGen?> = _activeGen.asStateFlow()

    // eventos auxiliares (notas/erros/progresso) p/ UI e serviço
    private val _aux = Channel<NativeEvent>(Channel.UNLIMITED)
    private val auxFlow = _aux.receiveAsFlow().shareIn(
        scope, kotlinx.coroutines.flow.SharingStarted.Eagerly,
        replay = 0, extraBufferCapacity = 8192,
        onBufferOverflow = kotlinx.coroutines.channels.BufferOverflow.DROP_OLDEST
    )
    val auxEvents: SharedFlow<NativeEvent> = auxFlow

    private class Task(val kind: String, val chatId: String?) {
        val channel = Channel<NativeEvent>(Channel.UNLIMITED)
        fun close() { channel.close() }
    }

    private val tasks = ConcurrentHashMap<Long, Task>()
    private val reqSeq = AtomicLong(1)

    // sessões nativas vivas: chatId -> (handle, modelId)
    private data class SessionRef(val handle: Long, val modelId: String)
    private val sessions = ConcurrentHashMap<String, SessionRef>()
    private val warmed = ConcurrentHashMap<String, Boolean>()

    private var initDone = false

    // listener registrado no bridge
    override fun onEvent(raw: String) {
        val ev = NativeEvent.parse(raw)
        tasks[ev.token]?.channel?.trySend(ev)
        _aux.trySend(ev)
    }

    suspend fun ensureInit(): DeviceInfo {
        if (initDone) {
            return _device.value ?: DeviceInfo(ok = false, error = "init pendente")
        }
        val raw = NativeBridge.nativeInit()
        val info = runCatching {
            json.decodeFromString<DeviceInfo>(raw)
        }.getOrDefault(DeviceInfo(ok = false, error = raw.take(200)))
        NativeBridge.listener = this
        _device.value = info
        initDone = true
        return info
    }

    /** Sonda um arquivo GGUF (síncrono, leve). */
    suspend fun probe(path: String): ProbeInfo {
        val raw = NativeBridge.nativeProbeModel(path)
        return runCatching { json.decodeFromString<ProbeInfo>(raw) }
            .getOrDefault(ProbeInfo(ok = false, error = "probe falhou: ${raw.take(120)}"))
    }

    private suspend fun nextTask(kind: String, chatId: String? = null): Pair<Long, Task> {
        val token = reqSeq.getAndIncrement()
        val task = Task(kind, chatId)
        tasks[token] = task
        return token to task
    }

    private fun closeTask(token: Long) {
        tasks.remove(token)?.close()
    }

    // ------------------------------------------------------------------
    // Modelos
    // ------------------------------------------------------------------

    private fun modelLoadLayers(m: ChatModel, totalGpu: Long, fileSize: Long): Int {
        return when (m.offload) {
            "cpu" -> 0
            "full" -> -1
            else -> { // auto
                if (fileSize <= 0 || totalGpu <= 0) -1
                else {
                    // ~1.2x no pico de VRAM por causa de KV/ativações; se couber, manda tudo
                    if (fileSize * 12L / 10L < totalGpu) -1 else 0
                }
            }
        }
    }

    /** Carrega o modelo no motor nativo (uma única cópia por modelId). */
    suspend fun loadModel(m: ChatModel, onProgress: (Float) -> Unit = {}): Long =
        withContext(Dispatchers.Default) {
            loadModelBlocking(m, onProgress)
        }

    private suspend fun loadModelBlocking(m: ChatModel, onProgress: (Float) -> Unit): Long {
        _nativeModelHandles.value[m.id]?.let { return it }
        _loadingModel.value = m.id to 0f
        try {
            val (token, task) = nextTask("load")
            val gpu = m.useGpu && (m.offload != "cpu")
            val layers = modelLoadLayers(m, _device.value?.gpuTotal ?: 0, m.size)
            val cfg = buildString {
                append("{\"token\":").append(token)
                append(",\"path\":").append(json.encodeToString(m.file))
                append(",\"gpu\":").append(gpu)
                append(",\"layers\":").append(layers)
                append(",\"threads\":").append(m.threads)
                append("}")
            }
            NativeBridge.nativeLoadModel(cfg)
            var handle: Long? = null
            for (ev in task.channel) {
                when (ev) {
                    is NativeEvent.Progress -> onProgress(ev.p)
                    is NativeEvent.ModelLoaded -> handle = ev.model
                    is NativeEvent.Error -> {
                        throw RuntimeException(ev.message)
                    }
                    else -> {}
                }
            }
            val h = handle ?: throw RuntimeException("Falha ao carregar o modelo")
            _nativeModelHandles.value = _nativeModelHandles.value + (m.id to h)
            return h
        } finally {
            _loadingModel.value = null
        }
    }

    private suspend fun ensureModelLoaded(m: ChatModel): Long =
        loadModelBlocking(m) { _loadingModel.value = m.id to it }

    /** Descarrega modelos de texto que não sejam o informado (economia de RAM). */
    suspend fun unloadOtherModels(keepModelId: String) {
        for ((id, handle) in _nativeModelHandles.value) {
            if (id != keepModelId && sessions.values.none { it.modelId == id }) {
                NativeBridge.nativeUnloadModel(handle)
                _nativeModelHandles.value = _nativeModelHandles.value - id
            }
        }
    }

    // ------------------------------------------------------------------
    // Sessões
    // ------------------------------------------------------------------

    private suspend fun destroySession(chatId: String) {
        sessions.remove(chatId)?.let { ref ->
            warmed.remove(chatId)
            NativeBridge.nativeDestroySession(ref.handle)
        }
    }

    /**
     * Garante uma sessão nativa aquecida com o histórico completo do chat.
     * Só pode haver UMA sessão ativa por vez (memória de GPU limitada).
     */
    suspend fun ensureSession(chat: Chat): Long = withContext(Dispatchers.Default) {
        val existing = sessions[chat.id]
        if (existing != null && existing.modelId == chat.modelId) {
            if (warmed[chat.id] == true) return@withContext existing.handle
            // sessão criada mas ainda não aquecida
            runCatching { warmHistory(chat) }.onFailure {
                destroySession(chat.id)
                throw RuntimeException("Falha ao preparar o histórico: ${it.message}")
            }
            warmed[chat.id] = true
            return@withContext sessions[chat.id]!!.handle
        }

        // evita manter várias sessões pesadas ao mesmo tempo
        for (other in sessions.keys.toList()) {
            if (other != chat.id && _activeChat.value != other) destroySession(other)
        }
        // descarrega outros modelos de texto
        unloadOtherModels(chat.modelId)

        val model = Repo.modelById(chat.modelId)
            ?: throw RuntimeException("Modelo '${chat.modelId}' não encontrado. Importe um GGUF.")
        val mmproj = chat.mmprojId.ifBlank { null }?.let { Repo.mmprojById(it) }

        val handle = ensureModelLoaded(model)

        val effectiveSystem = chat.systemPrompt.ifBlank { model.systemPrompt }
        val (token, task) = nextTask("session")
        val cfg = buildString {
            append("{\"token\":").append(token)
            append(",\"model\":").append(handle)
            mmproj?.let {
                append(",\"mmproj\":").append(json.encodeToString(it.file))
            }
            append(",\"nCtx\":").append(chat.nCtx)
            append(",\"nBatch\":512")
            append(",\"threads\":").append(model.threads)
            append(",\"flashAttn\":").append(chat.flashAttn)
            append(",\"template\":").append(json.encodeToString(model.templateOverride))
            append(",\"system\":").append(json.encodeToString(effectiveSystem))
            append("}")
        }
        NativeBridge.nativeCreateSession(cfg)
        var sess: Long? = null
        for (ev in task.channel) {
            when (ev) {
                is NativeEvent.SessionReady -> sess = ev.session
                is NativeEvent.Error -> throw RuntimeException(ev.message)
                else -> {}
            }
        }
        val sh = sess ?: throw RuntimeException("Falha ao criar a sessão")
        sessions[chat.id] = SessionRef(sh, chat.modelId)
        warmed[chat.id] = false

        // warm-up: repete o histórico (assim o KV cache fica pronto)
        try {
            warmHistory(chat)
        } catch (e: Exception) {
            destroySession(chat.id)
            throw RuntimeException("Falha ao preparar o histórico: ${e.message}")
        }
        warmed[chat.id] = true
        sh
    }

    /** Re-executa o prompt de cada mensagem antiga (sem gerar). */
    private suspend fun warmHistory(chat: Chat) {
        val ref = sessions[chat.id] ?: return
        for (msg in chat.msgs) {
            when (msg.role) {
                "user" -> {
                    val (token, task) = nextTask("warm", chat.id)
                    val body = warmReq(token, msg, maxTiny = true)
                    NativeBridge.nativeChatRequest(ref.handle, body)
                    for (ev in task.channel) {
                        if (ev is NativeEvent.Error) throw RuntimeException(ev.message)
                    }
                }
                "assistant" -> {
                    val (token, task) = nextTask("warm", chat.id)
                    val body = buildString {
                        append("{\"token\":").append(token)
                        append(",\"assistant\":true,\"maxTokens\":0")
                        append(",\"content\":").append(json.encodeToString(msg.content))
                        append("}")
                    }
                    NativeBridge.nativeChatRequest(ref.handle, body)
                    for (ev in task.channel) {
                        if (ev is NativeEvent.Error) throw RuntimeException(ev.message)
                    }
                }
            }
        }
    }

    private fun warmReq(token: Long, msg: ChatMsg, maxTiny: Boolean): String = buildString {
        append("{\"token\":").append(token)
        append(",\"warm\":true,\"maxTokens\":0")
        append(",\"content\":").append(json.encodeToString(msg.content))
        if (msg.images.isNotEmpty()) {
            append(",\"images\":[")
            append(msg.images.joinToString(",") { json.encodeToString(it) })
            append("]")
        }
        append("}")
    }

    // ------------------------------------------------------------------
    // Geração
    // ------------------------------------------------------------------

    data class GenResult(
        val text: String,
        val reason: String,
        val tokens: Long,
        val tps: Double,
        val ok: Boolean,
        val error: String? = null
    )

    /**
     * Envia uma mensagem e gera a resposta (streaming). Persiste a conversa.
     * Funciona com a UI destruída — o serviço em primeiro plano mantém o
     * processo acordado (tela bloqueada).
     */
    suspend fun generate(
        chatId: String,
        text: String,
        images: List<String> = emptyList(),
        maxTokens: Int = 0
    ): GenResult = withContext(Dispatchers.Default) {
        generateBlocking(chatId, text, images, maxTokens)
    }

    private suspend fun generateBlocking(
        chatId: String,
        text: String,
        images: List<String>,
        maxTokens: Int
    ): GenResult {
        val chat0 = Repo.chat.value?.takeIf { it.id == chatId } ?: Store.loadChat(chatId)
            ?: return GenResult("", "error", 0, 0.0, false, "Chat não encontrado")
        if (chat0.modelId.isBlank()) {
            return GenResult("", "error", 0, 0.0, false, "Selecione um modelo para este chat")
        }
        val model = Repo.modelById(chat0.modelId)
            ?: return GenResult("", "error", 0, 0.0, false, "Modelo não encontrado. Importe um GGUF.")
        if (chat0.mmprojId.isNotBlank() && Repo.mmprojById(chat0.mmprojId) == null) {
            return GenResult("", "error", 0, 0.0, false, "Projetor de visão não encontrado")
        }
        if (images.isNotEmpty() && chat0.mmprojId.isBlank()) {
            return GenResult("", "error", 0, 0.0, false,
                "Este chat não tem um projetor de visão. Associe um mmproj ao modelo nas configurações do chat.")
        }
        if (_activeGen.value != null) {
            return GenResult("", "error", 0, 0.0, false, "Já existe uma geração em andamento")
        }

        _activeChat.value = chatId
        _activeGen.value = ActiveGen(chatId, model.name, 0, System.currentTimeMillis())

        val live = Repo.live(chatId)
        try {
            // serviço em primeiro plano (tela bloqueada)
            app.ggufchat.service.GenServiceController.startIfNeeded(chatId, model.name)

            // 1) sessão + warm-up com o histórico SEM a mensagem nova
            ensureSession(chat0)

            // 2) persiste a mensagem do usuário
            var chat = Store.loadChat(chatId) ?: chat0
            val userMsg = ChatMsg(
                id = Repo.nextMsgId(chat),
                role = "user",
                content = text,
                images = images,
                meta = MsgMeta(modelId = chat.modelId, mmprojId = chat.mmprojId.ifBlank { null }, createdAt = System.currentTimeMillis())
            )
            val autoTitle = (chat.title.isBlank() || chat.title == "Novo chat")
            chat = chat.copy(
                msgs = chat.msgs + userMsg,
                title = if (autoTitle && text.isNotBlank())
                    text.trim().replace(Regex("\\s+"), " ").take(48).let { if (text.trim().length > 48) "$it…" else it }
                else chat.title,
                updatedAt = System.currentTimeMillis()
            )
            Store.saveChat(chat)
            Repo.setChat(chat)
            Repo.refreshChatsMeta()

            val sess = sessions[chatId]?.handle ?: error("sessão indisponível")
            val tokenLimit = if (maxTokens > 0) maxTokens else chat.maxTokens
            val limit = if (tokenLimit > 0) tokenLimit else 1024

            val (token, task) = nextTask("gen", chatId)
            _activeGen.value = _activeGen.value?.copy(token = token)

            val body = buildString {
                append("{\"token\":").append(token)
                append(",\"maxTokens\":").append(limit)
                append(",\"content\":").append(json.encodeToString(text))
                if (images.isNotEmpty()) {
                    append(",\"images\":[")
                    append(images.joinToString(",") { json.encodeToString(it) })
                    append("]")
                }
                append(",\"sampling\":{")
                append("\"temp\":").append(chat.temp)
                append(",\"topK\":").append(chat.topK)
                append(",\"topP\":").append(chat.topP)
                append(",\"minP\":0.05")
                append(",\"repeatPenalty\":").append(chat.repeatPenalty)
                append(",\"penaltyLastN\":64")
                append(",\"seed\":").append(chat.seed)
                append("}}")
            }
            NativeBridge.nativeChatRequest(sess, body)

            var stream = StringBuilder()
            var reason = "stop"
            var tokensOut = 0L
            var tps = 0.0
            var err: String? = null
            for (ev in task.channel) {
                when (ev) {
                    is NativeEvent.Token -> {
                        stream.append(ev.text)
                        Repo.updateLive(chatId) {
                            it.text = stream.toString()
                        }
                    }
                    is NativeEvent.Done -> {
                        stream = StringBuilder(ev.text)
                        reason = ev.reason
                        tokensOut = ev.n
                        tps = ev.tps
                        Repo.updateLive(chatId) { it.text = ev.text }
                    }
                    is NativeEvent.Error -> {
                        err = ev.message
                    }
                    else -> {}
                }
            }
            val finalText = stream.toString()

            if (err != null) {
                Repo.updateLive(chatId) { it.error = err }
                return GenResult("", "error", tokensOut, tps, false, err)
            }

            val meta = MsgMeta(
                modelId = chat.modelId,
                mmprojId = chat.mmprojId.ifBlank { null },
                tokens = tokensOut,
                tps = tps,
                temperature = chat.temp,
                topP = chat.topP,
                maxTokens = limit,
                stopped = reason,
                partial = reason == "cancelled",
                createdAt = System.currentTimeMillis()
            )
            val asst = ChatMsg(
                id = Repo.nextMsgId(chat) + 1,
                role = "assistant",
                content = finalText,
                meta = meta
            )
            val updated = Store.loadChat(chatId)?.let { c ->
                c.copy(msgs = c.msgs + asst, updatedAt = System.currentTimeMillis())
            } ?: chat.copy(msgs = chat.msgs + asst, updatedAt = System.currentTimeMillis())
            Store.saveChat(updated)
            Repo.setChat(updated)
            Repo.refreshChatsMeta()
            Repo.updateLive(chatId) {
                it.partial = reason == "cancelled"
                it.stopped = reason
                it.tokens = tokensOut
                it.tps = tps
            }
            if (reason == "ctx_full") {
                Repo.updateLive(chatId) { it.error = "Contexto cheio — reduza o histórico ou aumente o contexto." }
            }
            return GenResult(finalText, reason, tokensOut, tps, true)
        } catch (e: Exception) {
            Repo.updateLive(chatId) { it.error = e.message ?: "Erro desconhecido" }
            return GenResult("", "error", 0, 0.0, false, e.message ?: "Erro desconhecido")
        } finally {
            Repo.clearLive(chatId)
            _activeChat.value = null
            _activeGen.value = null
            app.ggufchat.service.GenServiceController.stop()
        }
    }

    /** Interrompe a geração em andamento do chat. */
    fun stop(chatId: String) {
        sessions[chatId]?.let { NativeBridge.nativeStop(it.handle) }
    }

    fun stopAll() {
        sessions.keys.toList().forEach { stop(it) }
    }

    fun clearSession(chatId: String) {
        sessions.remove(chatId)?.let {
            NativeBridge.nativeResetSession(it.handle)
            warmed.remove(chatId)
        }
    }

    fun resetChat(chatId: String) {
        sessions.remove(chatId)?.let {
            NativeBridge.nativeDestroySession(it.handle)
            warmed.remove(chatId)
        }
        unloadIfUnused()
    }

    private fun unloadIfUnused() {
        val used = sessions.values.map { it.modelId }.toSet()
        for ((id, handle) in _nativeModelHandles.value) {
            if (id !in used) {
                NativeBridge.nativeUnloadModel(handle)
                _nativeModelHandles.value = _nativeModelHandles.value - id
            }
        }
    }

    /** Limpa tudo (fim de vida do processo). */
    fun shutdown() {
        for ((_, ref) in sessions) NativeBridge.nativeDestroySession(ref.handle)
        sessions.clear()
        for ((_, h) in _nativeModelHandles.value) NativeBridge.nativeUnloadModel(h)
        _nativeModelHandles.value = emptyMap()
    }
}
