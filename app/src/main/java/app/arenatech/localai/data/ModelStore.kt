package app.arenatech.localai.data

import android.content.Context
import android.net.Uri
import app.arenatech.localai.engine.Engine
import app.arenatech.localai.generation.GenerationRunner
import com.arm.aichat.gguf.GgufMetadata
import com.arm.aichat.gguf.GgufMetadataReader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/**
 * Holds the imported GGUF model slots (default: 2) and their persistence.
 * Only the model referenced by the currently active slot is loaded into the
 * native engine at any one time.
 */
class ModelStore(private val context: Context) {

    private val _slots = MutableStateFlow<Map<String, ModelSlot>>(emptyMap())
    val slots: StateFlow<Map<String, ModelSlot>> = _slots.asStateFlow()

    private val mutex = Mutex()
    private val modelsDir: File get() = File(context.filesDir, "models")
    private val dbDir: File get() = File(context.filesDir, "db")

    init {
        loadFromDisk()
    }

    private fun fileFor(slotId: String) = File(modelsDir, "$slotId.gguf")

    fun loadFromDisk() {
        val f = File(dbDir, "models.json")
        val map = linkedMapOf<String, ModelSlot>()
        if (f.exists()) {
            runCatching {
                val arr = JSONObject(f.readText()).getJSONArray("slots")
                for (i in 0 until arr.length()) {
                    val o = arr.getJSONObject(i)
                    map[o.getString("id")] = ModelSlot(
                        id = o.getString("id"),
                        label = o.getString("label"),
                        sourceName = o.optString("sourceName"),
                        modelPath = o.optString("modelPath"),
                        arch = o.optString("arch"),
                        metaSummary = o.optString("metaSummary"),
                        sizeBytes = o.optLong("sizeBytes"),
                        vision = o.optBoolean("vision"),
                    )
                }
            }.onFailure { map.clear() }
        }
        // Fill in the fixed slots even when empty.
        val full = linkedMapOf<String, ModelSlot>()
        ModelSlots.allIds.forEachIndexed { i, id ->
            full[id] = map[id] ?: ModelSlot(id = id, label = "Modelo ${i + 1}")
        }
        _slots.value = full
    }

    suspend fun get(slotId: String): ModelSlot = mutex.withLock { _slots.value[slotId] ?: emptySlot(slotId) }

    fun emptySlot(id: String): ModelSlot {
        val i = ModelSlots.allIds.indexOf(id)
        return ModelSlot(id = id, label = "Modelo ${if (i < 0) 1 else i + 1}")
    }

    /** Imports a GGUF chosen by the user (via Storage Access Framework) into [slotId]. */
    suspend fun importTo(slotId: String, uri: Uri): ModelSlot = withContext(Dispatchers.IO) {
        mutex.withLock {
            val reader = GgufMetadataReader.create()
            if (!reader.ensureSourceFileFormat(context, uri)) {
                throw InvalidModelException("Arquivo não é um GGUF válido.")
            }
            // Parse metadata (light read at the head of the file).
            val meta: GgufMetadata? = context.contentResolver.openInputStream(uri)?.use {
                reader.readStructuredMetadata(it)
            }

            // Resolve a human friendly display name.
            val name = meta?.basic?.name ?: meta?.architecture?.architecture ?: "model"
            val sizeLbl = meta?.basic?.sizeLabel?.let { "-$it" } ?: ""
            val sourceName = "$name$sizeLbl".trim()

            // Copy the (potentially large) file into private app storage.
            val dest = fileFor(slotId)
            dest.parentFile?.mkdirs()
            if (dest.exists()) dest.delete()
            context.contentResolver.openInputStream(uri)?.use { input ->
                File(dest.parentFile, "$slotId.part").outputStream().use { out -> input.copyTo(out, 4 * 1024 * 1024) }
            }
            val finalDest = fileFor(slotId)
            File(dest.parentFile, "$slotId.part").renameTo(finalDest)

            val arch = meta?.architecture?.architecture ?: "desconhecido"
            val index = ModelSlots.allIds.indexOf(slotId).coerceAtLeast(0)
            val slot = ModelSlot(
                id = slotId,
                label = "Modelo ${index + 1}",
                sourceName = sourceName,
                modelPath = finalDest.absolutePath,
                arch = arch,
                metaSummary = summarize(meta),
                sizeBytes = finalDest.length(),
                vision = looksMultimodal(name, meta),
            )
            _slots.update { it + (slotId to slot) }
            persistLocked()
            slot
        }
    }

    suspend fun clear(slotId: String) = withContext(Dispatchers.IO) {
        mutex.withLock {
            // Stop any ongoing generation that might hold this model's file.
            GenerationRunner.stopAndJoin()
            if (Engine.isSlotLoadedSync(slotId)) Engine.unloadSync()
            runCatching { fileFor(slotId).delete() }
            val index = ModelSlots.allIds.indexOf(slotId).coerceAtLeast(0)
            _slots.update { it + (slotId to emptySlot(slotId)) }
            persistLocked()
        }
    }

    private fun summarize(meta: GgufMetadata?): String {
        if (meta == null) return ""
        val b = StringBuilder()
        meta.architecture?.architecture?.let { b.append("Arq: ").append(it).append('\n') }
        meta.architecture?.vocabSize?.let { b.append("Vocab: ").append(it).append('\n') }
        meta.dimensions?.contextLength?.let { b.append("Ctx: ").append(it).append('\n') }
        meta.dimensions?.embeddingSize?.let { b.append("Hidden: ").append(it).append('\n') }
        meta.dimensions?.blockCount?.let { b.append("Camadas: ").append(it).append('\n') }
        meta.architecture?.fileType?.let { b.append("Tipo: ").append(it).append('\n') }
        meta.author?.license?.let { b.append("Licença: ").append(it) }
        return b.toString().trim()
    }

    private fun looksMultimodal(name: String, meta: GgufMetadata?): Boolean {
        val tags = meta?.additional?.tags.orEmpty().joinToString(" ")
        val hay = (name + " " + tags + " " + (meta?.architecture?.architecture ?: "")).lowercase()
        return listOf("llava", "clip", "vision", "mmproj", "qwen2-vl", "multimodal", "florence")
            .any { hay.contains(it) }
    }

    private fun persistLocked() {
        dbDir.mkdirs()
        val arr = JSONArray()
        _slots.value.values.forEach { s ->
            arr.put(JSONObject().apply {
                put("id", s.id); put("label", s.label); put("sourceName", s.sourceName)
                put("modelPath", s.modelPath); put("arch", s.arch)
                put("metaSummary", s.metaSummary); put("sizeBytes", s.sizeBytes)
                put("vision", s.vision)
            })
        }
        File(dbDir, "models.json").writeText(JSONObject().put("slots", arr).toString())
    }

    companion object {
        @Volatile private var _instance: ModelStore? = null
        fun init(context: Context): ModelStore =
            _instance ?: synchronized(this) { ModelStore(context.applicationContext).also { _instance = it } }
        val instance: ModelStore get() = checkNotNull(_instance) { "ModelStore not initialized" }
    }
}
