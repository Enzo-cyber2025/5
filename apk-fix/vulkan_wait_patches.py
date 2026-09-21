"""Build-time opt-in wait policy for pinned Vulkan. Same fence, same completion dependency.
Only replaces tail busy polling with the driver's blocking fence wait; no model,
shader, batching, precision, queue submission, or synchronization removal.
"""
MARKER='// GGUF_VULKAN_BLOCKING_WAIT: same completion fence, no busy polling.'
ANCHOR='''    // Spin (w/pause) waiting for the graph to finish executing.
    vk::Result result;'''
ADDITION='''    // GGUF_VULKAN_BLOCKING_WAIT: same completion fence, no busy polling.
    // Keep the earlier almost-ready fence wait/reset unchanged. The final fence
    // must still signal before staging reads, buffer reuse or sampler access.
    static const bool gguf_blocking_wait = [] {
        const char * value = getenv("GGUF_VULKAN_BLOCKING_WAIT");
        const bool enabled = value == nullptr || strcmp(value, "1") == 0;
        GGML_LOG_INFO("GGUF_VULKAN_WAIT_POLICY blocking=%d same_completion_fence=1\\n", (int) enabled);
        return enabled;
    }();
    if (gguf_blocking_wait) {
        VK_CHECK(ctx->device->device.waitForFences({ ctx->fence }, true, UINT64_MAX),
                 "GGUF blocking completion fence", ctx->device);
        ctx->device->device.resetFences({ ctx->fence });
        return;
    }

'''

def patch(s):
    if MARKER in s:return s
    assert s.count(ANCHOR)==1,'Pinned Vulkan fence implementation changed'
    start=s.index('static void ggml_vk_wait_for_fence(')
    end=s.index('\nstatic constexpr',start)
    body=s[start:end]
    assert 'waitForFences({ ctx->almost_ready_fence }, true, UINT64_MAX)' in body
    assert 'getFenceStatus(ctx->fence)' in body and 'resetFences({ ctx->fence })' in body
    return s.replace(ANCHOR,ADDITION+ANCHOR)

def apply(source):
    p=source/'ggml/src/ggml-vulkan/ggml-vulkan.cpp'
    p.write_text(patch(p.read_text()))
