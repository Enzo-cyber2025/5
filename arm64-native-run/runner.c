/*
 * runner.c — executa o código NATIVO arm64 REAL do APK (libaijni.so etc.)
 * sob qemu-aarch64 (user-mode) + libc musl aarch64.
 *
 * Isto NÃO é um emulador de Android completo: é a execução real das .so
 * arm64-v8a que o APK carrega em produção, com um mini-JNI que emula as
 * chamadas que o libaijni.so faz de volta para a JVM.
 *
 * Assinaturas JNI extraídas do classes.dex do APK:
 *   long   create(String model, String mmproj, int ctx, int gpuLayers, int threads, boolean mmap)
 *   String backendName(long h)
 *   boolean generate(long h, String prompt, int nPredict, float temp, float topP,
 *                    float topK, float minP, float repeatPenalty, int thinking, int seed, Callback cb)
 *   int[]  tokenize(long h, String text)
 *   String detokenize(long h, int[] tokens)
 *   String getMeta(long h, String key)
 *   String getTemplate(long h)
 *   String lastError(long h)
 *   void   destroy(long h)
 *   void   abort(long h)
 *   String applyTemplate(long h, String tpl, String[] keys, String[] values)
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdbool.h>
#include <signal.h>
#include <ucontext.h>
#include <unistd.h>

#define JNI_FALSE 0
#define JNI_TRUE  1

/* ================= mini-JNI ================= */
typedef struct JNINativeInterface { void* fns[256]; } JNINativeInterface;
typedef const JNINativeInterface* Table;
typedef Table* JNIEnv;              /* JNIEnv = ponteiro p/ ponteiro p/ tabela */
typedef void*  jobject;
typedef void*  jclass;
typedef void*  jstring;
typedef void*  jarray;
typedef void*  jobjectArray;
typedef void*  jintArray;
typedef void*  jmethodID;
typedef int    jint;
typedef int    jsize;
typedef int    jboolean;
typedef long   jlong;
typedef float  jfloat;

struct myjstr  { const char* s; };
struct myintarr{ jint len; jint data[65536]; };
struct myobjarr{ jint len; jobject items[256]; };

/* ---- helpers que retornam/inspecionam os objetos do mini-JNI ---- */
static struct myjstr* asstr(jobject o){ return (struct myjstr*)o; }
static struct myintarr* asintarr(jobject o){ return (struct myintarr*)o; }

