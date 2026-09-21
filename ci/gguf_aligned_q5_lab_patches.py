"""LAB ONLY. Give the decode matvec a four byte aligned Q5 weight layout.

Measured basis (llvmpipe, saturated grid, 256 MiB stream, run 35515986619):

    five scattered word loads per eight MACs    1.230 GMAC/s  (the pinned shape)
    one header word plus one nibble word        2.009 GMAC/s  (1.63x)
    one word with an amortised header           2.544 GMAC/s  (2.07x)

The pinned Q5_0 block is 22 bytes (d, qh[2], qs[16]) and the matvec reads it as
sixteen bit fields: two halves of the high bit mask, two halves of the nibbles and
the scale, per four values, per row. Nothing in that block is four byte aligned,
so no shader can turn those reads into word loads.

This patch rewrites every Q5_0 weight tensor once, on the host, into a Q5_1
tensor of the same element count. A Q5_1 block is 24 bytes, four byte aligned,
and its fields are exactly where the aligned reads need them:

    bytes 0..1   d            copied from the Q5_0 block
    bytes 2..3   m            zero, the Q5_0 path has no min term
    bytes 4..7   qh           qh[1] << 16 | qh[0], the value Q5_0 builds itself
    bytes 8..23  qs           the same sixteen nibble bytes

Only integer copies: no requantisation, no rounding, no new scale. The matvec
shader then reads one word of nibbles per four values and one word of mask per
four values, subtracts 16 exactly as the Q5_0 shader does, and multiplies the row
sum by d exactly as before. Every intermediate value is the one the Q5_0 path
computed, so the output is bit identical; the lab re-measures the greedy fixture
text to prove it.

The prompt path (n > 8) keeps reading the original Q5_0 buffer with the original
shaders, so prompt results cannot change.

Never part of a release: this module is applied to the lab checkout only.
"""
from pathlib import Path

MARKER = 'GGUF_ALIGNED_Q5'

# ---------------------------------------------------------------------------
# Shader: read the aligned block with word loads.
# ---------------------------------------------------------------------------
DEQUANT_ANCHOR = '''#if defined(DATA_A_Q5_1)
vec2 dequantize(uint ib, uint iqs, uint a_offset) {
    const uint uint_qh = data_a[a_offset + ib].qh;
    const ivec2 qh = ivec2(((uint_qh >> iqs) << 4) & 0x10, (uint_qh >> (iqs + 12)) & 0x10);
    const uint vui = uint(data_a[a_offset + ib].qs[iqs]);
    return vec2((vui & 0xF) | qh.x, (vui >> 4) | qh.y);
}
vec4 dequantize4(uint ib, uint iqs, uint a_offset) {
    const uint uint_qh = data_a_packed16[a_offset + ib].qh;
    const ivec2 qh0 = ivec2(((uint_qh >> iqs) << 4) & 0x10, (uint_qh >> (iqs + 12)) & 0x10);
    const ivec2 qh1 = ivec2(((uint_qh >> (iqs + 1)) << 4) & 0x10, (uint_qh >> (iqs + 13)) & 0x10);
    const uint vui = uint(data_a_packed16[a_offset + ib].qs[iqs/2]);
    return vec4((vui & 0xF) | qh0.x, ((vui >> 4) & 0xF) | qh0.y, ((vui >> 8) & 0xF) | qh1.x, (vui >> 12) | qh1.y);
}
#endif
'''

