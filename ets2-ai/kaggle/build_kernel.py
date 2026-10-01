#!/usr/bin/env python3
"""Assembles a self-contained Kaggle kernel script from the ets2ai package.

The kernel trains the exact same policy (same seed) and writes
model-weights.json + metrics.json to the kernel output directory, so GitHub
Actions can download it via `kaggle kernels output` and run the same quality
gates as the local training job.
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "ets2ai"
MODULES = ["contract.py", "sim.py", "model.py", "data.py", "train.py"]

FOOTER = """

# ---------------------------------------------------------------------------
# Kaggle runner footer (appended by build_kernel.py — do not edit here)
# ---------------------------------------------------------------------------
import json as _json
import os as _os

_OUT = _os.environ.get("KAGGLE_WORKING_DIR", ".")
_DTYPE = np.float32 if _os.environ.get("ETS2AI_F32") == "1" else np.float64
_EPOCHS = int(_os.environ.get("ETS2AI_EPOCHS", "60"))
_n_params = (N_IN * HIDDEN[0] + HIDDEN[0]
             + sum(HIDDEN[i] * HIDDEN[i + 1] + HIDDEN[i + 1] for i in range(len(HIDDEN) - 1))
             + HIDDEN[-1] * N_OUT + N_OUT)
print("[kaggle] gerando dados do especialista (estradas aleatorias)...")
_xtr, _ytr, _xva, _yva = generate()
_xtr = np.asarray(_xtr, dtype=_DTYPE); _ytr = np.asarray(_ytr, dtype=_DTYPE)
_xva = np.asarray(_xva, dtype=_DTYPE); _yva = np.asarray(_yva, dtype=_DTYPE)
print(f"[kaggle] treino {_xtr.shape} | val {_xva.shape} | "
      f"arquitetura {N_IN}-{'-'.join(str(_h) for _h in HIDDEN)}-{N_OUT} "
      f"({_n_params:,} params) | dtype {_DTYPE.__name__} | epochs {_EPOCHS}")

_gpus = []
_TRAIN_GPU = False
try:
    import tensorflow as _tf
    _gpus = _tf.config.list_physical_devices("GPU")
except Exception:
    _tf = None

