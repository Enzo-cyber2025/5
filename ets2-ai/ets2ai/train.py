"""Train the ETS2-AI driving policy and export weights + metrics.

Usage:  python -m ets2ai.train [--epochs N] [--out DIR]

Reports MSE (the project target is <= 0.150) and closed-loop driving quality
on held-out roads. Deterministic: same seed -> same weights everywhere.
"""
import argparse
import json
from pathlib import Path
import numpy as np

from . import sim
from .contract import (N_IN, N_OUT, HIDDEN, SEED, LOSS_TARGET, FEATURES,
                       ACTIONS, model_meta, save_weights)
from .data import generate, N_VAL_ROADS, ROAD_SEED
from .model import train, forward, mse
from .sim import Road, run_episode


def policy_from_layers(layers):
    def policy(road, truck, job_left_km, rng=None):
        f = np.array(sim.features(road, truck, job_left_km), dtype=np.float32)
        out = forward(f, layers)[0]
        return float(out[0]), float(out[1]), float(out[2])
    return policy


def closed_loop_eval(layers, n_roads=N_VAL_ROADS, seed=777):
    policy = policy_from_layers(layers)
    rows = []
    for k in range(n_roads):
        road = Road.random(ROAD_SEED + 100 + k)   # roads never seen in training
        rows.append(run_episode(road, policy, seed=seed + k))
    n_pass = sum(r["radar_passes"] for r in rows)
    agg = {
        "roads": n_roads,
        "finish_rate": sum(r["finished"] for r in rows) / n_roads,
        "in_lane_pct": sum(r["in_lane_pct"] for r in rows) / n_roads,
        "avg_speed_kmh": sum(r["avg_speed"] for r in rows) / n_roads * 3.6,
        "km_total": sum(r["km"] for r in rows),
        "radar_compliance": (sum(r["radar_passes"] * r["radar_compliance"] for r in rows)
                             / max(1, n_pass)),
        "radar_passes": n_pass,
        "max_lat_accel": max(r["max_lat_accel"] for r in rows),
        "gps_mean_abs_offset_m": sum(r["mean_abs_offset"] for r in rows) / n_roads,
        "top_speed_kmh": max(r["avg_speed"] for r in rows) * 3.6,
    }
    return agg, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=350)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "artifacts"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("[1/4] gerando dados do especialista (estradas aleatorias)...")
    x_train, y_train, x_val, y_val = generate()
    print(f"      treino {x_train.shape}  val {x_val.shape}")

    print("[2/4] treinando MLP 12-24-24-3 (tanh, Adam)...")
    layers, hist = train(x_train, y_train, epochs=args.epochs,
                         x_val=x_val, y_val=y_val)

    loss_tr = mse(forward(x_train, layers), y_train)
    loss_va = mse(forward(x_val, layers), y_val)
    mae_va = float(np.mean(np.abs(forward(x_val, layers) - y_val)))
    print(f"      MSE treino {loss_tr:.5f} | MSE validacao {loss_va:.5f} "
          f"(meta <= {LOSS_TARGET}) | MAE val {mae_va:.5f}")

    print("[3/4] avaliacao em circuito fechado (estradas ineditas)...")
    agg, rows = closed_loop_eval(layers)
    print(f"      conclusao {agg['finish_rate']*100:.0f}%  "
          f"na faixa {agg['in_lane_pct']*100:.0f}%  "
          f"vel media {agg['avg_speed_kmh']:.0f} km/h")

    print("[4/4] exportando pesos...")
    meta = model_meta(epochs=args.epochs, samples=int(len(x_train) + len(x_val)),
                      loss=loss_va)
    save_weights(out / "model-weights.json", layers, meta)
    (out / "metrics.json").write_text(json.dumps({
        "meta": meta,
        "mse_train": loss_tr,
        "mse_val": loss_va,
        "mae_val": mae_va,
        "loss_target": LOSS_TARGET,
        "target_met": bool(loss_va <= LOSS_TARGET),
        "closed_loop": agg,
        "closed_loop_rows": rows,
    }, indent=2), encoding="utf-8")
    print(f"      -> {out/'model-weights.json'}")
    print(f"      -> {out/'metrics.json'}")
    ok = loss_va <= LOSS_TARGET
    print("META ATINGIDA" if ok else "meta NAO atingida (ver --epochs)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
