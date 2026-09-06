#include <jni.h>
#include <android/log.h>
#include <string>
#include <vector>
#include <thread>
#include <chrono>
#include <atomic>

#define LOG_TAG "VulcanMind-Infer"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

extern bool vulkan_is_available();

// Simula geração streaming token a token
// Em build real, aqui chamaria llama.cpp: llama_model_load, llama_context, llama_decode, sampler, etc.

bool inference_generate(int slotA, int slotB, const char* prompt, const char* imagePath, jobject callback) {
    LOGI("inference_generate start slotA=%d slotB=%d prompt=%.100s image=%s", slotA, slotB, prompt, imagePath ? imagePath : "null");

    // Get JNIEnv from callback's VM? We need to fetch via JavaVM global stored in native-lib.cpp
    // For simplicity, we assume callback is Valid and we will call via JNI env passed from that thread's attachment
    // In native-lib.cpp thread we already attached, so we can get env via JavaVM->GetEnv
    extern JavaVM* g_jvm;
    JNIEnv* env = nullptr;
    g_jvm->GetEnv((void**)&env, JNI_VERSION_1_6);
    if (!env) {
        LOGE("env null in inference_generate");
        return false;
    }

    // Find callback methods
    jclass cbClass = env->GetObjectClass(callback);
    jmethodID onToken = env->GetMethodID(cbClass, "onToken", "(Ljava/lang/String;)V");
    jmethodID onFinished = env->GetMethodID(cbClass, "onFinished", "(Ljava/lang/String;)V");
    jmethodID onThinking = env->GetMethodID(cbClass, "onThinking", "(Ljava/lang/String;)V");

    if (!onToken || !onFinished) {
        LOGE("callback methods not found");
        return false;
    }

    // Simulate thinking phase if prompt contains <think> or thinking keyword
    std::string promptStr(prompt);
    bool useThinking = (promptStr.find("thinking") != std::string::npos || promptStr.find("<think>") != std::string::npos || promptStr.find("pense") != std::string::npos);

    if (useThinking && onThinking) {
        LOGI("Thinking mode enabled - generating chain-of-thought");
        std::vector<std::string> thinkingTokens = {
            "🤔 Analisando prompt com Vulkan acceleration...\n",
            "• Entendendo contexto e histórico do chat\n",
            "• Verificando se precisa pesquisa web\n",
            "• Planejando resposta estruturada\n",
            "• Validando coerência multimodal\n"
        };
        for (auto &t : thinkingTokens) {
            jstring jt = env->NewStringUTF(t.c_str());
            env->CallVoidMethod(callback, onThinking, jt);
            env->DeleteLocalRef(jt);
            std::this_thread::sleep_for(std::chrono::milliseconds(180));
        }
    }

    // Multimodal handling: se slotB carregado e imagePath != null, simula vision encoder
    bool multimodal = (slotB >= 0 && imagePath != nullptr);
    if (multimodal) {
        LOGI("Multimodal inference: vision GGUF slotB + LLM slotA, image=%s", imagePath);
        std::string visionMsg = "[👁️ Vision encoder Vulkan: imagem analisada, embeddings extraídos]";
        jstring jt = env->NewStringUTF(visionMsg.c_str());
        env->CallVoidMethod(callback, onToken, jt);
        env->DeleteLocalRef(jt);
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }

    // Simulate token generation streaming
    // Resposta fake mas convincente, em português, demonstrando Vulkan GGUF
    std::vector<std::string> tokens;
    if (promptStr.find("olá") != std::string::npos || promptStr.find("ola") != std::string::npos || promptStr.find("Olá") != std::string::npos) {
        tokens = {"Olá", "! ", "Sou ", "o ", "Vulcan", "Mind", " ", "rodando ", "GGUF ", "direto ", "da ", "memória ", "via ", "Vulkan", " 🚀\n\n",
                  "Como ", "posso ", "ajudar", " hoje", "?", " ", "Estou ", "com ", "acesso ", "a ", "pesquisa ", "web ", "e ", "modo ", "thinking", "."};
    } else if (multimodal) {
        tokens = {"Recebi", " sua ", "imagem", "! ", "Analisando ", "com ", "o ", "encoder ", "multimodal ", "GGUF ", "(slot ", "B) ", "via ", "Vulkan", "...\n\n",
                  "Vejo ", "conteúdo ", "interessante", " e ", "posso ", "descrever", " ou ", "responder ", "sobre ", "ela", ". ", "O ", "modelo ", "principal ", "(slot ", "A) ", "está ", "gerando ", "a ", "resposta ", "com ", "contexto ", "visual", "."};
    } else {
        tokens = {"Entendi", " sua ", "mensagem", ": \"", promptStr.substr(0, 60).c_str(), "\"\n\n",
                  "Gerando ", "resposta ", "com ", "GGUF ", "carregado ", "diretamente ", "na ", "memória ", "(mmap ", "zero-copy)", " e ", "acelerado ", "por ", "Vulkan ", "compute ", "shaders", ".\n\n",
                  "• ", "Thinking", ": ", "ativo", "\n",
                  "• ", "Pesquisa", ": ", "disponível", " se ", "necessário", "\n",
                  "• ", "Contexto", ": ", "preservado ", "por ", "chat", "\n\n",
                  "Posso ", "continuar ", "mesmo ", "com ", "a ", "tela ", "bloqueada ", "graças ", "ao ", "ForegroundService", " + ", "WakeLock", "."};
    }

    std::string full;
    for (auto &tok : tokens) {
        full += tok;
        jstring jt = env->NewStringUTF(tok.c_str());
        env->CallVoidMethod(callback, onToken, jt);
        env->DeleteLocalRef(jt);
        // Simular latência de inferência Vulkan acelerada (~30 tokens/s)
        std::this_thread::sleep_for(std::chrono::milliseconds(45));
        if (env->ExceptionCheck()) {
            env->ExceptionClear();
            LOGE("Exception during callback");
            break;
        }
    }

    // Final callback
    jstring jfull = env->NewStringUTF(full.c_str());
    env->CallVoidMethod(callback, onFinished, jfull);
    env->DeleteLocalRef(jfull);
    LOGI("inference_generate finished, total tokens %zu", tokens.size());
    return true;
}
