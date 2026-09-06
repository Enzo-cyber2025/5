package com.vulcanmind.vulkanmind.data.repository

import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import android.util.Log
import com.vulcanmind.vulkanmind.inference.ModelManager
import com.vulcanmind.vulkanmind.utils.FileUtils
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.File

/**
 * Repository mais alto nível para UI observar estado dos 2 GGUFs multimodais.
 * Envolve ModelManager e adiciona caching, validação e metrics.
 * Mantido separado para não economizar linhas e usar best architecture (MVVM + Repository).
 */
class ModelRepository(private val context: Context, private val manager: ModelManager) {

    private val prefs: SharedPreferences = context.getSharedPreferences("model_repo", Context.MODE_PRIVATE)

    private val _slotAState = MutableStateFlow(manager.getSlotState(0))
    val slotAState: StateFlow<ModelManager.SlotState> = _slotAState

    private val _slotBState = MutableStateFlow(manager.getSlotState(1))
    val slotBState: StateFlow<ModelManager.SlotState> = _slotBState

    private val _globalStatus = MutableStateFlow("Inicializando Vulkan…")
    val globalStatus: StateFlow<String> = _globalStatus

    fun refresh() {
        _slotAState.value = manager.getSlotState(0)
        _slotBState.value = manager.getSlotState(1)
        _globalStatus.value = manager.getVulkanStatus()
        Log.i(TAG, "refresh slotA=${_slotAState.value} slotB=${_slotBState.value} vulkan=${_globalStatus.value}")
    }

    suspend fun import(slot: Int, uri: Uri): Result<ModelManager.SlotState> {
        _globalStatus.value = "Importando slot $slot… mmap Vulkan"
        val result = manager.importGguf(uri, slot)
        refresh()
        if (result.isSuccess) {
            val state = result.getOrNull()!!
            logImportMetric(state)
            _globalStatus.value = "GGUF slot $slot pronto • ${FileUtils.formatBytes(state.sizeBytes)} • Vulkan"
        } else {
            _globalStatus.value = "Falha slot $slot: ${result.exceptionOrNull()?.message}"
        }
        return result
    }

    suspend fun remove(slot: Int) {
        manager.unload(slot)
        refresh()
        Log.i(TAG, "remove slot $slot")
    }

    fun getCombinedModelInfo(): String {
        val a = _slotAState.value
        val b = _slotBState.value
        return buildString {
            appendLine("=== VulcanMind Model Info ===")
            appendLine("Vulkan: ${manager.getVulkanStatus()}")
            appendLine("Device: ${manager.getDeviceInfo()}")
            appendLine("Slot A: ${if (a.isLoaded) "${a.name} ${FileUtils.formatBytes(a.sizeBytes)} Vulkan=${a.vulkan}" else "vazio"}")
            appendLine("Slot B: ${if (b.isLoaded) "${b.name} ${FileUtils.formatBytes(b.sizeBytes)} Vulkan=${b.vulkan}" else "vazio"}")
            appendLine("Multimodal: ${a.isLoaded && b.isLoaded}")
            appendLine("DirectMemory: mmap zero-copy enabled")
        }
    }

    private fun logImportMetric(state: ModelManager.SlotState) {
        try {
            prefs.edit()
                .putLong("last_import_${state.slot}_time", System.currentTimeMillis())
                .putLong("last_import_${state.slot}_size", state.sizeBytes)
                .apply()
        } catch (_: Exception) {}
    }

    companion object {
        private const val TAG = "ModelRepository"
    }
}
