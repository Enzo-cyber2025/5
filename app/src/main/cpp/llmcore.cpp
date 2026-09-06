// llmcore.cpp — Engine nativo GGUF Chat (llama.cpp v0.4.0 + mtmd + Vulkan)
//
// Arquitetura:
//   * backends CPU + Vulkan via ggml; enumeração de dispositivos
//   * probe de GGUF (metadados) sem alocar pesos
//   * modelos de texto (GGUF) + projetores multimodais (mmproj/mtmd)
//   * sessões de chat: histórico + KV cache incremental (texto puro)
//   * turnos com imagem: re-decode completo via mtmd (mesma mecânica do mtmd-cli)
//   * geração assíncrona e cancelável (funciona com a tela bloqueada)
//   * eventos JSON para o Kotlin correlacionados por "token" do pedido

#include <jni.h>
#include <android/log.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <exception>
#include <filesystem>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "llama.h"
#include "ggml.h"
#include "ggml-backend.h"
#include "gguf.h"
#include "common.h"
#include "chat.h"
#include "sampling.h"
#include "mtmd.h"
#include "mtmd-helper.h"
#include "json.hpp"

#define LOG_TAG "GGUFChat"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, LOG_TAG, __VA_ARGS__)

using json = nlohmann::json;

// ---------------------------------------------------------------------------
// JNI helpers
// ---------------------------------------------------------------------------

static JavaVM * g_vm = nullptr;

static std::string jstr(JNIEnv * env, jstring s) {
    if (!s) return {};
    const char * p = env->GetStringUTFChars(s, nullptr);
    if (!p) return {};
    std::string out(p);
    env->ReleaseStringUTFChars(s, p);
    return out;
}

static jstring newJStr(JNIEnv * env, const std::string & s) {
    return env->NewStringUTF(s.c_str());
}

struct ThreadAttach {
    JNIEnv * env = nullptr;
    bool attached = false;
    explicit ThreadAttach() {
        if (!g_vm) return;
        jint rc = g_vm->GetEnv((void **) &env, JNI_VERSION_1_6);
        if (rc == JNI_EDETACHED) {
            JavaVMAttachArgs args{JNI_VERSION_1_6, nullptr, nullptr};
            if (g_vm->AttachCurrentThread(&env, &args) == JNI_OK) attached = true;
        }
    }
    ~ThreadAttach() {
        if (attached && g_vm) g_vm->DetachCurrentThread();
    }
};

static jclass    g_bridgeClass   = nullptr;
static jfieldID  g_listenerField = nullptr;
static jmethodID g_onEventMethod = nullptr;

static void emitEvent(const std::string & jsonStr) {
    if (!g_vm) return;
    ThreadAttach ta;
    JNIEnv * env = ta.env;
    if (!env || !g_bridgeClass || !g_listenerField || !g_onEventMethod) return;
    jobject listener = env->GetStaticObjectField(g_bridgeClass, g_listenerField);
    if (!listener) return;
    jstring s = newJStr(env, jsonStr);
    env->CallVoidMethod(listener, g_onEventMethod, s);
    env->DeleteLocalRef(s);
    env->DeleteLocalRef(listener);
    if (env->ExceptionCheck()) env->ExceptionClear();
}

static void ggmlLogCb(enum ggml_log_level level, const char * text, void *) {
    if (!text) return;
    if (level == GGML_LOG_LEVEL_ERROR) __android_log_write(ANDROID_LOG_ERROR, "ggml", text);
    else if (level == GGML_LOG_LEVEL_WARN) __android_log_write(ANDROID_LOG_WARN, "ggml", text);
    else __android_log_write(ANDROID_LOG_INFO, "ggml", text);
}

// ---------------------------------------------------------------------------
// Estado
// ---------------------------------------------------------------------------

namespace engine {

struct ModelRec {
    uint64_t id = 0;
    std::string path;
    bool useGpu = false;
    llama_model * m = nullptr;
    llama_vocab * vocab = nullptr;
};

struct HistMsg {
    std::string role;
    std::string content;                 // conteúdo (com marcadores de mídia p/ msgs de imagem)
    std::vector<std::string> images;     // caminhos das imagens (ordem dos marcadores)
};

struct CacheEnt {
    bool isImg = false;
    llama_token tok = -1;
    uint32_t npos = 0;
};

struct SessionRec {
    uint64_t id = 0;
    ModelRec * model = nullptr;
    llama_context * lctx = nullptr;
    llama_memory_t memory = nullptr;
    mtmd_context * mctx = nullptr;
    bool visionReady = false;

    common_sampler * smpl = nullptr;
    common_chat_templates_ptr tmpls;
    bool useJinja = true;

    uint32_t nCtx = 8192;
    int32_t nBatch = 512;
    int32_t threads = 4;

    std::vector<HistMsg> history;
    std::vector<CacheEnt> cache;
    int64_t posAcc = 0;      // posições ocupadas no KV
    std::string marker = "<__media__>";

