"""Dataset generation: expert demonstrations on random roads.

The expert is a pure-pursuit + predictive-speed controller. Since v0.4.2 the
demonstrations are PERFECT (zero action noise) — the user asked for the
minimum loss mathematically achievable, and the old human-like noise
(sigma=0.02) imposed a ~2e-4 MSE floor that no network could beat.
Train/val roads are disjoint.
"""
import numpy as np

from .contract import N_IN, N_OUT
from .sim import Road, expert, run_episode

N_TRAIN_ROADS = 220     # v0.4.3: >1M training samples (user spec)
N_VAL_ROADS = 15
NOISE = 0.0            # v0.4.2: especialista perfeito (antes 0.020 humano)
ROAD_SEED = 31337


def _oversample_dock(feats, acts, reps=4):
    """Duplicate approach/dock rows (last 150 m) so the policy learns the
    precise stop: they are a tiny fraction of each episode."""
    tail = feats[:, 11] * 20.0 * 1000.0 < 150.0     # job_left < 150 m
    return (np.concatenate([feats] + [feats[tail]] * (reps - 1)),
            np.concatenate([acts] + [acts[tail]] * (reps - 1)))


def generate():
    x_train, y_train, x_val, y_val = [], [], [], []
    for k in range(N_TRAIN_ROADS + N_VAL_ROADS):
        road = Road.random(ROAD_SEED + k)
        feats, acts, _ = run_episode(
            road,
            lambda r, t, j, rng: expert(r, t, j, noise=NOISE, rng=rng),
            seed=1000 + k, record=True)
        feats, acts = _oversample_dock(feats, acts)
        if k < N_TRAIN_ROADS:
            x_train.append(feats); y_train.append(acts)
        else:
            x_val.append(feats); y_val.append(acts)
    return (np.concatenate(x_train), np.concatenate(y_train),
            np.concatenate(x_val), np.concatenate(y_val))


if __name__ == "__main__":
    xt, yt, xv, yv = generate()
    print("train", xt.shape, "val", xv.shape)
