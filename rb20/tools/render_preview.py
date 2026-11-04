"""
render_preview.py -- CPU software rasteriser for the car preview and UI badge.

Runs headless (Pillow + numpy only), so the same previews are produced in the
GitHub Actions runner and locally. Reads the same mesh.json that feeds the KN5.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mesh_core
from mesh_core import MATERIALS


def _norm(v):
    l = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / l for c in v)


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def load(mesh_json):
    if mesh_json and os.path.exists(mesh_json):
        with open(mesh_json, "r", encoding="utf-8") as f:
            return json.load(f)["objects"]
    return mesh_core.build_car()


def render(objects, path, width=1022, height=575):
    eye = (4.05, 2.05, 6.10)
    target = (0.0, 0.42, 0.05)
    fwd = _norm(tuple(target[i] - eye[i] for i in range(3)))
    right = _norm(_cross(fwd, (0.0, 1.0, 0.0)))
    up = _cross(right, fwd)
    f = (height / 2.0) / math.tan(math.radians(34.0) / 2.0)

    yy, xx = np.mgrid[0:height, 0:width]
    t = yy / height
    bg = np.zeros((height, width, 3), dtype=np.float32)
    bg[..., 0] = 26 + 22 * (1 - t)
    bg[..., 1] = 30 + 24 * (1 - t)
    bg[..., 2] = 38 + 30 * (1 - t)
    # soft elliptical contact shadow
    cx, cy, rx, ry = width * 0.50, height * 0.72, width * 0.28, height * 0.075
    d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    sh = np.clip(1.0 - d, 0, 1) ** 1.5 * 36.0
    for c in range(3):
        bg[..., c] -= sh
    img = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(img)

    light = _norm((-0.45, 0.85, 0.55))
    tris = []
    for o in objects:
        org = o.get("origin", (0, 0, 0))
        pos = o["positions"]
        idx = o["indices"]
        vn = o.get("normals")
        base = MATERIALS.get(o["material"], ((90, 90, 90), ""))[0]
        world = [(p[0] + org[0], p[1] + org[1], p[2] + org[2]) for p in pos]
        for k in range(0, len(idx), 3):
            a, b, c = world[idx[k]], world[idx[k+1]], world[idx[k+2]]
            e1 = tuple(b[i]-a[i] for i in range(3))
            e2 = tuple(c[i]-a[i] for i in range(3))
            face = _norm(_cross(e1, e2))
            if vn:
                # smooth per-vertex normals from the KN5 data (no faceting stripes)
                n = _norm(tuple(sum(vn[idx[k+j]][i] for j in range(3)) for i in range(3)))
                if _dot(n, face) < 0:
                    n = face
            else:
                n = face
            cam = []
            ok = True
            for p in (a, b, c):
                rel = tuple(p[i]-eye[i] for i in range(3))
                cam.append((_dot(rel, right), _dot(rel, up), _dot(rel, fwd)))
                if rel[2] < -0.001:
                    pass
            z = sum(p[2] for p in cam) / 3.0
            if z <= 0.25:
                continue
            scr = [(width/2 + p[0]/p[2]*f, height/2 - p[1]/p[2]*f) for p in cam]
            if any(not math.isfinite(v) for pt in scr for v in pt):
                continue
            lam = abs(_dot(n, light))
            shade = 0.24 + 0.76 * lam
            spec = 0.18 * (max(0.0, _dot(n, light)) ** 12)
            col = tuple(min(255, int(v * shade + 255 * spec)) for v in base)
            tris.append((z, scr, col))
    tris.sort(key=lambda t: -t[0])
    for z, scr, col in tris:
        draw.polygon(scr, fill=col)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
    except Exception:
        font = small = ImageFont.load_default()
    draw.text((28, 24), "ARB RB20", font=font, fill=(238, 240, 246))
    draw.text((28, 52), "2024 F1  ·  vanilla Assetto Corsa  ·  no CSP", font=small,
              fill=(168, 176, 194))
    img.save(path, quality=90)
    print("wrote", path, img.size, "triangles drawn", len(tris))


def badge(path, size=256):
    img = Image.new("RGB", (size, size), (11, 18, 42))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 6, size-6, size-6), radius=26, outline=(216, 35, 42), width=5)
    for k in range(-size, size, 34):
        d.line((k, size, k + size, 0), fill=(216, 35, 42), width=9)
    d.rounded_rectangle((24, 78, size-24, size-78), radius=12, fill=(11, 18, 42))
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 58)
        s = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17)
    except Exception:
        f = s = ImageFont.load_default()
    d.text((size/2, 108), "RB20", font=f, fill=(240, 242, 248), anchor="mm")
    d.text((size/2, 158), "2024", font=s, fill=(232, 179, 58), anchor="mm")
    img.save(path)
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", default="")
    ap.add_argument("--car-dir", required=True)
    args = ap.parse_args()
    objs = load(args.mesh)
    skins = os.path.join(args.car_dir, "skins", "default")
    ui = os.path.join(args.car_dir, "ui")
    os.makedirs(skins, exist_ok=True)
    os.makedirs(ui, exist_ok=True)
    preview = os.path.join(skins, "preview.jpg")
    render(objs, preview)
    badge(os.path.join(ui, "badge.png"))
    badge(os.path.join(ui, "logo.png"))
    # Standard Kunos car folder also carries logo.png at the root and a small
    # showroom preview under ui/.
    import shutil
    shutil.copyfile(os.path.join(ui, "logo.png"),
                    os.path.join(args.car_dir, "logo.png"))
    small = Image.open(preview).convert("RGB")
    small.thumbnail((320, 180))
    small.save(os.path.join(ui, "preview_small.png"))
    print("wrote", os.path.join(ui, "preview_small.png"))
    # Standard Kunos UI variants are derived from our own badge/preview only
    # after those exist (this step runs after calibrate).
    import vanilla_extras
    vanilla_extras.write_ui_extras(args.car_dir)


if __name__ == "__main__":
    main()
