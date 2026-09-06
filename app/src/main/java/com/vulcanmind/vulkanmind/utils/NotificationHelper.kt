package com.vulcanmind.vulkanmind.utils

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.vulcanmind.vulkanmind.MainActivity
import com.vulcanmind.vulkanmind.R

object NotificationHelper {
    private const val CHANNEL_GEN = "vulcan_generation_v7"
    private const val CHANNEL_SYS = "vulcan_system_v7"

    fun ensureChannels(ctx: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (nm.getNotificationChannel(CHANNEL_GEN) == null) {
                nm.createNotificationChannel(NotificationChannel(CHANNEL_GEN, "Geração Foreground", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "Geração com tela bloqueada"
                    setShowBadge(false)
                })
            }
            if (nm.getNotificationChannel(CHANNEL_SYS) == null) {
                nm.createNotificationChannel(NotificationChannel(CHANNEL_SYS, "Sistema", NotificationManager.IMPORTANCE_MIN).apply {
                    description = "Status Vulkan"
                    setShowBadge(false)
                })
            }
        }
    }

    fun buildGeneratingNotification(ctx: Context, title: String, text: String, stopIntent: PendingIntent? = null): Notification {
        val launch = PendingIntent.getActivity(ctx, 0, Intent(ctx, MainActivity::class.java).apply { flags = Intent.FLAG_ACTIVITY_SINGLE_TOP }, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val builder = NotificationCompat.Builder(ctx, CHANNEL_GEN)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setOngoing(true)
            .setContentIntent(launch)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        if (stopIntent != null) builder.addAction(android.R.drawable.ic_media_pause, "Parar", stopIntent)
        return builder.build()
    }
}
