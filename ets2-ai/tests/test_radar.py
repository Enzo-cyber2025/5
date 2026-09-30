"""Speed-demon policy gates: radars, rollover physics, GPS adherence."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ets2ai import sim                                     # noqa: E402
from ets2ai.contract import load_weights, clamp_action     # noqa: E402
from ets2ai.model import forward                           # noqa: E402
from ets2ai.sim import Road, expert, run_episode           # noqa: E402

ART = ROOT / "artifacts"


def _policy(layers):
    def p(road, truck, job_left_km, rng=None):
        f = np.asarray(sim.features(road, truck, job_left_km), dtype=np.float32)
        o = forward(f, layers)[0]
        c = clamp_action(float(o[0]), float(o[1]), float(o[2]))
        return c
    return p


def test_expert_is_a_speed_demon_who_respects_radars():
    road = Road.random(31415)
    assert len(road.radars) >= 2
    m = run_episode(road, lambda r, t, j, rng: expert(r, t, j), seed=1)
    assert m["radar_compliance"] == 1.0, m   # nunca acima do limite na camera
    assert m["max_lat_accel"] < sim.LAT_ACCEL_ROLLOVER  # nao tomba
    # acelera acima do limite nas retas (velocista)
    assert m["avg_speed"] > 21.0  # media ~80 km/h, acima do ritmo antigo (65)


def test_policy_speeds_and_brakes_for_radars():
    layers, meta = load_weights(ART / "model-weights.json")
    assert meta["final_loss"] <= 0.150
    pol = _policy(layers)
    road = Road.random(27182)
    feats, _, m = run_episode(road, pol, seed=7, record=True)
    speeds = feats[:, 0] * 25.0
    # velocista: pico bem acima do limite (130 km/h ~ 36 m/s)
    assert speeds.max() >= 30.0, speeds.max()
    # radares: quase todas as passagens abaixo do limite
    assert m["radar_compliance"] >= 0.9, m
    # fisica: nunca passa do limite de tombamento
    assert m["max_lat_accel"] <= sim.LAT_ACCEL_ROLLOVER + 0.05, m
    # GPS: segue o tracado de perto
    assert m["mean_abs_offset"] < 0.6, m
    assert m["in_lane_pct"] > 0.95 and m["finished"]


def test_radar_feature_drives_braking():
    """Em episodio real: com radar perto e em alta, freio maior que sem radar."""
    layers, _ = load_weights(ART / "model-weights.json")
    pol = _policy(layers)
    feats, acts, m = run_episode(Road.random(27182), pol, seed=7, record=True)
    near = (feats[:, 12] < 0.30) & (feats[:, 0] > 1.0)   # radar <150 m, rapido
    far = feats[:, 12] > 0.60                            # radar >300 m
    assert near.sum() > 20 and far.sum() > 20, (int(near.sum()), int(far.sum()))
    brake_near = float(acts[near, 2].mean())
    brake_far = float(acts[far, 2].mean())
    thr_near = float(acts[near, 1].mean())
    thr_far = float(acts[far, 1].mean())
    assert brake_near > brake_far                        # freia mais perto do radar
    assert thr_near < thr_far                            # e acelera menos
