"""LAB ONLY: vector accumulators instead of a horizontal dot() per k-iteration.

The pinned DMMV shader computes, for every k-iteration and every row,

    rowtmp  = dot(bv0, v);
    rowtmp += dot(bv1, v2);
    temp    += rowtmp;

A `dot()` on a vec4 lowers to a vector multiply plus a horizontal add chain, so
each 8-element step costs about 14 scalar operations for 8 multiply-accumulates
inside the hottest loop of decode. Element-wise accumulation into vec4 registers
is the same set of products with the same per-block scale, reduced once per row
after the loop: about 8 fused multiply-adds for the same 8 products. Only the
summation order changes, and no precision, layout, activation policy, row
grouping or workgroup constant is touched.

This module is applied by the llvmpipe host lab only (ci/llvmpipe_lab_patches.py
looks in ci/ as well). It is not a mobile patch, not compiled into any APK and
not part of any acceptance result: it exists to test the hypothesis cheaply on
the CPU Vulkan device before anything is ported to the app.
"""
from pathlib import Path

TARGET = 'ggml/src/ggml-vulkan/vulkan-shaders/mul_mat_vec.comp'

GLOBALS_ANCHOR = 'uint a_offset, b_offset, d_offset, y_offset;\n'
GLOBALS = '''// LAB: per-element accumulators, declared once per invocation.
vec4 gguf_acc0[NUM_COLS][NUM_ROWS];
vec4 gguf_acc1[NUM_COLS][NUM_ROWS];
'''

INIT_ANCHOR = '''    [[unroll]] for (uint j = 0; j < NUM_COLS; ++j) {
        [[unroll]] for (uint i = 0; i < NUM_ROWS; ++i) {
            temp[j][i] = FLOAT_TYPE(0);
        }
    }
'''
INIT = INIT_ANCHOR + '''    [[unroll]] for (uint j = 0; j < NUM_COLS; ++j) {
        [[unroll]] for (uint i = 0; i < NUM_ROWS; ++i) {
            gguf_acc0[j][i] = vec4(0);
            gguf_acc1[j][i] = vec4(0);
        }
    }
'''

INNER_ANCHOR = '''            // matrix multiplication
            FLOAT_TYPE rowtmp = dot(bv0, v);
            rowtmp += dot(bv1, v2);

            if (dm.y == 0)
                rowtmp *= dm.x;

            temp[j][n] += rowtmp;
'''
INNER = '''            // LAB: element-wise accumulate, reduce once per row after the loop.
            if (dm.y == 0) {
                gguf_acc0[j][n] += (v * dm.x) * bv0;
                gguf_acc1[j][n] += (v2 * dm.x) * bv1;
            } else {
                gguf_acc0[j][n] += v * bv0;
                gguf_acc1[j][n] += v2 * bv1;
            }
'''

FINAL_ANCHOR = '    reduce_result(temp, d_offset, first_row, num_rows, tid);\n'
FINAL = '''    [[unroll]] for (uint j = 0; j < NUM_COLS; ++j) {
        [[unroll]] for (uint n = 0; n < num_rows; ++n) {
            const vec4 a0 = gguf_acc0[j][n];
            const vec4 a1 = gguf_acc1[j][n];
            temp[j][n] += ((a0.x + a0.y) + (a0.z + a0.w)) + ((a1.x + a1.y) + (a1.z + a1.w));
        }
    }

''' + FINAL_ANCHOR


def patch_shader(source):
    for name, anchor, replacement in (('globals', GLOBALS_ANCHOR, GLOBALS),
                                      ('accumulator init', INIT_ANCHOR, INIT),
                                      ('inner loop', INNER_ANCHOR, INNER),
                                      ('final reduction', FINAL_ANCHOR, FINAL)):
        assert source.count(anchor) == 1, f'LAB accum: {name} anchor changed'
        source = source.replace(anchor, replacement, 1)
    return source


def apply(root):
    path = Path(root) / TARGET
    text = path.read_text()
    assert 'gguf_acc0' not in text, 'LAB accum patch already applied'
    path.write_text(patch_shader(text))
    return 'mul_mat_vec.comp inner loop accumulates element-wise (LAB)'
