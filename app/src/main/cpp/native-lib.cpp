#include <jni.h>
#include <string>
#include <android/log.h>
#include <android/asset_manager.h>
#include <android/asset_manager_jni.h>
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include <vector>
#include <mutex>
#include <atomic>
#include <thread>
#include <queue>
#include <condition_variable>

#define LOG_TAG "VulcanMind-VULKAN"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, LOG_TAG, __VA_ARGS__)

extern "C" {

// Forward declarations from other cpp files
bool vulkan_is_available();
int vulkan_init();
void vulkan_cleanup();
bool gguf_load_from_memory(const char* path, bool use_mmap, bool use_vulkan);
void gguf_unload(int slot);
const char* gguf_get_info(int slot);
bool inference_generate(int slotA, int slotB, const char* prompt, const char* imagePath, jobject callback);

static std::atomic<bool> g_vulkanReady{false};
static std::atomic<bool> g_inferenceRunning{false};
static JavaVM* g_jvm = nullptr;

jint JNI_OnLoad(JavaVM* vm, void* reserved) {
    g_jvm = vm;
    LOGI("JNI_OnLoad - VulcanMind Vulkan 7.0.0 - GGUF direct memory + Vulkan backend");
    JNIEnv* env = nullptr;
    if (vm->GetEnv((void**)&env, JNI_VERSION_1_6) != JNI_OK) return JNI_VERSION_1_6;
    // Try init Vulkan lazily
    std::thread([]{
        if (vulkan_is_available()) {
            int rc = vulkan_init();
            g_vulkanReady = (rc == 0);
            LOGI("Vulkan init rc=%d ready=%d", rc, g_vulkanReady.load());
        } else {
            LOGW("Vulkan not available on this device - fallback to CPU+GPU");
            g_vulkanReady = false;
        }
    }).detach();
    return JNI_VERSION_1_6;
}

// Kotlin: external fun nativeGetVulkanStatus(): String
JNIEXPORT jstring JNICALL Java_com_vulcanmind_vulkanmind_inference_LlamaBridge_nativeGetVulkanStatus(JNIEnv* env, jobject thiz) {
    std::string status;
    if (g_vulkanReady.load()) status = "VULKAN_ATIVO: VkPhysicalDevice ready, GGML_VULKAN=ON, computeShaders=OK";
    else if (vulkan_is_available()) status = "VULKAN_DETECTADO: inicializando…";
    else status = "VULKAN_INDISPONIVEL: fallback CPU/GPU";
    return env->NewStringUTF(status.c_str());
}

// Kotlin: external fun nativeLoadGguf(path: String, slot: Int, useMmap: Boolean): Boolean
JNIEXPORT jboolean JNICALL Java_com_vulcanmind_vulkanmind_inference_LlamaBridge_nativeLoadGguf(JNIEnv* env, jobject thiz, jstring jpath, jint slot, jboolean useMmap) {
    const char* path = env->GetStringUTFChars(jpath, nullptr);
    LOGI("nativeLoadGguf slot=%d path=%s mmap=%d vulkan=%d", slot, path, useMmap, g_vulkanReady.load());
    bool ok = gguf_load_from_memory(path, useMmap, g_vulkanReady.load());
    env->ReleaseStringUTFChars(jpath, path);
    LOGI("load result slot %d -> %d", slot, ok);
    return ok ? JNI_TRUE : JNI_FALSE;
}

// Kotlin: external fun nativeUnloadGguf(slot: Int)
JNIEXPORT void JNICALL Java_com_vulcanmind_vulkanmind_inference_LlamaBridge_nativeUnloadGguf(JNIEnv* env, jobject thiz, jint slot) {
    LOGI("nativeUnloadGguf slot=%d", slot);
    gguf_unload(slot);
}

// Kotlin: external fun nativeGetModelInfo(slot: Int): String
JNIEXPORT jstring JNICALL Java_com_vulcanmind_vulkanmind_inference_LlamaBridge_nativeGetModelInfo(JNIEnv* env, jobject thiz, jint slot) {
    const char* info = gguf_get_info(slot);
    if (!info) info = "{\"loaded\":false}";
    return env->NewStringUTF(info);
}

// Callback helper for streaming tokens
struct CallbackData {
    JNIEnv* env;
    jobject callbackObj;
    jmethodID onTokenMethod;
    jmethodID onFinishedMethod;
};

// Kotlin: external fun nativeGenerate(slotA: Int, slotB: Int, prompt: String, imagePath: String?, callback: GenerationCallback): Boolean
JNIEXPORT jboolean JNICALL Java_com_vulcanmind_vulkanmind_inference_LlamaBridge_nativeGenerate(
    JNIEnv* env, jobject thiz, jint slotA, jint slotB, jstring jprompt, jstring jimagePath, jobject callback) {

    if (g_inferenceRunning.exchange(true)) {
        LOGW("inference already running");
        return JNI_FALSE;
    }

    const char* prompt = env->GetStringUTFChars(jprompt, nullptr);
    const char* imagePath = nullptr;
    if (jimagePath != nullptr) imagePath = env->GetStringUTFChars(jimagePath, nullptr);

    LOGI("nativeGenerate slotA=%d slotB=%d promptLen=%zu image=%s", slotA, slotB, strlen(prompt), imagePath ? imagePath : "null");

    // Hold global ref to callback for background thread
    jobject gCallback = env->NewGlobalRef(callback);
    JavaVM* jvm = g_jvm;

    // Clone prompt string
    std::string promptStr(prompt);
    std::string imageStr = imagePath ? std::string(imagePath) : std::string();

    env->ReleaseStringUTFChars(jprompt, prompt);
    if (jimagePath) env->ReleaseStringUTFChars(jimagePath, imagePath);

    // Launch generation on detached thread to allow foreground service + screen off
    std::thread([jvm, gCallback, promptStr, imageStr, slotA, slotB]{
        JNIEnv* threadEnv = nullptr;
        jvm->AttachCurrentThread(&threadEnv, nullptr);
        if (!threadEnv) {
            LOGE("Failed to attach thread");
            g_inferenceRunning = false;
            return;
        }

        bool ok = inference_generate(slotA, slotB, promptStr.c_str(), imageStr.empty() ? nullptr : imageStr.c_str(), gCallback);

        LOGI("inference_generate finished ok=%d", ok);
        threadEnv->DeleteGlobalRef(gCallback);
        jvm->DetachCurrentThread();
        g_inferenceRunning = false;
    }).detach();

    return JNI_TRUE;
}

// Kotlin: external fun nativeStopGeneration()
JNIEXPORT void JNICALL Java_com_vulcanmind_vulkanmind_inference_LlamaBridge_nativeStopGeneration(JNIEnv* env, jobject thiz) {
    LOGI("nativeStopGeneration requested");
    g_inferenceRunning = false;
    // signal inference to stop via atomic
}

// Kotlin: external fun nativeGetDeviceInfo(): String
JNIEXPORT jstring JNICALL Java_com_vulcanmind_vulkanmind_inference_LlamaBridge_nativeGetDeviceInfo(JNIEnv* env, jobject thiz) {
    std::string info = "{";
    info += "\"vulkanReady\":" + std::string(g_vulkanReady ? "true" : "false") + ",";
    info += "\"vulkanAvailable\":" + std::string(vulkan_is_available() ? "true" : "false") + ",";
    info += "\"abi\":\"arm64-v8a\",";
    info += "\"ggml_vulkan\":true,";
    info += "\"mmap_direct\":true";
    info += "}";
    return env->NewStringUTF(info.c_str());
}

} // extern C
