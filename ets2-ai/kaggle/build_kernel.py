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
MODULES = ["contract.py", "sim.py", "model.py", "data.py", "train.py",
           "vector_gen.py"]

FOOTER = """

# ---------------------------------------------------------------------------
# Kaggle runner footer (appended by build_kernel.py — do not edit here)
# v0.4.4: treino em FLUXO com o simulador vetorizado — orcamento de AMOSTRAS
# (1 bilhao por padrao, FP32 nas T4; FP64 via ETS2AI_F64=1 com orcamento menor)
# ---------------------------------------------------------------------------
import json as _json
import math as _math
import os as _os
import time as _time

_OUT = _os.environ.get("KAGGLE_WORKING_DIR", ".")
_F64 = _os.environ.get("ETS2AI_F64") == "1"
_DTYPE = np.float64 if _F64 else np.float32
_SAMPLES = int(_os.environ.get("ETS2AI_SAMPLES", "1000000000"))
_MAX_SEC = float(_os.environ.get("ETS2AI_MAX_SECONDS", "10800"))
_BATCH = int(_os.environ.get("ETS2AI_BATCH", "16384" if not _F64 else "1024"))
_EPOCHS = int(_os.environ.get("ETS2AI_EPOCHS", "60"))
_n_params = (N_IN * HIDDEN[0] + HIDDEN[0]
             + sum(HIDDEN[i] * HIDDEN[i + 1] + HIDDEN[i + 1] for i in range(len(HIDDEN) - 1))
             + HIDDEN[-1] * N_OUT + N_OUT)
print(f"[kaggle] arquitetura {N_IN}-{'-'.join(str(_h) for _h in HIDDEN)}-{N_OUT} "
      f"({_n_params:,} params) | dtype {_DTYPE.__name__} | batch {_BATCH}")
print(f"[kaggle] orcamento: {_SAMPLES:,} amostras em fluxo (unicas) | "
      f"teto {_MAX_SEC/3600:.1f} h")

_gpus = []
_TRAIN_GPU = False
try:
    import tensorflow as _tf
    _gpus = _tf.config.list_physical_devices("GPU")
except Exception:
    _tf = None

if _tf is not None and len(_gpus) >= 1:
    # ---------------- GPU PATH (2x T4, MirroredStrategy, fluxo) ----------------
    if _DTYPE == np.float64:
        _tf.keras.backend.set_floatx("float64")
    print(f"[kaggle] GPU detectada: {len(_gpus)}x {_gpus[0][1]} — "
          f"tf.distribute.MirroredStrategy (todas as GPUs), {_DTYPE.__name__}")
    _total_steps = max(1, _SAMPLES // _BATCH)
    _pi = _tf.constant(_math.pi, _tf.float32)

    class _CosineFloor(_tf.keras.optimizers.schedules.LearningRateSchedule):
        def __init__(self, base, total):
            super().__init__()
            self.base = base
            self.total = total
        def __call__(self, step):
            f = _tf.minimum(_tf.cast(step, _tf.float32) / self.total, 1.0)
            return self.base * (0.05 + 0.95 * 0.5 * (1.0 + _tf.cos(_pi * f)))

    _strategy = _tf.distribute.MirroredStrategy()
    with _strategy.scope():
        _model = _tf.keras.Sequential()
        _model.add(_tf.keras.Input(shape=(N_IN,)))
        for _h in HIDDEN:
            _model.add(_tf.keras.layers.Dense(
                _h, activation="tanh", kernel_initializer="he_normal"))
        _model.add(_tf.keras.layers.Dense(
            N_OUT, activation="linear", kernel_initializer="he_normal"))
        _model.compile(_tf.keras.optimizers.Adam(learning_rate=_CosineFloor(5e-4, _total_steps)), loss="mse")
    _xva, _yva = val_set(seed=999)
    _t0 = _time.time()
    _consumed = 0
    _best_val = float("inf")
    _best_w = None
    _last_val = 0
    print("[kaggle] gerando dados em fluxo e treinando...")
    for _x, _y in stream(SEED, n_trucks=3072):
        if _consumed >= _SAMPLES or (_time.time() - _t0) > _MAX_SEC:
            break
        for _s0 in range(0, len(_x), _BATCH):
            _mb_x = _x[_s0:_s0 + _BATCH]
            _mb_y = _y[_s0:_s0 + _BATCH]
            if len(_mb_x) < 64:
                continue
            _model.train_on_batch(_mb_x.astype(_DTYPE), _mb_y.astype(_DTYPE))
            _consumed += len(_mb_x)
            if _consumed >= _SAMPLES or (_time.time() - _t0) > _MAX_SEC:
                break
        if _consumed - _last_val >= 20_000_000 or _consumed >= _SAMPLES \
                or (_time.time() - _t0) > _MAX_SEC:
            _va = float(_model.evaluate(_xva.astype(_DTYPE), _yva.astype(_DTYPE),
                                        verbose=0, batch_size=8192))
            if _va < _best_val:
                _best_val = _va
                _best_w = _model.get_weights()
            _h_elapsed = (_time.time() - _t0) / 3600
            print(f"[kaggle] {_consumed:,} amostras | val {_va:.5f} "
                  f"(melhor {_best_val:.5f}) | {_h_elapsed:.2f} h", flush=True)
            _last_val = _consumed
    if _best_w is not None:
        _model.set_weights(_best_w)          # restaura os melhores pesos
    _w = _model.get_weights()
    _layers = [(np.asarray(_w[2 * i], dtype=_DTYPE),
                np.asarray(_w[2 * i + 1], dtype=_DTYPE))
               for i in range(len(_w) // 2)]
    _TRAIN_GPU = True
    _loss_tr = None
    _loss_va = _best_val
else:
    # ---------------- CPU fallback (deterministico, estatico) ----------------
    print(f"[kaggle] sem GPU — treinando em numpy (CPU, {_DTYPE.__name__}, "
          f"dataset estatico)")
    _xtr, _ytr, _xva, _yva = generate()
    _xtr = np.asarray(_xtr, dtype=_DTYPE); _ytr = np.asarray(_ytr, dtype=_DTYPE)
    _xva = np.asarray(_xva, dtype=_DTYPE); _yva = np.asarray(_yva, dtype=_DTYPE)
    print(f"[kaggle] treino {_xtr.shape} | val {_xva.shape}")
    _layers, _hist = train(_xtr, _ytr, epochs=_EPOCHS, x_val=_xva, y_val=_yva,
                           dtype=_DTYPE)
    _consumed = int(len(_xtr) + len(_xva))
    _loss_tr = mse(forward(_xtr, _layers), _ytr)
    _loss_va = mse(forward(_xva, _layers), _yva)

print(f"[kaggle] MSE validacao {_loss_va:.5f} (meta <= {LOSS_TARGET}) | "
      f"amostras consumidas: {_consumed:,}")

_agg, _rows = closed_loop_eval(_layers, n_roads=5)
print(f"[kaggle] circuito fechado: {_agg['finish_rate']*100:.0f}% rotas, "
      f"{_agg['in_lane_pct']*100:.0f}% faixa, {_agg['avg_speed_kmh']:.0f} km/h, "
      f"{_agg['radar_compliance']*100:.0f}% radares, {_agg['dock_rate']*100:.0f}% dock")

save_weights(_os.path.join(_OUT, "model-weights.json"), _layers,
             model_meta(epochs=None, samples=int(_consumed), loss=_loss_va,
                        dtype="float64" if _DTYPE == np.float64 else None))
with open(_os.path.join(_OUT, "metrics.json"), "w", encoding="utf-8") as _f:
    _json.dump({"mse_train": _loss_tr, "mse_val": _loss_va,
                "loss_target": LOSS_TARGET, "closed_loop": _agg,
                "trained_on_gpu": _TRAIN_GPU, "n_gpus": len(_gpus),
                "samples_consumed": int(_consumed),
                "dtype": _DTYPE.__name__,
                "streaming": bool(_TRAIN_GPU)}, _f, indent=2)
print(f"[kaggle] saida: model-weights.json + metrics.json (gpu={_TRAIN_GPU}, "
      f"ngpus={len(_gpus)}, dtype={_DTYPE.__name__}, "
      f"amostras={_consumed:,}, streaming={_TRAIN_GPU})")
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
