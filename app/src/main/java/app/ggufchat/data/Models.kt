package app.ggufchat.data

import kotlinx.serialization.Serializable

@Serializable
data class ProbeInfo(
    val ok: Boolean = false,
    val name: String = "",
    val arch: String = "",
    val desc: String = "",
    val layers: Long = -1,
    val ftype: Long = -1,
    val size: Long = 0,
    val is_llm: Boolean = false,
    val error: String? = null
)

@Serializable
data class ChatModel(
    val id: String,             // slug
    val name: String = "",      // nome amigável (editável)
    val fileName: String = "",  // arquivo original importado
    val file: String = "",      // caminho absoluto no app
    val size: Long = 0,
    val arch: String = "",
    val isLlm: Boolean = true,  // false => mmproj (projetor de visão)
    val forceMmproj: Boolean = false,
    val createdAt: Long = 0,
    val nCtxDefault: Int = 4096,
    val useGpu: Boolean = true,
    val offload: String = "auto",   // auto | full | cpu
    val threads: Int = 4,
    val templateOverride: String = "",
    val systemPrompt: String = "",
    val thinking: Boolean = false   // exibir bloco de raciocínio
) {
    val isVisionProjector: Boolean get() = forceMmproj || !isLlm
}

@Serializable
data class MsgMeta(
    val modelId: String? = null,
    val mmprojId: String? = null,
    val tokens: Long = 0,
    val tps: Double = 0.0,
    val temperature: Double = 0.8,
    val topP: Double = 0.95,
    val maxTokens: Int = -1,
    val stopped: String? = null,   // stop|length|cancelled|ctx_full|error
    val partial: Boolean = false,
    val usedNctx: Int = 0,
    val createdAt: Long = 0
)

@Serializable
data class ChatMsg(
    val id: Long = 0,
    val role: String = "user",          // user | assistant | system
    val content: String = "",
    val thinking: String = "",
    val images: List<String> = emptyList(),
    val meta: MsgMeta? = null
)

@Serializable
data class Chat(
    val id: String,                 // slug
    val title: String = "Novo chat",
    val modelId: String = "",
    val mmprojId: String = "",      // opcional: projetor de visão
    val systemPrompt: String = "",
    val createdAt: Long = 0,
    val updatedAt: Long = 0,
    val msgs: List<ChatMsg> = emptyList(),
    val nCtx: Int = 4096,
    val temp: Double = 0.8,
    val topP: Double = 0.95,
    val topK: Int = 40,
    val repeatPenalty: Double = 1.0,
    val maxTokens: Int = -1,
    val seed: Long = 0,
    val flashAttn: Boolean = true,
    val thinking: Boolean = false
)

@Serializable
data class AppSettings(
    val theme: String = "system",            // system|dark|light
    val bgGenerate: Boolean = false,          // permitir geração com a tela bloqueada
    val searchEnabled: Boolean = true,        // ferramenta de pesquisa na web
    val searchEngine: String = "duckduckgo",
    val hideThinking: Boolean = false,        // recolher blocos de raciocínio
    val maxDownloadMb: Int = 0,               // 0 = sem limite
    val vibrateOnDone: Boolean = false,
    val keepScreenOnWhileChat: Boolean = false,
    val cpuThreads: Int = 4,
    val firstRunDone: Boolean = false
)

@Serializable
data class DeviceInfo(
    val ok: Boolean,
    val vulkan: Boolean = false,
    val gpuName: String = "",
    val gpuTotal: Long = 0,
    val gpuFree: Long = 0,
    val llama: String = "",
    val devices: List<DeviceEntry> = emptyList(),
    val error: String? = null
)

@Serializable
data class DeviceEntry(
    val name: String = "",
    val type: Int = 0,
    val total: Long = 0,
    val free: Long = 0
)

/** Estados de uma geração visíveis na UI. */
enum class GenStatus { Idle, LoadingModel, Warming, Generating, Stopping, Error }

data class GenerationUiState(
    val chatId: String? = null,
    val status: GenStatus = GenStatus.Idle,
    val modelName: String = "",
    val streamText: String = "",
    val error: String? = null
)
