"""Dedicated opt-in build only. Q5_0 -> Q8_0 preserving original scale/integers."""
from pathlib import Path

def once(s,anchor,replacement,marker):
    if marker in s:return s
    assert s.count(anchor)==1,marker
    return s.replace(anchor,replacement,1)

CHECK='''src0_type == GGML_TYPE_Q5_0 && src1_type == GGML_TYPE_Q8_0 &&
                    op->op == GGML_OP_CPY && ggml_is_contiguous(op->src[0]) && ggml_is_contiguous(op) &&
                    op->src[0]->view_src == nullptr && op->view_offs == 0 &&
                    ggml_nelements(op) % 64 == 0 && ggml_nelements(op) <= 64LL*64*65535'''

def patch(s):
    s=once(s,'    vk_pipeline pipeline_cpy_f32_quant[GGML_TYPE_COUNT];',
        '    vk_pipeline pipeline_gguf_repack_q5; // GGUF_REPACK_Q5_PIPELINE\n    vk_pipeline pipeline_cpy_f32_quant[GGML_TYPE_COUNT];','GGUF_REPACK_Q5_PIPELINE')
    anchor='    ggml_vk_create_pipeline(device, device->pipeline_cpy_f32_f32,'
    assert s.count(anchor)==1
    s=once(s,anchor,'''    // GGUF_REPACK_Q5_CREATE: only the experimental build contains this pipeline.
    ggml_vk_create_pipeline(device, device->pipeline_gguf_repack_q5, "gguf_repack_q5", gguf_repack_q5_len, gguf_repack_q5_data, "main", 2, 3*sizeof(uint32_t), {64,1,1}, {}, 1);
'''+anchor,'GGUF_REPACK_Q5_CREATE')
    anchor='static vk_pipeline ggml_vk_get_cpy_pipeline(ggml_backend_vk_context * ctx, const ggml_tensor * src, const ggml_tensor * dst, ggml_type to) {'
    s=once(s,anchor,anchor+'''
    // GGUF_REPACK_Q5_SELECT
    if(src->type==GGML_TYPE_Q5_0 && to==GGML_TYPE_Q8_0 && dst && ggml_is_contiguous(src) && ggml_is_contiguous(dst))
        return ctx->device->pipeline_gguf_repack_q5;
''','GGUF_REPACK_Q5_SELECT')
    anchor='static void ggml_vk_cpy(ggml_backend_vk_context * ctx, vk_context& subctx, const ggml_tensor * src0, ggml_tensor * dst) {'
    s=once(s,anchor,anchor+'''
    // GGUF_REPACK_Q5_DISPATCH: exact integer bit-layout conversion, on GPU.
    if(src0->type==GGML_TYPE_Q5_0 && dst->type==GGML_TYPE_Q8_0) {
        GGML_ASSERT(ggml_is_contiguous(src0) && ggml_is_contiguous(dst));
        GGML_ASSERT(ggml_nelements(dst)%64==0 && ggml_nelements(dst)<=64LL*64*65535);
        const uint32_t a=get_misalign_bytes(ctx,src0),d=get_misalign_bytes(ctx,dst);
        GGML_ASSERT(a%4==0 && d%4==0);
        struct RepackParameters {uint32_t pairs,source_offset_words,target_offset_words;};
        const RepackParameters pc{uint32_t(ggml_nelements(dst)/64),a/4,d/4};
        auto pipeline=ctx->device->pipeline_gguf_repack_q5;
        ggml_pipeline_request_descriptor_sets(ctx,pipeline,1);
        ggml_vk_sync_buffers(ctx,subctx);
        ggml_vk_dispatch_pipeline(ctx,subctx,pipeline,
            {ggml_vk_tensor_subbuffer(ctx,src0,true),ggml_vk_tensor_subbuffer(ctx,dst,true)},pc,{pc.pairs,1,1});
        return;
    }
''','GGUF_REPACK_Q5_DISPATCH')
    anchor='''                ggml_type src1_type = op->src[1] != nullptr ? op->src[1]->type : src0_type;
'''
    s=once(s,anchor,anchor+'\n                // GGUF_REPACK_Q5_SUPPORT: no views, odd tails or oversized dispatch.\n                if ('+CHECK+') return true;\n','GGUF_REPACK_Q5_SUPPORT')
    return s

def apply(root):
    p=root/'ggml/src/ggml-vulkan/ggml-vulkan.cpp';p.write_text(patch(p.read_text()))
    shaders=root/'ggml/src/ggml-vulkan/vulkan-shaders'
    (shaders/'gguf_repack_q5.comp').write_text(Path(__file__).with_name('repack_q5.comp').read_text())
    p=shaders/'vulkan-shaders-gen.cpp';s=p.read_text();anchor='    string_to_spv("cpy_f32_f32", "copy.comp",'
    assert s.count(anchor)==1
    s=once(s,anchor,'    string_to_spv("gguf_repack_q5", "gguf_repack_q5.comp", {}); // GGUF_REPACK_Q5_SHADER\n'+anchor,'GGUF_REPACK_Q5_SHADER');p.write_text(s)
