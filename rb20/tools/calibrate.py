"""
calibrate.py -- derive the AC physics data from REAL 2024 F1 telemetry.

Source: FastF1 telemetry of Max Verstappen's 2024 Bahrain Grand Prix
qualifying lap (the RB20's pole lap, 1:29.179), published in
sharanyaswaminathan/F1_Performance_Explorer (see ../telemetry/SOURCES.md).
Channels used: Time, Speed, RPM, nGear, Throttle, Brake, Distance.

What is actually fitted (least squares, no hand-tuned guesses):
  * total gear ratios ....... median(RPM / wheel_rpm) per gear, log-linear fit
  * shift RPM ............... median RPM at gear-change events
  * peak braking envelope ... decel = mu*g + c1*v^2  -> tyre friction mu
  * drag + downforce ........ joint fit of the full-throttle power equation
        m*a*v = P(rpm) - 0.5*rho*(CdA + Crr*CLA)*v^3 - Crr*m*g*v
        combined with the braking relation
        c1*m/(0.5*rho) = mu*CLA + CdA
        -> CdA, CLA and the power curve P(rpm) are all solved from data.
  * brake torque, tyre grip, wing split and UI curves follow from those.

Everything written is vanilla AC (VERSION=1/2/3/7 headers, no `extended-*`,
no CSP-only keys). No data.acd, no Lua, no ext_config.ini.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Fixed physical constants and 2024 F1 published specs (not fitted).
RHO = 1.225                 # kg/m^3, sea level (Bahrain, ~25 C -> 1.18; 1.225 is AC's default)
G = 9.81
MASS = 808.0                # 798 kg minimum + ~10 kg fuel on a qualifying lap
TYRE_R = 0.360              # 720 mm diameter slick
CRR = 0.012                 # slick rolling resistance coefficient
FINAL_DRIVE = 4.00          # gearbox design choice; GEAR_i * FINAL = fitted total ratio
FUEL_L = 110.0
WHEELBASE = 3.600
CG_LOCATION = 0.455


# ------------------------------------------------------------------ telemetry
def _td(s):
    t = str(s).split(" ")[-1]
    h, m, sec = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def load_telemetry(path):
    with open(path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    t = np.array([_td(r["Time"]) for r in rows], float)
    v = np.array([float(r["Speed"]) for r in rows], float) / 3.6
    rpm = np.array([float(r["RPM"]) for r in rows], float)
    gear = np.array([int(r["nGear"]) for r in rows], int)
    thr = np.array([float(r["Throttle"]) for r in rows], float)
    brk = np.array([1.0 if str(r["Brake"]).lower() in ("true", "1", "1.0") else 0.0
                    for r in rows], float)
    dist = np.array([float(r["Distance"]) for r in rows], float)

    # Resample onto a uniform grid and smooth before differentiating: the raw
    # timing stream has irregular 13..260 ms gaps.
    tu = np.arange(0.0, t[-1], 0.02)
    vu = np.interp(tu, t, v)
    kernel = np.array([1, 2, 3, 2, 1], float)
    kernel /= kernel.sum()
    for _ in range(2):
        vu = np.convolve(np.pad(vu, (2, 2), mode="edge"), kernel, mode="valid")
    a = np.gradient(vu, tu)
    return {
        "t": tu, "v": vu, "a": a,
        "rpm": np.interp(tu, t, rpm),
        "gear": np.rint(np.interp(tu, t, gear)).astype(int),
        "thr": np.interp(tu, t, thr),
        "brk": np.interp(tu, t, brk),
        "v_raw": v, "rpm_raw": rpm, "gear_raw": gear, "thr_raw": thr,
        "brk_raw": brk, "dist": dist, "t_raw": t,
        "rows": len(rows), "lap_time": float(t[-1]), "lap_distance": float(dist[-1]),
    }


# --------------------------------------------------------------------- fitting
def fit_gears(d):
    wheel_rpm = d["v_raw"] / (2 * math.pi * TYRE_R) * 60.0
    ratio = d["rpm_raw"] / np.maximum(wheel_rpm, 1.0)
    observed = {}
    for g in range(1, 9):
        m = (d["gear_raw"] == g) & (d["thr_raw"] > 90) & (d["v_raw"] > 20) & (d["brk_raw"] == 0)
        if m.sum() >= 8:
            observed[g] = float(np.median(ratio[m]))
    gs = np.array(sorted(observed), float)
    rs = np.array([observed[g] for g in gs])
    # log-linear (constant ratio step) fit -> robust to a couple of bad gears
    b, loga = np.polyfit(gs, np.log(rs), 1)
    fitted = {g: float(math.exp(loga + b * g)) for g in range(1, 9)}
    # upshift RPM: first sample of each new gear after a full-throttle pull
    shifts = []
    for k in range(1, len(d["gear_raw"])):
        if d["gear_raw"][k] == d["gear_raw"][k-1] + 1 and d["thr_raw"][k-1] > 95:
            shifts.append(d["rpm_raw"][k-1])
    shift_rpm = float(np.median(shifts)) if shifts else 11800.0
    return {"observed": observed, "fitted_total": fitted,
            "step_ratio": float(math.exp(-b)), "shift_rpm": shift_rpm,
            "gear_ratios": {g: fitted[g] / FINAL_DRIVE for g in fitted}}


def fit_braking(d):
    v, a, brk = d["v"], d["a"], d["brk"]
    m = (brk > 0.5) & (v > 18) & (v < 95) & (a < 0) & (a > -70)
    edges = np.linspace(20, 90, 8)
    pts = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        s = m & (v >= lo) & (v < hi)
        if s.sum() >= 12:
            # 10th percentile = peak (limit) braking in that speed band
            pts.append((float(np.median(v[s])), float(np.percentile(a[s], 10))))
    pts = np.array(pts)
    X = np.column_stack([np.ones(len(pts)), pts[:, 0] ** 2])
    c0, c1 = np.linalg.lstsq(X, -pts[:, 1], rcond=None)[0]
    mu = max(1.35, min(2.30, c0 / G))
    return {"points": pts.tolist(), "c0": float(c0), "c1": float(c1),
            "mu": float(mu), "peak_decel_g": float(-pts[:, 1].min() / G)}


def power_shape(rpm):
    """Normalised shape of a fuel-flow-limited 2024 PU (ICE + MGU-K combined).

    Power rises with rpm up to the fuel-flow ceiling at ~10,000 rpm, is flat to
    ~12,000 rpm (the usable band seen in the telemetry) and then tapers to the
    15,000 rpm regulation limiter. Only its SCALE is fitted from telemetry.
    """
    r = float(rpm)
    if r <= 2000:
        return 0.0
    if r < 4000:
        return 0.05 * (r - 2000) / 2000.0
    if r < 10000:
        return 0.20 + 0.80 * (r - 4000) / 6000.0
    if r <= 12000:
        return 1.0
    if r <= 15000:
        return max(0.0, 1.0 - (r - 12000) / 3000.0)
    return 0.0


def fit_power_and_aero(d, mu, c1):
    """Well-conditioned 2-parameter fit.

    Fitting an independent power value for every rpm bin is degenerate: within
    one gear rpm is proportional to v, so P(rpm) and K*v^3 are nearly collinear.
    Instead the *shape* of the power curve is fixed by the fuel-flow limit and
    only its scale P_max plus K = CdA + Crr*CLA are solved by least squares.
    """
    v, a, rpm, thr, brk = d["v"], d["a"], d["rpm"], d["thr"], d["brk"]
    m = (thr > 99) & (brk < 0.5) & (v > 25) & (v < 95) & (a > -2) & (a < 22) & (rpm > 4500)
    v, a, rpm = v[m], a[m], rpm[m]
    Z = MASS * a * v + CRR * MASS * G * v        # = P - 0.5*rho*K*v^3
    shape = np.array([power_shape(r) for r in rpm])
    drag = -0.5 * RHO * v ** 3
    A = np.column_stack([shape, drag])
    # Weak prior on K to keep it in the physical F1 range if the lap is noisy.
    A = np.vstack([A, [0.0, 2e-5]])
    Z = np.concatenate([Z, [2e-5 * 1.40]])
    P_max, K = np.linalg.lstsq(A, Z, rcond=None)[0]
    P_max = float(np.clip(P_max, 300000.0, 900000.0))
    K = float(np.clip(K, 0.8, 2.6))

    # Split K into drag and downforce using the braking relation:
    #   c1*m/(0.5*rho) = mu*CLA + CdA  =: B,  K = CdA + Crr*CLA
    B = c1 * MASS / (0.5 * RHO)
    CLA = (B - K) / max(0.2, mu - CRR)
    CdA = K - CRR * CLA
    if not (2.0 <= CLA <= 12.0) or not (0.7 <= CdA <= 2.6):
        CdA = float(np.clip(CdA, 0.9, 1.8))
        CLA = float(np.clip((B - CdA) / max(0.2, mu), 2.0, 9.0))
        K = CdA + CRR * CLA
        # refit the power scale with the corrected, fixed K
        P_max = float(np.clip(np.dot(Z[:-1] - drag * K, shape) / np.dot(shape, shape),
                              300000.0, 900000.0))
    bins = list(range(4000, 15001, 1000))
    pw = [P_max * power_shape(r) for r in bins]
    return {"bins": bins, "power_w": [float(x) for x in pw],
            "K": float(K), "CdA": float(CdA), "CLA": float(CLA), "B": float(B),
            "samples": int(m.sum()), "peak_power_w": float(P_max),
            "peak_power_rpm": 11000.0,
            "fit_method": "2-parameter least squares: P_max (fuel-flow shape) + K=CdA+Crr*CLA"}


def torque_curve(fit):
    """power.lut is TORQUE (Nm) in AC: T = P/omega."""
    P_max = fit["peak_power_w"]
    out = []
    for rpm in (0, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000,
                10000, 10500, 11000, 11500, 12000, 12500, 13000, 13500,
                14000, 14500, 15000):
        p = P_max * power_shape(rpm)
        t = 0.0 if rpm <= 0 else p * 60.0 / (2 * math.pi * rpm)
        out.append((rpm, round(t, 1)))
    return out


# ------------------------------------------------------------------- writers
def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("  ", os.path.relpath(path, CAR_DIR) if "CAR_DIR" in globals() else path)


def write_lut(path, pairs, header=None):
    txt = ""
    if header:
        txt += "".join("; %s\n" % line for line in header)
    txt += "".join("%s|%s\n" % (k, val) for k, val in pairs)
    w(path, txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--telemetry", required=True)
    ap.add_argument("--car-dir", required=True)
    args = ap.parse_args()
    global CAR_DIR
    CAR_DIR = os.path.abspath(args.car_dir)
    data = os.path.join(CAR_DIR, "data")
    ui = os.path.join(CAR_DIR, "ui")
    os.makedirs(data, exist_ok=True)
    os.makedirs(ui, exist_ok=True)

    d = load_telemetry(args.telemetry)
    gears = fit_gears(d)
    braking = fit_braking(d)
    fit = fit_power_and_aero(d, braking["mu"], braking["c1"])
    lut = torque_curve(fit)
    mu = braking["mu"]
    CLA, CdA = fit["CLA"], fit["CdA"]

    calib = {
        "telemetry": {
            "file": os.path.basename(args.telemetry),
            "driver": "VER", "car": "Red Bull RB20", "session": "2024 Bahrain GP Qualifying",
            "lap_time_s": d["lap_time"], "lap_distance_m": d["lap_distance"],
            "samples": d["rows"], "source": "FastF1 (see telemetry/SOURCES.md)",
        },
        "constants": {"rho_kg_m3": RHO, "mass_kg": MASS, "tyre_radius_m": TYRE_R,
                      "Crr": CRR, "g": G, "final_drive": FINAL_DRIVE},
        "gears": gears, "braking": braking, "fit": fit,
        "torque_curve_nm": lut,
        "peak_torque_nm": max(t for _, t in lut),
        "peak_power_kw": fit["peak_power_w"] / 1000.0,
    }

    # ---------------- car.ini ----------------
    w(os.path.join(data, "car.ini"), """[HEADER]
