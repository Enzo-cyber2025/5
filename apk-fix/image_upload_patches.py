"""Opt-in Vulkan RGB packing. No decode, resize, normalization or dtype changes.
Only activate after explicit experiment selection; legacy/default path preserved.
"""
LAYOUT='''// GGUF_VULKAN_IMAGE_PACK_LAYOUT: exact graph shared by app and host layout tests.
static ggml_tensor * gguf_rgb_planar_graph(ggml_context * ctx0, int64_t nx, int64_t ny, int64_t batch, bool verify) {
    auto * rgb = ggml_new_tensor_4d(ctx0, GGML_TYPE_F32, 3, nx, ny, batch);
    ggml_set_name(rgb, "gguf_inp_rgb");
    ggml_set_input(rgb);
    auto * planar = ggml_cont(ctx0, ggml_permute(ctx0, rgb, 2, 0, 1, 3));
    ggml_set_name(planar, "inp_raw");
    if (verify) ggml_set_output(planar);
    return planar;
}
'''
GRAPH_OLD='''    ggml_tensor * inp_raw = ggml_new_tensor_4d(ctx0, GGML_TYPE_F32, img.nx(), img.ny(), channels, n_batch);
    ggml_set_name(inp_raw, "inp_raw");
    ggml_set_input(inp_raw);
    return inp_raw;'''
GRAPH_NEW='''    // GGUF_VULKAN_IMAGE_PACK_GRAPH: HWC upload, exact layout conversion on GPU.
    // A bare permute is insufficient: im2col expects contiguous planar pixels.
    if (channels == 3 && model.modality == CLIP_MODALITY_VISION &&
        ggml_backend_gguf_strict_device() && std::getenv("GGUF_VULKAN_IMAGE_PACK")) {
        return gguf_rgb_planar_graph(ctx0, img.nx(), img.ny(), n_batch,
            std::getenv("GGUF_VERIFY_IMAGE_PACK") != nullptr);
    }
'''+GRAPH_OLD
UPLOAD='''    // GGUF_VULKAN_IMAGE_PACK_UPLOAD: no host planar/concatenation buffer.
    if (!imgs.is_audio && ggml_graph_get_tensor(gf, "gguf_inp_rgb")) {
        auto * rgb = get_inp_tensor("gguf_inp_rgb");
        if (!ggml_backend_gguf_strict_device() || rgb->type != GGML_TYPE_F32)
            throw std::runtime_error("Vulkan image packing requires strict F32 input");
        if ((size_t)rgb->ne[3] != imgs.entries.size())
            throw std::runtime_error("Image batch size mismatch");
        size_t offset = 0;
        for (const auto &image : imgs.entries) {
            const auto &pixels = image.get_ro_buf();
            if (rgb->ne[0] != 3 || rgb->ne[1] != image.nx() || rgb->ne[2] != image.ny() ||
                pixels.size() != (size_t)rgb->ne[0] * rgb->ne[1] * rgb->ne[2])
                throw std::runtime_error("Image dimensions/layout mismatch");
            const size_t bytes = pixels.size() * sizeof(float);
            if (offset > ggml_nbytes(rgb) || bytes > ggml_nbytes(rgb) - offset)
                throw std::runtime_error("Image upload exceeds tensor storage");
            ggml_backend_tensor_set(rgb, pixels.data(), offset, bytes);
            offset += bytes;
        }
        if (offset != ggml_nbytes(rgb)) throw std::runtime_error("Incomplete image upload");
        LOG_INF("GGUF_IMAGE_UPLOAD packing=Vulkan bytes=%zu host_planar_copy=0\\n", offset);
    } else if (!imgs.is_audio) {
        if (std::getenv("GGUF_VULKAN_IMAGE_PACK"))
            throw std::runtime_error("Requested Vulkan image packing requires a supported strict RGB graph");'''
