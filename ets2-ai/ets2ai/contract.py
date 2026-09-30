"""Shared feature/action contract for the ETS2-AI driving policy.

Every implementation (numpy training, Java on-device, TFLite, Windows bridge)
must obey EXACTLY this contract. Changing it requires regenerating weights.
"""
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Input features (12). Order is part of the wire format.
# ---------------------------------------------------------------------------
FEATURES = [
    "speed",            # m/s / 25 (truck top speed ~ 25 m/s = 90 km/h)
    "lane_offset",      # lateral offset from lane centre, m / 3.5
    "heading_error",    # heading error vs road tangent, rad / 0.6
    "curv_1",           # curvature at 8 m ahead, 1/m / 0.05
    "curv_2",           # curvature at 18 m ahead
    "curv_3",           # curvature at 30 m ahead
    "curv_4",           # curvature at 45 m ahead
    "curv_5",           # curvature at 60 m ahead
    "speed_limit",      # speed limit, m/s / 25
    "fuel",             # fuel fraction 0..1
    "fatigue",          # fatigue 0..1 (1 = must sleep immediately)
    "job_dist",         # remaining job distance, km / 100
    "radar_dist",       # distance to the next speed camera, m / 500
]
N_IN = len(FEATURES)

# ---------------------------------------------------------------------------
# Outputs (3). Order is part of the wire format.
# ---------------------------------------------------------------------------
ACTIONS = ["steer", "throttle", "brake"]
N_OUT = len(ACTIONS)

# MLP architecture (part of the wire format).
HIDDEN = [24, 24]
SEED = 20260930  # deterministic training across runs/CI

# Reporting target demanded by the project brief.
LOSS_TARGET = 0.150


def clamp_action(steer, throttle, brake):
    """Actuator clamp — part of the wire contract (mirrored in Java/bridge).
    The raw MLP may extrapolate outside the training distribution; commands
    sent to the game (or the demo sim) are always clamped here."""
    return (max(-1.0, min(1.0, steer)),
            max(0.0, min(1.0, throttle)),
            max(0.0, min(1.0, brake)))


def model_meta(epochs=None, samples=None, loss=None):
    return {
        "features": FEATURES,
        "actions": ACTIONS,
        "hidden": HIDDEN,
        "seed": SEED,
        "loss_target": LOSS_TARGET,
        "epochs": epochs,
        "samples": samples,
        "final_loss": loss,
    }


def save_weights(path, layer_weights, meta):
    """layer_weights: list of (W, b) numpy arrays; saved as plain JSON."""
    payload = {
        "meta": meta,
        "layers": [
            {"w": w.tolist(), "b": b.tolist()} for (w, b) in layer_weights
        ],
    }
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def load_weights(path):
    import numpy as np
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    layers = [
        (np.array(l["w"], dtype=np.float32), np.array(l["b"], dtype=np.float32))
        for l in payload["layers"]
    ]
    return layers, payload["meta"]


def save_device_format(path, layers, meta):
    """Plain-text weights for the Java app (no JSON parser on device).

    Format (CSV, one float per value, '.' decimal separator):
        ETS2AI,v1,<nin>,<nout>,<h1>,<h2>
        per layer: W rows (fan_in lines of fan_out floats), then bias line.
    The values are bit-identical to model-weights.json.
    """
    lines = [f"ETS2AI,v1,{N_IN},{N_OUT},{','.join(str(h) for h in HIDDEN)}"]
    for (w, b) in layers:
        for row in w:
            lines.append(",".join(repr(float(v)) for v in row))
        lines.append(",".join(repr(float(v)) for v in b))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_device_format(path):
    """Reference loader (used by tests to prove txt == json)."""
    import numpy as np
    lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
    header = lines[0].split(",")
    assert header[0] == "ETS2AI" and header[1] == "v1"
    sizes = [int(header[2])] + [int(h) for h in header[4:]] + [int(header[3])]
    layers, pos = [], 1
    for i in range(len(sizes) - 1):
        fan_in, fan_out = sizes[i], sizes[i + 1]
        w = np.zeros((fan_in, fan_out), dtype=np.float32)
        for r in range(fan_in):
            w[r] = [float(v) for v in lines[pos].split(",")]
            pos += 1
        b = np.array([float(v) for v in lines[pos].split(",")], dtype=np.float32)
        pos += 1
        layers.append((w, b))
    assert pos == len(lines)
    return layers