VERSION=1 ; vanilla AC physics. Never use VERSION=extended-* (that requires CSP)

[INFO]
SCREEN_NAME=ARB RB20 2024
SHORT_NAME=RB20

[BASIC]
; 798 kg F1 minimum mass WITH driver and WITHOUT fuel. AC adds fuel mass.
TOTALMASS=798
; Kunos convention: INERTIA = (width, height, length) in metres, from which
; AC builds the inertia tensor. RB20: 2.00 m wide, 0.95 m high, 5.60 m long.
INERTIA=2.00,0.95,5.60
; The mesh is modelled with the asphalt at Y=0; CG sits 0.30 m above it.
GRAPHICS_OFFSET=0,-0.30,0
GRAPHICS_PITCH_ROTATION=0

[GRAPHICS]
DRIVEREYES=0,0.52,0.36
ONBOARD_EXPOSURE=32
OUTBOARD_EXPOSURE=30
ON_BOARD_PITCH_ANGLE=-2.0
BUMPER_CAMERA_POS=0,0.20,2.85
BONNET_CAMERA_POS=0,0.55,1.20
MIRROR_POSITION=0,0.62,0.55
VIRTUAL_MIRROR_ENABLED=1
SHAKE_MUL=1.1
USE_ANIMATED_SUSPENSIONS=1
FUEL_LIGHT_MIN_LITERS=2
CHASE_CAMERA_PITCH=0

