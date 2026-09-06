package com.vulcanmind.vulkanmind.data.repository

import com.vulcanmind.vulkanmind.data.db.ChatDao
import com.vulcanmind.vulkanmind.data.db.MessageDao
import com.vulcanmind.vulkanmind.data.models.Chat
import com.vulcanmind.vulkanmind.data.models.Message
import kotlinx.coroutines.flow.Flow

class ChatRepository(
    private val chatDao: ChatDao,
    private val messageDao: MessageDao
) {
    fun observeChats(): Flow<List<Chat>> = chatDao.observeChats()
    fun observeMessages(chatId: Long): Flow<List<Message>> = messageDao.observeMessages(chatId)

    suspend fun createChat(title: String = "Novo Chat", thinking: Boolean = true, search: Boolean = true): Long {
        val chat = Chat(title = title, thinkingEnabled = thinking, searchEnabled = search)
        return chatDao.insert(chat)
    }

    suspend fun getChat(id: Long) = chatDao.getChat(id)
    suspend fun deleteChat(id: Long) {
        messageDao.clearChat(id)
        chatDao.delete(id)
    }
    suspend fun renameChat(id: Long, title: String) = chatDao.rename(id, title)
    suspend fun touchChat(id: Long) = chatDao.touch(id)
    suspend fun updateChat(chat: Chat) = chatDao.update(chat)

    suspend fun addMessage(msg: Message): Long {
        val id = messageDao.insert(msg)
        chatDao.touch(msg.chatId)
        return id
    }

    suspend fun getMessages(chatId: Long) = messageDao.getMessages(chatId)
    suspend fun clearMessages(chatId: Long) = messageDao.clearChat(chatId)

    // Exporta chat para markdown (útil para compartilhar)
    suspend fun exportChat(chatId: Long): String {
        val chat = chatDao.getChat(chatId) ?: return ""
        val msgs = messageDao.getMessages(chatId)
        val sb = StringBuilder()
        sb.appendLine("# ${chat.title}")
        sb.appendLine("_VulcanMind Vulkan — GGUF direto da memória_")
        sb.appendLine()
        for (m in msgs) {
            when (m.role) {
                "user" -> sb.appendLine("**Você:** ${m.content}")
                "assistant" -> {
                    if (!m.thinkingContent.isNullOrBlank()) {
                        sb.appendLine("<details><summary>Thinking</summary>\n${m.thinkingContent}\n</details>")
                    }
                    sb.appendLine("**Vulcan:** ${m.content}")
                }
                "system" -> sb.appendLine("> Sistema: ${m.content}")
            }
            sb.appendLine()
        }
        return sb.toString()
    }
}
