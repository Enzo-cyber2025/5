"""ETS2-AI core: numpy-only MLP + training + export.

Deliberately dependency-free (numpy only) so the exact same numbers can be
reproduced on the CI runner and re-implemented bit-for-bit in Java on the
phone and in TFLite. Deterministic under SEED.
"""
import json
import math
from pathlib import Path
import numpy as np

from .contract import N_IN, N_OUT, HIDDEN, SEED, LOSS_TARGET, model_meta


def init_layers(rng, dtype=np.float32):
    """He initialisation for tanh layers; returns [(W,b), ...]."""
    sizes = [N_IN] + list(HIDDEN) + [N_OUT]
    layers = []
    for i in range(len(sizes) - 1):
        fan_in, fan_out = sizes[i], sizes[i + 1]
        # cast DEPOIS da multiplicacao: com NEP 50 (numpy>=2), float32 * np.float64
        # promoveria para float64 — era o comportamento antigo por acidente.
        w = (rng.standard_normal((fan_in, fan_out)) * np.sqrt(1.0 / fan_in)).astype(dtype)
        b = np.zeros(fan_out, dtype=dtype)
        layers.append((w, b))
    return layers


def forward(x, layers, keep=None):
    """Forward pass. x: (N, N_IN) or (N_IN,). tanh hidden, linear output.

    Precision follows the weights (float32 deploy / float64 experiment).
    `keep` (optional) receives intermediate activations for backprop.
    Returns activations of the output layer.
    """
    a = np.atleast_2d(np.asarray(x, dtype=layers[0][0].dtype))
    last = len(layers) - 1
    for i, (w, b) in enumerate(layers):
        z = a @ w + b
        a = z if i == last else np.tanh(z)
        if keep is not None:
            keep.append(a)
    return a


def mse(pred, target):
    """MSE na precisao nativa dos inputs (float32 fica float32; float64
    conserva a faixa ~1e-308 — usado pelo modo --dtype float64)."""
    p = np.asarray(pred)
    t = np.asarray(target)
    if p.dtype != t.dtype:
        p, t = p.astype(np.float64), t.astype(np.float64)
    return float(np.mean((p - t) ** 2))


class Adam:
    def __init__(self, layers, lr=2e-3, b1=0.9, b2=0.999, eps=1e-8):
        self.lr, self.b1, self.b2, self.eps = lr, b1, b2, eps
        self.m = [[np.zeros_like(p) for p in (w, b)] for (w, b) in layers]
        self.v = [[np.zeros_like(p) for p in (w, b)] for (w, b) in layers]
        self.t = 0

    def step(self, layers, grads):
        self.t += 1
        b1c = 1 - self.b1 ** self.t
        b2c = 1 - self.b2 ** self.t
        for li, ((w, b), (gw, gb)) in enumerate(zip(layers, grads)):
            for pi, (p, g) in enumerate(((w, gw), (b, gb))):
                self.m[li][pi] = self.b1 * self.m[li][pi] + (1 - self.b1) * g
                self.v[li][pi] = self.b2 * self.v[li][pi] + (1 - self.b2) * g * g
                m_hat = self.m[li][pi] / b1c
                v_hat = self.v[li][pi] / b2c
                p -= self.lr * m_hat / (np.sqrt(v_hat) + self.eps)


def train(x, y, epochs=400, batch=512, lr=2e-3, seed=SEED, verbose=True,
          x_val=None, y_val=None, start_layers=None, dtype=np.float32,
          schedule="cosine"):
    """Train the MLP on (x, y) with Adam + MSE. Returns (layers, history).

    start_layers: optional [(W,b), ...] to continue training from existing
    weights (DAgger finetuning) instead of initialising from scratch.
    dtype: np.float32 (deploy rapido) ou np.float64 (experimento de precisao).
    schedule: "cosine" decai lr de `lr` ate 5% de `lr` ao longo das epocas
    (deterministico, ajuda a fechar a loss); None mantem lr constante.
    """
    rng = np.random.default_rng(seed)
    layers = start_layers if start_layers is not None else init_layers(rng, dtype)
    opt = Adam(layers, lr=lr)
    x = np.asarray(x, dtype=dtype)
    y = np.asarray(y, dtype=dtype)
    if x_val is not None:
        x_val = np.asarray(x_val, dtype=dtype)
        y_val = np.asarray(y_val, dtype=dtype)
    n = len(x)
    history = []
    best = (np.inf, None)
    for epoch in range(epochs):
        if schedule == "cosine":
            opt.lr = lr * (0.05 + 0.95 * 0.5 * (1.0 + math.cos(math.pi * epoch / epochs)))
        idx = rng.permutation(n)
        for s in range(0, n, batch):
            sel = idx[s:s + batch]
            acts = []
            out = forward(x[sel], layers, keep=acts)
            err = out - y[sel]                       # (B, N_OUT)
            grads = [None] * len(layers)
            delta = (2.0 / (len(sel) * N_OUT)) * err  # dMSE/dz_out (linear)
            for li in range(len(layers) - 1, -1, -1):
                a_prev = x[sel] if li == 0 else acts[li - 1]
                grads[li] = (a_prev.T @ delta, delta.sum(axis=0))
                if li > 0:
                    delta = (delta @ layers[li][0].T) * (1 - acts[li - 1] ** 2)
            opt.step(layers, grads)
        tr = mse(forward(x, layers), y)
        va = mse(forward(x_val, layers), y_val) if x_val is not None else None
        history.append((tr, va))
        if va is not None and va < best[0]:
            best = (va, [(w.copy(), b.copy()) for (w, b) in layers])
        if verbose and (epoch % 40 == 0 or epoch == epochs - 1):
            msg = f"epoch {epoch:4d}  train_mse {tr:.5f}"
            if va is not None:
                msg += f"  val_mse {va:.5f}"
            print(msg, flush=True)
    if best[1] is not None:  # restore best-validation weights
        layers = best[1]
    return layers, history
