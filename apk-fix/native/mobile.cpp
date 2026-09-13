// Built against the SAME pinned llama/ggml/mtmd headers and libraries.
#include <jni.h>
#include <android/log.h>
#include "llama.h"
#include "ggml-backend.h"
#include "mtmd.h"
#include <atomic>
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
struct Engine {
    llama_model *model=nullptr;
    llama_context *ctx=nullptr;
    mtmd_context *projector=nullptr;
    std::atomic<bool> cancel{false};
    std::mutex mutex;
    std::string error;
    int layers=0;
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
    throw std::runtime_error("Não foi possível verificar a memória disponível");
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
    std::vector<char> b(128);
    int n=llama_token_to_piece(v,t,b.data(),b.size(),0,false);
    if(n<0) { b.resize(-n); n=llama_token_to_piece(v,t,b.data(),b.size(),0,false); }
    if(n<0) throw std::runtime_error("Falha ao decodificar token");
    return std::string(b.data(),n);
}
extern "C" JNIEXPORT jlong JNICALL Java_com_ggufchat_app_Native_create(JNIEnv *env,jclass,jstring path,jstring proj,jint context,jint threads,jint layers,jboolean mmap) {
    try {
        create_error.clear();loaded_gpu_layers=0;
        if(layers<0) layers=INT_MAX;
        auto model_path=utf8(env,path), projector_path=utf8(env,proj);
        if(projector_path=="null") projector_path.clear();
        if(context<256 || context>8192) throw std::runtime_error("Contexto deve ficar entre 256 e 8192 para limitar memória");
        uint64_t size=bytes(model_path)+(projector_path.empty()?0:bytes(projector_path));
        uint64_t estimate=size+size/2+(uint64_t)context*262144+268435456;
        uint64_t available=available_memory();
        LOG("Memory guard: estimated=%llu available=%llu",(unsigned long long)estimate,(unsigned long long)available);
        if(estimate>available*7/10) throw std::runtime_error("Memória disponível insuficiente. Use um modelo/contexto menor ou feche outros aplicativos.");
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
        auto mp=llama_model_default_params(); mp.n_gpu_layers=layers; mp.use_mmap=mmap; mp.use_mlock=false;
        ggml_backend_dev_t no_accelerators[] = {nullptr};
        ggml_backend_dev_t vulkan_devices[] = {nullptr,nullptr};
        if(layers==0) mp.devices=no_accelerators; // Explicit CPU mode only.
        else {
            vulkan_devices[0]=ggml_backend_dev_by_name("Vulkan0");
            if(!vulkan_devices[0]) throw std::runtime_error("Vulkan indisponível. Nenhum fallback automático para CPU foi feito.");
            mp.devices=vulkan_devices;
        }
        e->model=llama_model_load_from_file(model_path.c_str(),mp);
        if(!e->model) throw std::runtime_error("Falha ao carregar GGUF: formato, arquitetura ou backend incompatível");
        if(layers!=0 && loaded_gpu_layers<=0)
            throw std::runtime_error("O GGUF não carregou camadas no Vulkan. Escolha CPU explicitamente ou outro modelo/dispositivo.");
        e->layers=loaded_gpu_layers;
        auto cp=llama_context_default_params(); cp.n_ctx=context; cp.n_batch=128; cp.n_ubatch=64;
        cp.n_threads=cp.n_threads_batch=std::max(1,std::min(threads,8));
        cp.abort_callback=[](void *p){return static_cast<Engine*>(p)->cancel.load();}; cp.abort_callback_data=e.get();
        e->ctx=llama_init_from_model(e->model,cp);
        if(!e->ctx) throw std::runtime_error("Não foi possível criar contexto: reduza o contexto/modelo");
        if(!projector_path.empty()) {
            auto vp=mtmd_context_params_default(); vp.use_gpu=layers!=0; vp.n_threads=cp.n_threads; vp.print_timings=false;
            e->projector=mtmd_init_from_file(projector_path.c_str(),e->model,vp);
            if(!e->projector) throw std::runtime_error("mmproj incompatível com o GGUF ou memória insuficiente");
            LOG("GGUF_PROJECTOR_LOADED vision=%d audio=%d",mtmd_support_vision(e->projector),mtmd_support_audio(e->projector));
        }
        LOG("GGUF_UNIT_LOADED language=%s layers=%d projector=%s",e->layers>0?"Vulkan":"CPU",e->layers,
            e->projector?(e->layers>0?"Vulkan":"CPU"):"none");
        LOG("model loaded: n_ctx=%u projector=%s",llama_n_ctx(e->ctx),e->projector?"loaded":"none");
        std::lock_guard<std::mutex> guard(registry_mutex); auto id=next_handle++; engines[id]=e; return id;
    } catch(const std::exception &ex) { create_error=ex.what(); LOG("Create failed: %s",ex.what()); return 0; }
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
extern "C" JNIEXPORT jstring JNICALL Java_com_ggufchat_app_Native_backendName(JNIEnv *env,jclass,jlong h) {
    auto e=get(h); return java_string(env,e?(std::string(e->layers==0?"CPU":"Vulkan")+(e->projector?" · GGUF + mmproj carregados":"")):"Não carregado");
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
extern "C" JNIEXPORT jboolean JNICALL Java_com_ggufchat_app_Native_generate(JNIEnv *env,jclass,jlong h,jstring prompt,jint predict,jfloat temp,jfloat top_p,jfloat top_k,jfloat min_p,jfloat repeat,jint last_n,jint seed,jobject callback) {
    auto e=get(h);if(!e)return false; std::lock_guard<std::mutex> lock(e->mutex); e->cancel=false;e->error.clear();
    jmethodID on_token=nullptr,on_done=nullptr; jclass clazz=nullptr;
    bool ok=false;
    try {
        if(!callback || predict<=0) throw std::runtime_error("Callback ou limite de tokens inválido");
        clazz=env->GetObjectClass(callback);on_token=env->GetMethodID(clazz,"onToken","(Ljava/lang/String;)V");on_done=env->GetMethodID(clazz,"onDone","(Z)V");
        if(!on_token || !on_done || env->ExceptionCheck()) throw std::runtime_error("Callback inválido");
        auto vocab=llama_model_get_vocab(e->model);auto input=tokens(vocab,utf8(env,prompt));
        if(input.empty() || input.size()>=(size_t)llama_n_ctx(e->ctx)) throw std::runtime_error("Conversa excede o contexto. Inicie outra conversa ou aumente o contexto.");
        int limit=std::min<int>(predict,llama_n_ctx(e->ctx)-input.size());
        llama_memory_clear(llama_get_memory(e->ctx),true);
        for(size_t at=0;at<input.size();at+=128) {
            if(e->cancel) throw std::runtime_error("Geração cancelada");
            auto batch=llama_batch_get_one(input.data()+at,std::min<size_t>(128,input.size()-at));
            if(llama_decode(e->ctx,batch)!=0) throw std::runtime_error("Falha de decode no prompt");
        }
        std::unique_ptr<llama_sampler,decltype(&llama_sampler_free)> sampler(llama_sampler_chain_init(llama_sampler_chain_default_params()),llama_sampler_free);
        if(!sampler) throw std::runtime_error("Sem memória para amostrador");
        if(last_n!=0) llama_sampler_chain_add(sampler.get(),llama_sampler_init_penalties(last_n,repeat,0,0));
        if(temp<=0) llama_sampler_chain_add(sampler.get(),llama_sampler_init_greedy());
        else {llama_sampler_chain_add(sampler.get(),llama_sampler_init_top_k((int)top_k));llama_sampler_chain_add(sampler.get(),llama_sampler_init_top_p(top_p,1));llama_sampler_chain_add(sampler.get(),llama_sampler_init_min_p(min_p,1));llama_sampler_chain_add(sampler.get(),llama_sampler_init_temp(temp));llama_sampler_chain_add(sampler.get(),llama_sampler_init_dist(seed));}
        std::string pending;int emitted=0;const char *reason="length";
        for(int i=0;i<limit;i++) {
            if(e->cancel) throw std::runtime_error("Geração cancelada");
            auto t=llama_sampler_sample(sampler.get(),e->ctx,-1);
            if(llama_vocab_is_eog(vocab,t)) {reason="eog";break;}
            pending+=piece(vocab,t);size_t complete=complete_utf8(pending);
            if(complete) {auto text=java_string(env,pending.substr(0,complete));if(!text)throw std::runtime_error("Sem memória para resposta");env->CallVoidMethod(callback,on_token,text);env->DeleteLocalRef(text);pending.erase(0,complete);}
            if(env->ExceptionCheck()) throw std::runtime_error("Callback de texto falhou");
            if(llama_decode(e->ctx,llama_batch_get_one(&t,1))!=0) throw std::runtime_error("Falha de decode durante resposta");
            emitted++;
        }
        if(!pending.empty()) {auto text=java_string(env,"\xef\xbf\xbd");env->CallVoidMethod(callback,on_token,text);env->DeleteLocalRef(text);}
        if(e->cancel || env->ExceptionCheck()) throw std::runtime_error("Geração cancelada ou callback falhou");
        ok=true;LOG("GGUF_NATIVE_COMPLETE tokens=%d reason=%s projector=%d",emitted,reason,e->projector!=nullptr);
    } catch(const std::exception &ex) {e->error=ex.what();LOG("Generation failed: %s",ex.what());}
    if(on_done && !env->ExceptionCheck()) env->CallVoidMethod(callback,on_done,(jboolean)ok);
    if(clazz)env->DeleteLocalRef(clazz);
    return ok && !env->ExceptionCheck();
}
JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM*,void*) {return JNI_VERSION_1_6;}
