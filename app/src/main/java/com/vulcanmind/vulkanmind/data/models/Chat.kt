package com.vulcanmind.vulkanmind.data.models

import androidx.room.Entity
import androidx.room.PrimaryKey
import kotlinx.serialization.Serializable

@Entity(tableName = "chats")
data class Chat(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val title: String,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis(),
    val modelSlotAName: String? = null,
    val modelSlotBName: String? = null,
    val thinkingEnabled: Boolean = true,
    val searchEnabled: Boolean = true,
    val systemPrompt: String = "Você é VulcanMind, um assistente que roda GGUFs diretamente da memória via Vulkan. Seja útil, preciso e use thinking quando necessário.",
    val pinned: Boolean = false
)

@Entity(tableName = "messages")
data class Message(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val chatId: Long,
    val role: String, // "user" | "assistant" | "system" | "thinking"
    val content: String,
    val timestamp: Long = System.currentTimeMillis(),
    val thinkingContent: String? = null, // conteúdo do <think>
    val hasImage: Boolean = false,
    val imagePath: String? = null,
    val tokenCount: Int? = null,
    val generationTimeMs: Long? = null,
    val wasGeneratedWithScreenOff: Boolean = false
)

@Serializable
data class GgufModel(
    val slot: Int, // 0 = A, 1 = B
    val name: String,
    val path: String,
    val sizeBytes: Long,
    val isLoaded: Boolean = false,
    val isMultimodal: Boolean = false,
    val vocabSize: Int? = null,
    val contextLength: Int? = null,
    val vulkanAccelerated: Boolean = true,
    val mmapDirect: Boolean = true,
    val loadTimeMs: Long = 0
)

enum class ThinkingMode {
    DISABLED, ENABLED, AUTO
}

@Serializable
data class SearchResult(
    val title: String,
    val url: String,
    val snippet: String,
    val score: Double = 0.0
)
