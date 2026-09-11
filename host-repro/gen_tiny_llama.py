#!/usr/bin/env python3
"""Gera um GGUF mínimo e VÁLIDO (arquitetura llama, F32) para testar o motor."""
import struct, numpy as np, sys

# ---- dims ----
n_vocab = 259   # <unk>, <s>, </s> + 256 bytes
n_embd  = 32
n_head  = 4
n_head_kv = 4
n_layer = 1
n_ctx   = 64
n_ff    = 64
rope_dim = n_embd // n_head  # 8

# ---- tokenizer ----
tokens = ["<unk>", "<s>", "</s>"] + [f"<0x{i:02X}>" for i in range(256)]
assert len(tokens) == n_vocab
scores = np.full(n_vocab, 0.0, dtype=np.float32)
token_type = np.zeros(n_vocab, dtype=np.int32)
token_type[0] = 1   # unknown
token_type[1] = 3   # control
token_type[2] = 3   # control

# ---- GGUF value type ids ----
U8, I8, U16, I16, U32, I32, F32, BOOL, STR, ARR, U64, I64, F64 = 0,1,2,3,4,5,6,7,8,9,10,11,12
F32_T = 0  # GGML_TYPE_F32

def wstr(s):
    b = s.encode()
    return struct.pack('<Q', len(b)) + b

def kv(out, key, vtype, val):
    out.write(wstr(key))
    out.write(struct.pack('<I', vtype))
    if vtype == U32:
        out.write(struct.pack('<I', val))
    elif vtype == F32:
        out.write(struct.pack('<f', val))
    elif vtype == BOOL:
        out.write(struct.pack('<?', val))
    elif vtype == STR:
        out.write(wstr(val))
    elif vtype == ARR:
        # val = (elem_type, list)
        et, items = val
        out.write(struct.pack('<I', et))
        out.write(struct.pack('<Q', len(items)))
        for it in items:
            if et == STR:
                out.write(wstr(it))
            elif et == F32:
                out.write(struct.pack('<f', it))
            elif et == I32:
                out.write(struct.pack('<i', it))
    else:
        raise ValueError(vtype)

def tensor(out, name, arr):
    # GGUF guarda ne0 primeiro = dimensão mais interna => shape reverso
    dims = list(arr.shape)[::-1]
    assert arr.dtype == np.float32
    out.write(wstr(name))
    out.write(struct.pack('<I', len(dims)))
    for d in dims:
        out.write(struct.pack('<Q', d))
    out.write(struct.pack('<I', F32_T))
    out.write(struct.pack('<Q', 0))  # offset placeholder (preenchido depois)

def w(name, shape):
    # pesos pequenos, determinísticos, não-constantes para exercitar o grafo
    return (np.random.default_rng(hash(name) & 0xffffffff)
            .standard_normal(shape).astype(np.float32) * 0.1)

tensors = []
tensors.append(("token_embd.weight",        w("tok",  (n_vocab, n_embd))))
tensors.append(("blk.0.attn_norm.weight",   w("an",   (n_embd,))))
tensors.append(("blk.0.attn_q.weight",      w("aq",   (n_embd, n_embd))))
tensors.append(("blk.0.attn_k.weight",      w("ak",   (n_embd, n_embd))))
tensors.append(("blk.0.attn_v.weight",      w("av",   (n_embd, n_embd))))
tensors.append(("blk.0.attn_output.weight", w("ao",   (n_embd, n_embd))))
tensors.append(("blk.0.ffn_norm.weight",    w("fn",   (n_embd,))))
tensors.append(("blk.0.ffn_gate.weight",    w("fg",   (n_ff, n_embd))))
tensors.append(("blk.0.ffn_down.weight",    w("fd",   (n_embd, n_ff))))
tensors.append(("blk.0.ffn_up.weight",      w("fu",   (n_ff, n_embd))))
tensors.append(("output_norm.weight",       w("on",   (n_embd,))))
tensors.append(("output.weight",            w("out",  (n_vocab, n_embd))))

import io
out = io.BytesIO()
out.write(b"GGUF")
out.write(struct.pack('<I', 3))
out.write(struct.pack('<Q', len(tensors)))
out.write(struct.pack('<Q', 0))  # kv count placeholder

kv_count = 0
def K(key, vtype, val):
    global kv_count
    kv(out, key, vtype, val); kv_count += 1

K("general.architecture", STR, "llama")
K("general.name", STR, "tiny-llama")
K("general.file_type", U32, 0)
K("llama.context_length", U32, n_ctx)
K("llama.embedding_length", U32, n_embd)
K("llama.block_count", U32, n_layer)
K("llama.feed_forward_length", U32, n_ff)
K("llama.attention.head_count", U32, n_head)
K("llama.attention.head_count_kv", U32, n_head_kv)
K("llama.attention.layer_norm_rms_epsilon", F32, 1e-5)
K("llama.rope.dimension_count", U32, rope_dim)
K("llama.rope.freq_base", F32, 10000.0)
K("llama.vocab_size", U32, n_vocab)
K("tokenizer.ggml.model", STR, "llama")
K("tokenizer.ggml.tokens", ARR, (STR, tokens))
K("tokenizer.ggml.scores", ARR, (F32, scores.tolist()))
K("tokenizer.ggml.token_type", ARR, (I32, token_type.tolist()))
K("tokenizer.ggml.bos_token_id", U32, 1)
K("tokenizer.ggml.eos_token_id", U32, 2)
K("tokenizer.ggml.unknown_token_id", U32, 0)
K("tokenizer.ggml.add_bos_token", BOOL, True)
K("tokenizer.ggml.add_eos_token", BOOL, False)

