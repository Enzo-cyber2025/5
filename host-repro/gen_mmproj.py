#!/usr/bin/env python3
"""Gera um mmproj LLaVA (PROJECTOR_TYPE_MLP) mínimo e válido."""
import struct, numpy as np

n_embd = 32          # hidden do encoder de visão
proj_dim = 32        # hidden do LLM (tem que casar com tiny-llama n_embd=32)
n_head = 4
n_ff = 64
n_layer = 1
img = 28
patch = 7
n_patch = (img // patch) ** 2          # 16
n_pos = n_patch + 1                     # 17 (class token + patches)

U32, F32, BOOL, STR, ARR = 4, 6, 7, 8, 9
F32_T = 0

def wstr(s):
    b = s.encode(); return struct.pack('<Q', len(b)) + b

def w(name, shape):
    return (np.random.default_rng(hash(name) & 0xffffffff)
            .standard_normal(shape).astype(np.float32) * 0.1)

# (nome, array)
tensors = [
    ("v.position_embd.weight", w("pos",  (n_pos, n_embd))),
    ("v.patch_embd.weight",    w("patch",(n_embd, 3, patch, patch))),  # out,in,h,w
    ("v.blk.0.attn_q.weight",  w("q",    (n_embd, n_embd))),
    ("v.blk.0.attn_k.weight",  w("k",    (n_embd, n_embd))),
    ("v.blk.0.attn_v.weight",  w("v",    (n_embd, n_embd))),
    ("v.blk.0.attn_out.weight",w("o",    (n_embd, n_embd))),
    ("v.blk.0.ln1.weight",     w("ln1w", (n_embd,))),
    ("v.blk.0.ln1.bias",       w("ln1b", (n_embd,))),
    ("v.blk.0.ln2.weight",     w("ln2w", (n_embd,))),
    ("v.blk.0.ln2.bias",       w("ln2b", (n_embd,))),
    ("v.blk.0.ffn_up.weight",  w("up",   (n_ff, n_embd))),
    ("v.blk.0.ffn_down.weight",w("down", (n_embd, n_ff))),
    ("v.post_ln.weight",       w("pln",  (n_embd,))),
    ("v.post_ln.bias",         w("plnb", (n_embd,))),
    ("mm.0.weight",            w("mm0w", (proj_dim, n_embd))),
    ("mm.0.bias",              w("mm0b", (proj_dim,))),
    ("mm.2.weight",            w("mm2w", (proj_dim, proj_dim))),
    ("mm.2.bias",              w("mm2b", (proj_dim,))),
]

kvs = [
    ("clip.has_vision_encoder", BOOL, True),
    ("clip.projector_type", STR, "mlp"),
    ("clip.vision.image_size", U32, img),
    ("clip.vision.patch_size", U32, patch),
    ("clip.vision.embedding_length", U32, n_embd),
    ("clip.vision.projection_dim", U32, proj_dim),
    ("clip.vision.block_count", U32, n_layer),
    ("clip.vision.feed_forward_length", U32, n_ff),
    ("clip.vision.attention.head_count", U32, n_head),
    ("clip.vision.attention.layer_norm_epsilon", F32, 1e-5),
    ("clip.vision.image_mean", ARR, (F32, [0.48145466, 0.4578275, 0.40821073])),
    ("clip.vision.image_std",  ARR, (F32, [0.26862954, 0.26130258, 0.27577711])),
    ("general.architecture", STR, "clip"),
    ("general.file_type", U32, 0),
]

def kv(out, key, vtype, val):
    out.write(wstr(key)); out.write(struct.pack('<I', vtype))
    if vtype == U32: out.write(struct.pack('<I', val))
    elif vtype == F32: out.write(struct.pack('<f', val))
    elif vtype == BOOL: out.write(struct.pack('<?', val))
    elif vtype == STR: out.write(wstr(val))
    elif vtype == ARR:
        et, items = val
        out.write(struct.pack('<I', et)); out.write(struct.pack('<Q', len(items)))
        for it in items:
            if et == F32: out.write(struct.pack('<f', it))
            else: raise ValueError(et)
    else: raise ValueError(vtype)

def build():
    b = io.BytesIO()
    b.write(b"GGUF"); b.write(struct.pack('<I', 3))
    b.write(struct.pack('<Q', len(tensors))); b.write(struct.pack('<Q', len(kvs)))
    for k, t, v in kvs: kv(b, k, t, v)
    for name, arr in tensors:
        dims = list(arr.shape)[::-1]
        b.write(wstr(name)); b.write(struct.pack('<I', len(dims)))
        for d in dims: b.write(struct.pack('<Q', d))
        b.write(struct.pack('<I', F32_T)); b.write(struct.pack('<Q', 0))
    pos = b.tell(); pad = (32 - pos % 32) % 32; b.write(b"\0" * pad)
    data_start = b.tell()
    offs = []; cur = 0
    for name, arr in tensors:
        offs.append(cur); cur += arr.nbytes
    b2 = io.BytesIO()
    b2.write(b"GGUF"); b2.write(struct.pack('<I', 3))
    b2.write(struct.pack('<Q', len(tensors))); b2.write(struct.pack('<Q', len(kvs)))
    for k, t, v in kvs: kv(b2, k, t, v)
    for (name, arr), off in zip(tensors, offs):
        dims = list(arr.shape)[::-1]
        b2.write(wstr(name)); b2.write(struct.pack('<I', len(dims)))
        for d in dims: b2.write(struct.pack('<Q', d))
        b2.write(struct.pack('<I', F32_T)); b2.write(struct.pack('<Q', off))
    pos = b2.tell(); pad = (32 - pos % 32) % 32; b2.write(b"\0" * pad)
    for name, arr in tensors: b2.write(arr.tobytes())
    return b2.getvalue()

import io
data = build()
open("/tmp/tiny-mmproj.gguf", "wb").write(data)
print("escrito /tmp/tiny-mmproj.gguf", len(data), "bytes")
for n, a in tensors:
    print(" ", n, list(a.shape))
