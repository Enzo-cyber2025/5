"""
features.py -- native vanilla-AC DRS, ERS (MGU-K) and wet compounds.

Everything here uses Kunos/vanilla physics files, the SAME files that ship with
AC's own hybrid/DRS cars. No CSP, no Lua, no ext_config.ini, no data.acd:

  * ers.ini + ctrl_ers_N.ini + kers_torque.lut + kers_torque_coast.lut
        -> MGU-K (120 kW FIA limit), 4 MJ deployment / 2 MJ recovery per lap,
           cockpit-selectable delivery profiles and a KERS/overtake button.
  * drs.ini -> DRS on the rear-wing flap wing (WING_4), ANGLE mode,
           IGNORE_ZONES=1 so it works on every vanilla track, no track edits.
  * tyres.ini compounds 3/4 -> Cinturato Intermediate and Full Wet.
  * ui_car.json / calibration.json -> official published power figure.

Official power (see references/POWER_AND_VANILLA_FEATURES.md):
  RB20 / Honda RBPTH002 published combined peak = 805 kW (1,080 hp).
  FIA 2024 caps the MGU-K at 120 kW, so the ICE share is 685 kW.
  power.lut carries the ICE only; kers_torque.lut carries the 120 kW MGU-K.
  Combined peak = 805 kW. The lap-average electrical share is limited by the
  4 MJ/lap deployment rule, which is why the telemetry fit (a lap) sees less
  than the peak. That difference is modelled, not hidden.
"""
from __future__ import annotations

import configparser
import json
import math
import os

PU_PEAK_KW = 805.0
MGUK_KW = 120.0
ICE_KW = PU_PEAK_KW - MGUK_KW                      # 685 kW
ERS_DEPLOY_MJ_LAP = 4.0
ERS_RECOVERY_MJ_LAP = 2.0
ERS_DISCHARGE_MS = int(round(ERS_DEPLOY_MJ_LAP * 1e6 / (MGUK_KW * 1000.0) * 1000.0))  # 33333 ms
DRIVETRAIN_EFF = 0.95                             # crank -> wheels, used by the aero fit
DRS_WING = "WING_4"
DRS_CLOSED_ANGLE = 12
DRS_OPEN_ANGLE = 0


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _lut(path, pairs, comments=()):
    txt = "".join("; %s\n" % c for c in comments)
    txt += "".join("%s|%s\n" % (k, v) for k, v in pairs)
    _w(path, txt)


def _ini(path):
    cp = configparser.ConfigParser(strict=False, allow_no_value=True,
                                   inline_comment_prefixes=(";",))
    cp.optionxform = str
    cp.read(path)
    return cp


