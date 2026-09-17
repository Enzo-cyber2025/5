"""Opt-in Idefics3 pair batching; preserve per-image pixel-unshuffle and attention.
Other projectors keep their upstream batching support. Single-image graph unchanged.
"""
MERGE=r'''    // GGUF_IDEFICS_BATCH_MERGE: never fold the image axis into spatial axes.
    if (proj_type == PROJECTOR_TYPE_IDEFICS3 && n_batch > 1) {
        GGML_ASSERT(cur->ne[2] == n_batch);
        GGML_ASSERT(cur->ne[1] == (int64_t) width * height);
        cur = ggml_reshape_4d(ctx0, cur, n_embd, width, height, n_batch);
        if (pad_width || pad_height) {
            cur = ggml_pad(ctx0, cur, 0, pad_width, pad_height, 0);
            width += pad_width;
            height += pad_height;
        }
        cur = ggml_reshape_4d(ctx0, cur, n_embd * scale_factor, width / scale_factor, height, n_batch);
        cur = ggml_permute(ctx0, cur, 0, 2, 1, 3);
        cur = ggml_cont_4d(ctx0, cur, n_embd * scale_factor * scale_factor, height / scale_factor, width / scale_factor, n_batch);
        cur = ggml_permute(ctx0, cur, 0, 2, 1, 3);
        cur = ggml_cont_3d(ctx0, cur, cur->ne[0], cur->ne[1] * cur->ne[2], n_batch);
        cb(cur, "pixel_shuffle", -1);
        return cur;
    }
'''
SUPPORT='''    // GGUF_IDEFICS_BATCH_SUPPORT: explicitly gated until quality/speed acceptance.
    bool support_batch() const override {
        return proj_type == PROJECTOR_TYPE_IDEFICS3 && std::getenv("GGUF_PROJECTOR_BATCH2") != nullptr;
    }
'''

def patch_projector_batch(source):
    p=source/'tools/mtmd/clip.cpp';s=p.read_text()
    if 'GGUF_IDEFICS_BATCH_MERGE' in s:assert MERGE in s,'Stale Idefics batch merge'
    else:
        anchor='    const int64_t pad_height = CLIP_ALIGN(height, scale_factor) - height;'
        assert s.count(anchor)==1;s=s.replace(anchor,anchor+'\n'+MERGE);p.write_text(s)
    p=source/'tools/mtmd/models/models.h';s=p.read_text()
    if 'GGUF_IDEFICS_BATCH_SUPPORT' in s:assert SUPPORT in s,'Stale Idefics batch support'
    else:
        anchor='    clip_graph_siglip(clip_ctx * ctx, const clip_image_f32 & img) : clip_graph(ctx, img) {}'
        assert s.count(anchor)==1;s=s.replace(anchor,anchor+'\n'+SUPPORT)
        s=s.replace('#include <map>','#include <map>\n#include <cstdlib>');p.write_text(s)