    std::atomic<bool> stopFlag{false};
    std::atomic<bool> busy{false};
    std::thread worker;
};

struct Global {
    std::mutex mtx;
    std::map<uint64_t, std::unique_ptr<ModelRec>> models;
    std::map<uint64_t, std::unique_ptr<SessionRec>> sessions;
    uint64_t nextId = 1;
    bool inited = false;
    bool vulkanOk = false;
    ggml_backend_dev_t gpuDev = nullptr;
    uint64_t gpuTotal = 0, gpuFree = 0;
    std::string gpuName;
};

Global g;

uint64_t allocId() {
    std::lock_guard<std::mutex> lk(g.mtx);
    return g.nextId++;
}

SessionRec * getSession(uint64_t id) {
    std::lock_guard<std::mutex> lk(g.mtx);
    auto it = g.sessions.find(id);
    return it == g.sessions.end() ? nullptr : it->second.get();
}

ModelRec * getModel(uint64_t id) {
    std::lock_guard<std::mutex> lk(g.mtx);
    auto it = g.models.find(id);
    return it == g.models.end() ? nullptr : it->second.get();
}

bool fileExists(const std::string & p) {
    std::error_code ec;
    return std::filesystem::is_regular_file(p, ec);
}

void initDevices() {
    g.gpuDev = ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_GPU);
    g.vulkanOk = g.gpuDev != nullptr;
    if (g.gpuDev) {
        ggml_backend_dev_props props{};
        ggml_backend_dev_get_props(g.gpuDev, &props);
        g.gpuName = props.name ? props.name : "GPU";
        size_t freeMem = 0, totalMem = 0;
        ggml_backend_dev_memory(g.gpuDev, &freeMem, &totalMem);
        g.gpuTotal = totalMem;
        g.gpuFree = freeMem;
    }
}

void evBase(json & j, uint64_t token) {
    j["token"] = token;
}

void emitError(uint64_t token, const std::string & code, const std::string & msg) {
    json j{{"e", "error"}, {"code", code}, {"message", msg}};
    evBase(j, token);
    emitEvent(j.dump());
}

void emitDone(uint64_t token, const std::string & text, const std::string & reason,
              int64_t nTok, double tps) {
    json j{{"e", "done"}, {"text", text}, {"reason", reason}, {"n", nTok}, {"tps", tps}};
    evBase(j, token);
    emitEvent(j.dump());
}

void emitNote(uint64_t token, const std::string & code) {
    json j{{"e", "note"}, {"code", code}};
    evBase(j, token);
    emitEvent(j.dump());
}

// ---------------------------------------------------------------------------
// Probe GGUF
// ---------------------------------------------------------------------------

