"""
mesh_core.py -- parametric geometry for the ARB RB20 (2024 F1) Assetto Corsa mod.

Pure Python (no Blender needed). This module is the single source of truth for the
car's shape. The GitHub Actions job imports it INSIDE Blender (bpy) through
blender_model.py, applies real Blender modifiers, triangulates and writes
build/mesh.json; make_kn5.py can also use this module directly as a fallback.

Coordinates are Assetto Corsa Y-up: +X right, +Y up, +Z forward. The model is
built with the ground plane at Y=0 (tyre centres at Y=0.36). car.ini applies
GRAPHICS_OFFSET=0,-0.30,0 so the CG sits 0.30 m above the asphalt.

All dimensions were derived from published 2024 F1 regulations/specs and the
reference images and 3D reference models listed in ../references/REFERENCES.md.
This is an original, clean-sheet model: no team logos, no copied mesh data.
"""
from __future__ import annotations

import math
from typing import Iterable

# ---------------------------------------------------------------- dimensions
WHEELBASE = 3.600
CG_LOCATION = 0.455                     # front weight share
FRONT_Z = WHEELBASE * (1.0 - CG_LOCATION)
REAR_Z = -WHEELBASE * CG_LOCATION
FRONT_TRACK = 1.695
REAR_TRACK = 1.595
TYRE_R = 0.360                          # 720/720-18 -> 0.36 m radius
RIM_R = 0.229
FRONT_W = 0.305
REAR_W = 0.405
MAX_WIDTH = 2.000
LENGTH = 5.600

MATERIALS = {
    "RB20_BODY":   ((13, 24, 56),   "navy composite"),
    "RB20_CARBON": ((16, 18, 22),   "satin carbon"),
    "RB20_RED":    ((216, 35, 42),  "accent red"),
    "RB20_GOLD":   ((232, 179, 58), "accent gold"),
    "RB20_WHITE":  ((232, 233, 236),"white"),
    "RB20_TYRE":   ((20, 22, 26),   "Pirelli slick"),
    "RB20_RIM":    ((110, 115, 122),"machined rim"),
    "RB20_GLASS":  ((34, 48, 58),   "dark visor"),
    "RB20_BRAKE":  ((74, 64, 56),   "carbon disc"),
    "RB20_LIGHT":  ((220, 30, 30),  "rain light"),
    "RB20_LED":    ((30, 220, 100), "steering wheel DRS/ERS LEDs"),
}


def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vnorm(a):
    l = math.sqrt(_vdot(a, a)) or 1.0
    return (a[0] / l, a[1] / l, a[2] / l)