# ---------------------------------------------------------------------- ERS
def write_ers(d):
    # MGU-K is a constant-power machine: T = P / omega. 120 kW from 3,000 rpm
    # up to the 15,000 rpm limiter. Torque is in Nm, keyed by ENGINE rpm
    # (ATTACH=ENGINE convention used by AC's hybrid cars).
    rpms = (0, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000,
            11000, 12000, 13000, 14000, 15000)
    tq = [(r, 0.0 if r < 3000 else round(MGUK_KW * 1000.0 * 60.0 / (2 * math.pi * r), 1))
          for r in rpms]
    _lut(os.path.join(d, "kers_torque.lut"), tq,
         ["MGU-K deployment torque [Nm] vs engine rpm: constant 120 kW (FIA 2024 limit).",
          "power.lut holds the 685 kW ICE; the sum is the published 805 kW peak."])
    _lut(os.path.join(d, "kers_torque_coast.lut"),
         [(0, 0), (3000, -8), (6000, -18), (9000, -28), (12000, -38), (15000, -42)],
         ["MGU-K harvesting torque [Nm] on coast/brake, capped at 2 MJ per lap."])

    # Shared controller LUTs. Inputs are AC's native telemetry channels.
    _lut(os.path.join(d, "ers_gear.lut"),
         [(0, 0.75), (1, 0.75), (2, 0.85), (3, 1.00), (8, 1.00)],
         ["Deploy multiplier by gear: no full MGU-K torque in 1st/2nd (traction)."])
    _lut(os.path.join(d, "ers_slip.lut"),
         [(0, 1.00), (0.05, 1.00), (0.15, 0.70), (0.30, 0.15), (0.60, 0.00)],
         ["Deploy multiplier by max slip ratio: cut deployment when the rears spin."])

    modes = [("Charge", 0.10), ("Balanced", 0.70), ("Hotlap", 1.00)]
    for i, (name, peak) in enumerate(modes):
        gas_lut = "ers%d_gas.lut" % i
        _lut(os.path.join(d, gas_lut),
             [(0, 0), (0.5, round(peak * 0.6, 2)), (1, peak)],
             ["%s profile: deployment vs throttle." % name])
        _w(os.path.join(d, "ctrl_ers_%d.ini" % i), """[HEADER]
NAME=%s

[CONTROLLER_0]
COMBINATOR=ADD
INPUT=GAS
LUT=%s
FILTER=0.96
UP_LIMIT=1
DOWN_LIMIT=0

[CONTROLLER_1]
COMBINATOR=MULT
INPUT=GEAR
LUT=ers_gear.lut
FILTER=0.96
UP_LIMIT=1
DOWN_LIMIT=0

[CONTROLLER_2]
COMBINATOR=MULT
INPUT=SLIPRATIO_MAX
LUT=ers_slip.lut
FILTER=0.96
UP_LIMIT=1
DOWN_LIMIT=0
""" % (name, gas_lut))

    _w(os.path.join(d, "ers.ini"), """[HEADER]
VERSION=1

[KINETIC]
; 2024 FIA rules: MGU-K 120 kW, 4 MJ deployment/lap, 2 MJ recovery/lap.
; DISCHARGE_TIME is the time a full store lasts at 120 kW: 4 MJ / 120 kW = 33.33 s.
CHARGE_K=0.00010
TORQUE_CURVE=kers_torque.lut
COAST_CURVE=kers_torque_coast.lut
DISCHARGE_TIME=%d
HAS_BUTTON_OVERRIDE=1
MAX_KJ_PER_LAP=4000000
DEFAULT_CONTROLLER=1
BRAKE_REAR_CORRECTION=45

[HEAT]
; MGU-H is modelled as energy recovery into the store only. TORQUE_PERC=0 keeps
; total crankshaft power at the 805 kW published figure instead of inventing
; extra electric torque beyond the 120 kW MGU-K regulatory limit.
CHARGE_K=0.00060
TORQUE_PERC=0

[COCKPIT_CONTROLS]
RECOVERY=1
DELIVERY_PROFILE=1
MGU_H_MODE=0
""" % ERS_DISCHARGE_MS)


# ---------------------------------------------------------------------- DRS
def write_drs(d, CLA, CdA):
    p = os.path.join(d, "aero.ini")
    cp = _ini(p)
    # Split the original REAR wing into a fixed main plane and a movable DRS
    # flap so the total CL/CD is unchanged when DRS is CLOSED.
    # Original shares: CL 0.27 / CD 0.28. New: main 0.10/0.10, flap 0.17/0.18.
    w2 = cp["WING_2"]
    w2["CL_GAIN"] = "%.4f" % (float(w2["CL_GAIN"]) * 0.10 / 0.27)
    w2["CD_GAIN"] = "%.4f" % (float(w2["CD_GAIN"]) * 0.10 / 0.28)

    w4 = {k: v for k, v in cp["WING_2"].items()}
    w4.update({
        "NAME": "DRS", "CHORD": "1.0", "SPAN": "1.0",
        "POSITION": "0,0.630,-2.420",
        "LUT_AOA_CL": "aero_drs_CL.lut", "LUT_GH_CL": "gh_drs_CL.lut",
        "CL_GAIN": "%.4f" % (CLA * 0.17),
        "LUT_AOA_CD": "aero_drs_CD.lut", "LUT_GH_CD": "gh_drs_CD.lut",
        "CD_GAIN": "%.4f" % (CdA * 0.18),
        "ANGLE": str(DRS_CLOSED_ANGLE),
    })
    cp[DRS_WING] = w4
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        cp.write(f, space_around_delimiters=False)

    # With the flap rotated to 0 degrees it stalls: downforce collapses and
    # drag drops. These are AoA multipliers, exactly like the other wings.
    _lut(os.path.join(d, "aero_drs_CL.lut"),
         [(0, 0.10), (4, 0.42), (8, 0.76), (12, 1.00), (17, 1.10), (25, 1.18)],
         ["DRS flap AoA [deg] -> CL multiplier. 12 deg = closed, 0 deg = open."])
    _lut(os.path.join(d, "aero_drs_CD.lut"),
         [(0, 0.30), (4, 0.55), (8, 0.80), (12, 1.00), (17, 1.14), (25, 1.42)],
         ["DRS flap AoA [deg] -> CD multiplier."])
    _lut(os.path.join(d, "gh_drs_CL.lut"),
         [(0, 0.0), (0.010, 0.35), (0.020, 0.92), (0.030, 1.06),
          (0.045, 1.00), (0.070, 0.88), (0.100, 0.55), (0.150, 0.30)])
    _lut(os.path.join(d, "gh_drs_CD.lut"),
         [(0, 0.97), (0.020, 0.99), (0.045, 1.00), (0.080, 1.01), (0.150, 1.02)])

    _w(os.path.join(d, "drs.ini"), """[HEADER]
VERSION=2

[%s]
MODE=ANGLE
EFFECT=0.10
ANGLE=%d

[DRS_ZONES]
; Vanilla AC tracks do not all carry DRS zones. IGNORE_ZONES=1 lets the
; native DRS button work on every track without editing any track files.
IGNORE_ZONES=1

[DEACTIVATION]
LIMIT_G=6.9
""" % (DRS_WING, DRS_OPEN_ANGLE))