json probeFile(const std::string & path) {
    json out{{"ok", false}};
    gguf_init_params iparams{true, nullptr};
    gguf_context * gctx = gguf_init_from_file(path.c_str(), iparams);
    if (!gctx) {
        out["error"] = "Não foi possível ler o arquivo (GGUF inválido?)";
        return out;
    }
    std::string arch, name, desc;
    int64_t nLayer = -1, ftype = -1;
    bool hasTokenizer = false;
    int64_t nKV = gguf_get_n_kv(gctx);
    for (int64_t i = 0; i < nKV; i++) {
        const char * key = gguf_get_key(gctx, i);
        if (!key) continue;
        std::string k(key);
        enum gguf_type t = gguf_get_kv_type(gctx, i);
        if (k == "general.architecture" && t == GGUF_TYPE_STRING) arch = gguf_get_val_str(gctx, i);
        else if (k == "general.name" && t == GGUF_TYPE_STRING) name = gguf_get_val_str(gctx, i);
        else if (k == "general.description" && t == GGUF_TYPE_STRING) desc = gguf_get_val_str(gctx, i);
        else if (k == "llama.block_count" && t == GGUF_TYPE_UINT32) nLayer = (int64_t) gguf_get_val_u32(gctx, i);
        else if (k == "general.file_type" && t == GGUF_TYPE_UINT32) ftype = (int64_t) gguf_get_val_u32(gctx, i);
        else if (k == "tokenizer.ggml.model" && t == GGUF_TYPE_STRING) hasTokenizer = true;
    }
    uint64_t size = 0;
    try { std::error_code ec; size = (uint64_t) std::filesystem::file_size(path, ec); } catch (...) {}
    gguf_free(gctx);
    if (arch.empty()) {
        out["error"] = "GGUF sem arquitetura identificada";
        return out;
    }
    out["ok"] = true;
    out["arch"] = arch;
    out["name"] = name.empty() ? arch : name;
    out["desc"] = desc;
    out["layers"] = nLayer;
    out["ftype"] = ftype;
    out["size"] = size;
    out["is_llm"] = hasTokenizer; // LLMs têm tokenizador; mmproj geralmente não
    return out;
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

std::vector<common_chat_msg> toCommonMsgs(const std::vector<HistMsg> & hist) {
    std::vector<common_chat_msg> out;
    out.reserve(hist.size());
    for (const auto & h : hist) {
        common_chat_msg m;
        m.role = h.role;
        m.content = h.content;
        out.push_back(std::move(m));
    }
    return out;
}

bool decodePromptTokens(SessionRec * s, const std::vector<llama_token> & toks,
                        int64_t startPos, bool logitsLast, int64_t * outEndPos) {
    const size_t n = toks.size();
    int64_t pos = startPos;
    for (size_t i = 0; i < n; i += (size_t) s->nBatch) {
        if (s->stopFlag.load()) return false;
        size_t chunk = std::min<size_t>((size_t) s->nBatch, n - i);
        llama_batch b = llama_batch_init((int32_t) chunk, 0, 1);
        if (b.token == nullptr) return false;
        for (size_t j = 0; j < chunk; j++) {
            b.token[j] = toks[i + j];
            b.pos[j] = (llama_pos) (pos + (int64_t) j);
            b.n_seq_id[j] = 1;
            b.seq_id[j][0] = 0;
            b.logits[j] = (logitsLast && i + j == n - 1) ? 1 : 0;
        }
        b.n_tokens = (int32_t) chunk;
        int rc = llama_decode(s->lctx, b);
        llama_batch_free(b);
        if (rc < 0) return false;
        pos += (int64_t) chunk;
    }
    if (outEndPos) *outEndPos = pos;
    return true;
}

void resetMemory(SessionRec * s) {
    if (s->memory) llama_memory_clear(s->memory, true);
    s->cache.clear();
    s->posAcc = 0;
}

void cacheAppendToken(SessionRec * s, llama_token t) {
    CacheEnt e;
    e.tok = t;
    s->cache.push_back(e);
}

void cacheAppendTokens(SessionRec * s, const std::vector<llama_token> & toks, size_t from) {
    for (size_t i = from; i < toks.size(); i++) cacheAppendToken(s, toks[i]);
}

void cacheAppendImage(SessionRec * s, uint32_t npos) {
    CacheEnt e;
    e.isImg = true;
    e.npos = npos;
    s->cache.push_back(e);
}

int64_t cacheCovered(SessionRec * s, const std::vector<llama_token> & candidate) {
    size_t ci = 0, ti = 0;
    while (ci < s->cache.size() && ti < candidate.size()) {
        const CacheEnt & e = s->cache[ci];
        if (e.isImg) { ci++; continue; }
        if (e.tok != candidate[ti]) break;
        ci++; ti++;
    }
    return (int64_t) ti;
}

size_t countMarkers(SessionRec * s, const std::string & text) {
    size_t n = 0, pos = 0;
    while ((pos = text.find(s->marker, pos)) != std::string::npos) {
        n++;
        pos += s->marker.size();
    }
    return n;
}

size_t countHistoryImages(const SessionRec * s) {
    size_t n = 0;
    for (const auto & h : s->history) n += h.images.size();
    return n;
}

// Rota mtmd: formata o histórico (com conteúdos marcados), re-decodifica TUDO
// a partir da posição 0 — igual ao mtmd-cli. bitmaps = imagens do histórico +
// imagens do turno atual, na ordem em que os marcadores aparecem.
bool evalVisionFull(SessionRec * s, const std::string & currMarked,
                    const std::vector<std::string> & currImages,
                    bool addSpecial, int64_t * outEndPos) {
    if (!s->visionReady || !s->mctx) return false;

    auto msgs = toCommonMsgs(s->history);
    common_chat_msg newMsg;
    newMsg.role = "user";
    newMsg.content = currMarked;
    std::string formatted;
    try {
        formatted = common_chat_format_single(s->tmpls.get(), msgs, newMsg, true, s->useJinja);
    } catch (const std::exception & e) {
        LOGE("format_single(visão): %s", e.what());
        return false;
    }

    // conta marcadores no texto formatado (histórico + atual)
    const size_t nMarkers = countMarkers(s, formatted);
    const size_t nExpect = countHistoryImages(s) + currImages.size();
    if (nMarkers != nExpect) {
        LOGW("marcadores (%zu) != imagens esperadas (%zu) no texto formatado", nMarkers, nExpect);
        return false;
    }
    if (nMarkers == 0) return false; // não deveria acontecer na rota de visão

    // carrega bitmaps: histórico (em ordem) + atuais
    std::vector<std::string> allPaths;
    for (const auto & h : s->history) {
        for (const auto & im : h.images) allPaths.push_back(im);
    }
    for (const auto & im : currImages) allPaths.push_back(im);

    std::vector<mtmd_bitmap *> bitmaps;
    mtmd_helper_init_opt opt = mtmd_helper_init_opt_default();
    for (const auto & p : allPaths) {
        if (!fileExists(p)) {
            for (auto * b : bitmaps) mtmd_bitmap_free(b);
            LOGW("imagem sumiu do disco: %s", p.c_str());
            return false;
        }
        auto wrap = mtmd_helper_bitmap_init_from_file(s->mctx, p.c_str(), false, opt);
        if (!wrap.bitmap) {
            for (auto * b : bitmaps) mtmd_bitmap_free(b);
            LOGW("falha ao ler imagem: %s", p.c_str());
            return false;
        }
        bitmaps.push_back(wrap.bitmap);
    }

    // separa por marcador
    std::vector<std::string> segments;
    size_t start = 0, pos = 0;
    while ((pos = formatted.find(s->marker, start)) != std::string::npos) {
        segments.push_back(formatted.substr(start, pos - start));
        start = pos + s->marker.size();
    }
    segments.push_back(formatted.substr(start));

    std::vector<mtmd_input_text> texts(segments.size());
    std::vector<mtmd_input_part> parts;
    for (size_t i = 0; i < segments.size(); i++) {
        texts[i] = {segments[i].data(), segments[i].size(), false, true};
        mtmd_input_part tp;
        tp.text = &texts[i];
        parts.push_back(tp);
        if (i < bitmaps.size()) {
            mtmd_input_part ip;
            ip.bitmap = bitmaps[i];
            parts.push_back(ip);
        }
    }
    std::vector<const mtmd_input_part *> ptrs;
    for (const auto & part : parts) ptrs.push_back(&part);

    mtmd_input_chunks * chunks = mtmd_input_chunks_init();
    int rc = mtmd_tokenize_from_parts(s->mctx, chunks, ptrs.data(), ptrs.size(), addSpecial);
    for (auto * b : bitmaps) mtmd_bitmap_free(b);
    if (rc != 0) {
        mtmd_input_chunks_free(chunks);
        LOGW("mtmd_tokenize_from_parts rc=%d", rc);
        return false;
    }

    resetMemory(s);
    llama_pos nPast = 0;
    const size_t nChunks = mtmd_input_chunks_size(chunks);
    for (size_t i = 0; i < nChunks; i++) {
        if (s->stopFlag.load()) {
            mtmd_input_chunks_free(chunks);
            return false;
        }
        const mtmd_input_chunk * chunk = mtmd_input_chunks_get(chunks, i);
        if (!chunk) { mtmd_input_chunks_free(chunks); return false; }
        if (mtmd_input_chunk_get_type(chunk) == MTMD_INPUT_CHUNK_TYPE_TEXT) {
            llama_pos next = nPast;
            rc = mtmd_helper_eval_chunk_single(s->mctx, s->lctx, chunk,
                                               nPast, 0, s->nBatch, false, &next);
            if (rc != 0) {
                mtmd_input_chunks_free(chunks);
                LOGE("mtmd text chunk rc=%d", rc);
                return false;
            }
            nPast = next;
            size_t nt = 0;
            const llama_token * toks = mtmd_input_chunk_get_tokens_text(chunk, &nt);
            for (size_t k = 0; k < nt; k++) cacheAppendToken(s, toks[k]);
        } else {
            mtmd_batch * mb = mtmd_batch_init(s->mctx);
            if (!mb) { mtmd_input_chunks_free(chunks); return false; }
            rc = mtmd_batch_add_chunk(mb, chunk);
            size_t j = i + 1;
            while (rc == 0 && j < nChunks) {
                const mtmd_input_chunk * nxt = mtmd_input_chunks_get(chunks, j);
                if (mtmd_input_chunk_get_type(nxt) != MTMD_INPUT_CHUNK_TYPE_TEXT) {
                    if (mtmd_batch_add_chunk(mb, nxt) != 0) break;
                    j++;
                } else break;
            }
            if (rc != 0) {
                mtmd_batch_free(mb);
                mtmd_input_chunks_free(chunks);
                return false;
            }
            rc = mtmd_batch_encode(mb);
            if (rc != 0) {
                mtmd_batch_free(mb);
                mtmd_input_chunks_free(chunks);
                LOGE("mtmd_batch_encode rc=%d", rc);
                return false;
            }
            float * embd = mtmd_batch_get_output_embd(mb, chunk);
            if (!embd) {
                mtmd_batch_free(mb);
                mtmd_input_chunks_free(chunks);
                return false;
            }
            llama_pos next = nPast;
            rc = mtmd_helper_decode_image_chunk(s->mctx, s->lctx, chunk, embd,
                                                nPast, 0, s->nBatch, &next,
                                                nullptr, nullptr);
            mtmd_batch_free(mb);
            if (rc != 0) {
                mtmd_input_chunks_free(chunks);
                LOGE("mtmd image decode rc=%d", rc);
                return false;
            }
            nPast = next;
            cacheAppendImage(s, (uint32_t) mtmd_input_chunk_get_n_pos(chunk));
            i = j - 1;
        }
    }
    mtmd_input_chunks_free(chunks);
    s->posAcc = nPast;
    if (outEndPos) *outEndPos = nPast;
    return true;
}

// Rota texto: incremental (LCP com o cache); se falhar, replay completo.
bool evalPlain(SessionRec * s, const std::string & content, bool addSpecial,
               int64_t * outEndPos) {
    auto msgs = toCommonMsgs(s->history);
    common_chat_msg newMsg;
    newMsg.role = "user";
    newMsg.content = content;
    std::string formatted;
    try {
        formatted = common_chat_format_single(s->tmpls.get(), msgs, newMsg, true, s->useJinja);
    } catch (const std::exception & e) {
        LOGE("format_single: %s", e.what());
        return false;
    }

    std::vector<llama_token> toks = common_tokenize(s->model->vocab, formatted, addSpecial, true);
    int64_t endPos = 0;
    if (s->cache.empty()) {
        if (!decodePromptTokens(s, toks, 0, true, &endPos)) return false;
        s->cache.clear();
        cacheAppendTokens(s, toks, 0);
        s->posAcc = endPos;
        if (outEndPos) *outEndPos = endPos;
        return true;
    }
    int64_t covered = cacheCovered(s, toks);
    if (covered >= (int64_t) toks.size()) {
        if (outEndPos) *outEndPos = s->posAcc;
        return true;
    }
    std::vector<llama_token> delta(toks.begin() + (ptrdiff_t) covered, toks.end());
    if (!decodePromptTokens(s, delta, covered, true, &endPos)) {
        resetMemory(s);
        if (!decodePromptTokens(s, toks, 0, true, &endPos)) return false;
        s->cache.clear();
        cacheAppendTokens(s, toks, 0);
        s->posAcc = endPos;
        if (outEndPos) *outEndPos = endPos;
        return true;
    }
    if (covered < (int64_t) s->cache.size()) s->cache.resize((size_t) covered);
    cacheAppendTokens(s, toks, (size_t) covered);
    s->posAcc = endPos;
    if (outEndPos) *outEndPos = endPos;
    return true;
}

// ---------------------------------------------------------------------------
// UTF-8 (streaming em pedaços válidos)
// ---------------------------------------------------------------------------

struct Utf8Assembler {
    std::string pending;
    std::string streamed;

    static int completeLen(const unsigned char * b, size_t n) {
        if (n == 0) return 0;
        int len = 1;
        if ((b[0] & 0x80) == 0) len = 1;
        else if ((b[0] & 0xE0) == 0xC0) len = 2;
        else if ((b[0] & 0xF0) == 0xE0) len = 3;
        else if ((b[0] & 0xF8) == 0xF0) len = 4;
        else return -1;
        if (len > (int) n) {
            for (size_t i = 1; i < n; i++) if ((b[i] & 0xC0) != 0x80) return -1;
            return 0;
        }
        if (len == 2 && b[0] < 0xC2) return -1;
        if (len == 3 && b[0] == 0xE0 && b[1] < 0xA0) return -1;
        if (len == 4 && b[0] == 0xF0 && b[1] < 0x90) return -1;
        for (int i = 1; i < len; i++) if ((b[i] & 0xC0) != 0x80) return -1;
        return len;
    }

    std::string add(const std::string & bytes) {
        pending += bytes;
        size_t cut = 0, i = 0;
        while (i < pending.size()) {
            const unsigned char * b = (const unsigned char *) pending.data() + i;
            int len = completeLen(b, pending.size() - i);
            if (len < 0) { i++; cut = i; continue; }
            if (len == 0) break;
            i += (size_t) len;
            cut = i;
        }
        std::string out = pending.substr(0, cut);
        pending.erase(0, cut);
        streamed += out;
        return out;
    }
};

// ---------------------------------------------------------------------------
// Pedido de chat
// ---------------------------------------------------------------------------

void runChatRequest(SessionRec * s, const json & req, uint64_t token) {
    const std::string content = req.value("content", "");
    std::vector<std::string> images;
    if (req.contains("images") && req["images"].is_array()) {
        for (const auto & im : req["images"]) images.push_back(im.get<std::string>());
    }
    const bool warm   = req.value("warm", false);
    const bool assistantOnly = req.value("assistant", false);
    int64_t maxTokens = req.value("maxTokens", 1024);

    const json & sp = req.contains("sampling") ? req["sampling"] : json::object();
    const float temp = sp.value("temp", 0.8f);
    const int32_t topK = sp.value("topK", 40);
    const float topP = sp.value("topP", 0.95f);
    const float minP = sp.value("minP", 0.05f);
    const float repPen = sp.value("repeatPenalty", 1.0f);
    const int32_t penLastN = sp.value("penaltyLastN", 64);
    const int64_t seed = sp.value("seed", (int64_t) 0);

    if (assistantOnly) {
        HistMsg ah;
        ah.role = "assistant";
        ah.content = content;
        s->history.push_back(std::move(ah));
        emitDone(token, "", "warm", 0, 0.0);
        return;
    }

    // conteúdo marcado (imagens sempre no início do texto, como mtmd-cli)
    std::string marked;
    if (!images.empty()) {
        for (size_t i = 0; i < images.size(); i++) marked += s->marker;
        marked += content;
    } else {
        marked = content;
    }

    // função que avalia o turno (escolhe rota)
    const size_t histImgs = countHistoryImages(s);
    const bool needVision = s->visionReady && (histImgs > 0 || !images.empty());

    const int maxAttempts = 64;
    bool evalOk = false;
    int64_t nPast = 0;
    for (int attempt = 0; attempt < maxAttempts + 1 && !evalOk; attempt++) {
        const bool addSpecial = s->history.empty();
        if (needVision) {
            evalOk = evalVisionFull(s, marked, images, addSpecial, &nPast);
        } else {
            evalOk = evalPlain(s, content, addSpecial, &nPast);
        }
        if (!evalOk) break;
        const size_t headroom = (size_t) std::max<int64_t>(maxTokens, 0) + 512;
        if ((size_t) s->posAcc + headroom <= s->nCtx) break;
        // estourou o contexto: remove o par mais antigo (mantendo system)
        if (s->history.size() <= 1) break;
        size_t dropFrom = (s->history[0].role == "system") ? 1 : 0;
        if (dropFrom >= s->history.size()) break;
        size_t dropCount = (dropFrom + 1 < s->history.size()) ? 2 : 1;
        s->history.erase(s->history.begin() + (ptrdiff_t) dropFrom,
                         s->history.begin() + (ptrdiff_t) std::min(s->history.size(),
                                                                    dropFrom + dropCount));
        resetMemory(s);
        emitNote(token, "ctx_trim");
    }

    if (!evalOk) {
        emitError(token, "eval",
                  needVision
                      ? "Falha ao processar a mensagem com imagem (arquivo inválido ou projetor incompatível)."
                      : "Falha ao avaliar o prompt (contexto cheio?)");
        return;
    }

    if (warm) {
        HistMsg hm;
        hm.role = "user";
        hm.content = marked;
        hm.images = images;
        s->history.push_back(std::move(hm));
        emitDone(token, "", "warm", 0, 0.0);
        return;
    }

    // sampler
    if (s->smpl) { common_sampler_free(s->smpl); s->smpl = nullptr; }
    {
        common_params_sampling spars;
        spars.temp = temp;
        spars.top_k = topK;
        spars.top_p = topP;
        spars.min_p = minP;
        spars.penalty_repeat = repPen;
        spars.penalty_last_n = penLastN;
        spars.seed = seed <= 0
            ? (uint32_t) (std::chrono::steady_clock::now().time_since_epoch().count() & 0xFFFFFFFFu)
            : (uint32_t) seed;
        s->smpl = common_sampler_init(s->model->m, spars);
    }
    if (!s->smpl) {
        emitError(token, "sampler", "Falha ao criar o sampler");
        return;
    }

    HistMsg hm;
    hm.role = "user";
    hm.content = marked;
    hm.images = images;
    s->history.push_back(std::move(hm));

    Utf8Assembler asm_;
    int64_t nGenerated = 0;
    auto t0 = std::chrono::steady_clock::now();
    std::string reason = "stop";
    llama_pos pos = (llama_pos) nPast;

    while (nGenerated < maxTokens) {
        if (s->stopFlag.load()) { reason = "cancelled"; break; }
        if (pos >= (llama_pos) s->nCtx - 8) { reason = "ctx_full"; break; }

        llama_token t = common_sampler_sample(s->smpl, s->lctx, -1);
        if (llama_vocab_is_eog(s->model->vocab, t)) { reason = "stop"; break; }
        common_sampler_accept(s->smpl, t, true);

        std::string piece = common_token_to_piece(s->lctx, t, false);
        std::string text = asm_.add(piece);
        if (!text.empty()) {
            json ev{{"e", "tok"}, {"t", text}};
            evBase(ev, token);
            emitEvent(ev.dump());
        }
        nGenerated++;

        llama_batch b = llama_batch_init(1, 0, 1);
        b.token[0] = t;
        b.pos[0] = pos;
        b.n_seq_id[0] = 1;
        b.seq_id[0][0] = 0;
        b.logits[0] = 1;
        b.n_tokens = 1;
        int rc = llama_decode(s->lctx, b);
        llama_batch_free(b);
        if (rc < 0) { reason = "error"; break; }
        cacheAppendToken(s, t);
        pos++;
        s->posAcc = pos;
    }

    const std::string finalText = asm_.streamed;
    if (!(reason == "cancelled" && finalText.empty())) {
        HistMsg ah;
        ah.role = "assistant";
        ah.content = finalText;
        s->history.push_back(std::move(ah));
    }
    double tps = 0.0;
    auto t1 = std::chrono::steady_clock::now();
    double secs = std::chrono::duration<double>(t1 - t0).count();
    if (secs > 0 && nGenerated > 0) tps = (double) nGenerated / secs;
    if (reason == "ctx_full") emitNote(token, "ctx_full");
    if (reason == "error") emitNote(token, "gen_error");
    emitDone(token, finalText, reason, nGenerated, tps);
}

} // namespace engine

