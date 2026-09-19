"""Opt-in experiment: amortize standard-quant matvec workgroups, not math/precision.

Pinned shaders already compute NUM_ROWS independent rows. Change their shared
row multiplier, keeping shader source, reduction and workgroup width untouched.
The experiment is intentionally restricted to the measured FP32 software driver.
"""
from pathlib import Path

MARKER = 'GGUF_ROW_TILE_EXPERIMENT'
ANCHOR = '    // RDNA3: above four columns, static 4 rows for all types bench faster than the default\n'
BLOCK = '''#if defined(GGUF_EXPERIMENT_ROW_TILE)
    // GGUF_ROW_TILE_EXPERIMENT: fixed predeclared factor, not runtime autotuning.
    uint32_t gguf_row_factor = 1;
    if (const char * setting = getenv("GGUF_VK_ROW_TILE")) {
        if (strcmp(setting, "4") != 0) {
            throw std::runtime_error("GGUF row tile experiment accepts only factor 4; unset for control");
        }
        if (device->name.find("llvmpipe") == std::string::npos || device->fp16 ||
            device->integer_dot_product || getenv("GGML_VK_FORCE_MMVQ") || getenv("GGML_VK_DISABLE_MMVQ") ||
            device->subgroup_size != 8 || rm_stdq != 1) {
            throw std::runtime_error("GGUF row tile experiment requires llvmpipe FP32, int-dot off, subgroup 8, default MMV policy");
        }
        gguf_row_factor = 4;
        rm_stdq *= gguf_row_factor;
    }
    GGML_LOG_INFO("GGUF_VK_ROW_TILE factor=%u stdq=%u q5_rows=%u q8_rows=%u fp16=%u int_dot=%u subgroup=%u\\n",
        gguf_row_factor, rm_stdq, 2*rm_stdq, rm_stdq,
        uint32_t(device->fp16), uint32_t(device->integer_dot_product), device->subgroup_size);
#endif
'''


def patch(source):
    if MARKER in source:
        assert source.count(BLOCK) == source.count(DISPATCH_BLOCK) == 1, 'Unexpected partial row-tile patch'
        return source
    assert source.count(ANCHOR) == 1, 'Pinned row-tile anchor changed'
    source = source.replace(ANCHOR, BLOCK + ANCHOR, 1)
    start = source.index('static void ggml_vk_mul_mat_vec_q_f16(')
    end = source.index('static void ggml_vk_mul_mat_vec_p021_f16_f32(', start)
    part = source[start:end]
    anchor = '        base_work_group_y += groups_y;'
    assert part.count(anchor) == 1
    part = part.replace(anchor, DISPATCH_BLOCK + anchor, 1)
    return source[:start] + part + source[end:]


def apply(root):
    path = Path(root) / 'ggml/src/ggml-vulkan/ggml-vulkan.cpp'
    path.write_text(patch(path.read_text()))

# One recorded single-column dispatch per relevant weight type, not a timing
# profiler. Native completion/strict audits separately establish execution.
DISPATCH_BLOCK = '''#if defined(GGUF_EXPERIMENT_ROW_TILE)
        // GGUF_ROW_TILE_DISPATCH_AUDIT
        if (ne11 == 1 && (src0->type == GGML_TYPE_Q5_0 || src0->type == GGML_TYPE_Q8_0)) {
            static std::once_flag gguf_row_seen[2];
            const unsigned slot = src0->type == GGML_TYPE_Q5_0 ? 0 : 1;
            std::call_once(gguf_row_seen[slot], [&]() {
                GGML_LOG_INFO("GGUF_VK_ROW_TILE_DISPATCH type=%s rows=%u activation=%s quantize_y=%u columns=%u\\n",
                    ggml_type_name(src0->type), dmmv->wg_denoms[0], ggml_type_name(src1->type),
                    uint32_t(quantize_y), uint32_t(ne11));
            });
        }
#endif
'''
