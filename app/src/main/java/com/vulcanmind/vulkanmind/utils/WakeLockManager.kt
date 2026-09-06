package com.vulcanmind.vulkanmind.utils

import android.content.Context
import android.os.PowerManager
import android.util.Log

/**
 * Gerenciador de WakeLock para geração com tela bloqueada.
 * - Usa PARTIAL_WAKE_LOCK para manter CPU ativa
 * - Timeout de 30 min para evitar drenar bateria infinitamente
 * - Reference counted false para controle manual
 * Melhor API: PowerManager + try/catch + logging extensivo.
 */
class WakeLockManager(private val context: Context) {

    private var wakeLock: PowerManager.WakeLock? = null
    private var isHeldByUs = false

    fun acquire(tag: String = "VulcanMind::WakeLock", timeoutMs: Long = 30*60*1000L): Boolean {
        return try {
            if (wakeLock == null) {
                val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
                wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, tag).apply {
                    setReferenceCounted(false)
                }
            }
            if (wakeLock?.isHeld == true) {
                Log.w(TAG, "WakeLock already held, releasing first")
                release()
            }
            wakeLock?.acquire(timeoutMs)
            isHeldByUs = true
            Log.i(TAG, "WakeLock ACQUIRED tag=$tag timeout=${timeoutMs}ms — geração continuará com display off")
            true
        } catch (e: Exception) {
            Log.e(TAG, "acquire failed", e)
            false
        }
    }

    fun release() {
        try {
            wakeLock?.let { wl ->
                if (wl.isHeld) {
                    wl.release()
                    Log.i(TAG, "WakeLock RELEASED")
                } else {
                    Log.w(TAG, "WakeLock release called but not held")
                }
            }
            isHeldByUs = false
        } catch (e: Exception) {
            Log.e(TAG, "release failed", e)
        }
    }

    fun isHeld(): Boolean = try { wakeLock?.isHeld == true } catch (_: Exception) { false }

    fun ensureHeld() {
        if (!isHeld()) {
            Log.w(TAG, "WakeLock not held but should be — re-acquiring")
            acquire()
        }
    }

    fun logStatus() {
        Log.i(TAG, "WakeLock held=${isHeld()} byUs=$isHeldByUs tag=${wakeLock}")
    }

    companion object {
        private const val TAG = "WakeLockManager"
    }
}