DEQUANT_ALIGNED = '''#if defined(DATA_A_Q5_1)
// GGUF_ALIGNED_Q5: the buffer holds four byte aligned Q5_1 blocks whose values
// are encoded exactly like Q5_0 values (5 bit code, decoded as code - 16), so
// this reads words instead of halves and subtracts the same 16.
vec2 dequantize(uint ib, uint iqs, uint a_offset) {
    const uint uint_qh = data_a_packed32[a_offset + ib].qh;
    const ivec2 qh = ivec2(((uint_qh >> iqs) << 4) & 0x10, (uint_qh >> (iqs + 12)) & 0x10);
    const uint vui = data_a_packed32[a_offset + ib].qs[iqs/4];
    return vec2((vui & 0xF) | qh.x, (vui >> 4) | qh.y) - 16.0f;
}
vec4 dequantize4(uint ib, uint iqs, uint a_offset) {
    const uint uint_qh = data_a_packed32[a_offset + ib].qh;
    const ivec2 qh0 = ivec2(((uint_qh >> iqs) << 4) & 0x10, (uint_qh >> (iqs + 12)) & 0x10);
    const ivec2 qh1 = ivec2(((uint_qh >> (iqs + 1)) << 4) & 0x10, (uint_qh >> (iqs + 13)) & 0x10);
    const uint vui = data_a_packed32[a_offset + ib].qs[iqs/4];
    return vec4((vui & 0xF) | qh0.x, ((vui >> 4) & 0xF) | qh0.y, ((vui >> 8) & 0xF) | qh1.x, (vui >> 12) | qh1.y) - 16.0f;
}
// Eight values at once: one mask word and one nibble word. The low half of the
// nibble word carries the first four values (bytes iqs and iqs+1 of the original
// block, low and high nibbles) and the high half the next four.
void dequantize8(uint ib, uint iqs, uint a_offset, out vec4 v0, out vec4 v1) {
    const uint uint_qh = data_a_packed32[a_offset + ib].qh;
    const uint w0 = data_a_packed32[a_offset + ib].qs[iqs/4];
    const ivec2 qh0 = ivec2(((uint_qh >> iqs) << 4) & 0x10, (uint_qh >> (iqs + 12)) & 0x10);
    const ivec2 qh1 = ivec2(((uint_qh >> (iqs + 1)) << 4) & 0x10, (uint_qh >> (iqs + 13)) & 0x10);
    const ivec2 qh2 = ivec2(((uint_qh >> (iqs + 2)) << 4) & 0x10, (uint_qh >> (iqs + 14)) & 0x10);
    const ivec2 qh3 = ivec2(((uint_qh >> (iqs + 3)) << 4) & 0x10, (uint_qh >> (iqs + 15)) & 0x10);
    v0 = vec4((w0 & 0xF) | qh0.x, ((w0 >> 4) & 0xF) | qh0.y, ((w0 >> 8) & 0xF) | qh1.x, (w0 >> 12) | qh1.y) - 16.0f;
    v1 = vec4(((w0 >> 16) & 0xF) | qh2.x, ((w0 >> 20) & 0xF) | qh2.y, ((w0 >> 24) & 0xF) | qh3.x, (w0 >> 28) | qh3.y) - 16.0f;
}
#endif
'''

# The matvec tail already calls dequantize4 twice; make the aligned path use the
# single eight value reader instead, so the mask and nibble words are read once.
MATVEC_ANCHOR = '''            vec4 v = dequantize4(ib, iqs, a_offset);
            vec4 v2 = dequantize4(ib, iqs+(4/QUANT_R), a_offset);
'''

MATVEC_ALIGNED = '''#if defined(DATA_A_Q5_1)
            // GGUF_ALIGNED_Q5: one mask read and two nibble words for eight values.
            vec4 v;
            vec4 v2;
            dequantize8(ib, iqs, a_offset, v, v2);
#else
            vec4 v = dequantize4(ib, iqs, a_offset);
            vec4 v2 = dequantize4(ib, iqs+(4/QUANT_R), a_offset);
#endif
'''