/* ---- implementações reais das funções JNI usadas pelo libaijni.so ---- */
static const char* f_GetStringUTFChars(JNIEnv env, jstring s, jboolean* isCopy){
    (void)env; if(isCopy) *isCopy = JNI_FALSE;
    return s ? asstr(s)->s : NULL;
}
static void f_ReleaseStringUTFChars(JNIEnv env, jstring s, const char* p){
    (void)env;(void)s;(void)p;
}
static jsize f_GetStringUTFLength(JNIEnv env, jstring s){ (void)env; return s? strlen(asstr(s)->s):0; }
static jsize f_GetStringLength(JNIEnv env, jstring s){ (void)env; return s? strlen(asstr(s)->s):0; }
static jstring f_NewStringUTF(JNIEnv env, const char* u){
    (void)env; struct myjstr* m = malloc(sizeof *m); m->s = strdup(u?u:""); return (jstring)m;
}
static jsize f_GetArrayLength(JNIEnv env, jarray a){
    (void)env;
    if(!a) return 0;
    return ((struct myintarr*)a)->len;   /* int[] e obj[] compartilham o 1o campo */
}
static jobject f_GetObjectArrayElement(JNIEnv env, jobjectArray a, jsize i){
    (void)env; if(!a || i<0) return NULL; return ((struct myobjarr*)a)->items[i];
}
static jintArray f_NewIntArray(JNIEnv env, jsize n){
    (void)env; struct myintarr* a = calloc(1,sizeof *a); a->len = n; return (jintArray)a;
}
static jobjectArray f_NewObjectArray(JNIEnv env, jsize n, jclass c, jobject init){
    (void)env;(void)c;(void)init;
    struct myobjarr* a = calloc(1,sizeof *a); a->len = n; return (jobjectArray)a;
}
static void f_SetObjectArrayElement(JNIEnv env, jobjectArray a, jsize i, jobject v){
    (void)env; if(a && i>=0 && i<256) ((struct myobjarr*)a)->items[i]=v;
}
static jint* f_GetIntArrayElements(JNIEnv env, jintArray a, jboolean* isCopy){
    (void)env; if(isCopy) *isCopy = JNI_FALSE; return a? asintarr(a)->data : NULL;
}
static void f_ReleaseIntArrayElements(JNIEnv env, jintArray a, jint* elems, jint mode){
    (void)env;(void)a;(void)elems;(void)mode;
}
static void f_SetIntArrayRegion(JNIEnv env, jintArray a, jsize s, jsize l, const jint* in){
    (void)env; if(a) memcpy(&asintarr(a)->data[s], in, l*sizeof(jint));
}
static void f_GetIntArrayRegion(JNIEnv env, jintArray a, jsize s, jsize l, jint* out){
    (void)env; if(a) memcpy(out, &asintarr(a)->data[s], l*sizeof(jint));
}
static jclass f_FindClass(JNIEnv env, const char* name){
    (void)env; (void)name; return (jclass)0x1;
}
static jclass f_GetObjectClass(JNIEnv env, jobject o){ (void)env;(void)o; return (jclass)0x1; }
#define MID_ONTOKEN ((jmethodID)0x1)
#define MID_ONDONE  ((jmethodID)0x2)
static jmethodID f_GetMethodID(JNIEnv env, jclass c, const char* n, const char* sig){
    (void)env;(void)c;(void)sig;
    if (n && strcmp(n,"onToken")==0) return MID_ONTOKEN;
    if (n && strcmp(n,"onDone")==0)  return MID_ONDONE;
    return (jmethodID)0x3;
}
static void f_CallVoidMethod(JNIEnv env, jobject obj, jmethodID mid, ...){
    (void)env;(void)obj;
    if (mid == MID_ONTOKEN) {
        va_list ap; va_start(ap, mid);
        jstring token = va_arg(ap, jstring);      /* onToken(String) */
        va_end(ap);
        if (token && asstr(token)->s) fputs(asstr(token)->s, stdout);
        fflush(stdout);
    } else if (mid == MID_ONDONE) {
        va_list ap; va_start(ap, mid);
        int ok = va_arg(ap, int);                 /* onDone(boolean) */
        va_end(ap);
        fprintf(stdout, "\n[onDone(%d)]\n", ok);
        fflush(stdout);
    }
}
static void f_DeleteLocalRef(JNIEnv env, jobject o){
    (void)env;
    if(o){ if(asstr(o)->s) free((void*)asstr(o)->s); free(o); }
}
static jobject f_NewGlobalRef(JNIEnv env, jobject o){ (void)env; return o; }
static void f_DeleteGlobalRef(JNIEnv env, jobject o){ (void)env;(void)o; }

/* stub genérico: qualquer chamada JNI não implementada imprime o índice */
static void* stub_unimpl(JNIEnv env, ...){
    (void)env;
    return NULL;
}

static JNINativeInterface g_table;
static Table g_tbl = &g_table;
static JNIEnv  g_env = &g_tbl;

static void setfn(int idx, void* p){ ((void**)&g_table)[idx] = p; }

static void init_jni(void){
    for(int i=0;i<256;i++) setfn(i, (void*)stub_unimpl);
    /* índices conforme jni.h (iguais em todas as arquiteturas) */
    setfn(4,   (void*)f_FindClass);               /* 0x20   FindClass */
    setfn(6,   (void*)f_FindClass);               /* 0x30   (FindClass=6) */
    setfn(21,  (void*)f_NewGlobalRef);            /* 0xa8   NewGlobalRef */
    setfn(22,  (void*)f_DeleteGlobalRef);         /* 0xb0   DeleteGlobalRef */
    setfn(23,  (void*)f_DeleteLocalRef);          /* 0xb8   DeleteLocalRef */
    setfn(31,  (void*)f_GetObjectClass);          /* 0xf8   GetObjectClass */
    setfn(33,  (void*)f_GetMethodID);             /* 0x108  GetMethodID */
    setfn(61,  (void*)f_CallVoidMethod);          /* 0x1e8  CallVoidMethod */
    setfn(163, (void*)f_GetStringLength);         /* 0x518  GetStringLength */
    setfn(164, (void*)f_GetStringUTFLength);      /* 0x520  GetStringUTFLength */
    setfn(167, (void*)f_NewStringUTF);            /* 0x538  NewStringUTF */
    setfn(169, (void*)f_GetStringUTFChars);       /* 0x548  GetStringUTFChars */
    setfn(170, (void*)f_ReleaseStringUTFChars);   /* 0x550  ReleaseStringUTFChars */
    setfn(171, (void*)f_GetArrayLength);          /* 0x558  GetArrayLength */
    setfn(173, (void*)f_GetObjectArrayElement);   /* 0x568  GetObjectArrayElement */
    setfn(179, (void*)f_NewIntArray);             /* 0x598  NewIntArray */
    setfn(181, (void*)f_SetObjectArrayElement);   /* 0x5a8  SetObjectArrayElement */
    setfn(188, (void*)f_NewObjectArray);          /* 0x5e0  NewObjectArray */
    setfn(187, (void*)f_GetIntArrayElements);     /* 0x5d8  GetIntArrayElements */
    setfn(195, (void*)f_ReleaseIntArrayElements); /* 0x618  ReleaseIntArrayElements */
    setfn(199, (void*)f_GetIntArrayRegion);       /* 0x638  GetIntArrayRegion */
    setfn(211, (void*)f_SetIntArrayRegion);       /* 0x698  SetIntArrayRegion */
}

