"""Exporta o modelo treinado para PyTorch (.pt, TorchScript auto-contido).

O arquivo sai carregavel com `torch.jit.load()` SEM precisar do codigo deste
repo — os pesos e a topologia ficam embutidos. A arquitetura e identica a do
numpy/Java/TFLite (MLP 13 -> hidden -> 3, tanh nas ocultas, saida linear),
entao a paridade numerica e verificada contra `ets2ai.model.forward` antes
de gravar.

Uso:
    python -m ets2ai.export_pt --weights artifacts/model-weights.json \
        --out artifacts/ets2ai-v0.4.3.pt
"""
import argparse
import json
from pathlib import Path
from typing import List

import numpy as np

from .contract import N_IN, N_OUT, HIDDEN


def load_torch():
    """Importa torch com mensagem de erro clara se estiver ausente."""
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - ambiente sem torch
        raise SystemExit(
            "PyTorch nao esta instalado. Instale com:\n"
            "  pip install torch\n"
            "(a exportacao .pt e opcional; o restante do projeto usa numpy)"
        ) from exc
    return torch


def build_module(torch, meta, layers_data):
    """Monta nn.Module com os pesos do JSON (w e (fan_in, fan_out), como numpy)."""
    from torch import nn

    hidden = list(meta.get("hidden", HIDDEN))

    class Ets2AI(nn.Module):
        def __init__(self):
            super().__init__()
            sizes = [N_IN] + hidden + [N_OUT]
            mods = []
            for i in range(len(sizes) - 1):
                mods.append(nn.Linear(sizes[i], sizes[i + 1]))
                if i < len(sizes) - 2:
                    mods.append(nn.Tanh())
            self.net = nn.Sequential(*mods)
            # metadados legiveis depois do torch.jit.load()
            self.version = "0.4.0"
            self.loss = float(meta.get("final_loss", 0.0))
            self.n_params = int(sum(p.numel() for p in self.net.parameters()))
            self.features: List[str] = list(meta.get("features", []))
            self.actions: List[str] = list(meta.get("actions", []))

        def forward(self, x):
            return self.net(x)

    model = Ets2AI()
    with torch.no_grad():
        for lin, ld in zip([m for m in model.net if hasattr(m, "weight")], layers_data):
            w = np.asarray(ld["w"], dtype=np.float32)      # (fan_in, fan_out)
            b = np.asarray(ld["b"], dtype=np.float32)
            lin.weight.copy_(torch.from_numpy(w.T.copy()))  # torch: (out, in)
            lin.bias.copy_(torch.from_numpy(b))
    return model


def export(weights_path, out_path, n_check=2048, seed=7):
    torch = load_torch()
    from . import model as numpy_model

    data = json.loads(Path(weights_path).read_text())
    meta, layers_data = data["meta"], data["layers"]

    model = build_module(torch, meta, layers_data)
    model.eval()

    # --- paridade com numpy: mesmos numeros, outra biblioteca ---
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((n_check, N_IN)).astype(np.float32) * 3.0
    ref = numpy_model.forward(x, [(np.asarray(l["w"], np.float32),
                                   np.asarray(l["b"], np.float32))
                                  for l in layers_data])
    with torch.no_grad():
        got = model(torch.from_numpy(x)).numpy()
    max_diff = float(np.abs(ref - got).max())
    if max_diff > 1e-5:
        raise SystemExit(f"FALHA paridade numpy x torch: max diff {max_diff:.3e}")

    scripted = torch.jit.script(model)
    scripted.save(str(out_path))

    # --- confere o arquivo salvo carregando de volta ---
    reloaded = torch.jit.load(str(out_path))
    reloaded.eval()
    with torch.no_grad():
        got2 = reloaded(torch.from_numpy(x[:64])).numpy()
    max_diff2 = float(np.abs(ref[:64] - got2).max())
    if max_diff2 > 1e-5:
        raise SystemExit(f"FALHA paridade do .pt recarregado: {max_diff2:.3e}")

    kb = Path(out_path).stat().st_size / 1024
    print(f"OK {out_path} ({kb:.0f} KB)")
    print(f"   params={reloaded.n_params} hidden={list(meta.get('hidden', HIDDEN))}")
    print(f"   loss={reloaded.loss:.6f} (meta {meta.get('loss_target')})")
    print(f"   features={reloaded.features}")
    print(f"   actions={reloaded.actions}")
    print(f"   paridade numpy x torch: max diff {max_diff:.2e} ({n_check} amostras)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weights", default="artifacts/model-weights.json")
    ap.add_argument("--out", default="artifacts/ets2ai-v0.4.3.pt")
    args = ap.parse_args()
    raise SystemExit(export(args.weights, args.out))


if __name__ == "__main__":
    main()
