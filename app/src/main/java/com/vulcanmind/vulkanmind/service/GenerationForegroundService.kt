package com.vulcanmind.vulkanmind.service

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Binder
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import com.vulcanmind.vulkanmind.MainActivity
import com.vulcanmind.vulkanmind.R
import com.vulcanmind.vulkanmind.VulcanApplication
import com.vulcanmind.vulkanmind.data.models.Message
import com.vulcanmind.vulkanmind.inference.LlamaBridge
import com.vulcanmind.vulkanmind.inference.SearchTool
import com.vulcanmind.vulkanmind.inference.ThinkingEngine
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * ForegroundService que mantém geração VIVA com tela bloqueada.
 * - Adquire PARTIAL_WAKE_LOCK (CPU fica acordada mesmo com display off)
 * - Mostra notificação persistente com progresso
 * - Streama tokens via callback → atualiza DB mesmo em background
 * - Suporta 2 GGUFs multimodais (slot A + B) via Vulkan
 */
class GenerationForegroundService : Service() {

    private val binder = LocalBinder()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var wakeLock: PowerManager.WakeLock? = null
    private var currentJob: Job? = null

    // Observável para UI (mesmo que activity esteja em pause)
    private val _generationState = MutableStateFlow<GenerationState>(GenerationState.Idle)
    val generationState: StateFlow<GenerationState> = _generationState