/* ================= crash handler (aarch64) ================= */
static void report_crash(int sig, siginfo_t* si, void* uc_){
    ucontext_t* u = (ucontext_t*)uc_;
    unsigned long pc = u->uc_mcontext.pc;
    unsigned long sp = u->uc_mcontext.sp;
    unsigned long fa = u->uc_mcontext.fault_address;
    fprintf(stderr, "\n>>> CRASH: sinal %d (%s)\n", sig, strsignal(sig));
    fprintf(stderr, ">>> PC=0x%lx  SP=0x%lx  fault_addr=0x%lx (si_addr=0x%lx)\n",
            pc, sp, fa, (unsigned long)si->si_addr);
    fprintf(stderr, ">>> x0=%#lx x1=%#lx x2=%#lx x3=%#lx x4=%#lx x5=%#lx x6=%#lx x7=%#lx\n",
            u->uc_mcontext.regs[0], u->uc_mcontext.regs[1], u->uc_mcontext.regs[2],
            u->uc_mcontext.regs[3], u->uc_mcontext.regs[4], u->uc_mcontext.regs[5],
            u->uc_mcontext.regs[6], u->uc_mcontext.regs[7]);
    /* identifica a função e a .so do PC */
    Dl_info info; memset(&info,0,sizeof info);
    if (dladdr((void*)pc, &info) && info.dli_fname){
        fprintf(stderr, ">>> em %s +0x%lx [%s]\n",
                info.dli_sname?info.dli_sname:"?", pc-(unsigned long)info.dli_saddr,
                info.dli_fname);
    }
    /* a qual .so pertence o PC (via /proc/self/maps do guest) */
    FILE* m = fopen("/proc/self/maps","r");
    if(m){
        char line[512];
        while(fgets(line,sizeof line,m)){
            unsigned long lo,hi; char perm[8], path[256]={0};
            if(sscanf(line,"%lx-%lx %7s %*x %*s %*d %255s",&lo,&hi,perm,path)>=3){
                if(pc>=lo && pc<hi){
                    fprintf(stderr,">>> PC 0x%lx em [%s] (off=0x%lx)\n", pc, path, pc-lo);
                }
            }
        }
        fclose(m);
    }
    /* mini backtrace: caminha x29 (frame pointer), se presente */
    unsigned long fp = u->uc_mcontext.regs[29];
    unsigned long lr = u->uc_mcontext.regs[30];
    fprintf(stderr,">>> LR=0x%lx FP=0x%lx\n", lr, fp);
    for(int i=0;i<16 && fp;i++){
        unsigned long* f = (unsigned long*)fp;
        unsigned long next_fp = f[0];
        unsigned long ret = f[1];
        if(!ret) break;
        Dl_info d2; memset(&d2,0,sizeof d2);
        if(dladdr((void*)ret,&d2) && d2.dli_fname){
            fprintf(stderr,"    #%d 0x%lx %s+0x%lx [%s]\n", i, ret,
                    d2.dli_sname?d2.dli_sname:"?", ret-(unsigned long)d2.dli_saddr, d2.dli_fname);
        } else {
            fprintf(stderr,"    #%d 0x%lx\n", i, ret);
        }
        if(next_fp <= fp) break;   /* evita loop */
        fp = next_fp;
    }
    fflush(stderr);
    _exit(128+sig);
}

