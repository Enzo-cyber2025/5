// Actual patched ggml CPU backend: prove strict rejection occurs before math.
// No Vulkan device or physical-GPU speed claim is made by this host test.
#include "ggml.h"
#include "ggml-backend.h"
#include "ggml-cpu.h"
#include "ggml-alloc.h"
#include "strict_vulkan.h"
#include <cassert>
#include <cstdio>
#include <cstring>

int main() {
    auto *ctx=ggml_init({1024*1024,nullptr,true});assert(ctx);
    auto *a=ggml_new_tensor_1d(ctx,GGML_TYPE_F32,4);
    auto *b=ggml_new_tensor_1d(ctx,GGML_TYPE_F32,4);
    auto *out=ggml_add(ctx,a,b);ggml_set_name(out,"strict-add");
    auto *graph=ggml_new_graph(ctx);ggml_build_forward_expand(graph,out);
    auto backend=ggml_backend_cpu_init();assert(backend);
    auto buffer=ggml_backend_alloc_ctx_tensors(ctx,backend);assert(buffer);
    const float x[]={1,2,3,4},sentinel[]={-91,-91,-91,-91};float result[4];
    ggml_backend_tensor_set(a,x,0,sizeof(x));ggml_backend_tensor_set(b,x,0,sizeof(x));
    ggml_backend_tensor_set(out,sentinel,0,sizeof(sentinel));
    // A distinct sentinel identity is never dereferenced or advertised as GPU.
    char unsupported_device;
    auto requested=reinterpret_cast<ggml_backend_dev_t>(&unsupported_device);
    {
        StrictVulkanScope strict(requested);
        assert(ggml_backend_graph_compute(backend,graph)==GGML_STATUS_FAILED);
        ggml_backend_tensor_get(out,result,0,sizeof(result));
        assert(!memcmp(result,sentinel,sizeof(result)));
        assert(strstr(ggml_backend_gguf_strict_error(),"strict-add"));
        assert(ggml_backend_gguf_strict_nodes()==0);
        auto sched=ggml_backend_sched_new(&backend,nullptr,1,128,false,true);assert(sched);
        assert(ggml_backend_sched_graph_compute(sched,graph)==GGML_STATUS_FAILED);
        ggml_backend_tensor_get(out,result,0,sizeof(result));assert(!memcmp(result,sentinel,sizeof(result)));
        ggml_backend_sched_free(sched);
    }
    assert(!ggml_backend_gguf_strict_device());
    {
        StrictVulkanScope cpu(nullptr);
        assert(ggml_backend_graph_compute(backend,graph)==GGML_STATUS_SUCCESS);
        ggml_backend_tensor_get(out,result,0,sizeof(result));
        for(int i=0;i<4;i++)assert(result[i]==2*x[i]);
    }
    ggml_backend_buffer_free(buffer);ggml_backend_free(backend);ggml_free(ctx);
    puts("REAL_GGML_CPU_TENSOR_DISPATCH_BLOCKED_BEFORE_MATH_PASS");
}
