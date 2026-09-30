"""Docking/parking gates: precise stop at the loading dock."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ets2ai import sim                                      # noqa: E402
from ets2ai.contract import load_weights, clamp_action      # noqa: E402
from ets2ai.model import forward                            # noqa: E402
from ets2ai.sim import Road, expert, run_episode            # noqa: E402

ART = ROOT / "artifacts"


def _policy(layers):
    def p(road, truck, job_left_km, rng=None):
        f = np.asarray(sim.features(road, truck, job_left_km), dtype=np.float32)
        o = forward(f, layers)[0]
        return clamp_action(float(o[0]), float(o[1]), float(o[2]))
    return p


def test_expert_docks_precisely():
    road = Road.random(60606)
    m = run_episode(road, lambda r, t, j, rng: expert(r, t, j), seed=3)
    assert m["docked"], m
    assert abs(m["stop_error_m"]) < 2.5, m     # creep para na linha (1.5 m)


def test_policy_parks_at_the_dock():
    """A IA para NO dock, sem overshoot, em estradas ineditas."""
    layers, meta = load_weights(ART / "model-weights.json")
    assert meta["final_loss"] <= 0.150
    pol = _policy(layers)
    errs = []
    for k in range(4):
        road = Road.random(13579 + k)
        m = run_episode(road, pol, seed=11 + k)
        assert m["docked"], (k, m)
        assert m["stop_error_m"] is not None and m["stop_error_m"] > 0
        errs.append(m["stop_error_m"])
    assert max(errs) < 5.0, errs               # parou na linha, sem atropelar
    assert min(errs) > 0.0, errs


def test_dock_governor_blocks_overshoot():
    """Governor: chegando rapido demais, freia total — nunca atravessa o dock."""
    road = Road.random(24680)
    truck = sim.Truck(road, s=road.length - 200.0, offset=0.0, speed=33.0)
    for _ in range(1200):
        cmd = sim.governor(road, truck, (0.0, 1.0, 0.0))   # acelerando a toa
        truck.step(road, cmd[0], cmd[1], cmd[2])
        if truck.speed < 0.6:
            break
    assert truck.s < road.length - 3.0       # parou antes da linha
    assert truck.speed < 2.0
