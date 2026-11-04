"""
validate.py -- gate the release: structure, vanilla-AC compatibility, physics.

Fails (exit 1) if the mod needs CSP, references a missing file, has a broken
KN5, or if the telemetry-based physics validation did not pass.
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kn5format

CSP_FORBIDDEN = [
    "extended-", "extendedV", "extension/ext_config.ini", "ext_config.ini",
    "wing_controller.ini", "custom_shaders_patch",
    "data.acd", "ksPerPixelMultiMap_emissive", "ksWindscreen", "RainFX",
    "VERSION=10", "VERSION=extended", "[_EXTENSION]", "REQUIRED_VERSION",
    "csp_extra_options", "physics/extended", "SOL__", "AC_RAIN",
]

REQUIRED = [
    "content/cars/arb_rb20/arb_rb20.kn5",
    "content/cars/arb_rb20/collider.kn5",
    "content/cars/arb_rb20/ui/ui_car.json",
    "content/cars/arb_rb20/ui/badge.png",
    "content/cars/arb_rb20/skins/default/preview.jpg",
    "content/cars/arb_rb20/data/car.ini",
    "content/cars/arb_rb20/data/engine.ini",
    "content/cars/arb_rb20/data/power.lut",
    "content/cars/arb_rb20/data/drivetrain.ini",
    "content/cars/arb_rb20/data/suspensions.ini",
    "content/cars/arb_rb20/data/tyres.ini",
    "content/cars/arb_rb20/data/aero.ini",
    "content/cars/arb_rb20/data/brakes.ini",
    "content/cars/arb_rb20/data/setup.ini",
    "content/cars/arb_rb20/data/ers.ini",
    "content/cars/arb_rb20/data/drs.ini",
    "content/cars/arb_rb20/data/kers_torque.lut",
    "content/cars/arb_rb20/data/kers_torque_coast.lut",
    "content/cars/arb_rb20/data/ctrl_ers_0.ini",
    "content/cars/arb_rb20/data/ctrl_ers_1.ini",
    "content/cars/arb_rb20/data/ctrl_ers_2.ini",
    "content/cars/arb_rb20/data/aero_drs_CL.lut",
    "content/cars/arb_rb20/data/aero_drs_CD.lut",
    "content/cars/arb_rb20/data/lods.ini",
    "content/cars/arb_rb20/data/lights.ini",
    "content/cars/arb_rb20/data/digital_instruments.ini",
    "content/cars/arb_rb20/data/wing_animations.ini",
    "content/cars/arb_rb20/animations/rb20_drs.ksanim",
    "content/cars/arb_rb20/data/electronics.ini",
    "content/cars/arb_rb20/data/calibration.json",
    "content/cars/arb_rb20/LEIA-ME.txt",
    "content/cars/arb_rb20/VALIDACAO.md",
    "content/cars/arb_rb20/REFERENCIAS.md",
    # Standard Kunos car folder (formula_k layout).
    "content/cars/arb_rb20/logo.png",
    "content/cars/arb_rb20/body_shadow.png",
    "content/cars/arb_rb20/tyre_0_shadow.png",
    "content/cars/arb_rb20/tyre_1_shadow.png",
    "content/cars/arb_rb20/tyre_2_shadow.png",
    "content/cars/arb_rb20/tyre_3_shadow.png",
    "content/cars/arb_rb20/arb_rb20_LOD_B.kn5",
    "content/cars/arb_rb20/arb_rb20_LOD_C.kn5",
    "content/cars/arb_rb20/arb_rb20_LOD_D.kn5",
    "content/cars/arb_rb20/animations/steer.ksanim",
    "content/cars/arb_rb20/data/driver3d.ini",
    "content/cars/arb_rb20/data/cameras.ini",
    "content/cars/arb_rb20/data/dash_cam.ini",
    "content/cars/arb_rb20/data/escmode.ini",
    "content/cars/arb_rb20/data/fuel_cons.ini",
    "content/cars/arb_rb20/data/blurred_objects.ini",
    "content/cars/arb_rb20/data/proview_nodes.ini",
    "content/cars/arb_rb20/data/suspension_graphics.ini",
    "content/cars/arb_rb20/data/throttle.lut",
    "content/cars/arb_rb20/sfx/GUIDs.txt",
    "content/cars/arb_rb20/skins/default/ui_skin.json",
    "content/cars/arb_rb20/skins/default/livery.png",
    "content/cars/arb_rb20/texture/display.png",
    "content/cars/arb_rb20/texture/display_off.png",
    "content/cars/arb_rb20/ui/preview_small.png",
]


def ini(path):
    cp = configparser.ConfigParser(strict=False, allow_no_value=True,
                                   inline_comment_prefixes=(";",))
    cp.optionxform = str
    cp.read(path)
    return cp


def read_ksanim(path):
    """Parse a vanilla .ksanim v2; return (version, [(node, frames)], end, size)."""
    import struct
    with open(path, "rb") as f:
        b = f.read()
    ver, count = struct.unpack_from("<ii", b, 0)
    off, nodes = 8, []
    for _ in range(count):
        (ln,) = struct.unpack_from("<i", b, off)
        off += 4
        name = b[off:off + ln].decode("ascii", "replace")
        off += ln
        (fc,) = struct.unpack_from("<i", b, off)
        off += 4
        off += fc * 40
        nodes.append((name, fc))
    return ver, nodes, off, len(b)


def check_car_dir(car_dir):
    problems, notes = [], []
    data = os.path.join(car_dir, "data")

    # 1. Vanilla headers only.
    expected = {"car.ini": "1", "engine.ini": "1", "drivetrain.ini": "2",
                "suspensions.ini": "2", "tyres.ini": "7", "aero.ini": "3",
                "brakes.ini": "1", "ai.ini": "4"}
    for fname, ver in expected.items():
        p = os.path.join(data, fname)
        if not os.path.exists(p):
            problems.append("missing " + fname)
            continue
        cp = ini(p)
        got = cp.get("HEADER", "VERSION", fallback="(none)")
        if got != ver:
            problems.append("%s HEADER VERSION=%s (expected vanilla %s)" % (fname, got, ver))
        notes.append("%s VERSION=%s" % (fname, got))

    # 2. No CSP-only files or tokens anywhere in the car folder.
    for root, dirs, files in os.walk(car_dir):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), car_dir).replace("\\", "/")
            if any(x.lower() in rel.lower() for x in ("ext_config", "extension/", "data.acd",
                                                       "wing_controller", ".lua")):
                problems.append("CSP-ish file present: " + rel)
            if name.lower().endswith((".ini", ".lut", ".json", ".txt", ".md")):
                try:
                    txt = open(os.path.join(root, name), "r", encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                # Strip comments so documentation lines cannot trigger false
                # positives (e.g. "never use VERSION=extended-*").
                code = "\n".join(line.split(";", 1)[0] for line in txt.splitlines())
                for token in CSP_FORBIDDEN:
                    if token.lower() in code.lower():
                        problems.append("CSP token %r in %s" % (token, rel))
    # 3. Shaders in the KN5 must be vanilla.
    vanilla_shaders = {"ksPerPixel", "ksPerPixelAT", "ksPerPixelAlpha",
                       "ksPerPixelMultiMap", "ksPerPixel_nosdw", "ksTyres",
                       "ksBrakeDisc", "GL"}
    mesh_names = set()
    for kn5 in ("arb_rb20.kn5", "arb_rb20_LOD_B.kn5",
                "arb_rb20_LOD_C.kn5", "arb_rb20_LOD_D.kn5",
                "collider.kn5"):
        p = os.path.join(car_dir, kn5)
        info = kn5format.read_kn5(p)
        nodes = list(kn5format.walk(info["root"]))
        if kn5 == "arb_rb20.kn5":
            mesh_names.update(n["name"] for n in nodes if n["class"] == 2)
        meshes = [n for n in nodes if n["class"] == 2]
        tris = sum(n["index_count"] // 3 for n in meshes)
        if not meshes:
            problems.append(kn5 + " has no meshes")
        for m in info["materials"]:
            if m["shader"] not in vanilla_shaders:
                problems.append("non-vanilla shader %s in %s" % (m["shader"], kn5))
            for pname, slot, tex in m["maps"]:
                if tex not in [t[0] for t in info["textures"]]:
                    problems.append("missing embedded texture %s" % tex)
        notes.append("%s v%d: %d nodes, %d tris, %d textures, %d materials" %
                     (kn5, info["version"], len(nodes), tris,
                      len(info["textures"]), len(info["materials"])))
        if tris < 100 and kn5 != "collider.kn5":
            problems.append("%s has only %d triangles" % (kn5, tris))
        if tris < 5000 and kn5 == "arb_rb20.kn5":
            problems.append("main KN5 has only %d triangles" % tris)

    # 4. Every LUT / texture reference resolves.
    ref = re.compile(r"^([A-Za-z0-9_\-]+\.(?:lut|dds|png))\s*$", re.M)
    for root, dirs, files in os.walk(data):
        for name in files:
            if not name.endswith(".ini"):
                continue
            txt = open(os.path.join(root, name), "r", encoding="utf-8", errors="ignore").read()
            for hit in re.findall(r"=\s*([^\s;]+\.(?:lut|dds|png))", txt):
                candidates = [os.path.join(data, hit),
                              os.path.join(car_dir, "skins", "default", hit)]
                if not any(os.path.exists(c) for c in candidates):
                    problems.append("%s references missing file %s" % (name, hit))
    cp = ini(os.path.join(data, "lods.ini"))
    for s in cp.sections():
        f = cp.get(s, "FILE", fallback="")
        if f and not os.path.exists(os.path.join(car_dir, f)):
            problems.append("lods.ini references missing %s" % f)

    # 5. Physics sanity from the shipped files.
    car = ini(os.path.join(data, "car.ini"))
    drv = ini(os.path.join(data, "drivetrain.ini"))
    eng = ini(os.path.join(data, "engine.ini"))
    tyres = ini(os.path.join(data, "tyres.ini"))
    if int(float(car["BASIC"]["TOTALMASS"])) != 798:
        problems.append("unexpected TOTALMASS")
    if int(drv["GEARS"]["COUNT"]) != 8:
        problems.append("expected 8 gears")
    if float(eng["ENGINE_DATA"]["LIMITER"]) != 15000:
        problems.append("expected 15,000 rpm limiter")
    if not (1.4 < float(tyres["FRONT"]["DX0"]) < 2.2):
        problems.append("tyre grip out of realistic range")

    # 6. Native ERS, DRS, wet compounds and the official published power.
    ers = ini(os.path.join(data, "ers.ini"))
    if ers.get("HEADER", "VERSION", fallback="") != "1":
        problems.append("ers.ini must be vanilla VERSION=1")
    kin = ers["KINETIC"] if ers.has_section("KINETIC") else {}
    if str(kin.get("HAS_BUTTON_OVERRIDE", "0")) != "1":
        problems.append("ERS KERS-button override missing")
    try:
        if abs(float(kin["DISCHARGE_TIME"]) - 33333.0) > 100:
            problems.append("ERS discharge time does not implement 4 MJ/lap")
    except (KeyError, ValueError):
        problems.append("ERS discharge time missing")
    drs = ini(os.path.join(data, "drs.ini"))
    if drs.get("HEADER", "VERSION", fallback="") != "2":
        problems.append("drs.ini must be vanilla VERSION=2")
    if drs.get("DRS_ZONES", "IGNORE_ZONES", fallback="0") != "1":
        problems.append("DRS must use IGNORE_ZONES=1 for vanilla tracks")
    for sec in ("FRONT_3", "REAR_3", "FRONT_4", "REAR_4"):
        if sec not in tyres:
            problems.append("missing wet compound section " + sec)
    if "FRONT_4" in tyres and float(tyres["FRONT_4"]["DX0"]) >= float(tyres["FRONT"]["DX0"]):
        problems.append("full-wet compound has no grip reduction")
    with open(os.path.join(data, "calibration.json"), "r", encoding="utf-8") as f:
        cal = json.load(f)
    if abs(float(cal.get("official_power", {}).get("published_rb20_combined_kw", 0)) - 805.0) > 0.5:
        problems.append("official 805 kW power figure missing from calibration")
    with open(os.path.join(car_dir, "ui", "ui_car.json"), "r", encoding="utf-8") as f:
        ui = json.load(f)
    bhp = ui.get("specs", {}).get("bhp", "")
    if "1080" not in bhp or "805" not in bhp:
        problems.append("ui_car.json does not show the official 805 kW")
    # 7. Real-F1 rear light, DRS dash LEDs and the visual flap animation.
    lights = ini(os.path.join(data, "lights.ini"))
    if lights.get("HEADER", "VERSION", fallback="") != "3":
        problems.append("lights.ini must be vanilla VERSION=3")
    if lights.get("HEADER", "KERS_BLINKING", fallback="0") != "1":
        problems.append("lights.ini must enable vanilla KERS_BLINKING")
    if "COLOR" not in (lights["BRAKE_0"] if lights.has_section("BRAKE_0") else {}):
        problems.append("main rear light has no COLOR/OFF_COLOR")
    light_secs = [x for x in lights.sections() if x.startswith("LIGHT_")]
    if not any(lights.get(x, "KERS", fallback="0") == "1" for x in light_secs):
        problems.append("no rear light flashes on MGU-K harvest (KERS=1)")
    if not any(lights.get(x, "SPECIAL", fallback="0") == "1" for x in light_secs):
        problems.append("ERS repeater lights must use SPECIAL=1")
    wanim = ini(os.path.join(data, "wing_animations.ini"))
    if wanim.get("ANIMATION_0", "WING", fallback="") != "4":
        problems.append("wing_animations.ini must target WING_4 (the DRS flap)")
    if wanim.get("ANIMATION_0", "FILE", fallback="") != "rb20_drs.ksanim":
        problems.append("wing_animations.ini points at the wrong .ksanim")
    ks = os.path.join(car_dir, "animations", "rb20_drs.ksanim")
    if os.path.exists(ks):
        ver, knodes, off, size = read_ksanim(ks)
        if ver != 2 or off != size:
            problems.append("rb20_drs.ksanim is not a well-formed vanilla v2 animation")
        if len(knodes) != 1 or knodes[0] != ("WING_REAR_FLAP", 13):
            problems.append("DRS animation must have 13 frames on WING_REAR_FLAP")
    else:
        problems.append("missing animations/rb20_drs.ksanim")
    digi = ini(os.path.join(data, "digital_instruments.ini"))
    for sec in ("DRS_AVAILABLE_0", "DRS_ENABLED_0"):
        if sec not in digi:
            problems.append("missing vanilla dash DRS section " + sec)
    refs = [lights.get(x, "NAME", fallback="") for x in lights.sections()
            if lights.has_option(x, "NAME")]
    refs += [digi.get(x, "OBJECT_NAME", fallback="") for x in digi.sections()
             if digi.has_option(x, "OBJECT_NAME")]
    refs += [digi.get(x, "NAME", fallback="") for x in digi.sections()
             if x.startswith("DISPLAY_") and digi.has_option(x, "NAME")]
    for r in refs:
        if r and r not in mesh_names:
            problems.append("lights/dash references missing KN5 mesh " + r)
    # 8. Standard Kunos car layout: LOD chain, steer animation, dash sections.
    steer = os.path.join(car_dir, "animations", "steer.ksanim")
    if os.path.exists(steer):
        sver, snodes, send, ssize = read_ksanim(steer)
        if sver != 2 or send != ssize or not snodes or snodes[0][0] != "STEER_HR":
            problems.append("steer.ksanim is not a valid vanilla STEER_HR animation")
    else:
        problems.append("missing vanilla animations/steer.ksanim")
    if "DISPLAY_0" not in digi:
        problems.append("digital_instruments.ini lacks the vanilla DISPLAY_0")
    if not any(x.startswith("ITEM_") for x in digi.sections()):
        problems.append("digital_instruments.ini lacks vanilla ITEM_n readouts")
    lod_cp = ini(os.path.join(data, "lods.ini"))
    lod_files = [lod_cp.get(x, "FILE", fallback="") for x in lod_cp.sections()
                 if x.startswith("LOD_")]
    if len(lod_files) != 4 or len(set(lod_files)) != 4:
        problems.append("lods.ini must list four distinct LOD KN5 files")
    else:
        for f in lod_files:
            if not os.path.exists(os.path.join(car_dir, f)):
                problems.append("lods.ini references missing " + f)
    notes.append("layout: Kunos-style folders, 4 LOD KN5, steer.ksanim, "
                 "driver3d/cameras/dash/sfx/skins/texture")
    notes.append("lights: vanilla VERSION=3 (brake / wet / KERS harvest flash), "
                 "DRS: WING_4 13-frame flap animation + 2 dash LEDs")
    notes.append("features: ERS 120 kW/4 MJ, DRS WING_4, 5 compounds (2 wet), 805 kW official")
    return problems, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--car-dir", required=True)
    ap.add_argument("--validation", required=True)
    ap.add_argument("--zip", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    problems, notes = check_car_dir(args.car_dir)

    with open(args.validation, "r", encoding="utf-8") as f:
        vr = json.load(f)
    if not vr.get("all_checks_passed"):
        problems.append("physics validation checks failed: %s" % vr.get("checks"))
    notes.append("physics: top %.1f km/h, 0-100 %.2f s, peak braking %.2f g" %
                 (vr["simulation"]["top_speed_kmh"],
                  vr["simulation"]["accel_times_s"].get("100", 0),
                  vr["simulation"]["braking_from_300_kmh"]["peak_decel_g"]))

    with zipfile.ZipFile(args.zip, "r") as z:
        names = set(z.namelist())
        for req in REQUIRED:
            if req not in names:
                problems.append("zip missing " + req)
        bad = [n for n in names if n.lower().endswith((".acd", ".lua")) or "ext_config" in n.lower()]
        if bad:
            problems.append("CSP-ish entries in zip: %s" % bad)
        notes.append("zip: %d entries, %d bytes" % (len(names), os.path.getsize(args.zip)))

    report = {"ok": not problems, "problems": problems, "notes": notes,
              "no_csp_dependency": not any("CSP" in p for p in problems)}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("\n".join("  - " + n for n in notes))
    if problems:
        print("VALIDATION FAILED:")
        print("\n".join("  ! " + p for p in problems))
        sys.exit(1)
    print("VALIDATION OK - vanilla AC, no CSP dependency, physics checked.")


if __name__ == "__main__":
    main()