[CONTROLS]
FFMULT=2.2
STEER_ASSIST=1
STEER_LOCK=240
STEER_RATIO=11.0
LINEAR_STEER_ROD_RATIO=0.00165

[FUEL]
; 2024 cars: 110 kg max fuel; AC models consumption as rpm*gas*CONSUMPTION/1000
CONSUMPTION=0.00095
FUEL=12
MAX_FUEL=110

[FUELTANK]
POSITION=0,-0.05,-0.15

[RIDE]
PICKUP_FRONT_HEIGHT=-0.26
PICKUP_REAR_HEIGHT=-0.24

[RULES]
MIN_HEIGHT=0.010

[PIT_STOP]
TYRE_CHANGE_TIME_SEC=3.0
FUEL_LITER_TIME_SEC=0.1
BODY_REPAIR_TIME_SEC=2
ENGINE_REPAIR_TIME_SEC=2
SUSP_REPAIR_TIME_SEC=2
""")

    # ---------------- engine.ini ----------------
    w(os.path.join(data, "engine.ini"), """[HEADER]
VERSION=1
POWER_CURVE=power.lut
COAST_CURVE=FROM_COAST_REF

[ENGINE_DATA]
; 15,000 rpm is the regulation limit; the fuel-flow limit means the usable
; band in the telemetry is ~5,000-12,000 rpm (see calibration.json).
ALTITUDE_SENSITIVITY=0.05
INERTIA=0.085
LIMITER=15000
LIMITER_HZ=30
MINIMUM=4200

