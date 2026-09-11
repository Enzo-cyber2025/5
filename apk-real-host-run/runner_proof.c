/* Prova o crash dentro do .so REAL do APK, mapeando o RIP do trap. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <signal.h>
#include <ucontext.h>
#include <unistd.h>
#include <stdint.h>
#include <stdlib.h>

static void handler(int sig, siginfo_t *si, void *uc_) {
    ucontext_t *uc = (ucontext_t*)uc_;
    uintptr_t rip = uc->uc_mcontext.gregs[REG_RIP];
    fprintf(stderr, "\n>>> TRAP/ASSERT (sig=%d) em RIP=%p\n", sig, (void*)rip);
    FILE *m = fopen("/proc/self/maps", "r");
    char line[512]; uintptr_t bestlo = 0; char best[512] = {0};
    while (fgets(line, sizeof line, m)) {
        uintptr_t lo, hi; char rest[256];
        if (sscanf(line, "%lx-%lx %*s %*s %*s %*s %255[^\n]", &lo, &hi, rest) == 3
            && rip >= lo && rip < hi && lo >= bestlo) {
            bestlo = lo; snprintf(best, sizeof best, "%s", rest);
        }
    }
    fprintf(stderr, ">>> dentro de: %s (offset 0x%lx)\n", best, rip - bestlo);
    fclose(m);
    _exit(133);
}

typedef void* (*fp_t)(void*, size_t);
typedef void* (*gbase_t)(void*);

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    struct sigaction sa = {0};
    sa.sa_sigaction = handler; sa.sa_flags = SA_SIGINFO;
    sigaction(SIGTRAP, &sa, 0);
    sigaction(SIGILL, &sa, 0);
    sigaction(SIGABRT, &sa, 0);

    void *h = dlopen("libggml-base.so", RTLD_NOW | RTLD_GLOBAL);
    if (!h) { fprintf(stderr, "dlopen FALHOU: %s\n", dlerror()); return 2; }
    printf(">>> libggml-base.so REAL do APK carregado\n");

    fp_t    cpu_from_ptr = (fp_t)    dlsym(h, "ggml_backend_cpu_buffer_from_ptr");
    gbase_t get_base     = (gbase_t) dlsym(h, "ggml_backend_buffer_get_base");
    printf(">>> cpu_from_ptr=%p get_base=%p (endereços no .so REAL do APK)\n",
           cpu_from_ptr, get_base);
    printf(">>> caminho BUG: cpu_from_ptr(NULL, 1048608) -> get_base(buf)\n");
    fflush(stdout);

    void *buf  = cpu_from_ptr(NULL, 1024 * 1024 + 32);
    void *base = get_base(buf);   /* GGML_ASSERT dispara aqui */
    printf(">>> base=%p\n", base);
    return 0;
}