# ---------------------------------------------------------------------------
# Host: rewrite the weights once, at upload, and dispatch the Q5_1 pipeline.
# ---------------------------------------------------------------------------
HOST_HELPERS = '''
// GGUF_ALIGNED_Q5 (lab only): Q5_0 weights are copied once into a four byte
// aligned Q5_1 buffer so the decode matvec can read words instead of halves.
// Same nibbles, same high bits, same scale, no requantisation.
static std::unordered_map<const ggml_tensor *, std::pair<vk_buffer, size_t>> gguf_aligned_q5_buffers;
static size_t gguf_aligned_q5_tensors = 0;
static size_t gguf_aligned_q5_bytes = 0;

static bool gguf_aligned_q5_eligible(const ggml_tensor * t) {
    if (t == nullptr || t->type != GGML_TYPE_Q5_0) return false;
    if (!ggml_is_contiguous(t) || t->view_offs != 0) return false;
    if (t->ne[0] % ggml_blck_size(GGML_TYPE_Q5_0) != 0) return false;
    if (ggml_nbytes(t) % (size_t) ggml_type_size(t->type) != 0) return false;
    // The descriptor carries the tensor's own base address and the shader indexes
    // from there, so the copy replaces the subbuffer and nothing else. (An earlier
    // version also demanded that the tensor offset divide the 22 byte block size,
    // which silently refused all 166 q5_0 tensors of the fixture model.)
    return true;
}

static void gguf_aligned_q5_store_from_bytes(vk_device & device, const ggml_tensor * t, const void * data) {
    const size_t blocks = ggml_nelements(t) / ggml_blck_size(t->type);
    const uint8_t * src = (const uint8_t *) data;
    std::vector<uint8_t> packed(blocks * 24);
    for (size_t b = 0; b < blocks; ++b) {
        const uint8_t * s = src + b * 22;
        uint8_t * d = packed.data() + b * 24;
        d[0] = s[0]; d[1] = s[1];             // d
        d[2] = 0;    d[3] = 0;                // m, unused by the aligned reader
        d[4] = s[2]; d[5] = s[3];             // qh low
        d[6] = s[4]; d[7] = s[5];             // qh high
        memcpy(d + 8, s + 6, 16);             // nibbles, unchanged
    }
    vk_buffer buf = ggml_vk_create_buffer_device(device, packed.size());
    ggml_vk_buffer_write(buf, 0, packed.data(), packed.size());
    gguf_aligned_q5_buffers[t] = { buf, packed.size() };
    gguf_aligned_q5_tensors++;
    gguf_aligned_q5_bytes += packed.size();
    std::cerr << "GGUF_ALIGNED_Q5 tensor=" << t->name << " blocks=" << blocks
              << " bytes=" << packed.size() << std::endl;
}

// Used by the upload hook, which receives a vk_device.
static void gguf_aligned_q5_store(vk_device & device, const ggml_tensor * t, const void * data) {
    gguf_aligned_q5_store_from_bytes(device, t, data);
}

// One-time fallback: read the tensor back from its device buffer, repack it and
// keep the aligned copy. This exists because the upload hook depends on how the
// model loader hands data to the backend, and a relayout that silently never runs
// would be presented as a flat measurement.
static vk_buffer gguf_aligned_q5_lazy(ggml_backend_vk_context * ctx, const ggml_tensor * t) {
    const size_t bytes = ggml_nbytes(t);
    if (bytes == 0 || bytes % (size_t) ggml_type_size(t->type) != 0) return nullptr;
    vk_subbuffer sub = ggml_vk_tensor_subbuffer(ctx, t);  // buffer_read takes a non-const reference
    if (sub.buffer == nullptr || sub.size < bytes) return nullptr;
    std::vector<uint8_t> original(bytes);
    ggml_vk_buffer_read(sub.buffer, sub.offset, original.data(), bytes);
    gguf_aligned_q5_store_from_bytes(ctx->device, t, original.data());
    std::cerr << "GGUF_ALIGNED_Q5_LAZY name=" << t->name << " bytes=" << bytes << std::endl;
    auto it = gguf_aligned_q5_buffers.find(t);
    return it == gguf_aligned_q5_buffers.end() ? nullptr : it->second.first;
}

static vk_buffer gguf_aligned_q5_lookup(const ggml_tensor * t) {
    auto it = gguf_aligned_q5_buffers.find(t);
    if (it == gguf_aligned_q5_buffers.end()) return nullptr;
    // A recycled tensor address must not bind a buffer of another size.
    const size_t expected = (ggml_nelements(t) / ggml_blck_size(t->type)) * 24u;
    if (it->second.second != expected) return nullptr;
    return it->second.first;
}

'''

SET_TENSOR_ANCHOR = '''    if (size == 0) {
        return;
    }

    ggml_vk_buffer_write(buf, vk_tensor_offset(tensor) + tensor->view_offs + offset, data, size);
}
'''

