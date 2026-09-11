// Reproduz o crash do app: buffer backend criado a partir de ponteiro NULO
// (o que a função do Vulkan faz quando a memória "pinned" falha sem exceção),
// e valida a correção (fallback para buffer CPU).
#include "ggml/include/ggml.h"
#include "ggml/include/ggml-backend.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>

static void run(bool fixed) {
    void *ptr = nullptr;         // simula ggml_vk_host_malloc() retornando nullptr
    size_t size = 1024 * 1024 + 32;

    ggml_backend_buffer_t buffer;
    if (fixed) {
        if (ptr == nullptr) {
            // === CORREÇÃO APLICADA NO APK (arm64 + x86_64) ===
            buffer = ggml_backend_buft_alloc_buffer(ggml_backend_cpu_buffer_type(), size);
            printf("FIX: ponteiro nulo -> buffer CPU alocado\n");
        } else {
            buffer = ggml_backend_cpu_buffer_from_ptr(ptr, size);
        }
    } else {
        // === CÓDIGO ORIGINAL (bug) ===
        buffer = ggml_backend_cpu_buffer_from_ptr(ptr, size);
        printf("BUG: buffer criado a partir de ponteiro nulo\n");
    }

    // O loader faz isto; aqui o app crasha no caminho original
    void *base = ggml_backend_buffer_get_base(buffer);
    printf("get_base() = %p\n", base);
    ggml_backend_buffer_free(buffer);
}

int main(int argc, char **argv) {
    bool fixed = argc > 1 && strcmp(argv[1], "fix") == 0;
    printf("=== caminho %s ===\n", fixed ? "CORRIGIDO" : "ORIGINAL (bug)");
    run(fixed);
    printf("OK (sem crash)\n");
    return 0;
}
