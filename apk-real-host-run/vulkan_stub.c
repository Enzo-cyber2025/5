#include <stdint.h>
#include <string.h>

#define VK_SUCCESS 0
#define VK_MAKE_API_VERSION_1_0 4194304u  /* VK_MAKE_API_VERSION(0,1,0,0) < 1.2 */

typedef int32_t VkResult;

/* Vulkan 1.0 -> ggml_vulkan exige 1.2, entao lança vk::SystemError("Vulkan 1.2 required"),
   que ggml_backend_vk_reg() captura e retorna nullptr -> backend pulado graciosamente. */
static VkResult my_vkEnumerateInstanceVersion(uint32_t *pApiVersion){
    if (pApiVersion) *pApiVersion = VK_MAKE_API_VERSION_1_0;
    return VK_SUCCESS;
}

void * vkGetInstanceProcAddr(void *instance, const char *name){
    (void)instance;
    if (name && strcmp(name, "vkEnumerateInstanceVersion") == 0) {
        return (void*)&my_vkEnumerateInstanceVersion;
    }
    return 0; /* demais entradas: NULL (nunca chegam a ser chamadas: init falha antes) */
}
void * vkGetDeviceProcAddr(void *d, const char *n){ (void)d;(void)n; return 0; }
void * vkGetPhysicalDeviceFeatures2(void *a, void *b){ (void)a;(void)b; return 0; }
void vkCmdCopyBuffer(void *a, void *b, void *c, uint32_t d, uint32_t e, const void *f){ (void)a;(void)b;(void)c;(void)d;(void)e;(void)f; }