SET_TENSOR_PATCHED = '''    if (size == 0) {
        return;
    }

    // GGUF_ALIGNED_Q5 diagnostic: what the loader actually hands the backend.
    if (tensor->type == GGML_TYPE_Q5_0) {
        std::cerr << "GGUF_ALIGNED_Q5_SET name=" << tensor->name << " offset=" << offset
                  << " size=" << size << " nbytes=" << ggml_nbytes(tensor)
                  << " eligible=" << (gguf_aligned_q5_eligible(tensor) ? 1 : 0) << std::endl;
    }
    // GGUF_ALIGNED_Q5: whole tensor upload of a Q5_0 weight becomes the aligned copy.
    if (gguf_aligned_q5_eligible(tensor) && offset == 0 && size == ggml_nbytes(tensor) &&
        gguf_aligned_q5_buffers.find(tensor) == gguf_aligned_q5_buffers.end()) {
        gguf_aligned_q5_store(buf->device, tensor, data);
    }

    ggml_vk_buffer_write(buf, vk_tensor_offset(tensor) + tensor->view_offs + offset, data, size);
}
'''

DISPATCH_ANCHOR = '''    // Check for mmq first
    vk_pipeline dmmv = quantize_y ? ggml_vk_get_dequantize_mul_mat_vec(ctx, src0->type, GGML_TYPE_Q8_1, ne11, ne20, ne00) : nullptr;
    vk_pipeline to_q8_1 = nullptr;

    if (dmmv == nullptr) {
        // Fall back to f16 dequant mul mat
        dmmv = ggml_vk_get_dequantize_mul_mat_vec(ctx, src0->type, src1->type, ne11, ne20, ne00);
        quantize_y = false;
    }
'''

DISPATCH_PATCHED = '''    // GGUF_ALIGNED_Q5: when this weight has an aligned copy, read it with the
    // Q5_1 pipelines, which the aligned layout was built for. The quantised
    // activation path (mmq) is refused for those: its Q5_1 arithmetic takes the
    // -16 offset from the block's min term, which this layout does not carry, so
    // it would add a constant to every dot product. The aligned shader subtracts
    // the same 16 the Q5_0 shader subtracts.
    vk_buffer gguf_aligned_q5 = gguf_aligned_q5_lookup(src0);
    if (gguf_aligned_q5 == nullptr && gguf_aligned_q5_eligible(src0)) {
        gguf_aligned_q5 = gguf_aligned_q5_lazy(ctx, src0);
    }
    const ggml_type gguf_aligned_q5_type = gguf_aligned_q5 != nullptr ? GGML_TYPE_Q5_1 : src0->type;
    if (gguf_aligned_q5 != nullptr) {
        quantize_y = false;
    }

    // Check for mmq first
    vk_pipeline dmmv = quantize_y ? ggml_vk_get_dequantize_mul_mat_vec(ctx, gguf_aligned_q5_type, GGML_TYPE_Q8_1, ne11, ne20, ne00) : nullptr;
    vk_pipeline to_q8_1 = nullptr;

    if (dmmv == nullptr) {
        // Fall back to f16 dequant mul mat
        dmmv = ggml_vk_get_dequantize_mul_mat_vec(ctx, gguf_aligned_q5_type, src1->type, ne11, ne20, ne00);
        quantize_y = false;
    }
'''

SUBBUFFER_ANCHOR = """    vk_subbuffer d_Qy = ggml_vk_tensor_subbuffer(ctx, src1);
    vk_subbuffer d_X, d_Y;
"""

SUBBUFFER_PATCHED = """    vk_subbuffer d_Qy = ggml_vk_tensor_subbuffer(ctx, src1);
    vk_subbuffer d_X, d_Y;

    if (gguf_aligned_q5 != nullptr && !qx_needs_dequant) {
        // GGUF_ALIGNED_Q5: bind the aligned copy, which the Q5_1 pipeline expects.
        // Non-contiguous input would be copied from this subbuffer with the type
        // size of the original, so those keep the original path.
        d_Qx = { gguf_aligned_q5, 0, gguf_aligned_q5->size };
    }
"""