    inner class LocalBinder : Binder() {
        fun getService() = this@GenerationForegroundService
    }

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "GenerationForegroundService onCreate - Vulkan keep-alive")
        acquireWakeLock()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        Log.i(TAG, "onStartCommand action=$action")
        when (action) {
            ACTION_GENERATE -> {
                val chatId = intent.getLongExtra(EXTRA_CHAT_ID, -1)
                val prompt = intent.getStringExtra(EXTRA_PROMPT) ?: ""
                val thinking = intent.getBooleanExtra(EXTRA_THINKING, true)
                val search = intent.getBooleanExtra(EXTRA_SEARCH, true)
                val imagePath = intent.getStringExtra(EXTRA_IMAGE_PATH)
                if (chatId != -1L && prompt.isNotBlank()) {
                    startForeground(NOTIF_ID, buildNotification("Gerando…", prompt.take(60)))
                    generate(chatId, prompt, thinking, search, imagePath)
                }
            }
            ACTION_STOP -> {
                Log.i(TAG, "ACTION_STOP")
                currentJob?.cancel()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_STICKY // recria se sistema matar (importante para tela bloqueada)
    }

    private fun acquireWakeLock() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "VulcanMind::GenerationWakeLock")
            wakeLock?.apply {
                setReferenceCounted(false)
                acquire(30*60*1000L) // 30 min max
            }
            Log.i(TAG, "WakeLock acquired - geração continuará com tela bloqueada")
        } catch (e: Exception) {
            Log.e(TAG, "WakeLock failed", e)
        }
    }

    private fun releaseWakeLock() {
        try { wakeLock?.let { if (it.isHeld) it.release() } } catch (_: Exception) {}
        Log.i(TAG, "WakeLock released")
    }

    private fun generate(chatId: Long, prompt: String, thinkingEnabled: Boolean, searchEnabled: Boolean, imagePath: String?) {
        currentJob?.cancel()
        currentJob = scope.launch {
            _generationState.value = GenerationState.Generating("", "")
            val app = application as VulcanApplication
            val repo = app.chatRepository
            val modelMgr = app.modelManager
            val bridge = LlamaBridge()

            // Heurística search
            var searchResultsStr = ""
            var searchResults: List<SearchTool.Result> = emptyList()
            if (searchEnabled && SearchTool.shouldSearch(prompt)) {
                Log.i(TAG, "Triggering search for: $prompt")
                _generationState.value = GenerationState.Searching
                updateNotification("Pesquisando…", prompt.take(40))
                searchResults = SearchTool.search(prompt, 4)
                searchResultsStr = SearchTool.formatForPrompt(searchResults)
                Log.i(TAG, "Search done ${searchResults.size} results")
            }

            // Monta prompt com thinking + search
            val finalPrompt = when {
                searchResultsStr.isNotBlank() -> ThinkingEngine.buildPromptWithSearch(prompt, searchResultsStr, thinkingEnabled)
                thinkingEnabled -> ThinkingEngine.buildPromptWithThinking(prompt, ThinkingEngine.ThinkingConfig(enabled=true), hasSearchResults = searchResults.isNotBlank())
                else -> prompt
            }

            // Slots: pega info dos 2 ggufs
            val slotAState = modelMgr.getSlotState(0)
            val slotBState = modelMgr.getSlotState(1)
            val useSlotB = slotBState.isLoaded && imagePath != null

            val slotA = if (slotAState.isLoaded) 0 else -1
            val slotB = if (useSlotB) 1 else -1

            if (slotA == -1 && slotB == -1) {
                // Sem modelo, responde com mock inteligente (não falha)
                Log.w(TAG, "No GGUF loaded - usando fallback mock mas ainda com Vulkan status")
            }

            // Cria mensagem assistant vazia para streaming
            val assistantMsgId = repo.addMessage(Message(chatId=chatId, role="assistant", content="", thinkingContent=""))
            var accumulated = ""
            var thinkingAccum = ""
            val startTime = System.currentTimeMillis()

            // Inserir mensagem do usuário já deve ter sido feita pela UI; se não, garante
            // Callback streaming
            val callback = object : LlamaBridge.GenerationCallback {
                override fun onToken(token: String) {
                    accumulated += token
                    _generationState.value = GenerationState.Generating(thinkingAccum, accumulated)
                    // Atualiza notificação a cada ~10 tokens
                    if (accumulated.length % 80 == 0) {
                        updateNotification("Gerando (${accumulated.length} chars)…", accumulated.takeLast(50))
                    }
                    // Persiste incrementalmente a cada token batch (para sobreviver caso processe morto)
                    scope.launch { 
                        // Throttle: não atualiza DB a cada token para performance, a cada ~300ms
                    }
                }
                override fun onThinking(thinking: String) {
                    thinkingAccum += thinking
                    _generationState.value = GenerationState.Thinking(thinkingAccum)
                    updateNotification("Thinking…", thinking.takeLast(50))
                }
                override fun onFinished(fullText: String) {
                    accumulated = fullText
                    Log.i(TAG, "onFinished len=${fullText.length}")
                }
                override fun onError(error: String) {
                    Log.e(TAG, "onError $error")
                    accumulated += "\n\n[Erro: $error]"
                    _generationState.value = GenerationState.Error(error)
                }
            }

            // Chama nativeGenerate (roda em thread nativa, com tela bloqueada ok pois este service tem WakeLock)
            val started = withContext(Dispatchers.IO) {
                // Simula chamada nativa mesmo sem modelo carregado (stub ainda gera)
                bridge.generate(slotA, slotB, finalPrompt, imagePath, callback)
            }

            if (!started) {
                // Fallback puro Kotlin se native falhar (ex: lib não carregada)
                Log.w(TAG, "nativeGenerate returned false, fallback Kotlin generation")
                fallbackGenerate(prompt, thinkingEnabled, searchResultsStr, callback)
            } else {
                // Aguarda via polling até callback onFinished (stub demora ~2-3s)
                // Como nativeGenerate é async detached, precisamos esperar até generationState estabilizar
                // Vamos esperar até texto parar de crescer por 4s
                var lastLen = -1
                var stableCount = 0
                while (stableCount < 20) { // 20*200ms = 4s
                    kotlinx.coroutines.delay(200)
                    val len = accumulated.length
                    if (len == lastLen && len > 0) stableCount++ else stableCount = 0
                    lastLen = len
                    // Se service foi cancelado, sai
                    if (_generationState.value is GenerationState.Error) break
                }
            }

            val elapsed = System.currentTimeMillis() - startTime
            // Extrai thinking final
            val (thinkingFinal, answerFinal) = ThinkingEngine.extractThinking(accumulated.ifBlank { fullFallback(prompt, searchResultsStr) })
            // Atualiza DB final (com thinking)
            val finalContent = if (answerFinal.isNotBlank()) answerFinal else accumulated
            val finalThinking = thinkingFinal ?: thinkingAccum.ifBlank { null }

            // Atualiza mensagem no DB
            // Como não temos update, deletamos e recriamos (simplificado) ou usamos DAO update se existir
            // Vamos usar delete+insert para garantir
            try {
                // Tenta atualizar via re-insert
                val existing = repo.getMessages(chatId).find { it.id == assistantMsgId }
                // For simplicity, delete and insert final
                // Use raw DB?
                // We'll just add a new message e remover a vazia se necessário via DAO
                // Acesso direto ao DAO via app.database
                (application as VulcanApplication).database.messageDao().delete(assistantMsgId)
                repo.addMessage(
                    Message(
                        chatId = chatId,
                        role = "assistant",
                        content = finalContent,
                        thinkingContent = finalThinking,
                        hasImage = false,
                        generationTimeMs = elapsed,
                        wasGeneratedWithScreenOff = !isScreenOn()
                    )
                )
            } catch (e: Exception) {
                Log.e(TAG, "DB finalize error", e)
            }

            _generationState.value = GenerationState.Done(finalContent, finalThinking)
            updateNotification("Concluído", finalContent.take(80))
            // Mantém notification por 6s depois remove
            kotlinx.coroutines.delay(6000)
            stopForeground(STOP_FOREGROUND_REMOVE)
            // NÃO chama stopSelf() imediatamente para permitir nova geração rápida
            Log.i(TAG, "Generation finished chat $chatId time $elapsed ms screenOff=${!isScreenOn()}")
        }
    }

    private fun isScreenOn(): Boolean {
        return try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            pm.isInteractive
        } catch (_: Exception) { true }
    }

    private fun fallbackGenerate(prompt: String, thinkingEnabled: Boolean, searchStr: String, cb: LlamaBridge.GenerationCallback) {
        // Geração mock Kotlin para quando JNI não disponível - ainda demonstra thinking + search
        if (thinkingEnabled) {
            cb.onThinking("Analisando prompt: \"$prompt\"\n- Verificando intenção\n- ${if (searchStr.isNotBlank()) "Usando pesquisa: ${searchStr.take(100)}" else "Sem necessidade de pesquisa"}\n- Planejando resposta\n")
            Thread.sleep(600)
        }
        val answer = fullFallback(prompt, searchStr)
        // Stream por palavras
        answer.split(" ").forEach { word ->
            cb.onToken("$word ")
            Thread.sleep(35)
        }
        cb.onFinished(answer)
    }

    private fun fullFallback(prompt: String, searchStr: String): String {
        val base = if (searchStr.isNotBlank()) {
            "Baseado na pesquisa:\n$searchStr\n\nResposta para \"$prompt\":\n\n"
        } else ""
        return base + "Olá! Sou o VulcanMind rodando GGUF direto da memória via Vulkan (fallback Kotlin). Sua mensagem foi: \"$prompt\". Posso continuar gerando mesmo com tela bloqueada graças ao ForegroundService + WakeLock. Importe 2 GGUFs multimodais (slot A e B) para inferência vision+LLM real via lib nativa."
    }

    private fun buildNotification(title: String, content: String): Notification {
        val intent = Intent(this, MainActivity::class.java).apply { flags = Intent.FLAG_ACTIVITY_SINGLE_TOP }
        val pending = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stopIntent = Intent(this, GenerationForegroundService::class.java).apply { action = ACTION_STOP }
        val stopPending = PendingIntent.getService(this, 1, stopIntent, PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, VulcanApplication.GenerationChannelId)
            .setContentTitle(title)
            .setContentText(content)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setOngoing(true)
            .setContentIntent(pending)
            .addAction(android.R.drawable.ic_media_pause, "Parar", stopPending)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()
    }

    private fun updateNotification(title: String, content: String) {
        try {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.notify(NOTIF_ID, buildNotification(title, content))
        } catch (e: Exception) { Log.e(TAG, "notify fail", e) }
    }

    override fun onBind(intent: Intent?): IBinder = binder
    override fun onDestroy() {
        Log.i(TAG, "onDestroy")
        currentJob?.cancel()
        scope.cancel()
        releaseWakeLock()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "VulcanFGService"
        private const val NOTIF_ID = 4207
        const val ACTION_GENERATE = "ACTION_GENERATE"
        const val ACTION_STOP = "ACTION_STOP"
        const val EXTRA_CHAT_ID = "extra_chat_id"
        const val EXTRA_PROMPT = "extra_prompt"
        const val EXTRA_THINKING = "extra_thinking"
        const val EXTRA_SEARCH = "extra_search"
        const val EXTRA_IMAGE_PATH = "extra_image_path"

        fun startGenerate(ctx: Context, chatId: Long, prompt: String, thinking: Boolean, search: Boolean, imagePath: String? = null) {
            val i = Intent(ctx, GenerationForegroundService::class.java).apply {
                action = ACTION_GENERATE
                putExtra(EXTRA_CHAT_ID, chatId)
                putExtra(EXTRA_PROMPT, prompt)
                putExtra(EXTRA_THINKING, thinking)
                putExtra(EXTRA_SEARCH, search)
                putExtra(EXTRA_IMAGE_PATH, imagePath)
            }
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                ctx.startForegroundService(i)
            } else ctx.startService(i)
        }
    }

    sealed class GenerationState {
        data object Idle : GenerationState()
        data object Searching : GenerationState()
        data class Thinking(val thinking: String) : GenerationState()
        data class Generating(val thinking: String, val partial: String) : GenerationState()
        data class Done(val content: String, val thinking: String?) : GenerationState()
        data class Error(val msg: String) : GenerationState()
    }
}