if _tf is not None and len(_gpus) >= 1:
    # ---------------- GPU PATH (Kaggle 2x T4, MirroredStrategy, FP64) ----------------
    # FP64 e o padrao desde a v0.4.3 (exigencia do usuario). A T4 roda FP64 a
    # 1/32 da velocidade do FP32 — para optar por FP32: ETS2AI_F32=1.
    import math as _math
    if _DTYPE == np.float64:
        _tf.keras.backend.set_floatx("float64")
    print(f"[kaggle] GPU detectada: {len(_gpus)}x {_gpus[0][1]} — treinando com "
          f"tf.distribute.MirroredStrategy (todas as GPUs), {_DTYPE.__name__}")
    _strategy = _tf.distribute.MirroredStrategy()
    with _strategy.scope():
        _model = _tf.keras.Sequential()
        _model.add(_tf.keras.Input(shape=(N_IN,)))
        for _h in HIDDEN:
            _model.add(_tf.keras.layers.Dense(_h, activation="tanh"))
        _model.add(_tf.keras.layers.Dense(N_OUT, activation="linear"))
        _lr = 2e-3
        _model.compile(_tf.keras.optimizers.Adam(learning_rate=_lr), loss="mse")
    _sched = _tf.keras.callbacks.LearningRateScheduler(
        lambda e, lr: _lr * (0.05 + 0.95 * 0.5 * (1.0 + _math.cos(_math.pi * e / max(1, _EPOCHS)))),
        verbose=0)
    _model.fit(_xtr, _ytr, epochs=_EPOCHS, batch_size=2048,
               validation_data=(_xva, _yva), verbose=2, callbacks=[_sched])
    _w = _model.get_weights()
    _layers = [(np.asarray(_w[2 * i], dtype=_DTYPE),
                np.asarray(_w[2 * i + 1], dtype=_DTYPE))
               for i in range(len(_w) // 2)]
    _TRAIN_GPU = True
else:
    # ---------------- CPU fallback (identical math) ----------------
    print(f"[kaggle] sem GPU — treinando em numpy (CPU, {_DTYPE.__name__})")
    _layers, _hist = train(_xtr, _ytr, epochs=_EPOCHS, x_val=_xva, y_val=_yva,
                           dtype=_DTYPE)

_loss_tr = mse(forward(_xtr, _layers), _ytr)
_loss_va = mse(forward(_xva, _layers), _yva)
print(f"[kaggle] MSE treino {_loss_tr:.5f} | validacao {_loss_va:.5f} (meta <= {LOSS_TARGET})")

_agg, _rows = closed_loop_eval(_layers, n_roads=5)
print(f"[kaggle] circuito fechado: {_agg['finish_rate']*100:.0f}% rotas, "
      f"{_agg['in_lane_pct']*100:.0f}% faixa, {_agg['avg_speed_kmh']:.0f} km/h, "
      f"radares {_agg['radar_compliance']*100:.0f}%, dock {_agg['dock_rate']*100:.0f}%")

save_weights(_os.path.join(_OUT, "model-weights.json"), _layers,
             model_meta(epochs=_EPOCHS, samples=int(len(_xtr) + len(_xva)), loss=_loss_va,
                        dtype="float64" if _DTYPE == np.float64 else None))
with open(_os.path.join(_OUT, "metrics.json"), "w", encoding="utf-8") as _f:
    _json.dump({"mse_train": _loss_tr, "mse_val": _loss_va,
                "loss_target": LOSS_TARGET, "closed_loop": _agg,
                "trained_on_gpu": _TRAIN_GPU, "n_gpus": len(_gpus),
                "dtype": _DTYPE.__name__}, _f, indent=2)
print(f"[kaggle] saida: model-weights.json + metrics.json (gpu={_TRAIN_GPU}, "
      f"ngpus={len(_gpus)}, dtype={_DTYPE.__name__})")
"""


def strip_local_imports(src):
    """Remove intra-package imports (including multi-line/parenthesised);
    concatenation order provides the names."""
    out = []
    skipping = False
    depth = 0
    for line in src.splitlines():
        if skipping:
            depth += line.count("(") - line.count(")")
            if depth <= 0:
                skipping = False
            continue
        if re.match(r"^(from \.|from ets2ai|import ets2ai)", line):
            depth = line.count("(") - line.count(")")
            if depth > 0:
                skipping = True
            continue
        out.append(line)
    return "\n".join(out)


def build() -> str:
    parts = [
        "# ETS2-AI training kernel (auto-generated by ets2-ai/kaggle/build_kernel.py)\n"
        "# Same code, same seed as the repo — output is validated by GitHub Actions.\n"
    ]
    for name in MODULES:
        body = (PKG / name).read_text(encoding="utf-8")
        body = body.split('if __name__ == "__main__":')[0]  # drop CLI mains
        parts.append(f"# ===== ets2ai/{name} =====\n" + strip_local_imports(body))
        if name == "sim.py":
            # train.py does `from . import sim` — provide a module shim with
            # every name train.py touches through `sim.`.
            parts.append(
                "import types as _types\n"
                "sim = _types.SimpleNamespace(\n"
                "    features=features, Road=Road, Truck=Truck, expert=expert,\n"
                "    run_episode=run_episode, wrap_angle=wrap_angle,\n"
                "    LOOKAHEAD=LOOKAHEAD, SPEED_LIMIT_MPS=SPEED_LIMIT_MPS,\n"
                "    REFUEL_BELOW=REFUEL_BELOW, SLEEP_ABOVE=SLEEP_ABOVE,\n"
                "    ROAD_HALF=ROAD_HALF, LANE_HALF=LANE_HALF, DT=DT,\n"
                ")\n")
    parts.append(FOOTER)
    return "\n".join(parts)


if __name__ == "__main__":
    print(build())
