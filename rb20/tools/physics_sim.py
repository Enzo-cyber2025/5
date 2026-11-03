"""
physics_sim.py -- offline validation of the SHIPPED AC physics data.

Reads the generated .ini/.lut files (not the calibration shortcuts), integrates
a longitudinal vehicle model that mirrors AC's equations, and compares it with
the real telemetry acceleration and braking envelopes. Also computes steady
state cornering grip, 0-100/200/300 times, braking distance and top speed.

This is NOT a claim that Assetto Corsa itself was executed -- see README.
"""
from __future__ import annotations

import argparse
import configparser
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from calibrate import load_telemetry, fit_braking, G, RHO, CRR, MASS, TYRE_R

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def ini(path):
    cp = configparser.ConfigParser(strict=False, allow_no_value=True,
                                   inline_comment_prefixes=(";",))
    cp.optionxform = str
    cp.read(path)
    return cp


def lut(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            k, v = line.split("|", 1)
            out.append((float(k), float(v)))
    return np.array(out, float)


def interp(table, x):
    return float(np.interp(x, table[:, 0], table[:, 1],
                           left=table[0, 1], right=table[-1, 1]))


def load_car(car_dir, telemetry):
    d = os.path.join(car_dir, "data")
    car = ini(os.path.join(d, "car.ini"))
    eng = ini(os.path.join(d, "engine.ini"))
    drv = ini(os.path.join(d, "drivetrain.ini"))
    aero = ini(os.path.join(d, "aero.ini"))
    tyres = ini(os.path.join(d, "tyres.ini"))
    brakes = ini(os.path.join(d, "brakes.ini"))
    ai = ini(os.path.join(d, "ai.ini"))
    power = lut(os.path.join(d, "power.lut"))
    m = float(car["BASIC"]["TOTALMASS"]) + 0.75 * float(car["FUEL"]["FUEL"])
    ratios = [float(drv["GEARS"]["GEAR_%d" % g]) for g in range(1, 9)]
    final = float(drv["GEARS"]["FINAL"])
    shift = float(ai["GEARS"]["UP"])
    limiter = float(eng["ENGINE_DATA"]["LIMITER"])
    CLA = CD = 0.0
    for s in aero.sections():
        if not s.startswith("WING_"):
            continue
        sec = aero[s]
        area = float(sec["CHORD"]) * float(sec["SPAN"])
        cl_lut = lut(os.path.join(d, sec["LUT_AOA_CL"]))
        cd_lut = lut(os.path.join(d, sec["LUT_AOA_CD"]))
        gh_cl = lut(os.path.join(d, sec["LUT_GH_CL"]))
        gh_cd = lut(os.path.join(d, sec["LUT_GH_CD"]))
        CLA += area * float(sec["CL_GAIN"]) * interp(cl_lut, float(sec["ANGLE"])) * interp(gh_cl, 0.045)
        CD += area * float(sec["CD_GAIN"]) * interp(cd_lut, float(sec["ANGLE"])) * interp(gh_cd, 0.045)
    mu = 0.5 * (float(tyres["FRONT"]["DX0"]) + float(tyres["FRONT"]["DY0"]))
    brake_force = 4.0 * float(brakes["DATA"]["MAX_TORQUE"]) / TYRE_R
    return {"m": m, "ratios": ratios, "final": final, "shift": shift,
            "limiter": limiter, "power": power, "CLA": CLA, "CdA": CD,
            "mu": mu, "brake_force": brake_force, "front_share": float(brakes["DATA"]["FRONT_SHARE"])}


def simulate(c):
    m, R = c["m"], TYRE_R
    dt = 0.004
    v = 0.2
    gear = 0
    t = 0.0
    s = 0.0
    marks = {}
    trace = []
    a_prev = 0.0
    while t < 60.0 and v < 115.0:
        total = c["ratios"][gear] * c["final"]
        rpm = min(c["limiter"], max(4200.0, v / (2 * math.pi * R) * 60.0 * total))
        torque = interp(c["power"], rpm)
        f_engine = torque * total * 0.95 / R
        f_down = 0.5 * RHO * c["CLA"] * v ** 2
        f_drag = 0.5 * RHO * c["CdA"] * v ** 2
        f_rr = CRR * (m * G + f_down)
        # RWD: rear axle load = static rear share + longitudinal load transfer
        n_rear = 0.55 * (m * G + f_down) + m * max(0.0, a_prev) * 0.30 / 3.6
        f_grip = c["mu"] * n_rear
        a = (min(f_engine, f_grip) - f_drag - f_rr) / m
        a_prev = a
        v += a * dt
        s += v * dt
        t += dt
        for target in (100, 200, 300):
            kmh = v * 3.6
            if target not in marks and kmh >= target:
                marks[target] = round(t, 2)
        if int(t / dt) % 25 == 0:
            trace.append((v, a, rpm, gear + 1))
        if rpm >= c["shift"] and gear < 7:
            gear += 1
        if a < 0.02 and v > 60:
            break
    return {"top_speed_kmh": round(v * 3.6, 1), "marks_s": marks,
            "trace": trace, "time_s": round(t, 2)}


def braking_curve(c, v0=300 / 3.6):
    m = c["m"]
    dt = 0.002
    v, s, t = v0, 0.0, 0.0
    out = []
    while v > 1.0 and t < 30:
        f_down = 0.5 * RHO * c["CLA"] * v ** 2
        f_drag = 0.5 * RHO * c["CdA"] * v ** 2
        f_grip = c["mu"] * (m * G + f_down)
        f = min(c["brake_force"], f_grip)
        a = -(f + f_drag + CRR * (m * G + f_down)) / m
        out.append((v, -a))
        v += a * dt
        s += v * dt
        t += dt
    return {"distance_m": round(s, 1), "time_s": round(t, 2),
            "peak_decel_g": round(max(x[1] for x in out) / G, 2),
            "curve": out[::40]}


def lateral_envelope(c):
    out = []
    for kmh in range(80, 341, 20):
        v = kmh / 3.6
        f_down = 0.5 * RHO * c["CLA"] * v ** 2
        g = c["mu"] * (c["m"] * G + f_down) / (c["m"] * G)
        out.append((kmh, round(g, 2)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--car-dir", required=True)
    ap.add_argument("--telemetry", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    tel = load_telemetry(args.telemetry)
    brake_fit = fit_braking(tel)
    c = load_car(args.car_dir, tel)
    acc = simulate(c)
    brk = braking_curve(c)
    lat = lateral_envelope(c)

    # Compare simulated acceleration with the real full-throttle envelope.
    sim_v = np.array([p[0] for p in acc["trace"]])
    sim_a = np.array([p[1] for p in acc["trace"]])
    tel_m = (tel["thr"] > 99) & (tel["brk"] < 0.5) & (tel["v"] > 25) & (tel["v"] < 95)
    bins = np.arange(30, 95, 10)
    accel_rows, brake_rows = [], []
    for lo, hi in zip(bins[:-1], bins[1:]):
        tm = tel_m & (tel["v"] >= lo) & (tel["v"] < hi)
        sm = (sim_v >= lo) & (sim_v < hi)
        if tm.sum() > 4 and sm.sum() > 0:
            accel_rows.append((lo + 5, float(np.median(tel["a"][tm])), float(np.median(sim_a[sm]))))
    accel_mae = float(np.mean([abs(r[1] - r[2]) for r in accel_rows])) if accel_rows else 99.0
    sim_bv = np.array([p[0] for p in brk["curve"]])
    sim_ba = np.array([p[1] for p in brk["curve"]])
    for v, dec in brake_fit["points"]:
        s = np.abs(sim_bv - v).argmin()
        brake_rows.append((v, -dec, float(sim_ba[s])))
    brake_mae = float(np.mean([abs(r[1] - r[2]) for r in brake_rows]))

    g250 = dict(lat)[260]
    checks = {
        "accel_mae_under_2_mps2": accel_mae < 2.0 and accel_mae >= 0,
        "brake_mae_under_6_mps2": brake_mae < 6.0,
        "top_speed_300_360_kmh": 300 <= acc["top_speed_kmh"] <= 360,
        "zero_to_100_between_2_and_4_s": 2.0 <= acc["marks_s"].get(100, 99) <= 4.0,
        "peak_braking_over_4g": brk["peak_decel_g"] > 4.0,
        "lateral_grip_over_3g_at_260": g250 > 3.0,
    }
    report = {
        "note": "Offline physics validation of the shipped INI/LUT data. "
                "Assetto Corsa itself was not executed (see README.md).",
        "parameters": {k: v for k, v in c.items() if k != "power"},
        "telemetry": {"lap_time_s": tel["lap_time"], "samples": tel["rows"],
                      "mu_from_braking": brake_fit["mu"],
                      "peak_braking_g_telemetry": brake_fit["peak_decel_g"]},
        "simulation": {"top_speed_kmh": acc["top_speed_kmh"],
                       "accel_times_s": acc["marks_s"],
                       "braking_from_300_kmh": {k: v for k, v in brk.items() if k != "curve"},
                       "lateral_g_vs_kmh": lat},
        "telemetry_comparison": {"accel_bins": accel_rows, "accel_mae_mps2": round(accel_mae, 3),
                                 "brake_bins": brake_rows, "brake_mae_mps2": round(brake_mae, 3)},
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }
    with open(os.path.join(args.out, "validation_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))

    # 3-panel comparison plot
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.6))
    ax[0].plot([r[0] for r in accel_rows], [r[1] for r in accel_rows], "o-", label="telemetry VER")
    ax[0].plot([r[0] for r in accel_rows], [r[2] for r in accel_rows], "s--", label="mod physics")
    ax[0].set(xlabel="speed m/s", ylabel="acceleration m/s²", title="Full throttle")
    ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3)
    ax[1].plot([r[0] for r in brake_rows], [r[1] for r in brake_rows], "o-", label="telemetry VER")
    ax[1].plot([r[0] for r in brake_rows], [r[2] for r in brake_rows], "s--", label="mod physics")
    ax[1].set(xlabel="speed m/s", ylabel="deceleration m/s²", title="Braking")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=0.3)
    ax[2].plot([p[0] for p in lat], [p[1] for p in lat], "-", color="#d8232a")
    ax[2].set(xlabel="km/h", ylabel="lateral g", title="Steady-state grip")
    ax[2].grid(alpha=0.3)
    fig.tight_layout()
    plot = os.path.join(args.out, "validation.png")
    fig.savefig(plot, dpi=110)
    plt.close(fig)

    print("top speed      %.1f km/h" % acc["top_speed_kmh"])
    print("0-100/200/300  %s s" % acc["marks_s"])
    print("brake 300->0   %.1f m, peak %.2f g" % (brk["distance_m"], brk["peak_decel_g"]))
    print("lateral @260   %.2f g" % g250)
    print("accel MAE      %.2f m/s²   brake MAE %.2f m/s²" % (accel_mae, brake_mae))
    print("checks", checks)
    print("wrote", os.path.join(args.out, "validation_report.json"), "and", plot)
    if not all(checks.values()):
        print("WARNING: some validation checks failed", file=sys.stderr)


if __name__ == "__main__":
    main()
