"""Gera as pistas e carros padrão (JSON) em assets/.

Os arquivos gerados têm exatamente o mesmo formato aceito pelo carregador de
mods — ou seja, servem de exemplo para você criar os seus.
Uso:  python tools/make_assets.py
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")
TRACKS = os.path.join(ASSETS, "tracks")
CARS = os.path.join(ASSETS, "cars")


def round_path(points, radius=25.0, samples=10, closed=True):
    """Arredonda cantos de uma polilinha com curvas quadráticas."""
    pts = [np.asarray(p, dtype=float) for p in points]
    n = len(pts)
    out = []
    rng = range(n) if closed else range(1, n - 1)
    if not closed:
        out.append(pts[0])
    for i in rng:
        b = pts[i]
        a = pts[(i - 1) % n]
        c = pts[(i + 1) % n]
        d1 = a - b
        d2 = c - b
        l1, l2 = np.linalg.norm(d1), np.linalg.norm(d2)
        if l1 < 1e-6 or l2 < 1e-6:
            continue
        d1, d2 = d1 / l1, d2 / l2
        r = min(radius, l1 * 0.45, l2 * 0.45)
        start = b + d1 * r
        end = b + d2 * r
        out.append(start)
        for k in range(1, samples):
            t = k / samples
            out.append((1 - t) ** 2 * start + 2 * (1 - t) * t * b + t ** 2 * end)
        out.append(end)
    if not closed:
        out.append(pts[-1])
    return [np.asarray(p) for p in out]


def poly(r_func, n=64, scale=(1.0, 1.0)):
    pts = []
    for k in range(n):
        a = k / n * math.tau
        r = r_func(a)
        pts.append([r * math.cos(a) * scale[0], r * math.sin(a) * scale[1]])
    return pts


def rounded_rect(length=260.0, width=140.0, radius=45.0, n_arc=8):
    hl, hw = length / 2, width / 2
    corners = [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)]
    return round_path(corners, radius=radius, samples=n_arc, closed=True)


def dump(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print("escrito", os.path.relpath(path, ROOT))


# ---------------------------------------------------------------------- #
# Pistas
# ---------------------------------------------------------------------- #
def build_tracks():
    tracks = {}

    tracks["oval_iniciante"] = {
        "name": "Oval Iniciante",
        "description": "Oval aberto, ideal para as primeiras gerações.",
        "difficulty": "fácil",
        "closed": True,
        "width": 18.0,
        "spacing": 4.0,
        "points": [[round(x, 1), round(y, 1)] for x, y in
                   poly(lambda a: 150.0, n=40, scale=(1.0, 0.62))],
    }

    tracks["kartodromo"] = {
        "name": "Kartódromo",
        "description": "Curto e técnico: volta rápida, evolução acelera.",
        "difficulty": "fácil",
        "closed": True,
        "width": 11.0,
        "spacing": 3.0,
        "points": [[round(x, 1), round(y, 1)] for x, y in
                   round_path([[-90, -55], [40, -70], [95, -20], [60, 30],
                               [-10, 15], [-40, 55], [-100, 40]],
                              radius=22, samples=12, closed=True)],
    }

    tracks["serra"] = {
        "name": "Circuito da Serra",
        "description": "Curvas de raio variável com trecho de terra.",
        "difficulty": "médio",
        "closed": True,
        "width": 13.5,
        "spacing": 4.0,
        "points": [[round(x, 1), round(y, 1)] for x, y in
                   poly(lambda a: 155.0 + 30.0 * math.sin(3 * a) + 13.0 * math.sin(5 * a + 0.7),
                        n=72, scale=(1.0, 0.78))],
        "zones": [{"start": 0.55, "end": 0.68, "grip": 0.72, "name": "terra"}],
    }

    tracks["speedway"] = {
        "name": "Speedway Retão",
        "description": "Duas retas longas e duas curvas de alta.",
        "difficulty": "médio",
        "closed": True,
        "width": 17.0,
        "spacing": 4.0,
        "points": [[round(x, 1), round(y, 1)] for x, y in
                   rounded_rect(length=330.0, width=150.0, radius=55.0)],
    }

    tracks["touge"] = {
        "name": "Touge Sinuoso",
        "description": "Sequência de curvas fechadas em descida imaginária.",
        "difficulty": "difícil",
        "closed": True,
        "width": 10.5,
        "spacing": 3.0,
        "points": [[round(x, 1), round(y, 1)] for x, y in
                   poly(lambda a: 135.0 + 24.0 * math.sin(6 * a) + 9.0 * math.sin(2 * a + 1.1),
                        n=96, scale=(1.0, 0.85))],
    }

    tracks["cidade"] = {
        "name": "Circuito Urbano",
        "description": "Curvas de 90°, chicane e pouca área de escape.",
        "difficulty": "difícil",
        "closed": True,
        "width": 12.0,
        "spacing": 3.0,
        "points": [[round(x, 1), round(y, 1)] for x, y in
                   round_path([[-130, -80], [20, -80], [20, -20], [110, -20],
                               [110, 60], [30, 60], [30, 100], [-130, 100]],
                              radius=26, samples=10, closed=True)],
    }

    # figura 8 (lemniscata de Gerono)
    t = np.linspace(0, math.tau, 96, endpoint=False)
    fig8 = [[round(185.0 * math.cos(tt), 1), round(120.0 * math.sin(tt) * math.cos(tt), 1)]
            for tt in t]
    tracks["figura8"] = {
        "name": "Figura 8",
        "description": "Cruza no meio — atenção ao tráfego fantasma.",
        "difficulty": "médio",
        "closed": True,
        "width": 15.0,
        "spacing": 3.0,
        "points": fig8,
    }

    tracks["terra_dirt"] = {
        "name": "Dirt Oval",
        "description": "Oval de terra: aderência baixa, muito contraesterço.",
        "difficulty": "difícil",
        "closed": True,
        "width": 20.0,
        "spacing": 4.0,
        "points": [[round(x, 1), round(y, 1)] for x, y in
                   poly(lambda a: 145.0 + 12.0 * math.sin(2 * a), n=56, scale=(1.0, 0.7))],
        "zones": [{"start": 0.0, "end": 1.0, "grip": 0.68, "name": "terra"}],
        "surface": "terra",
    }

    for name, data in tracks.items():
        data.setdefault("zones", [])
        dump(os.path.join(TRACKS, f"{name}.json"), data)


# ---------------------------------------------------------------------- #
# Carros
# ---------------------------------------------------------------------- #
def build_cars():
    cars = {
        "kart": {
            "id": "kart",
            "name": "Kart 2 Tempos",
            "mass": 620.0, "length": 2.6, "width": 1.4, "wheelbase": 1.55,
            "cg_front": 0.72, "cg_height": 0.32,
            "engine_force": 3400.0, "brake_force": 5200.0, "max_speed": 38.0,
            "max_steer": 0.72, "steer_rate": 6.0, "steer_falloff": 0.35,
            "grip_front": 1.75, "grip_rear": 1.70, "tire_stiffness": 12.0,
            "drag": 0.30, "rolling": 16.0, "downforce": 0.0,
            "drive_front": 0.0, "brake_front": 0.55, "yaw_inertia": 0.85,
            "body_color": "#ffd23f", "accent_color": "#222222",
        },
        "sedan": {
            "id": "sedan",
            "name": "Sedã 1.6",
            "mass": 1180.0, "length": 4.4, "width": 1.75, "wheelbase": 2.62,
            "cg_front": 1.25, "cg_height": 0.55,
            "engine_force": 5200.0, "brake_force": 9800.0, "max_speed": 52.0,
            "max_steer": 0.56, "steer_rate": 3.4, "steer_falloff": 0.55,
            "grip_front": 1.28, "grip_rear": 1.34, "tire_stiffness": 8.0,
            "drag": 0.46, "rolling": 28.0, "downforce": 0.0,
            "drive_front": 1.0, "brake_front": 0.66, "yaw_inertia": 1.10,
            "body_color": "#4f8cc9", "accent_color": "#e8e8e8",
        },
        "gt": {
            "id": "gt",
            "name": "GT-R Kit",
            "mass": 1320.0, "length": 4.5, "width": 1.92, "wheelbase": 2.72,
            "cg_front": 1.30, "cg_height": 0.50,
            "engine_force": 12500.0, "brake_force": 16500.0, "max_speed": 82.0,
            "max_steer": 0.55, "steer_rate": 4.4, "steer_falloff": 0.60,
            "grip_front": 1.62, "grip_rear": 1.60, "tire_stiffness": 10.5,
            "drag": 0.44, "rolling": 30.0, "downforce": 0.9,
            "drive_front": 0.35, "brake_front": 0.62, "yaw_inertia": 1.05,
            "body_color": "#e0483a", "accent_color": "#f5f5f5",
        },
        "drift": {
            "id": "drift",
            "name": "Drift BX",
            "mass": 1240.0, "length": 4.3, "width": 1.80, "wheelbase": 2.58,
            "cg_front": 1.22, "cg_height": 0.52,
            "engine_force": 9800.0, "brake_force": 11000.0, "max_speed": 68.0,
            "max_steer": 0.68, "steer_rate": 5.2, "steer_falloff": 0.45,
            "grip_front": 1.62, "grip_rear": 1.14, "tire_stiffness": 7.5,
            "drag": 0.48, "rolling": 26.0, "downforce": 0.0,
            "drive_front": 0.0, "brake_front": 0.58, "yaw_inertia": 0.95,
            "body_color": "#b14cd8", "accent_color": "#1b1b1b",
        },
        "formula": {
            "id": "formula",
            "name": "Fórmula Júnior",
            "mass": 720.0, "length": 4.0, "width": 1.8, "wheelbase": 2.85,
            "cg_front": 1.30, "cg_height": 0.35,
            "engine_force": 8600.0, "brake_force": 15000.0, "max_speed": 88.0,
            "max_steer": 0.48, "steer_rate": 5.0, "steer_falloff": 0.65,
            "grip_front": 1.95, "grip_rear": 1.90, "tire_stiffness": 13.0,
            "drag": 0.62, "rolling": 22.0, "downforce": 2.6,
            "drive_front": 0.0, "brake_front": 0.58, "yaw_inertia": 0.9,
            "body_color": "#2fd18a", "accent_color": "#101010",
        },
        "truck": {
            "id": "truck",
            "name": "Caminhão Turbo",
            "mass": 2600.0, "length": 5.6, "width": 2.3, "wheelbase": 3.3,
            "cg_front": 1.55, "cg_height": 0.95,
            "engine_force": 21000.0, "brake_force": 15000.0, "max_speed": 58.0,
            "max_steer": 0.50, "steer_rate": 2.4, "steer_falloff": 0.60,
            "grip_front": 1.10, "grip_rear": 1.18, "tire_stiffness": 6.0,
            "drag": 1.05, "rolling": 55.0, "downforce": 0.0,
            "drive_front": 0.0, "brake_front": 0.70, "yaw_inertia": 1.45,
            "body_color": "#f07f2a", "accent_color": "#3a3a3a",
        },
    }
    for name, data in cars.items():
        dump(os.path.join(CARS, f"{name}.json"), data)


if __name__ == "__main__":
    build_tracks()
    build_cars()
    print("ok")
