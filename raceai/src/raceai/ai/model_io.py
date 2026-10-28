"""Salvar/carregar modelos: .pt (PyTorch), .npz (numpy) e .onnx (export).

Os metadados guardam a topologia, o nome da pista/carro do treino, a geração
e o fitness — assim o jogo avisa se você carregar um modelo incompatível.
"""
from __future__ import annotations

import json
import sys
import os
import time

import numpy as np

from .policy import PolicySpec, flatten, genome_to_layers, unflatten

FORMAT = "raceai-policy-v1"


class ModelError(RuntimeError):
    pass


def _meta(spec: PolicySpec, extra: dict | None = None) -> dict:
    m = {
        "format": FORMAT,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "spec": spec.to_dict(),
    }
    if extra:
        m.update(extra)
    return m


# ---------------------------------------------------------------------- #
# Salvamento
# ---------------------------------------------------------------------- #
def save_npz(path: str, spec: PolicySpec, genome: list[np.ndarray], meta: dict | None = None):
    arrays = {f"w{i:02d}": np.asarray(w, dtype=np.float32) for i, w in enumerate(genome)}
    arrays["meta_json"] = np.frombuffer(json.dumps(_meta(spec, meta)).encode("utf-8"), dtype=np.uint8)
    np.savez_compressed(path, **arrays)


def save_pt(path: str, spec: PolicySpec, genome: list[np.ndarray], meta: dict | None = None):
    import torch
    layers = genome_to_layers(spec, genome)
    state = {}
    for i, (W, b) in enumerate(layers):
        state[f"{i}.weight"] = torch.from_numpy(np.asarray(W, dtype=np.float32).copy())
        state[f"{i}.bias"] = torch.from_numpy(np.asarray(b, dtype=np.float32).copy())
    torch.save({"state_dict": state, "meta": _meta(spec, meta), "format": FORMAT}, path)


def save_onnx(path: str, spec: PolicySpec, genome: list[np.ndarray], meta: dict | None = None):
    """Exporta para ONNX (requer PyTorch + onnx instalados)."""
    import torch
    import torch.nn as nn

    layers = []
    dims = [spec.obs_dim, *spec.hidden, spec.act_dim]
    for i in range(len(dims) - 1):
        layers.append(nn.Linear(dims[i], dims[i + 1]))
        if i < len(dims) - 2:
            layers.append(nn.Tanh())
    layers.append(nn.Tanh())
    net = nn.Sequential(*layers)
    flat = flatten(genome)
    with torch.no_grad():
        pos = 0
        for m in net.modules():
            if isinstance(m, nn.Linear):
                w_size = m.weight.numel()
                b_size = m.bias.numel()
                m.weight.copy_(torch.from_numpy(flat[pos:pos + w_size]
                                                .reshape(m.weight.shape).astype(np.float32)))
                pos += w_size
                m.bias.copy_(torch.from_numpy(flat[pos:pos + b_size]
                                               .reshape(m.bias.shape).astype(np.float32)))
                pos += b_size
    net.eval()
    dummy = torch.zeros(1, spec.obs_dim, dtype=torch.float32)
    try:
        torch.onnx.export(net, dummy, path, input_names=["obs"], output_names=["action"],
                          opset_version=13, dynamo=False,
                          metadata={"raceai_meta": json.dumps(_meta(spec, meta))})
    except TypeError:
        torch.onnx.export(net, dummy, path, input_names=["obs"], output_names=["action"],
                          opset_version=13)


def save_model(path: str, spec: PolicySpec, genome: list[np.ndarray], meta: dict | None = None):
    """Salva no formato pedido. Sem PyTorch instalado, cai para .npz.

    Retorna o caminho realmente usado (pode mudar a extensão no fallback).
    """
    ext = os.path.splitext(path)[1].lower()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if ext == ".pt":
        try:
            import torch  # noqa: F401
        except Exception:
            alt = os.path.splitext(path)[0] + ".npz"
            print(f"[aviso] PyTorch indisponível: salvando '{os.path.basename(alt)}' "
                  f"em vez de .pt (o jogo carrega os dois formatos)", file=sys.stderr)
            save_npz(alt, spec, genome, meta)
            return alt
        save_pt(path, spec, genome, meta)
    elif ext == ".onnx":
        save_onnx(path, spec, genome, meta)
    else:
        save_npz(path, spec, genome, meta)
    return path


