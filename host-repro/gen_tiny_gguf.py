#!/usr/bin/env python3
"""Gera um modelo LLaMA mínimo (GGUF) válido para testes de carga/inferência.

Dependências: gguf (do repo llama.cpp: `pip install gguf` OU sys.path para
`llama.cpp/gguf-py`), numpy.

Pontos importantes que já deram problema antes:
  * gguf-py grava as dimensões do tensor em ordem REVERSA. Para obter
    ne=[embd, vocab], passe shape=(vocab, embd).
  * O tokenizer SentencePiece ("tokenizer.ggml.model"="llama") cai no fallback
    de bytes e procura tokens "<0xXX>" — TODO modelo real inclui os 256.
"""
import sys
import numpy as np
from gguf import GGUFWriter

rng = np.random.default_rng(42)
embd, blocks, ff, heads = 32, 2, 64, 4
rope_dim = embd // heads
base = ["<unk>", "<s>", "</s>"]
byte_tokens = [f"<0x{ch:02X}>" for ch in range(256)]
words = ["world", "Hello", "!"]
tokens = base + byte_tokens + words
n = len(tokens)
token_type = [2, 3, 3] + [6] * 256 + [1] * len(words)  # unk=2 control=3 byte=6 normal=1

w = GGUFWriter("/tmp/tiny-llama.gguf", "llama")
w.add_architecture()
w.add_uint32("general.file_type", 1)   # ALL_F32
w.add_string("general.name", "tiny-test")
w.add_uint32("llama.context_length", 128)
w.add_uint32("llama.embedding_length", embd)
w.add_uint32("llama.block_count", blocks)
w.add_uint32("llama.feed_forward_length", ff)
w.add_uint32("llama.attention.head_count", heads)
w.add_uint32("llama.attention.head_count_kv", heads)
w.add_float32("llama.attention.layer_norm_rms_epsilon", 1e-5)
w.add_uint32("llama.rope.dimension_count", rope_dim)
w.add_uint32("llama.vocab_size", n)
w.add_string("tokenizer.ggml.model", "llama")
w.add_array("tokenizer.ggml.tokens", tokens)
w.add_array("tokenizer.ggml.scores", [0.0] * n)
w.add_array("tokenizer.ggml.token_type", token_type)
w.add_uint32("tokenizer.ggml.bos_token_id", 1)
w.add_uint32("tokenizer.ggml.eos_token_id", 2)
w.add_uint32("tokenizer.ggml.unknown_token_id", 0)

def f(*shape):
    return (rng.standard_normal(shape) * 0.02).astype(np.float32)

w.add_tensor("token_embd.weight", f(n, embd))       # ne=[embd, vocab]
w.add_tensor("output_norm.weight", f(embd))
w.add_tensor("output.weight", f(n, embd))           # ne=[embd, vocab]
for i in range(blocks):
    w.add_tensor(f"blk.{i}.attn_norm.weight", f(embd))
    w.add_tensor(f"blk.{i}.attn_q.weight", f(embd, embd))
    w.add_tensor(f"blk.{i}.attn_k.weight", f(embd, embd))
    w.add_tensor(f"blk.{i}.attn_v.weight", f(embd, embd))
    w.add_tensor(f"blk.{i}.attn_output.weight", f(embd, embd))
    w.add_tensor(f"blk.{i}.ffn_norm.weight", f(embd))
    w.add_tensor(f"blk.{i}.ffn_gate.weight", f(ff, embd))   # ne=[embd, ff]
    w.add_tensor(f"blk.{i}.ffn_down.weight", f(embd, ff))   # ne=[ff, embd]
    w.add_tensor(f"blk.{i}.ffn_up.weight", f(ff, embd))     # ne=[embd, ff]
w.write_header_to_file()
w.write_kv_data_to_file()
w.write_tensors_to_file()
w.close()
print(f"modelo escrito: /tmp/tiny-llama.gguf (vocab={n})")
