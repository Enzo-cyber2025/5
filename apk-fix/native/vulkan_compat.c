// Vulkan 1.1 promoted-extension compatibility, not a Vulkan implementation.
// Every operation is performed by Android's real loader/driver. Never invent
// extension names, features, devices, successful results, or CPU fallbacks.
#include <vulkan/vulkan.h>
#include <android/log.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include "vulkan_compat_policy.h"

static void *loader;
static pthread_once_t once = PTHREAD_ONCE_INIT;
static PFN_vkGetInstanceProcAddr real_gipa;
static PFN_vkGetDeviceProcAddr real_gdpa;
static PFN_vkCreateDevice real_create;
static PFN_vkGetPhysicalDeviceProperties real_properties;
static PFN_vkGetPhysicalDeviceFeatures2 real_features;
static PFN_vkEnumerateDeviceExtensionProperties real_extensions;
static PFN_vkCmdCopyBuffer real_copy;

static void load(void) {
    loader = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
    if (!loader) return;
#define RESOLVE(dst, name) dst = (PFN_##name)dlsym(loader, #name)
    RESOLVE(real_gipa, vkGetInstanceProcAddr);
    RESOLVE(real_gdpa, vkGetDeviceProcAddr);
    RESOLVE(real_create, vkCreateDevice);
    RESOLVE(real_properties, vkGetPhysicalDeviceProperties);
    RESOLVE(real_features, vkGetPhysicalDeviceFeatures2);
    RESOLVE(real_extensions, vkEnumerateDeviceExtensionProperties);
    RESOLVE(real_copy, vkCmdCopyBuffer);
#undef RESOLVE
}

static VKAPI_ATTR VkResult VKAPI_CALL create_device(VkPhysicalDevice physical,
        const VkDeviceCreateInfo *info, const VkAllocationCallbacks *allocator,
        VkDevice *device) {
    pthread_once(&once, load);
    if (!real_create) return VK_ERROR_INITIALIZATION_FAILED;
    // A null input is invalid; never dereference it or manufacture success.
    if (!physical || !info || !device) return VK_ERROR_INITIALIZATION_FAILED;
    int requested = 0;
    for (uint32_t i = 0; i < info->enabledExtensionCount; ++i)
        if (!strcmp(info->ppEnabledExtensionNames[i], "VK_KHR_16bit_storage")) requested = 1;
    if (!requested || !real_properties || !real_features || !real_extensions)
        return real_create(physical, info, allocator, device);

    VkPhysicalDeviceProperties properties;
    real_properties(physical, &properties);
    if (properties.apiVersion < VK_API_VERSION_1_1)
        return real_create(physical, info, allocator, device);
    VkPhysicalDevice16BitStorageFeatures storage = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_16BIT_STORAGE_FEATURES,
    };
    VkPhysicalDeviceFeatures2 features = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &storage,
    };
    real_features(physical, &features);
    uint32_t count = 0;
    VkResult result = real_extensions(physical, NULL, &count, NULL);
    if (result != VK_SUCCESS) return result;
    VkExtensionProperties *extensions = calloc(count ? count : 1, sizeof(*extensions));
    if (!extensions) return VK_ERROR_OUT_OF_HOST_MEMORY;
    result = real_extensions(physical, NULL, &count, extensions);
    if (result != VK_SUCCESS) { free(extensions); return result; }
    int advertised = 0;
    for (uint32_t i = 0; i < count; ++i)
        if (!strcmp(extensions[i].extensionName, "VK_KHR_16bit_storage")) advertised = 1;
    free(extensions);
    if (!gguf_core_16bit_alias(properties.apiVersion, storage.storageBuffer16BitAccess, advertised))
        return real_create(physical, info, allocator, device);

    const char **names = calloc(info->enabledExtensionCount, sizeof(*names));
    if (!names) return VK_ERROR_OUT_OF_HOST_MEMORY;
    VkDeviceCreateInfo compatible = *info;
    compatible.enabledExtensionCount = 0;
    compatible.ppEnabledExtensionNames = names;
    for (uint32_t i = 0; i < info->enabledExtensionCount; ++i) {
        const char *name = info->ppEnabledExtensionNames[i];
        if (strcmp(name, "VK_KHR_16bit_storage"))
            names[compatible.enabledExtensionCount++] = name;
    }
    // pNext, all requested feature bits, queues and every other extension remain
    // untouched. The actual driver must still validate and create the device.
    result = real_create(physical, &compatible, allocator, device);
    __android_log_print(ANDROID_LOG_INFO, "GGUFVulkanCompat",
        "Core 1.1 16-bit storage verified; omitted unadvertised KHR alias; vkCreateDevice=%d", result);
    free(names);
    return result;
}

// Unique import names prevent symbol interposition by an already-loaded system
// libvulkan. Only the bundled ggml Vulkan backend links against these four.
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL gfGetInstanceProcAddr(VkInstance instance, const char *name) {
    pthread_once(&once, load);
    if (!real_gipa || !name) return NULL;
    PFN_vkVoidFunction original = real_gipa(instance, name);
    if (original && !strcmp(name, "vkCreateDevice")) return (PFN_vkVoidFunction)create_device;
    return original;
}
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL gfGetDeviceProcAddr(VkDevice device, const char *name) {
    pthread_once(&once, load);
    return real_gdpa ? real_gdpa(device, name) : NULL;
}
VKAPI_ATTR void VKAPI_CALL gfGetPhysicalDeviceFeatures2(VkPhysicalDevice physical, VkPhysicalDeviceFeatures2 *features) {
    pthread_once(&once, load);
    if (!real_features) abort();
    real_features(physical, features);
}
VKAPI_ATTR void VKAPI_CALL gfCmdCopyBuffer(VkCommandBuffer command, VkBuffer src, VkBuffer dst,
        uint32_t count, const VkBufferCopy *regions) {
    pthread_once(&once, load);
    if (!real_copy) abort();
    real_copy(command, src, dst, count, regions);
}