// ---------------------------------------------------------------------------
// JNI
// ---------------------------------------------------------------------------

static jstring JNI_init(JNIEnv * env, jclass) {
    using namespace engine;
    json out{{"ok", true}};
    {
        std::lock_guard<std::mutex> lk(g.mtx);
        try {
            if (!g.inited) {
                llama_backend_init();
                ggml_log_set(ggmlLogCb, nullptr);
                initDevices();
                g.inited = true;
            }
        } catch (const std::exception & e) {
            out["ok"] = false;
            out["error"] = e.what();
        }
        out["vulkan"] = g.vulkanOk;
        out["gpuName"] = g.gpuName;
        out["gpuTotal"] = g.gpuTotal;
        out["gpuFree"] = g.gpuFree;
        out["llama"] = llama_version();
        json arr = json::array();
        int ndev = ggml_backend_dev_count();
        for (int i = 0; i < ndev; i++) {
            ggml_backend_dev_t dev = ggml_backend_dev_get(i);
            if (!dev) continue;
            ggml_backend_dev_props props{};
            ggml_backend_dev_get_props(dev, &props);
            size_t freeMem = 0, totalMem = 0;
            ggml_backend_dev_memory(dev, &freeMem, &totalMem);
            json d{{"name", props.name ? props.name : "?"},
                   {"type", (int) props.type},
                   {"total", (uint64_t) totalMem},
                   {"free", (uint64_t) freeMem}};
            arr.push_back(d);
        }
        out["devices"] = arr;
    }
    return newJStr(env, out.dump());
}

