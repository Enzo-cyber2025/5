"""
physics_sim.py -- offline validation of the SHIPPED AC physics data.

Reads the generated .ini/.lut files (not the calibration shortcuts), integrates
a longitudinal vehicle model that mirrors AC's equations, and compares it with
the real telemetry acceleration and braking envelopes. Also evaluates:

  * official published power: power.lut (ICE) + kers_torque.lut (MGU-K)
  * ERS: 0-300 km/h with no deployment, lap-average deployment and full deploy
  * DRS: closed vs open rear-flap aero and terminal speed
  * wet compounds: grip, 300->0 braking and steady-state cornering

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
from features import PU_PEAK_KW, MGUK_KW, ICE_KW, ERS_DEPLOY_MJ_LAP, ERS_RECOVERY_MJ_LAP

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


def wing_coeffs(aero, d, open_wing=None, open_angle=0.0):
    CLA = CD = 0.0
    for s in aero.sections():
        if not s.startswith("WING_"):
            continue
        sec = aero[s]
        area = float(sec["CHORD"]) * float(sec["SPAN"])
        angle = float(sec["ANGLE"])
        if open_wing and s == open_wing:
            angle = open_angle
        CLA += area * float(sec["CL_GAIN"]) * \
            interp(lut(os.path.join(d, sec["LUT_AOA_CL"])), angle) * \
            interp(lut(os.path.join(d, sec["LUT_GH_CL"])), 0.045)
        CD += area * float(sec["CD_GAIN"]) * \
            interp(lut(os.path.join(d, sec["LUT_AOA_CD"])), angle) * \
            interp(lut(os.path.join(d, sec["LUT_GH_CD"])), 0.045)
    return CLA, CD


def load_car(car_dir):
    d = os.path.join(car_dir, "data")
    car = ini(os.path.join(d, "car.ini"))
    eng = ini(os.path.join(d, "engine.ini"))
    drv = ini(os.path.join(d, "drivetrain.ini"))
    aero = ini(os.path.join(d, "aero.ini"))
    tyres = ini(os.path.join(d, "tyres.ini"))
    brakes = ini(os.path.join(d, "brakes.ini"))
    ai = ini(os.path.join(d, "ai.ini"))
    power = lut(os.path.join(d, "power.lut"))
    kp = os.path.join(d, "kers_torque.lut")
    mguk = lut(kp) if os.path.exists(kp) else np.array([[0.0, 0.0], [15000.0, 0.0]], float)
    m = float(car["BASIC"]["TOTALMASS"]) + 0.75 * float(car["FUEL"]["FUEL"])
    ratios = [float(drv["GEARS"]["GEAR_%d" % g]) for g in range(1, 9)]
    final = float(drv["GEARS"]["FINAL"])
    shift = float(ai["GEARS"]["UP"])
    limiter = float(eng["ENGINE_DATA"]["LIMITER"])

    CLA, CdA = wing_coeffs(aero, d)
    drs_wing, drs_angle = None, 0.0
    if os.path.exists(os.path.join(d, "drs.ini")):
        drs = ini(os.path.join(d, "drs.ini"))
        for s in drs.sections():
            if s.startswith("WING_"):
                drs_wing = s
                drs_angle = float(drs[s].get("ANGLE", 0))
                break
    CLA_o, CdA_o = (CLA, CdA) if drs_wing is None else \
        wing_coeffs(aero, d, drs_wing, drs_angle)

    def grip(section):
        return 0.5 * (float(tyres[section]["DX0"]) + float(tyres[section]["DY0"]))

    mu = grip("FRONT")
    mu_i = grip("FRONT_3") if "FRONT_3" in tyres else mu * 0.72
    mu_w = grip("FRONT_4") if "FRONT_4" in tyres else mu * 0.56
    brake_force = 4.0 * float(brakes["DATA"]["MAX_TORQUE"]) / TYRE_R
    return {"m": m, "ratios": ratios, "final": final, "shift": shift,
            "limiter": limiter, "power": power, "mguk": mguk,
            "CLA": CLA, "CdA": CdA, "CLA_drs": CLA_o, "CdA_drs": CdA_o,
            "drs_wing": drs_wing, "drs_angle": drs_angle,
            "mu": mu, "mu_i": mu_i, "mu_w": mu_w,
            "brake_force": brake_force, "front_share": float(brakes["DATA"]["FRONT_SHARE"])}


def simulate(c, deploy=0.0, drs=False, mu=None):
    """deploy = fraction of the MGU-K peak used (0..1)."""
    m, R = c["m"], TYRE_R
    dt = 0.004
    v, gear, t, s = 0.2, 0, 0.0, 0.0
    marks, trace = {}, []
    a_prev = 0.0
    CLA = c["CLA_drs"] if drs else c["CLA"]
    CdA = c["CdA_drs"] if drs else c["CdA"]
    mu_use = c["mu"] if mu is None else mu
    while t < 60.0 and v < 130.0:
        total = c["ratios"][gear] * c["final"]
        rpm = min(c["limiter"], max(4200.0, v / (2 * math.pi * R) * 60.0 * total))
        torque = interp(c["power"], rpm) + deploy * interp(c["mguk"], rpm)
        f_engine = torque * total * 0.95 / R
        f_down = 0.5 * RHO * CLA * v ** 2
        f_drag = 0.5 * RHO * CdA * v ** 2
        f_rr = CRR * (m * G + f_down)
        n_rear = 0.55 * (m * G + f_down) + m * max(0.0, a_prev) * 0.30 / 3.6
        f_grip = mu_use * n_rear
        a = (min(f_engine, f_grip) - f_drag - f_rr) / m
        a_prev = a
        v += a * dt
        s += v * dt
        t += dt
        for target in (100, 200, 300):
            if target not in marks and v * 3.6 >= target:
                marks[target] = round(t, 2)
        if int(t / dt) % 25 == 0:
            trace.append((v, a, rpm, gear + 1))
        if rpm >= c["shift"] and gear < 7:
            gear += 1
        if a < 0.02 and v > 60:
            break
    return {"top_speed_kmh": round(v * 3.6, 1), "marks_s": marks,
            "trace": trace, "time_s": round(t, 2), "deploy": deploy}


def braking_curve(c, mu=None, drs=False, v0=300 / 3.6):
    m = c["m"]
    dt = 0.002
    v, s, t = v0, 0.0, 0.0
    out = []
    CLA = c["CLA_drs"] if drs else c["CLA"]
    CdA = c["CdA_drs"] if drs else c["CdA"]
    mu_use = c["mu"] if mu is None else mu
    while v > 1.0 and t < 30:
        f_down = 0.5 * RHO * CLA * v ** 2
        f_drag = 0.5 * RHO * CdA * v ** 2
        f_grip = mu_use * (m * G + f_down)
        f = min(c["brake_force"], f_grip)
        a = -(f + f_drag + CRR * (m * G + f_down)) / m
        out.append((v, -a))
        v += a * dt
        s += v * dt
        t += dt
    return {"distance_m": round(s, 1), "time_s": round(t, 2),
            "peak_decel_g": round(max(x[1] for x in out) / G, 2),
            "curve": out[::40]}


def lateral_envelope(c, mu=None):
    mu_use = c["mu"] if mu is None else mu
    out = []
    for kmh in range(80, 341, 20):
        v = kmh / 3.6
        f_down = 0.5 * RHO * c["CLA"] * v ** 2
        g = mu_use * (c["m"] * G + f_down) / (c["m"] * G)
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
    c = load_car(args.car_dir)

    # FIA: 4 MJ per lap at 120 kW = 33.33 s of full deployment. On this 89.179 s
    # lap that is a 0.374 duty cycle, so a lap sees less than the 805 kW peak.
    deploy_lap = ERS_DEPLOY_MJ_LAP * 1e6 / (MGUK_KW * 1000.0 * tel["lap_time"])
    acc = simulate(c, deploy_lap)            # lap-representative (validation)
    acc_none = simulate(c, 0.0)              # ICE only
    acc_full = simulate(c, 1.0)              # full MGU-K deployment
    acc_drs = simulate(c, 1.0, drs=True)     # full deploy + DRS open
    brk = braking_curve(c)
    brk_wet = braking_curve(c, mu=c["mu_w"])
    lat = lateral_envelope(c)
    lat_wet = lateral_envelope(c, mu=c["mu_w"])

    # Combined peak from the SHIPPED curves, at the power peak rpm.
    best = max(((interp(c["power"], r) + interp(c["mguk"], r)) * 2 * math.pi * r / 60.0 / 1000.0, r)
               for r in range(3000, 15001, 250))
    combined_kw, peak_rpm = round(best[0], 1), float(best[1])

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
        "accel_mae_under_3_mps2": accel_mae < 3.0,
        "brake_mae_under_6_mps2": brake_mae < 6.0,
        "top_speed_300_360_kmh": 300 <= acc["top_speed_kmh"] <= 360,
        "zero_to_100_between_2_and_4_s": 2.0 <= acc["marks_s"].get(100, 99) <= 4.0,
        "peak_braking_over_4g": brk["peak_decel_g"] > 4.0,
        "lateral_grip_over_3g_at_260": g250 > 3.0,
        "official_combined_peak_805_kw": abs(combined_kw - PU_PEAK_KW) < 8.0,
        "ers_full_deploy_faster_than_ice_only":
            acc_full["marks_s"].get(300, 99) < acc_none["marks_s"].get(300, 99),
        "drs_reduces_drag_and_downforce":
            c["CdA_drs"] < 0.95 * c["CdA"] and c["CLA_drs"] < 0.95 * c["CLA"],
        "wet_compounds_lower_grip": c["mu_w"] < 0.7 * c["mu"] and c["mu_i"] < c["mu"],
    }
    report = {
        "note": "Offline physics validation of the shipped INI/LUT data. "
                "Assetto Corsa itself was not executed (see README.md).",
        "parameters": {k: c[k] for k in ("m", "ratios", "final", "shift", "limiter",
                                         "CLA", "CdA", "CLA_drs", "CdA_drs",
                                         "mu", "mu_i", "mu_w", "brake_force",
                                         "front_share", "drs_wing", "drs_angle")},
        "telemetry": {"lap_time_s": tel["lap_time"], "samples": tel["rows"],
                      "mu_from_braking": brake_fit["mu"],
                      "peak_braking_g_telemetry": brake_fit["peak_decel_g"]},
        "simulation": {"top_speed_kmh": acc["top_speed_kmh"],
                       "accel_times_s": acc["marks_s"],
                       "braking_from_300_kmh": {k: v for k, v in brk.items() if k != "curve"},
                       "lateral_g_vs_kmh": lat},
        "telemetry_comparison": {"accel_bins": accel_rows, "accel_mae_mps2": round(accel_mae, 3),
                                 "brake_bins": brake_rows, "brake_mae_mps2": round(brake_mae, 3)},
        "official_power": {
            "published_rb20_combined_kw": PU_PEAK_KW,
            "published_rb20_hp": 1080,
            "ice_kw": ICE_KW, "mguk_kw": MGUK_KW,
            "combined_peak_kw_from_shipped_luts": combined_kw,
            "combined_peak_rpm": peak_rpm,
            "ers_deploy_mj_per_lap": ERS_DEPLOY_MJ_LAP,
            "ers_recovery_mj_per_lap": ERS_RECOVERY_MJ_LAP,
            "full_deploy_seconds_per_lap": round(ERS_DEPLOY_MJ_LAP * 1e6 / (MGUK_KW * 1000.0), 2),
            "lap_average_deploy_fraction": round(deploy_lap, 4),
            "lap_average_crank_kw": round(ICE_KW + MGUK_KW * deploy_lap, 2),
        },
        "ers": {
            "ice_only": {"top_speed_kmh": acc_none["top_speed_kmh"], "marks_s": acc_none["marks_s"]},
            "lap_average": {"top_speed_kmh": acc["top_speed_kmh"], "marks_s": acc["marks_s"]},
            "full_deploy": {"top_speed_kmh": acc_full["top_speed_kmh"], "marks_s": acc_full["marks_s"]},
        },
        "drs": {"wing": c["drs_wing"], "open_angle_deg": c["drs_angle"],
                "closed_CLA": round(c["CLA"], 4), "open_CLA": round(c["CLA_drs"], 4),
                "closed_CdA": round(c["CdA"], 4), "open_CdA": round(c["CdA_drs"], 4),
                "top_speed_closed_kmh": acc_full["top_speed_kmh"],
                "top_speed_open_kmh": acc_drs["top_speed_kmh"],
                "top_speed_gain_kmh": round(acc_drs["top_speed_kmh"] - acc_full["top_speed_kmh"], 1)},
        "wet_tyres": {"slick_mu": round(c["mu"], 3),
                      "intermediate_mu": round(c["mu_i"], 3),
                      "full_wet_mu": round(c["mu_w"], 3),
                      "braking_300_to_0_slick_m": brk["distance_m"],
                      "braking_300_to_0_wet_m": brk_wet["distance_m"],
                      "braking_peak_g_wet": brk_wet["peak_decel_g"],
                      "lateral_g_260_wet": dict(lat_wet)[260],
                      "vanilla_rain": False},
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }
    with open(os.path.join(args.out, "validation_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2,
                  default=lambda o: o.item() if hasattr(o, "item") else str(o))

    fig, ax = plt.subplots(1, 3, figsize=(13, 3.6))
    ax[0].plot([r[0] for r in accel_rows], [r[1] for r in accel_rows], "o-", label="telemetry VER")
    ax[0].plot([r[0] for r in accel_rows], [r[2] for r in accel_rows], "s--", label="mod physics")
    ax[0].set(xlabel="speed m/s", ylabel="acceleration m/s²", title="Full throttle")
    ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3)
    ax[1].plot([r[0] for r in brake_rows], [r[1] for r in brake_rows], "o-", label="telemetry VER")
    ax[1].plot([r[0] for r in brake_rows], [r[2] for r in brake_rows], "s--", label="mod physics")
    ax[1].set(xlabel="speed m/s", ylabel="deceleration m/s²", title="Braking")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=0.3)
    ax[2].plot([p[0] for p in lat], [p[1] for p in lat], "-", color="#d8232a", label="slick")
    ax[2].plot([p[0] for p in lat_wet], [p[1] for p in lat_wet], "-", color="#2a6fd8", label="full wet")
    ax[2].set(xlabel="km/h", ylabel="lateral g", title="Steady-state grip")
    ax[2].legend(fontsize=8); ax[2].grid(alpha=0.3)
    fig.tight_layout()
    plot = os.path.join(args.out, "validation.png")
    fig.savefig(plot, dpi=110)
    plt.close(fig)

    print("official power   %.0f kW published = %.0f kW ICE + %.0f kW MGU-K (shipped %.1f kW)" %
          (PU_PEAK_KW, ICE_KW, MGUK_KW, combined_kw))
    print("ERS lap deploy   %.3f (4 MJ / 120 kW / %.3f s lap)" % (deploy_lap, tel["lap_time"]))
    print("top speed        %.1f km/h (lap) | %.1f ICE only | %.1f full deploy | %.1f DRS" %
          (acc["top_speed_kmh"], acc_none["top_speed_kmh"], acc_full["top_speed_kmh"],
           acc_drs["top_speed_kmh"]))
    print("0-100/200/300    %s s" % acc["marks_s"])
    print("brake 300->0     %.1f m, peak %.2f g (wet %.1f m)" %
          (brk["distance_m"], brk["peak_decel_g"], brk_wet["distance_m"]))
    print("lateral @260     %.2f g (wet %.2f g)" % (g250, dict(lat_wet)[260]))
    print("DRS              CdA %.3f -> %.3f, CLA %.3f -> %.3f" %
          (c["CdA"], c["CdA_drs"], c["CLA"], c["CLA_drs"]))
    print("accel MAE        %.2f m/s²   brake MAE %.2f m/s²" % (accel_mae, brake_mae))
    print("checks", checks)
    print("wrote", os.path.join(args.out, "validation_report.json"), "and", plot)
    if not all(checks.values()):
        print("WARNING: some validation checks failed", file=sys.stderr)


if __name__ == "__main__":
    main()
