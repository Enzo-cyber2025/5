"""Renderização (pygame): câmera, pista, carros, HUD, minimapa e gráfico.

Tudo separado do núcleo de simulação para o treinador headless não precisar
de pygame.
"""
from __future__ import annotations

import math

import numpy as np
import pygame

BG = (16, 18, 22)
GRASS = (26, 46, 30)
GRASS_ALT = (30, 52, 34)
ASPHALT = (58, 60, 66)
ASPHALT_DARK = (48, 50, 56)
EDGE = (225, 228, 235)
KERB_A = (210, 60, 60)
KERB_B = (235, 235, 235)
START_LINE = (240, 240, 240)
TEXT = (232, 236, 243)
TEXT_DIM = (150, 158, 172)
ACCENT = (86, 204, 242)
GOOD = (96, 214, 138)
WARN = (242, 196, 86)
BAD = (232, 96, 96)
PANEL = (24, 27, 33, 220)
DIRT = (110, 84, 56)


class Camera:
    """Câmera 2D com centro em metros e zoom em pixels/metro."""

    def __init__(self, width: int = 1280, height: int = 720, zoom: float = 9.0):
        self.x = 0.0
        self.y = 0.0
        self.zoom = zoom
        self.width = width
        self.height = height
        self.target_zoom = zoom

    def resize(self, width: int, height: int):
        self.width = width
        self.height = height

    def follow(self, tx: float, ty: float, smoothing: float = 0.12, snap: bool = False):
        if snap:
            self.x, self.y = tx, ty
        else:
            self.x += (tx - self.x) * smoothing
            self.y += (ty - self.y) * smoothing

    def set_zoom(self, z: float):
        self.zoom = max(1.5, min(40.0, z))

    def to_screen(self, wx, wy):
        """Converte coordenadas de mundo (metros) para tela (pixels)."""
        z = self.zoom
        sx = (np.asarray(wx) - self.x) * z + self.width * 0.5
        sy = -(np.asarray(wy) - self.y) * z + self.height * 0.5
        return sx, sy

    def to_screen_points(self, pts: np.ndarray) -> np.ndarray:
        sx, sy = self.to_screen(pts[:, 0], pts[:, 1])
        return np.stack([sx, sy], axis=1)

    def visible_radius(self) -> float:
        return math.hypot(self.width, self.height) * 0.5 / self.zoom


