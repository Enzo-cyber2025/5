"""
blender_model.py -- MODEL THE CAR IN BLENDER (headless, runs on GitHub Actions).

Run with the `bpy` module (Blender's Python API):
    python rb20/tools/blender_model.py --out rb20/out

It creates a real Blender scene from mesh_core, adds Bevel + WeightedNormal
modifiers, evaluates and triangulates the meshes, and exports build/mesh.json
in Assetto Corsa coordinates for make_kn5.py. It also saves the editable
.blend and an FBX (Y-up) as source assets.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bpy
import bmesh

import mesh_core
from mesh_core import MATERIALS


def to_blender(p):
    """AC (x, y up, z forward) -> Blender (x, -z forward, y up)."""
    return (p[0], -p[2], p[1])


def to_ac(p):
    """Blender -> AC."""
    return (p[0], p[2], -p[1])


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for m in list(bpy.data.meshes):
        if m.users == 0:
            bpy.data.meshes.remove(m)


def make_material(name):
    rgb = MATERIALS[name][0]
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (rgb[0]/255.0, rgb[1]/255.0, rgb[2]/255.0, 1.0)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*[c/255.0 for c in rgb], 1.0)
        bsdf.inputs["Roughness"].default_value = 0.42 if name != "RB20_GLASS" else 0.15
        bsdf.inputs["Metallic"].default_value = 0.35 if name in ("RB20_RIM", "RB20_BRAKE") else 0.05
    return mat


def build_scene(raw_objects):
    clear_scene()
    mats = {n: make_material(n) for n in sorted({o.material for o in raw_objects})}
    created = []
    for src in raw_objects:
        bm = bpy.data.meshes.new(src.name)
        verts = [to_blender(p) for p in src.v]
        bm.from_pydata(verts, [], [list(f) for f in src.f])
        bm.update()
        uv = bm.uv_layers.new(name="UVMap")
        for poly in bm.polygons:
            for li in poly.loop_indices:
                uv.data[li].uv = src.uv[bm.loops[li].vertex_index]
            poly.use_smooth = True
        bm.materials.append(mats[src.material])
        obj = bpy.data.objects.new(src.name, bm)
        bpy.context.collection.objects.link(obj)
        ox, oy, oz = to_blender(src.origin)
        obj.location = (ox, oy, oz)

        # Real Blender sculpting pass. Curved panels (body, nose, sidepods,
        # wings, halo, wheels) get a Catmull-Clark SUBSURF so the lofted
        # superellipses become smooth F1 surfaces instead of faceted boxes.
        # Everything else keeps a small ANGLE-limited bevel for crisp carbon
        # edges. Smooth shading + weighted normals are applied to all objects.
        if src.subdiv:
            for poly in bm.polygons:
                poly.use_smooth = True
            sub = obj.modifiers.new("Surface subdivision", "SUBSURF")
            sub.subdivision_type = "CATMULL_CLARK"
            sub.levels = 1
            sub.render_levels = 1
            sub.show_only_control_edges = True
        if src.smooth >= 30:
            bev = obj.modifiers.new("Edge bevel", "BEVEL")
            bev.width = 0.0035 if src.subdiv else 0.004
            bev.segments = 3
            bev.limit_method = "ANGLE"
            bev.angle_limit = math.radians(32)
        wn = obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
        wn.keep_sharp = True
        wn.weight = 50
        created.append((src, obj))
    # A little studio setup for whoever opens the .blend.
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (4.2, -6.4, 2.4)
    cam.rotation_euler = (math.radians(72), 0, math.radians(34))
    cam_data.lens = 55
    bpy.context.scene.camera = cam
    # A neutral studio floor makes the saved .blend useful for inspection.
    floor_mesh = bpy.data.meshes.new("StudioFloor")
    floor_mesh.from_pydata([(-9, -9, -0.002), (9, -9, -0.002),
                            (9, 9, -0.002), (-9, 9, -0.002)], [],
                           [(0, 1, 2, 3)])
    floor_mesh.update()
    floor_obj = bpy.data.objects.new("StudioFloor", floor_mesh)
    bpy.context.collection.objects.link(floor_obj)
    for name, loc, energy in (("Key", (-3, -4, 6), 1800),
                              ("Fill", (4, 3, 4), 900),
                              ("Rim", (0, 5, 5), 1400)):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = energy
        ld.shape = "DISK"
        ld.size = 5.0
        lo = bpy.data.objects.new(name, ld)
        bpy.context.collection.objects.link(lo)
        lo.location = loc
    return created


def evaluated_triangles(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    mesh = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=deps)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()
    try:
        mesh.calc_loop_triangles()          # removed in newer Blender builds
    except Exception:
        pass
    try:
        corner_normals = [tuple(n.vector) for n in mesh.corner_normals]
    except Exception:
        corner_normals = None
    uv_layer = mesh.uv_layers.active
    positions, normals, uvs, indices = [], [], [], []
    cache = {}
    for tri in mesh.loop_triangles:
        for li in tri.loops:
            vi = mesh.loops[li].vertex_index
            p = tuple(mesh.vertices[vi].co)
            n = corner_normals[li] if corner_normals else tuple(tri.normal)
            u = tuple(uv_layer.data[li].uv) if uv_layer else (0.5, 0.5)
            key = (tuple(round(c, 6) for c in p),
                   tuple(round(c, 5) for c in n),
                   tuple(round(c, 6) for c in u))
            if key not in cache:
                cache[key] = len(positions)
                positions.append(to_ac(p))
                normals.append(to_ac(n))
                uvs.append(u)
            indices.append(cache[key])
    bpy.data.meshes.remove(mesh)
    return positions, normals, uvs, indices


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="build output directory")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    raw = mesh_core.build_car_raw()
    created = build_scene(raw)
    print("Blender", bpy.app.version_string, "- objects:", len(created))

    objects = []
    for src, obj in created:
        positions, normals, uvs, indices = evaluated_triangles(obj)
        if not positions:
            continue
        if len(positions) >= 65535:
            raise RuntimeError("%s exceeds the KN5 16-bit index limit" % src.name)
        objects.append({
            "name": src.name,
            "material": src.material,
            "origin": [round(c, 6) for c in src.origin],
            "cast_shadows": src.cast_shadows,
            "visible": src.visible,
            "positions": [[round(c, 6) for c in p] for p in positions],
            "normals": [[round(c, 6) for c in n] for n in normals],
            "uv": [[round(c, 6) for c in u] for u in uvs],
            "indices": indices,
        })

    # If Blender's evaluation produced something unusable, fail loudly rather
    # than ship an empty car.
    tris = sum(len(o["indices"]) // 3 for o in objects)
    if len(objects) < 50 or tris < 5000:
        raise RuntimeError("Blender produced too little geometry (%d objects, %d tris)" %
                           (len(objects), tris))

    mesh_json = os.path.join(args.out, "mesh.json")
    with open(mesh_json, "w", encoding="utf-8") as f:
        json.dump({"meta": {
            "generator": "Blender %s (bpy, headless)" % bpy.app.version_string,
            "units": "m",
            "axes": "Assetto Corsa Y-up, +Z forward",
            "source": "mesh_core.py parametric RB20",
            "modifiers": ["BEVEL", "WEIGHTED_NORMAL", "TRIANGULATE"],
            "objects": len(objects),
            "triangles": tris,
        }, "objects": objects}, f)
    print("wrote", mesh_json, "-", len(objects), "objects,", tris, "triangles")

    blend_path = os.path.join(args.out, "arb_rb20.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print("wrote", blend_path)

    try:
        fbx = os.path.join(args.out, "arb_rb20.fbx")
        bpy.ops.export_scene.fbx(filepath=fbx, use_selection=False,
                                 axis_forward="-Y", axis_up="Z",
                                 apply_unit_scale=True, global_scale=1.0,
                                 mesh_smooth_type="FACE", add_leaf_bones=False)
        print("wrote", fbx)
    except Exception as exc:                       # FBX is an optional extra
        print("FBX export skipped:", exc)


if __name__ == "__main__":
    main()
