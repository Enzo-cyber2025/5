"""Pinned, app-private routing policy. No CPU tensor math in strict Vulkan scopes.
This is not an assertion that tokenization, I/O, RNG bookkeeping or Android run
on a GPU. The selected Vulkan device can itself be software in test emulators.
"""

API = '''
    // GGUF_STRICT_VULKAN_API: per-calling-thread, scoped by the JNI engine.
    GGML_API ggml_backend_dev_t ggml_backend_gguf_set_strict_device(ggml_backend_dev_t device);
    GGML_API ggml_backend_dev_t ggml_backend_gguf_strict_device(void);
    GGML_API void ggml_backend_gguf_strict_reset(void);
    GGML_API const char * ggml_backend_gguf_strict_error(void);
    GGML_API uint64_t ggml_backend_gguf_strict_graphs(void);
    GGML_API uint64_t ggml_backend_gguf_strict_nodes(void);
'''

STATE = '''
// GGUF_STRICT_VULKAN_STATE: NOT global; concurrent explicit CPU engines unaffected.
static thread_local ggml_backend_dev_t gguf_strict_device = nullptr;
static thread_local char gguf_strict_error[512] = {};
static thread_local uint64_t gguf_strict_graphs = 0;
static thread_local uint64_t gguf_strict_nodes = 0;
ggml_backend_dev_t ggml_backend_gguf_set_strict_device(ggml_backend_dev_t device) {
    auto old = gguf_strict_device;
    gguf_strict_device = device;
    return old;
}
ggml_backend_dev_t ggml_backend_gguf_strict_device(void) { return gguf_strict_device; }
void ggml_backend_gguf_strict_reset(void) {
    gguf_strict_error[0] = 0;
    gguf_strict_graphs = gguf_strict_nodes = 0;
}
const char * ggml_backend_gguf_strict_error(void) { return gguf_strict_error; }
uint64_t ggml_backend_gguf_strict_graphs(void) { return gguf_strict_graphs; }
uint64_t ggml_backend_gguf_strict_nodes(void) { return gguf_strict_nodes; }
static bool gguf_strict_is_math(enum ggml_op op) {
    return op != GGML_OP_NONE && op != GGML_OP_VIEW && op != GGML_OP_RESHAPE &&
           op != GGML_OP_PERMUTE && op != GGML_OP_TRANSPOSE;
}
static bool gguf_strict_check_graph(ggml_backend_t backend, const ggml_cgraph * graph) {
    if (!gguf_strict_device) return true;
    for (int i = 0; i < graph->n_nodes; ++i) {
        const auto * node = graph->nodes[i];
        if (!gguf_strict_is_math(node->op)) continue;
        if (ggml_backend_get_device(backend) != gguf_strict_device) {
            snprintf(gguf_strict_error, sizeof(gguf_strict_error),
                "Vulkan estrito: operacao %s (%s) foi destinada a %s; calculo CPU bloqueado. Modelo/parametros precisam de suporte Vulkan.",
                ggml_op_name(node->op), node->name, ggml_backend_name(backend));
            GGML_LOG_ERROR("GGUF_STRICT_VULKAN_BLOCKED %s\\n", gguf_strict_error);
            return false;
        }
    }
    return true;
}
'''

DIRECT_GUARD = '''
    // GGUF_STRICT_VULKAN_DISPATCH: also guards direct, non-scheduler calls.
    if (!gguf_strict_check_graph(backend, cgraph)) return GGML_STATUS_FAILED;
    if (gguf_strict_device) {
        ++gguf_strict_graphs;
        for (int i = 0; i < cgraph->n_nodes; ++i) {
            if (gguf_strict_is_math(cgraph->nodes[i]->op)) ++gguf_strict_nodes;
        }
    }
'''

PREFER = '''
    // GGUF_STRICT_VULKAN_PREFER: avoid CPU heuristics even for small operations.
    // Preallocated destinations/views above cannot be moved; final guard checks them.
    if (gguf_strict_device && gguf_strict_is_math(tensor->op)) {
        for (int b = 0; b < sched->n_backends; ++b) {
            if (ggml_backend_get_device(sched->backends[b]) == gguf_strict_device &&
                    ggml_backend_supports_op(sched->backends[b], tensor)) return b;
        }
    }
'''

SCHED_GUARD = '''
    // GGUF_STRICT_VULKAN_PREFLIGHT: reject the whole graph before ANY split runs.
    // Also covers mtmd encoders and KV maintenance using this scheduler.
    for (int i = 0; gguf_strict_device && i < sched->n_splits; ++i) {
        const auto * split = &sched->splits[i];
        if (!gguf_strict_check_graph(sched->backends[split->backend_id], &split->graph))
            return GGML_STATUS_FAILED;
    }
'''


def once(source, anchor, addition, marker):
    if marker in source:
        return source
    assert source.count(anchor) == 1, 'Pinned source changed: ' + marker
    return source.replace(anchor, addition)


def patch_header(s):
    anchor = '    GGML_API enum ggml_status ggml_backend_graph_compute      (ggml_backend_t backend, struct ggml_cgraph * cgraph);'
    return once(s, anchor, API + '\n' + anchor, 'GGUF_STRICT_VULKAN_API')


def patch_backend(s):
    s = once(s, '// backend buffer type', STATE + '\n// backend buffer type', 'GGUF_STRICT_VULKAN_STATE')
    anchor = '''enum ggml_status ggml_backend_graph_compute_async(ggml_backend_t backend, struct ggml_cgraph * cgraph) {
    GGML_ASSERT(backend);'''
    s = once(s, anchor, anchor + DIRECT_GUARD, 'GGUF_STRICT_VULKAN_DISPATCH')
    s = once(s, '    // graph input\n', PREFER + '\n    // graph input\n', 'GGUF_STRICT_VULKAN_PREFER')
    anchor = '    return ggml_backend_sched_compute_splits(sched);'
    return once(s, anchor, SCHED_GUARD + '\n' + anchor, 'GGUF_STRICT_VULKAN_PREFLIGHT')


def patch_sampler_binding(s):
    anchor = '        sampler->iface->backend_init(sampler, buft, cparams.n_outputs_max_per_seq);'
    replacement = '''        // GGUF_STRICT_VULKAN_SAMPLER: a supported prefix is not full sampling.
        const bool full_sampler = sampler->iface->backend_init(sampler, buft, cparams.n_outputs_max_per_seq);
        if (ggml_backend_gguf_strict_device() && !full_sampler) {
            LLAMA_LOG_ERROR("GGUF_STRICT_VULKAN_SAMPLER unsupported chain; CPU fallback blocked\\n");
            return false;
        }'''
    return once(s, anchor, replacement, 'GGUF_STRICT_VULKAN_SAMPLER')


def apply(source):
    for rel, patch in (
        ('ggml/include/ggml-backend.h', patch_header),
        ('ggml/src/ggml-backend.cpp', patch_backend),
        ('src/llama-context.cpp', patch_sampler_binding),
    ):
        p = source / rel
        p.write_text(patch(p.read_text()))
