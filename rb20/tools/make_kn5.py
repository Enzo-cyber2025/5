"""
make_kn5.py -- turn build/mesh.json (Blender output) into vanilla AC .kn5 files.

If mesh.json is absent (e.g. running outside CI), mesh_core.build_car() is used
directly, so the mod can always be rebuilt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import kn5format
import mesh_core
import textures


def load_objects(mesh_json):
    if mesh_json and os.path.exists(mesh_json):
        with open(mesh_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        objs = data["objects"]
        print("mesh source: %s (%s)" % (mesh_json, data.get("meta", {}).get("generator", "?")))
    else:
        objs = mesh_core.build_car()
        print("mesh source: mesh_core.build_car() (Blender mesh.json not found)")
    for o in objs:
        if len(o["positions"]) >= 65535:
            raise ValueError("%s exceeds KN5 16-bit index limit" % o["name"])
        if len(o["indices"]) % 3:
            raise ValueError("%s has a non-triangular index buffer" % o["name"])
    return objs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", default="")
    ap.add_argument("--car-dir", required=True)
    ap.add_argument("--skins-dir", default="")
    args = ap.parse_args()

    objs = load_objects(args.mesh)
    used = sorted({o["material"] for o in objs})
    mats = textures.build_materials(used)
    texs = textures.build_textures(used)
    os.makedirs(args.car_dir, exist_ok=True)

    # Kunos cars ship a four-step LOD chain referenced by data/lods.ini. Each
    # level drops the smallest triangle soups; the KN5 format and vanilla
    # shaders are identical, so no CSP or third-party mesh is involved.
    def ntri(o):
        return len(o["indices"]) // 3

    biggest = max(objs, key=ntri)
    lods = [
        ("arb_rb20.kn5", objs, 0),
        ("arb_rb20_LOD_B.kn5", [o for o in objs if ntri(o) >= 24], 24),
        ("arb_rb20_LOD_C.kn5", [o for o in objs if ntri(o) >= 96], 96),
        ("arb_rb20_LOD_D.kn5", [o for o in objs if ntri(o) >= 240], 240),
    ]
    kn5_paths = []
    for name, subset, minimum in lods:
        if not subset:
            subset = [biggest]
        p = os.path.join(args.car_dir, name)
        size = kn5format.write_kn5(p, texs, mats, subset, root_name="ARB_RB20")
        kn5_paths.append(p)
        print("wrote %s (%d bytes, %d objects, %d triangles, min %d tri/obj)" %
              (p, size, len(subset), sum(ntri(o) for o in subset), minimum))

    col = mesh_core.build_collider()
    col_path = os.path.join(args.car_dir, "collider.kn5")
    csize = kn5format.write_kn5(col_path, texs, mats, col, root_name="ARB_RB20_COLLIDER")
    print("wrote %s (%d bytes)" % (col_path, csize))

    # Keep a copy of each texture in the default skin: AC replaces KN5 textures
    # with identically named files from skins/<skin>/, so users can repaint it.
    if args.skins_dir:
        os.makedirs(args.skins_dir, exist_ok=True)
        for name, blob in texs:
            with open(os.path.join(args.skins_dir, name), "wb") as f:
                f.write(blob)

    # Structural round-trip check with our independent reader.
    for p in kn5_paths + [col_path]:
        info = kn5format.read_kn5(p)
        nodes = list(kn5format.walk(info["root"]))
        meshes = [n for n in nodes if n["class"] == 2]
        tris = sum(n["index_count"] // 3 for n in meshes)
        print("read back %s: v%d, %d textures, %d materials, %d nodes, %d tris" %
              (os.path.basename(p), info["version"], len(info["textures"]),
               len(info["materials"]), len(nodes), tris))
        if not meshes:
            raise ValueError("KN5 contains no meshes")


if __name__ == "__main__":
    main()
