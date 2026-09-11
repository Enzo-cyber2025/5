#define _GNU_SOURCE
#define JNI_FALSE 0
#define JNI_TRUE 1
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdbool.h>
#include <signal.h>
#include <execinfo.h>
#include <ucontext.h>

/* ============ mini-JNI (o suficiente p/ o libaijni.so REAL do APK) ============ */
typedef struct JNINativeInterface { void* fns[256]; } JNINativeInterface;
typedef const JNINativeInterface* Table;
typedef Table* JNIEnv;            /* JNIEnv = ponteiro p/ ponteiro p/ tabela */
typedef void* jobject;
typedef void* jclass;
typedef void* jstring;
typedef void* jarray;
typedef void* jobjectArray;
typedef void* jintArray;
typedef int    jint;
typedef int    jsize;
typedef int    jboolean;
typedef long   jlong;
typedef float  jfloat;
typedef void*  jmethodID;

struct myjstr { const char* s; };
struct myintarr { jint len; jint data[4096]; };

static const char* f_GetStringUTFChars(JNIEnv env, jstring s, jboolean* isCopy){
    if(isCopy) *isCopy = JNI_FALSE;
    return ((struct myjstr*)s)->s;
}
static void f_ReleaseStringUTFChars(JNIEnv env, jstring s, const char* p){ (void)env;(void)s;(void)p; }
static jstring f_NewStringUTF(JNIEnv env, const char* u){
    struct myjstr* m = malloc(sizeof *m);
    m->s = strdup(u);
    return (jstring)m;
}
static jsize f_GetArrayLength(JNIEnv env, jarray a){ return ((struct myintarr*)a)->len; }
static jobject f_GetObjectArrayElement(JNIEnv env, jobjectArray a, jsize i){
    return ((jobject*)a)[i];
}
static jintArray f_NewIntArray(JNIEnv env, jsize n){
    struct myintarr* a = calloc(1, sizeof *a);
    a->len = n;
    return (jintArray)a;
}
/* slot 187 (0x5d8) GetIntArrayElements — retorna ponteiro direto p/ os dados */
static jint* f_GetIntArrayElements(JNIEnv env, jintArray a, jboolean* isCopy){
    if(isCopy) *isCopy = JNI_FALSE;
    return ((struct myintarr*)a)->data;
}
/* slot 195 (0x618) ReleaseIntArrayElements — ponteiro direto => nada a fazer */
static void f_ReleaseIntArrayElements(JNIEnv env, jintArray a, jint* elems, jint mode){
    (void)env;(void)a;(void)elems;(void)mode;
}
/* slot 211 (0x698) SetIntArrayRegion */
static void f_SetIntArrayRegion(JNIEnv env, jintArray a, jsize s, jsize l, const jint* in){
    memcpy(&((struct myintarr*)a)->data[s], in, l*sizeof(jint));
}
static jclass f_GetObjectClass(JNIEnv env, jobject o){ (void)env;(void)o; return (jclass)0x1; }
#define MID_ONTOKEN ((jmethodID)0x1)
#define MID_ONDONE  ((jmethodID)0x2)
static jmethodID f_GetMethodID(JNIEnv env, jclass c, const char* n, const char* sig){
    (void)env;(void)c;(void)sig;
    if (n && strcmp(n, "onToken") == 0) return MID_ONTOKEN;
    if (n && strcmp(n, "onDone")  == 0) return MID_ONDONE;
    return (jmethodID)0x3;
}
static void f_CallVoidMethod(JNIEnv env, jobject obj, jmethodID mid, ...){
    (void)env;(void)obj;
    if (mid == MID_ONTOKEN) {
        va_list ap; va_start(ap, mid);
        jstring token = va_arg(ap, jstring);   /* onToken(String) */
        va_end(ap);
        if (token) { const char* s = ((struct myjstr*)token)->s; if (s) fputs(s, stdout); }
        fflush(stdout);
    } else if (mid == MID_ONDONE) {
        va_list ap; va_start(ap, mid);
        int ok = va_arg(ap, int);              /* onDone(boolean) */
        va_end(ap);
        fprintf(stdout, "\n[onDone(%d)]\n", ok);
        fflush(stdout);
    } else {
        /* outro método: ignora */
    }
}
static void f_DeleteLocalRef(JNIEnv env, jobject o){
    (void)env;
    if(o){ free((void*)((struct myjstr*)o)->s); free((struct myjstr*)o); }
}

static JNINativeInterface g_table;
static Table g_tbl = &g_table;
static JNIEnv  g_env = &g_tbl;

static void setfn(int idx, void* p){ ((void**)&g_table)[idx] = p; }