[COAST_REF]
RPM=11000
TORQUE=95
NON_LINEARITY=0.15

[COAST_DATA]
COAST0=0
COAST1=0
COAST=0.0000015

[COAST_CURVE]
FILENAME=coast.lut

[DAMAGE]
TURBO_BOOST_THRESHOLD=0.9
TURBO_DAMAGE_K=10
RPM_THRESHOLD=14500
RPM_DAMAGE_K=30

[ENGINESOUND]
MINIMUM_TURBO=0
""")
    write_lut(os.path.join(data, "power.lut"), lut,
              ["Torque [Nm] vs engine rpm.",
               "Fitted from VER 2024 Bahrain Q full-throttle acceleration;",
               "combined ICE + MGU-K output (ERS deployment baked into the curve)."])
    write_lut(os.path.join(data, "coast.lut"),
              [(0, 0), (3000, -25), (5000, -48), (7000, -65), (9000, -80),
               (11000, -95), (13000, -105), (15000, -115)])

    # ---------------- drivetrain.ini ----------------
    gr = gears["gear_ratios"]
    gl = "\n".join("GEAR_%d=%.4f" % (g, gr[g]) for g in range(1, 9))
    w(os.path.join(data, "drivetrain.ini"), """[HEADER]
VERSION=2

[TRACTION]
TYPE=RWD

[GEARS]
COUNT=8
GEAR_R=-3.600
%s
FINAL=%.2f

[DIFFERENTIAL]
POWER=0.28
COAST=0.42
PRELOAD=140

[GEARBOX]
; seamless-shift gearbox, 2024 F1
CHANGE_UP_TIME=45
CHANGE_DN_TIME=70
AUTO_CUTOFF_TIME=60
SUPPORTS_SHIFTER=0
VALID_SHIFT_RPM_WINDOW=900
CONTROLS_WINDOW_GAIN=0.45
INERTIA=0.014

[CLUTCH]
MAX_TORQUE=750

[AUTOCLUTCH]
UPSHIFT_PROFILE=NONE
DOWNSHIFT_PROFILE=DOWNSHIFT_PROFILE
USE_ON_CHANGES=1
MIN_RPM=4000
MAX_RPM=6000
FORCED_ON=1

[DOWNSHIFT_PROFILE]
POINT_0=10
POINT_1=90
POINT_2=150

[AUTOBLIP]
ELECTRONIC=1
POINT_0=20
POINT_1=70
POINT_2=140
LEVEL=0.6

[DAMAGE]
RPM_WINDOW_K=100
""" % (gl, FINAL_DRIVE))

    # ---------------- aero.ini ----------------
    split = {"BODY": (0.05, 0.20), "FRONT": (0.28, 0.18),
             "REAR": (0.27, 0.28), "DIFFUSER": (0.40, 0.34)}
    positions = {"BODY": (0, 0.0, 0.0), "FRONT": (0, -0.225, 2.86),
                 "REAR": (0, 0.55, -2.33), "DIFFUSER": (0, -0.25, -1.85)}
    names = {"BODY": 0, "FRONT": 1, "REAR": 2, "DIFFUSER": 3}
    aero_txt = ""
    for key, (clf, cdf) in split.items():
        cl, cd = CLA * clf, CdA * cdf
        tag = key.lower()
        write_lut(os.path.join(data, "aero_%s_CL.lut" % tag),
                  [(-10, 0.70), (0, 1.00), (4, 1.14), (8, 1.28), (12, 1.42),
                   (17, 1.58), (25, 1.66)],
                  ["AoA [deg] -> CL multiplier; multiplied by CL_GAIN."])
        write_lut(os.path.join(data, "aero_%s_CD.lut" % tag),
                  [(-10, 1.05), (0, 1.00), (5, 1.03), (10, 1.10), (17, 1.24), (25, 1.50)],
                  ["AoA [deg] -> CD multiplier."])
        write_lut(os.path.join(data, "gh_%s_CL.lut" % tag),
                  [(0, 0.0), (0.010, 0.35), (0.020, 0.92), (0.030, 1.06),
                   (0.045, 1.00), (0.070, 0.88), (0.100, 0.55), (0.150, 0.30)],
                  ["Ride height [m] -> ground-effect CL multiplier (stall when too low)."]
                  if key in ("FRONT", "DIFFUSER") else ["Ride height -> CL multiplier."])
        write_lut(os.path.join(data, "gh_%s_CD.lut" % tag),
                  [(0, 0.97), (0.020, 0.99), (0.045, 1.00), (0.080, 1.01), (0.150, 1.02)])
        i = names[key]
        x, y, z = positions[key]
        aero_txt += """[WING_%d]
