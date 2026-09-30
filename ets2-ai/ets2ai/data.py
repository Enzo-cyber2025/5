"""Dataset generation: expert demonstrations on random roads.

The expert is a pure-pursuit + predictive-speed controller with small
human-like action noise, so the learned policy imitates a competent (not
superhuman) trucker. Train/val roads are disjoint.
"""
import numpy as np

from .contract import N_IN, N_OUT
from .sim import Road, expert, run_episode

N_TRAIN_ROADS = 26
N_VAL_ROADS = 7
NOISE = 0.020          # small human imperfection (tight GPS line)
ROAD_SEED = 31337


def generate():
    x_train, y_train, x_val, y_val = [], [], [], []
    for k in range(N_TRAIN_ROADS + N_VAL_ROADS):
        road = Road.random(ROAD_SEED + k)
        feats, acts, _ = run_episode(
            road,
            lambda r, t, j, rng: expert(r, t, j, noise=NOISE, rng=rng),
            seed=1000 + k, record=True)
        if k < N_TRAIN_ROADS:
            x_train.append(feats); y_train.append(acts)
        else:
            x_val.append(feats); y_val.append(acts)
    return (np.concatenate(x_train), np.concatenate(y_train),
            np.concatenate(x_val), np.concatenate(y_val))


if __name__ == "__main__":
    xt, yt, xv, yv = generate()
    print("train", xt.shape, "val", xv.shape)