/* ================= assinaturas JNI reais ================= */
typedef jint     (*onload_t)(void*, void*);
typedef jlong    (*create_t)(JNIEnv, jclass, jstring, jstring, jint, jint, jint, jboolean);
typedef jstring  (*backendName_t)(JNIEnv, jclass, jlong);
typedef jboolean (*generate_t)(JNIEnv, jclass, jlong, jstring, jint, jfloat, jfloat, jfloat, jfloat, jfloat, jint, jint, jobject);
typedef jintArray(*tokenize_t)(JNIEnv, jclass, jlong, jstring);
typedef jstring  (*detokenize_t)(JNIEnv, jclass, jlong, jintArray);
typedef jstring  (*getmeta_t)(JNIEnv, jclass, jlong, jstring);
typedef jstring  (*gettemplate_t)(JNIEnv, jclass, jlong);
typedef jstring  (*lasterror_t)(JNIEnv, jclass, jlong);
typedef void     (*destroy_t)(JNIEnv, jclass, jlong);
typedef void     (*abort_t)(JNIEnv, jclass, jlong);

static struct myjstr* mkstr(const char* s){
    struct myjstr* m = malloc(sizeof *m); m->s = strdup(s? s:""); return m;
}
static const char* jstr2c(jstring s){ return s? asstr(s)->s : NULL; }

static const char* LIB = "/tmp/sysroot/lib/libaijni.so";

