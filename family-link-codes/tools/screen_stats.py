#!/usr/bin/env python3
"""Describe a PNG screenshot as text: statistics plus an ASCII rendering.

CI cannot show images inside a PR comment, but it can compute this and paste it,
which is enough to tell a rendered UI from a black screen.

    tools/screen_stats.py shot.png [--width 64]

Supports the PNGs that `adb exec-out screencap -p` produces: 8-bit RGB/RGBA,
non-interlaced, which is what every Android device emits.
"""
from __future__ import annotations

import struct
import sys
import zlib

RAMP = " .:-=+*#%@"


def read_png(path: str) -> tuple[int, int, list[list[tuple[int, int, int]]]]:
    with open(path, "rb") as handle:
        blob = handle.read()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos = 8
    width = height = depth = color_type = interlace = 0
    idat = bytearray()
    while pos < len(blob):
        (length,) = struct.unpack(">I", blob[pos : pos + 4])
        kind = blob[pos + 4 : pos + 8]
        data = blob[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            idat += data
        elif kind == b"IEND":
            break
    if depth != 8 or interlace != 0 or color_type not in (2, 6):
        raise ValueError(f"unsupported PNG (depth {depth}, colour {color_type}, interlace {interlace})")
    channels = 3 if color_type == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    rows: list[list[tuple[int, int, int]]] = []
    previous = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        line = bytearray(raw[offset + 1 : offset + 1 + stride])
        offset += 1 + stride
        if filter_type == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = previous[i]
                c = previous[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + predictor) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"bad filter {filter_type}")
        previous = line
        rows.append([(line[x], line[x + 1], line[x + 2]) for x in range(0, stride, channels)])
    return width, height, rows


def describe(path: str, width: int = 64) -> str:
    w, h, rows = read_png(path)
    total = w * h
    lum_sum = 0
    dark = 0
    colours: set[tuple[int, int, int]] = set()
    step_y = max(1, h // 240)
    step_x = max(1, w // 240)
    for y in range(0, h, step_y):
        for x in range(0, w, step_x):
            r, g, b = rows[y][x]
            lum = (299 * r + 587 * g + 114 * b) // 1000
            lum_sum += lum
            if lum < 12:
                dark += 1
            colours.add((r, g, b))
    sampled = len(range(0, h, step_y)) * len(range(0, w, step_x))
    mean = lum_sum / max(1, sampled)
    dark_pct = 100.0 * dark / max(1, sampled)

    out = [
        f"file: {path}",
        f"size: {w}x{h}",
        f"mean brightness: {mean:.1f}/255",
        f"near-black pixels: {dark_pct:.1f}%",
        f"distinct colours (sampled): {len(colours)}",
    ]
    if len(colours) == 1:
        out.append("verdict: one flat colour - the app is not drawing anything")
    elif dark_pct > 97:
        out.append("verdict: black screen - nothing rendered")
    elif len(colours) < 40:
        out.append("verdict: mostly flat - a splash or a plain background")
    else:
        out.append("verdict: real content on screen")

    out.append("")
    chars_w = width
    chars_h = max(8, int(chars_w * h / w * 0.5))
    for cy in range(chars_h):
        line = []
        for cx in range(chars_w):
            x0, x1 = cx * w // chars_w, max(cx * w // chars_w + 1, (cx + 1) * w // chars_w)
            y0, y1 = cy * h // chars_h, max(cy * h // chars_h + 1, (cy + 1) * h // chars_h)
            acc = n = 0
            for y in range(y0, y1, max(1, (y1 - y0) // 3) or 1):
                for x in range(x0, x1, max(1, (x1 - x0) // 3) or 1):
                    r, g, b = rows[y][x]
                    acc += (299 * r + 587 * g + 114 * b) // 1000
                    n += 1
            level = (acc // max(1, n)) * (len(RAMP) - 1) // 255
            line.append(RAMP[level])
        out.append("|" + "".join(line) + "|")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    width = 64
    if "--width" in argv:
        width = int(argv[argv.index("--width") + 1])
    try:
        print(describe(argv[1], width))
    except Exception as error:  # noqa: BLE001 - a bad screenshot must not fail CI
        print(f"could not read {argv[1]}: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