static jstring JNI_probeModel(JNIEnv * env, jclass, jstring jpath) {
    std::string path = jstr(env, jpath);
    json out = engine::probeFile(path);
    return newJStr(env, out.dump());
}

// cfg: { token, path, gpu, layers, threads }
static void JNI_loadModel(JNIEnv * env, jclass, jstring jcfg) {
    using namespace engine;
    json cfg = json::parse(jstr(env, jcfg), nullptr, false);
    if (cfg.is_discarded()) { emitError(0, "json", "JSON inválido"); return; }
    const uint64_t token = cfg.value("token", (uint64_t) 0);
    const std::string path = cfg.value("path", "");
    if (path.empty() || !fileExists(path)) {
        emitError(token, "file", "Arquivo do modelo não encontrado");
        return;
    }
    const bool useGpu = cfg.value("gpu", true);
    const int32_t layers = cfg.value("layers", -1);
    const int32_t threads = std::max(1, cfg.value("threads", 4));

    llama_model_params mp = llama_model_default_params();
    bool gpu = false;
    {
        std::lock_guard<std::mutex> lk(g.mtx);
        gpu = useGpu && g.vulkanOk;
    }
    mp.n_gpu_layers = gpu ? (layers < 0 ? -1 : layers) : 0;
    mp.progress_callback = [](float progress, void * user) -> bool {
        uint64_t tk = (uint64_t) (uintptr_t) user;
        json j{{"e", "model_progress"}, {"p", progress}};
        evBase(j, tk);
        emitEvent(j.dump());
        return true;
    };
    mp.progress_callback_user_data = (void *) (uintptr_t) token;

    llama_model * m = llama_model_load_from_file(path.c_str(), mp);
    if (!m) {
        emitError(token, "load_failed",
                  "Falha ao carregar o modelo. Verifique se o arquivo é um GGUF de texto válido "
                  "e se há memória livre (tente 'CPU' se o Vulkan falhar).");
        return;
    }
    uint64_t id = allocId();
    auto rec = std::make_unique<ModelRec>();
    rec->id = id;
    rec->path = path;
    rec->useGpu = gpu;
    rec->m = m;
    rec->vocab = llama_model_get_vocab(m);
    {
        std::lock_guard<std::mutex> lk(g.mtx);
        g.models[id] = std::move(rec);
    }
    json j{{"e", "model_loaded"}, {"model", id}};
    evBase(j, token);
    emitEvent(j.dump());
}

