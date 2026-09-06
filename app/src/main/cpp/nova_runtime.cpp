#include <jni.h>
#include <android/log.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <cctype>
#include <mutex>
#include <string>
#include <vector>

#include "llama.h"
#include "mtmd.h"
#include "mtmd-helper.h"

#if __has_include(<vulkan/vulkan.h>)
#include <vulkan/vulkan.h>
#endif

#define NOVA_LOG_TAG "NovaLocal"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, NOVA_LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, NOVA_LOG_TAG, __VA_ARGS__)

namespace {

std::once_flag g_backend_once;
std::atomic<bool> g_vulkan_available{false};
std::string g_vulkan_api = "";

void initialize_backend() {
    llama_backend_init();
}

struct MappedFile {
    int fd = -1;
    const uint8_t * data = nullptr;
    size_t size = 0;

    bool open(int source_fd, size_t hinted_size) {
        fd = dup(source_fd);
        if (fd < 0) return false;
        struct stat st{};
        if (fstat(fd, &st) == 0 && st.st_size > 0) size = static_cast<size_t>(st.st_size);
        if (size == 0) size = hinted_size;
        if (size < 32) return false;
        void *mapped = mmap(nullptr, size, PROT_READ, MAP_PRIVATE, fd, 0);
        if (mapped == MAP_FAILED) {
            data = nullptr;
            return false;
        }
        data = static_cast<const uint8_t *>(mapped);
        return true;
    }

    void close() {
        if (data != nullptr) munmap(const_cast<uint8_t *>(data), size);
        data = nullptr;
        if (fd >= 0) ::close(fd);
        fd = -1;
        size = 0;
    }

    ~MappedFile() { close(); }
};

struct Cursor {
    const uint8_t *p;
    const uint8_t *end;

    bool bytes(size_t n) const { return n <= static_cast<size_t>(end - p); }
    bool readU8(uint8_t &v) {
        if (!bytes(1)) return false;
        v = *p++;
        return true;
    }
    bool readU32(uint32_t &v) {
        if (!bytes(4)) return false;
        v = static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8)
                | (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
        p += 4;
        return true;
    }
    bool readU64(uint64_t &v) {
        if (!bytes(8)) return false;
        v = 0;
        for (int i = 0; i < 8; ++i) v |= static_cast<uint64_t>(p[i]) << (8 * i);
        p += 8;
        return true;
    }
    bool skip(size_t n) {
        if (!bytes(n)) return false;
        p += n;
        return true;
    }
    bool stringValue(std::string &out) {
        uint64_t length = 0;
        if (!readU64(length) || length > 1024 * 1024 || !bytes(static_cast<size_t>(length))) return false;
        out.assign(reinterpret_cast<const char *>(p), static_cast<size_t>(length));
        p += length;
        return true;
    }
};

// GGUF value type IDs. We only need strings to make the model shelf useful,
// but skipping every standard type lets us inspect files without loading weights.
static bool skipValueSafe(Cursor &cursor, uint32_t type, int depth = 0) {
    if (depth > 12) return false;
    uint64_t n;
    uint32_t child;
    switch (type) {
        case 0: case 1: case 7: return cursor.skip(1);
        case 2: case 3: return cursor.skip(2);
        case 4: case 5: case 6: return cursor.skip(4);
        case 8: {
            std::string ignored;
            return cursor.stringValue(ignored);
        }
        case 10: case 11: case 12: return cursor.skip(8);
        case 9:
            if (!cursor.readU32(child) || !cursor.readU64(n) || n > 100000000ULL) return false;
            for (uint64_t i = 0; i < n; ++i) if (!skipValueSafe(cursor, child, depth + 1)) return false;
            return true;
        default: return false;
    }
}

static std::string jsonEscape(const std::string &value) {
    std::string result;
    result.reserve(value.size() + 8);
    for (char c : value) {
        switch (c) {
            case '\\': result += "\\\\"; break;
            case '"': result += "\\\""; break;
            case '\n': result += "\\n"; break;
            case '\r': result += "\\r"; break;
            case '\t': result += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) >= 32) result += c;
                break;
        }
    }
    return result;
}

