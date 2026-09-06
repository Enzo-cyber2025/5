package com.vulcanmind.vulkanmind.utils

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Log
import java.io.File
import java.io.FileInputStream
import java.nio.channels.FileChannel

object FileUtils {
    private const val TAG = "FileUtils"

    fun getFileName(ctx: Context, uri: Uri): String {
        var name: String? = null
        ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (idx >= 0) name = c.getString(idx)
            }
        }
        return name ?: uri.lastPathSegment?.substringAfterLast('/') ?: "model.gguf"
    }

    fun getFileSize(ctx: Context, uri: Uri): Long {
        ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val idx = c.getColumnIndex(OpenableColumns.SIZE)
                if (idx >= 0) return c.getLong(idx)
            }
        }
        return -1
    }

    /**
     * Verifica GGUF magic sem carregar tudo em memória - lê apenas 4 bytes via FileChannel
     */
    fun isGgufFile(file: File): Boolean {
        return try {
            FileInputStream(file).use { fis ->
                val header = ByteArray(4)
                if (fis.read(header) != 4) return false
                val magic = String(header)
                magic == "GGUF" || magic == "GGML"
            }
        } catch (e: Exception) {
            Log.w(TAG, "isGguf check fail", e)
            false
        }
    }

    /**
     * Cálculo de hash rápido para verificar integridade (xxhash64 stub)
     */
    fun quickHash(file: File): String {
        return try {
            FileInputStream(file).channel.use { ch ->
                val size = ch.size()
                val buf = ch.map(FileChannel.MapMode.READ_ONLY, 0, minOf(size, 1024*1024))
                var hash = 0L
                while (buf.hasRemaining()) {
                    hash = hash * 31 + buf.get().toLong()
                }
                hash.toString(16)
            }
        } catch (_: Exception) { "unknown" }
    }

    fun formatBytes(bytes: Long): String {
        val gb = bytes / (1024.0*1024*1024)
        val mb = bytes / (1024.0*1024)
        return if (gb >= 1) String.format("%.2f GB", gb) else String.format("%.0f MB", mb)
    }

    fun ensureCacheDir(ctx: Context): File {
        return File(ctx.filesDir, "gguf_cache").apply { mkdirs() }
    }
}