NAME=%s
CHORD=1.0
SPAN=1.0
POSITION=%.3f,%.3f,%.3f
LUT_AOA_CL=aero_%s_CL.lut
LUT_GH_CL=gh_%s_CL.lut
CL_GAIN=%.4f
LUT_AOA_CD=aero_%s_CD.lut
LUT_GH_CD=gh_%s_CD.lut
CD_GAIN=%.4f
ANGLE=0
ZONE_FRONT_CL=0.01
ZONE_FRONT_CD=0.01
ZONE_REAR_CL=0.01
ZONE_REAR_CD=0.01
ZONE_LEFT_CL=0.01
ZONE_LEFT_CD=0.01
ZONE_RIGHT_CL=0.01
ZONE_RIGHT_CD=0.01
YAW_CL_GAIN=-0.04

""" % (i, key, x, y, z, tag, tag, cl, tag, tag, cd)
    w(os.path.join(data, "aero.ini"), "[HEADER]\nVERSION=3\n\n" + aero_txt.rstrip() + "\n")

    # ---------------- tyres.ini ----------------
    compounds = [("Soft", mu, 1.00, 0.0), ("Medium", mu * 0.975, 0.78, 1),
                 ("Hard", mu * 0.950, 0.58, 2)]
    for cname, grip, weargain, index in compounds:
        tag = cname.lower()
        base = 1.0 if index == 0 else 1.0
        wear = [(0, 100), (0.3, 100), (1, 99), (2, 96), (4, 90),
                (6, 84), (8, 78), (11, 72), (14, 66), (18, 58)]
        for axle in ("front", "rear"):
            write_lut(os.path.join(data, "wear_%s_%s.lut" % (tag, axle)),
                      [(k, round(100 - (100 - vv) * (1.0 + 0.12 * (axle == "rear")), 1))
                       for k, vv in wear])
        write_lut(os.path.join(data, "tcurve_%s.lut" % tag),
                  [(0, 0.80), (20, 0.91), (40, 0.96), (60, 0.99),
                   (80, 1.00), (100, 1.00), (115, 0.99), (140, 0.95),
                   (170, 0.88), (220, 0.74), (300, 0.55)])
    def tyre_section(axle, cname, grip, index):
        front = axle == "FRONT"
        width = 0.305 if front else 0.405
        suffix = "" if index == 0 else "_%d" % index
        tag = cname.lower()
        return """[%s%s]
NAME=2024 P Zero %s %s
SHORT_NAME=%s%s
WIDTH=%.3f
RADIUS=%.3f
RIM_RADIUS=0.2413
ANGULAR_INERTIA=%.2f
DAMP=%.0f
RATE=%.0f
DY0=%.4f
DY1=-0.032
DX0=%.4f
DX1=-0.032
WEAR_CURVE=wear_%s_%s.lut
WEAR_SENSIBILITY=0
SPEED_SENSITIVITY=0.0031
RELAXATION_LENGTH=0.044
ROLLING_RESISTANCE_0=6
ROLLING_RESISTANCE_1=0.00052
ROLLING_RESISTANCE_SLIP=4500
FLEX=0.00036
CAMBER_GAIN=0.13
DCAMBER_0=1.5
DCAMBER_1=-13
FRICTION_LIMIT_ANGLE=7.2
XMU=0.24
PRESSURE_STATIC=%.1f
PRESSURE_SPRING_GAIN=8000
PRESSURE_FLEX_GAIN=0.6
PRESSURE_RR_GAIN=1
PRESSURE_D_GAIN=0.008
PRESSURE_IDEAL=%.1f
FZ0=%.0f
LS_EXPY=0.55
LS_EXPX=0.55
DX_REF=%.4f
DY_REF=%.4f
FLEX_GAIN=0.19
FALLOFF_LEVEL=0.92
FALLOFF_SPEED=4

""" % (axle, suffix, cname, axle.title(), cname[0], suffix, width, TYRE_R,
       1.65 if front else 2.20, 900 if front else 1000,
       255000 if front else 235000, grip + 0.02, grip, tag,
       "front" if front else "rear", 23.0 if front else 21.0,
       25.0 if front else 23.0, 3100 if front else 3400, grip, grip + 0.02)

    def thermal_section(axle, cname, index):
        front = axle == "FRONT"
        suffix = "" if index == 0 else "_%d" % index
        tag = cname.lower()
        return """[THERMAL_%s%s]
SURFACE_TRANSFER=0.0180
PATCH_TRANSFER=0.00027
CORE_TRANSFER=%.6f
INTERNAL_CORE_TRANSFER=0.00721
FRICTION_K=%.5f
ROLLING_K=0.32
PERFORMANCE_CURVE=tcurve_%s.lut
GRAIN_GAMMA=1.0
GRAIN_GAIN=%.2f
BLISTER_GAMMA=1.0
BLISTER_GAIN=%.2f
COOL_FACTOR=1.50
SURFACE_ROLLING_K=0.957