struct GgufSummary {
    bool valid = false;
    uint32_t version = 0;
    uint64_t tensorCount = 0;
    uint64_t kvCount = 0;
    std::string name;
    std::string arch;
    bool vision = false;
    bool projector = false;
};

static GgufSummary inspectGguf(const MappedFile &file) {
    GgufSummary summary;
    if (file.data == nullptr || file.size < 24 || std::memcmp(file.data, "GGUF", 4) != 0) return summary;
    Cursor cursor{file.data + 4, file.data + file.size};
    if (!cursor.readU32(summary.version) || summary.version < 1 || summary.version > 3
            || !cursor.readU64(summary.tensorCount) || !cursor.readU64(summary.kvCount)
            || summary.kvCount > 1000000ULL) return summary;
    summary.valid = true;
    for (uint64_t i = 0; i < summary.kvCount; ++i) {
        std::string key;
        uint32_t type = 0;
        if (!cursor.stringValue(key) || !cursor.readU32(type)) { summary.valid = false; break; }
        if (type == 8 && (key == "general.name" || key == "general.basename"
                || key == "general.architecture" || key == "general.type")) {
            std::string value;
            if (!cursor.stringValue(value)) { summary.valid = false; break; }
            if (key == "general.name" || (summary.name.empty() && key == "general.basename")) summary.name = value;
            if (key == "general.architecture") summary.arch = value;
            std::string lower = value;
            std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            if (lower.find("vision") != std::string::npos || lower.find("vl") != std::string::npos
                    || lower.find("llava") != std::string::npos || lower.find("gemma3") != std::string::npos
                    || lower.find("minicpm") != std::string::npos || lower.find("internvl") != std::string::npos
                    || lower.find("clip") != std::string::npos) summary.vision = true;
            if (lower.find("mmproj") != std::string::npos || lower.find("projector") != std::string::npos
                    || lower.find("clip") != std::string::npos) summary.projector = true;
        } else if (!skipValueSafe(cursor, type)) {
            summary.valid = false;
            break;
        }
        std::string lowerKey = key;
        std::transform(lowerKey.begin(), lowerKey.end(), lowerKey.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (lowerKey.find("clip") != std::string::npos || lowerKey.find("vision") != std::string::npos
                || lowerKey.find("mmproj") != std::string::npos || lowerKey.find("projector") != std::string::npos) {
            summary.vision = true;
            if (lowerKey.find("mmproj") != std::string::npos || lowerKey.find("projector") != std::string::npos) summary.projector = true;
        }
    }
    return summary;
}

static void detectVulkan() {
    void *library = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
    if (library == nullptr) return;
#if defined(VK_VERSION_1_0)
    auto getProc = reinterpret_cast<PFN_vkGetInstanceProcAddr>(dlsym(library, "vkGetInstanceProcAddr"));
    if (getProc != nullptr) {
        auto enumerate = reinterpret_cast<PFN_vkEnumerateInstanceVersion>(getProc(nullptr, "vkEnumerateInstanceVersion"));
        uint32_t version = VK_API_VERSION_1_0;
        if (enumerate != nullptr) enumerate(&version);
        if (version >= VK_API_VERSION_1_0) {
            g_vulkan_available.store(true);
            g_vulkan_api = std::to_string(VK_VERSION_MAJOR(version)) + "."
                    + std::to_string(VK_VERSION_MINOR(version));
        }
    }
#else
    g_vulkan_available.store(true);
    g_vulkan_api = "1.0";
#endif
    // Keep the loader resident for ggml's Vulkan backend.
    (void) library;
}

struct RuntimeModel {
    int modelFd = -1;
    int projectorFd = -1;
    MappedFile mapped;
    llama_model *model = nullptr;
    llama_context *context = nullptr;
    mtmd_context *vision = nullptr;
    std::atomic<bool> cancel{false};
    bool usingGpu = false;
    int nBatch = 512;

    ~RuntimeModel() {
        if (vision != nullptr) mtmd_free(vision);
        if (context != nullptr) llama_free(context);
        if (model != nullptr) llama_model_free(model);
        if (modelFd >= 0) ::close(modelFd);
        if (projectorFd >= 0) ::close(projectorFd);
    }
};

static int duplicateForPath(int source) {
    int fd = dup(source);
    if (fd >= 0) fcntl(fd, F_SETFD, FD_CLOEXEC);
    return fd;
}

static std::string procPath(int fd) {
    return std::string("/proc/self/fd/") + std::to_string(fd);
}

static bool tokenize(const llama_vocab *vocab, const std::string &prompt,
                     std::vector<llama_token> &tokens, int32_t maxTokens) {
    int32_t capacity = std::max<int32_t>(256, static_cast<int32_t>(prompt.size() * 2 + 16));
    tokens.resize(static_cast<size_t>(capacity));
    int32_t count = llama_tokenize(vocab, prompt.c_str(), static_cast<int32_t>(prompt.size()),
                                   tokens.data(), capacity, true, true);
    if (count < 0) {
        tokens.resize(static_cast<size_t>(-count));
        count = llama_tokenize(vocab, prompt.c_str(), static_cast<int32_t>(prompt.size()),
                               tokens.data(), -count, true, true);
    }
    if (count <= 0) return false;
    tokens.resize(static_cast<size_t>(count));
    if (maxTokens > 0 && static_cast<int32_t>(tokens.size()) > maxTokens) {
        tokens.erase(tokens.begin(), tokens.end() - maxTokens);
    }
    return true;
}

static void setBatchToken(llama_batch &batch, int index, llama_token token,
                          llama_pos position, bool logits) {
    batch.token[index] = token;
    batch.pos[index] = position;
    batch.n_seq_id[index] = 1;
    batch.seq_id[index][0] = 0;
    batch.logits[index] = logits ? 1 : 0;
}

static bool decodePrompt(RuntimeModel *runtime, const std::vector<llama_token> &tokens, llama_pos &position) {
    llama_batch batch = llama_batch_init(runtime->nBatch, 0, 1);
    if (batch.token == nullptr) return false;
    bool success = true;
    size_t offset = 0;
    while (offset < tokens.size() && !runtime->cancel.load()) {
        int count = static_cast<int>(std::min<size_t>(runtime->nBatch, tokens.size() - offset));
        batch.n_tokens = count;
        for (int i = 0; i < count; ++i) {
            bool last = offset + static_cast<size_t>(i) + 1 == tokens.size();
            setBatchToken(batch, i, tokens[offset + static_cast<size_t>(i)],
                          static_cast<llama_pos>(offset + static_cast<size_t>(i)), last);
        }
        if (llama_decode(runtime->context, batch) != 0) { success = false; break; }
        offset += static_cast<size_t>(count);
    }
    position = static_cast<llama_pos>(tokens.size());
    llama_batch_free(batch);
    return success && !runtime->cancel.load();
}

static std::string generateFromLastLogits(RuntimeModel *runtime, llama_pos position,
                                           int maxTokens, float temperature) {
    llama_sampler_chain_params samplerParams = llama_sampler_chain_default_params();
    llama_sampler *sampler = llama_sampler_chain_init(samplerParams);
    if (sampler == nullptr) return "";
    llama_sampler_chain_add(sampler, llama_sampler_init_top_k(40));
    llama_sampler_chain_add(sampler, llama_sampler_init_top_p(0.92f, 1));
    llama_sampler_chain_add(sampler, llama_sampler_init_temp(std::max(0.05f, temperature)));
    llama_sampler_chain_add(sampler, llama_sampler_init_dist(LLAMA_DEFAULT_SEED));

    llama_batch batch = llama_batch_init(1, 0, 1);
    std::string answer;
    answer.reserve(static_cast<size_t>(maxTokens) * 4);
    bool success = true;
    for (int step = 0; step < maxTokens && !runtime->cancel.load(); ++step) {
        llama_token token = llama_sampler_sample(sampler, runtime->context, -1);
        llama_sampler_accept(sampler, token);
        const llama_vocab *vocab = llama_model_get_vocab(runtime->model);
        if (llama_vocab_is_eog(vocab, token)) break;
        char piece[512];
        int count = llama_token_to_piece(vocab, token, piece, sizeof(piece), 0, false);
        if (count > 0) answer.append(piece, static_cast<size_t>(count));
        else if (count < 0) {
            std::vector<char> larger(static_cast<size_t>(-count));
            int retry = llama_token_to_piece(vocab, token, larger.data(), -count, 0, false);
            if (retry > 0) answer.append(larger.data(), static_cast<size_t>(retry));
        }
        batch.n_tokens = 1;
        setBatchToken(batch, 0, token, position++, true);
        if (llama_decode(runtime->context, batch) != 0) { success = false; break; }
    }
    llama_batch_free(batch);
    llama_sampler_free(sampler);
    if (!success) return "";
    return answer;
}

static std::string generateText(RuntimeModel *runtime, const std::string &prompt,
                                int maxTokens, float temperature) {
    llama_memory_clear(llama_get_memory(runtime->context), true);
    const llama_vocab *vocab = llama_model_get_vocab(runtime->model);
    std::vector<llama_token> tokens;
    uint32_t contextSize = llama_n_ctx(runtime->context);
    int32_t available = static_cast<int32_t>(contextSize > static_cast<uint32_t>(maxTokens + 16)
            ? contextSize - static_cast<uint32_t>(maxTokens + 16) : 256);
    if (!tokenize(vocab, prompt, tokens, available)) return "";
    llama_pos position = 0;
    if (!decodePrompt(runtime, tokens, position)) return "";
    return generateFromLastLogits(runtime, position, maxTokens, temperature);
}

static std::string generateImage(RuntimeModel *runtime, const std::string &prompt,
                                 int maxTokens, float temperature,
                                 const uint8_t *rgb, int width, int height) {
    if (runtime->vision == nullptr || rgb == nullptr || width <= 0 || height <= 0) return "";
    llama_memory_clear(llama_get_memory(runtime->context), true);
    mtmd_bitmap *bitmap = mtmd_bitmap_init(static_cast<uint32_t>(width), static_cast<uint32_t>(height), rgb);
    mtmd_input_chunks *chunks = mtmd_input_chunks_init();
    if (bitmap == nullptr || chunks == nullptr) {
        if (bitmap != nullptr) mtmd_bitmap_free(bitmap);
        if (chunks != nullptr) mtmd_input_chunks_free(chunks);
        return "";
    }
    mtmd_input_text inputText{prompt.c_str(), prompt.size(), true, true};
    const mtmd_bitmap *bitmaps[1] = {bitmap};
    int result = mtmd_tokenize(runtime->vision, chunks, &inputText, bitmaps, 1);
    mtmd_bitmap_free(bitmap);
    if (result != 0) {
        mtmd_input_chunks_free(chunks);
        return "";
    }

    llama_pos position = 0;
    size_t count = mtmd_input_chunks_size(chunks);
    bool success = true;
    for (size_t i = 0; i < count && !runtime->cancel.load(); ++i) {
        const mtmd_input_chunk *chunk = mtmd_input_chunks_get(chunks, i);
        auto type = mtmd_input_chunk_get_type(chunk);
        llama_pos next = position;
        if (type == MTMD_INPUT_CHUNK_TYPE_TEXT) {
            result = mtmd_helper_eval_chunk_single(runtime->vision, runtime->context, chunk,
                    position, 0, runtime->nBatch, i + 1 == count, &next);
        } else {
            mtmd_batch *batch = mtmd_batch_init(runtime->vision);
            if (batch == nullptr || mtmd_batch_add_chunk(batch, chunk) != 0
                    || mtmd_batch_encode(batch) != 0) {
                if (batch != nullptr) mtmd_batch_free(batch);
                success = false;
                break;
            }
            float *embedding = mtmd_batch_get_output_embd(batch, chunk);
            result = embedding == nullptr ? 1 : mtmd_helper_decode_image_chunk(runtime->vision,
                    runtime->context, chunk, embedding, position, 0, runtime->nBatch, &next, nullptr, nullptr);
            mtmd_batch_free(batch);
        }
        if (result != 0) { success = false; break; }
        position = next;
    }
    mtmd_input_chunks_free(chunks);
    if (!success || runtime->cancel.load()) return "";
    return generateFromLastLogits(runtime, position, maxTokens, temperature);
}

static RuntimeModel *fromHandle(jlong handle) {
    return reinterpret_cast<RuntimeModel *>(handle);
}

static jstring makeString(JNIEnv *env, const std::string &value) {
    return env->NewStringUTF(value.c_str());
}

} // namespace

