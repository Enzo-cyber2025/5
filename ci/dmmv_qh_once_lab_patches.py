"""LAB ONLY. Load each quantised block's high-bit word once per iteration.

`iter()` in the shipped matvec calls `dequantize4` twice per k-iteration (once
for the low nibbles, once for the high ones). Both calls read the same block, so
the 32 high bits of that block are fetched from the buffer twice per eight
values. On the measured driver a storage buffer load costs about 1.27 ns against
0.135 ns per MAC, so those redundant fetches are the single cheapest thing to
remove without touching a single arithmetic operation: the same bits, the same
shifts, the same order, therefore bit-identical results.

This module only rewrites the shared standard-quant matvec shader. It never
enters the delivered APK.
"""
from pathlib import Path

MARKER = 'GGUF_LAB_QH_ONCE'

# ---------------------------------------------------------------------------
# 1. dequant_funcs.glsl: provide dequantize8() alongside dequantize4().
# ---------------------------------------------------------------------------
DEQUANT_ANCHOR = '#define DATA_A_QUANT_LEGACY\n#endif\n'

Q5_0_FUNC = '''
// GGUF_LAB_QH_ONCE: eight values of the same block, one high-bit fetch.
void dequantize8_q5_0(uint ib, uint iqs, uint a_offset, out vec4 v0, out vec4 v1) {
    const uint uint_qh = uint(data_a_packed16[a_offset + ib].qh[1]) << 16 |
                         uint(data_a_packed16[a_offset + ib].qh[0]);
    const ivec2 qh0 = ivec2(((uint_qh >> iqs) << 4) & 0x10, (uint_qh >> (iqs + 12)) & 0x10);
    const ivec2 qh1 = ivec2(((uint_qh >> (iqs + 1)) << 4) & 0x10, (uint_qh >> (iqs + 13)) & 0x10);
    const ivec2 qh2 = ivec2(((uint_qh >> (iqs + 2)) << 4) & 0x10, (uint_qh >> (iqs + 14)) & 0x10);
    const ivec2 qh3 = ivec2(((uint_qh >> (iqs + 3)) << 4) & 0x10, (uint_qh >> (iqs + 15)) & 0x10);
    const uint w0 = uint(data_a_packed16[a_offset + ib].qs[iqs/2]);
    const uint w1 = uint(data_a_packed16[a_offset + ib].qs[iqs/2 + 1]);
    v0 = vec4((w0 & 0xF) | qh0.x, ((w0 >> 4) & 0xF) | qh0.y,
              ((w0 >> 8) & 0xF) | qh1.x, (w0 >> 12) | qh1.y) - 16.0f;
    v1 = vec4((w1 & 0xF) | qh2.x, ((w1 >> 4) & 0xF) | qh2.y,
              ((w1 >> 8) & 0xF) | qh3.x, (w1 >> 12) | qh3.y) - 16.0f;
}
'''

ITER_ANCHOR = '''            vec4 v = dequantize4(ib, iqs, a_offset);
            vec4 v2 = dequantize4(ib, iqs+(4/QUANT_R), a_offset);
'''

ITER_Q5_0 = '''#ifdef DATA_A_Q5_0
            // GGUF_LAB_QH_ONCE: one high-bit fetch serves both halves.
            vec4 v;
            vec4 v2;
            dequantize8_q5_0(ib, iqs, a_offset, v, v2);
#else
            vec4 v = dequantize4(ib, iqs, a_offset);
            vec4 v2 = dequantize4(ib, iqs+(4/QUANT_R), a_offset);
#endif
'''


def patch_dequant(source):
    if MARKER in source:
        return source
    assert source.count(DEQUANT_ANCHOR) >= 1, 'pinned DATA_A_QUANT_LEGACY anchor changed'
    # insert the helper right after the Q5_0 dequantize4 definition
    anchor = '''    return (vec4((vui & 0xF) | qh0.x, ((vui >> 4) & 0xF) | qh0.y, ((vui >> 8) & 0xF) | qh1.x, (vui >> 12) | qh1.y) - 16.0f);
}
#endif
'''
    assert source.count(anchor) == 1, 'pinned Q5_0 dequantize4 body changed'
    source = source.replace(anchor, anchor + Q5_0_FUNC, 1)
    return source


def patch_matvec(source):
    if MARKER in source:
        return source
    assert source.count(ITER_ANCHOR) == 1, 'pinned matvec dequant call site changed'
    return source.replace(ITER_ANCHOR, ITER_Q5_0, 1)


def apply(root):
    base = Path(root) / 'ggml/src/ggml-vulkan/vulkan-shaders'
    dequant = base / 'dequant_funcs.glsl'
    dequant.write_text(patch_dequant(dequant.read_text()))
    matvec = base / 'mul_mat_vec.comp'
    matvec.write_text(patch_matvec(matvec.read_text()))
    return None
