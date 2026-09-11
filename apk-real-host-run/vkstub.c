/* Stub de libggml-vulkan.so usado SOMENTE no harness de host (/tmp/android-run).
 * Simula "nenhuma GPU Vulkan disponível" — o mesmo fallback que o app real faz
 * em aparelho sem Vulkan 1.2 (usa CPU). NÃO altera o APK real.
 *
 * Motivo: no host sem Vulkan, o libggml-vulkan.so REAL do APK imprime
 * "ggml_vulkan: Error: Vulkan 1.2 required." e lança vk::SystemError; o
 * desenrolar de exceção C++ (libc++ do Android vs libgcc_s/glibc do host)
 * quebra e o processo pula para endereço inválido (SIGSEGV). */
void* ggml_backend_init(void){ return 0; }
int   ggml_backend_score(void){ return 0; }
void* ggml_backend_vk_reg(void){ return 0; }
void* ggml_backend_vk_init(void){ return 0; }
