#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 make_gguf.py - Cria e "compila" um modelo GGUF de ~300M de parametros
                com pesos aleatorios, arquitetura PROFUNDA e ESTREITA.
=============================================================================

 - Arquitetura estilo LLaMA (RMSNorm + SwiGLU + RoPE + GQA opcional).
 - Profunda e estreita: muitas camadas, hidden size pequeno.
     padrao: n_layer = 80, n_embd = 512, n_head = 8, n_kv_head = 4
 - Escritor GGUF v3 implementado do zero (nao depende do pacote `gguf`).
 - Streaming: os tensores sao gerados e gravados um a um, entao o pico de
   RAM e o tamanho do maior tensor, nao o do modelo inteiro.
 - Suporta F32, F16 e BF16.
 - Inclui um tokenizer minimo (vocabulario sintetico) para que o arquivo
   seja carregavel por llama.cpp sem erro de metadados faltando.

 Uso:
     python make_gguf.py --out modelo-300m.gguf --verify
     python make_gguf.py --out m.gguf --dtype f32 --auto-depth
     python make_gguf.py --n-layer 96 --n-embd 448 --dry-run

 Requer apenas: Python 3.8+ e numpy.
=============================================================================
"""

from __future__ import annotations

import argparse
import math
import os
import struct
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit("ERRO: este script precisa de numpy.  Instale com: pip install numpy")


# =============================================================================
# 1. CONSTANTES DO FORMATO GGUF
# =============================================================================

GGUF_MAGIC = b"GGUF"
GGUF_VERSION = 3
GGUF_DEFAULT_ALIGNMENT = 32


class GGUFValueType:
    """Codigos de tipo para valores de metadados (secao key-value)."""
    UINT8 = 0
    INT8 = 1
    UINT16 = 2
    INT16 = 3
    UINT32 = 4
    INT32 = 5
    FLOAT32 = 6
    BOOL = 7
    STRING = 8
    ARRAY = 9
    UINT64 = 10
    INT64 = 11
    FLOAT64 = 12


class GGMLType:
    """Codigos de tipo para os dados dos tensores."""
    F32 = 0
    F16 = 1
    Q4_0 = 2
    Q4_1 = 3
    Q5_0 = 6
    Q5_1 = 7
    Q8_0 = 8
    Q8_1 = 9
    I8 = 24
    I16 = 25
    I32 = 26
    I64 = 27
    F64 = 28
    BF16 = 30


# nome amigavel -> (codigo ggml, bytes por elemento)
DTYPE_TABLE: Dict[str, Tuple[int, int]] = {
    "f32": (GGMLType.F32, 4),
    "f16": (GGMLType.F16, 2),
    "bf16": (GGMLType.BF16, 2),
}

ITEM_SIZE: Dict[int, int] = {GGMLType.F32: 4, GGMLType.F16: 2, GGMLType.BF16: 2}


# =============================================================================
# 2. ESCRITOR GGUF (implementado do zero)
# =============================================================================

@dataclass
class TensorInfo:
    """Metadados de um tensor, na ordem em que serao escritos no cabecalho."""
    name: str
    shape_ne: Tuple[int, ...]   # ordem GGUF: ne[0] e a dimensao mais rapida
    ggml_type: int
    nbytes: int
    offset: int = 0


class GGUFWriter:
    """
    Escritor de arquivos GGUF em dois passes:

      pass 1 (planejamento)  -> add_kv(...) e plan_tensor(...)
      pass 2 (gravacao)      -> write_header() e depois write_tensor_data(...)

    Escrever em dois passes e o que permite o modo streaming: precisamos
    conhecer todos os offsets antes de gravar qualquer byte de dados, mas
    nunca precisamos manter os dados na memoria.
    """

    def __init__(self, path: str, alignment: int = GGUF_DEFAULT_ALIGNMENT) -> None:
        self.path = path
        self.alignment = alignment
        self.kv: List[Tuple[str, int, Any]] = []
        self.tensors: List[TensorInfo] = []
        self._fp = None
        self._data_start = 0

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _pack_string(s: str) -> bytes:
        raw = s.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    def _pack_value(self, vtype: int, value: Any) -> bytes:
        if vtype == GGUFValueType.UINT8:   return struct.pack("<B", value)
        if vtype == GGUFValueType.INT8:    return struct.pack("<b", value)
        if vtype == GGUFValueType.UINT16:  return struct.pack("<H", value)
        if vtype == GGUFValueType.INT16:   return struct.pack("<h", value)
        if vtype == GGUFValueType.UINT32:  return struct.pack("<I", value)
        if vtype == GGUFValueType.INT32:   return struct.pack("<i", value)
        if vtype == GGUFValueType.UINT64:  return struct.pack("<Q", value)
        if vtype == GGUFValueType.INT64:   return struct.pack("<q", value)
        if vtype == GGUFValueType.FLOAT32: return struct.pack("<f", value)
        if vtype == GGUFValueType.FLOAT64: return struct.pack("<d", value)
        if vtype == GGUFValueType.BOOL:    return struct.pack("<?", bool(value))
        if vtype == GGUFValueType.STRING:  return self._pack_string(value)
        if vtype == GGUFValueType.ARRAY:
            elem_type, items = value
            out = [struct.pack("<I", elem_type), struct.pack("<Q", len(items))]
            # caminho rapido para arrays numericos grandes (vocabulario)
            if elem_type == GGUFValueType.FLOAT32:
                out.append(np.asarray(items, dtype="<f4").tobytes())
            elif elem_type == GGUFValueType.INT32:
                out.append(np.asarray(items, dtype="<i4").tobytes())
            elif elem_type == GGUFValueType.UINT32:
                out.append(np.asarray(items, dtype="<u4").tobytes())
            else:
                for it in items:
                    out.append(self._pack_value(elem_type, it))
            return b"".join(out)
        raise ValueError(f"tipo de valor GGUF desconhecido: {vtype}")

    def _align_up(self, n: int) -> int:
        rem = n % self.alignment
        return n if rem == 0 else n + (self.alignment - rem)

    # ------------------------------------------------------- pass 1: metadados
    def add_kv(self, key: str, vtype: int, value: Any) -> None:
        self.kv.append((key, vtype, value))

    def add_uint32(self, key: str, v: int) -> None:    self.add_kv(key, GGUFValueType.UINT32, v)
    def add_int32(self, key: str, v: int) -> None:     self.add_kv(key, GGUFValueType.INT32, v)
    def add_float32(self, key: str, v: float) -> None: self.add_kv(key, GGUFValueType.FLOAT32, v)
    def add_bool(self, key: str, v: bool) -> None:     self.add_kv(key, GGUFValueType.BOOL, v)
    def add_string(self, key: str, v: str) -> None:    self.add_kv(key, GGUFValueType.STRING, v)

    def add_array(self, key: str, elem_type: int, items: Sequence[Any]) -> None:
        self.add_kv(key, GGUFValueType.ARRAY, (elem_type, list(items)))

    # --------------------------------------------------- pass 1: plano tensores
    def plan_tensor(self, name: str, shape_ne: Sequence[int], ggml_type: int) -> TensorInfo:
        """Registra um tensor. `shape_ne` ja deve estar na ordem do GGUF."""
        n_elem = 1
        for d in shape_ne:
            n_elem *= int(d)
        info = TensorInfo(name=name,
                          shape_ne=tuple(int(d) for d in shape_ne),
                          ggml_type=ggml_type,
                          nbytes=n_elem * ITEM_SIZE[ggml_type])
        self.tensors.append(info)
        return info

    def _compute_offsets(self) -> int:
        """Atribui offsets relativos ao inicio do bloco de dados."""
        off = 0
        for t in self.tensors:
            t.offset = off
            off = self._align_up(off + t.nbytes)
        return off

    # ------------------------------------------------------ pass 2: cabecalho
    def write_header(self) -> None:
        self._compute_offsets()

        head = bytearray()
        head += GGUF_MAGIC
        head += struct.pack("<I", GGUF_VERSION)
        head += struct.pack("<Q", len(self.tensors))
        head += struct.pack("<Q", len(self.kv))

        for key, vtype, value in self.kv:
            head += self._pack_string(key)
            head += struct.pack("<I", vtype)
            head += self._pack_value(vtype, value)

        for t in self.tensors:
            head += self._pack_string(t.name)
            head += struct.pack("<I", len(t.shape_ne))
            for d in t.shape_ne:
                head += struct.pack("<Q", d)
            head += struct.pack("<I", t.ggml_type)
            head += struct.pack("<Q", t.offset)

        # padding ate o alinhamento -> inicio do bloco de dados
        head += b"\x00" * (self._align_up(len(head)) - len(head))

        self._fp = open(self.path, "wb", buffering=1024 * 1024)
        self._fp.write(bytes(head))
        self._data_start = len(head)

    # --------------------------------------------------------- pass 2: dados
    def write_tensor_data(self, info: TensorInfo, array: np.ndarray) -> None:
        """Grava os bytes de um tensor, respeitando o offset planejado."""
        if self._fp is None:
            raise RuntimeError("write_header() precisa ser chamado antes")

        target = self._data_start + info.offset
        here = self._fp.tell()
        if here < target:
            self._fp.write(b"\x00" * (target - here))
        elif here > target:
            raise RuntimeError(f"offset inconsistente em '{info.name}'")

        raw = array.tobytes()
        if len(raw) != info.nbytes:
            raise RuntimeError(
                f"'{info.name}': esperado {info.nbytes} bytes, obtido {len(raw)}")
        self._fp.write(raw)

    def close(self) -> None:
        if self._fp is None:
            return
        cur = self._fp.tell() - self._data_start
        total = self._align_up(cur)
        if cur < total:
            self._fp.write(b"\x00" * (total - cur))
        self._fp.close()
        self._fp = None


# =============================================================================
# 3. CONFIGURACAO DA ARQUITETURA
# =============================================================================

@dataclass
class ModelConfig:
    """Hiperparametros de um transformer decoder estilo LLaMA."""
    name: str = "deep-narrow-300m"
    n_layer: int = 85          # PROFUNDO
    n_embd: int = 512          # ESTREITO
    n_head: int = 8
    n_kv_head: int = 4         # GQA (grouped-query attention)
    n_ff: int = 1536           # SwiGLU
    n_vocab: int = 32000
    n_ctx: int = 4096
    rope_theta: float = 10000.0
    norm_eps: float = 1e-5
    tie_embeddings: bool = False

    @property
    def head_dim(self) -> int:
        return self.n_embd // self.n_head

    @property
    def kv_dim(self) -> int:
        return self.head_dim * self.n_kv_head

    # ------------------------------------------------------------ contagem
    def params_per_layer(self) -> int:
        e, f = self.n_embd, self.n_ff
        attn = (e * e                # wq
                + e * self.kv_dim    # wk
                + e * self.kv_dim    # wv
                + e * e)             # wo
        ffn = 3 * e * f              # gate, up, down
        norms = 2 * e                # attn_norm + ffn_norm
        return attn + ffn + norms

    def params_total(self) -> int:
        emb = self.n_vocab * self.n_embd
        out = 0 if self.tie_embeddings else self.n_vocab * self.n_embd
        return emb + out + self.n_embd + self.n_layer * self.params_per_layer()

    def validate(self) -> None:
        if self.n_embd % self.n_head:
            raise ValueError("n_embd deve ser divisivel por n_head")
        if self.n_head % self.n_kv_head:
            raise ValueError("n_head deve ser divisivel por n_kv_head")
        if self.n_layer < 1 or self.n_embd < 8:
            raise ValueError("configuracao degenerada")

    def describe(self) -> str:
        p = self.params_total()
        per = self.n_layer * self.params_per_layer()
        emb = p - per
        return (
            f"  arquitetura      : llama (RMSNorm + SwiGLU + RoPE + GQA)\n"
            f"  camadas          : {self.n_layer}   <- profundo\n"
            f"  hidden size      : {self.n_embd}   <- estreito\n"
            f"  razao prof/larg  : {self.n_layer / self.n_embd:.4f} camadas por unidade de largura\n"
            f"  cabecas (q / kv) : {self.n_head} / {self.n_kv_head}  (head_dim={self.head_dim})\n"
            f"  feed-forward     : {self.n_ff}  ({self.n_ff / self.n_embd:.2f}x)\n"
            f"  vocabulario      : {self.n_vocab}\n"
            f"  contexto         : {self.n_ctx}\n"
            f"  embeddings atados: {'sim' if self.tie_embeddings else 'nao'}\n"
            f"  params/camada    : {self.params_per_layer():,}\n"
            f"  params blocos    : {per:,}\n"
            f"  params embeddings: {emb:,}\n"
            f"  PARAMETROS TOTAIS: {p:,}  ({p / 1e6:.2f}M)\n"
        )


def solve_depth_for_target(cfg: ModelConfig, target: float) -> ModelConfig:
    """
    Ajusta n_layer (mantendo a estreiteza) para chegar o mais perto possivel
    do numero de parametros desejado, e depois faz um ajuste fino em n_ff
    (arredondado para multiplo de 64).
    """
    base = cfg.n_vocab * cfg.n_embd * (1 if cfg.tie_embeddings else 2) + cfg.n_embd
    per = cfg.params_per_layer()
    cfg.n_layer = max(1, round((target - base) / per))

    best_delta = abs(cfg.params_total() - target)
    best_ff = cfg.n_ff
    for ff in range(max(64, cfg.n_ff - 1024), cfg.n_ff + 1025, 64):
        trial = ModelConfig(**{**cfg.__dict__, "n_ff": ff})
        d = abs(trial.params_total() - target)
        if d < best_delta:
            best_delta, best_ff = d, ff
    cfg.n_ff = best_ff
    return cfg


# =============================================================================
# 4. GERACAO DOS PESOS ALEATORIOS
# =============================================================================

def to_bf16(x: np.ndarray) -> np.ndarray:
    """Converte float32 -> bfloat16 (round-to-nearest-even), como uint16."""
    x = np.ascontiguousarray(x, dtype=np.float32)
    bits = x.view(np.uint32)
    rounding = ((bits >> 16) & np.uint32(1)) + np.uint32(0x7FFF)
    return ((bits + rounding) >> 16).astype(np.uint16)


def cast_for_gguf(x: np.ndarray, ggml_type: int) -> np.ndarray:
    if ggml_type == GGMLType.F32:
        return np.ascontiguousarray(x, dtype="<f4")
    if ggml_type == GGMLType.F16:
        return np.ascontiguousarray(x, dtype="<f2")
    if ggml_type == GGMLType.BF16:
        return np.ascontiguousarray(to_bf16(x), dtype="<u2")
    raise ValueError(f"tipo nao suportado: {ggml_type}")


class WeightFactory:
    """
    Produz pesos aleatorios com inicializacao sensata por tipo de tensor.
    Redes profundas e estreitas sao instaveis com init ingenua, entao as
    projecoes que escrevem no residual recebem escala 1/sqrt(2*n_layer)
    (mesma ideia do GPT-2 / DeepNet).
    """

    def __init__(self, cfg: ModelConfig, seed: int) -> None:
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)

    def normal(self, shape: Tuple[int, ...], std: float) -> np.ndarray:
        return self.rng.standard_normal(size=shape, dtype=np.float32) * np.float32(std)

    def linear_in(self, out_f: int, in_f: int) -> np.ndarray:
        return self.normal((out_f, in_f), math.sqrt(2.0 / (5.0 * in_f)))

    def linear_residual(self, out_f: int, in_f: int) -> np.ndarray:
        std = math.sqrt(2.0 / (5.0 * in_f)) / math.sqrt(2.0 * self.cfg.n_layer)
        return self.normal((out_f, in_f), std)


# =============================================================================
# 5. MONTAGEM DO ARQUIVO
# =============================================================================

def build_general_metadata(w: GGUFWriter, cfg: ModelConfig, dtype_name: str) -> None:
    ftype = {"f32": 0, "f16": 1, "bf16": 32}[dtype_name]

    w.add_string("general.architecture", "llama")
    w.add_uint32("general.quantization_version", 2)
    w.add_uint32("general.alignment", GGUF_DEFAULT_ALIGNMENT)
    w.add_string("general.name", cfg.name)
    w.add_string("general.basename", cfg.name)
    w.add_string("general.size_label", f"{cfg.params_total() / 1e6:.0f}M")
    w.add_string("general.license", "mit")
    w.add_string("general.description",
                 "Modelo profundo e estreito com pesos aleatorios, gerado sinteticamente.")
    w.add_uint32("general.file_type", ftype)

    w.add_uint32("llama.block_count", cfg.n_layer)
    w.add_uint32("llama.context_length", cfg.n_ctx)
    w.add_uint32("llama.embedding_length", cfg.n_embd)
    w.add_uint32("llama.feed_forward_length", cfg.n_ff)
    w.add_uint32("llama.attention.head_count", cfg.n_head)
    w.add_uint32("llama.attention.head_count_kv", cfg.n_kv_head)
    w.add_uint32("llama.attention.key_length", cfg.head_dim)
    w.add_uint32("llama.attention.value_length", cfg.head_dim)
    w.add_float32("llama.attention.layer_norm_rms_epsilon", cfg.norm_eps)
    w.add_uint32("llama.rope.dimension_count", cfg.head_dim)
    w.add_float32("llama.rope.freq_base", cfg.rope_theta)
    w.add_uint32("llama.vocab_size", cfg.n_vocab)


def build_tokenizer_metadata(w: GGUFWriter, cfg: ModelConfig) -> None:
    """
    Vocabulario sintetico minimo. Nao serve para gerar texto util (os pesos
    sao aleatorios de qualquer forma), mas satisfaz os carregadores que
    exigem os campos de tokenizer.
    """
    tokens: List[str] = ["<unk>", "<s>", "</s>", "<pad>"]
    scores: List[float] = [0.0, 0.0, 0.0, 0.0]
    toktypes: List[int] = [2, 3, 3, 3]  # 2=UNKNOWN, 3=CONTROL

    # 256 bytes crus, no estilo dos tokenizers SentencePiece
    for b in range(256):
        tokens.append(f"<0x{b:02X}>")
        scores.append(0.0)
        toktypes.append(6)  # BYTE

    i = 0
    while len(tokens) < cfg.n_vocab:
        tokens.append("\u2581tk%d" % i)   # U+2581 = marcador de espaco do SPM
        scores.append(-float(i))
        toktypes.append(1)               # NORMAL
        i += 1

    w.add_string("tokenizer.ggml.model", "llama")
    w.add_string("tokenizer.ggml.pre", "default")
    w.add_array("tokenizer.ggml.tokens", GGUFValueType.STRING, tokens)
    w.add_array("tokenizer.ggml.scores", GGUFValueType.FLOAT32, scores)
    w.add_array("tokenizer.ggml.token_type", GGUFValueType.INT32, toktypes)
    w.add_uint32("tokenizer.ggml.unknown_token_id", 0)
    w.add_uint32("tokenizer.ggml.bos_token_id", 1)
    w.add_uint32("tokenizer.ggml.eos_token_id", 2)
    w.add_uint32("tokenizer.ggml.padding_token_id", 3)
    w.add_bool("tokenizer.ggml.add_bos_token", True)
    w.add_bool("tokenizer.ggml.add_eos_token", False)


def plan_all_tensors(w: GGUFWriter, cfg: ModelConfig, ggml_type: int
                     ) -> List[Tuple[TensorInfo, str, Tuple[int, ...]]]:
    """
    Registra todos os tensores no cabecalho e devolve a receita para gerar
    cada um depois: (info, papel, shape logico em row-major).

    IMPORTANTE: no GGUF as dimensoes vao invertidas em relacao ao PyTorch.
    Um peso (out_features, in_features) e declarado como ne = [in, out].
    """
    plan: List[Tuple[TensorInfo, str, Tuple[int, ...]]] = []
    norm_type = GGMLType.F32  # normas sempre em F32, como faz o llama.cpp

    def add(name: str, role: str, shape_rowmajor: Tuple[int, ...], t: int) -> None:
        ne = tuple(reversed(shape_rowmajor))
        plan.append((w.plan_tensor(name, ne, t), role, shape_rowmajor))

    add("token_embd.weight", "embedding", (cfg.n_vocab, cfg.n_embd), ggml_type)

    for i in range(cfg.n_layer):
        p = "blk.%d." % i
        add(p + "attn_norm.weight",   "norm", (cfg.n_embd,),            norm_type)
        add(p + "attn_q.weight",      "in",   (cfg.n_embd, cfg.n_embd), ggml_type)
        add(p + "attn_k.weight",      "in",   (cfg.kv_dim, cfg.n_embd), ggml_type)
        add(p + "attn_v.weight",      "in",   (cfg.kv_dim, cfg.n_embd), ggml_type)
        add(p + "attn_output.weight", "res",  (cfg.n_embd, cfg.n_embd), ggml_type)
        add(p + "ffn_norm.weight",    "norm", (cfg.n_embd,),            norm_type)
        add(p + "ffn_gate.weight",    "in",   (cfg.n_ff, cfg.n_embd),   ggml_type)
        add(p + "ffn_up.weight",      "in",   (cfg.n_ff, cfg.n_embd),   ggml_type)
        add(p + "ffn_down.weight",    "res",  (cfg.n_embd, cfg.n_ff),   ggml_type)

    add("output_norm.weight", "norm", (cfg.n_embd,), norm_type)
    if not cfg.tie_embeddings:
        add("output.weight", "embedding", (cfg.n_vocab, cfg.n_embd), ggml_type)

    return plan


def generate_tensor(fac: WeightFactory, role: str, shape: Tuple[int, ...]) -> np.ndarray:
    if role == "norm":
        return np.ones(shape, dtype=np.float32)
    if role == "embedding":
        return fac.normal(shape, 0.02)
    if role == "in":
        return fac.linear_in(shape[0], shape[1])
    if role == "res":
        return fac.linear_residual(shape[0], shape[1])
    raise ValueError(role)


def human(nbytes: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if nbytes < 1024 or unit == "TiB":
            return f"{nbytes:.2f} {unit}"
        nbytes /= 1024.0
    return ""


# =============================================================================
# 6. VERIFICACAO (parser independente do escritor)
# =============================================================================

def verify_gguf(path: str, expect_tensors: int, expect_params: int,
                cfg: ModelConfig) -> bool:
    print("\n[verificacao] relendo o arquivo com um parser independente...")
    with open(path, "rb") as f:
        blob = f.read(1 << 24)  # o cabecalho cabe folgado nos primeiros 16 MiB

    if blob[:4] != GGUF_MAGIC:
        print("  FALHOU: magic invalido")
        return False
    ver, n_tensors, n_kv = struct.unpack_from("<IQQ", blob, 4)
    pos = 24

    fixed = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}

    def rd_str(p: int) -> Tuple[str, int]:
        (ln,) = struct.unpack_from("<Q", blob, p)
        return blob[p + 8:p + 8 + ln].decode("utf-8", "replace"), p + 8 + ln

    def skip_val(p: int, vt: int) -> int:
        if vt in fixed:
            return p + fixed[vt]
        if vt == GGUFValueType.STRING:
            (ln,) = struct.unpack_from("<Q", blob, p)
            return p + 8 + ln
        if vt == GGUFValueType.ARRAY:
            et, n = struct.unpack_from("<IQ", blob, p)
            p += 12
            if et in fixed:
                return p + fixed[et] * n
            for _ in range(n):
                p = skip_val(p, et)
            return p
        raise ValueError(vt)

    meta: Dict[str, Any] = {}
    n_vocab_read = None
    for _ in range(n_kv):
        key, pos = rd_str(pos)
        (vt,) = struct.unpack_from("<I", blob, pos)
        pos += 4
        if vt == GGUFValueType.UINT32:
            meta[key] = struct.unpack_from("<I", blob, pos)[0]
        elif vt == GGUFValueType.FLOAT32:
            meta[key] = struct.unpack_from("<f", blob, pos)[0]
        elif vt == GGUFValueType.ARRAY and key == "tokenizer.ggml.tokens":
            n_vocab_read = struct.unpack_from("<IQ", blob, pos)[1]
        pos = skip_val(pos, vt)

    total_params = 0
    names: List[str] = []
    last_end = 0
    for _ in range(n_tensors):
        name, pos = rd_str(pos)
        (ndim,) = struct.unpack_from("<I", blob, pos)
        pos += 4
        dims = struct.unpack_from("<" + "Q" * ndim, blob, pos)
        pos += 8 * ndim
        ttype, toff = struct.unpack_from("<IQ", blob, pos)
        pos += 12
        n = 1
        for d in dims:
            n *= d
        total_params += n
        last_end = max(last_end, toff + n * ITEM_SIZE[ttype])
        names.append(name)

    data_start = (pos + GGUF_DEFAULT_ALIGNMENT - 1) // GGUF_DEFAULT_ALIGNMENT * GGUF_DEFAULT_ALIGNMENT
    size_on_disk = os.path.getsize(path)

    ok = True
    print(f"  versao GGUF        : {ver}")
    print(f"  pares de metadados : {n_kv}")
    print(f"  tensores           : {n_tensors} (esperado {expect_tensors})")
    print(f"  parametros somados : {total_params:,} (esperado {expect_params:,})")
    print(f"  block_count        : {meta.get('llama.block_count')}")
    print(f"  embedding_length   : {meta.get('llama.embedding_length')}")
    print(f"  head_count / kv    : {meta.get('llama.attention.head_count')} / "
          f"{meta.get('llama.attention.head_count_kv')}")
    print(f"  tokens no vocab    : {n_vocab_read}")
    print(f"  inicio dos dados   : {data_start}")
    print(f"  tamanho em disco   : {human(size_on_disk)}")
    print(f"  primeiros tensores : {', '.join(names[:3])} ...")
    print(f"  ultimos tensores   : ... {', '.join(names[-2:])}")

    if ver != GGUF_VERSION:
        print("  FALHOU: versao"); ok = False
    if n_tensors != expect_tensors:
        print("  FALHOU: contagem de tensores"); ok = False
    if total_params != expect_params:
        print("  FALHOU: contagem de parametros"); ok = False
    if n_vocab_read != cfg.n_vocab:
        print("  FALHOU: tamanho do vocabulario"); ok = False
    if size_on_disk < data_start + last_end:
        print("  FALHOU: arquivo truncado"); ok = False
    print("  RESULTADO: " + ("OK" if ok else "ERRO"))
    return ok


# =============================================================================
# 7. MAIN
# =============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Cria um GGUF de ~300M de parametros, profundo e estreito, "
                    "com pesos aleatorios.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--out", default="deep-narrow-300m.gguf", help="arquivo de saida")
    ap.add_argument("--dtype", choices=list(DTYPE_TABLE), default="f16",
                    help="precisao dos pesos")
    ap.add_argument("--target-params", type=float, default=300e6,
                    help="alvo de parametros (usado com --auto-depth)")
    ap.add_argument("--auto-depth", action="store_true",
                    help="ajusta n_layer/n_ff automaticamente para bater no alvo")
    ap.add_argument("--n-layer", type=int, default=85)
    ap.add_argument("--n-embd", type=int, default=512)
    ap.add_argument("--n-head", type=int, default=8)
    ap.add_argument("--n-kv-head", type=int, default=4)
    ap.add_argument("--n-ff", type=int, default=1536)
    ap.add_argument("--n-vocab", type=int, default=32000)
    ap.add_argument("--n-ctx", type=int, default=4096)
    ap.add_argument("--tie-embeddings", action="store_true",
                    help="compartilha token_embd com a projecao de saida")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--name", default="deep-narrow-300m")
    ap.add_argument("--verify", action="store_true", help="rele e valida o arquivo")
    ap.add_argument("--dry-run", action="store_true",
                    help="so mostra a arquitetura, nao escreve nada")
    args = ap.parse_args()

    cfg = ModelConfig(name=args.name, n_layer=args.n_layer, n_embd=args.n_embd,
                      n_head=args.n_head, n_kv_head=args.n_kv_head, n_ff=args.n_ff,
                      n_vocab=args.n_vocab, n_ctx=args.n_ctx,
                      tie_embeddings=args.tie_embeddings)
    cfg.validate()
    if args.auto_depth:
        cfg = solve_depth_for_target(cfg, args.target_params)
        cfg.validate()

    ggml_type, item_size = DTYPE_TABLE[args.dtype]

    print("=" * 72)
    print(" GERADOR DE GGUF - modelo profundo e estreito com pesos aleatorios")
    print("=" * 72)
    print(cfg.describe())
    print(f"  precisao         : {args.dtype}  ({item_size} bytes/peso)")
    print(f"  tamanho estimado : {human(cfg.params_total() * item_size)}")
    print(f"  saida            : {args.out}")
    print("=" * 72)

    if args.dry_run:
        print("\n[dry-run] nada foi escrito.")
        return 0

    t0 = time.time()
    w = GGUFWriter(args.out)
    build_general_metadata(w, cfg, args.dtype)
    build_tokenizer_metadata(w, cfg)
    plan = plan_all_tensors(w, cfg, ggml_type)

    print(f"\n[1/2] planejando {len(plan)} tensores e escrevendo o cabecalho...")
    w.write_header()
    print(f"      cabecalho: {human(w._data_start)}  "
          f"(bloco de dados comeca no byte {w._data_start})")

    print(f"[2/2] gerando e gravando os pesos ({args.dtype}) em streaming...")
    fac = WeightFactory(cfg, args.seed)
    written = 0
    for idx, (info, role, shape) in enumerate(plan):
        arr = generate_tensor(fac, role, shape)
        w.write_tensor_data(info, cast_for_gguf(arr, info.ggml_type))
        written += info.nbytes
        del arr
        if idx % 100 == 0 or idx == len(plan) - 1:
            pct = 100.0 * (idx + 1) / len(plan)
            sys.stdout.write(f"\r      {idx + 1}/{len(plan)} tensores "
                             f"({pct:5.1f}%)  {human(written)} gravados")
            sys.stdout.flush()
    w.close()
    print()

    dt = time.time() - t0
    size = os.path.getsize(args.out)
    print(f"\nConcluido em {dt:.1f}s")
    print(f"  arquivo    : {args.out}")
    print(f"  tamanho    : {human(size)} ({size:,} bytes)")
    print(f"  parametros : {cfg.params_total():,}")
    print(f"  taxa       : {human(size / max(dt, 1e-9))}/s")

    if args.verify and not verify_gguf(args.out, len(plan), cfg.params_total(), cfg):
        return 1

    print("\nTeste com llama.cpp:")
    print(f"  llama-cli -m {args.out} -p \"ola\" -n 16")
    print("  (a saida sera ruido: os pesos sao aleatorios, o modelo nao foi treinado)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