VERIFY='''    // GGUF_VULKAN_IMAGE_PACK_VERIFY: instrumented correctness, NOT speed data.
    if (!imgs.is_audio && std::getenv("GGUF_VERIFY_IMAGE_PACK")) {
        auto * rgb = ggml_graph_get_tensor(gf, "gguf_inp_rgb");
        if (rgb) {
            auto * planar = ggml_graph_get_tensor(gf, "inp_raw");
            if (!planar) throw std::runtime_error("Missing planar diagnostic tensor");
            auto backend = ggml_backend_sched_get_tensor_backend(ctx->sched.get(), planar);
            if (!backend || ggml_backend_get_device(backend) != ggml_backend_gguf_strict_device())
                throw std::runtime_error("Image packing did not execute on selected Vulkan device");
            std::vector<float> actual((size_t)ggml_nelements(planar));
            ggml_backend_tensor_get(planar, actual.data(), 0, ggml_nbytes(planar));
            const size_t pixels_per_image = (size_t)imgs.entries[0].nx() * imgs.entries[0].ny();
            for (size_t b = 0; b < imgs.entries.size(); ++b) {
                const auto &expected = imgs.entries[b].get_ro_buf();
                for (size_t c = 0; c < 3; ++c) for (size_t p = 0; p < pixels_per_image; ++p) {
                    if (std::memcmp(&actual[(b*3+c)*pixels_per_image+p], &expected[p*3+c], sizeof(float)))
                        throw std::runtime_error("Vulkan image packing changed pixel bits");
                }
            }
            LOG_INF("GGUF_IMAGE_PACK_BYTES_EQUAL bytes=%zu backend=%s\\n", ggml_nbytes(planar), ggml_backend_name(backend));
        }
    }
'''
DIGEST='''            // Both control and GPU packing diagnostics hash the actual full
            // projector output. No checksums of private images in normal mode.
            if (!imgs.is_audio && std::getenv("GGUF_VERIFY_IMAGE_PACK")) {
                const auto digest = hash_sha256_hex(out_batch_embd.data(), out_batch_embd.size()*sizeof(float));
                LOG_INF("GGUF_IMAGE_PACK_EMBEDDING sha256=%s bytes=%zu\\n", digest.c_str(), out_batch_embd.size()*sizeof(float));
            }
'''

def patch_image_upload(source):
    p=source/'tools/mtmd/clip.cpp';s=p.read_text()
    if 'GGUF_VULKAN_IMAGE_PACK_GRAPH' in s:
        assert LAYOUT in s and GRAPH_NEW in s and UPLOAD in s and VERIFY in s and DIGEST in s,'Stale image upload patch'
        return
    marker='ggml_tensor * clip_graph::build_inp_raw(int channels) {'
    assert s.count(marker)==1;s=s.replace(marker,LAYOUT+'\n'+marker)
    assert s.count(GRAPH_OLD)==1;s=s.replace(GRAPH_OLD,GRAPH_NEW)
    marker='    // set input pixel values\n    if (!imgs.is_audio) {'
    assert s.count(marker)==1;s=s.replace(marker,'    // set input pixel values\n'+UPLOAD)
    marker='        set_input_f32("inp_raw", inp_raw);'
    assert s.count(marker)==1;s=s.replace(marker,marker+'\n        LOG_INF("GGUF_IMAGE_UPLOAD packing=CPU bytes=%zu host_planar_copy=1\\n", inp_raw.size()*sizeof(float));')
    marker='    // the last node is the embedding tensor, code2wav has no out_embd'
    assert s.count(marker)==1;s=s.replace(marker,VERIFY+'\n'+marker)
    marker='            ggml_backend_tensor_get(embeddings, out_batch_embd.data(), 0, ggml_nbytes(embeddings));'
    assert s.count(marker)==1;s=s.replace(marker,marker+'\n'+DIGEST)
    s=s.replace('#include "gguf.h"','#include "gguf.h"\n#include "hash/hash.h"')
    p.write_text(s)
