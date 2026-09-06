package app.ggufchat.core

/** Recebe eventos JSON do motor nativo (qualquer thread). */
interface EngineListener {
    fun onEvent(json: String)
}

/**
 * Ponte JNI para o motor nativo (libllmcore.so — llama.cpp + Vulkan + mtmd).
 * O nativo lê o campo estático [listener] e invoca [EngineListener.onEvent]
 * com eventos JSON correlacionados pelo campo "token" do pedido.
 */
class NativeBridge private constructor() {
    companion object {
        init {
            System.loadLibrary("llmcore")
        }

        @JvmField
        var listener: EngineListener? = null

        @JvmStatic
        external fun nativeInit(): String

        @JvmStatic
        external fun nativeProbeModel(path: String): String

        @JvmStatic
        external fun nativeLoadModel(cfgJson: String)

        @JvmStatic
        external fun nativeUnloadModel(handle: Long)

        @JvmStatic
        external fun nativeCreateSession(cfgJson: String)

        @JvmStatic
        external fun nativeDestroySession(handle: Long)

        @JvmStatic
        external fun nativeChatRequest(handle: Long, reqJson: String)

        @JvmStatic
        external fun nativeStop(handle: Long)

        @JvmStatic
        external fun nativeResetSession(handle: Long)
    }
}
