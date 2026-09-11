#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <signal.h>
#include <execinfo.h>
#include <stdlib.h>
#include <unistd.h>

typedef void* (*fp_t)(void*, size_t);
typedef void* (*bt_t)(void);
typedef void* (*bf_t)(void*, size_t);
typedef void* (*gbase_t)(void*);
typedef void (*bfree_t)(void*);

static void handler(int sig, siginfo_t *si, void *uc){
    fprintf(stderr, "\n>>> SINAL %d (%s) em RIP=0x%lx\n", sig, strsignal(sig), (unsigned long)si->si_addr);
    void *bt[16]; int n = backtrace(bt, 16);
    char **syms = backtrace_symbols(bt, n);
    Dl_info info;
    for(int i=0;i<n;i++){
        if (dladdr(bt[i], &info) && info.dli_fname && info.dli_saddr){
            long off = (char*)bt[i] - (char*)info.dli_fbase;
            long soff = (char*)bt[i] - (char*)info.dli_saddr;
            fprintf(stderr, "    #%d 0x%lx  %s +0x%lx  [%s +0x%lx]\n",
                i, (unsigned long)bt[i], info.dli_sname?info.dli_sname:"?", soff, info.dli_fname, off);
        } else {
            fprintf(stderr, "    #%d %s\n", i, syms? syms[i]:"?");
        }
    }
    fflush(stderr);
    _exit(133);
}

int main(int argc, char**argv){
    struct sigaction sa; memset(&sa,0,sizeof sa);
    sa.sa_sigaction = handler; sa.sa_flags = SA_SIGINFO;
    sigaction(SIGTRAP,&sa,0); sigaction(SIGILL,&sa,0); sigaction(SIGABRT,&sa,0);
    sigaction(SIGSEGV,&sa,0); sigaction(SIGBUS,&sa,0); sigaction(SIGFPE,&sa,0);

    void *h = dlopen("libggml-base.so", RTLD_NOW|RTLD_GLOBAL);
    if(!h){ fprintf(stderr,"dlopen FALHOU: %s\n", dlerror()); return 2; }
    printf(">>> libggml-base.so REAL do APK carregado (base=%p)\n", h);

    fp_t cpu_from_ptr = (fp_t)dlsym(h, "ggml_backend_cpu_buffer_from_ptr");
    bt_t cpu_type = (bt_t)dlsym(h, "ggml_backend_cpu_buffer_type");
    bf_t buft_alloc = (bf_t)dlsym(h, "ggml_backend_buft_alloc_buffer");
    gbase_t get_base = (gbase_t)dlsym(h, "ggml_backend_buffer_get_base");
    bfree_t buf_free = (bfree_t)dlsym(h, "ggml_backend_buffer_free");
    if(!cpu_from_ptr||!cpu_type||!buft_alloc||!get_base||!buf_free){ fprintf(stderr,"dlsym FALHOU\n"); return 3; }
    printf(">>> get_base=%p cpu_from_ptr=%p\n", (void*)get_base, (void*)cpu_from_ptr);

    size_t size = 1024*1024 + 32;
    int mode = (argc>1 && !strcmp(argv[1],"fix"));

    if(!mode){
        printf(">>> [BUG] cpu_buffer_from_ptr(nullptr, %zu) -> get_base (caminho REAL do APK)\n", size);
        fflush(stdout);
        void *buf = cpu_from_ptr(NULL, size);
        printf("    buffer criado (buf=%p), chamando get_base...\n", buf);
        fflush(stdout);
        void *base = get_base(buf);
        printf("    base=%p\n", base);
        buf_free(buf);
    } else {
        printf(">>> [FIX] buft_alloc_buffer(cpu_buffer_type(), %zu) -> get_base\n", size);
        fflush(stdout);
        void *buf = buft_alloc(cpu_type(), size);
        void *base = get_base(buf);
        printf("    FIX OK: base=%p\n", base);
        buf_free(buf);
    }
    printf("OK\n");
    return 0;
}