int main(int argc, char** argv){
    struct sigaction sa; memset(&sa,0,sizeof sa);
    sa.sa_sigaction = report_crash; sa.sa_flags = SA_SIGINFO;
    sigaction(SIGTRAP,&sa,0); sigaction(SIGILL,&sa,0); sigaction(SIGABRT,&sa,0);
    sigaction(SIGSEGV,&sa,0); sigaction(SIGBUS,&sa,0); sigaction(SIGFPE,&sa,0);
    setvbuf(stdout,NULL,_IONBF,0); setvbuf(stderr,NULL,_IONBF,0);
    init_jni();

    const char* gguf   = argc>1 ? argv[1] : "/tmp/models/tiny-llama-022.gguf";
    const char* mmproj = argc>2 ? argv[2] : NULL;
    int gpuLayers      = argc>3 ? atoi(argv[3]) : 0;
    int useMmap        = argc>4 ? atoi(argv[4]) : 1;
    const char* only   = argc>5 ? argv[5] : NULL;  /* fase única: onload|create|generate|... */

    void* h = dlopen(LIB, RTLD_NOW|RTLD_GLOBAL);
    if(!h){ fprintf(stderr,"dlopen %s FALHOU: %s\n", LIB, dlerror()); return 2; }
    printf(">>> libaijni.so arm64 REAL do APK carregado\n");

    onload_t onload = (onload_t)dlsym(h,"JNI_OnLoad");
    create_t create = (create_t)dlsym(h,"Java_com_ggufchat_app_Native_create");
    backendName_t backendName = (backendName_t)dlsym(h,"Java_com_ggufchat_app_Native_backendName");
    generate_t generate = (generate_t)dlsym(h,"Java_com_ggufchat_app_Native_generate");
    tokenize_t tokenize = (tokenize_t)dlsym(h,"Java_com_ggufchat_app_Native_tokenize");
    detokenize_t detokenize = (detokenize_t)dlsym(h,"Java_com_ggufchat_app_Native_detokenize");
    getmeta_t getMeta = (getmeta_t)dlsym(h,"Java_com_ggufchat_app_Native_getMeta");
    gettemplate_t getTemplate = (gettemplate_t)dlsym(h,"Java_com_ggufchat_app_Native_getTemplate");
    lasterror_t lastError = (lasterror_t)dlsym(h,"Java_com_ggufchat_app_Native_lastError");
    destroy_t destroy = (destroy_t)dlsym(h,"Java_com_ggufchat_app_Native_destroy");
    abort_t abort_ = (abort_t)dlsym(h,"Java_com_ggufchat_app_Native_abort");
    if(!onload||!create||!backendName||!generate||!tokenize||!detokenize||!destroy){
        fprintf(stderr,"dlsym JNI FALHOU\n"); return 3;
    }

    /* Pré-carrega as .so do engine com binding EAGER (RTLD_NOW|RTLD_GLOBAL),
     * para evitar o lazy-binding do musl (RTLD_LAZY do engine) que resolve
     * errado _ZdlPv/_Znwm sob qemu. Se já estiverem carregadas, o engine
     * reaproveita o handle e não re-reloca. */
    {
        const char* pre[] = {"libunwind.so","libggml.so","libggml-base.so",
                             "libc++_shared.so","libllama.so", NULL};
        for(int i=0; pre[i]; i++){
            void* ph = dlopen(pre[i], RTLD_NOW|RTLD_GLOBAL);
            printf(">>> preload %-18s -> %p %s\n", pre[i], ph, ph?"":"FALHOU");
        }
        /* diagnóstico: onde _ZdlPv resolve, e o conteúdo do slot GOT de
         * libllama.so para _ZdlPv (file off 0x34c750) */
        void* zd = dlsym(RTLD_DEFAULT, "_ZdlPv");
        void* zn = dlsym(RTLD_DEFAULT, "_Znwm");
        Dl_info di; memset(&di,0,sizeof di);
        if(zd && dladdr(zd,&di))
            printf(">>> dlsym _ZdlPv = %p [%s] %s\n", zd, di.dli_fname?di.dli_fname:"?", di.dli_sname?di.dli_sname:"?");
        if(zn && dladdr(zn,&di))
            printf(">>> dlsym _Znwm = %p [%s] %s\n", zn, di.dli_fname?di.dli_fname:"?", di.dli_sname?di.dli_sname:"?");
        void* lmf = dlsym(RTLD_DEFAULT, "llama_model_load_from_file");
        if(lmf){
            unsigned long base = (unsigned long)lmf - 0xf604c;
            unsigned long got = *(unsigned long*)(base + 0x34c750);
            printf(">>> libllama base=%#lx  GOT[_ZdlPv@0x34c750]=%#lx\n", base, got);
        }
    }

    /* ===== fase 1: JNI_OnLoad (o que o Android chama ao carregar a lib) ===== */
    if(!only || !strcmp(only,"onload")){
        printf(">>> JNI_OnLoad() ...\n");
        jint v = onload(g_env, NULL);
        printf(">>> JNI_OnLoad ret=%d (%s)\n", v, v>=0x10000 ? "OK":"FALHOU");
        if(v < 0x10000){ return 4; }
    }
    if(only && !strcmp(only,"onload")) return 0;

    /* ===== fase 2: create ===== */
    if(!only || !strcmp(only,"create")){
        printf(">>> create(model=%s, mmproj=%s, ctx=256, gpuLayers=%d, threads=4, mmap=%d)\n",
               gguf, mmproj?mmproj:"(null)", gpuLayers, useMmap);
        jlong handle = create(g_env, NULL,
                              (jstring)mkstr(gguf),
                              mmproj ? (jstring)mkstr(mmproj) : NULL,
                              256, gpuLayers, 4, useMmap?JNI_TRUE:JNI_FALSE);
        printf(">>> create() ret=0x%lx\n", (unsigned long)handle);
        if(handle == 0){
            jstring e = lastError ? lastError(g_env, NULL, 0) : NULL;
            printf(">>> lastError=%s\n", e&&jstr2c(e)? jstr2c(e) : "(null)");
            if(only && !strcmp(only,"create")) return 5;
            return 5;   /* sem handle não dá p/ continuar */
        }
        printf(">>> handle=0x%lx\n", (unsigned long)handle);

        jstring bn = backendName(g_env, NULL, handle);
        printf(">>> backendName=%s\n", jstr2c(bn)? jstr2c(bn):"(null)");
        jstring tpl = getTemplate ? getTemplate(g_env, NULL, handle) : NULL;
        printf(">>> getTemplate=%s\n", tpl&&jstr2c(tpl)? jstr2c(tpl):"(null)");

        if(!only || !strcmp(only,"generate")){
            /* tokenize / detokenize */
            jintArray toks = tokenize(g_env, NULL, handle, (jstring)mkstr("Hello world"));
            if(toks){ struct myintarr* a=asintarr(toks);
                printf(">>> tokenize(\"Hello world\") = %d tokens\n", a->len);
                jstring det = detokenize(g_env, NULL, handle, toks);
                printf(">>> detokenize = '%s'\n", det&&jstr2c(det)? jstr2c(det):"(null)");
            }
            printf(">>> generate(prompt=\"Hello\", 24 tokens, temp=0.8) ...\n");
            jobject cb = (jobject)0x2;
            jboolean ok = generate(g_env, NULL, handle, (jstring)mkstr("Hello"), 24,
                                   0.8f, 0.95f, 40.0f, 0.05f, 1.1f, 64, 1234, cb);
            printf("\n>>> generate() ret=%d (%s)\n", ok, ok?"TRUE":"FALSE");
        }

        destroy(g_env, NULL, handle);
        printf(">>> destroy() OK\n");
    }

    printf(">>> ===== camada nativa arm64 do APK executou SEM CRASH =====\n");
    return 0;
}
