"""Carregamento de mods: pistas e carros em JSON.

O jogo procura em duas pastas (além dos arquivos embutidos):
  <pasta do executável>/mods/tracks/*.json
  <pasta do executável>/mods/cars/*.json

Qualquer JSON no formato dos arquivos de `assets/` já funciona como mod.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from .car import CarSpec
from .track import Track


def base_dir() -> str:
    """Pasta gravável ao lado do executável (mods, modelos, logs)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def bundle_dir() -> str:
    """Pasta dos arquivos embutidos (assets)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", base_dir())
    return base_dir()


def assets_dir() -> str:
    return os.path.join(bundle_dir(), "assets")


def mods_dir() -> str:
    return os.path.join(base_dir(), "mods")


def models_dir() -> str:
    return os.path.join(base_dir(), "modelos")


@dataclass
class ModItem:
    kind: str                 # "tracks" | "cars"
    name: str
    path: str
    builtin: bool = False
    error: str = ""
    obj: object | None = None


def _scan_folder(kind: str, folder: str, builtin: bool) -> list[ModItem]:
    out = []
    if not os.path.isdir(folder):
        return out
    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(".json"):
            continue
        path = os.path.join(folder, fname)
        item = ModItem(kind=kind, name=os.path.splitext(fname)[0], path=path, builtin=builtin)
        try:
            with open(path, "r", encoding="utf-8") as f:
                json.load(f)          # valida o JSON
        except Exception as exc:
            item.error = f"JSON inválido: {exc}"
        out.append(item)
    return out


def scan(kind: str) -> list[ModItem]:
    items = _scan_folder(kind, os.path.join(assets_dir(), kind), True)
    seen = {i.name for i in items}
    for it in _scan_folder(kind, os.path.join(mods_dir(), kind), False):
        if it.name in seen:
            it.name += " (mod)"
        items.append(it)
    return items


def load_tracks() -> list[ModItem]:
    items = scan("tracks")
    for it in items:
        if it.error:
            continue
        try:
            it.obj = Track.load(it.path)
        except Exception as exc:
            it.error = str(exc)
    return items


def load_cars() -> list[ModItem]:
    items = scan("cars")
    for it in items:
        if it.error:
            continue
        try:
            it.obj = CarSpec.load(it.path)
        except Exception as exc:
            it.error = str(exc)
    return items


def create_template(kind: str, name: str) -> str:
    """Cria um JSON de exemplo na pasta de mods (para você editar)."""
    folder = os.path.join(mods_dir(), kind)
    os.makedirs(folder, exist_ok=True)
    safe = "".join(c for c in name.strip() if c.isalnum() or c in "-_ ") or "meu_mod"
    path = os.path.join(folder, f"{safe.replace(' ', '_').lower()}.json")
    i = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{safe.replace(' ', '_').lower()}_{i}.json")
        i += 1
    if kind == "tracks":
        data = {
            "name": safe,
            "description": "Pista criada como modelo",
            "closed": True,
            "width": 14.0,
            "spacing": 4.0,
            "points": [[0, 0], [120, 0], [190, 70], [190, 160], [90, 200], [-40, 150], [-60, 60]],
            "zones": [],
            "start": 0.0,
        }
    else:
        data = {
            "id": safe.replace(" ", "_").lower(),
            "name": safe,
            "mass": 1200.0, "length": 4.3, "width": 1.9, "wheelbase": 2.65,
            "cg_front": 1.28, "cg_height": 0.52,
            "engine_force": 9500.0, "max_power": 250000.0, "brake_force": 13000.0,
            "max_speed": 70.0, "max_steer": 0.58, "steer_rate": 4.0, "steer_falloff": 0.55,
            "grip_front": 1.5, "grip_rear": 1.48, "tire_stiffness": 9.5, "tire_shape": 1.45,
            "drag": 0.44, "rolling": 28.0, "downforce": 0.4,
            "drive_front": 0.4, "brake_front": 0.62, "yaw_inertia": 1.05,
            "body_color": "#3aa8e0", "accent_color": "#ffffff",
        }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def open_folder(path: str):
    """Abre a pasta no explorador (Windows) / gerenciador (Linux)."""
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(folder)          # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass
