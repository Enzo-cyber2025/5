package app.ggufchat.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import java.io.File
import java.io.InputStream
import java.util.UUID

/**
 * Persistência em JSON simples (arquivos internos do app).
 * Tudo é gravado de forma atômica (arquivo temporário + rename).
 */
object Store {
    private const val JSON_INDENT = "  "

    val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
        prettyPrint = true
        explicitNulls = false
    }

    lateinit var appContext: Context
        private set

    fun init(ctx: Context) {
        appContext = ctx.applicationContext
        dirs()
    }

    fun dirs() {
        filesDir().mkdirs()
        modelsDir().mkdirs()
        chatsDir().mkdirs()
        imagesRoot().mkdirs()
        downloadsDir().mkdirs()
        workDir().mkdirs()
    }

    fun filesDir() = File(appContext.filesDir, "data")
    fun modelsDir() = File(filesDir(), "models")
    fun chatsDir() = File(filesDir(), "chats")
    fun imagesRoot() = File(filesDir(), "images")
    fun downloadsDir() = File(filesDir(), "downloads")
    fun workDir() = File(filesDir(), "work")   // arquivos temporários

    fun newId(prefix: String) = "$prefix-${UUID.randomUUID().toString().take(8)}"

    // ---------------- models ----------------

    private val modelsFile: File get() = File(modelsDir(), "models.json")

    fun loadModels(): List<ChatModel> = runCatching {
        if (!modelsFile.exists()) return emptyList()
        json.decodeFromString<List<ChatModel>>(modelsFile.readText())
    }.getOrDefault(emptyList())

    fun saveModels(list: List<ChatModel>) = runCatching {
        val f = File(modelsDir(), "models.json.tmp")
        f.writeText(json.encodeToString(list))
        f.renameTo(modelsFile)
    }

    // ---------------- chats ----------------

    fun loadChatsMeta(): List<Chat> = runCatching {
        chatsDir().listFiles { f -> f.isFile && f.extension == "json" }
            ?.mapNotNull { f ->
                runCatching { json.decodeFromString<Chat>(f.readText()) }.getOrNull()
            }
            ?.sortedByDescending { it.updatedAt } ?: emptyList()
    }.getOrDefault(emptyList())

    fun chatFile(id: String) = File(chatsDir(), "$id.json")

    fun loadChat(id: String): Chat? = runCatching {
        val f = chatFile(id)
        if (!f.exists()) return null
        json.decodeFromString<Chat>(f.readText())
    }.getOrNull()

    fun saveChat(chat: Chat) = runCatching {
        val f = chatFile(chat.id)
        val tmp = File(chatsDir(), "${chat.id}.tmp")
        tmp.writeText(json.encodeToString(chat))
        if (f.exists()) f.delete()
        tmp.renameTo(f)
    }

    fun deleteChat(id: String) {
        chatFile(id).delete()
        File(imagesRoot(), id).deleteRecursively()
    }

    // ---------------- settings ----------------

    private val settingsFile: File get() = File(filesDir(), "settings.json")

    fun loadSettings(): AppSettings = runCatching {
        if (!settingsFile.exists()) return AppSettings()
        json.decodeFromString<AppSettings>(settingsFile.readText())
    }.getOrDefault(AppSettings())

    fun saveSettings(s: AppSettings) = runCatching {
        val tmp = File(filesDir(), "settings.tmp")
        tmp.writeText(json.encodeToString(s))
        tmp.renameTo(settingsFile)
    }

    // ---------------- imagens ----------------

    fun imagesDir(chatId: String): File {
        val d = File(imagesRoot(), chatId)
        d.mkdirs()
        return d
    }

    /**
     * Copia/recodifica uma imagem escolhida pelo usuário para o armazenamento
     * interno (o motor nativo lê arquivos). Sempre salva JPEG (max 2048px).
     */
    suspend fun storeImage(chatId: String, input: InputStream): String? = withContext(Dispatchers.IO) {
        runCatching {
            val bmp = BitmapFactory.decodeStream(input) ?: return@withContext null
            val maxDim = 2048
            val w = bmp.width
            val h = bmp.height
            val scale = if (w > maxDim || h > maxDim) {
                maxDim.toFloat() / maxOf(w, h)
            } else 1f
            val out = if (scale < 1f) {
                Bitmap.createScaledBitmap(
                    bmp, (w * scale).toInt().coerceAtLeast(1), (h * scale).toInt().coerceAtLeast(1), true
                )
            } else bmp
            val file = File(imagesDir(chatId), "img-${UUID.randomUUID().toString().take(12)}.jpg")
            file.outputStream().use { fos ->
                out.compress(Bitmap.CompressFormat.JPEG, 90, fos)
            }
            if (out !== bmp) out.recycle()
            bmp.recycle()
            file.absolutePath
        }.getOrNull()
    }

    fun deleteImage(path: String) {
        runCatching { File(path).delete() }
    }

    fun sizeText(bytes: Long): String {
        if (bytes <= 0) return "0 B"
        val kb = bytes / 1024.0
        if (kb < 1024) return "%.0f KB".format(kb)
        val mb = kb / 1024.0
        if (mb < 1024) return (if (mb >= 100) "%.0f MB" else "%.1f MB").format(mb)
        return "%.2f GB".format(mb / 1024)
    }

    fun slugFromFileName(name: String): String {
        val base = name.substringBeforeLast('.').trim()
            .lowercase()
            .replace(Regex("[^a-z0-9]+"), "-")
            .trim('-')
        return base.ifEmpty { "modelo" }
    }
}