class Mesh:
    """Triangle soup builder with smooth/hard edge splitting and UVs."""

    def __init__(self, name, material, origin=(0.0, 0.0, 0.0),
                 cast_shadows=1, visible=1, smooth=45.0):
        self.name = name
        self.material = material
        self.origin = tuple(origin)
        self.cast_shadows = cast_shadows
        self.visible = visible
        self.smooth = smooth
        self.v: list[tuple[float, float, float]] = []
        self.uv: list[tuple[float, float]] = []
        self.f: list[tuple[int, int, int]] = []

    def vert(self, p, uv=None):
        self.v.append(tuple(p))
        self.uv.append(uv if uv is not None else self._planar_uv(p))
        return len(self.v) - 1

    @staticmethod
    def _planar_uv(p):
        # Bounded, deterministic UVs. Textures are near-solid colours with a
        # subtle carbon weave, so a simple planar projection is enough.
        return (0.5 + 0.11 * p[0], 0.5 + 0.075 * p[2])

    def tri(self, a, b, c):
        self.f.append((a, b, c))

    def quad(self, a, b, c, d):
        self.tri(a, b, c)
        self.tri(a, c, d)

    def box(self, centre, size, taper=0.0):
        """Axis-aligned box, `taper` shrinks the +Z face ( wedge shapes )."""
        cx, cy, cz = centre
        sx, sy, sz = (s / 2.0 for s in size)
        k = 1.0 - taper
        p = [
            (cx - sx, cy - sy, cz - sz), (cx + sx, cy - sy, cz - sz),
            (cx + sx, cy + sy, cz - sz), (cx - sx, cy + sy, cz - sz),
            (cx - sx * k, cy - sy * k, cz + sz), (cx + sx * k, cy - sy * k, cz + sz),
            (cx + sx * k, cy + sy * k, cz + sz), (cx - sx * k, cy + sy * k, cz + sz),
        ]
        i = [self.vert(q) for q in p]
        self.quad(i[0], i[3], i[2], i[1])   # -Z
        self.quad(i[4], i[5], i[6], i[7])   # +Z
        self.quad(i[0], i[1], i[5], i[4])   # -Y
        self.quad(i[3], i[7], i[6], i[2])   # +Y
        self.quad(i[0], i[4], i[7], i[3])   # -X
        self.quad(i[1], i[2], i[6], i[5])   # +X

    def loft(self, rings, cap=True, smooth=True):
        """Connect a list of equal-length point rings (each a closed polygon)."""
        idx = [[self.vert(p) for p in ring] for ring in rings]
        n = len(rings[0])
        for a, b in zip(idx, idx[1:]):
            for j in range(n):
                j2 = (j + 1) % n
                self.quad(a[j], a[j2], b[j2], b[j])
        if cap:
            back = [self.vert(p) for p in rings[0]]
            front = [self.vert(p) for p in rings[-1]]
            for j in range(1, n - 1):
                self.tri(back[0], back[j + 1], back[j])
                self.tri(front[0], front[j], front[j + 1])
        return idx

    def tube(self, p0, p1, r, seg=10, r1=None):
        """Cylinder (optionally conical) between two points."""
        p0, p1 = tuple(p0), tuple(p1)
        axis = _vnorm(_vsub(p1, p0))
        up = (0.0, 1.0, 0.0) if abs(axis[1]) < 0.9 else (1.0, 0.0, 0.0)
        u = _vnorm(_vcross(axis, up))
        w = _vnorm(_vcross(axis, u))
        r1 = r if r1 is None else r1
        rings = []
        for p, rr in ((p0, r), (p1, r1)):
            rings.append([(p[0] + rr * (u[0] * math.cos(t) + w[0] * math.sin(t)),
                           p[1] + rr * (u[1] * math.cos(t) + w[1] * math.sin(t)),
                           p[2] + rr * (u[2] * math.cos(t) + w[2] * math.sin(t)))
                          for t in (2 * math.pi * k / seg for k in range(seg))])
        self.loft(rings, cap=True)

    def cylinder_x(self, centre, radius, width, seg=28, inner=0.0):
        """Cylinder with its axis along X (wheel/tyre/rim primitive)."""
        cx, cy, cz = centre
        x0, x1 = cx - width / 2.0, cx + width / 2.0
        if inner <= 0.0:
            rings = []
            for x in (x0, x1):
                rings.append([(x, cy + radius * math.cos(t), cz + radius * math.sin(t))
                              for t in (2 * math.pi * k / seg for k in range(seg))])
            self.loft(rings, cap=True)
        else:
            # Annulus with an outer wall, inner wall and two end faces.
            n = seg
            outer0 = [self.vert((x0, cy + radius * math.cos(t), cz + radius * math.sin(t)))
                      for t in (2 * math.pi * k / n for k in range(n))]
            outer1 = [self.vert((x1, cy + radius * math.cos(t), cz + radius * math.sin(t)))
                      for t in (2 * math.pi * k / n for k in range(n))]
            inner0 = [self.vert((x0, cy + inner * math.cos(t), cz + inner * math.sin(t)))
                      for t in (2 * math.pi * k / n for k in range(n))]
            inner1 = [self.vert((x1, cy + inner * math.cos(t), cz + inner * math.sin(t)))
                      for t in (2 * math.pi * k / n for k in range(n))]
            for j in range(n):
                j2 = (j + 1) % n
                self.quad(outer0[j], outer1[j], outer1[j2], outer0[j2])
                self.quad(inner0[j2], inner1[j2], inner1[j], inner0[j])
                self.quad(outer0[j], outer0[j2], inner0[j2], inner0[j])
                self.quad(outer1[j2], outer1[j], inner1[j], inner1[j2])

    def aerofoil(self, centre, span, chord, thickness, angle_deg=0.0, seg=7):
        """Simple cambered wing: closed aerofoil section extruded along X."""
        cx, cy, cz = centre
        a = math.radians(angle_deg)
        ca, sa = math.cos(a), math.sin(a)
        # NACA-ish upper/lower outline in the Z/Y plane, nose at -chord/2.
        profile = []
        for k in range(seg + 1):
            s = k / seg
            z = -chord / 2.0 + chord * s
            camber = 0.06 * chord * math.sin(math.pi * s)
            thick = thickness * (0.30 + 0.70 * math.sin(math.pi * s) ** 0.6)
            profile.append((z, camber + thick / 2.0))
        for k in range(seg, -1, -1):
            s = k / seg
            z = -chord / 2.0 + chord * s
            camber = 0.06 * chord * math.sin(math.pi * s)
            thick = thickness * (0.30 + 0.70 * math.sin(math.pi * s) ** 0.6)
            profile.append((z, camber - thick / 2.0))
        rings = []
        for x in (cx - span / 2.0, cx + span / 2.0):
            rings.append([(x, cy + (dy * ca - dz * sa), cz + (dy * sa + dz * ca))
                          for dz, dy in profile])
        self.loft(rings, cap=True)

    def finish(self):
        """Return a KN5-ready soup: positions, normals, UVs, indices."""
        if not self.f:
            return None
        # 1. Face normals + signed volume (winding fix for closed solids).
        fn = []
        vol = 0.0
        for ia, ib, ic in self.f:
            a, b, c = self.v[ia], self.v[ib], self.v[ic]
            n = _vcross(_vsub(b, a), _vsub(c, a))
            fn.append(_vnorm(n))
            vol += _vdot(a, _vcross(b, c)) / 6.0
        if vol < 0.0:
            self.f = [(a, c, b) for a, b, c in self.f]
            fn = [(-n[0], -n[1], -n[2]) for n in fn]
        self.fixed = True

        # 2. Cluster incident face normals per vertex (hard-edge splitting).
        incident: list[list[tuple[int, int]]] = [[] for _ in self.v]
        for fi, (ia, ib, ic) in enumerate(self.f):
            for ci, vi in enumerate((ia, ib, ic)):
                incident[vi].append((fi, ci))
        cos_limit = math.cos(math.radians(self.smooth))
        remap: list[list[int]] = [[] for _ in self.v]
        positions, normals, uvs = [], [], []
        for vi, inc in enumerate(incident):
            groups: list[list[tuple[int, int]]] = []
            for item in inc:
                placed = False
                for g in groups:
                    if _vdot(fn[g[0][0]], fn[item[0]]) >= cos_limit:
                        g.append(item)
                        placed = True
                        break
                if not placed:
                    groups.append([item])
            for g in groups:
                n = (0.0, 0.0, 0.0)
                for fi, _ in g:
                    n = (n[0] + fn[fi][0], n[1] + fn[fi][1], n[2] + fn[fi][2])
                n = _vnorm(n)
                remap[vi].append(len(positions))
                positions.append(self.v[vi])
                normals.append(n)
                uvs.append(self.uv[vi])

        indices = []
        for fi, (ia, ib, ic) in enumerate(self.f):
            for vi in (ia, ib, ic):
                best, bestdot = None, -2.0
                for out in remap[vi]:
                    d = _vdot(normals[out], fn[fi])
                    if d > bestdot:
                        best, bestdot = out, d
                indices.append(best)
        return {
            "name": self.name,
            "material": self.material,
            "origin": self.origin,
            "cast_shadows": self.cast_shadows,
            "visible": self.visible,
            "positions": positions,
            "normals": normals,
            "uv": uvs,
            "indices": indices,
        }


