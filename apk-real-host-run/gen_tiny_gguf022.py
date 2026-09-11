#!/usr/bin/env python3
"""Gera um modelo LLaMA mínimo (GGUF) válido para o motor 0.22.0 do APK.

Usa o gguf-py do checkout /tmp/llama022 (master ≈ ggml 0.22.0), o MESMO
formato que o libllama.so real do APK espera. numpy necessário.

Regra de forma (já validada): gguf-py grava as dimensões do tensor em ordem
REVERSA. Para obter ggml ne=[embd, vocab], passa-se shape=(vocab, embd).
"""
import sys
import numpy as np

sys.path.insert(0, "/tmp/llama022/gguf-py")
from gguf import GGUFWriter  # noqa: E402

rng = np.random.default_rng(42)

embd, blocks, ff, heads = 32, 1, 64, 4
n_kv = heads                      # MHA
rope_dim = embd // heads          # 8
kv_gqa = rope_dim * n_kv          # head_dim * n_head_kv = 8*4 = 32

base = ["<unk>", "<s>", "</s>"]
byte_tokens = [f"<0x{ch:02X}>" for ch in range(256)]
words = ["world", "Hello", "!", "a", "b", "test", "the", "sky"]
tokens = base + byte_tokens + words
n = len(tokens)
# unk=2, control=3, byte=6, normal=1
token_type = [2, 3, 3] + [6] * 256 + [1] * len(words)

OUT = "/tmp/tiny-llama-022.gguf"
w = GGUFWriter(OUT, "llama")
w.add_file_type(1)                  # ALL_F32
w.add_name("tiny-test")
w.add_context_length(64)
w.add_embedding_length(embd)
w.add_block_count(blocks)
w.add_feed_forward_length(ff)
w.add_head_count(heads)
w.add_head_count_kv(n_kv)
w.add_layer_norm_rms_eps(1e-5)
w.add_uint32("llama.rope.dimension_count", rope_dim)
w.add_vocab_size(n)

# tokenizer (SentencePiece fallback -> tokens "<0xXX>")
w.add_string("tokenizer.ggml.model", "llama")
w.add_array("tokenizer.ggml.tokens", tokens)
w.add_array("tokenizer.ggml.scores", [0.0] * n)
w.add_array("tokenizer.ggml.token_type", token_type)
w.add_uint32("tokenizer.ggml.bos_token_id", 1)
w.add_uint32("tokenizer.ggml.eos_token_id", 2)
w.add_uint32("tokenizer.ggml.unknown_token_id", 0)
w.add_bool("tokenizer.ggml.add_bos_token", True)
w.add_bool("tokenizer.ggml.add_eos_token", False)

def f(*shape, scale=0.02):
    return (rng.standard_normal(shape) * scale).astype(np.float32)

# ---- tensores (shape numpy -> ggml ne reverso) ----
w.add_tensor("token_embd.weight", f(n, embd))
w.add_tensor("output_norm.weight", f(embd))
w.add_tensor("output.weight", f(n, embd))
for i in range(blocks):
    bid = f"blk.{i}"
    w.add_tensor(f"{bid}.attn_norm.weight", f(embd))
    w.add_tensor(f"{bid}.attn_q.weight", f(embd, embd))
    w.add_tensor(f"{bid}.attn_k.weight", f(kv_gqa, embd))
    w.add_tensor(f"{bid}.attn_v.weight", f(kv_gqa, embd))
    w.add_tensor(f"{bid}.attn_output.weight", f(embd, embd))
    w.add_tensor(f"{bid}.ffn_norm.weight", f(embd))
    w.add_tensor(f"{bid}.ffn_gate.weight", f(ff, embd))
    w.add_tensor(f"{bid}.ffn_down.weight", f(embd, ff))
    w.add_tensor(f"{bid}.ffn_up.weight", f(ff, embd))

w.write_header_to_file()
w.write_kv_data_to_file()
w.write_tensors_to_file()
w.close()
print(f"OK: {OUT} ({n} tokens)")