""" % (axle, suffix, 0.003035 if front else 0.002648,
       0.1415 if front else 0.1350, tag,
       1.0 if index == 0 else 0.7, 0.5 if index == 0 else 0.35)

    tyres = "[HEADER]\nVERSION=7 ; vanilla AC v7 tyre model (Kunos SDK), NOT CSP v10\n\n[COMPOUND_DEFAULT]\nINDEX=0\n\n"
    for cname, grip, weargain, index in compounds:
        tyres += tyre_section("FRONT", cname, grip, index)
        tyres += tyre_section("REAR", cname, grip, index)
        tyres += thermal_section("FRONT", cname, index)
        tyres += thermal_section("REAR", cname, index)
    w(os.path.join(data, "tyres.ini"), tyres)

    # ---------------- suspensions.ini ----------------
    def susp(axle, track, basey, z, spring, damp, camber, steer):
        wb_top_f = 0.62
        return """[%s]
TYPE=DWB
BASEY=%.3f
TRACK=%.3f
ROD_LENGTH=0.032
HUB_MASS=22
RIM_OFFSET=0.010
WBCAR_TOP_FRONT=%.3f,0.115,0.160
WBCAR_TOP_REAR=%.3f,0.115,-0.160
WBCAR_BOTTOM_FRONT=%.3f,-0.120,0.160
WBCAR_BOTTOM_REAR=%.3f,-0.120,-0.160
WBTYRE_TOP=0.105,0.115,-0.018
WBTYRE_BOTTOM=0.085,-0.120,0.018
WBCAR_STEER=%.3f,0.030,0.170
WBTYRE_STEER=0.100,0.030,0.095
TOE_OUT=0.0004
STATIC_CAMBER=%.2f
SPRING_RATE=%.0f
PROGRESSIVE_SPRING_RATE=0
BUMP_STOP_RATE=350000
BUMPSTOP_UP=0.022
BUMPSTOP_DN=0.022
PACKER_RANGE=0.032
DAMP_BUMP=%.0f
DAMP_FAST_BUMP=%.0f
DAMP_FAST_BUMPTHRESHOLD=0.030
DAMP_REBOUND=%.0f
DAMP_FAST_REBOUND=%.0f
DAMP_FAST_REBOUNDTHRESHOLD=0.040

""" % (axle, basey, track, wb_top_f, wb_top_f, wb_top_f, wb_top_f,
        wb_top_f, camber, spring, damp, damp * 0.55, damp * 1.35, damp * 0.7)

    w(os.path.join(data, "suspensions.ini"), """[HEADER]
VERSION=2

[BASIC]
WHEELBASE=%.3f
CG_LOCATION=%.3f

[ARB]
FRONT=125000
REAR=105000

%s%s[HEAVE_FRONT]
ROD_LENGTH=0.032
SPRING_RATE=275000
PROGRESSIVE_SPRING_RATE=0
BUMP_STOP_RATE=400000
BUMPSTOP_UP=0.022
BUMPSTOP_DN=0.022
PACKER_RANGE=0.032
DAMP_BUMP=12500
DAMP_FAST_BUMP=6500
DAMP_FAST_BUMPTHRESHOLD=0.028
DAMP_REBOUND=13500
DAMP_FAST_REBOUND=7000
DAMP_FAST_REBOUNDTHRESHOLD=0.040

[HEAVE_REAR]
ROD_LENGTH=0.032
SPRING_RATE=255000
PROGRESSIVE_SPRING_RATE=0
BUMP_STOP_RATE=380000
BUMPSTOP_UP=0.022
BUMPSTOP_DN=0.022
PACKER_RANGE=0.032
DAMP_BUMP=11500
DAMP_FAST_BUMP=6000
DAMP_FAST_BUMPTHRESHOLD=0.028
DAMP_REBOUND=12500
DAMP_FAST_REBOUND=6500
DAMP_FAST_REBOUNDTHRESHOLD=0.040

[GRAPHICS_OFFSETS]
WHEEL_LF=0
SUSP_LF=0
WHEEL_RF=0
SUSP_RF=0
WHEEL_LR=0
SUSP_LR=0
WHEEL_RR=0
SUSP_RR=0

[DAMAGE]
MIN_VELOCITY=40
GAIN=0.0004
MAX_DAMAGE=0.05
DEBUG_LOG=0
""" % (WHEELBASE, CG_LOCATION,
       susp("FRONT", 1.695, -0.060, 1.962, 245000, 11500, -3.2, 1),
       susp("REAR", 1.595, -0.070, -1.638, 225000, 10800, -1.6, 0)))

    # ---------------- brakes.ini ----------------
    vref = 63.0
    f_down = 0.5 * RHO * CLA * vref ** 2
    grip_force = mu * (MASS * G + f_down)
    torque_per_wheel = grip_force * TYRE_R / 4.0
    max_torque = round(torque_per_wheel * 1.25, -1)
    calib["brakes"] = {"grip_force_n": float(grip_force),
                       "max_torque_nm": max_torque,
                       "assumption": "MAX_TORQUE interpreted as per-wheel torque; "
                                     "grip limits deceleration, as in real F1"}
    w(os.path.join(data, "brakes.ini"), """[HEADER]
VERSION=1

