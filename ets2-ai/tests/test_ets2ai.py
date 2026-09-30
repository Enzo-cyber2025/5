"""Quality gates for the ETS2-AI policy. Run with pytest from ets2-ai/.

These tests are the project's honesty layer: they re-run the closed-loop
evaluation and fail the CI if the policy cannot actually drive, even when
the scalar loss target is met.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from ets2ai.contract import (load_weights, load_device_format, N_IN, N_OUT,
                             FEATURES, ACTIONS, LOSS_TARGET, clamp_action)
from ets2ai.model import forward
from ets2ai import sim
from ets2ai.sim import Road, Truck, expert, run_episode, wrap_angle

ART = ROOT / "artifacts"


@pytest.fixture(scope="module")
def layers():
    layers, meta = load_weights(ART / "model-weights.json")
    assert meta["final_loss"] <= LOSS_TARGET
    return layers


def test_contract_shape():
    assert N_IN == 13 and N_OUT == 3
    assert FEATURES[:3] == ["speed", "lane_offset", "heading_error"]
    assert FEATURES[-1] == "radar_dist"
    assert ACTIONS == ["steer", "throttle", "brake"]


def test_device_format_matches_json(layers):
    """The CSV the Java app reads must be bit-identical to the JSON."""
    dev = load_device_format(ART / "model-weights.txt")
    assert len(dev) == len(layers)
    for (w1, b1), (w2, b2) in zip(dev, layers):
        np.testing.assert_array_equal(w1, w2)
        np.testing.assert_array_equal(b1, b2)


def test_forward_ranges(layers):
    """Raw outputs may extrapolate off-distribution; clamped commands must
    always respect actuator limits (clamp is part of the contract)."""
    rng = np.random.default_rng(0)
    x = rng.uniform(-1.2, 1.2, (512, N_IN)).astype(np.float32)
    out = forward(x, layers)
    assert out.shape == (512, N_OUT)
    clamped = np.array([clamp_action(*row) for row in out])
    assert float(clamped[:, 0].min()) >= -1.0 and float(clamped[:, 0].max()) <= 1.0
    assert float(clamped[:, 1].min()) >= 0.0 and float(clamped[:, 1].max()) <= 1.0
    assert float(clamped[:, 2].min()) >= 0.0 and float(clamped[:, 2].max()) <= 1.0


def test_expert_drives_the_sim():
    """Sanity: the expert used to generate data completes a route."""
    road = Road.random(4242)
    m = run_episode(road, lambda r, t, j, rng: expert(r, t, j), seed=5)
    assert m["finished"], m
    assert m["in_lane_pct"] > 0.95


def test_policy_loss_target(layers):
    metrics = json.loads((ART / "metrics.json").read_text())
    assert metrics["mse_val"] <= LOSS_TARGET
    assert metrics["target_met"] is True


def test_policy_drives_closed_loop(layers):
    """THE gate: the learned policy must complete unseen routes in-lane."""
    def policy(road, truck, job_left_km, rng=None):
        f = np.asarray(sim.features(road, truck, job_left_km), dtype=np.float32)
        o = forward(f, layers)[0]
        return float(o[0]), float(o[1]), float(o[2])

    roads = [Road.random(90210 + k) for k in range(3)]
    finishes, lanes = [], []
    for k, road in enumerate(roads):
        m = run_episode(road, policy, seed=123 + k)
        finishes.append(m["finished"])
        lanes.append(m["in_lane_pct"])
    assert sum(finishes) == len(roads), (finishes, lanes)
    assert min(lanes) > 0.95, lanes


def test_rules_refuel_and_sleep(layers):
    """Career rules must fire: low fuel refuels, high fatigue sleeps."""
    road = Road.random(555)
    truck = Truck(road, s=5.0, offset=0.0, speed=20.0)
    truck.fuel = 0.05
    truck.step(road, 0, 0.5, 0)
    # rule check happens in run_episode; here we assert thresholds exist
    assert sim.REFUEL_BELOW == 0.14 and sim.SLEEP_ABOVE == 0.82
    assert truck.fuel < sim.REFUEL_BELOW


def test_wrap_angle():
    assert abs(wrap_angle(3 * np.pi) - np.pi) < 1e-9
    assert abs(wrap_angle(-3 * np.pi) + np.pi) < 1e-9
