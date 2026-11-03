"""
kn5format.py -- minimal, dependency-free reader/writer for Assetto Corsa KN5 v5.

Version 5 is the vanilla (non-CSP) container used by Kunos models. It stores:
  magic "sc6969" + int32 version
  textures: (active, name, bytes)  -- DDS/PNG payloads embedded in the file
  materials: shader name, blend flags, shader properties, texture mappings
  node tree: dummies (class 1, 4x4 matrix) and meshes (class 2)
  mesh vertex record (44 bytes): position(3f), normal(3f), uv(2f), tangent(3f)

Written from the public on-disk format; no Kunos code or CSP is used.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

MAGIC = b"sc6969"
VERSION = 5
VERTEX_FLOATS = 11
VERTEX_BYTES = VERTEX_FLOATS * 4


# ------------------------------------------------------------------- writer
class W:
    def __init__(self):
        self.buf = bytearray()

    def raw(self, b):
        self.buf += b

    def pack(self, fmt, *v):
        self.buf += struct.pack("<" + fmt, *v)

    def i32(self, v):
        self.pack("i", int(v))

    def u8(self, v):
        self.pack("B", int(v))

    def f32(self, v):
        self.pack("f", float(v))

    def s(self, v):
        b = str(v).encode("utf-8")
        self.i32(len(b))
        self.raw(b)


def _tangents(positions, uvs, indices):
    """One tangent per triangle, copied to its three corners (last wins)."""
    tangents = [(1.0, 0.0, 0.0)] * len(positions)
    for k in range(0, len(indices), 3):
        i0, i1, i2 = indices[k:k + 3]
        p0, p1, p2 = positions[i0], positions[i1], positions[i2]
        t0, t1, t2 = uvs[i0], uvs[i1], uvs[i2]
        e1 = [p1[j] - p0[j] for j in range(3)]
        e2 = [p2[j] - p0[j] for j in range(3)]
        du1, dv1 = t1[0] - t0[0], t1[1] - t0[1]
        du2, dv2 = t2[0] - t0[0], t2[1] - t0[1]
        det = du1 * dv2 - du2 * dv1
        if abs(det) < 1e-12:
            t = (1.0, 0.0, 0.0)
        else:
            r = 1.0 / det
            t = (r * (dv2 * e1[0] - dv1 * e2[0]),
                 r * (dv2 * e1[1] - dv1 * e2[1]),
                 r * (dv2 * e1[2] - dv1 * e2[2]))
            n = math.sqrt(sum(c * c for c in t)) or 1.0
            t = (t[0] / n, t[1] / n, t[2] / n)
        tangents[i0] = tangents[i1] = tangents[i2] = t
    return tangents


def _vertex_blob(obj):
    pos = obj["positions"]
    nrm = obj["normals"]
    uv = obj["uv"]
    idx = obj["indices"]
    if max(idx) >= 65535 or len(pos) >= 65535:
        raise ValueError("%s: KN5 uses 16-bit vertex indices (max 65534)" % obj["name"])
    tan = _tangents(pos, uv, idx)
    out = bytearray()
    for i in range(len(pos)):
        p, n, u, t = pos[i], nrm[i], uv[i], tan[i]
        out += struct.pack("<11f", p[0], p[1], p[2],
                           n[0], n[1], n[2],
                           u[0], -u[1],            # AC flips V
                           t[0], t[1], t[2])
    return bytes(out), idx


def _sphere(pos):
    if not pos:
        return (0.0, 0.0, 0.0, 0.0)
    cx = sum(p[0] for p in pos) / len(pos)
    cy = sum(p[1] for p in pos) / len(pos)
    cz = sum(p[2] for p in pos) / len(pos)
    r = max(math.sqrt((p[0]-cx)**2 + (p[1]-cy)**2 + (p[2]-cz)**2) for p in pos)
    return (cx, cy, cz, r)


def _translation_matrix(t):
    x, y, z = t
    return (1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            x, y, z, 1)


def _write_dummy(w, name, children, matrix=None):
    w.i32(1)
    w.s(name)
    w.i32(len(children))
    w.u8(1)
    w.pack("16f", *(matrix or _translation_matrix((0, 0, 0))))
    for c in children:
        _write_node(w, c)


def _write_node(w, node):
    if node["kind"] == "dummy":
        _write_dummy(w, node["name"], node["children"], node.get("matrix"))
        return
    blob, idx = _vertex_blob(node["obj"])
    w.i32(2)
    w.s(node["name"])
    w.i32(0)
    w.u8(1)                                   # active
    w.u8(node["obj"].get("cast_shadows", 1))
    w.u8(node["obj"].get("visible", 1))
    w.u8(0)                                   # transparent
    w.i32(len(node["obj"]["positions"]))
    w.raw(blob)
    w.i32(len(idx))
    w.pack("%dH" % len(idx), *idx)
    w.i32(node["material"])
    w.i32(0)                                   # layer
    w.f32(0.0)                                 # lod_in
    w.f32(0.0)                                 # lod_out
    w.pack("4f", *_sphere(node["obj"]["positions"]))
    w.u8(1)                                    # renderable


def write_kn5(path, textures, materials, objects, root_name="ARB_RB20"):
    """textures: [(name, bytes)]; materials: list of dicts; objects: mesh soups."""
    w = W()
    w.raw(MAGIC)
    w.i32(VERSION)
    w.i32(len(textures))
    for name, data in textures:
        w.i32(1)
        w.s(name)
        w.i32(len(data))
        w.raw(data)
    w.i32(len(materials))
    for m in materials:
        w.s(m["name"])
        w.s(m.get("shader", "ksPerPixel"))
        w.u8(m.get("blend", 0))
        w.u8(m.get("alpha_tested", 0))
        w.i32(m.get("depth_mode", 0))
        props = m.get("props", {})
        w.i32(len(props))
        for pname, val in props.items():
            w.s(pname)
            w.pack("10f", float(val), 0, 0, 0, 0, 0, 0, 0, 0, 0)
        maps = m.get("maps", [])
        w.i32(len(maps))
        for pname, slot, tex in maps:
            w.s(pname)
            w.i32(slot)
            w.s(tex)
    mat_index = {m["name"]: i for i, m in enumerate(materials)}
    children = []
    for obj in objects:
        mi = mat_index[obj["material"]]
        mesh_node = {"kind": "mesh", "name": obj["name"], "obj": obj, "material": mi}
        children.append({"kind": "dummy", "name": obj["name"],
                         "matrix": _translation_matrix(obj.get("origin", (0, 0, 0))),
                         "children": [mesh_node]})
    _write_dummy(w, root_name, children)
    with open(path, "wb") as f:
        f.write(w.buf)
    return len(w.buf)


# ------------------------------------------------------------------- reader
class R:
    def __init__(self, buf):
        self.b = memoryview(buf)
        self.p = 0

    def take(self, n):
        v = bytes(self.b[self.p:self.p + n])
        self.p += n
        return v

    def unpack(self, fmt):
        v = struct.unpack_from("<" + fmt, self.b, self.p)
        self.p += struct.calcsize("<" + fmt)
        return v

    def i32(self):
        return self.unpack("i")[0]

    def u8(self):
        return self.unpack("B")[0]

    def s(self):
        return self.take(self.i32()).decode("utf-8", "replace")


def _read_node(r):
    cls = r.i32()
    name = r.s()
    nchild = r.i32()
    active = r.u8()
    node = {"class": cls, "name": name, "active": active, "children": []}
    if cls == 1:
        node["matrix"] = r.unpack("16f")
    elif cls == 2:
        node["flags"] = (r.u8(), r.u8(), r.u8())
        vc = r.i32()
        node["vertex_bytes"] = len(r.take(vc * VERTEX_BYTES))
        node["vertex_count"] = vc
        ic = r.i32()
        node["index_count"] = ic
        r.take(ic * 2)
        node["material"] = r.i32()
        node["layer"] = r.i32()
        node["lod"] = r.unpack("2f")
        node["sphere"] = r.unpack("4f")
        node["renderable"] = r.u8()
    else:
        raise ValueError("unknown KN5 node class %d" % cls)
    node["children"] = [_read_node(r) for _ in range(nchild)]
    return node


def read_kn5(path):
    with open(path, "rb") as f:
        r = R(f.read())
    if r.take(6) != MAGIC:
        raise ValueError("not a KN5 file")
    version = r.i32()
    if version > 5:
        r.i32()  # extra
    textures = []
    for _ in range(r.i32()):
        active = r.i32()
        name = r.s()
        textures.append((name, len(r.take(r.i32())), active))
    materials = []
    for _ in range(r.i32()):
        name, shader = r.s(), r.s()
        blend, alpha, depth = r.u8(), r.u8(), r.i32()
        props = []
        for _ in range(r.i32()):
            pn = r.s()
            props.append((pn, r.unpack("10f")))
        maps = []
        for _ in range(r.i32()):
            maps.append((r.s(), r.i32(), r.s()))
        materials.append({"name": name, "shader": shader, "blend": blend,
                          "alpha_tested": alpha, "depth_mode": depth,
                          "props": props, "maps": maps})
    root = _read_node(r)
    if r.p != len(r.b):
        raise ValueError("%d trailing bytes" % (len(r.b) - r.p))
    return {"version": version, "textures": textures,
            "materials": materials, "root": root}


def walk(node):
    yield node
    for c in node["children"]:
        yield from walk(c)