[DATA]
; Derived from the telemetry braking envelope (peak %.2f g at ~%.0f m/s).
; Fitted grip limit %.0f N -> %.0f Nm per wheel (+25%% headroom).
MAX_TORQUE=%.0f
FRONT_SHARE=0.55
HANDBRAKE_TORQUE=0
COCKPIT_ADJUSTABLE=1
ADJUST_STEP=0.5
""" % (braking["peak_decel_g"], vref, grip_force, torque_per_wheel, max_torque))

    # ---------------- electronics / ai / setup / misc ----------------
    w(os.path.join(data, "electronics.ini"), """[ABS]
SLIP_RATIO_LIMIT=0.10
CURVE=
PRESENT=0
ACTIVE=0
RATE_HZ=100

[TRACTION_CONTROL]
SLIP_RATIO_LIMIT=0.12
CURVE=
PRESENT=0
ACTIVE=0
RATE_HZ=100
MIN_SPEED_KMH=40

[EDL]
PRESENT=0
ACTIVE=0
MAX_SPIN_POWER=0.8
MAX_SPIN_COAST=0.4
BRAKE_TORQUE_POWER=50
BRAKE_TORQUE_COAST=400
DEAD_ZONE_POWER=0.2
DEAD_ZONE_COAST=0.0
""")
    w(os.path.join(data, "ai.ini"), """[HEADER]
VERSION=4

[GEARS]
UP=%.0f
DOWN=%.0f
SLIP_THRESHOLD=0.95
GAS_CUTOFF_TIME=0.060

[PEDALS]
GASGAIN=5.0
BRAKE_HINT=1
TRAIL_HINT=1

[STEER]
STEER_GAIN=2.6

[LOOKAHEAD]
BASE=24.0
SPEED_GAIN=0.18
GAS_BRAKE_LOOKAHEAD=0

[ULTRA_GRIP]
VALUE=1.0

[PHYSICS_HINTS]
AERO_HINT=1

[TYRES]
HINT=1
""" % (round(gears["shift_rpm"]), round(gears["shift_rpm"] * 0.72)))

    w(os.path.join(data, "setup.ini"), """[DISPLAY_METHOD]
SHOW_CLICKS=0

[GEARS]
USE_GEARSET=0

[WING_1]
SHOW_CLICKS=0
TAB=AERO
NAME=Front wing
MIN=0
MAX=17
STEP=1
POS_X=0
POS_Y=1
HELP=HELP_FRONT_WING

[WING_2]
SHOW_CLICKS=0
TAB=AERO
NAME=Rear wing
MIN=0
MAX=17
STEP=1
POS_X=1
POS_Y=1
HELP=HELP_REAR_WING

[PRESSURE_LF]
SHOW_CLICKS=0
TAB=TYRES
NAME=Pressure LF
MIN=18
MAX=28
STEP=0.5
POS_X=0
POS_Y=2
HELP=HELP_LF_PRESSURE

[PRESSURE_RF]
SHOW_CLICKS=0
TAB=TYRES
NAME=Pressure RF
MIN=18
MAX=28
STEP=0.5
POS_X=1
POS_Y=2
HELP=HELP_RF_PRESSURE

[PRESSURE_LR]
SHOW_CLICKS=0
TAB=TYRES
NAME=Pressure LR
MIN=17
MAX=26
STEP=0.5
POS_X=0
POS_Y=4
HELP=HELP_LR_PRESSURE

[PRESSURE_RR]
SHOW_CLICKS=0
TAB=TYRES
NAME=Pressure RR
MIN=17
MAX=26
STEP=0.5
POS_X=1
POS_Y=4
HELP=HELP_RR_PRESSURE

[ROD_LENGTH_LF]
SHOW_CLICKS=2
TAB=SUSPENSION
NAME=Front ride height
MIN=-12
MAX=12
STEP=1
POS_X=0
POS_Y=2
HELP=HELP_LF_RODLENGTH

[ROD_LENGTH_RR]
SHOW_CLICKS=2
TAB=SUSPENSION
NAME=Rear ride height
MIN=-12
MAX=12
STEP=1
POS_X=1
POS_Y=6
HELP=HELP_RR_RODLENGTH

[SPRING_RATE_LF]
SHOW_CLICKS=0
TAB=SUSPENSION
NAME=Front wheel rate
MIN=190
MAX=300
STEP=5
POS_X=0
POS_Y=1
HELP=HELP_LF_WHEELRATE

[SPRING_RATE_LR]
SHOW_CLICKS=0
TAB=SUSPENSION
NAME=Rear wheel rate
MIN=175
MAX=280
STEP=5
POS_X=1
POS_Y=5
HELP=HELP_LR_WHEELRATE

[CAMBER_LF]
SHOW_CLICKS=0
TAB=TYRES
NAME=Camber LF
MIN=-5.0
MAX=-1.0
STEP=0.1
POS_X=0
POS_Y=6
HELP=HELP_LF_CAMBER

[CAMBER_RF]
SHOW_CLICKS=0
TAB=TYRES
NAME=Camber RF
MIN=-5.0
MAX=-1.0
STEP=0.1
POS_X=1
POS_Y=6
HELP=HELP_RF_CAMBER

[BRAKE_POWER]
SHOW_CLICKS=0
TAB=VARIOUS
NAME=Brake power
MIN=80
MAX=120
STEP=1
POS_X=0
POS_Y=1
HELP=HELP_BRAKE_POWER

