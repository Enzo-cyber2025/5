"""App-private QKV fusion experiment: same encoded weights, device-only copying.
Restricted to Idefics3 equal-head/no-QK-norm layers. Retains originals for exact
reference evaluation; increased device memory is measured, not hidden.
"""
JOIN=r'''// GGUF_QKV_JOIN: contiguous byte-preserving Q/K/V concatenation.
struct gguf_qkv_join {
    ggml_tensor * combined;
    std::array<ggml_tensor *,3> sources;
    std::array<ggml_tensor *,3> views;
};
static bool gguf_qkv_same(ggml_tensor *q,ggml_tensor *k,ggml_tensor *v,bool bias) {
    if(!q || !k || !v || !ggml_is_contiguous(q) || !ggml_is_contiguous(k) || !ggml_is_contiguous(v))return false;
    if(q->type!=k->type || q->type!=v->type || ggml_nbytes(q)%4)return false;
    for(int d=0;d<4;d++)if(q->ne[d]!=k->ne[d] || q->ne[d]!=v->ne[d])return false;
    if(q->ne[2]!=1 || q->ne[3]!=1 || (bias && q->ne[1]!=1))return false;
    return q->ne[bias?0:1]>0 && q->ne[bias?0:1]<=INT64_MAX/3 && ggml_nbytes(q)<=SIZE_MAX/3;
}
static gguf_qkv_join gguf_qkv_build(ggml_context *ctx,ggml_tensor *q,ggml_tensor *k,ggml_tensor *v,bool bias) {
    if(!gguf_qkv_same(q,k,v,bias))throw std::runtime_error("Unsupported QKV tensor layout");
    auto *combined=bias?ggml_new_tensor_1d(ctx,q->type,3*q->ne[0]):ggml_new_tensor_2d(ctx,q->type,q->ne[0],3*q->ne[1]);
    gguf_qkv_join j{combined,{q,k,v},{}};
    for(size_t i=0;i<3;i++) {
        j.views[i]=bias?ggml_view_1d(ctx,combined,q->ne[0],i*ggml_nbytes(q)):
            ggml_view_2d(ctx,combined,q->ne[0],q->ne[1],q->nb[1],i*ggml_nbytes(q));
    }
    return j;
}
struct gguf_qkv_layer {
    size_t index;
    ggml_tensor *weight;
    ggml_tensor *bias;
};
'''
MEMBERS=r'''    // GGUF_QKV_STORAGE: originals remain available for reference-only diagnostics.
    ggml_context_ptr gguf_qkv_meta;
    ggml_backend_buffer_ptr gguf_qkv_buffer;
    std::vector<gguf_qkv_layer> gguf_qkv_layers;
'''
INIT=r'''    // GGUF_QKV_INIT: one-time packing, never dequantize/requantize on the host.
    void gguf_init_qkv(clip_ctx &ctx_clip) {
        if(!std::getenv("GGUF_VULKAN_QKV"))return;
        auto device=ggml_backend_gguf_strict_device();
        auto &model=ctx_clip.model;
        if(!device || ggml_backend_get_device(ctx_clip.backend)!=device ||
           model.proj_type!=PROJECTOR_TYPE_IDEFICS3 || model.modality!=CLIP_MODALITY_VISION ||
           model.hparams.n_head<=0 || model.hparams.n_embd<=0 || model.hparams.n_head!=model.hparams.n_head_kv)
            throw std::runtime_error("QKV experiment requires strict Vulkan and supported equal-head Idefics3");
        if(model.layers.empty() || model.layers.size()>(SIZE_MAX/ggml_tensor_overhead()-1)/8)
            throw std::runtime_error("Invalid QKV layer count");
        ggml_init_params params{(model.layers.size()*8+1)*ggml_tensor_overhead(),nullptr,true};
        ctx_clip.gguf_qkv_meta.reset(ggml_init(params));
        if(!ctx_clip.gguf_qkv_meta)throw std::runtime_error("QKV metadata allocation failed");
        std::vector<gguf_qkv_join> joins;
        for(size_t i=0;i<model.layers.size();i++) {
            auto &layer=model.layers[i];
            const bool has_bias=layer.q_b || layer.k_b || layer.v_b;
            const int head_dim=model.hparams.n_embd_head>0?model.hparams.n_embd_head:
                model.hparams.n_embd/model.hparams.n_head;
            if(layer.qkv_w || layer.qkv_b || layer.q_norm || layer.k_norm ||
               !gguf_qkv_same(layer.q_w,layer.k_w,layer.v_w,false) ||
               layer.q_w->ne[1]!=(int64_t)head_dim*model.hparams.n_head ||
               (has_bias && (layer.q_b==nullptr || layer.q_b->type!=GGML_TYPE_F32 || !gguf_qkv_same(layer.q_b,layer.k_b,layer.v_b,true) || layer.q_b->ne[0]!=layer.q_w->ne[1])))
                throw std::runtime_error("Unsupported QKV layer; parameters were not modified");
            auto w=gguf_qkv_build(ctx_clip.gguf_qkv_meta.get(),layer.q_w,layer.k_w,layer.v_w,false);
            ggml_format_name(w.combined,"gguf_qkv_%zu_w",i);joins.push_back(w);
            ggml_tensor *bias=nullptr;
            if(has_bias) {
                auto b=gguf_qkv_build(ctx_clip.gguf_qkv_meta.get(),layer.q_b,layer.k_b,layer.v_b,true);
                ggml_format_name(b.combined,"gguf_qkv_%zu_b",i);joins.push_back(b);bias=b.combined;
            }
            ctx_clip.gguf_qkv_layers.push_back({i,w.combined,bias});
        }
        auto buft=ggml_backend_get_default_buffer_type(ctx_clip.backend);
        ctx_clip.gguf_qkv_buffer.reset(ggml_backend_alloc_ctx_tensors_from_buft(ctx_clip.gguf_qkv_meta.get(),buft));
        if(!ctx_clip.gguf_qkv_buffer)throw std::runtime_error("QKV device allocation failed");
        ggml_backend_buffer_set_usage(ctx_clip.gguf_qkv_buffer.get(),GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
        ctx_clip.mem_usage[device]+=ggml_backend_buffer_get_size(ctx_clip.gguf_qkv_buffer.get());
        size_t copied=0;
        for(const auto &join:joins)for(size_t i=0;i<3;i++) {
            auto *src=join.sources[i],*dst=join.views[i];
            if(!src->buffer || !dst->buffer ||
               ggml_backend_buft_get_device(ggml_backend_buffer_get_type(src->buffer))!=device ||
               ggml_backend_buft_get_device(ggml_backend_buffer_get_type(dst->buffer))!=device ||
               !ggml_backend_buffer_copy_tensor(src,dst))
                throw std::runtime_error("QKV device copy unavailable; host fallback not allowed");
            copied+=ggml_nbytes(src);
            if(std::getenv("GGUF_VERIFY_QKV")) {
                std::vector<unsigned char> a(ggml_nbytes(src)),b(a.size());
                ggml_backend_tensor_get(src,a.data(),0,a.size());ggml_backend_tensor_get(dst,b.data(),0,b.size());
                if(a!=b)throw std::runtime_error("QKV weight copy changed bytes");
            }
        }
        for(const auto &p:ctx_clip.gguf_qkv_layers) {
            model.layers[p.index].qkv_w=p.weight;model.layers[p.index].qkv_b=p.bias;
        }
        LOG_INF("GGUF_QKV_READY layers=%zu copied_bytes=%zu extra_device_bytes=%zu weight_verification=%d backend=%s\n",
            ctx_clip.gguf_qkv_layers.size(),copied,ggml_backend_buffer_get_size(ctx_clip.gguf_qkv_buffer.get()),
            std::getenv("GGUF_VERIFY_QKV")!=nullptr,ggml_backend_name(ctx_clip.backend));
    }
'''
TOGGLE=r'''
// GGUF_QKV_REFERENCE: same loaded original tensors, no CPU reference inference.
bool clip_gguf_qkv_reference(clip_ctx *ctx,bool reference) {
    if(!ctx || ctx->gguf_qkv_layers.empty())return false;
    for(const auto &p:ctx->gguf_qkv_layers) {
        auto &layer=ctx->model.layers[p.index];
        layer.qkv_w=reference?nullptr:p.weight;layer.qkv_b=reference?nullptr:p.bias;
    }
    return true;
}
'''
DECL='MTMD_API bool mtmd_gguf_qkv_reference(mtmd_context *ctx, bool reference);'
BRIDGE=r'''
// GGUF_QKV_BRIDGE
bool mtmd_gguf_qkv_reference(mtmd_context *ctx,bool reference) {
    return ctx && clip_gguf_qkv_reference(ctx->ctx_v,reference);
}
'''

