package com.vulcanmind.vulkanmind.utils

import android.app.ActivityManager
import android.content.Context
import android.util.Log

object MemoryUtils {
    private const val TAG = "MemoryUtils"

    fun getAvailableMemoryMb(ctx: Context): Long {
        val am = ctx.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val info = ActivityManager.MemoryInfo()
        am.getMemoryInfo(info)
        return info.availMem / (1024*1024)
    }

    fun getTotalMemoryMb(ctx: Context): Long {
        val am = ctx.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val info = ActivityManager.MemoryInfo()
        am.getMemoryInfo(info)
        return info.totalMem / (1024*1024)
    }

    fun canLoadGguf(ctx: Context, ggufSizeBytes: Long): Boolean {
        val avail = getAvailableMemoryMb(ctx)
        val needed = ggufSizeBytes / (1024*1024) + 800 // +800MB overhead llama
        Log.i(TAG, "canLoad? avail=${avail}MB needed=${needed}MB gguf=${ggufSizeBytes/(1024*1024)}MB")
        // Vulkan permite offload para VRAM, então limiar é menor
        return avail > needed * 0.6
    }

    fun logMemory(ctx: Context) {
        Log.i(TAG, "=== MEMORY ===")
        Log.i(TAG, "Avail: ${getAvailableMemoryMb(ctx)} MB")
        Log.i(TAG, "Total: ${getTotalMemoryMb(ctx)} MB")
        Log.i(TAG, "Low: ${(ctx.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).let { val i=ActivityManager.MemoryInfo(); it.getMemoryInfo(i); i.lowMemory }}")
    }
}
