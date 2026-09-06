package com.vulcanmind.vulkanmind.inference

import android.util.Log

/**
 * Bridge JNI para lib vulcanmind.so (Vulkan + GGUF direct memory)
 * Todas chamadas nativas rodam via Vulkan quando disponível, com fallback CPU/GPU.
 */
class LlamaBridge {

    companion object {
        private const val TAG = "LlamaBridge"
        private var loaded = false

        fun ensureLoaded(): Boolean {
            if (loaded) return true
            return try {
                System.loadLibrary("vulcanmind")
                loaded = true
                Log.i(TAG, "libvulcanmind.so loaded - Vulkan GGUF direct memory ready")
                true
            } catch (e: UnsatisfiedLinkError) {
                Log.e(TAG, "Failed to load vulcanmind", e)
                false
            }
        }
    }

    init {
        ensureLoaded()
    }

    external fun nativeGetVulkanStatus(): String
    external fun nativeLoadGguf(path: String, slot: Int, useMmap: Boolean): Boolean
    external fun nativeUnloadGguf(slot: Int)
    external fun nativeGetModelInfo(slot: Int): String
    external fun nativeGenerate(slotA: Int, slotB: Int, prompt: String, imagePath: String?, callback: GenerationCallback): Boolean
    external fun nativeStopGeneration()
    external fun nativeGetDeviceInfo(): String

    interface GenerationCallback {
        fun onToken(token: String)
        fun onThinking(thinking: String)
        fun onFinished(fullText: String)
        fun onError(error: String)
    }

    // Wrappers com tratamento de erro e logs extensos
    fun getVulkanStatus(): String = try {
        nativeGetVulkanStatus()
    } catch (e: Throwable) {
        Log.e(TAG, "getVulkanStatus error", e)
        "ERRO: ${e.message}"
    }

    fun loadGguf(path: String, slot: Int, useMmap: Boolean = true): Boolean {
        Log.i(TAG, "loadGguf slot=$slot path=$path mmap=$useMmap")
        return try {
            nativeLoadGguf(path, slot, useMmap)
        } catch (e: Throwable) {
            Log.e(TAG, "loadGguf fail", e)
            false
        }
    }

    fun getModelInfo(slot: Int): String = try { nativeGetModelInfo(slot) } catch (e: Throwable) { "{\"loaded\":false,\"error\":\"${e.message}\"}" }

    fun generate(slotA: Int, slotB: Int, prompt: String, imagePath: String?, cb: GenerationCallback): Boolean {
        Log.i(TAG, "generate slotA=$slotA slotB=$slotB promptLen=${prompt.length} image=$imagePath")
        return try { nativeGenerate(slotA, slotB, prompt, imagePath, cb) } catch (e: Throwable) { Log.e(TAG, "generate error", e); cb.onError(e.message ?: "erro desconhecido"); false }
    }

    fun stop() { try { nativeStopGeneration() } catch (_: Throwable) {} }
    fun deviceInfo(): String = try { nativeGetDeviceInfo() } catch (e: Throwable) { "{\"error\":\"${e.message}\"}" }
}
