package com.vulcanmind.vulkanmind.utils

import android.content.pm.PackageManager
import android.os.Build
import android.util.Log

object VulkanUtils {
    private const val TAG = "VulkanUtils"

    fun isVulkanSupported(pm: PackageManager): Boolean {
        val hasFeature = pm.hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_LEVEL) ||
                pm.hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_VERSION)
        Log.i(TAG, "Vulkan feature check: $hasFeature")
        return hasFeature
    }

    fun getVulkanVersion(pm: PackageManager): String {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                val hasLevel0 = pm.hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_LEVEL)
                val hasVersion1 = pm.hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_VERSION)
                "Level0=$hasLevel0 Version1=$hasVersion1"
            } else "Pre-N (no Vulkan detection)"
        } catch (e: Exception) {
            "unknown: ${e.message}"
        }
    }

    fun recommendThreadCount(): Int {
        val cores = Runtime.getRuntime().availableProcessors()
        return when {
            cores >= 8 -> 6
            cores >= 6 -> 4
            else -> 2
        }
    }

    fun logVulkanCapabilities(pm: PackageManager) {
        Log.i(TAG, "=== VULKAN CAPABILITIES ===")
        Log.i(TAG, "VulkanSupported: ${isVulkanSupported(pm)}")
        Log.i(TAG, "VulkanVersion: ${getVulkanVersion(pm)}")
        Log.i(TAG, "Cores: ${Runtime.getRuntime().availableProcessors()} -> threads ${recommendThreadCount()}")
        Log.i(TAG, "==========================")
    }
}