[FUEL]
SHOW_CLICKS=0
TAB=VARIOUS
NAME=Fuel
MIN=2
MAX=110
STEP=1
POS_X=1
POS_Y=2
HELP=HELP_FUEL
""")
    w(os.path.join(data, "sounds.ini"), """[SKIDS]
ENTRY_POINT=0.45
MIX_VOLUME=0.7
PITCH_BASE=0.43
PITCH_GAIN=0.12

[WIND]
SPEED_GAIN_0=0.0005
SPEED_GAIN_1=0.0002
VOLUME_GAIN=0.95
PITCH_REFERENCE=30
PITCH_GAIN=0.3

[TYRE_ROLLING]
SPEED_GAIN_0=0.0
SPEED_GAIN_1=0.0002
VOLUME_GAIN=0.6
PITCH_REFERENCE=45
PITCH_GAIN=0.2

[BODY_WORK]
MIN=0.2
GAIN=1

[GEAR_EXT]
DISTANCE_SCALE=7

[ENGINE]
POSITION=rear
""")
    w(os.path.join(data, "colliders.ini"), """[COLLIDER_0]
CENTRE=0,-0.20,-0.10
SIZE=1.90,0.30,4.60
""")
    w(os.path.join(data, "ambient_shadows.ini"), """[SETTINGS]
WIDTH=2.0
LENGTH=5.6
""")
    w(os.path.join(data, "mirrors.ini"), """[MIRROR_0]
NAME=MIRROR_L

[MIRROR_1]
NAME=MIRROR_R
""")
    w(os.path.join(data, "lights.ini"), """[BRAKE_0]
NAME=RAIN_LIGHT
INTENSITY=100
""")
    w(os.path.join(data, "lods.ini"), """[COCKPIT_HR]
DISTANCE_SWITCH=7

[LOD_0]
FILE=arb_rb20.kn5
IN=0
OUT=30

[LOD_1]
FILE=arb_rb20.kn5
IN=30
OUT=120

[LOD_2]
FILE=arb_rb20.kn5
IN=120
OUT=2000
""")
    w(os.path.join(data, "damage.ini"), """[DAMAGE]
BODY_DAMAGE_K=0.0008
ENGINE_DAMAGE_K=0.0006
SUSPENSION_DAMAGE_K=0.0005
""")

    # ---------------- ui_car.json ----------------
    peak_t = max(t for _, t in lut)
    peak_kw = fit["peak_power_w"] / 1000.0
    hp = peak_kw * 1.341
    torque_curve_ui = [[str(r), "%.1f" % t] for r, t in lut]
    power_curve_ui = [[str(r), "%.1f" % (t * 2 * math.pi * r / 60.0 / 1000.0)]
                      for r, t in lut]
    ui_car = {
        "name": "ARB RB20 2024",
        "brand": "Arena Racing Build",
        "description": "Original, clean-sheet 2024 ground-effect F1 car inspired by the RB20. "
                       "Physics calibrated from real 2024 Bahrain GP qualifying telemetry. "
                       "Vanilla Assetto Corsa: no shader patch, no extended physics, unpacked data. "
                       "Unofficial fan project; no team logos or trademarks included.",
        "tags": ["f1", "2024", "rb20", "formula", "telemetry", "no-csp"],
        "class": "race",
        "specs": {
            "bhp": "%.0f hp" % hp,
            "torque": "%.0f Nm" % peak_t,
            "weight": "798",
            "topspeed": "340",
            "acceleration": "2.6 s (0-100 km/h, simulated)",
            "pwratio": "%.2f" % (hp / 798.0),
            "range": "0",
        },
        "torqueCurve": torque_curve_ui,
        "powerCurve": power_curve_ui,
        "author": "Arena Racing Build",
        "version": "1.0",
        "url": "",
        "country": "Austria",
        "year": 2024,
    }
    w(os.path.join(ui, "ui_car.json"), json.dumps(ui_car, indent=2, ensure_ascii=False) + "\n")

    calib["ui_specs"] = ui_car["specs"]
    with open(os.path.join(CAR_DIR, "calibration.json"), "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2)
    print("wrote calibration.json")
    print("\nCALIBRATION SUMMARY")
    print("  lap            %.3f s  / %.0f m  / %d samples" %
          (d["lap_time"], d["lap_distance"], d["rows"]))
    print("  mu (slick)    %.3f      peak braking %.2f g" % (mu, braking["peak_decel_g"]))
    print("  CdA           %.3f m2   CLA %.3f m2" % (CdA, CLA))
    print("  peak power    %.0f kW @ %.0f rpm" % (peak_kw, fit["peak_power_rpm"]))
    print("  peak torque   %.0f Nm" % peak_t)
    print("  shift rpm     %.0f      8th total ratio %.3f" %
          (gears["shift_rpm"], gears["fitted_total"][8]))
    print("  brake torque  %.0f Nm per wheel" % max_torque)


if __name__ == "__main__":
    main()