def _superellipse(z, half_w, y0, y1, n=14, exponent=0.62):
    """Rounded-rectangle cross-section ring at longitudinal position z."""
    cy = (y0 + y1) / 2.0
    hy = (y1 - y0) / 2.0
    ring = []
    for k in range(n):
        t = 2 * math.pi * k / n
        c, s = math.cos(t), math.sin(t)
        x = half_w * math.copysign(abs(c) ** exponent, c)
        y = cy + hy * math.copysign(abs(s) ** exponent, s)
        ring.append((x, y, z))
    return ring


def _sidepod(sign, z, x_in, x_out, y0, y1):
    x_in, x_out = sign * x_in, sign * x_out
    return [(x_in, y0, z), (x_out, y0, z), (x_out, y1, z), (x_in, y1, z)]


# ------------------------------------------------------------------ the car
def build_car_raw():
    """Return the editable Mesh builders (used by Blender)."""
    objs: list[Mesh] = []

    def M(name, mat, **kw):
        m = Mesh(name, mat, **kw)
        objs.append(m)
        return m

    # ---- monocoque / engine cover: lofted superellipse sections -------------
    body = M("BODY", "RB20_BODY")
    sections = [
        (2.72, 0.085, 0.145, 0.225),
        (2.40, 0.135, 0.115, 0.300),
        (1.95, 0.205, 0.095, 0.410),
        (1.35, 0.275, 0.085, 0.510),
        (0.80, 0.310, 0.080, 0.590),
        (0.25, 0.335, 0.080, 0.660),
        (-0.35, 0.330, 0.080, 0.660),
        (-0.95, 0.290, 0.085, 0.565),
        (-1.50, 0.225, 0.100, 0.455),
        (-2.02, 0.135, 0.135, 0.340),
        (-2.22, 0.080, 0.170, 0.285),
    ]
    body.loft([_superellipse(*s) for s in sections], cap=True)

    # nose tip + front bulkhead accent
    nose = M("NOSE", "RB20_CARBON")
    nose.loft([_superellipse(2.72, 0.085, 0.145, 0.225),
               _superellipse(2.88, 0.045, 0.165, 0.205)], cap=True)

    # ---- floor + venturi tunnels + diffuser --------------------------------
    floor = M("FLOOR", "RB20_CARBON")
    floor.box((0.0, 0.052, 0.10), (1.94, 0.028, 4.55))
    # tunnel roofs (two ground-effect channels)
    for s in (-1, 1):
        tun = M("TUNNEL_%s" % ("L" if s < 0 else "R"), "RB20_CARBON")
        tun.box((s * 0.55, 0.080, -0.15), (0.62, 0.055, 2.80), taper=0.25)
        edge = M("FLOOR_EDGE_%s" % ("L" if s < 0 else "R"), "RB20_CARBON")
        edge.box((s * 0.965, 0.075, -0.10), (0.07, 0.055, 2.90))
        for k in range(5):
            fin = M("FLOOR_FIN_%s%d" % ("L" if s < 0 else "R", k), "RB20_CARBON")
            fin.box((s * (0.80 + 0.02 * k), 0.090, 1.55 - 0.55 * k),
                    (0.02, 0.075, 0.34), taper=0.4)
    diff = M("DIFFUSER", "RB20_CARBON")
    diff.box((0.0, 0.145, -2.00), (1.78, 0.20, 0.52), taper=0.15)
    for s in (-1, 1):
        for k in range(3):
            f = M("DIFF_FIN_%s%d" % ("L" if s < 0 else "R", k), "RB20_CARBON")
            f.box((s * (0.30 + 0.28 * k), 0.205, -1.98), (0.018, 0.26, 0.46), taper=0.3)

    # ---- sidepods (coke-bottle), inlets, bargeboards -----------------------
    for s, tag in ((-1, "L"), (1, "R")):
        pod = M("SIDEPOD_" + tag, "RB20_BODY")
        pod.loft([
            _sidepod(s, 1.02, 0.300, 0.560, 0.230, 0.455),
            _sidepod(s, 0.62, 0.305, 0.780, 0.130, 0.455),
            _sidepod(s, 0.10, 0.310, 0.915, 0.090, 0.430),
            _sidepod(s, -0.55, 0.330, 0.860, 0.090, 0.385),
            _sidepod(s, -1.10, 0.360, 0.600, 0.110, 0.305),
            _sidepod(s, -1.45, 0.330, 0.420, 0.135, 0.255),
        ], cap=True)
        inlet = M("INLET_" + tag, "RB20_CARBON")
        inlet.box((s * 0.430, 0.340, 1.025), (0.245, 0.205, 0.045))
        bar = M("BARGEBOARD_" + tag, "RB20_CARBON")
        bar.box((s * 0.760, 0.245, 1.48), (0.035, 0.30, 0.65), taper=0.5)
        mirror = M("MIRROR_" + tag, "RB20_RED")
        mirror.box((s * 0.655, 0.545, 0.72), (0.16, 0.075, 0.10))
        mirror_stalk = M("MIRROR_STALK_" + tag, "RB20_CARBON")
        mirror_stalk.tube((s * 0.515, 0.500, 0.72), (s * 0.655, 0.535, 0.72), 0.016, 8)

    # ---- airbox, shark fin, engine cover accents ---------------------------
    airbox = M("AIRBOX", "RB20_CARBON")
    airbox.loft([
        [(x, y, z) for x, y in ((-0.13, 0.63), (0.13, 0.63), (0.13, 0.83), (-0.13, 0.83))]
        for z in (0.42, 0.10)],
        cap=True)
    for k in range(3):
        fin = M("SHARK_FIN_%d" % k, "RB20_CARBON")
        fin.box((0.0, 0.72 - 0.055 * k, -0.25 - 0.55 * k),
                (0.028, 0.24 - 0.045 * k, 1.05), taper=0.55)
    # red/gold accent stripes along the engine cover and nose (no logos)
    for k, mat in enumerate(("RB20_RED", "RB20_GOLD")):
        stripe = M("ACCENT_%d" % k, mat)
        stripe.box((0.0, 0.655 - 0.012 * k, -0.52), (0.10 + 0.03 * k, 0.012, 1.55))
    nosestripe = M("NOSE_STRIPE", "RB20_RED")
    nosestripe.box((0.0, 0.222, 2.34), (0.105, 0.014, 0.72), taper=0.55)

    # ---- halo + cockpit ----------------------------------------------------
    halo = M("HALO", "RB20_CARBON")
    # main hoop: arc from left rear to right rear over the cockpit
    hoop = []
    for k in range(13):
        t = math.pi * k / 12.0
        hoop.append((-0.335 * math.cos(t), 0.665 + 0.115 * math.sin(t), 0.86))
    for a, b in zip(hoop, hoop[1:]):
        halo.tube(a, b, 0.027, 8)
    halo.tube((0.0, 0.780, 0.86), (-0.02, 0.500, 1.48), 0.026, 8)
    halo.tube((-0.335, 0.665, 0.86), (-0.335, 0.520, 0.42), 0.022, 8)
    halo.tube((0.335, 0.665, 0.86), (0.335, 0.520, 0.42), 0.022, 8)

    cockpit = M("COCKPIT_HR", "RB20_GLASS")
    cockpit.box((0.0, 0.315, 0.68), (0.50, 0.20, 0.72), taper=0.45)   # seat
    cockpit.box((0.0, 0.505, 1.10), (0.46, 0.055, 0.10))             # dash
    cockpit.box((0.0, 0.430, 0.34), (0.42, 0.20, 0.24))              # driver back
    for s in (-1, 1):
        cockpit.box((s * 0.255, 0.465, 0.70), (0.055, 0.19, 0.70))    # side padding
    steer = M("STEER_HR", "RB20_CARBON")
    steer.cylinder_x((0.0, 0.545, 1.02), 0.135, 0.032, seg=20)
    steer.box((0.0, 0.585, 1.002), (0.155, 0.070, 0.012))             # display
    steer.box((0.0, 0.505, 1.002), (0.185, 0.030, 0.012))
    for s in (-1, 1):
        steer.box((s * 0.105, 0.545, 1.002), (0.065, 0.130, 0.022))
    # Steering-wheel DRS LEDs, like the real RB20 wheel: one for "DRS
    # available" and one for "DRS enabled". digital_instruments.ini (vanilla
    # ACD DRS_AVAILABLE_n / DRS_ENABLED_n) switches their emissive.
    avail = M("DASH_DRS_AVAIL", "RB20_LED")
    avail.box((-0.055, 0.596, 1.012), (0.022, 0.010, 0.006))
    enabled = M("DASH_DRS", "RB20_LED")
    enabled.box((0.055, 0.596, 1.012), (0.022, 0.010, 0.006))
    # Vanilla digital_instruments.ini [DISPLAY_0] target, as on the Kunos F1
    # template: the dash display is a real mesh so ITEM_n readouts can render.
    display = M("DASH_DISPLAY", "RB20_GLASS")
    display.box((0.0, 0.558, 1.014), (0.100, 0.034, 0.004))
    # Vanilla analog_instruments.ini needles. Their geometry is local to their
    # own origin so AC can rotate each dummy without swinging it around the
    # car origin. They sit inside the dark display and are effectively hidden.
    for i, tag in enumerate(("RPM", "SPEED", "WATER", "FUEL")):
        x = (i - 1.5) * 0.022
        needle = M("ARROW_" + tag, "RB20_LED", origin=(x, 0.560, 1.017))
        needle.box((0.0, 0.0, 0.0), (0.003, 0.010, 0.002))

    # ---- front wing: mainplane, 3 flaps, endplates -------------------------
    fw = M("WING_FRONT", "RB20_CARBON", smooth=180)
    fw.aerofoil((0.0, 0.078, 2.865), 1.94, 0.30, 0.038, 2.0)
    for k in range(3):
        flap = M("FW_FLAP_%d" % k, "RB20_RED" if k == 2 else "RB20_CARBON", smooth=180)
        flap.aerofoil((0.0, 0.115 + 0.072 * k, 2.735 - 0.070 * k),
                      1.88, 0.17, 0.022, 12.0 + 8.0 * k)
    for s, tag in ((-1, "L"), (1, "R")):
        ep = M("FW_ENDPLATE_" + tag, "RB20_BODY")
        ep.box((s * 0.975, 0.175, 2.805), (0.022, 0.275, 0.40), taper=0.35)
        nosecone = M("FW_NOSE_MOUNT_" + tag, "RB20_CARBON")
        nosecone.tube((s * 0.06, 0.215, 2.78), (s * 0.10, 0.090, 2.86), 0.020, 8)

    # ---- rear wing + beam wing + endplates --------------------------------
    rw = M("WING_REAR", "RB20_CARBON", smooth=180)
    rw.aerofoil((0.0, 0.845, -2.330), 1.045, 0.30, 0.040, 14.0)
    rwf = M("WING_REAR_FLAP", "RB20_RED", smooth=180)
    rwf.aerofoil((0.0, 0.985, -2.415), 1.045, 0.215, 0.026, 26.0)
    beam = M("BEAM_WING", "RB20_CARBON", smooth=180)
    beam.aerofoil((0.0, 0.455, -2.290), 0.90, 0.22, 0.028, 10.0)
    for s, tag in ((-1, "L"), (1, "R")):
        ep = M("RW_ENDPLATE_" + tag, "RB20_BODY")
        ep.box((s * 0.525, 0.845, -2.365), (0.020, 0.44, 0.50), taper=0.18)
        sup = M("RW_SUPPORT_" + tag, "RB20_CARBON")
        sup.tube((s * 0.14, 0.36, -2.12), (s * 0.14, 0.82, -2.34), 0.026, 8)

    # ---- rear crash structure, exhaust, rain light, T-cam -----------------
    rear = M("REAR_STRUCTURE", "RB20_CARBON")
    rear.box((0.0, 0.285, -2.16), (0.30, 0.22, 0.34), taper=0.55)
    exh = M("EXHAUST", "RB20_RIM")
    exh.tube((0.0, 0.330, -2.02), (0.0, 0.330, -2.32), 0.055, 12, r1=0.048)
    # ---- real F1 rear light cluster ----------------------------------------
    # FIA 2024 Technical Regs art. 14.3 / Sporting Regs art. 26.11: one red
    # rear light, always lit with intermediate/full-wet tyres, brighter under
    # braking and flashing while the MGU-K harvests. Vanilla lights.ini drives
    # these meshes by node name; each one has its own node so it can be
    # controlled independently (brake / steady wet / ERS harvest repeaters).
    light = M("RAIN_LIGHT", "RB20_LIGHT")
    light.box((0.0, 0.245, -2.33), (0.085, 0.060, 0.025))
    wet = M("RAIN_LIGHT_WET", "RB20_LIGHT")
    wet.box((0.0, 0.281, -2.332), (0.055, 0.020, 0.020))
    for s, tag in ((-1, "L"), (1, "R")):
        led = M("RAIN_LIGHT_" + tag, "RB20_LIGHT")
        led.box((s * 0.528, 0.865, -2.360), (0.014, 0.045, 0.030))
    cam = M("T_CAM", "RB20_CARBON")
    cam.box((0.0, 0.790, 0.13), (0.12, 0.10, 0.17), taper=0.4)

    # ---- wheels + suspension ----------------------------------------------
    wheel_defs = [
        ("LF", -FRONT_TRACK / 2, FRONT_Z, FRONT_W, 1),
        ("RF", +FRONT_TRACK / 2, FRONT_Z, FRONT_W, -1),
        ("LR", -REAR_TRACK / 2, REAR_Z, REAR_W, 1),
        ("RR", +REAR_TRACK / 2, REAR_Z, REAR_W, -1),
    ]
    for tag, x, z, width, outward in wheel_defs:
        origin = (x, TYRE_R, z)
        # dummy translate: geometry is local to the wheel centre
        w = M("WHEEL_" + tag, "RB20_TYRE", origin=origin)
        w.cylinder_x((0, 0, 0), TYRE_R, width, seg=32, inner=RIM_R - 0.004)
        # rounded shoulders (two thin rings slightly smaller than R)
        for s in (-1, 1):
            w.cylinder_x((s * (width / 2 - 0.018), 0, 0), TYRE_R - 0.012,
                         0.036, seg=32, inner=RIM_R - 0.004)
        rim = M("RIM_" + tag, "RB20_RIM", origin=origin)
        rim.cylinder_x((0, 0, 0), RIM_R - 0.006, width - 0.070, seg=28, inner=0.055)
        cover = M("COVER_" + tag, "RB20_BODY", origin=origin)
        cover.cylinder_x((outward * (width / 2 - 0.012), 0, 0), RIM_R - 0.012,
                         0.014, seg=28, inner=0.075)
        for k in range(10):
            a = 2 * math.pi * k / 10
            spoke = M("SPOKE_%s_%d" % (tag, k), "RB20_RIM", origin=origin)
            spoke.tube((outward * (width / 2 - 0.020), 0.060 * math.cos(a), 0.060 * math.sin(a)),
                       (outward * (width / 2 - 0.020), (RIM_R - 0.02) * math.cos(a),
                        (RIM_R - 0.02) * math.sin(a)), 0.012, 6)
        disc = M("DISC_" + tag, "RB20_BRAKE", origin=origin)
        disc.cylinder_x((-outward * 0.045, 0, 0), 0.165, 0.026, seg=24, inner=0.060)
        cal = M("CALIPER_" + tag, "RB20_GOLD", origin=origin)
        cal.box((-outward * 0.045, -0.150, 0.020), (0.055, 0.085, 0.090))

        # wishbones: chassis points are expressed relative to the wheel centre
        sgn = 1 if x < 0 else -1
        sus = M("SUSP_" + tag, "RB20_CARBON", origin=origin)
        chassis_x = sgn * (abs(x) - 0.12)
        for dy, dz in ((0.115, 0.14), (0.115, -0.14), (-0.115, 0.14), (-0.115, -0.14)):
            sus.tube((chassis_x, dy, dz), (sgn * 0.055, dy * 0.72, dz * 0.35), 0.019, 8)
        sus.tube((chassis_x, -0.10, 0.02), (sgn * 0.06, 0.10, -0.04), 0.016, 8)  # pushrod
        sus.tube((chassis_x, 0.00, -0.12), (sgn * 0.05, 0.00, -0.10), 0.013, 8)   # track rod

    for m in objs:                 # make winding consistent for Blender too
        if not m.f:
            continue
        vol = 0.0
        for ia, ib, ic in m.f:
            a, b, c = m.v[ia], m.v[ib], m.v[ic]
            vol += _vdot(a, _vcross(b, c)) / 6.0
        if vol < 0.0:
            m.f = [(a, c, b) for a, b, c in m.f]
    return objs


def build_car():
    return [o for o in (m.finish() for m in build_car_raw()) if o]


def build_collider():
    """One low-poly box used by collider.kn5 (bottom/kerb collisions)."""
    m = Mesh("COLLIDER", "RB20_CARBON")
    m.box((0.0, 0.18, 0.10), (1.90, 0.30, 4.60))
    return [m.finish()]


if __name__ == "__main__":
    import json
    car = build_car()
    tris = sum(len(o["indices"]) // 3 for o in car)
    verts = sum(len(o["positions"]) for o in car)
    print(json.dumps({"objects": len(car), "triangles": tris, "vertices": verts,
                      "materials": sorted({o["material"] for o in car})}, indent=2))
