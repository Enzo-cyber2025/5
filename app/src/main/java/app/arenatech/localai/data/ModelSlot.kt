package app.arenatech.localai.data

/** Number of GGUF model slots the user can import & switch between. */
object ModelSlots {
    const val MAX_SLOTS = 2
    const val DEFAULT_SLOT_ID = "slot-0"
    val allIds: List<String> = (0 until MAX_SLOTS).map { "slot-$it" }
}

data class ModelSlot(
    val id: String,
    val label: String,
    val sourceName: String = "",
    val modelPath: String = "",   // absolute path to the file copied into app storage
    val arch: String = "",
    val metaSummary: String = "",
    val sizeBytes: Long = 0L,
    val vision: Boolean = false,
) {
    val isEmpty: Boolean get() = modelPath.isEmpty()
    val sizeLabel: String
        get() = when {
            sizeBytes >= 1_000_000_000L -> "%.1f GB".format(sizeBytes / 1_000_000_000.0)
            sizeBytes >= 1_000_000L -> "%.0f MB".format(sizeBytes / 1_000_000.0)
            else -> "%.0f KB".format(sizeBytes / 1000.0)
        }
}

class InvalidModelException(message: String) : Exception(message)
