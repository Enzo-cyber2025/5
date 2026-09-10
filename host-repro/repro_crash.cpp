// Reprodução do crash nativo "ao abrir conversa" no nível do ggml.
//
// Contexto (app GGUF Chat, llama.cpp / llamarn 0.10.5, commit ggml 50f068...):
//   ggml_backend_vk_host_buffer_type_alloc_buffer() chama ggml_vk_host_malloc().
//   Quando a alocação de memória "pinned" (host-visible) da GPU FALHA SEM lançar
//   exceção, ggml_vk_host_malloc() devolve `nullptr`. O chamador só trata
//   vk::SystemError (exceção), NÃO o retorno nulo, e segue para
//   ggml_backend_cpu_buffer_from_ptr(nullptr, size). O buffer é criado com
//   context = nullptr e, quando o loader pede a base do buffer
//   (ggml_backend_buffer_get_base), dispara GGML_ASSERT(base != NULL) -> abort
//   do processo nativo -> o app "crashou na hora de abrir".
//
// Uso (linkar contra a libggml-base do llama.cpp):
//   g++ repro_crash.cpp -I<ggml include> -L<lib dir> -lggml-base -o repro_crash
//   ./repro_crash bug   # reproduz o crash (SIGABRT, exit 134)
//   ./repro_crash fix   # demonstra a correção (fallback CPU), exit 0
#include "ggml-backend.h"
#include <cstdio>
#include <cstring>

static void scenario_bug() {
    // Caminho EXATO do código com bug (sem checagem de nullptr):
    size_t size = (size_t)(1u << 20) + 32; // alloc_buffer faz: size += 32
    void * ptr = nullptr;                  // ggml_vk_host_malloc() falhou -> nullptr
    ggml_backend_buffer_t buffer = ggml_backend_cpu_buffer_from_ptr(ptr, size);
    printf("buffer criado com ptr=nullptr; chamando get_base (aqui crasha):\n");
    fflush(stdout);
    void * base = ggml_backend_buffer_get_base(buffer); // GGML_ASSERT(base != NULL) -> abort
    printf("base = %p (nao deveria chegar aqui)\n", base);
}

static void scenario_fix() {
    // Correção (equivalente ao patch binário do APK / fallback do upstream):
    size_t size = (size_t)(1u << 20) + 32;
    void * ptr = nullptr; // falha simulada
    ggml_backend_buffer_t buffer;
    if (ptr == nullptr) {
        buffer = ggml_backend_buft_alloc_buffer(ggml_backend_cpu_buffer_type(), size);
    } else {
        buffer = ggml_backend_cpu_buffer_from_ptr(ptr, size);
    }
    void * base = ggml_backend_buffer_get_base(buffer);
    printf("FIX OK: buffer CPU alocado, base=%p, size=%zu\n",
           base, ggml_backend_buffer_get_size(buffer));
    ggml_backend_buffer_free(buffer);
}

int main(int argc, char ** argv) {
    if (argc > 1 && strcmp(argv[1], "fix") == 0) { scenario_fix(); return 0; }
    scenario_bug();
    return 0;
}
