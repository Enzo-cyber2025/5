"""Pistas: construção a partir de JSON, geometria, consultas e sensores.

Uma pista é uma polilinha de centro reamostrada com espaçamento constante,
com largura, zonas de superfície (asfalto/terra/gelo) e checkpoints.
Tudo é armazenado em arrays numpy para consultas vetorizadas.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

import numpy as np

from .mathutil import (catmull_rom, path_curvature, path_tangents,
                       polyline_arc_lengths, ray_segment_distance,
                       resample_polyline, wrap_angle)

DEFAULT_SPACING = 4.0


@dataclass
class SurfaceZone:
    """Trecho com aderência diferente (terra, grama, gelo...)."""
    start: float      # fração do comprimento da pista [0,1]
    end: float
    grip: float
    name: str = "zone"


@dataclass
class Track:
    name: str = "sem nome"
    center: np.ndarray = field(default_factory=lambda: np.zeros((2, 2)))
    width: float = 14.0
    half_widths: np.ndarray = field(default_factory=lambda: np.zeros(2))
    closed: bool = True
    grip: np.ndarray = field(default_factory=lambda: np.ones(2))
    tangents: np.ndarray = field(default_factory=lambda: np.zeros((2, 2)))
    normals: np.ndarray = field(default_factory=lambda: np.zeros((2, 2)))
    heading: np.ndarray = field(default_factory=lambda: np.zeros(2))
    curvature: np.ndarray = field(default_factory=lambda: np.zeros(2))
    arc: np.ndarray = field(default_factory=lambda: np.zeros(2))
    length: float = 0.0
    edge_l: np.ndarray = field(default_factory=lambda: np.zeros((2, 2)))
    edge_r: np.ndarray = field(default_factory=lambda: np.zeros((2, 2)))
    checkpoints: np.ndarray = field(default_factory=lambda: np.zeros(1, dtype=int))
    start_index: int = 0
    source: str = ""
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def __post_init__(self):
        if len(self.center) and self.half_widths is None:
            self.rebuild()

    @property
    def n(self) -> int:
        return len(self.center)

    @property
    def spacing(self) -> float:
        return float(self.arc[1] - self.arc[0]) if len(self.arc) > 1 else DEFAULT_SPACING

    # ------------------------------------------------------------------ #
    def rebuild(self):
        n = len(self.center)
        self.tangents = path_tangents(self.center, self.closed)
        # normal à esquerda da tangente
        self.normals = np.stack([-self.tangents[:, 1], self.tangents[:, 0]], axis=1)
        self.heading = np.arctan2(self.tangents[:, 1], self.tangents[:, 0])
        self.curvature = path_curvature(self.center, self.closed)
        self.arc = polyline_arc_lengths(self.center, self.closed)[:n] if self.closed \
            else polyline_arc_lengths(self.center, False)
        self.length = float(self.arc[-1] + (self.spacing if self.closed else 0.0))
        self.edge_l = self.center + self.normals * self.half_widths[:, None]
        self.edge_r = self.center - self.normals * self.half_widths[:, None]
        m = max(4, min(60, int(self.length // 25)))
        self.checkpoints = (np.arange(m) * (n / m)).astype(int)
        self._build_wall_cache()

    def _build_wall_cache(self):
        """Segmentos de parede (esquerda+direita) para raycast, em arrays planos."""
        n = self.n
        left_p, left_q = self.edge_l, np.roll(self.edge_l, -1, axis=0)
        right_p, right_q = self.edge_r, np.roll(self.edge_r, -1, axis=0)
        self.wall_p = np.vstack([left_p, right_p])       # (2N,2)
        self.wall_q = np.vstack([left_q, right_q])       # (2N,2)
        self.ray_window = 64                             # segmentos à frente considerados

    # ------------------------------------------------------------------ #
    # Consultas
    # ------------------------------------------------------------------ #
    def nearest(self, pos: np.ndarray, hint: np.ndarray | None = None,
                window: int = 48, guard: float = 25.0) -> tuple[np.ndarray, np.ndarray]:
        """Índice do ponto mais próximo e deslocamento lateral com sinal.

        pos : (A,2); hint : (A,) índices anteriores (busca local) ou None (busca global).
        Retorna (idx, lateral) com lateral positiva à esquerda da tangente.

        Quando há busca local e o ponto achado está longe demais (carro
        reposicionado por batida, ou seção paralela da pista), refaz a busca
        global — evita que a progressão "salte" para outro trecho.
        """
        pos = np.asarray(pos, dtype=np.float64)
        a = pos.shape[0]
        n = self.n
        if hint is None:
            dx = pos[:, 0][:, None] - self.center[None, :, 0]
            dy = pos[:, 1][:, None] - self.center[None, :, 1]
            idx = np.argmin(dx * dx + dy * dy, axis=1)
        else:
            base = (hint.astype(int) - 6) % n
            offs = np.arange(window)
            ii = (base[:, None] + offs[None, :]) % n               # (A,W)
            cx = self.center[ii]                                   # (A,W,2)
            dx = pos[:, 0][:, None] - cx[:, :, 0]
            dy = pos[:, 1][:, None] - cx[:, :, 1]
            d2 = dx * dx + dy * dy
            best = np.argmin(d2, axis=1)
            rows = np.arange(a)
            idx = ii[rows, best]
            # guarda: distância impossível -> o trecho local não é o certo
            too_far = np.sqrt(d2[rows, best]) > (self.half_widths[idx] + guard)
            if too_far.any():
                dx = pos[:, 0][:, None] - self.center[None, :, 0]
                dy = pos[:, 1][:, None] - self.center[None, :, 1]
                idx = np.where(too_far, np.argmin(dx * dx + dy * dy, axis=1), idx)
        # projeção fina sobre o segmento (idx -> idx+1) e (idx-1 -> idx)
        nxt = (idx + 1) % n
        prv = (idx - 1) % n
        tang = self.tangents[idx]
        rel = pos - self.center[idx]
        along = rel[:, 0] * tang[:, 0] + rel[:, 1] * tang[:, 1]
        idx = np.where(along > 0, nxt, idx)
        idx = np.where(along < -self.spacing, idx, np.where(along > 0, nxt, idx))
        # deslocamento lateral com sinal (positivo = esquerda)
        tang = self.tangents[idx]
        nrm = self.normals[idx]
        rel = pos - self.center[idx]
        lateral = rel[:, 0] * nrm[:, 0] + rel[:, 1] * nrm[:, 1]
        return idx.astype(int), lateral

    def surface_grip(self, idx: np.ndarray) -> np.ndarray:
        return self.grip[idx]

    def arc_at(self, idx: np.ndarray, lateral_progress: np.ndarray | None = None) -> np.ndarray:
        s = self.arc[idx]
        if lateral_progress is not None:
            s = s + lateral_progress
        return s

    def lookahead(self, idx: np.ndarray, distances: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Diferença de heading (rad) para pontos a `distances` metros à frente.

        Retorna (dheading (A,K), curvatura média (A,K)).
        """
        n = self.n
        steps = np.round(np.asarray(distances) / max(self.spacing, 1e-6)).astype(int)
        out_dh = np.empty((len(idx), len(steps)))
        out_k = np.empty((len(idx), len(steps)))
        for k, st in enumerate(steps):
            j = (idx + st) % n
            out_dh[:, k] = wrap_angle(self.heading[j] - self.heading[idx])
            # curvatura média no trecho
            jj = (idx[:, None] + np.arange(0, max(st, 1))) % n if st > 1 else idx[:, None]
            out_k[:, k] = self.curvature[jj].mean(axis=1) if st > 1 else self.curvature[idx]
        return out_dh, out_k

    def cast_rays(self, pos: np.ndarray, heading: np.ndarray, idx: np.ndarray,
                  n_rays: int = 9, max_range: float = 70.0,
                  fov: float = math.radians(140.0)) -> np.ndarray:
        """Raycast dos sensores contra as paredes da pista (vetorizado)."""
        a = pos.shape[0]
        n = self.n
        offs = np.linspace(-fov / 2.0, fov / 2.0, n_rays)
        ang = heading[:, None] + offs[None, :]
        origin = pos[:, None, None, :]
        direction = np.stack([np.cos(ang), np.sin(ang)], axis=-1)[:, :, None, :]

        w = self.ray_window
        base = (idx - 4) % n
        ii = (base[:, None] + np.arange(w)[None, :])
        ii_l = ii % n
        ii_r = (ii % n) + n
        all_idx = np.concatenate([ii_l, ii_r], axis=1)          # (A, 2W)
        seg_p = self.wall_p[all_idx][:, None, :, :]
        seg_q = self.wall_q[all_idx][:, None, :, :]
        dist = ray_segment_distance(origin, direction, seg_p, seg_q, max_range)
        return np.minimum(dist, max_range)

    # ------------------------------------------------------------------ #
    # Construção / serialização
    # ------------------------------------------------------------------ #
    @classmethod
    def from_dict(cls, data: dict, source: str = "") -> "Track":
        name = str(data.get("name", data.get("id", "pista")))
        closed = bool(data.get("closed", True))
        pts = np.asarray(data.get("points", []), dtype=np.float64)
        if pts.ndim != 2 or len(pts) < 4:
            raise ValueError(f"pista '{name}': 'points' precisa ter ao menos 4 pontos [x, y]")
        spacing = float(data.get("spacing", DEFAULT_SPACING))
        # uniformiza os pontos de controle antes do spline: o Catmull-Rom
        # uniforme "overshoota" quando os pontos têm espaçamentos muito
        # diferentes (comum em mods escritos à mão)
        step = max(8.0, spacing * 2.0)
        if len(pts) > 4:
            pts = resample_polyline(pts, step, closed)
        smooth = catmull_rom(pts, samples_per_seg=int(data.get("smooth_samples", 24)), closed=closed)
        center = resample_polyline(smooth, spacing, closed)

        width = data.get("width", 14.0)
        if isinstance(width, (int, float)):
            base = float(width)
            widths = np.full(len(center), base)
        else:
            # lista de larguras por ponto de controle -> interpola ao longo do caminho
            wa = np.asarray(width, dtype=np.float64)
            t = np.linspace(0, 1, len(center))
            tw = np.linspace(0, 1, len(wa))
            widths = np.interp(t, tw, wa)
        # largura mínima de segurança (carros têm ~2 m)
        widths = np.maximum(widths, 6.0)

        trk = cls(name=name, center=center, width=float(np.mean(widths)),
                  half_widths=widths * 0.5, closed=closed, source=source)
        trk.rebuild()

        grip = np.ones(trk.n, dtype=np.float64)
        for z in data.get("zones", []) or []:
            zs, ze = float(z.get("start", 0.0)), float(z.get("end", 0.0))
            g = float(z.get("grip", 1.0))
            i0 = int(zs * trk.n) % trk.n
            i1 = int(ze * trk.n) % trk.n
            if i1 >= i0:
                grip[i0:i1] = g
            else:
                grip[i0:] = g
                grip[:i1] = g
        trk.grip = grip
        trk.start_index = int(float(data.get("start", 0.0)) * trk.n) % trk.n
        trk.meta = {k: v for k, v in data.items() if k in
                    ("description", "author", "difficulty", "laps", "surface")}
        return trk

    def to_dict(self) -> dict:
        step = max(1, self.n // 60)
        return {
            "name": self.name,
            "closed": self.closed,
            "width": float(np.mean(self.half_widths) * 2.0),
            "spacing": float(self.spacing),
            "points": [[round(float(x), 2), round(float(y), 2)] for x, y in self.center[::step]],
        }

    @classmethod
    def load(cls, path: str) -> "Track":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data, source=os.path.abspath(path))

    def save(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    def start_pose(self, lateral_offset: float = 0.0, row: int = 0) -> tuple[np.ndarray, float]:
        i = self.start_index
        back = int(round(6.0 / max(self.spacing, 1e-6)))
        i0 = (i - back) % self.n
        pos = self.center[i0] + self.normals[i0] * lateral_offset
        return pos, float(self.heading[i0])

    def validate(self) -> list[str]:
        """Problemas de geometria que atrapalham a simulação (avisos)."""
        issues = []
        if self.length < 80:
            issues.append(f"pista muito curta ({self.length:.0f} m)")
        d = np.linalg.norm(self.center[:, None, :] - self.center[None, :, :], axis=2)
        n = self.n

        # distância entre pontos distantes ao longo do traçado (trechos paralelos)
        rows = np.arange(n)
        far = np.abs(rows[:, None] - rows[None, :]) > max(12, n // 20)
        near = (np.abs(rows[:, None] - rows[None, :]) < n - max(12, n // 20))
        mask = far & near
        if mask.any():
            idx = np.argwhere(mask)
            gap = float(d[mask].min())
            need = float(self.half_widths.mean() * 2 + 4.0)
            if gap < need:
                # cruzeiro (figura 8) é legítimo; trechos paralelos colados, não
                ii, jj = idx[np.argmin(np.where(mask, d, np.inf))]
                dot = float(self.tangents[ii] @ self.tangents[jj])
                if abs(dot) > 0.85:
                    issues.append(f"trechos paralelos a só {gap:.1f} m "
                                  f"(recomendado > {need:.0f} m)")
                else:
                    issues.append(f"cruzamento em X (trechos a {gap:.1f} m) — "
                                  f"os carros não colidem entre si")
        # curvatura excessiva para a largura
        r_min = 1.0 / max(np.abs(self.curvature).max(), 1e-6)
        if r_min < self.half_widths.mean() * 0.8:
            issues.append(f"curva muito fechada (raio ~{r_min:.1f} m)")
        return issues

    def bounds(self) -> tuple[float, float, float, float]:
        allp = np.vstack([self.edge_l, self.edge_r])
        return float(allp[:, 0].min()), float(allp[:, 1].min()), \
               float(allp[:, 0].max()), float(allp[:, 1].max())


def make_oval(radius: float = 160.0, width: float = 16.0, wobble: float = 0.0) -> dict:
    pts = []
    for k in range(36):
        a = k / 36.0 * math.tau
        r = radius * (1.0 + wobble * math.sin(3 * a))
        pts.append([round(r * math.cos(a), 2), round(r * math.sin(a) * 0.72, 2)])
    return {"name": "Oval", "closed": True, "width": width, "points": pts}
