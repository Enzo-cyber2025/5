"""Opt-in screening lever: wider dequant-matvec workgroups on the measured device.

Upstream already prefers DMMV_WG_SIZE_LARGE for Nvidia/Intel heuristics. This
extends that same upstream variant choice to the measured software device, so
each output row is covered by four times more lanes. Shader source, precision,
activation policy and the number of rows per workgroup are unchanged; the
pipeline constants follow the variant upstream already ships (same shader, larger
BLOCK_SIZE and the hybrid reduction it already uses on other vendors).
The workgroup invocation limit for this combination is enforced by the row
grouping block, which owns the row multiplier.
"""
from pathlib import Path

MARKER = 'GGUF_DMMV_LARGE_EXPERIMENT'
ANCHOR = (
    '    if (b_type == GGML_TYPE_Q8_1) {\n'
    '        if (ctx->device->vendor_id == VK_VENDOR_ID_INTEL) {\n'
    '            dmmv_wg = DMMV_WG_SIZE_SUBGROUP;\n'
    '        }\n'
    '        return ctx->device->pipeline_dequant_mul_mat_vec_q8_1_f32[dmmv_wg][a_type][num_cols-1];\n'
    '    }\n'
)
BLOCK = '''    // GGUF_DMMV_LARGE_EXPERIMENT: same upstream variant, selected for the measured software device.
    if (getenv("GGUF_VK_DMMV_LARGE") && num_cols == 1 && b_type == GGML_TYPE_F32 &&
        std::string(ctx->device->properties.deviceName).find("llvmpipe") != std::string::npos) {
        dmmv_wg = DMMV_WG_SIZE_LARGE;
    }
'''


def patch(source):
    if MARKER in source:
        assert source.count(MARKER) == 1, 'Unexpected partial large-workgroup patch'
        return source
    assert source.count(ANCHOR) == 1, 'Pinned dmmv workgroup anchor changed'
    return source.replace(ANCHOR, BLOCK + ANCHOR, 1)


def apply(root):
    path = Path(root) / 'ggml/src/ggml-vulkan/ggml-vulkan.cpp'
    path.write_text(patch(path.read_text()))
