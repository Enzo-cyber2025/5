// Preserve the real native stderr diagnostics before the JNI bridge loads.
// No Vulkan version spoofing, tensor changes, or synthetic offload messages.
#include <android/log.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/system_properties.h>
#include <unistd.h>

#define TAG "GGUFNativeStderr"

static void *forward_stderr(void *arg) {
    const int fd = (int)(intptr_t)arg;
    char input[1024], line[3001];
    size_t used = 0;
    for (;;) {
        ssize_t size = read(fd, input, sizeof(input));
        if (size < 0 && errno == EINTR) continue;
        if (size <= 0) break;
        for (ssize_t i = 0; i < size; ++i) {
            if (input[i] != '\n') line[used++] = input[i];
            if (input[i] == '\n' || used == sizeof(line) - 1) {
                line[used] = '\0';
                if (used) __android_log_write(ANDROID_LOG_INFO, TAG, line);
                used = 0;
            }
        }
    }
    if (used) {
        line[used] = '\0';
        __android_log_write(ANDROID_LOG_INFO, TAG, line);
    }
    close(fd);
    return NULL;
}

// The backend intentionally ignores CPU-type Vulkan implementations by default.
// Opt in ONLY on an emulator, ONLY when the test runner explicitly requests 0.
// Do not force a device on phones or fake its reported type/features.
static void configure_emulator_vulkan(void) {
    char emulator[PROP_VALUE_MAX] = {0}, device[PROP_VALUE_MAX] = {0};
    __system_property_get("ro.kernel.qemu", emulator);
    __system_property_get("debug.gguf.vulkan_device", device);
    if (strcmp(emulator, "1") == 0 && strcmp(device, "0") == 0) {
        if (setenv("GGML_VK_VISIBLE_DEVICES", "0", 1) == 0)
            __android_log_write(ANDROID_LOG_INFO, TAG,
                "Emulator-only GGML_VK_VISIBLE_DEVICES=0; software Vulkan is not hardware acceleration");
    }
}

// The Vulkan entry point uses opaque VkInstance (pointer), returns function
// pointers, and the version query takes uint32_t*. No Vulkan object is created.
static void report_loader_version(void) {
    void *handle = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
    if (!handle) {
        __android_log_print(ANDROID_LOG_WARN, TAG, "Vulkan loader unavailable: %s", dlerror());
        return;
    }
    typedef void (*vk_function)(void);
    typedef vk_function (*get_proc_fn)(void *, const char *);
    typedef int32_t (*version_fn)(uint32_t *);
    get_proc_fn get_proc = (get_proc_fn)dlsym(handle, "vkGetInstanceProcAddr");
    version_fn enumerate = get_proc ? (version_fn)get_proc(NULL, "vkEnumerateInstanceVersion") : NULL;
    uint32_t version = 1u << 22; // Vulkan 1.0 when enumerate is unavailable.
    int32_t status = enumerate ? enumerate(&version) : 0;
    if (status == 0) {
        unsigned major = (version >> 22) & 0x7f, minor = (version >> 12) & 0x3ff;
        __android_log_print(ANDROID_LOG_INFO, TAG,
            "Vulkan loader API %u.%u.%u; bundled ggml Vulkan requires >= 1.2",
            major, minor, version & 0xfff);
        if (major < 1 || (major == 1 && minor < 2))
            __android_log_write(ANDROID_LOG_WARN, TAG,
                "Vulkan incompatible: loader below 1.2; do not bypass the native version check");
    } else {
        __android_log_print(ANDROID_LOG_WARN, TAG, "vkEnumerateInstanceVersion failed: %d", status);
    }
    dlclose(handle);
}

#ifndef GGUF_DIAGNOSTICS_TEST
__attribute__((constructor))
#endif
void gguf_install_native_diagnostics(void) {
    int descriptors[2];
    if (pipe2(descriptors, O_CLOEXEC) != 0) {
        __android_log_write(ANDROID_LOG_WARN, TAG, "Cannot capture native stderr: pipe failed");
        return;
    }
    pthread_t thread;
    int status = pthread_create(&thread, NULL, forward_stderr, (void *)(intptr_t)descriptors[0]);
    if (status != 0) {
        close(descriptors[0]);
        close(descriptors[1]);
        __android_log_print(ANDROID_LOG_WARN, TAG, "Cannot capture native stderr: pthread error %d", status);
        return;
    }
    pthread_detach(thread);
    // Only stderr, never stdout: preserve Java's existing generation markers.
    if (dup2(descriptors[1], STDERR_FILENO) < 0)
        __android_log_write(ANDROID_LOG_WARN, TAG, "Cannot redirect native stderr");
    close(descriptors[1]);
    configure_emulator_vulkan();
    report_loader_version();
}