# --------------------------------------------------------------- wet tyres
WET = [
    dict(idx=3, tag="intermediate", name="Intermediate", short="I", gm=0.72,
         radius=0.362, rr0=9, rr1=0.00085, speed=0.0040, flex=0.00048,
         slip_angle=6.4, press=22.0, ideal=24.0),
    dict(idx=4, tag="wet", name="Full Wet", short="W", gm=0.56,
         radius=0.368, rr0=12, rr1=0.00110, speed=0.0045, flex=0.00055,
         slip_angle=6.0, press=21.0, ideal=23.0),
]


def write_wet(d, mu):
    txt = ""
    for w in WET:
        tag, grip = w["tag"], mu * w["gm"]
        for axle in ("front", "rear"):
            _lut(os.path.join(d, "wear_%s_%s.lut" % (tag, axle)),
                 [(0, 100), (0.3, 100), (1, 99), (2, 97), (4, 93),
                  (6, 88), (8, 83), (11, 77), (14, 71), (18, 63)],
                 ["Wet compound wear: [%] grip vs 100%% of compound life."])
        _lut(os.path.join(d, "tcurve_%s.lut" % tag),
             [(0, 0.80), (20, 0.92), (40, 0.99), (60, 1.00), (75, 0.98),
              (100, 0.86), (140, 0.65), (220, 0.45), (300, 0.30)],
             ["Wet compound works at a much lower temperature than a slick."])
        for axle in ("FRONT", "REAR"):
            front = axle == "FRONT"
            width = 0.305 if front else 0.405
            txt += """[%s_%d]
NAME=2024 Cinturato %s %s
SHORT_NAME=%s%d
WIDTH=%.3f
RADIUS=%.3f
RIM_RADIUS=0.2413
ANGULAR_INERTIA=%.2f
DAMP=%.0f
RATE=%.0f
DY0=%.4f
DY1=-0.028
DX0=%.4f
DX1=-0.028
WEAR_CURVE=wear_%s_%s.lut
WEAR_SENSIBILITY=0
SPEED_SENSITIVITY=%.4f
RELAXATION_LENGTH=0.052
ROLLING_RESISTANCE_0=%d
ROLLING_RESISTANCE_1=%.5f
ROLLING_RESISTANCE_SLIP=4200
FLEX=%.5f
CAMBER_GAIN=0.10
DCAMBER_0=1.3
DCAMBER_1=-11
FRICTION_LIMIT_ANGLE=%.1f
XMU=0.20
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
FLEX_GAIN=0.16
FALLOFF_LEVEL=0.90
FALLOFF_SPEED=4

""" % (axle, w["idx"], w["name"], axle.title(), w["short"], w["idx"],
       width, w["radius"], 1.65 if front else 2.20,
       900 if front else 1000, 255000 if front else 235000,
       grip + 0.02, grip, tag, "front" if front else "rear",
       w["speed"], w["rr0"], w["rr1"], w["flex"], w["slip_angle"],
       w["press"], w["ideal"], 3100 if front else 3400, grip, grip + 0.02)
        for axle in ("FRONT", "REAR"):
            front = axle == "FRONT"
            txt += """[THERMAL_%s_%d]
SURFACE_TRANSFER=0.0180
PATCH_TRANSFER=0.00027
CORE_TRANSFER=%.6f
INTERNAL_CORE_TRANSFER=0.00721
FRICTION_K=%.5f
ROLLING_K=0.32
PERFORMANCE_CURVE=tcurve_%s.lut
GRAIN_GAMMA=1.0
GRAIN_GAIN=0.55
BLISTER_GAMMA=1.0
BLISTER_GAIN=0.20
COOL_FACTOR=1.50
SURFACE_ROLLING_K=0.957

""" % (axle, w["idx"], 0.003035 if front else 0.002648,
       0.1415 if front else 0.1350, tag)
    with open(os.path.join(d, "tyres.ini"), "a", encoding="utf-8") as f:
        f.write(txt)


