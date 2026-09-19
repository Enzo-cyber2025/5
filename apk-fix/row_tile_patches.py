"""Opt-in experiment: amortize standard- and k-quant matvec workgroups.

The pinned shaders already compute NUM_ROWS independent rows per workgroup. The
dispatch divides the row count by the pipeline's wg_denoms, so raising the row
multiplier cuts the number of dispatched workgroups without touching shader
source, reduction order, activation policy or precision. Every quant family the
fixture uses is covered so the effect is not limited to one weight type.
"""
from pathlib import Path

MARKER = 'GGUF_ROW_TILE_EXPERIMENT'
ANCHOR = '    const bool use_subgroups = device->subgroup_arithmetic;\n'
BLOCK = '''#if defined(GGUF_EXPERIMENT_ROW_TILE)
    // GGUF_ROW_TILE_EXPERIMENT: fixed predeclared factor, not runtime autotuning.
    uint32_t gguf_row_factor = 1;
    if (const char * setting = getenv("GGUF_VK_ROW_TILE")) {
        bool accepted = false;
        for (const char * candidate : {"1", "2", "4", "8"}) {
            if (strcmp(setting, candidate) == 0) accepted = true;
        }
        GGML_LOG_INFO("GGUF_VK_ROW_TILE_PRE setting=%s device=%s fp16=%u int_dot=%u subgroup=%u max_wg=%u stdq=%u kq=%u stdq_int=%u kq_int=%u\\n",
            setting, device->properties.deviceName, uint32_t(device->fp16), uint32_t(device->integer_dot_product),
            device->subgroup_size, device->properties.limits.maxComputeWorkGroupInvocations,
            rm_stdq, rm_kq, rm_stdq_int, rm_kq_int);
        if (!accepted) {
            throw std::runtime_error("GGUF row tile experiment accepts only 1, 2, 4 or 8; unset for control");
        }
        const bool software_fp32 = std::string(device->properties.deviceName).find("llvmpipe") != std::string::npos &&
                                   !device->fp16 && !device->integer_dot_product &&
                                   device->subgroup_size == 8 && rm_stdq == 1 && rm_kq == 2 && rm_stdq_int == 1 && rm_kq_int == 1;
        if (!software_fp32 || getenv("GGML_VK_FORCE_MMVQ") || getenv("GGML_VK_DISABLE_MMVQ")) {
            throw std::runtime_error("GGUF row tile experiment requires the measured llvmpipe FP32 device, int-dot off, subgroup 8, default MMV policy");
        }
        gguf_row_factor = uint32_t(atoi(setting));
        rm_stdq *= gguf_row_factor;
        rm_kq *= gguf_row_factor;
        rm_stdq_int *= gguf_row_factor;
        rm_kq_int *= gguf_row_factor;
        // One workgroup must stay inside the driver's invocation limit.
        const uint32_t rows_per_workgroup = 2 * std::max(rm_stdq, rm_kq);
        if (rows_per_workgroup * device->subgroup_size > device->properties.limits.maxComputeWorkGroupInvocations) {
            throw std::runtime_error("GGUF row tile factor exceeds the driver workgroup limit");
        }
    }
    GGML_LOG_INFO("GGUF_VK_ROW_TILE factor=%u stdq=%u kq=%u stdq_int=%u kq_int=%u q5_rows=%u q8_rows=%u kq_rows=%u fp16=%u int_dot=%u subgroup=%u\\n",
        gguf_row_factor, rm_stdq, rm_kq, rm_stdq_int, rm_kq_int, 2*rm_stdq, rm_stdq, rm_kq,
        uint32_t(device->fp16), uint32_t(device->integer_dot_product), device->subgroup_size);
#endif
'''
DISPATCH_BLOCK = '''#if defined(GGUF_EXPERIMENT_ROW_TILE)
        // GGUF_ROW_TILE_DISPATCH_AUDIT
        if (ne11 == 1 && (src0->type == GGML_TYPE_Q5_0 || src0->type == GGML_TYPE_Q8_0 ||
                          src0->type == GGML_TYPE_Q4_K || src0->type == GGML_TYPE_Q6_K)) {
            static std::once_flag gguf_row_seen[4];
            const unsigned slot = src0->type == GGML_TYPE_Q5_0 ? 0 : src0->type == GGML_TYPE_Q8_0 ? 1 :
                                  src0->type == GGML_TYPE_Q4_K ? 2 : 3;
            std::call_once(gguf_row_seen[slot], [&]() {
                GGML_LOG_INFO("GGUF_VK_ROW_TILE_DISPATCH type=%s rows=%u activation=%s quantize_y=%u columns=%u\\n",
                    ggml_type_name(src0->type), dmmv->wg_denoms[0], ggml_type_name(src1->type),
                    uint32_t(quantize_y), uint32_t(ne11));
            });
        }
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
