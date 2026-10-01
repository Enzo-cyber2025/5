#!/usr/bin/env python3
"""Push the training kernel to Kaggle, wait, download and validate output.

Runs INSIDE GitHub Actions with the repo checked out. Credentials come from
the repository secrets KAGGLE_USERNAME / KAGGLE_KEY (never from chat, never
committed). If the secrets are not configured the script exits with code 2
and the workflow shows a warning and stays green (local training in
train-verify remains the source of truth).

Flow:
  1. build kernel.py (same code/seed as repo) -> .cache/kaggle-kernel/
  2. kaggle kernels push
  3. poll kaggle kernels status until COMPLETE/ERROR (default timeout 900 s)
  4. kaggle kernels output -> .cache/kaggle-out/
  5. quality gates on the Kaggle-trained weights (same as local CI)
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

SLUG_SUFFIX = "ets2ai-train"


def sh(*args, **kw):
    print("$", " ".join(str(a) for a in args), flush=True)
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--epochs", type=int, default=320)
    ap.add_argument("--gpu", action="store_true",
                    help="executar o kernel com GPU do Kaggle (nota: o modelo "
                         "treina em ~2 min de CPU; GPU gasta cota a toa)")
    args = ap.parse_args()

    user = os.environ.get("KAGGLE_USERNAME", "").strip()
    key = os.environ.get("KAGGLE_KEY", "").strip()
    if not key:
        print("::warning::Secret KAGGLE_KEY nao configurado.")
        print("Para treinar no Kaggle: repo Settings > Secrets and variables > Actions >")
        print("  KAGGLE_KEY = seu token (kaggle.com > Settings > API > Create)")
        print("O token NUNCA deve ser colado em chat/commit — apenas em secrets.")
        return 2
    if not user:
        # tokens novos (KGAT_...) podem autenticar sozinhos; CLI antigo exige
        # usuario — tentamos e registramos o resultado para diagnostico.
        print("[kaggle] KAGGLE_USERNAME ausente: tentando autenticacao somente-token")
        os.environ["KAGGLE_USERNAME"] = "kaggle"   # placeholder; CLI novo ignora

    kdir = ROOT / ".cache" / "kaggle-kernel"
    kdir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(HERE))
    import build_kernel
    (kdir / "kernel.py").write_text(build_kernel.build(), encoding="utf-8")
    slug = f"{user}/{SLUG_SUFFIX}"
    (kdir / "kernel-metadata.json").write_text(json.dumps({
        "id": slug,
        "title": "ets2ai-train",
        "code_file": "kernel.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "true" if args.gpu else "false",
        "enable_internet": "false",
    }), encoding="utf-8")

    r = sh("kaggle", "kernels", "push", "-p", kdir)
    print(r.stdout or r.stderr)
    if r.returncode != 0:
        # descobre o username real da conta do token (kernels list --mine)
        r2 = sh("kaggle", "kernels", "list", "--mine", "--page-size", "5")
        out2 = (r2.stdout or "") + (r2.stderr or "")
        print("[kaggle] kernels list --mine:", out2.strip()[:400])
        print(f"::warning::kaggle kernels push falhou: {r.stderr.strip()[:300]}")
        return 1

    print(f"[kaggle] kernel empurrado: {slug}")
    print(f"[kaggle] notebook ativo: https://www.kaggle.com/code/{slug}")
    print("[kaggle] aguardando execucao (GPU T4 x2, FP64)...")
    deadline = time.time() + args.timeout
    status = "unknown"
    while time.time() < deadline:
        time.sleep(30)
        r = sh("kaggle", "kernels", "status", slug)
        out = (r.stdout + r.stderr).lower()
        if "complete" in out and "notcomplete" not in out and "running" not in out:
            status = "complete"
            break
        if "error" in out or "cancel" in out:
            status = "error"
            break
        if (int(deadline - time.time()) % 300) < 30:
            print(f"[kaggle] status: {out.strip()[:120]}")
    if status != "complete":
        print(f"::warning::kernel nao concluiu a tempo (status: {status})")
        return 1

    outdir = ROOT / ".cache" / "kaggle-out"
    outdir.mkdir(parents=True, exist_ok=True)
    r = sh("kaggle", "kernels", "output", slug, "-p", outdir)
    print(r.stdout or r.stderr)
    weights = outdir / "model-weights.json"
    if r.returncode != 0 or not weights.exists():
        print("::warning::saida do kernel nao encontrada")
        return 1

    # ---- quality gates on the KAGGLE-trained weights (same as local CI) ----
    import numpy as np
    from ets2ai.contract import load_weights, LOSS_TARGET
    from ets2ai.train import closed_loop_eval
    layers, meta = load_weights(weights)
    loss = meta["final_loss"]
    agg, _ = closed_loop_eval(layers, n_roads=3)
    print(f"[kaggle] pesos validados: loss {loss:.5f} | "
          f"{agg['finish_rate']*100:.0f}% rotas | {agg['in_lane_pct']*100:.0f}% faixa | "
          f"radares {agg['radar_compliance']*100:.0f}%")
    ok = (loss <= LOSS_TARGET and agg["finish_rate"] >= 2 / 3
          and agg["in_lane_pct"] > 0.95 and agg["dock_rate"] >= 2 / 3)
    print("[kaggle] GATES: " + ("OK — treino no Kaggle reproduz a qualidade" if ok
                                else "FALHOU — mantendo pesos do treino local"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