# ------------------------------------------------------------------- UI/JSON
def rewrite_ui(ui_dir, calib):
    p = os.path.join(ui_dir, "ui_car.json")
    with open(p, "r", encoding="utf-8") as f:
        ui = json.load(f)
    lap = calib["telemetry"]["lap_time_s"]
    frac = ERS_DEPLOY_MJ_LAP * 1e6 / (MGUK_KW * 1000.0 * lap)
    ui["description"] = (
        "Original, clean-sheet 2024 ground-effect F1 car inspired by the RB20. "
        "Published RB20 power unit output 805 kW (1,080 hp): 685 kW ICE plus a "
        "120 kW MGU-K with native ERS modes, 4 MJ deployment per lap, a KERS "
        "overtake button and native DRS on the rear flap. Five compounds "
        "including Intermediate and Full Wet. Physics calibrated from real 2024 "
        "Bahrain GP qualifying telemetry. Vanilla Assetto Corsa: no shader patch, "
        "no extended physics, unpacked data. Unofficial fan project, no team logos.")
    ui["tags"] = ["f1", "2024", "rb20", "formula", "telemetry", "no-csp",
                  "ers", "drs", "wet"]
    ui["specs"]["bhp"] = "1080 hp (805 kW)"
    ui["specs"]["power"] = "805 kW combined (ICE 685 + MGU-K 120)"
    ui["specs"]["torque"] = "%.0f Nm ICE (+ MGU-K)" % calib["peak_torque_nm"]
    ui["specs"]["ers"] = "120 kW MGU-K, 4 MJ/lap deploy, 2 MJ/lap recovery"
    ui["specs"]["drs"] = "Native DRS (rear flap)"
    ui["specs"]["tyres"] = "5 compounds: S / M / H / I / W"
    ui["specs"]["pwratio"] = "%.2f" % (1080.0 / 798.0)
    # UI curves now show the COMBINED power unit, not the ICE alone.
    for row in ui["powerCurve"]:
        r = float(row[0])
        if 3000 <= r < 15000:
            row[1] = "%.1f" % (float(row[1]) + MGUK_KW)
    for row in ui["torqueCurve"]:
        r = float(row[0])
        if 3000 <= r < 15000:
            row[1] = "%.1f" % (float(row[1]) + MGUK_KW * 1000.0 * 60.0 / (2 * math.pi * r))
    ui["version"] = "1.1"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(ui, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return frac


# ------------------------------------------------------------------ rear light
# Vanilla lights.ini (Kunos ACD reference, VERSION=3). Real F1 behaviour:
#   * main central red light -> [BRAKE_0], bright when braking;
#   * second central emitter -> [LIGHT_0], switched on by the driver together
#     with the light switch: FIA 2024 Sporting Regs art. 26.11 requires the
#     rear light to be illuminated at ALL TIMES when intermediate/wet tyres
#     are used. Vanilla AC cannot detect the tyre compound automatically, so
#     the documented driver action is "lights on whenever wets are fitted";
#   * the two endplate repeaters -> [LIGHT_1] / [LIGHT_2] with KERS=1: they
#     flash while the MGU-K is harvesting energy, exactly like a real F1 car.
# KERS_BLINKING=1 / FLASHING_* are vanilla header keys, not CSP.
LIGHTS_INI = """[HEADER]
VERSION=3
FLASHING_BLINK_TIME=0.15
FLASHING_REPEAT=8
KERS_BLINKING=1

[BRAKE_0]
NAME=RAIN_LIGHT_MESH
COLOR=320,10,6
OFF_COLOR=0,0,0

[LIGHT_0]
NAME=RAIN_LIGHT_WET_MESH
COLOR=180,0,0
OFF_COLOR=0,0,0

[LIGHT_1]
NAME=RAIN_LIGHT_L_MESH
COLOR=180,0,0
KERS=1
PITLINE=1
SPECIAL=1

[LIGHT_2]
NAME=RAIN_LIGHT_R_MESH
COLOR=180,0,0
KERS=1
PITLINE=1
SPECIAL=1
"""

# Vanilla ACD digital_instruments.ini DRS sections. OBJECT_NAME points at real
# MESH nodes of the KN5 (the dummy/mesh name collision was removed), so no
# missing-dummy crash is possible.
DIGITAL_INI = """[DRS_AVAILABLE_0]
OBJECT_NAME=DASH_DRS_AVAIL_MESH
EMISSIVE=0,12,0
DIFFUSE=0.30
BLINK_TIME=0

[DRS_ENABLED_0]
OBJECT_NAME=DASH_DRS_MESH
EMISSIVE=0,35,0
DIFFUSE=0.30
BLINK_TIME=0
"""

WING_ANIM_INI = """[ANIMATION_0]
WING=4
FILE=rb20_drs.ksanim
MIN=0
MAX=12
INVERTED=0
SPEED=6
"""

# Rear flap hinge in car coordinates (Y-up, +Z forward): leading edge of the
# 0.215 m chord aerofoil at (0, 0.985, -2.415) inclined 26 degrees.
FLAP_HINGE_Y = 0.940
FLAP_HINGE_Z = -2.320
DRS_NODE = "WING_REAR_FLAP"


def write_ksanim(path, node_name, frames):
    """Write a vanilla AC .ksanim v2 keyframe animation.

    On-disk layout verified against Kunos-style .ksanim files:
      int32 version=2, int32 node_count
      per node: int32 name_len, char name[name_len], int32 frame_count,
                frame_count * 10 floats = quat(x,y,z,w) + pos(3) + scale(3).
    Identity rotation is (0,0,0,1); no CSP/Lua is involved.
    """
    import struct
    buf = bytearray()
    buf += struct.pack("<ii", 2, 1)
    nm = node_name.encode("ascii")
    buf += struct.pack("<i", len(nm)) + nm
    buf += struct.pack("<i", len(frames))
    for q, p, s in frames:
        buf += struct.pack("<10f", q[0], q[1], q[2], q[3],
                           p[0], p[1], p[2], s[0], s[1], s[2])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(buf)


def drs_frames():
    """13 keyframes: wing angle 12 deg (DRS closed) -> 0 deg (DRS open).

    The flap's KN5 dummy sits at the hinge and its vertices are LOCAL to it,
    so every frame is a pure quaternion rotation with a constant translation,
    exactly like Kunos .ksanim files. No per-frame world-space offsets.
    """
    frames = []
    for angle in range(13):
        theta = math.radians(12 - angle)
        q = (math.sin(theta / 2.0), 0.0, 0.0, math.cos(theta / 2.0))
        frames.append((q, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
    return frames


def write_visual_features(car_dir, d):
    _w(os.path.join(d, "lights.ini"), LIGHTS_INI)
    _w(os.path.join(d, "digital_instruments.ini"), DIGITAL_INI)
    _w(os.path.join(d, "wing_animations.ini"), WING_ANIM_INI)
    write_ksanim(os.path.join(car_dir, "animations", "rb20_drs.ksanim"),
                 DRS_NODE, drs_frames())


def apply(car_dir):
    """Post-process the calibrated data/ folder with native AC features."""
    d = os.path.join(car_dir, "data")
    p = os.path.join(car_dir, "data", "calibration.json")
    with open(p, "r", encoding="utf-8") as f:
        calib = json.load(f)
    mu = calib["braking"]["mu"]
    CLA, CdA = calib["fit"]["CLA"], calib["fit"]["CdA"]
    lap = calib["telemetry"]["lap_time_s"]
    frac = ERS_DEPLOY_MJ_LAP * 1e6 / (MGUK_KW * 1000.0 * lap)

    write_ers(d)
    write_drs(d, CLA, CdA)
    write_wet(d, mu)
    write_visual_features(car_dir, d)
    rewrite_ui(os.path.join(car_dir, "ui"), calib)

    calib["official_power"] = {
        "published_rb20_combined_kw": PU_PEAK_KW,
        "published_rb20_hp": 1080,
        "ice_kw": ICE_KW,
        "mguk_kw": MGUK_KW,
        "source": "Liquipedia RB20 (1,080 hp / 805 kW); Wikipedia Honda V6 hybrid "
                  "(RBPTH002, 810 kW est.); FIA 2024 technical regulations for "
                  "the 120 kW MGU-K limit. See references/POWER_AND_VANILLA_FEATURES.md.",
        "note": "No FIA/team single official combined rating exists; 805 kW is the "
                "published RB20 figure. Other sources quote 550-560 kW ICE and "
                "~750 kW combined. power.lut is ICE-only, kers_torque.lut adds "
                "the MGU-K, their sum is 805 kW.",
    }
    calib["ers"] = {
        "mguk_kw": MGUK_KW, "deploy_mj_per_lap": ERS_DEPLOY_MJ_LAP,
        "recovery_mj_per_lap": ERS_RECOVERY_MJ_LAP,
        "full_deploy_seconds_per_lap": round(ERS_DEPLOY_MJ_LAP * 1e6 / (MGUK_KW * 1000.0), 2),
        "lap_average_deploy_fraction": round(frac, 4),
        "lap_average_power_kw": round(ICE_KW + MGUK_KW * frac, 2),
        "modes": ["Charge", "Balanced", "Hotlap"],
        "button_override": True,
        "implementation": "vanilla ers.ini + ctrl_ers_0..2.ini + kers_*.lut",
    }
    calib["drs"] = {
        "wing": DRS_WING, "closed_angle_deg": DRS_CLOSED_ANGLE,
        "open_angle_deg": DRS_OPEN_ANGLE,
        "ignore_track_zones": True,
        "implementation": "vanilla drs.ini VERSION=2",
    }
    calib["rear_light"] = {
        "implementation": "vanilla lights.ini VERSION=3 (no CSP, no emissive shaders)",
        "main_light": "BRAKE_0 -> RAIN_LIGHT_MESH, brighter under braking",
        "wet_rule": "FIA 2024 Sporting Regulations art. 26.11: the rear light "
                    "must be lit at all times with intermediate/full wet tyres",
        "wet_activation": "LIGHT_0 -> RAIN_LIGHT_WET_MESH, driver switches the "
                          "car lights on when fitting wet compounds. Vanilla AC "
                          "has no compound-to-light binding (that needs CSP).",
        "ers_harvest": "LIGHT_1/LIGHT_2 -> RAIN_LIGHT_L_MESH / _R_MESH, "
                       "KERS=1 + KERS_BLINKING=1: flashes on MGU-K recovery",
        "dashboard": "vanilla digital_instruments.ini DRS_AVAILABLE_0 / "
                     "DRS_ENABLED_0 -> steering-wheel LEDs",
        "meshes": ["RAIN_LIGHT_MESH", "RAIN_LIGHT_WET_MESH",
                   "RAIN_LIGHT_L_MESH", "RAIN_LIGHT_R_MESH",
                   "DASH_DRS_AVAIL_MESH", "DASH_DRS_MESH"],
    }
    calib["drs"]["visual_animation"] = {
        "implementation": "vanilla wing_animations.ini + animations/rb20_drs.ksanim v2",
        "wing": DRS_WING,
        "frames": len(drs_frames()),
        "angle_range_deg": [DRS_OPEN_ANGLE, DRS_CLOSED_ANGLE],
        "node": DRS_NODE,
        "note": "AC maps the wing angle (12 deg closed -> 0 deg open) to the "
                "13 keyframes; the flap physically rotates about its hinge.",
    }
    calib["wet_tyres"] = {
        "compounds": ["2024 Cinturato Intermediate", "2024 Cinturato Full Wet"],
        "grip_multiplier": {w["name"]: w["gm"] for w in WET},
        "note": "Vanilla AC has no dynamic rain (that would require CSP). The wet "
                "compounds are selectable in the setup screen and have lower grip, "
                "higher rolling resistance and a lower optimal temperature.",
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2)
        f.write("\n")
    print("  features: ERS (120 kW / 4 MJ), DRS (WING_4 + 13-frame flap "
          "animation), 2 wet compounds, vanilla F1 rear light / dash LEDs, "
          "official 805 kW published")