static void JNI_unloadModel(JNIEnv *, jclass, jlong jid) {
    using namespace engine;
    std::unique_ptr<ModelRec> removed;
    {
        std::lock_guard<std::mutex> lk(g.mtx);
        for (const auto & kv : g.sessions) {
            if (kv.second->model && kv.second->model->id == (uint64_t) jid) return; // em uso
        }
        auto it = g.models.find((uint64_t) jid);
        if (it != g.models.end()) {
            removed = std::move(it->second);
            g.models.erase(it);
        }
    }
    if (removed && removed->m) llama_model_free(removed->m);
}

// cfg: { token, model, mmproj?, nCtx, nBatch, threads, flashAttn, template, system }
static void JNI_createSession(JNIEnv * env, jclass, jstring jcfg) {
    using namespace engine;
    json cfg = json::parse(jstr(env, jcfg), nullptr, false);
    if (cfg.is_discarded()) { emitError(0, "json", "JSON inválido"); return; }
    const uint64_t token = cfg.value("token", (uint64_t) 0);
    ModelRec * model = getModel(cfg.value("model", (uint64_t) 0));
    if (!model || !model->m) {
        emitError(token, "no_model", "Modelo não está carregado");
        return;
    }
    const std::string mmproj = cfg.value("mmproj", "");
    const uint32_t nCtx = cfg.value("nCtx", 8192);
    const int32_t nBatch = std::max(1, cfg.value("nBatch", 512));
    const int32_t threads = std::max(1, cfg.value("threads", 4));
    const bool flashAttn = cfg.value("flashAttn", false);
    const std::string tmplOverride = cfg.value("template", "");
    const std::string system = cfg.value("system", "");

    auto s = std::make_unique<SessionRec>();
    s->model = model;
    s->nCtx = nCtx > 0 ? nCtx : 8192;
    s->nBatch = nBatch;
    s->threads = threads;

    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = s->nCtx;
    cp.n_batch = s->nBatch;
    cp.n_threads = s->threads;
    cp.n_threads_batch = s->threads;
    {
        std::lock_guard<std::mutex> lk(g.mtx);
        if (flashAttn && g.vulkanOk) cp.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_ENABLED;
    }
    s->lctx = llama_init_from_model(model->m, cp);
    if (!s->lctx) {
        emitError(token, "ctx_alloc",
                  "Falha ao alocar o contexto. Reduza o tamanho do contexto ou feche outros chats.");
        return;
    }
    s->memory = llama_get_memory(s->lctx);

    try {
        s->tmpls = common_chat_templates_init(model->m, tmplOverride);
        s->useJinja = true;
    } catch (const std::exception & e) {
        llama_free(s->lctx);
        emitError(token, "template", std::string("Template de chat indisponível: ") + e.what());
        return;
    }
    if (!s->tmpls) {
        llama_free(s->lctx);
        emitError(token, "template", "O modelo não tem template de chat compatível");
        return;
    }

    if (!mmproj.empty() && fileExists(mmproj)) {
        bool gpuFlag = false;
        {
            std::lock_guard<std::mutex> lk(g.mtx);
            gpuFlag = model->useGpu && g.vulkanOk;
        }
        mtmd_context_params mparams = mtmd_context_params_default();
        mparams.use_gpu = gpuFlag;
        mparams.device = gpuFlag ? g.gpuDev : nullptr;
        mparams.n_threads = threads;
        mparams.warmup = false;
        try {
            s->mctx = mtmd_init_from_file(mmproj.c_str(), model->m, mparams);
        } catch (const std::exception & e) {
            LOGE("mtmd init: %s", e.what());
            s->mctx = nullptr;
        }
        if (!s->mctx) {
            llama_free(s->lctx);
            emitError(token, "mmproj",
                      "Falha ao carregar o projetor de visão (mmproj). Verifique se ele é "
                      "compatível com o modelo de texto.");
            return;
        }
        if (!mtmd_support_vision(s->mctx)) {
            mtmd_free(s->mctx);
            llama_free(s->lctx);
            emitError(token, "mmproj", "Este projetor não suporta imagens");
            return;
        }
        s->visionReady = true;
        const char * mk = mtmd_get_marker(s->mctx);
        if (mk) s->marker = mk;
    }

    if (!system.empty()) {
        HistMsg h;
        h.role = "system";
        h.content = system;
        s->history.push_back(std::move(h));
    }

    uint64_t id = allocId();
    s->id = id;
    {
        std::lock_guard<std::mutex> lk(g.mtx);
        g.sessions[id] = std::move(s);
    }
    json j{{"e", "session_ready"}, {"session", id}};
    evBase(j, token);
    emitEvent(j.dump());
}

