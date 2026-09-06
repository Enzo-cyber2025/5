package com.vulcanmind.vulkanmind.service

import android.app.Service
import android.content.Intent
import android.os.IBinder
import android.util.Log

// Wrapper secundário para manter compatibilidade e mostrar 2 services em foreground se necessário
class InferenceService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Log.i("InferenceService", "Dummy start - delegated to GenerationForegroundService")
        return START_NOT_STICKY
    }
}
