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
    "wing_controller.ini", "wing_animations.ini", "custom_shaders_patch",
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
    "content/cars/arb_rb20/data/lods.ini",
    "content/cars/arb_rb20/data/electronics.ini",
    "content/cars/arb_rb20/calibration.json",
    "LEIA-ME.txt",
]


def ini(path):
    cp = configparser.ConfigParser(strict=False, allow_no_value=True,
                                   inline_comment_prefixes=(";",))
    cp.optionxform = str
    cp.read(path)
    return cp


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
    for kn5 in ("arb_rb20.kn5", "collider.kn5"):
        p = os.path.join(car_dir, kn5)
        info = kn5format.read_kn5(p)
        nodes = list(kn5format.walk(info["root"]))
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
