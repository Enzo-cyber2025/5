#ifndef GGUF_VULKAN_COMPAT_POLICY_H
#define GGUF_VULKAN_COMPAT_POLICY_H
#include <stdint.h>
// VK_KHR_16bit_storage was promoted to Vulkan 1.1. A missing alias is
// dispensable only when the real physical device offers the core feature.
static inline int gguf_core_16bit_alias(uint32_t api, uint32_t storage, int advertised) {
    return api >= ((1u << 22) | (1u << 12)) && storage != 0 && !advertised;
}
#endif
