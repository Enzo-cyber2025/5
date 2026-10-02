"""Finetune the committed policy on real recordings (DAgger corrections).

Why this exists: the base policy is trained purely on the synthetic expert
(you drive 0 km). To adapt it to the *real* ETS2, the practice mode
(ets2ai.practice / bridge --ets2) captures state->command pairs while EITHER
(a) you drive normally for a few minutes (record; calibration + mapa) or
(b) the AI drives and you only intervene when it errs (drive; DAgger:
minutes of corrections >> thousands of km of raw driving).

Recording format (written by bridge/ets2_bridge.py --record):
    line 1: ets2ai-rec,v1
    then:   13 normalized features,steer,throttle,brake,override,source
            (override=1 marks a HUMAN correction — weighted higher here)

Quality gates (the finetuned model is only usable if ALL pass):
    - MSE on held-out recording rows <= LOSS_TARGET (0.150)
    - closed-loop finish rate on unseen roads >= 75%, in-lane > 95%

Usage:
    python -m ets2ai.finetune --recordings sessao1.csv sessao2.csv \
        --epochs 150 --out artifacts-finetuned

Never overwrites the committed weights; the report tells you if the
finetuned model is good enough to promote (copy over artifacts/).
"""
import argparse
import json
from pathlib import Path
import numpy as np

from .contract import (load_weights, save_weights, model_meta, LOSS_TARGET,
                       N_IN, N_OUT)
from .model import train, forward, mse
from .train import closed_loop_eval

REC_HEADER = "ets2ai-rec,v1"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "artifacts-finetuned"
BASE_WEIGHTS = Path(__file__).resolve().parent.parent / "artifacts" / "model-weights.json"


def load_recordings(paths, override_weight=3):
    """Parse recordings into (x, y). Human-correction rows are repeated."""
    rows = []
    for p in paths:
        lines = Path(p).read_text(encoding="utf-8").strip().splitlines()
        if not lines or not lines[0].startswith(REC_HEADER):
            raise SystemExit(f"{p}: nao parece uma gravacao ets2ai-rec,v1")
        for ln in lines[1:]:
            parts = ln.split(",")
            if len(parts) < 15:
                continue
            feat = [float(v) for v in parts[:N_IN]]
            cmd = [float(v) for v in parts[N_IN:N_IN + N_OUT]]
            override = int(float(parts[N_IN + N_OUT])) if len(parts) > N_IN + N_OUT else 0
            reps = override_weight if override >= 1 else 1
            for _ in range(reps):
                rows.append(feat + cmd)
    if len(rows) < 200:
        raise SystemExit(f"gravacoes insuficientes ({len(rows)} linhas; "
                         "grave ao menos ~30 s de jogo)")
    data = np.array(rows, dtype=np.float32)
    return np.clip(data[:, :N_IN], -2.0, 2.0), np.clip(data[:, N_IN:N_IN + N_OUT], -1.0, 1.0)


def run(recording_paths, epochs=150, lr=5e-4, out=DEFAULT_OUT,
        override_weight=3, base_weights=BASE_WEIGHTS, seed=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    x, y = load_recordings(recording_paths, override_weight)
    # time-blocked split: last 15% of rows are validation
    n_val = max(200, int(0.15 * len(x)))
    x_tr, y_tr = x[:-n_val], y[:-n_val]
    x_va, y_va = x[-n_val:], y[-n_val:]
    print(f"[finetune] {len(x_tr)} linhas treino | {len(x_va)} validacao "
          f"| {len(recording_paths)} gravacoes")

    layers, meta = load_weights(base_weights)
    print(f"[finetune] base: val_loss {meta['final_loss']:.5f} "
          f"({meta['samples']} amostras sinteticas)")

    base_before = mse(forward(x_va, layers), y_va)

    # deterministic continuation: same seed policy as base training
    layers, _ = train(x_tr, y_tr, epochs=epochs, lr=lr, verbose=False,
                      x_val=x_va, y_val=y_va, start_layers=layers)

    loss_after = mse(forward(x_va, layers), y_va)
    print(f"[finetune] MSE na gravacao: antes {base_before:.5f} -> "
          f"depois {loss_after:.5f}")

    print("[finetune] circuito fechado (o modelo nao pode piorar de vez):")
    agg_base, _ = closed_loop_eval(load_weights(base_weights)[0], n_roads=3)
    agg_ft, rows_ft = closed_loop_eval(layers, n_roads=3)
    print(f"            base:      {agg_base['finish_rate']*100:.0f}% rotas, "
          f"{agg_base['in_lane_pct']*100:.0f}% faixa")
    print(f"            finetuned: {agg_ft['finish_rate']*100:.0f}% rotas, "
          f"{agg_ft['in_lane_pct']*100:.0f}% faixa")

    gates = {
        "mse_val_recording": loss_after,
        "mse_gate": bool(loss_after <= LOSS_TARGET),
        "finish_rate": agg_ft["finish_rate"],
        "in_lane_pct": agg_ft["in_lane_pct"],
        "closed_loop_gate": bool(agg_ft["finish_rate"] >= 0.75 and agg_ft["in_lane_pct"] > 0.95),
    }
    gates["all_pass"] = gates["mse_gate"] and gates["closed_loop_gate"]

    save_weights(out / "model-weights-finetuned.json", layers,
                 model_meta(epochs=epochs, samples=int(len(x)), loss=loss_after))
    (out / "metrics-finetune.json").write_text(json.dumps({
        "gates": gates,
        "base": {"mse_on_recording": base_before,
                 "closed_loop": agg_base},
        "finetuned": {"mse_on_recording": loss_after,
                      "closed_loop": agg_ft,
                      "closed_loop_rows": rows_ft},
        "recordings": [str(p) for p in recording_paths],
        "epochs": epochs, "lr": lr, "override_weight": override_weight,
    }, indent=2), encoding="utf-8")

    print(f"[finetune] -> {out/'model-weights-finetuned.json'}")
    print("[finetune] GATES: " + ("TODOS OK — pode promover para artifacts/"
          if gates["all_pass"] else "FALHOU — NAO use estes pesos"))
    return gates


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--recordings", nargs="+", required=True)
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--override-weight", type=int, default=3)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    ok = run(args.recordings, epochs=args.epochs, lr=args.lr, out=args.out,
             override_weight=args.override_weight)
    return 0 if ok["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
