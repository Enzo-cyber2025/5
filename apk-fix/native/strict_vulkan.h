#pragma once
#include "ggml-backend.h"

// Host orchestration remains CPU work. Only tensor compute routing is strict.
// Scope includes model/context loading, language graphs, mtmd and KV updates.
struct StrictVulkanScope {
    ggml_backend_dev_t previous;
    explicit StrictVulkanScope(ggml_backend_dev_t device)
        : previous(ggml_backend_gguf_set_strict_device(device)) {
        ggml_backend_gguf_strict_reset();
    }
    ~StrictVulkanScope() { ggml_backend_gguf_set_strict_device(previous); }
    StrictVulkanScope(const StrictVulkanScope &) = delete;
    StrictVulkanScope &operator=(const StrictVulkanScope &) = delete;
};
