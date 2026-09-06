package app.ggufchat.service

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
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import app.ggufchat.R
import app.ggufchat.core.CoreEngine
import app.ggufchat.core.NativeEvent
import app.ggufchat.data.Repo
import app.ggufchat.data.Store
import app.ggufchat.ui.MainActivity
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.launch

/**
 * Serviço em primeiro plano: mantém o processo vivo e com wake lock parcial
 * enquanto o motor gera a resposta com a tela bloqueada.
 */
class GenService : Service() {

    private var collectorJob: Job? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                intent.getStringExtra(EXTRA_CHAT)?.let { CoreEngine.stop(it) }
                stopSelf(startId)
                return START_NOT_STICKY
            }
        }
        val chat = intent?.getStringExtra(EXTRA_CHAT) ?: run {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        val modelName = intent.getStringExtra(EXTRA_MODEL) ?: ""

        if (collectorJob == null) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                ServiceCompat.startForeground(
                    this, NOTIF_ID,
                    notificationFor(chat, modelName, "", generating = true),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
                )
            } else {
                startForeground(NOTIF_ID, notificationFor(chat, modelName, "", generating = true))
            }
            acquireWakeLock()
            startCollecting(chat)
        } else {
            val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
            nm.notify(NOTIF_ID, notificationFor(chat, modelName, "", generating = true))
        }
        return START_NOT_STICKY
    }

    private fun startCollecting(chat: String) {
        collectorJob = CoreEngine.scope.launch {
            var last = 0L
            CoreEngine.auxEvents
                .filter { it is NativeEvent.Token || it is NativeEvent.Done ||
                        it is NativeEvent.Error || it is NativeEvent.Note }
                .collect { ev ->
                    val modelName = CoreEngine.activeGen.value?.modelName ?: ""
                    val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
                    when (ev) {
                        is NativeEvent.Token -> {
                            val now = System.currentTimeMillis()
                            if (now - last > 500) {
                                last = now
                                val partial = Repo.liveText.value[chat]?.text ?: ""
                                nm.notify(NOTIF_ID, notificationFor(chat, modelName, partial.trim().take(220), true))
                            }
                        }
                        is NativeEvent.Done -> {
                            nm.notify(NOTIF_ID, notificationFor(chat, modelName, ev.text.trim().take(300), false))
                        }
                        is NativeEvent.Error -> {
                            nm.notify(NOTIF_ID, notificationFor(chat, modelName, ev.message.take(200), false))
                        }
                        is NativeEvent.Note -> {
                            if (ev.code == "ctx_full") {
                                nm.notify(NOTIF_ID, notificationFor(chat, modelName, getString(R.string.notif_error), false))
                            }
                        }
                        else -> {}
                    }
                }
        }
    }

    private fun notificationFor(chat: String, model: String, text: String, generating: Boolean): Notification {
        val openIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
            putExtra(MainActivity.EXTRA_CHAT, chat)
        }
        val openPi = PendingIntent.getActivity(
            this, 1, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val stopIntent = Intent(this, GenService::class.java).apply {
            action = ACTION_STOP
            putExtra(EXTRA_CHAT, chat)
        }
        val stopPi = PendingIntent.getService(
            this, 2, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val title = if (generating) getString(R.string.notif_generating) else getString(R.string.notif_done)
        val content = text.ifBlank { model }
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_llm)
            .setContentTitle("$title · $model")
            .setContentText(content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(content))
            .setContentIntent(openPi)
            .addAction(0, getString(R.string.notif_stop), stopPi)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setOnlyAlertOnce(true)
            .setOngoing(generating)
            .build()
    }

    private fun acquireWakeLock() {
        if (wakeLock == null) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ggufchat:gen").apply {
                setReferenceCounted(false)
                acquire(60 * 60_000L)
            }
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    override fun onDestroy() {
        collectorJob?.cancel()
        collectorJob = null
        releaseWakeLock()
        super.onDestroy()
    }

    companion object {
        const val CHANNEL_ID = "generation"
        const val NOTIF_ID = 4242
        const val ACTION_STOP = "app.ggufchat.action.STOP"
        const val EXTRA_CHAT = "chat_id"
        const val EXTRA_MODEL = "model_name"

        private var channelCreated = false

        fun ensureChannel(ctx: Context) {
            if (channelCreated) return
            val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val ch = NotificationChannel(
                CHANNEL_ID,
                ctx.getString(R.string.notif_channel_name),
                NotificationManager.IMPORTANCE_LOW
            )
            ch.description = ctx.getString(R.string.notif_channel_desc)
            nm.createNotificationChannel(ch)
            channelCreated = true
        }
    }
}

/** Controla o ciclo de vida do serviço a partir do motor. */
object GenServiceController {
    /**
     * Inicia o serviço em primeiro plano durante a geração quando a opção
     * "continuar com a tela bloqueada" está ativa. Ao bloquear a tela, o
     * processo permanece vivo (notificação + wake lock) até a resposta
     * terminar — o motor roda numa thread própria descolada da UI.
     */
    fun startIfNeeded(chatId: String, modelName: String) {
        val ctx = Store.appContext
        if (!Repo.settings.value.bgGenerate) return
        GenService.ensureChannel(ctx)
        try {
            val intent = Intent(ctx, GenService::class.java).apply {
                putExtra(GenService.EXTRA_CHAT, chatId)
                putExtra(GenService.EXTRA_MODEL, modelName)
            }
            ContextCompat.startForegroundService(ctx, intent)
        } catch (_: Exception) {
        }
    }

    fun stop() {
        val ctx = Store.appContext
        ctx.stopService(Intent(ctx, GenService::class.java))
    }
}