extern "C" JNIEXPORT jstring JNICALL
Java_com_nova_local_NativeRuntime_nativeProbe(JNIEnv *env, jclass, jint fd, jlong size) {
    MappedFile file;
    if (!file.open(fd, static_cast<size_t>(std::max<jlong>(0, size)))) {
        return makeString(env, "{\"ok\":false,\"reason\":\"mmap failed\"}");
    }
    GgufSummary summary = inspectGguf(file);
    if (!summary.valid) return makeString(env, "{\"ok\":false,\"reason\":\"arquivo GGUF inválido\"}");
    std::string json = "{\"ok\":true,\"version\":" + std::to_string(summary.version)
            + ",\"tensors\":" + std::to_string(summary.tensorCount)
            + ",\"kv\":" + std::to_string(summary.kvCount)
            + ",\"name\":\"" + jsonEscape(summary.name)
            + "\",\"arch\":\"" + jsonEscape(summary.arch)
            + "\",\"vision\":" + (summary.vision ? "true" : "false")
            + ",\"projector\":" + (summary.projector ? "true" : "false") + "}";
    return makeString(env, json);
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_nova_local_NativeRuntime_nativeLoad(JNIEnv *, jclass, jint modelFd, jlong modelSize,
                                              jint projectorFd, jboolean preferVulkan) {
    std::call_once(g_backend_once, [] {
        detectVulkan();
        initialize_backend();
    });
    auto *runtime = new RuntimeModel();
    if (!runtime->mapped.open(modelFd, static_cast<size_t>(std::max<jlong>(0, modelSize)))) {
        delete runtime;
        return 0;
    }
    GgufSummary summary = inspectGguf(runtime->mapped);
    if (!summary.valid) { delete runtime; return 0; }
    runtime->usingGpu = preferVulkan && g_vulkan_available.load();
    runtime->modelFd = duplicateForPath(modelFd);
    if (runtime->modelFd < 0) { delete runtime; return 0; }

    llama_model_params modelParams = llama_model_default_params();
    modelParams.n_gpu_layers = runtime->usingGpu ? -1 : 0;
    std::string modelPath = procPath(runtime->modelFd);
    runtime->model = llama_model_load_from_file(modelPath.c_str(), modelParams);
    if (runtime->model == nullptr) { delete runtime; return 0; }

    int threads = std::max(2, std::min(8, static_cast<int>(sysconf(_SC_NPROCESSORS_ONLN)) - 1));
    if (projectorFd >= 0) {
        runtime->projectorFd = duplicateForPath(projectorFd);
        if (runtime->projectorFd >= 0) {
            mtmd_context_params visionParams = mtmd_context_params_default();
            visionParams.use_gpu = runtime->usingGpu;
            visionParams.n_threads = threads;
            visionParams.warmup = false;
            runtime->vision = mtmd_init_from_file(procPath(runtime->projectorFd).c_str(),
                                                  runtime->model, visionParams);
            if (runtime->vision == nullptr) {
                ::close(runtime->projectorFd);
                runtime->projectorFd = -1;
            }
        }
    }

    llama_context_params contextParams = llama_context_default_params();
    int trained = llama_model_n_ctx_train(runtime->model);
    contextParams.n_ctx = trained > 0 ? static_cast<uint32_t>(std::min(trained, 4096)) : 4096;
    contextParams.n_batch = runtime->nBatch;
    contextParams.n_ubatch = std::min(256, runtime->nBatch);
    contextParams.n_threads = threads;
    contextParams.n_threads_batch = threads;
    contextParams.offload_kqv = runtime->usingGpu;
    contextParams.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_AUTO;
    runtime->context = llama_init_from_model(runtime->model, contextParams);
    if (runtime->context == nullptr) { delete runtime; return 0; }
    LOGI("loaded GGUF; backend=%s vision=%s", runtime->usingGpu ? "Vulkan" : "CPU",
         runtime->vision == nullptr ? "no" : "yes");
    return reinterpret_cast<jlong>(runtime);
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_nova_local_NativeRuntime_nativeModelInfo(JNIEnv *env, jclass, jlong handle) {
    RuntimeModel *runtime = fromHandle(handle);
    if (runtime == nullptr || runtime->model == nullptr) return makeString(env, "{}");
    char description[256] = {};
    llama_model_desc(runtime->model, description, sizeof(description));
    std::string json = "{\"description\":\"" + jsonEscape(description)
            + "\",\"size\":" + std::to_string(llama_model_size(runtime->model))
            + ",\"params\":" + std::to_string(llama_model_n_params(runtime->model))
            + ",\"layers\":" + std::to_string(llama_model_n_layer(runtime->model))
            + ",\"context\":" + std::to_string(llama_n_ctx(runtime->context))
            + ",\"backend\":\"" + std::string(runtime->usingGpu ? "Vulkan" : "CPU")
            + "\",\"vision\":" + std::string(runtime->vision == nullptr ? "false" : "true") + "}";
    return makeString(env, json);
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_nova_local_NativeRuntime_nativeGenerate(JNIEnv *env, jclass, jlong handle,
                                                  jstring prompt, jint maxTokens, jfloat temperature) {
    RuntimeModel *runtime = fromHandle(handle);
    if (runtime == nullptr || runtime->context == nullptr || prompt == nullptr) return makeString(env, "");
    const char *text = env->GetStringUTFChars(prompt, nullptr);
    runtime->cancel.store(false);
    std::string answer = generateText(runtime, text == nullptr ? "" : text,
                                      std::max(1, static_cast<int>(maxTokens)), temperature);
    if (text != nullptr) env->ReleaseStringUTFChars(prompt, text);
    return makeString(env, answer);
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_nova_local_NativeRuntime_nativeGenerateWithImage(JNIEnv *env, jclass, jlong handle,
                                                           jstring prompt, jint maxTokens,
                                                           jfloat temperature, jbyteArray rgb,
                                                           jint width, jint height) {
    RuntimeModel *runtime = fromHandle(handle);
    if (runtime == nullptr || runtime->context == nullptr || prompt == nullptr || rgb == nullptr) return makeString(env, "");
    jsize length = env->GetArrayLength(rgb);
    if (length <= 0 || length < width * height * 3) return makeString(env, "");
    std::vector<uint8_t> pixels(static_cast<size_t>(length));
    env->GetByteArrayRegion(rgb, 0, length, reinterpret_cast<jbyte *>(pixels.data()));
    const char *text = env->GetStringUTFChars(prompt, nullptr);
    runtime->cancel.store(false);
    std::string answer = generateImage(runtime, text == nullptr ? "" : text,
                                       std::max(1, static_cast<int>(maxTokens)), temperature,
                                       pixels.data(), width, height);
    if (text != nullptr) env->ReleaseStringUTFChars(prompt, text);
    return makeString(env, answer);
}

extern "C" JNIEXPORT void JNICALL
Java_com_nova_local_NativeRuntime_nativeCancel(JNIEnv *, jclass, jlong handle) {
    RuntimeModel *runtime = fromHandle(handle);
    if (runtime != nullptr) runtime->cancel.store(true);
}

extern "C" JNIEXPORT void JNICALL
Java_com_nova_local_NativeRuntime_nativeRelease(JNIEnv *, jclass, jlong handle) {
    delete fromHandle(handle);
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_nova_local_NativeRuntime_nativeVulkanStatus(JNIEnv *env, jclass) {
    std::call_once(g_backend_once, [] {
        detectVulkan();
        initialize_backend();
    });
    std::string json = "{\"available\":" + std::string(g_vulkan_available.load() ? "true" : "false")
            + ",\"api\":\"" + jsonEscape(g_vulkan_api)
            + "\",\"backend\":\"" + std::string(g_vulkan_available.load() ? "ggml-vulkan" : "CPU") + "\"}";
    return makeString(env, json);
}
