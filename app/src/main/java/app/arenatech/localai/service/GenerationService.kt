package app.arenatech.localai.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import app.arenatech.localai.MainActivity
import app.arenatech.localai.R
import app.arenatech.localai.data.Prefs
import app.arenatech.localai.engine.Engine
import app.arenatech.localai.generation.GenerationRunner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Foreground service that keeps the CPU awake while the model is generating so
 * answers continue to be produced even after the user locks the screen / leaves
 * the app. Generation itself runs in the process-wide [GenerationRunner].
 */
class GenerationService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var wakeLock: PowerManager.WakeLock? = null
    private var started = false

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                scope.launch {
                    GenerationRunner.stopAndJoin()
                    finish()
                }
                return START_NOT_STICKY
            }
            else -> {
                val chatId = intent?.getStringExtra(EXTRA_CHAT_ID) ?: run { finish(); return START_NOT_STICKY }
                val research = intent.getBooleanExtra(EXTRA_RESEARCH, false)
                val thinking = intent.getBooleanExtra(EXTRA_THINKING, true)
                if (!started) {
                    started = true
                    startInForeground(chatId)
                    Engine.ensure(this)
                    GenerationRunner.start(chatId, research, thinking)
                    observe()
                }
                return START_NOT_STICKY
            }
        }
    }

    private fun observe() {
        scope.launch {
            GenerationRunner.status.collect { s ->
                when (s.phase) {
                    GenerationRunner.Phase.IDLE, GenerationRunner.Phase.ERROR -> {
                        if (started) {
                            started = false
                            finish()
                        }
                    }
                    else -> {
                        updateNotification(s.message)
                        acquireWakeLock()
                    }
                }
            }
        }
    }

    private fun startInForeground(chatId: String) {
        acquireWakeLock()
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
            putExtra(MainActivity.EXTRA_OPEN_CHAT, chatId)
        }
        val pi = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val stopIntent = Intent(this, GenerationService::class.java).apply { action = ACTION_STOP }
        val stopPi = PendingIntent.getService(
            this, 1, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("LocalAI — gerando resposta")
            .setContentText("A inferência está rodando no dispositivo…")
            .setSmallIcon(R.drawable.ic_stat)
            .setOngoing(true)
            .setContentIntent(pi)
            .addAction(0, "Parar", stopPi)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                NOTIF_ID, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            )
        } else {
            startForeground(NOTIF_ID, notification)
        }
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("LocalAI — gerando resposta")
            .setContentText(text.ifBlank { "A inferência está rodando…" })
            .setSmallIcon(R.drawable.ic_stat)
            .setOngoing(true)
            .build()
        runCatching { nm.notify(NOTIF_ID, notification) }
    }

    private fun acquireWakeLock() {
        if (wakeLock == null) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "LocalAI:generation")
                .apply {
                    setReferenceCounted(false)
                    acquire(60 * 60 * 1000L)
                }
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
    }

    private fun finish() {
        releaseWakeLock()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun createChannel() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val ch = NotificationChannel(CHANNEL_ID, "Geração em segundo plano", NotificationManager.IMPORTANCE_LOW)
        ch.description = "Mantém a geração de resposta ativa com a tela bloqueada."
        nm.createNotificationChannel(ch)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        scope.cancel()
        releaseWakeLock()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL_ID = "generation"
        private const val NOTIF_ID = 1001

        const val ACTION_GENERATE = "app.arenatech.localai.action.GENERATE"
        const val ACTION_STOP = "app.arenatech.localai.action.STOP"
        const val EXTRA_CHAT_ID = "chatId"
        const val EXTRA_RESEARCH = "research"
        const val EXTRA_THINKING = "thinking"

        fun start(context: Context, chatId: String, research: Boolean, thinking: Boolean) {
            // Ensure the native engine exists no matter which path is used.
            Engine.ensure(context)
            if (Prefs.instance.generateWithScreenLocked) {
                val i = Intent(context, GenerationService::class.java).apply {
                    action = ACTION_GENERATE
                    putExtra(EXTRA_CHAT_ID, chatId)
                    putExtra(EXTRA_RESEARCH, research)
                    putExtra(EXTRA_THINKING, thinking)
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(i)
                else context.startService(i)
            } else {
                GenerationRunner.start(chatId, research, thinking)
            }
        }

        fun stop(context: Context) {
            val i = Intent(context, GenerationService::class.java).apply { action = ACTION_STOP }
            context.startService(i)
        }
    }
}