/* ============ assinaturas JNI reais do libaijni.so ============ */
typedef jint   (*onload_t)(void*, void*);
typedef jlong  (*create_t)(JNIEnv, jclass, jstring, jstring, jint, jint, jint, jboolean);
typedef jstring (*backendName_t)(JNIEnv, jclass, jlong);
typedef jboolean (*generate_t)(JNIEnv, jclass, jlong, jstring, jint, jfloat, jfloat, jfloat, jfloat, jfloat, jint, jint, jobject);
typedef jintArray (*tokenize_t)(JNIEnv, jclass, jlong, jstring);
typedef jstring (*detokenize_t)(JNIEnv, jclass, jlong, jintArray);
typedef void   (*destroy_t)(JNIEnv, jclass, jlong);

static void crash(int sig, siginfo_t* si, void* uc){
    void* rip = si->si_addr;
#if defined(__x86_64__)
    ucontext_t* u = (ucontext_t*)uc;
    rip = (void*)u->uc_mcontext.gregs[REG_RIP];
#endif
    fprintf(stderr, "\n>>> CRASH: sinal %d (%s) em RIP=0x%lx (falha em 0x%lx)\n",
            sig, strsignal(sig), (unsigned long)rip, (unsigned long)si->si_addr);
#if defined(__x86_64__)
    {
        ucontext_t* u = (ucontext_t*)uc;
        greg_t* g = u->uc_mcontext.gregs;
        fprintf(stderr, ">>> regs: rax=%#lx rbx=%#lx rcx=%#lx rdx=%#lx rsi=%#lx rdi=%#lx rbp=%#lx rsp=%#lx\n",
            (unsigned long)g[REG_RAX],(unsigned long)g[REG_RBX],(unsigned long)g[REG_RCX],
            (unsigned long)g[REG_RDX],(unsigned long)g[REG_RSI],(unsigned long)g[REG_RDI],
            (unsigned long)g[REG_RBP],(unsigned long)g[REG_RSP]);
        fprintf(stderr, ">>> regs: r8=%#lx r9=%#lx r10=%#lx r11=%#lx r12=%#lx r13=%#lx r14=%#lx r15=%#lx\n",
            (unsigned long)g[REG_R8],(unsigned long)g[REG_R9],(unsigned long)g[REG_R10],
            (unsigned long)g[REG_R11],(unsigned long)g[REG_R12],(unsigned long)g[REG_R13],
            (unsigned long)g[REG_R14],(unsigned long)g[REG_R15]);
    }
#endif
    void* bt[30]; int n = backtrace(bt, 30);
    char** syms = backtrace_symbols(bt, n);
    Dl_info info;
    for(int i=0;i<n;i++){
        if(dladdr(bt[i], &info) && info.dli_fname){
            long off=(char*)bt[i]-(char*)info.dli_fbase;
            fprintf(stderr, "    #%d 0x%lx  %s +0x%lx [%s +0x%lx]\n", i,
                (unsigned long)bt[i], info.dli_sname?info.dli_sname:"?",
                (char*)bt[i]-(char*)info.dli_saddr, info.dli_fname, off);
        } else fprintf(stderr, "    #%d 0x%lx %s\n", i, (unsigned long)bt[i], syms? syms[i]:"?");
    }
    /* localiza a qual .so pertence o RIP de crash via /proc/self/maps */
    FILE* m = fopen("/proc/self/maps","r");
    if(m){
        char line[512];
        while(fgets(line,sizeof line,m)){
            unsigned long lo,hi; char perm[8], path[256]={0};
            if(sscanf(line,"%lx-%lx %7s %*x %*s %*d %255s", &lo,&hi,perm,path)>=3){
                if((unsigned long)rip>=lo && (unsigned long)rip<hi){
                    fprintf(stderr,"    >>> RIP 0x%lx pertence a [%s] (0x%lx-0x%lx, off=0x%lx)\n",
                        (unsigned long)rip, path, lo, hi, (unsigned long)rip-lo);
                }
            }
        }
        fclose(m);
    }
    fflush(stderr); _exit(128+sig);
}

static struct myjstr* mkstr(const char* s){
    struct myjstr* m = malloc(sizeof *m);
    m->s = strdup(s);
    return m;
}