# The model loader uploads weights through the backend's async path, not through the
# buffer interface, so the relayout has to hook there. Without this the copy never
# happens and a flat result looks like a slow kernel instead of an unused one.
ASYNC_ANCHOR = 'static void ggml_backend_vk_set_tensor_async(ggml_backend_t backend, ggml_tensor * tensor, const void * data, size_t offset, size_t size) {'

ASYNC_PATCHED = '''static void ggml_backend_vk_set_tensor_async(ggml_backend_t backend, ggml_tensor * tensor, const void * data, size_t offset, size_t size) {
    // GGUF_ALIGNED_Q5: the model loader uploads weights through this async path,
    // which never reaches the buffer's set_tensor, so the relayout hooks here.
    if (tensor->type == GGML_TYPE_Q5_0) {
        std::cerr << "GGUF_ALIGNED_Q5_ASYNC name=" << tensor->name << " offset=" << offset
                  << " size=" << size << " nbytes=" << ggml_nbytes(tensor)
                  << " eligible=" << (gguf_aligned_q5_eligible(tensor) ? 1 : 0) << std::endl;
    }
    if (gguf_aligned_q5_eligible(tensor) && offset == 0 && size == ggml_nbytes(tensor) &&
        gguf_aligned_q5_buffers.find(tensor) == gguf_aligned_q5_buffers.end() &&
        tensor->buffer != nullptr && tensor->buffer->buft == ggml_backend_vk_get_default_buffer_type(backend)) {
        ggml_backend_vk_buffer_context * gguf_buf_ctx = (ggml_backend_vk_buffer_context *) tensor->buffer->context;
        vk_device gguf_device = gguf_buf_ctx->device.lock();
        if (gguf_device != nullptr) {
            gguf_aligned_q5_store(gguf_device, tensor, data);
        }
    }
'''


def once(source, anchor, replacement, marker):
    if marker in source:
        return source
    assert source.count(anchor) == 1, f'anchor changed: {marker}'
    return source.replace(anchor, replacement, 1)


def apply(root):
    shaders = Path(root) / 'ggml/src/ggml-vulkan/vulkan-shaders'
    dequant = shaders / 'dequant_funcs.glsl'
    text = dequant.read_text()
    text = once(text, DEQUANT_ANCHOR.replace('vec2 dequantize(uint ib, uint iqs, uint a_offset) {\n    const uint uint_qh = data_a[a_offset + ib].qh;',
                                             'vec2 dequantize(uint ib, uint iqs, uint a_offset) {\n    const uint uint_qh = data_a[a_offset + ib].qh;'),
                 DEQUANT_ALIGNED, MARKER)
    dequant.write_text(text)

    matvec = shaders / 'mul_mat_vec.comp'
    text = matvec.read_text()
    text = once(text, MATVEC_ANCHOR, MATVEC_ALIGNED, MARKER + '_MMV')
    matvec.write_text(text)

    cpp = Path(root) / 'ggml/src/ggml-vulkan/ggml-vulkan.cpp'
    text = cpp.read_text()
    # The helpers are used by the matvec dispatch and by set_tensor, so they go
    # before the first user; the buffer helpers they need are defined earlier.
    host_anchor = 'static void ggml_vk_mul_mat_vec_q_f16(ggml_backend_vk_context * ctx, vk_context& subctx, const struct ggml_cgraph * cgraph, int node_idx, bool swap_inputs = false) {'
    text = once(text, host_anchor, HOST_HELPERS + host_anchor, MARKER + '_HOST')
    text = once(text, SET_TENSOR_ANCHOR, SET_TENSOR_PATCHED, MARKER + '_SET')
    text = once(text, DISPATCH_ANCHOR, DISPATCH_PATCHED, MARKER + '_DISPATCH')
    text = once(text, SUBBUFFER_ANCHOR, SUBBUFFER_PATCHED, MARKER + '_SUB')
    text = once(text, ASYNC_ANCHOR, ASYNC_PATCHED, MARKER + '_ASYNC')
    cpp.write_text(text)
    return None