static void JNI_destroySession(JNIEnv *, jclass, jlong jid) {
    using namespace engine;
    SessionRec * s = getSession((uint64_t) jid);
    if (!s) return;
    s->stopFlag.store(true);
    if (s->worker.joinable()) s->worker.join();
    std::unique_ptr<SessionRec> removed;
    {
        std::lock_guard<std::mutex> lk(g.mtx);
        auto it = g.sessions.find((uint64_t) jid);
        if (it != g.sessions.end()) {
            removed = std::move(it->second);
            g.sessions.erase(it);
        }
    }
    if (removed) {
        if (removed->smpl) { common_sampler_free(removed->smpl); removed->smpl = nullptr; }
        if (removed->mctx) mtmd_free(removed->mctx);
        if (removed->lctx) llama_free(removed->lctx);
    }
}

static void JNI_chatRequest(JNIEnv * env, jclass, jlong jid, jstring jreq) {
    using namespace engine;
    json req = json::parse(jstr(env, jreq), nullptr, false);
    if (req.is_discarded()) { emitError(0, "json", "JSON inválido"); return; }
    const uint64_t token = req.value("token", (uint64_t) 0);
    SessionRec * s = getSession((uint64_t) jid);
    if (!s) {
        emitError(token, "no_session", "Sessão não encontrada");
        return;
    }
    if (s->busy.exchange(true)) {
        emitError(token, "busy", "Outra geração está em andamento");
        return;
    }
    s->stopFlag.store(false);
    s->worker = std::thread([jid, token, req]() {
        SessionRec * sess = getSession(jid);
        if (!sess) {
            emitError(token, "no_session", "Sessão não encontrada");
            return;
        }
        try {
            runChatRequest(sess, req, token);
        } catch (const std::exception & e) {
            emitError(token, "internal", e.what());
        } catch (...) {
            emitError(token, "internal", "erro desconhecido");
        }
        sess->busy.store(false);
        sess->stopFlag.store(false);
        if (sess->worker.joinable()) sess->worker.detach();
    });
}

