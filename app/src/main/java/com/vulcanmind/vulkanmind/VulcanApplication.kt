package com.vulcanmind.vulkanmind

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.util.Log
import androidx.room.Room
import com.vulcanmind.vulkanmind.data.db.AppDatabase
import com.vulcanmind.vulkanmind.data.repository.ChatRepository
import com.vulcanmind.vulkanmind.inference.ModelManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob

class VulcanApplication : Application() {

    val applicationScope = CoroutineScope(SupervisorJob())

    // Lazy singletons para performance - Vulkan init é pesado, não bloquear main thread
    val database by lazy {
        Room.databaseBuilder(
            this,
            AppDatabase::class.java,
            "vulcanmind_v7.db"
        )
        .fallbackToDestructiveMigration()
        .build()
    }

    val chatRepository by lazy {
        ChatRepository(database.chatDao(), database.messageDao())
    }

    val modelManager by lazy {
        ModelManager(this)
    }

    override fun onCreate() {
        super.onCreate()
        Log.i("VulcanApp", "VulcanMind 7.0.0 - Vulkan GGUF direct memory - initializing")
        createNotificationChannels()
        // Pre-warm Vulkan backend in background (não bloqueia UI)
        applicationScope.apply {
            // ModelManager já faz lazy init do native lib
            try {
                ModelManager.preloadNative()
            } catch (e: Throwable) {
                Log.e("VulcanApp", "Native preload failed", e)
            }
        }
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                GenerationChannelId,
                "Geração em Segundo Plano",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Mantém geração com tela bloqueada via ForegroundService + WakeLock"
                setShowBadge(false)
            }
            val mgr = getSystemService(NotificationManager::class.java)
            mgr.createNotificationChannel(channel)

            val sysChannel = NotificationChannel(
                SystemChannelId,
                "Sistema Vulkan",
                NotificationManager.IMPORTANCE_MIN
            ).apply {
                description = "Status Vulkan e GGUF"
                setShowBadge(false)
            }
            mgr.createNotificationChannel(sysChannel)
        }
    }

    companion object {
        const val GenerationChannelId = "vulcan_generation_v7"
        const val SystemChannelId = "vulcan_system_v7"
    }
}
