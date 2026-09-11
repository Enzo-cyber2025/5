#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

typedef void* (*fp_t)(void*, size_t);
typedef void* (*bt_t)(void);
typedef void* (*bf_t)(void*, size_t);
typedef void* (*gbase_t)(void*);
typedef void  (*bfree_t)(void*);

int main(int argc, char **argv) {
    void *h = dlopen("libggml-base.so", RTLD_NOW | RTLD_GLOBAL);
    if (!h) { fprintf(stderr, "dlopen FALHOU: %s\n", dlerror()); return 2; }
    printf(">>> libggml-base.so REAL do APK carregado com sucesso\n");

    fp_t    cpu_from_ptr = (fp_t)    dlsym(h, "ggml_backend_cpu_buffer_from_ptr");
    bt_t    cpu_type     = (bt_t)    dlsym(h, "ggml_backend_cpu_buffer_type");
    bf_t    buft_alloc   = (bf_t)    dlsym(h, "ggml_backend_buft_alloc_buffer");
    gbase_t get_base     = (gbase_t) dlsym(h, "ggml_backend_buffer_get_base");
    bfree_t buf_free     = (bfree_t) dlsym(h, "ggml_backend_buffer_free");
    if (!cpu_from_ptr || !cpu_type || !buft_alloc || !get_base || !buf_free) {
        fprintf(stderr, "dlsym FALHOU: %s\n", dlerror()); return 3;
    }
    printf(">>> símbolos resolvidos do APK (cpu_from_ptr=%p, get_base=%p)\n",
           cpu_from_ptr, get_base);

    size_t size = 1024 * 1024 + 32;
    int fix = (argc > 1 && !strcmp(argv[1], "fix"));

    if (!fix) {
        /* Caminho exato do APK quando a alocação "pinned" Vulkan falha sem
           exceção: cria um buffer CPU a partir de um ponteiro NULO. */
        printf(">>> [BUG] cpu_buffer_from_ptr(nullptr, %zu) -> get_base\n", size);
        void *buf = cpu_from_ptr(NULL, size);
        fflush(stdout);
        void *base = get_base(buf);   /* GGML_ASSERT(base != NULL) dispara aqui */
        printf("    base=%p\n", base);
        buf_free(buf);
    } else {
        /* Fallback correto: alocar um buffer CPU de verdade. */
        printf(">>> [FIX] buft_alloc_buffer(cpu_buffer_type(), %zu)\n", size);
        void *buf = buft_alloc(cpu_type(), size);
        void *base = get_base(buf);
        printf("    FIX OK: buffer CPU alocado, base=%p\n", base);
        buf_free(buf);
    }
    printf("OK\n");
    return 0;
}