def patch_projector_qkv(source):
    p=source/'tools/mtmd/clip.cpp';s=p.read_text()
    if 'GGUF_QKV_JOIN' in s:
        assert all(x in s for x in (JOIN,MEMBERS,INIT,TOGGLE)),'Stale QKV patch'
    else:
        s=s.replace('#include "ggml-backend.h"','#include "ggml-backend.h"\n#include "ggml-backend-impl.h"')
        anchor='struct clip_ctx {';assert s.count(anchor)==1;s=s.replace(anchor,JOIN+'\n'+anchor+'\n'+MEMBERS)
        anchor='    void load_tensors(clip_ctx & ctx_clip) {';assert s.count(anchor)==1;s=s.replace(anchor,INIT+'\n'+anchor)
        anchor='            fin.close();';assert s.count(anchor)==1;s=s.replace(anchor,anchor+'\n            if(!ctx_clip.no_alloc)gguf_init_qkv(ctx_clip);')
        s+='\n'+TOGGLE;p.write_text(s)
    p=source/'tools/mtmd/clip.h';s=p.read_text();decl='bool clip_gguf_qkv_reference(clip_ctx *ctx, bool reference);'
    if decl not in s:s+='\n'+decl+'\n';p.write_text(s)
    p=source/'tools/mtmd/mtmd.h';s=p.read_text()
    if DECL not in s:
        anchor='// get output embeddings from the last encode pass';assert s.count(anchor)==1;s=s.replace(anchor,DECL+'\n\n'+anchor);p.write_text(s)
    p=source/'tools/mtmd/mtmd.cpp';s=p.read_text()
    if 'GGUF_QKV_BRIDGE' not in s:p.write_text(s+'\n'+BRIDGE)
    else:assert BRIDGE in s,'Stale QKV bridge'