# patch kv count (volta ao offset 12)
buf = out.getvalue()
buf = buf[:12] + struct.pack('<Q', kv_count) + buf[20:]
out = io.BytesIO(buf); out.seek(0, io.SEEK_END)

# tensor infos
for name, arr in tensors:
    tensor(out, name, arr)

# alinhamento 32
pos = out.tell()
pad = (32 - (pos % 32)) % 32
out.write(b"\0" * pad)
data_start = out.tell()

# dados
offsets = []
for name, arr in tensors:
    offsets.append(out.tell())
    out.write(arr.tobytes())

raw = bytearray(out.getvalue())
# preencher offsets dos tensores no header (busca reversa dos placeholders)
# reescrever: pegar a posição dos offsets via segunda passada
# (mais simples: recompor do zero)
def rebuild():
    b = io.BytesIO()
    b.write(b"GGUF")
    b.write(struct.pack('<I', 3))
    b.write(struct.pack('<Q', len(tensors)))
    b.write(struct.pack('<Q', kv_count))
    for key, vtype, val in kvs:
        kv(b, key, vtype, val)
    for name, arr in tensors:
        dims = list(arr.shape)[::-1]
        b.write(wstr(name))
        b.write(struct.pack('<I', len(dims)))
        for d in dims:
            b.write(struct.pack('<Q', d))
        b.write(struct.pack('<I', F32_T))
        b.write(struct.pack('<Q', 0))
    pos = b.tell()
    pad = (32 - (pos % 32)) % 32
    b.write(b"\0" * pad)
    data_start = b.tell()
    # agora sabemos data_start; recalcular offsets
    offs = []
    cur = 0  # offsets RELATIVOS ao início da seção de dados
    for name, arr in tensors:
        offs.append(cur)
        cur += arr.nbytes
    # voltar e reescrever os offsets
    b2 = io.BytesIO()
    b2.write(b"GGUF")
    b2.write(struct.pack('<I', 3))
    b2.write(struct.pack('<Q', len(tensors)))
    b2.write(struct.pack('<Q', kv_count))
    for key, vtype, val in kvs:
        kv(b2, key, vtype, val)
    for (name, arr), off in zip(tensors, offs):
        dims = list(arr.shape)[::-1]
        b2.write(wstr(name))
        b2.write(struct.pack('<I', len(dims)))
        for d in dims:
            b2.write(struct.pack('<Q', d))
        b2.write(struct.pack('<I', F32_T))
        b2.write(struct.pack('<Q', off))
    pos = b2.tell()
    pad = (32 - (pos % 32)) % 32
    b2.write(b"\0" * pad)
    for name, arr in tensors:
        b2.write(arr.tobytes())
    return b2.getvalue()

kvs = []
def K2(key, vtype, val):
    kvs.append((key, vtype, val))
K2("general.architecture", STR, "llama")
K2("general.name", STR, "tiny-llama")
K2("general.file_type", U32, 0)
K2("llama.context_length", U32, n_ctx)
K2("llama.embedding_length", U32, n_embd)
K2("llama.block_count", U32, n_layer)
K2("llama.feed_forward_length", U32, n_ff)
K2("llama.attention.head_count", U32, n_head)
K2("llama.attention.head_count_kv", U32, n_head_kv)
K2("llama.attention.layer_norm_rms_epsilon", F32, 1e-5)
K2("llama.rope.dimension_count", U32, rope_dim)
K2("llama.rope.freq_base", F32, 10000.0)
K2("llama.vocab_size", U32, n_vocab)
K2("tokenizer.ggml.model", STR, "llama")
K2("tokenizer.ggml.tokens", ARR, (STR, tokens))
K2("tokenizer.ggml.scores", ARR, (F32, scores.tolist()))
K2("tokenizer.ggml.token_type", ARR, (I32, token_type.tolist()))
K2("tokenizer.ggml.bos_token_id", U32, 1)
K2("tokenizer.ggml.eos_token_id", U32, 2)
K2("tokenizer.ggml.unknown_token_id", U32, 0)
K2("tokenizer.ggml.add_bos_token", BOOL, True)
K2("tokenizer.ggml.add_eos_token", BOOL, False)

data = rebuild()
open("/tmp/tiny-llama.gguf", "wb").write(data)
print("escrito /tmp/tiny-llama.gguf", len(data), "bytes")
print("tensores:", [(n, list(a.shape)) for n, a in tensors])