int main(int argc, char** argv){
    struct sigaction sa; memset(&sa,0,sizeof sa);
    sa.sa_sigaction=crash; sa.sa_flags=SA_SIGINFO;
    sigaction(SIGTRAP,&sa,0); sigaction(SIGILL,&sa,0); sigaction(SIGABRT,&sa,0);
    sigaction(SIGSEGV,&sa,0); sigaction(SIGBUS,&sa,0); sigaction(SIGFPE,&sa,0);
    setvbuf(stdout,NULL,_IONBF,0); setvbuf(stderr,NULL,_IONBF,0);

    /* preenche os slots da JNINativeInterface usados pelo libaijni.so real */
    setfn(167, (void*)f_NewStringUTF);           /* 0x538 */
    setfn(169, (void*)f_GetStringUTFChars);      /* 0x548 */
    setfn(170, (void*)f_ReleaseStringUTFChars);  /* 0x550 */
    setfn(171, (void*)f_GetArrayLength);         /* 0x558 */
    setfn(173, (void*)f_GetObjectArrayElement);  /* 0x568 */
    setfn(179, (void*)f_NewIntArray);            /* 0x598 */
    setfn(187, (void*)f_GetIntArrayElements);    /* 0x5d8 */
    setfn(195, (void*)f_ReleaseIntArrayElements);/* 0x618 */
    setfn(211, (void*)f_SetIntArrayRegion);      /* 0x698 */
    setfn(31,  (void*)f_GetObjectClass);         /* 0xf8  */
    setfn(33,  (void*)f_GetMethodID);            /* 0x108 */
    setfn(23,  (void*)f_DeleteLocalRef);         /* 0xb8  */
    setfn(61,  (void*)f_CallVoidMethod);         /* 0x1e8 */

    void* h = dlopen("libaijni.so", RTLD_NOW|RTLD_GLOBAL);
    if(!h){ fprintf(stderr,"dlopen libaijni.so FALHOU: %s\n", dlerror()); return 2; }
    printf(">>> libaijni.so REAL do APK carregado\n");

    onload_t onload = (onload_t)dlsym(h, "JNI_OnLoad");
    create_t create = (create_t)dlsym(h, "Java_com_ggufchat_app_Native_create");
    backendName_t backendName = (backendName_t)dlsym(h, "Java_com_ggufchat_app_Native_backendName");
    generate_t generate = (generate_t)dlsym(h, "Java_com_ggufchat_app_Native_generate");
    tokenize_t tokenize = (tokenize_t)dlsym(h, "Java_com_ggufchat_app_Native_tokenize");
    detokenize_t detokenize = (detokenize_t)dlsym(h, "Java_com_ggufchat_app_Native_detokenize");
    destroy_t destroy = (destroy_t)dlsym(h, "Java_com_ggufchat_app_Native_destroy");
    if(!onload||!create||!backendName||!generate||!destroy){
        fprintf(stderr,"dlsym FALHOU (JNI)\n"); return 3;
    }

    printf(">>> JNI_OnLoad(NULL,NULL) ...\n");
    jint v = onload(NULL, NULL);
    printf(">>> JNI_OnLoad ret=%d (>=0x10000 = OK; 0 = falhou)\n", v);

    const char* gguf    = argc>1 ? argv[1] : "/tmp/tiny-llama-022.gguf";
    const char* mmproj  = argc>2 ? argv[2] : "/tmp/tiny-mmproj-022.gguf";
    int gpuLayers       = argc>3 ? atoi(argv[3]) : 0;

    printf(">>> create(model=%s, mmproj=%s, ctx=256, threads=4, gpuLayers=%d, mmap=false)\n", gguf, mmproj, gpuLayers);
    jlong handle = create(g_env, NULL, (jstring)mkstr(gguf), (jstring)mkstr(mmproj), 256, 4, gpuLayers, JNI_FALSE);
    if(!handle){ fprintf(stderr,">>> create() retornou 0 (FALHOU o load do modelo)\n"); return 4; }
    printf(">>> create() OK — handle=0x%lx\n", (unsigned long)handle);

    jstring bn = backendName(g_env, NULL, handle);
    printf(">>> backendName = '%s'\n", ((struct myjstr*)bn)->s);

    jintArray toks = tokenize(g_env, NULL, handle, (jstring)mkstr("hello world"));
    if(toks){ struct myintarr* a=(struct myintarr*)toks; printf(">>> tokenize(\"hello world\") = %d tokens\n", a->len); }

    printf(">>> generate(prompt=\"Ola\", 32 tokens, temp=0.8, callback ativo) ...\n");
    jobject cb = (jobject)0x2;   /* não-nulo: gera E transmite token a token */
    jboolean ok = generate(g_env, NULL, handle, (jstring)mkstr("Ola"), 32,
                           0.8f, 0.95f, 40.0f, 0.05f, 1.1f, 64, 1234, cb);
    printf("\n>>> generate() ret=%d (%s)\n", ok, ok?"TRUE":"FALSE");

    destroy(g_env, NULL, handle);
    printf(">>> destroy() OK\n");
    printf(">>> ===== EXECUÇÃO REAL DA CAMADA NATIVA DO APK CONCLUÍDA SEM CRASH =====\n");
    return 0;
}
