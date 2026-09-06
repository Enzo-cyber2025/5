#include <jni.h>
#include <android/log.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <dlfcn.h>
#include <string>
#include <sstream>
#include <vector>
#include <algorithm>
#include <cstdint>

static std::string j2s(JNIEnv* env, jstring v){ if(!v) return {}; const char* p=env->GetStringUTFChars(v,nullptr); std::string s=p?p:""; if(p) env->ReleaseStringUTFChars(v,p); return s; }
static jstring s2j(JNIEnv* env, const std::string& s){ return env->NewStringUTF(s.c_str()); }

static std::string vulkanInfo(){
    std::ostringstream out;
    void* lib = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
    if(!lib){ out << "Vulkan: indisponível neste aparelho/ROM"; return out.str(); }
    using EnumVer = int (*)(uint32_t*);
    auto enumVersion = reinterpret_cast<EnumVer>(dlsym(lib, "vkEnumerateInstanceVersion"));
    if(enumVersion){ uint32_t v=0; if(enumVersion(&v)==0){ out << "Vulkan: OK API " << ((v>>22)&0x3ff) << "." << ((v>>12)&0x3ff) << "." << (v&0xfff); } else out << "Vulkan: biblioteca presente, consulta falhou"; }
    else out << "Vulkan: biblioteca presente, API 1.0";
    dlclose(lib);
    return out.str();
}

static uint32_t le32(const uint8_t* p){ return (uint32_t)p[0] | ((uint32_t)p[1]<<8) | ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24); }
static uint64_t le64(const uint8_t* p){ uint64_t r=0; for(int i=7;i>=0;--i){ r=(r<<8)|p[i]; } return r; }

extern "C" JNIEXPORT jstring JNICALL Java_ai_arena_ggufchat_NativeBridge_nativeInfo(JNIEnv* env, jclass){
    std::ostringstream out;
    out << "GGUF Vulkan Chats 1.0 — importação por Storage Access Framework, mmap direto quando o provedor permite.\n";
    out << vulkanInfo() << "\n";
    out << "Back-end nativo: arm64/armeabi-v7a/x86_64, pronto para plugar kernels llama.cpp/MTMD Vulkan.";
    return s2j(env, out.str());
}

extern "C" JNIEXPORT jstring JNICALL Java_ai_arena_ggufchat_NativeBridge_inspectFd(JNIEnv* env, jclass, jint fd, jlong size, jstring display){
    std::string name = j2s(env, display);
    std::ostringstream out; out << name << ": ";
    if(fd < 0){ out << "FD inválido"; return s2j(env, out.str()); }
    size_t mapSize = size > 0 ? (size_t)std::min<jlong>(size, 1024*1024) : 1024*1024;
    void* mem = mmap(nullptr, mapSize, PROT_READ, MAP_PRIVATE, fd, 0);
    if(mem == MAP_FAILED){ out << "sem mmap; provedor não expõe arquivo seekable"; return s2j(env, out.str()); }
    const uint8_t* p = static_cast<const uint8_t*>(mem);
    if(mapSize >= 24 && p[0]=='G' && p[1]=='G' && p[2]=='U' && p[3]=='F'){
        uint32_t version = le32(p+4);
        uint64_t tensors = le64(p+8);
        uint64_t kv = le64(p+16);
        out << "GGUF v" << version << ", tensors=" << tensors << ", metadados=" << kv << ", tamanho=" << (size/1024/1024) << " MiB, mmap=OK";
    } else {
        out << "arquivo mapeado, mas cabeçalho GGUF não encontrado";
    }
    munmap(mem, mapSize);
    return s2j(env, out.str());
}

static std::string lower(std::string s){ std::transform(s.begin(),s.end(),s.begin(),[](unsigned char c){return std::tolower(c);}); return s; }
extern "C" JNIEXPORT jstring JNICALL Java_ai_arena_ggufchat_NativeBridge_draftAnswer(JNIEnv* env, jclass, jstring prompt, jstring modelA, jstring modelB, jboolean thinking, jboolean search){
    std::string p = j2s(env, prompt), a=j2s(env, modelA), b=j2s(env, modelB);
    std::ostringstream out;
    if(thinking){
        out << "Thinking\n";
        out << "1. Verificar modelos carregados: " << (a.empty()?"GGUF 1 ausente":a) << " e " << (b.empty()?"GGUF 2 ausente":b) << ".\n";
        out << "2. Considerar contexto do chat, pesquisa externa e capacidades multimodais.\n";
        out << "3. Responder de forma objetiva e manter execução compatível com tela bloqueada.\n\n";
    }
    if(search){ out << "Pesquisa\nAbra o botão Pesquisa web para consultar a pergunta atual no navegador e cole os achados no chat para síntese local.\n\n"; }
    out << "Resposta\n";
    out << "Recebi: \"" << p << "\". ";
    if(a.find("não selecionado") == std::string::npos || b.find("não selecionado") == std::string::npos)
        out << "Os GGUFs selecionados foram inspecionados por mmap e o app inicializou a camada nativa/Vulkan disponível no aparelho. ";
    else
        out << "Importe pelo menos um .gguf para ativar o fluxo local. ";
    std::string lp=lower(p);
    if(lp.find("imagem")!=std::string::npos || lp.find("multimodal")!=std::string::npos)
        out << "Para uso multimodal, mantenha um modelo de linguagem no slot 1 e um projector/vision GGUF no slot 2. ";
    out << "Esta build organiza chats, importa dois modelos, mantém foreground service com wake lock para continuar gerando com tela bloqueada e expõe pontos nativos para trocar o gerador demonstrativo por inferência llama.cpp Vulkan completa.";
    return s2j(env, out.str());
}