static void JNI_stop(JNIEnv *, jclass, jlong jid) {
    using namespace engine;
    SessionRec * s = getSession((uint64_t) jid);
    if (s) s->stopFlag.store(true);
}

static void JNI_resetSession(JNIEnv *, jclass, jlong jid) {
    using namespace engine;
    SessionRec * s = getSession((uint64_t) jid);
    if (!s) return;
    s->stopFlag.store(true);
    if (s->worker.joinable()) s->worker.join();
    s->stopFlag.store(false);
    resetMemory(s);
    s->history.clear();
    if (s->smpl) { common_sampler_free(s->smpl); s->smpl = nullptr; }
}

// ---------------------------------------------------------------------------
// Registro JNI
// ---------------------------------------------------------------------------

static JNINativeMethod g_methods[] = {
    {"nativeInit",           "()Ljava/lang/String;",                   (void *) JNI_init},
    {"nativeProbeModel",     "(Ljava/lang/String;)Ljava/lang/String;", (void *) JNI_probeModel},
    {"nativeLoadModel",      "(Ljava/lang/String;)V",                  (void *) JNI_loadModel},
    {"nativeUnloadModel",    "(J)V",                                   (void *) JNI_unloadModel},
    {"nativeCreateSession",  "(Ljava/lang/String;)V",                  (void *) JNI_createSession},
    {"nativeDestroySession", "(J)V",                                   (void *) JNI_destroySession},
    {"nativeChatRequest",    "(JLjava/lang/String;)V",                 (void *) JNI_chatRequest},
    {"nativeStop",           "(J)V",                                   (void *) JNI_stop},
    {"nativeResetSession",   "(J)V",                                   (void *) JNI_resetSession},
};

JNIEXPORT jint JNI_OnLoad(JavaVM * vm, void *) {
    g_vm = vm;
    JNIEnv * env = nullptr;
    if (vm->GetEnv((void **) &env, JNI_VERSION_1_6) != JNI_OK) return JNI_ERR;
    jclass cls = env->FindClass("app/ggufchat/core/NativeBridge");
    if (!cls) {
        __android_log_write(ANDROID_LOG_ERROR, LOG_TAG, "FindClass(NativeBridge) falhou");
        return JNI_ERR;
    }
    g_bridgeClass = (jclass) env->NewGlobalRef(cls);
    env->DeleteLocalRef(cls);
    g_listenerField = env->GetStaticFieldID(g_bridgeClass, "listener", "Lapp/ggufchat/core/EngineListener;");
    if (!g_listenerField) {
        __android_log_write(ANDROID_LOG_ERROR, LOG_TAG, "campo 'listener' não encontrado");
        return JNI_ERR;
    }
    jclass listenerCls = env->FindClass("app/ggufchat/core/EngineListener");
    if (!listenerCls) {
        __android_log_write(ANDROID_LOG_ERROR, LOG_TAG, "FindClass(EngineListener) falhou");
        return JNI_ERR;
    }
    g_onEventMethod = env->GetMethodID(listenerCls, "onEvent", "(Ljava/lang/String;)V");
    env->DeleteLocalRef(listenerCls);
    if (!g_onEventMethod) {
        __android_log_write(ANDROID_LOG_ERROR, LOG_TAG, "método onEvent não encontrado");
        return JNI_ERR;
    }
    if (env->RegisterNatives(g_bridgeClass, g_methods, sizeof(g_methods) / sizeof(g_methods[0])) != JNI_OK) {
        __android_log_write(ANDROID_LOG_ERROR, LOG_TAG, "RegisterNatives falhou");
        return JNI_ERR;
    }
    return JNI_VERSION_1_6;
}
