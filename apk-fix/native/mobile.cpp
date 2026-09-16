// Built against the SAME pinned llama/ggml/mtmd headers and libraries.
#include <jni.h>
#include <android/log.h>
#include "llama.h"
#include "prompt_cache.h"
#include "cpu_threads.h"
#include "decode_delivery.h"
#include "strict_vulkan.h"
#include <sched.h>
#include <unistd.h>
#include "chat.h"
#include "gguf.h"
#include "ggml-backend.h"
#include "mtmd.h"
#include "mtmd-helper.h"
#include <atomic>
#include <chrono>
#include <algorithm>
#include <fstream>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>
#include <string>
#include <codecvt>
#include <locale>
#include <stdexcept>
#include <sys/stat.h>
#include <cstdio>
#include <cstring>
#include <climits>

#define LOG(...) __android_log_print(ANDROID_LOG_INFO,"GGUFChatNative",__VA_ARGS__)
struct ImageEmbedding {std::string metadata;std::vector<float> values;};
struct Engine {
    llama_model *model=nullptr;
    llama_context *ctx=nullptr;
    mtmd_context *projector=nullptr;
    std::atomic<bool> cancel{false};
    std::mutex mutex;
    std::string error;
    int layers=0;
    ggml_backend_dev_t strict_device=nullptr;
    std::vector<llama_token> cached_tokens; // exact tokens whose KV is present
    bool cache_supported=false;
    std::string image_set_id;
    std::vector<ImageEmbedding> image_cache;
    size_t image_cache_bytes=0;
    ~Engine() { if(projector) mtmd_free(projector); if(ctx) llama_free(ctx); if(model) llama_model_free(model); }
};
static std::mutex registry_mutex;
static std::unordered_map<jlong,std::shared_ptr<Engine>> engines;
static jlong next_handle=1;
static std::once_flag initialized;
static thread_local std::string create_error;
static thread_local int loaded_gpu_layers=0;
static std::shared_ptr<Engine> get(jlong h) {
    std::lock_guard<std::mutex> guard(registry_mutex);
    auto i=engines.find(h); return i==engines.end()?nullptr:i->second;
}
static std::string utf8(JNIEnv *env,jstring text) {
    if(!text) return {};
    const jchar *p=env->GetStringChars(text,nullptr);
    if(!p) throw std::runtime_error("Sem memória para ler o texto");
    std::u16string u(reinterpret_cast<const char16_t*>(p),env->GetStringLength(text));
    env->ReleaseStringChars(text,p);
    return std::wstring_convert<std::codecvt_utf8_utf16<char16_t>,char16_t>{}.to_bytes(u);
}
static jstring java_string(JNIEnv *env,const std::string &s) {
    auto u=std::wstring_convert<std::codecvt_utf8_utf16<char16_t>,char16_t>{}.from_bytes(s);
    return env->NewString(reinterpret_cast<const jchar*>(u.data()),u.size());
}
static size_t complete_utf8(const std::string &s) {
    size_t i=0;
    while(i<s.size()) {
        unsigned char c=s[i]; size_t n=c<0x80?1:(c<0xe0?2:(c<0xf0?3:4));
        if(i+n>s.size()) break;
        i+=n;
    }
    return i;
}
static uint64_t bytes(const std::string &p) {
    struct stat s{};
    if(stat(p.c_str(),&s)!=0 || s.st_size<24) throw std::runtime_error("Arquivo GGUF ausente ou inválido");
    return s.st_size;
}
static uint64_t available_memory() {
    std::ifstream f("/proc/meminfo"); std::string line;
    while(std::getline(f,line)) if(line.rfind("MemAvailable:",0)==0) return std::stoull(line.substr(13))*1024;
    return 0; // Telemetry unavailable is not evidence of allocation failure.
}
static std::vector<llama_token> tokens(const llama_vocab *v,const std::string &s) {
    int n=llama_tokenize(v,s.data(),s.size(),nullptr,0,true,true);
    if(n>=0) return {};
    std::vector<llama_token> t(-n);
    n=llama_tokenize(v,s.data(),s.size(),t.data(),t.size(),true,true);
    if(n<0) throw std::runtime_error("Falha ao tokenizar prompt");
    t.resize(n); return t;
}
static std::string piece(const llama_vocab *v,llama_token t) {
    char small[256];
    int n=llama_token_to_piece(v,t,small,sizeof(small),0,false);
    if(n>=0) return std::string(small,n);
    std::vector<char> large(-n);
    n=llama_token_to_piece(v,t,large.data(),large.size(),0,false);
    if(n<0) throw std::runtime_error("Falha ao decodificar token");
    return std::string(large.data(),n);
}
static int generation_threads(int requested) {
    cpu_set_t allowed;CPU_ZERO(&allowed);
    std::vector<int> capacities;int available=0;
    if(sched_getaffinity(0,sizeof(allowed),&allowed)==0) {
        for(int cpu=0;cpu<CPU_SETSIZE;cpu++)if(CPU_ISSET(cpu,&allowed)) {
            available++;
            std::ifstream f("/sys/devices/system/cpu/cpu"+std::to_string(cpu)+"/cpu_capacity");
            int capacity=0;if(f>>capacity)capacities.push_back(capacity);
        }
    }
    if(available<=0)available=std::max<long>(1,sysconf(_SC_NPROCESSORS_ONLN));
    int result=resolve_cpu_threads(requested,available,capacities);
    LOG("GGUF_CPU_THREADS requested=%d available=%d capacities=%zu resolved=%d",requested,available,capacities.size(),result);
    return result;
}
extern "C" JNIEXPORT jlong JNICALL Java_com_ggufchat_app_Native_create(JNIEnv *env,jclass,jstring path,jstring proj,jint context,jint threads,jint layers,jboolean mmap) {
    try {
        create_error.clear();loaded_gpu_layers=0;ggml_backend_gguf_strict_reset();
        const int requested_layers=layers;
        if(layers!=0) layers=INT_MAX; // Vulkan mode is all layers, never partial CPU inference.
        auto model_path=utf8(env,path), projector_path=utf8(env,proj);
        if(projector_path=="null") projector_path.clear();
        if(projector_path.empty()) {
            gguf_init_params gp{}; gp.no_alloc=true; gp.ctx=nullptr;
            auto *meta=gguf_init_from_file(model_path.c_str(),gp);
            if(meta) {
                auto key=gguf_find_key(meta,"clip.has_vision_encoder");
                auto project=gguf_find_key(meta,"clip.projector_type");
                if(project<0) project=gguf_find_key(meta,"clip.vision.projector_type");
                if(key>=0 && project>=0 && gguf_get_kv_type(meta,key)==GGUF_TYPE_BOOL
                        && gguf_get_val_bool(meta,key) && gguf_get_kv_type(meta,project)==GGUF_TYPE_STRING
                        && gguf_find_tensor(meta,"token_embd.weight")>=0) projector_path=model_path;
                gguf_free(meta);
            }
        }

        if(context<256 || context>8192) throw std::runtime_error("Contexto deve ficar entre 256 e 8192 para limitar memória");
        uint64_t size=bytes(model_path)+(projector_path.empty()||projector_path==model_path?0:bytes(projector_path));
        // File-backed mmap pages are reclaimable and GGUF bytes are not an RSS
        // prediction. KV/cache sizes depend on architecture, not a fixed token
        // multiplier. Never reject a valid model using this telemetry alone.
        uint64_t available=available_memory();
        LOG("GGUF_MEMORY_TELEMETRY file_bytes=%llu available=%llu mmap=%d policy=actual_allocator",
            (unsigned long long)size,(unsigned long long)available,(int)mmap);
        std::call_once(initialized,[]{
            llama_log_set([](ggml_log_level level,const char *text,void*) {
                const char *offload=std::strstr(text,"offloaded ");
                int n=0,total=0;
                if(offload && std::sscanf(offload,"offloaded %d/%d layers to GPU",&n,&total)==2)
                    loaded_gpu_layers=n;
                __android_log_write(level==GGML_LOG_LEVEL_ERROR?ANDROID_LOG_ERROR:ANDROID_LOG_INFO,"GGUFNativeStderr",text);
            },nullptr);
            llama_backend_init();
        });
        auto e=std::make_shared<Engine>();
        auto mp=llama_model_default_params(); mp.n_gpu_layers=layers; mp.load_mode=mmap?LLAMA_LOAD_MODE_MMAP:LLAMA_LOAD_MODE_NONE;
        ggml_backend_dev_t no_accelerators[] = {nullptr};
        ggml_backend_dev_t vulkan_devices[] = {nullptr,nullptr};
        llama_model_tensor_buft_override gpu_weights[] = {{".*",nullptr},{nullptr,nullptr}};
        if(layers==0) mp.devices=no_accelerators; // Explicit CPU mode only.
        else {
            vulkan_devices[0]=ggml_backend_dev_by_name("Vulkan0");
            if(!vulkan_devices[0]) throw std::runtime_error("Vulkan indisponível. Nenhum fallback automático para CPU foi feito.");
            mp.devices=vulkan_devices;
            e->strict_device=vulkan_devices[0];
            // Include token embeddings and other weights normally left on CPU.
            gpu_weights[0].buft=ggml_backend_dev_buffer_type(e->strict_device);
            mp.tensor_buft_overrides=gpu_weights;
            mp.split_mode=LLAMA_SPLIT_MODE_NONE;
            LOG("GGUF_STRICT_VULKAN requested_layers=%d effective_layers=all weights=all tensor_cpu_fallback=blocked host_orchestration=CPU",requested_layers);
        }
        StrictVulkanScope strict(e->strict_device);
        e->model=llama_model_load_from_file(model_path.c_str(),mp);
        if(!e->model) throw std::runtime_error("O carregador não conseguiu abrir os pesos. Consulte o diagnóstico nativo: arquivo/arquitetura/backend ou alocação podem causar esta falha");
        if(layers!=0 && loaded_gpu_layers<=0)
            throw std::runtime_error("O GGUF não carregou camadas no Vulkan. Escolha CPU explicitamente ou outro modelo/dispositivo.");
        e->layers=loaded_gpu_layers;
        auto cp=llama_context_default_params(); cp.n_ctx=context; cp.n_batch=128; cp.n_ubatch=32;
        cp.n_threads=cp.n_threads_batch=generation_threads(threads);
        cp.abort_callback=[](void *p){return static_cast<Engine*>(p)->cancel.load();}; cp.abort_callback_data=e.get();
        e->ctx=llama_init_from_model(e->model,cp);
        if(!e->ctx) throw std::runtime_error("Não foi possível criar contexto: reduza o contexto/modelo");
        e->cache_supported=!llama_model_is_recurrent(e->model) && !llama_model_is_hybrid(e->model)
            && !llama_model_has_encoder(e->model) && !llama_model_is_diffusion(e->model);
        LOG("GGUF_CONTEXT_TUNING batch=%u ubatch=%u threads=%d prefix_cache_supported=%d",
            llama_n_batch(e->ctx),llama_n_ubatch(e->ctx),cp.n_threads,(int)e->cache_supported);
        if(!projector_path.empty()) {
            auto vp=mtmd_context_params_default(); vp.use_gpu=layers!=0; vp.n_threads=cp.n_threads; vp.print_timings=false; vp.warmup=false; vp.device=layers!=0?vulkan_devices[0]:nullptr;
            e->projector=mtmd_init_from_file(projector_path.c_str(),e->model,vp);
            if(!e->projector) throw std::runtime_error("mmproj incompatível com o GGUF ou memória insuficiente");
            if(!mtmd_support_vision(e->projector)) throw std::runtime_error("O projetor carregado não oferece visão; modelo não aprovado como multimodal visual");
            if(projector_path==model_path) LOG("GGUF_SINGLE_FILE_LOADED same_path=1");
            LOG("GGUF_PROJECTOR_LOADED vision=%d audio=%d",mtmd_support_vision(e->projector),mtmd_support_audio(e->projector));
        }
        LOG("GGUF_UNIT_LOADED language=%s layers=%d projector=%s",e->layers>0?"Vulkan":"CPU",e->layers,
            e->projector?(e->layers>0?"Vulkan":"CPU"):"none");
        LOG("model loaded: n_ctx=%u projector=%s",llama_n_ctx(e->ctx),e->projector?"loaded":"none");
        std::lock_guard<std::mutex> guard(registry_mutex); auto id=next_handle++; engines[id]=e; return id;
    } catch(const std::exception &ex) { create_error=ex.what(); if(*ggml_backend_gguf_strict_error())create_error=ggml_backend_gguf_strict_error(); LOG("Create failed: %s",create_error.c_str()); return 0; }
}
extern "C" JNIEXPORT void JNICALL Java_com_ggufchat_app_Native_destroy(JNIEnv*,jclass,jlong h) {
    std::shared_ptr<Engine> old;
    { std::lock_guard<std::mutex> g(registry_mutex); auto i=engines.find(h); if(i!=engines.end()) { old=i->second; engines.erase(i); } }
    if(old) old->cancel=true; // an in-flight generation retains ownership until it exits
}
extern "C" JNIEXPORT void JNICALL Java_com_ggufchat_app_Native_abort(JNIEnv*,jclass,jlong h) { auto e=get(h); if(e) e->cancel=true; }
extern "C" JNIEXPORT jstring JNICALL Java_com_ggufchat_app_Native_lastError(JNIEnv *env,jclass,jlong h) {
    auto e=get(h); if(!e) return java_string(env,create_error);
    std::lock_guard<std::mutex> g(e->mutex); return java_string(env,e->error);
}
extern "C" JNIEXPORT jboolean JNICALL Java_com_ggufchat_app_AttachmentInference_supportsVision(JNIEnv*,jclass,jlong h) {
    auto e=get(h);
    return e && e->projector && mtmd_support_vision(e->projector);
}
extern "C" JNIEXPORT jstring JNICALL Java_com_ggufchat_app_Native_backendName(JNIEnv *env,jclass,jlong h) {
    auto e=get(h); return java_string(env,e?(std::string(e->layers==0?"CPU":"Vulkan estrito (cálculo do modelo)")+(e->projector?" · GGUF + mmproj carregados":"")):"Não carregado");
}
extern "C" JNIEXPORT jstring JNICALL Java_com_ggufchat_app_Native_getTemplate(JNIEnv *env,jclass,jlong h) {
    auto e=get(h); const char *t=e?llama_model_chat_template(e->model,nullptr):nullptr; return t?java_string(env,t):nullptr;
}
extern "C" JNIEXPORT jstring JNICALL Java_com_ggufchat_app_Native_getMeta(JNIEnv *env,jclass,jlong h,jstring key) {
    auto e=get(h); if(!e) return nullptr;
    try { auto k=utf8(env,key); std::vector<char> out(4096); int n=llama_model_meta_val_str(e->model,k.c_str(),out.data(),out.size());
        if(n<0) return nullptr; if(n>=(int)out.size()) {out.resize(n+1);llama_model_meta_val_str(e->model,k.c_str(),out.data(),out.size());} return java_string(env,out.data());
    } catch(...) {return nullptr;}
}
extern "C" JNIEXPORT jstring JNICALL Java_com_ggufchat_app_Native_applyTemplate(JNIEnv *env,jclass,jlong h,jstring templ,jobjectArray roles,jobjectArray contents) {
    auto e=get(h); if(!e || !roles || !contents) return nullptr;
    try {
        int count=env->GetArrayLength(roles); if(count!=env->GetArrayLength(contents)) return nullptr;
        std::vector<std::string> r,c; r.reserve(count);c.reserve(count);
        for(int i=0;i<count;i++) {auto a=(jstring)env->GetObjectArrayElement(roles,i);auto b=(jstring)env->GetObjectArrayElement(contents,i);
            r.push_back(utf8(env,a));c.push_back(utf8(env,b));env->DeleteLocalRef(a);env->DeleteLocalRef(b);}
        std::vector<llama_chat_message> messages; for(int i=0;i<count;i++) messages.push_back({r[i].c_str(),c[i].c_str()});
        auto t=utf8(env,templ); if(t.empty()) {const char *p=llama_model_chat_template(e->model,nullptr);if(p)t=p;}
        // Gemma 4 needs its actual Jinja template/new turn tokens, not the old Gemma formatter.
        if(t.find("<|turn>")!=std::string::npos) {
            auto templates=common_chat_templates_init(e->model,t);
            common_chat_templates_inputs input;
            input.enable_thinking=false; input.add_generation_prompt=true;
            for(int i=0;i<count;i++){common_chat_msg msg;msg.role=r[i];msg.content=c[i];input.messages.push_back(std::move(msg));}
            auto rendered=common_chat_templates_apply(templates.get(),input);
            LOG("GGUF_JINJA_TEMPLATE_APPLIED messages=%d",count);
            return java_string(env,rendered.prompt);
        }
        std::vector<char> b(8192); int n=llama_chat_apply_template(t.empty()?"chatml":t.c_str(),messages.data(),messages.size(),true,b.data(),b.size());
        if(n<0) return nullptr; if(n>=(int)b.size()) {b.resize(n+1);n=llama_chat_apply_template(t.empty()?"chatml":t.c_str(),messages.data(),messages.size(),true,b.data(),b.size());}
        return n>=0?java_string(env,std::string(b.data(),n)):nullptr;
    } catch(...) {return nullptr;}
}
extern "C" JNIEXPORT jintArray JNICALL Java_com_ggufchat_app_Native_tokenize(JNIEnv *env,jclass,jlong h,jstring text) {
    auto e=get(h); if(!e)return nullptr;
    try {auto t=tokens(llama_model_get_vocab(e->model),utf8(env,text));auto a=env->NewIntArray(t.size());if(a)env->SetIntArrayRegion(a,0,t.size(),t.data());return a;}catch(...){return nullptr;}
}
extern "C" JNIEXPORT jstring JNICALL Java_com_ggufchat_app_Native_detokenize(JNIEnv *env,jclass,jlong h,jintArray ids) {
    auto e=get(h);if(!e || !ids)return nullptr;
    try {std::vector<jint> t(env->GetArrayLength(ids));env->GetIntArrayRegion(ids,0,t.size(),t.data());std::string s;for(auto id:t)s+=piece(llama_model_get_vocab(e->model),id);return java_string(env,s);}catch(...){return nullptr;}
}
// Explicit field assignment: mtmd v0.4 adds text_len before the boolean flags.
// Positional {text.c_str(), true, true} would silently send only ONE byte.
static mtmd_input_text media_input(const std::string &text) {
    mtmd_input_text input{};
    input.text=text.c_str(); input.text_len=text.size();
    input.add_special=true; input.parse_special=true;
    return input;
}
struct BackendSamplerBinding {
    llama_context *ctx;
    bool attached=false;
    ~BackendSamplerBinding() {
        if(attached) {
            llama_synchronize(ctx); // no outstanding graph may refer to the freed chain
            llama_set_sampler(ctx,0,nullptr);
        }
    }
};
static jboolean generate(JNIEnv *env,jlong h,jstring prompt,jint predict,jfloat temp,jfloat top_p,jfloat top_k,jfloat min_p,jfloat repeat,jint last_n,jint seed,jobject callback,jobjectArray images) {
    auto e=get(h);if(!e)return false; std::lock_guard<std::mutex> lock(e->mutex); if(!images)e->cancel=false;e->error.clear();
    StrictVulkanScope strict(e->strict_device);
    jmethodID on_token=nullptr,on_done=nullptr; jclass clazz=nullptr;
    using Clock=std::chrono::steady_clock;
    auto started=Clock::now(),decode_started=started,last_flush=started;
    bool ok=false,decoding=false;int emitted=0,callbacks=0,backend_sampled=0,overlap_submissions=0;
    std::string pending;pending.reserve(4096);
    int64_t first_token_ns=-1;size_t prompt_tokens=0,reused_tokens=0;bool text_cache=false;
    auto flush=[&] {
        size_t complete=complete_utf8(pending);if(!complete)return;
        auto text=java_string(env,pending.substr(0,complete));
        if(!text)throw std::runtime_error("Sem memória para resposta");
        env->CallVoidMethod(callback,on_token,text);env->DeleteLocalRef(text);
        if(env->ExceptionCheck())throw std::runtime_error("Callback de texto falhou");
        pending.erase(0,complete);callbacks++;last_flush=Clock::now();
        if(first_token_ns<0) first_token_ns=std::chrono::duration_cast<std::chrono::nanoseconds>(last_flush-started).count();
    };
    try {
        if(!callback || predict<=0) throw std::runtime_error("Callback ou limite de tokens inválido");
        clazz=env->GetObjectClass(callback);on_token=env->GetMethodID(clazz,"onToken","(Ljava/lang/String;)V");on_done=env->GetMethodID(clazz,"onDone","(Z)V");
        if(!on_token || !on_done || env->ExceptionCheck()) throw std::runtime_error("Callback inválido");
        auto vocab=llama_model_get_vocab(e->model);
        std::unique_ptr<llama_sampler,decltype(&llama_sampler_free)> sampler(llama_sampler_chain_init(llama_sampler_chain_default_params()),llama_sampler_free);
        if(!sampler) throw std::runtime_error("Sem memória para amostrador");
        if(last_n!=0) llama_sampler_chain_add(sampler.get(),llama_sampler_init_penalties(llama_vocab_n_tokens(vocab),last_n,repeat,0,0));
        if(temp<=0) llama_sampler_chain_add(sampler.get(),llama_sampler_init_greedy());
        else {llama_sampler_chain_add(sampler.get(),llama_sampler_init_top_k((int)top_k));llama_sampler_chain_add(sampler.get(),llama_sampler_init_top_p(top_p,1));llama_sampler_chain_add(sampler.get(),llama_sampler_init_min_p(min_p,1));llama_sampler_chain_add(sampler.get(),llama_sampler_init_temp(temp));llama_sampler_chain_add(sampler.get(),llama_sampler_init_dist(seed));}
        BackendSamplerBinding binding{e->ctx};
        // Full backend chain required in Vulkan mode; never change temperature,
        // penalties, filters or RNG seed to manufacture backend support.
        if(e->layers>0) {
            binding.attached=llama_set_sampler(e->ctx,0,sampler.get());
            if(!binding.attached)throw std::runtime_error("Vulkan estrito: GPU não suporta a cadeia de amostragem configurada. Fallback CPU bloqueado; parâmetros não foram alterados.");
        }
        LOG("GGUF_GPU_SAMPLING requested=%d attached=%d",e->layers>0,(int)binding.attached);
        const auto text=utf8(env,prompt);
        const int n_images=images?env->GetArrayLength(images):0;
        size_t input_size=0;
        auto memory=llama_get_memory(e->ctx);
        if(n_images) {
            // Image identity/embedding positions are not inferred from text IDs.
            e->cached_tokens.clear();llama_memory_clear(memory,true);
            if(!e->projector || !mtmd_support_vision(e->projector))
                throw std::runtime_error("Este modelo/projetor não aceita imagens. Use um par com visão.");
            mtmd::bitmaps bitmaps;
            std::string image_set_id;
            bool image_ids_valid=true;
            for(int i=0;i<n_images;i++) {
                if(e->cancel)throw std::runtime_error("Geração cancelada");
                auto path=(jstring)env->GetObjectArrayElement(images,i);
                auto filename=utf8(env,path);env->DeleteLocalRef(path);
                auto decoded=mtmd_helper_bitmap_init_from_file(e->projector,filename.c_str(),false,mtmd_helper_init_opt_default());
                mtmd::bitmap bitmap(decoded.bitmap);
                if(!bitmap.ptr || mtmd_bitmap_is_audio(bitmap.ptr.get()))throw std::runtime_error("Não foi possível decodificar uma imagem preparada");
                // The pinned helper hashes the ACTUAL encoded bytes with SHA-256.
                // Paths, filenames, conversation IDs and user labels are not keys.
                const char *id=mtmd_bitmap_get_id(bitmap.ptr.get());
                if(!id || std::strlen(id)!=64)image_ids_valid=false;
                else {image_set_id+=id;image_set_id+=';';}
                bitmaps.entries.push_back(std::move(bitmap));
            }
            if(!image_ids_valid || e->image_set_id!=image_set_id) {
                e->image_cache.clear();e->image_cache_bytes=0;
                e->image_set_id=image_ids_valid?image_set_id:std::string();
            }
            mtmd::input_chunks chunks(mtmd_input_chunks_init());
            auto ptrs=bitmaps.c_ptr();auto input=media_input(text);
            if(mtmd_tokenize(e->projector,chunks.ptr.get(),&input,ptrs.data(),ptrs.size())!=0)
                throw std::runtime_error("Falha ao preparar pixels e texto para o projetor");
            input_size=mtmd_helper_get_n_tokens(chunks.ptr.get());
            if(input_size+1>=(size_t)llama_n_ctx(e->ctx))
                throw std::runtime_error("Texto e imagens excedem o contexto. Desative anexos na lista, use outra conversa ou aumente o contexto. Nenhum conteúdo foi cortado silenciosamente.");
            llama_pos past=0;size_t image_ordinal=0,image_hits=0,image_misses=0;
            for(size_t i=0;i<chunks.size();i++) {
                if(e->cancel)throw std::runtime_error("Geração cancelada");
                const auto *chunk=chunks[i];
                const bool is_image=mtmd_input_chunk_get_type(chunk)==MTMD_INPUT_CHUNK_TYPE_IMAGE;
                int result;
                if(is_image) {
                    // Per-request image order + per-slice ordinal + full geometry
                    // distinguish different crops even when their source hash matches.
                    std::string metadata;
                    size_t meta_size=0;
                    if(image_ids_valid && mtmd_input_chunk_save(chunk,nullptr,0,&meta_size)==0 && meta_size>0 && meta_size<65536) {
                        metadata.resize(meta_size);
                        if(mtmd_input_chunk_save(chunk,&metadata[0],metadata.size(),&meta_size)!=0)metadata.clear();
                    }
                    float *embd=nullptr;
                    const size_t count=mtmd_input_chunk_get_n_tokens(chunk)*(size_t)llama_model_n_embd_inp(e->model);
                    if(!metadata.empty() && image_ordinal<e->image_cache.size()) {
                        auto &cached=e->image_cache[image_ordinal];
                        if(cached.metadata==metadata && cached.values.size()==count)embd=cached.values.data();
                    }
                    if(embd) image_hits++;
                    else {
                        image_misses++;
                        if(mtmd_encode_chunk(e->projector,chunk)!=0)throw std::runtime_error("Falha ao codificar pixels no projetor");
                        embd=mtmd_get_output_embd(e->projector);
                        if(!embd)throw std::runtime_error("Projetor não devolveu embeddings visuais");
                        // Optional RAM cache, NOT an attachment/input quota. Larger
                        // inputs still run normally; OOM in this copy drops the cache.
                        constexpr size_t cache_limit=16*1024*1024;
                        if(!metadata.empty() && count<=cache_limit/sizeof(float) && e->image_cache_bytes+count*sizeof(float)<=cache_limit) {
                            try {
                                if(e->image_cache.size()<=image_ordinal)e->image_cache.resize(image_ordinal+1);
                                auto &cached=e->image_cache[image_ordinal];
                                e->image_cache_bytes-=cached.values.size()*sizeof(float);
                                cached.metadata=metadata;cached.values.assign(embd,embd+count);
                                e->image_cache_bytes+=count*sizeof(float);
                            } catch(const std::bad_alloc &) {e->image_cache.clear();e->image_cache_bytes=0;}
                        }
                    }
                    // Keep upstream non-causal attention, M-RoPE and batching logic.
                    // Only the pure vision encoder is skipped on an exact cache hit.
                    result=mtmd_helper_decode_image_chunk(e->projector,e->ctx,chunk,embd,past,0,llama_n_batch(e->ctx),&past,nullptr,nullptr);
                    image_ordinal++;
                } else result=mtmd_helper_eval_chunk_single(e->projector,e->ctx,chunk,past,0,llama_n_batch(e->ctx),i+1==chunks.size(),&past);
                if(result!=0)throw std::runtime_error("Falha ao avaliar texto/imagem no modelo");
                if(is_image)LOG("GGUF_IMAGE_EVALUATED tokens=%zu backend=%s",mtmd_input_chunk_get_n_tokens(chunk),e->layers>0?"Vulkan":"CPU");
            }
            LOG("GGUF_IMAGE_EMBED_CACHE hits=%zu misses=%zu bytes=%zu",image_hits,image_misses,e->image_cache_bytes);
            LOG("GGUF_MEDIA_PREFILL images=%d tokens=%zu positions=%d",n_images,input_size,past);
        } else {
            auto input=tokens(vocab,text);input_size=input.size();
            if(input.empty() || input_size>=(size_t)llama_n_ctx(e->ctx))throw std::runtime_error("Conversa e documentos excedem o contexto. Desative anexos na lista, inicie outra conversa ou aumente o contexto. Nenhum texto foi cortado silenciosamente.");
            text_cache=e->cache_supported;
            reused_tokens=reusable_prefix(e->cached_tokens,input,text_cache,
                llama_memory_seq_pos_min(memory,0),llama_memory_seq_pos_max(memory,0));
            if(reused_tokens && !llama_memory_seq_rm(memory,0,reused_tokens,-1)) reused_tokens=0;
            if(!reused_tokens) {llama_memory_clear(memory,true);e->cached_tokens.clear();}
            else e->cached_tokens.resize(reused_tokens);
            for(size_t at=reused_tokens;at<input.size();at+=llama_n_batch(e->ctx)) {
                if(e->cancel)throw std::runtime_error("Geração cancelada");
                auto count=std::min<size_t>(llama_n_batch(e->ctx),input.size()-at);
                auto batch=llama_batch_get_one(input.data()+at,count);
                // Intermediate prompt chunks only populate KV. Computing their
                // vocabulary projection is wasted: only the final position is sampled.
                // Keep every input token and the exact 128/32 attention batching.
                std::vector<int8_t> output_mask(count,0);
                if(at+count==input.size())output_mask.back()=1;
                batch.logits=output_mask.data();
                if(llama_decode(e->ctx,batch)!=0)throw std::runtime_error("Falha de decode no prompt");
                if(text_cache)e->cached_tokens.insert(e->cached_tokens.end(),input.begin()+at,input.begin()+at+count);
            }
        }
        prompt_tokens=input_size;
        LOG("GGUF_PROMPT_CACHE input_tokens=%zu reused_tokens=%zu evaluated_tokens=%zu media=%d",
            prompt_tokens,reused_tokens,prompt_tokens-reused_tokens,n_images);

        // llama_decode queues Vulkan work and async output copies. Its return
        // does NOT mean prefill is finished. Drain once at the phase boundary
        // (sampling would wait for the same work anyway), so the decode-only
        // footer never charges prompt GPU work to response-token throughput.
        llama_synchronize(e->ctx);
        decode_started=Clock::now();decoding=true;
        int limit=std::min<int>(predict,llama_n_ctx(e->ctx)-input_size);
        const char *reason="length";
        for(int i=0;i<limit;i++) {
            if(e->cancel) throw std::runtime_error("Geração cancelada");
            // Upstream sample() fetches token, probs, logits and candidates via
            // four synchronizing getters even when the token is already selected.
            // Consume that token once and accept ONCE, preserving sampler state/RNG.
            auto t=binding.attached?llama_get_sampled_token_ith(e->ctx,-1):LLAMA_TOKEN_NULL;
            if(t!=LLAMA_TOKEN_NULL) {
                llama_sampler_accept(sampler.get(),t);backend_sampled++;
            } else if(e->strict_device) {
                throw std::runtime_error("Vulkan estrito: backend não selecionou o token. Amostragem CPU bloqueada.");
            } else t=llama_sampler_sample(sampler.get(),e->ctx,-1);
            if(llama_vocab_is_eog(vocab,t)) {reason="eog";break;}
            emitted++;pending+=piece(vocab,t);
            // Retain the already sampled text even if queuing the next decode
            // fails or is cancelled; the failure path flushes this exact prefix.
            const bool has_next=i+1<limit;
            // Vulkan queues work asynchronously. Let it execute while the CPU
            // delivers the CURRENT text through Java. First text is never
            // delayed behind the next decode. CPU ordering remains unchanged.
            decode_and_deliver(e->layers>0,emitted==1,has_next,[&] {
                if(e->cancel)throw std::runtime_error("Geração cancelada");
                if(llama_decode(e->ctx,llama_batch_get_one(&t,1))!=0)
                    throw std::runtime_error("Falha de decode durante resposta");
                if(text_cache)e->cached_tokens.push_back(t);
                if(e->layers>0 && emitted>1)overlap_submissions++;
            },[&] {
                if(emitted==1 || pending.size()>=4096 || Clock::now()-last_flush>=std::chrono::milliseconds(50))flush();
            });
        }
        flush();
        if(!pending.empty()) {auto text=java_string(env,"\xef\xbf\xbd");env->CallVoidMethod(callback,on_token,text);env->DeleteLocalRef(text);}
        if(e->cancel || env->ExceptionCheck()) throw std::runtime_error("Geração cancelada ou callback falhou");
        ok=true;LOG("GGUF_NATIVE_COMPLETE tokens=%d reason=%s projector=%d",emitted,reason,e->projector!=nullptr);
    } catch(const std::exception &ex) {
        e->cached_tokens.clear(); // failed/partial work is never reused
        e->image_cache.clear();e->image_cache_bytes=0;e->image_set_id.clear();
        e->error=ex.what();if(*ggml_backend_gguf_strict_error())e->error=ggml_backend_gguf_strict_error();LOG("Generation failed: %s",e->error.c_str());
        // Cancellation still preserves already produced complete text.
        if(on_token&&!env->ExceptionCheck())try{flush();}catch(...){}
    }
    auto finished=Clock::now();
    jlong decode_ns=decoding?std::chrono::duration_cast<std::chrono::nanoseconds>(finished-decode_started).count():0;
    jlong prefill_ns=std::chrono::duration_cast<std::chrono::nanoseconds>((decoding?decode_started:finished)-started).count();
    LOG("GGUF_STRICT_VULKAN_RESULT enabled=%d submitted_graphs=%llu submitted_math_nodes=%llu blocked=%d host_orchestration=CPU",
        e->strict_device!=nullptr,(unsigned long long)ggml_backend_gguf_strict_graphs(),
        (unsigned long long)ggml_backend_gguf_strict_nodes(),*ggml_backend_gguf_strict_error()!=0);
    LOG("GGUF_GPU_SAMPLING_RESULT backend_selected=%d emitted=%d",backend_sampled,emitted);
    LOG("GGUF_VULKAN_DELIVERY token_only_export=1 overlap_submissions=%d first_text_immediate=1",overlap_submissions);
    LOG("GGUF_RESPONSE_LATENCY first_token_ns=%lld prompt_tokens=%zu reused_tokens=%zu",(long long)first_token_ns,prompt_tokens,reused_tokens);
    LOG("GGUF_GENERATION_STATS tokens=%d decode_ns=%lld prefill_ns=%lld callbacks=%d success=%d",emitted,(long long)decode_ns,(long long)prefill_ns,callbacks,(int)ok);
    if(!env->ExceptionCheck()) {
        jclass stats=env->FindClass("com/ggufchat/app/GenerationStats");
        if(stats) {
            auto latency=env->GetStaticMethodID(stats,"latency","(JJJ)V");
            if(latency)env->CallStaticVoidMethod(stats,latency,(jlong)first_token_ns,(jlong)prompt_tokens,(jlong)reused_tokens);
            auto measured=env->GetStaticMethodID(stats,"measured","(JJJZ)V");
            if(measured)env->CallStaticVoidMethod(stats,measured,(jlong)emitted,decode_ns,prefill_ns,(jboolean)ok);
            env->DeleteLocalRef(stats);
        }
    }
    if(on_done && !env->ExceptionCheck()) env->CallVoidMethod(callback,on_done,(jboolean)ok);
    if(clazz)env->DeleteLocalRef(clazz);
    return ok && !env->ExceptionCheck();
}
extern "C" JNIEXPORT jboolean JNICALL Java_com_ggufchat_app_Native_generate(JNIEnv *env,jclass,jlong h,jstring prompt,jint predict,jfloat temp,jfloat top_p,jfloat top_k,jfloat min_p,jfloat repeat,jint last_n,jint seed,jobject callback) {
    return generate(env,h,prompt,predict,temp,top_p,top_k,min_p,repeat,last_n,seed,callback,nullptr);
}
extern "C" JNIEXPORT void JNICALL Java_com_ggufchat_app_AttachmentInference_begin(JNIEnv*,jclass,jlong h) {
    auto e=get(h);if(e)e->cancel=false;
}
extern "C" JNIEXPORT jboolean JNICALL Java_com_ggufchat_app_AttachmentInference_nativeGenerate(JNIEnv *env,jclass,jlong h,jstring prompt,jint predict,jfloat temp,jfloat top_p,jfloat top_k,jfloat min_p,jfloat repeat,jint last_n,jint seed,jobject callback,jobjectArray images) {
    return generate(env,h,prompt,predict,temp,top_p,top_k,min_p,repeat,last_n,seed,callback,images);
}
JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM*,void*) {return JNI_VERSION_1_6;}
