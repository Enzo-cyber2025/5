"""LAB ONLY. Rewrite the shipped 8-element matvec accumulation, nothing else.

The pinned inner loop reduces horizontally inside every k-iteration:

    FLOAT_TYPE rowtmp = dot(bv0, v);
    rowtmp += dot(bv1, v2);
    if (dm.y == 0) rowtmp *= dm.x;
    temp[j][n] += rowtmp;

A horizontal dot() is a multiply of two vec4 plus a three-step add tree of the
four lanes, so eight MACs cost roughly fourteen scalar-ish operations. Keeping
the products in vec4 accumulators and reducing once per row instead costs two
vector FMAs per eight MACs, which is the shape every CPU kernel uses.

The change is arithmetic, not precision: the same products of the same inputs
reach the same row sum, in a different association order, so the greedy text of
the fixture is re-measured by the lab before anything else is believed.

This module patches only vulkan-shaders/mul_mat_vec.comp (the shared standard
quant matvec: q5_0, q8_0, q4_0 ...). It never enters the delivered APK and is
applied to the lab checkout only.
"""
from pathlib import Path

MARKER = 'GGUF_LAB_VEC_ACCUM'

ANCHOR_DECL = 'uint a_offset, b_offset, d_offset, y_offset;\n'

BLOCK_DECL = '''// GGUF_LAB_VEC_ACCUM: per-lane vector accumulators. The products are identical;
// only the order in which the four lanes are summed changes, and the horizontal
// reduction happens once per row instead of once per k-iteration.
vec4 gguf_acc0[NUM_COLS][NUM_ROWS];
vec4 gguf_acc1[NUM_COLS][NUM_ROWS];

'''

ANCHOR_INIT = '''    [[unroll]] for (uint j = 0; j < NUM_COLS; ++j) {
        [[unroll]] for (uint i = 0; i < NUM_ROWS; ++i) {
            temp[j][i] = FLOAT_TYPE(0);
        }
    }
'''

BLOCK_INIT = ANCHOR_INIT + '''    [[unroll]] for (uint j = 0; j < NUM_COLS; ++j) {
        [[unroll]] for (uint i = 0; i < NUM_ROWS; ++i) {
            gguf_acc0[j][i] = vec4(0.0);
            gguf_acc1[j][i] = vec4(0.0);
        }
    }
'''

ANCHOR_PRODUCT = '''            // matrix multiplication
            FLOAT_TYPE rowtmp = dot(bv0, v);
            rowtmp += dot(bv1, v2);

            if (dm.y == 0)
                rowtmp *= dm.x;

            temp[j][n] += rowtmp;
'''

BLOCK_PRODUCT = '''            // matrix multiplication, element wise: no horizontal reduction here
            if (dm.y == 0) {
                gguf_acc0[j][n] += (v * dm.x) * bv0;
                gguf_acc1[j][n] += (v2 * dm.x) * bv1;
            } else {
                // v and v2 already carry the min term
                gguf_acc0[j][n] += v * bv0;
                gguf_acc1[j][n] += v2 * bv1;
            }
'''

ANCHOR_REDUCE = '    reduce_result(temp, d_offset, first_row, num_rows, tid);\n'

BLOCK_REDUCE = '''    // one horizontal reduction per row, after the whole k loop
    [[unroll]] for (uint j = 0; j < NUM_COLS; ++j) {
        [[unroll]] for (uint n = 0; n < num_rows; ++n) {
            const vec4 a0 = gguf_acc0[j][n];
            const vec4 a1 = gguf_acc1[j][n];
            temp[j][n] += ((a0.x + a0.y) + (a0.z + a0.w)) +
                          ((a1.x + a1.y) + (a1.z + a1.w));
        }
    }
''' + ANCHOR_REDUCE


def patch(source):
    if MARKER not in source:
        assert source.count(ANCHOR_DECL) == 1, 'pinned matvec declaration anchor changed'
        assert source.count(ANCHOR_INIT) == 1, 'pinned matvec init anchor changed'
        assert source.count(ANCHOR_PRODUCT) == 1, 'pinned matvec product anchor changed'
        assert source.count(ANCHOR_REDUCE) == 1, 'pinned matvec reduce anchor changed'
    else:
        assert source.count(BLOCK_DECL) == source.count(BLOCK_INIT) == 1
        assert source.count(BLOCK_PRODUCT) == source.count(BLOCK_REDUCE) == 1
        return source
    source = source.replace(ANCHOR_DECL, BLOCK_DECL + ANCHOR_DECL, 1)
    source = source.replace(ANCHOR_INIT, BLOCK_INIT, 1)
    source = source.replace(ANCHOR_PRODUCT, BLOCK_PRODUCT, 1)
    source = source.replace(ANCHOR_REDUCE, BLOCK_REDUCE, 1)
    assert MARKER in source
    return source


def apply(root):
    path = Path(root) / 'ggml/src/ggml-vulkan/vulkan-shaders/mul_mat_vec.comp'
    text = path.read_text()
    # The flag reaches the shader through the generator, so record it in the
    # source as well: the compiled variant must be the one that was measured.
    path.write_text(patch(text))
    return None
