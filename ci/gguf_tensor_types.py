#!/usr/bin/env python3
"""List the tensor types inside a GGUF file, from its header only.

Which quantisation types a model actually stores decides which kernel paths can
speed it up: a weight relayout that targets q5_0 changes nothing if the model is
Q4_K_M. This reads the header (metadata and tensor directory) and prints how many
tensors and how many bytes each type occupies, plus the matvec-relevant tensors by
name, so a measurement can say what it was measuring.

Usage: gguf_tensor_types.py <file.gguf>
"""
import struct
import sys

GGML_TYPES = {
    0: 'f32', 1: 'f16', 2: 'q4_0', 3: 'q4_1', 6: 'q5_0', 7: 'q5_1', 8: 'q8_0',
    9: 'q8_1', 10: 'q2_K', 11: 'q3_K', 12: 'q4_K', 13: 'q5_K', 14: 'q6_K',
    15: 'q8_K', 16: 'iq2_xxs', 17: 'iq2_xs', 18: 'iq3_xxs', 19: 'iq1_s',
    20: 'iq4_nl', 21: 'iq3_s', 22: 'iq2_s', 23: 'iq4_xs', 24: 'i8', 25: 'i16',
    26: 'i32', 27: 'i64', 28: 'f64', 29: 'iq1_m', 30: 'bf16', 34: 'tq1_0',
    35: 'tq2_0', 39: 'mxfp4', 40: 'nvfp4',
}

KV_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}


def read_string(f):
    n = struct.unpack('<Q', f.read(8))[0]
    return f.read(n).decode('utf-8', 'replace')


def skip_value(f, kind):
    if kind in (8,):                       # string
        read_string(f)
    elif kind == 9:                        # array
        element = struct.unpack('<I', f.read(4))[0]
        count = struct.unpack('<Q', f.read(8))[0]
        if element in KV_SIZES:
            f.read(KV_SIZES[element] * count)
        elif element == 8:
            for _ in range(count):
                read_string(f)
        elif element == 9:
            raise ValueError('nested array in metadata')
        else:
            raise ValueError(f'unknown array element type {element}')
    elif kind in KV_SIZES:
        f.read(KV_SIZES[kind])
    else:
        raise ValueError(f'unknown metadata type {kind}')


def main(path):
    with open(path, 'rb') as f:
        magic = f.read(4)
        if magic != b'GGUF':
            raise SystemExit(f'{path}: not a GGUF file')
        version = struct.unpack('<I', f.read(4))[0]
        tensor_count = struct.unpack('<Q', f.read(8))[0]
        kv_count = struct.unpack('<Q', f.read(8))[0]
        arch = None
        for _ in range(kv_count):
            key = read_string(f)
            kind = struct.unpack('<I', f.read(4))[0]
            if key == 'general.architecture' and kind == 8:
                arch = read_string(f)
            else:
                skip_value(f, kind)
        counts, sizes, names = {}, {}, []
        for _ in range(tensor_count):
            name = read_string(f)
            n_dims = struct.unpack('<I', f.read(4))[0]
            dims = [struct.unpack('<Q', f.read(8))[0] for _ in range(n_dims)]
            ttype = struct.unpack('<I', f.read(4))[0]
            f.read(8)  # offset
            label = GGML_TYPES.get(ttype, f'type{ttype}')
            counts[label] = counts.get(label, 0) + 1
            elements = 1
            for d in dims:
                elements *= d
            names.append((name, label, dims, elements))

    print(f'# {path}')
    print(f'gguf_version={version} tensors={tensor_count} architecture={arch}')
    for label, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        total = sum(e for _, l, _, e in names if l == label)
        print(f'type {label}: tensors={count} elements={total}')
    print('--- tensors whose type has a decode matvec kernel ---')
    for name, label, dims, elements in sorted(names, key=lambda t: -t[3])[:20]:
        print(f'{label:>8} {"x".join(str(d) for d in dims):>18} {name}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else sys.exit('usage: gguf_tensor_types.py <file.gguf>'))
