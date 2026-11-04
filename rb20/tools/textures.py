"""
textures.py -- generate vanilla-AC-compatible DXT1 DDS textures (no CSP needed).

The KN5 embeds one small DXT1 diffuse texture per material. ksPerPixel is the
shader ksEditor itself uses as a fallback, so it needs only txDiffuse and six
scalar properties. No normal/specular/CSP-only shader overrides are used.

DDS layout follows the standard Microsoft header (the same one Kunos models use):
magic "DDS ", DDS_HEADER(124), DDS_PIXELFORMAT with FOURCC "DXT1", then 8 bytes
per 4x4 block.  A tiny pure-Python BC1 encoder is enough for our near-solid
colours + carbon weave.
"""
from __future__ import annotations

import math
import struct

from mesh_core import MATERIALS


def _rgb565(r, g, b):
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _un565(v):
    r = ((v >> 11) & 31) * 255 / 31.0
    g = ((v >> 5) & 63) * 255 / 63.0
    b = (v & 31) * 255 / 31.0
    return (r, g, b)


def _bc1_block(pixels):
    """Encode one 4x4 list of (r,g,b) into an 8-byte BC1/DXT1 block."""
    # Endpoints from the lightest/darkest pixel (luminance ordered).
    ordered = sorted(pixels, key=lambda c: 0.299*c[0] + 0.587*c[1] + 0.114*c[2])
    lo, hi = ordered[0], ordered[-1]
    c0 = _rgb565(*hi)
    c1 = _rgb565(*lo)
    if c1 > c0:
        c0, c1 = c1, c0
    a, b = _un565(c0), _un565(c1)
    palette = [a, b,
               tuple((2*a[i] + b[i]) / 3.0 for i in range(3)),
               tuple((a[i] + 2*b[i]) / 3.0 for i in range(3))]
    bits = 0
    for k, px in enumerate(pixels):
        best = min(range(4), key=lambda j: sum((px[i]-palette[j][i])**2 for i in range(3)))
        bits |= best << (2 * k)
    return struct.pack("<HHI", c0, c1, bits)


def dds_dxt1(width, height, pixel_fn):
    """pixel_fn(x, y) -> (r,g,b). Width/height must be multiples of 4."""
    if width % 4 or height % 4:
        raise ValueError("DXT1 needs dimensions divisible by 4")
    payload = bytearray()
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            block = [pixel_fn(bx + j % 4, by + j // 4) for j in range(16)]
            payload += _bc1_block(block)

    ddspf = struct.pack("<II4sIIIII", 32, 0x4, b"DXT1", 0, 0, 0, 0, 0)
    header = struct.pack("<4s", b"DDS ")
    header += struct.pack("<7I", 124, 0x00081007, height, width,
                          len(payload), 0, 0)
    header += b"\x00" * 44                     # dwReserved1[11]
    header += ddspf
    header += struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    assert len(header) == 128, len(header)
    return bytes(header) + bytes(payload)


def _pixel_factory(name, rgb):
    r, g, b = rgb
    if name == "RB20_CARBON":
        def fn(x, y):
            weave = 18 if ((x // 2 + y // 2) % 2 == 0) else -8
            return (r + weave, g + weave, b + weave)
        return fn
    if name == "RB20_TYRE":
        def fn(x, y):
            groove = -6 if (y % 16) < 2 else 4
            return (r + groove, g + groove, b + groove)
        return fn
    if name == "RB20_RIM":
        def fn(x, y):
            brushed = 14 * math.sin((x + y) * 0.6)
            return (r + brushed, g + brushed, b + brushed)
        return fn
    if name == "RB20_LIGHT":
        def fn(x, y):
            pulse = 18 * math.sin(x * 0.4) * math.sin(y * 0.4)
            return (r + pulse, g, b)
        return fn
    def fn(x, y):
        grain = 5 * math.sin(x * 1.7) * math.cos(y * 1.3)
        return (r + grain, g + grain, b + grain)
    return fn


def texture_name(material):
    return material.lower() + ".dds"


def build_textures(used_materials, size=256):
    out = []
    for name in used_materials:
        if name not in MATERIALS:
            raise KeyError(name)
        rgb = MATERIALS[name][0]
        out.append((texture_name(name),
                    dds_dxt1(size, size, _pixel_factory(name, rgb))))
    return out


def build_materials(used_materials):
    """Vanilla ksPerPixel materials, as ksEditor's own default fallback."""
    out = []
    for name in sorted(used_materials):
        emissive = 0.8 if name == "RB20_LIGHT" else 0.0
        metallic = 0.45 if name in ("RB20_RIM", "RB20_BRAKE") else 0.12
        props = {
            "ksAmbient": 0.42,
            "ksDiffuse": 0.80 if name != "RB20_GLASS" else 0.55,
            "ksSpecular": metallic,
            "ksSpecularEXP": 120.0 if metallic > 0.3 else 45.0,
            "ksEmissive": emissive,
            "ksAlphaRef": 0.0,
        }
        out.append({
            "name": name,
            "shader": "ksPerPixel",
            "blend": 0,
            "alpha_tested": 0,
            "depth_mode": 0,
            "props": props,
            "maps": [("txDiffuse", 0, texture_name(name))],
        })
    return out


if __name__ == "__main__":
    import mesh_core
    used = sorted({o["material"] for o in mesh_core.build_car()})
    t = build_textures(used)
    print([(n, len(d)) for n, d in t])
    print("materials", [m["shader"] for m in build_materials(used)])
