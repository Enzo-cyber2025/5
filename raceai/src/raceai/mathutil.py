"""Utilitários matemáticos usados pelo núcleo de simulação (sem dependência de pygame).

Tudo aqui é pensado para rodar vetorizado em numpy: a simulação precisa
atualizar centenas de carros por passo, inclusive no modo headless.
"""
from __future__ import annotations

import numpy as np

TAU = np.pi * 2.0


def wrap_angle(a):
    """Normaliza ângulo(s) para o intervalo (-pi, pi]."""
    return (np.asarray(a) + np.pi) % TAU - np.pi


def cross2(ax, ay, bx, by):
    """Produto vetorial 2D (escalar) de dois vetores, preservando shape por broadcasting."""
    return ax * by - ay * bx


def rotate(vx, vy, ang):
    """Rotaciona vetor (vx, vy) por ang radianos."""
    c, s = np.cos(ang), np.sin(ang)
    return vx * c - vy * s, vx * s + vy * c


def polyline_arc_lengths(pts: np.ndarray, closed: bool = True) -> np.ndarray:
    """Comprimento acumulado ao longo da polilinha (N+1 no caso fechado)."""
    pts = np.asarray(pts, dtype=np.float64)
    d = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    if closed:
        d = np.concatenate([d, [np.linalg.norm(pts[0] - pts[-1])]])
    return np.concatenate([[0.0], np.cumsum(d)])


def catmull_rom(points: np.ndarray, samples_per_seg: int = 20, closed: bool = True,
                tension: float = 0.5) -> np.ndarray:
    """Interpola pontos de controle com spline Catmull-Rom (centrípeta simplificada)."""
    pts = np.asarray(points, dtype=np.float64)
    n = len(pts)
    out = []
    if closed:
        idx_range = range(n)
    else:
        idx_range = range(n - 1)

    def get(i):
        if closed:
            return pts[i % n]
        return pts[max(0, min(n - 1, i))]

    for i in idx_range:
        p0, p1, p2, p3 = get(i - 1), get(i), get(i + 1), get(i + 2)
        for k in range(samples_per_seg):
            t = k / samples_per_seg
            t2, t3 = t * t, t * t * t
            # Catmull-Rom uniforme
            c0 = -tension * t3 + 2 * tension * t2 - tension * t
            c1 = (2 - tension) * t3 + (tension - 3) * t2 + 1
            c2 = (tension - 2) * t3 + (3 - 2 * tension) * t2 + tension * t
            c3 = tension * t3 - tension * t2
            out.append(c0 * p0 + c1 * p1 + c2 * p2 + c3 * p3)
    res = np.asarray(out, dtype=np.float64)
    if not closed:
        res = np.vstack([res, pts[-1]])
    return res


def resample_polyline(pts: np.ndarray, spacing: float, closed: bool = True) -> np.ndarray:
    """Reamostra a polilinha com espaçamento (quase) constante em metros.

    `closed=True` inclui o segmento de fechamento (pts[-1] -> pts[0]) e
    devolve pontos igualmente espaçados ao longo de todo o circuito.
    """
    pts = np.asarray(pts, dtype=np.float64)
    n = len(pts)
    lengths = polyline_arc_lengths(pts, closed)     # n+1 (fechado) ou n (aberto)
    total = float(lengths[-1])
    n_seg = n if closed else n - 1
    spacing = max(float(spacing), 1e-3)
    n_out = max(8 if closed else 2, int(round(total / spacing)))
    targets = np.linspace(0.0, total, n_out, endpoint=not closed)
    out = np.empty((n_out, 2), dtype=np.float64)
    j = 0
    for i, target in enumerate(targets):
        # os alvos são crescentes: basta avançar o segmento atual
        while j < n_seg - 1 and lengths[j + 1] <= target:
            j += 1
        seg_len = lengths[j + 1] - lengths[j]
        t = 0.0 if seg_len <= 1e-9 else (target - lengths[j]) / seg_len
        t = min(max(t, 0.0), 1.0)
        a = pts[j % n]
        b = pts[(j + 1) % n]
        out[i] = a + (b - a) * t
    return out


def path_tangents(pts: np.ndarray, closed: bool = True) -> np.ndarray:
    """Tangente unitária em cada ponto da polilinha."""
    pts = np.asarray(pts, dtype=np.float64)
    if closed:
        nxt = np.roll(pts, -1, axis=0)
        prv = np.roll(pts, 1, axis=0)
    else:
        nxt = np.vstack([pts[1:], pts[-1:]])
        prv = np.vstack([pts[:1], pts[:-1]])
    d = nxt - prv
    norm = np.linalg.norm(d, axis=1, keepdims=True)
    norm = np.maximum(norm, 1e-9)
    return d / norm


def path_curvature(pts: np.ndarray, closed: bool = True) -> np.ndarray:
    """Curvatura discreta (1/raio) com sinal em cada ponto."""
    tan = path_tangents(pts, closed)
    ang = np.arctan2(tan[:, 1], tan[:, 0])
    if closed:
        dang = wrap_angle(np.roll(ang, -1) - ang)
        seg = np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)
    else:
        dang = wrap_angle(np.diff(np.concatenate([ang, ang[-1:]])))
        seg = np.maximum(np.linalg.norm(np.diff(pts, axis=0), axis=1)[0], 1e-6)
    return dang / np.maximum(seg, 1e-6)


def ray_segment_distance(origin, direction, seg_p, seg_q, max_range: float):
    """Interseção raio x segmentos, vetorizada.

    Parâmetros
    ----------
    origin : (A, R, 1, 2) pontos de origem dos raios
    direction : (A, R, 1, 2) direções unitárias
    seg_p, seg_q : (A, 1, S, 2) extremos dos segmentos candidatos

    Retorna (A, R) com a menor distância positiva de acerto (ou max_range).
    """
    w = seg_p - origin                      # (A,R,S,2)
    e = seg_q - seg_p                       # (A,1,S,2) -> broadcast
    dx = direction[..., 0]
    dy = direction[..., 1]
    ex = e[..., 0]
    ey = e[..., 1]
    denom = dy * ex - dx * ey               # cross(e, d) com sinal consistente
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (w[..., 0] * ey - w[..., 1] * ex) / denom
        u = (w[..., 0] * dy - w[..., 1] * dx) / denom
    valid = (np.abs(denom) > 1e-9) & (t > 0.0) & (u >= 0.0) & (u <= 1.0)
    t = np.where(valid, t, np.inf)
    t = np.where(t < max_range, t, np.inf)
    best = np.min(t, axis=-1)
    return np.where(np.isfinite(best), best, max_range)


def lerp(a, b, t):
    return a + (b - a) * t


def clamp(x, lo, hi):
    return np.minimum(np.maximum(x, lo), hi)


def moving_average(values, window):
    if len(values) == 0:
        return np.array([])
    window = max(1, int(window))
    if len(values) < window:
        return np.cumsum(values) / np.arange(1, len(values) + 1)
    csum = np.cumsum(np.insert(values, 0, 0.0))
    return (csum[window:] - csum[:-window]) / window