# ---------------------------------------------------------------------- #
# Carregamento
# ---------------------------------------------------------------------- #
def load_npz(path: str) -> tuple[PolicySpec, list[np.ndarray], dict]:
    with np.load(path, allow_pickle=False) as z:
        keys = sorted([k for k in z.files if k.startswith("w")])
        genome = [np.asarray(z[k], dtype=np.float32) for k in keys]
        meta = {}
        if "meta_json" in z.files:
            try:
                meta = json.loads(bytes(z["meta_json"]).decode("utf-8"))
            except Exception:
                meta = {}
    spec = PolicySpec.from_dict(meta.get("spec", {}))
    _check(spec, genome, path)
    return spec, genome, meta


def load_pt(path: str) -> tuple[PolicySpec, list[np.ndarray], dict]:
    try:
        import torch
    except Exception as exc:  # pragma: no cover
        raise ModelError("PyTorch não está instalado — não é possível ler .pt. "
                         "Use um modelo .npz ou instale o PyTorch.") from exc
    try:
        obj = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        obj = torch.load(path, map_location="cpu")

    meta = {}
    if isinstance(obj, dict):
        meta = obj.get("meta", {}) if isinstance(obj.get("meta", {}), dict) else {}
        state = obj.get("state_dict", obj)
    elif hasattr(obj, "state_dict"):
        state = obj.state_dict()
    else:
        raise ModelError("arquivo .pt não reconhecido (esperado dict com state_dict)")

    # aceita tanto Sequential(Linear, Tanh) quanto OrderedDict solto
    pairs = []
    items = [(k, v) for k, v in state.items() if hasattr(torch, "Tensor") and torch.is_tensor(v)]
    weights = [(k, v) for k, v in items if k.endswith(".weight")]
    weights.sort(key=lambda kv: _layer_index(kv[0]))
    for wk, wv in weights:
        bk = wk.replace(".weight", ".bias")
        bv = state.get(bk)
        w = wv.detach().cpu().numpy().astype(np.float32)
        if w.ndim != 2:
            continue                       # ignora norm/batchnorm etc.
        if bv is None:
            b = np.zeros(w.shape[0], dtype=np.float32)
        else:
            b = bv.detach().cpu().numpy().astype(np.float32)
        pairs.append(w)
        pairs.append(b)
    if not pairs:
        raise ModelError("nenhuma camada Linear encontrada no .pt")
    spec = PolicySpec.from_dict(meta.get("spec", {}))
    if "spec" not in meta:
        # infere a topologia a partir dos pesos
        hidden = tuple(int(w.shape[0]) for w in pairs[0::2][:-1])
        spec = PolicySpec(obs_dim=int(pairs[0].shape[1]), hidden=hidden,
                          act_dim=int(pairs[-2].shape[0]))
    _check(spec, pairs, path)
    return spec, pairs, meta


def _layer_index(key: str) -> int:
    digits = "".join(ch for ch in key.split(".")[0] if ch.isdigit())
    return int(digits) if digits else 0


def _check(spec: PolicySpec, genome: list[np.ndarray], path: str):
    expected = spec.shapes
    got = [tuple(g.shape) for g in genome]
    if got != expected:
        raise ModelError(
            f"modelo incompatível: esperado {expected}, encontrado {got} em {os.path.basename(path)}")


def load_model(path: str) -> tuple[PolicySpec, list[np.ndarray], dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pt":
        return load_pt(path)
    if ext == ".npz":
        return load_npz(path)
    raise ModelError(f"formato não suportado: {ext or '(sem extensão)'} (use .pt ou .npz)")


def describe(meta: dict) -> str:
    bits = []
    for key, label in (("track", "pista"), ("car", "carro"), ("generation", "geração"),
                       ("fitness", "fitness"), ("device", "device")):
        if key in meta and meta[key] not in (None, ""):
            value = meta[key]
            if key == "fitness" and isinstance(value, (int, float)):
                value = f"{value:,.0f}"
            bits.append(f"{label}: {value}")
    return ", ".join(bits) if bits else "sem metadados"