class SpriteCache:
    """Sprites de carro pré-rotacionados (evita rotacionar 100 carros/frame)."""

    def __init__(self):
        self.cache = {}
        self.base_zoom = 14.0

    def _make(self, spec, zoom: float) -> pygame.Surface:
        px_len = max(6, int(spec.length * zoom))
        px_wid = max(4, int(spec.width * zoom))
        pad = 2
        surf = pygame.Surface((px_len + pad * 2, px_wid + pad * 2), pygame.SRCALPHA)
        w, h = surf.get_size()
        body = pygame.Color(spec.body_color)
        accent = pygame.Color(spec.accent_color)
        # pneus
        pygame.draw.rect(surf, (18, 18, 20), (0, 0, w, h), border_radius=max(2, h // 5))
        # carroceria
        pygame.draw.rect(surf, body, (pad, pad, w - pad * 2, h - pad * 2),
                         border_radius=max(2, h // 4))
        # faixa do capô / cockpit
        pygame.draw.rect(surf, accent,
                         (w * 0.34, h * 0.30, w * 0.30, h * 0.40),
                         border_radius=max(1, h // 8))
        # para-brisa dianteiro
        pygame.draw.rect(surf, (30, 34, 42),
                         (w * 0.70, h * 0.28, w * 0.14, h * 0.44),
                         border_radius=max(1, h // 10))
        # rodas
        wheel_h = max(2, int(h * 0.18))
        pygame.draw.rect(surf, (12, 12, 14), (w * 0.10, pad - 1, w * 0.16, wheel_h))
        pygame.draw.rect(surf, (12, 12, 14), (w * 0.10, h - pad - wheel_h + 1, w * 0.16, wheel_h))
        pygame.draw.rect(surf, (12, 12, 14), (w * 0.72, pad - 1, w * 0.16, wheel_h))
        pygame.draw.rect(surf, (12, 12, 14), (w * 0.72, h - pad - wheel_h + 1, w * 0.16, wheel_h))
        return surf

    def get(self, spec, heading: float, zoom: float) -> tuple[pygame.Surface, tuple[int, int]]:
        z_key = max(2.0, round(zoom * 2) / 2)          # passo de 0.5 px/m
        rot = int(round(math.degrees(-heading) / 5.0) * 5) % 360
        key = (spec.id, z_key, rot)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        base = self.cache.get((spec.id, "base"))
        size = (max(6, int(spec.length * z_key)), max(4, int(spec.width * z_key)))
        base_key = (spec.id, "base")
        if base is None or base[0].get_size() != tuple(np.array(size) + 4):
            base = (self._make(spec, z_key), size)
            self.cache[base_key] = base
        surf = pygame.transform.rotate(base[0], rot)
        self.cache[key] = (surf, (surf.get_width() // 2, surf.get_height() // 2))
        return self.cache[key]


class Renderer:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.sprites = SpriteCache()
        self.font_cache = {}
        self.track_surface = None
        self.track_key = None

    # ------------------------------------------------------------------ #
    def font(self, size: int, bold: bool = False):
        key = (size, bold)
        if key not in self.font_cache:
            self.font_cache[key] = pygame.font.Font(None, size)
        return self.font_cache[key]

    def text(self, surf, msg, pos, size=18, color=TEXT, bold=False, anchor="topleft",
             shadow=True):
        font = self.font(size, bold)
        img = font.render(str(msg), True, color)
        r = img.get_rect()
        setattr(r, anchor, pos)
        if shadow:
            bg = font.render(str(msg), True, (0, 0, 0))
            surf.blit(bg, (r.x + 1, r.y + 1))
        surf.blit(img, r)
        return r

    # ------------------------------------------------------------------ #
    def draw_background(self):
        self.screen.fill(BG)
        # leve textura de grama em faixas
        h = self.screen.get_height()
        for y in range(0, h, 64):
            shade = GRASS if (y // 64) % 2 == 0 else GRASS_ALT
            pygame.draw.rect(self.screen, shade, (0, y, self.screen.get_width(), 64))

    def draw_track(self, track, camera: Camera):
        """Desenha asfalto, zebras, linha de largada e zonas especiais."""
        n = track.n
        step = max(1, n // 260)
        idx = np.arange(0, n, step)
        left = camera.to_screen_points(track.edge_l[idx])
        right = camera.to_screen_points(track.edge_r[idx])

        # culling grosseiro pelo bounding box da tela
        poly = np.vstack([left, right[::-1]])
        visible = ((poly[:, 0] > -600) & (poly[:, 0] < camera.width + 600) &
                   (poly[:, 1] > -600) & (poly[:, 1] < camera.height + 600))
        if visible.any():
            try:
                pygame.draw.polygon(self.screen, ASPHALT, poly.astype(int))
            except (ValueError, TypeError):
                pass

        # zonas de baixa aderência
        if track.grip.min() < 0.999:
            zone = track.grip[idx] < 0.999
            if zone.any() and zone.sum() > 1:
                segs = np.flatnonzero(zone)
                if len(segs) > 1:
                    i0, i1 = segs[0], segs[-1]
                    pts = np.vstack([left[i0:i1 + 1], right[i1:i0 - 1 if i0 > 0 else None:-1]])
                    if len(pts) > 2:
                        try:
                            pygame.draw.polygon(self.screen, DIRT, pts.astype(int))
                        except (ValueError, TypeError):
                            pass

        # zebras nas bordas (linhas grossas)
        pygame.draw.lines(self.screen, KERB_A, track.closed, left.astype(int), 3)
        pygame.draw.lines(self.screen, KERB_A, track.closed, right.astype(int), 3)
        pygame.draw.lines(self.screen, EDGE, track.closed, left.astype(int), 1)
        pygame.draw.lines(self.screen, EDGE, track.closed, right.astype(int), 1)

        # linha de largada
        i = track.start_index
        p0 = track.edge_l[i]
        p1 = track.edge_r[i]
        a = camera.to_screen(p0[0], p0[1])
        b = camera.to_screen(p1[0], p1[1])
        pygame.draw.line(self.screen, START_LINE, a, b, 4)

        # seta de sentido
        j = (i + max(2, int(12 / max(track.spacing, 1e-6)))) % track.n
        c = camera.to_screen(track.center[j][0], track.center[j][1])
        tang = track.tangents[j]
        tip = (c[0] + tang[0] * 22, c[1] - tang[1] * 22)
        pygame.draw.line(self.screen, ACCENT, c, tip, 3)
        pygame.draw.circle(self.screen, ACCENT, (int(tip[0]), int(tip[1])), 4)

    def draw_cars(self, spec, fleet, n_active: int, camera: Camera, focus: int = -1,
                  max_draw: int = 200, alpha_ghosts: bool = True, draw_rays: bool = False,
                  track=None, ray_count: int = 9, ray_range: float = 70.0):
        order = list(range(min(n_active, max_draw)))
        if focus >= 0 and focus in order:
            order.remove(focus)
            order.append(focus)            # foco por último (por cima)
        for i in order:
            is_focus = (i == focus)
            if not fleet.alive[i] and not is_focus:
                continue
            wx, wy = fleet.x[i], fleet.y[i]
            sx, sy = camera.to_screen(wx, wy)
            if not (-80 < sx < camera.width + 80 and -80 < sy < camera.height + 80):
                continue
            surf, off = self.sprites.get(spec, fleet.heading[i], camera.zoom)
            if not is_focus and alpha_ghosts:
                surf = surf.copy()
                surf.set_alpha(150)
            self.screen.blit(surf, (int(sx) - off[0], int(sy) - off[1]))
            if is_focus:
                pygame.draw.circle(self.screen, ACCENT, (int(sx), int(sy)), 5, 2)
            if is_focus and draw_rays and track is not None:
                self.draw_sensor_rays(track, fleet, i, camera, ray_count, ray_range)

    def draw_sensor_rays(self, track, fleet, i, camera: Camera, n_rays=9, max_range=70.0):
        pos = np.array([[fleet.x[i], fleet.y[i]]])
        heading = np.array([fleet.heading[i]])
        dists = track.cast_rays(pos, heading, np.array([fleet.idx[i]]), n_rays=n_rays,
                                max_range=max_range, fov=math.radians(140.0))[0]
        offs = np.linspace(-math.radians(140.0) / 2, math.radians(140.0) / 2, n_rays)
        sx, sy = camera.to_screen(fleet.x[i], fleet.y[i])
        for k in range(n_rays):
            ang = fleet.heading[i] + offs[k]
            d = dists[k] * camera.zoom
            end = (sx + math.cos(ang) * d, sy - math.sin(ang) * d)
            hit = dists[k] < max_range * 0.995
            col = (120, 200, 255, 160) if hit else (110, 120, 140, 120)
            pygame.draw.line(self.screen, col[:3], (sx, sy), end, 1)

    # ------------------------------------------------------------------ #
    def panel(self, rect, alpha=200, border=True):
        surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(surf, (22, 25, 31, alpha), surf.get_rect(), border_radius=8)
        if border:
            pygame.draw.rect(surf, (60, 68, 84, alpha), surf.get_rect(), 1, border_radius=8)
        self.screen.blit(surf, rect.topleft)
        return rect

    def draw_minimap(self, track, fleet, n_active, focus: int, rect: pygame.Rect):
        self.panel(rect)
        minx, miny, maxx, maxy = track.bounds()
        w = maxx - minx
        h = maxy - miny
        pad = 10
        scale = min((rect.width - pad * 2) / max(w, 1e-6), (rect.height - pad * 2) / max(h, 1e-6))
        ox = rect.x + pad + (rect.width - pad * 2 - w * scale) * 0.5
        oy = rect.y + pad + (rect.height - pad * 2 - h * scale) * 0.5

        def mp(pts):
            return np.stack([ox + (pts[:, 0] - minx) * scale,
                             oy + (maxy - pts[:, 1]) * scale], axis=1)

        cl = mp(track.center)
        pygame.draw.lines(self.screen, (90, 96, 110), track.closed, cl.astype(int),
                          max(2, int(track.half_widths.mean() * scale)))
        pygame.draw.lines(self.screen, (140, 148, 165), track.closed, cl.astype(int), 1)
        sl = track.start_index
        pygame.draw.circle(self.screen, START_LINE, mp(track.center[sl:sl + 1])[0].astype(int), 3)
        if n_active:
            cars = np.stack([fleet.x[:n_active], fleet.y[:n_active]], axis=1)
            pts = mp(cars).astype(int)
            for p in pts:
                pygame.draw.circle(self.screen, (200, 210, 230), p, 1)
            if 0 <= focus < n_active:
                pygame.draw.circle(self.screen, ACCENT, pts[focus].astype(int), 3)

    def draw_plot(self, history: list, rect: pygame.Rect, title: str = "evolução do fitness"):
        self.panel(rect)
        self.text(self.screen, title, (rect.x + 8, rect.y + 6), 15, TEXT_DIM)
        if len(history) < 2:
            self.text(self.screen, "sem dados ainda", (rect.x + 10, rect.centery - 8), 15, TEXT_DIM)
            return
        vals = np.array([[h.get("best", 0.0), h.get("mean", 0.0)] for h in history], dtype=float)
        lo = float(np.nanmin(vals))
        hi = float(np.nanmax(vals))
        if hi - lo < 1e-6:
            hi = lo + 1.0
        plot = rect.inflate(-16, -30)
        plot.y += 14
        n = len(vals)
        xs = plot.x + np.linspace(0, plot.width - 1, n)

        def y_of(v):
            return plot.y + plot.height - (v - lo) / (hi - lo) * plot.height

        pts_best = list(zip(xs, y_of(vals[:, 0])))
        pts_mean = list(zip(xs, y_of(vals[:, 1])))
        pygame.draw.lines(self.screen, GOOD, False, pts_best, 2)
        pygame.draw.lines(self.screen, ACCENT, False, pts_mean, 1)
        self.text(self.screen, f"{hi:,.0f}", (plot.right + 2, plot.y - 4), 12, TEXT_DIM,
                  anchor="topright")
        self.text(self.screen, f"{lo:,.0f}", (plot.right + 2, plot.bottom - 12), 12, TEXT_DIM,
                  anchor="topright")
        last = history[-1]
        self.text(self.screen, f"melhor {last.get('best', 0):,.0f} · média {last.get('mean', 0):,.0f}",
                  (rect.x + 8, rect.bottom - 20), 14, TEXT)

    def bar(self, rect, frac, color, bg=(45, 50, 60), label="", value=""):
        pygame.draw.rect(self.screen, bg, rect, border_radius=3)
        w = max(0, min(1.0, frac)) * rect.width
        if w > 1:
            pygame.draw.rect(self.screen, color, (rect.x, rect.y, w, rect.height), border_radius=3)
        if label:
            self.text(self.screen, label, (rect.x, rect.y - 15), 13, TEXT_DIM)
        if value:
            self.text(self.screen, value, (rect.right, rect.y - 15), 13, TEXT_DIM,
                      anchor="topright")
