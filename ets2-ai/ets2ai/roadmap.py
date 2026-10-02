"""Mapa de pista APRENDIDO dirigindo — como a IA "pratica" no ETS2 real.

O SDK de telemetria do ETS2 nao expoe geometria da estrada: nao existe canal
"offset na faixa" nem "curvatura a 40 m a frente". O que existe: posicao GPS
(world_x/world_z) e direcao. Este modulo transforma posicoes observadas nas
features que o contrato (ets2ai.contract) exige:

  * cada passada de direcao grava a trajetoria a cada ~2 m;
  * passadas seguintes REFINAM a linha central (media movel) — o mapa melhora
    a cada volta, exatamente como um motorista que decorou a estrada;
  * a partir dai o mapa responde: offset lateral (sinal do contrato: + =
    direita), erro de direcao e curvatura a 8/18/40/90/170 m a frente
    (sim.LOOKAHEAD), com o MESMO sinal do simulador (curvatura + = curva a
    direita).

Convencao de eixos: o ETS2 usa um sistema proprio; em vez de confiar em
de-coracao, o Frame e CALIBRADO dirigindo (vide detect_frame): o par
(x, y) = (world_x, +-world_z) cujo "curso" gira para o lado do volante.
Rotacao do frame e irrelevante (toda a matematica do modelo e relativa ao
heading); so a reflexao (espelhamento) importa, e ela e detectada
empiricamente.
"""
import json
import math
from pathlib import Path

import numpy as np

GRID = 10.0          # metros por celula do indice espacial
STEP = 2.0           # espaçamento minimo entre pontos registrados
REFINE_W = 0.18      # peso do EMA ao refinar a linha central numa revisitada
MAX_LATERAL = 8.0    # mais longe que isso = outra estrada, nao refina
ANGLE_TOL = math.radians(65.0)   # heading alinhado dentro de +-65 graus


def wrap(a):
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


class Frame:
    """Transforma (world_x, world_z) do jogo no plano 2D do modelo.

    z_flip: reflexao do eixo z. Enquanto nao calibrado, vale o default
    (sem espelho). Depois de detect_frame(), fica travado e persistido junto
    com o mapa.
    """
    def __init__(self, z_flip=False, locked=False):
        self.z_flip = bool(z_flip)
        self.locked = bool(locked)

    def to_frame(self, wx, wz):
        return (float(wx), -float(wz) if self.z_flip else float(wz))

    def to_world(self, x, y):
        return (float(x), -float(y) if self.z_flip else float(y))

    def as_dict(self):
        return {"z_flip": self.z_flip, "locked": self.locked}

    @staticmethod
    def from_dict(d):
        return Frame(z_flip=d.get("z_flip", False),
                     locked=d.get("locked", False))


def detect_frame(world_pts, steers):
    """Descobre a reflexao certa a partir de uma dirigida de calibracao.

    world_pts: lista de (wx, wz) na ordem; steers: volante do jogo (-1..1,
    + = direita) nas mesmas amostras. Ideia: no frame correto, virar o volante
    a direita aumenta o "curso" (angulo do deslocamento). Como rotacoes nao
    importam, basta comparar a reflexao vs a identidade.

    Retorna (Frame, qualidade) — qualidade em [-1..1]; |q| < 0.15 = dirigida
    sem curvas suficientes (nao travar).
    """
    if len(world_pts) < 20 or len(steers) != len(world_pts):
        return Frame(locked=False), 0.0
    pts = np.asarray(world_pts, dtype=np.float64)
    steer = np.asarray(steers, dtype=np.float64)
    d = pts[1:] - pts[:-1]                       # deslocamentos
    dist = np.hypot(d[:, 0], d[:, 1])
    ok = dist > 0.05
    if ok.sum() < 10:
        return Frame(locked=False), 0.0
    d, dist = d[ok], dist[ok]
    s = steer[1:][ok]
    course = np.arctan2(d[:, 1], d[:, 0])        # plano bruto (wx, wz)
    dc = np.diff(course)
    dc = (dc + math.pi) % (2.0 * math.pi) - math.pi
    # virar a direita: no frame bruto o curso pode girar + ou -
    pos = float(np.sum(dc * s[:-1][: len(dc)]))
    tot = float(np.sum(np.abs(dc))) + 1e-9
    if tot < 0.35:                               # ~20 graus de curva no total
        return Frame(locked=False), 0.0
    q = pos / tot
    z_flip = q < 0.0                             # espelho se girar ao contrario
    return Frame(z_flip=z_flip, locked=True), abs(q)


class RoadMap:
    """Linha central aprendida + consultas de features do contrato."""

    def __init__(self, frame=None):
        self.frame = frame or Frame()
        self.x = []          # posicao (frame) da linha central
        self.y = []
        self.h = []          # heading (frame) da estrada no ponto
        self.s = []          # arclength dentro da passada
        self.pass_id = []    # qual passada gravou o ponto
        self.vref = []       # velocidade humana no ponto (EMA)
        self.hits = []       # quantas vezes o ponto foi refinado
        self._pass = -1
        self._grid = {}      # (cx, cy) -> [indices]
        self._last_raw = None    # (x, y, heading) da ultima observacao

    # ------------------------------------------------------------------ #
    # gravacao
    # ------------------------------------------------------------------ #
    def _cell(self, x, y):
        return (int(math.floor(x / GRID)), int(math.floor(y / GRID)))

    def _index_add(self, i):
        c = self._cell(self.x[i], self.y[i])
        self._grid.setdefault(c, []).append(i)

    def record(self, wx, wz, heading, speed, refine=True):
        """Grava/refina a partir de uma posicao observada.

        heading: direcao de deslocamento no PLANO BRUTO do jogo (curso),
        calculado pelo chamador a partir de (wx, wz) consecutivos — o metodo
        converte para o frame. Retorna True se criou ponto novo.
        """
        if self.frame.z_flip:
            heading = -heading
        x, y = self.frame.to_frame(wx, wz)
        if self._last_raw is not None:
            lx, ly, lh = self._last_raw
            d = math.hypot(x - lx, y - ly)
            if d < STEP:
                return False
            if d > 30.0 or abs(wrap(heading - lh)) > math.radians(75.0):
                self._pass += 1               # teleporte/outra passada
        else:
            self._pass += 1
        self._last_raw = (x, y, heading)
        # passada anterior ja mapeou este trecho? -> refina a linha central
        if refine:
            near = self._nearest(x, y, heading, exclude_pass=self._pass,
                                 ahead=False)
            if near is not None:
                i = near
                w = REFINE_W / max(1, self.hits[i]) ** 0.5
                self.x[i] = (1.0 - w) * self.x[i] + w * x
                self.y[i] = (1.0 - w) * self.y[i] + w * y
                self.h[i] = self.h[i] + w * wrap(heading - self.h[i])
                self.vref[i] = (1.0 - w) * self.vref[i] + w * speed
                self.hits[i] += 1
                return False
        self.x.append(x); self.y.append(y); self.h.append(heading)
        base = 0.0
        for j in range(len(self.x) - 2, -1, -1):
            if self.pass_id[j] == self._pass:
                base = self.s[j] + math.hypot(x - self.x[j], y - self.y[j])
                break
        self.s.append(base)
        self.pass_id.append(self._pass)
        self.vref.append(speed)
        self.hits.append(1)
        self._index_add(len(self.x) - 1)
        return True

    # ------------------------------------------------------------------ #
    # consulta
    # ------------------------------------------------------------------ #
    def _nearest(self, x, y, heading, exclude_pass=None, ahead=True,
                 max_lateral=MAX_LATERAL):
        """Ponto da linha central mais proximo, com heading alinhado.

        ahead=True exige que o ponto esteja a frente do caminhao (consulta
        de features); ahead=False aceita pontos laterais (refinamento).
        """
        cx, cy = self._cell(x, y)
        best, best_d = None, max_lateral ** 2
        ch = math.cos(heading)
        sh = math.sin(heading)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for i in self._grid.get((gx, gy), ()):
                    if exclude_pass is not None and self.pass_id[i] == exclude_pass:
                        continue
                    dx, dy = self.x[i] - x, self.y[i] - y
                    if ahead and dx * ch + dy * sh < -5.0:
                        continue   # bem atras (protege contra estrada ja feita)
                    if abs(wrap(self.h[i] - heading)) > ANGLE_TOL:
                        continue
                    d2 = dx * dx + dy * dy
                    if d2 < best_d:
                        best, best_d = i, d2
        return best

    def locate(self, wx, wz, heading):
        """(idx, offset, tangent) na linha central; None se fora do mapa.

        offset segue o contrato: + = direita do sentido da estrada.
        """
        if self.frame.z_flip:
            heading = -heading
        x, y = self.frame.to_frame(wx, wz)
        i = self._nearest(x, y, heading)
        if i is None:
            return None
        # projeto no segmento (i -> vizinho a frente da mesma passada)
        j = self._next_in_pass(i, heading)
        if j is not None:
            ax, ay, bx, by = self.x[i], self.y[i], self.x[j], self.y[j]
        else:
            k = self._prev_in_pass(i)
            ax, ay, bx, by = self.x[k], self.y[k], self.x[i], self.y[i]
        ux, uy = bx - ax, by - ay
        n = math.hypot(ux, uy) or 1e-9
        ux, uy = ux / n, uy / n
        t = max(0.0, min(n, (x - ax) * ux + (y - ay) * uy))
        px, py = ax + ux * t, ay + uy * t
        tangent = math.atan2(uy, ux)
        rx, ry = x - px, y - py
        # direita do sentido = (-sin, cos)? nao: direita = (uy_normal)
        # vetor "direita" do heading t: (sin(t)? ) — ver contrato: offset+ =
        # direita => (x - offset*sin(th), y + offset*cos(th)) no sim =>
        # direita(t) = (-sin(t), cos(t))... que e a ESQUERDA em matematica
        # padrao; o sim usa plano tipo tela (y para baixo). Para manter o
        # MESMO sinal do sim usamos right = (-sin t, cos t) — vide teste.
        rightx, righty = -math.sin(tangent), math.cos(tangent)
        offset = rx * rightx + ry * righty
        return i, offset, tangent

    def _next_in_pass(self, i, heading):
        for j in (i + 1, i + 2, i - 1):
            if 0 <= j < len(self.x) and self.pass_id[j] == self.pass_id[i]:
                dx, dy = self.x[j] - self.x[i], self.y[j] - self.y[i]
                if math.hypot(dx, dy) > 1e-6 and \
                        (dx * math.cos(heading) + dy * math.sin(heading)) > 0.0:
                    return j
        return None

    def _prev_in_pass(self, i):
        for j in (i - 1, i + 1):
            if 0 <= j < len(self.x) and self.pass_id[j] == self.pass_id[i]:
                return j
        return i

    def _walk(self, i, heading):
        """Indices da mesma passada, na ordem do deslocamento, a partir de i."""
        j = self._next_in_pass(i, heading)
        step = 1 if (j is not None and j > i) else -1
        out = []
        k = i
        while 0 <= k < len(self.x) and (k == i or self.pass_id[k] == self.pass_id[i]):
            out.append(k)
            k += step
        return out

    def curvatures_ahead(self, idx, heading, dists=(8.0, 18.0, 40.0, 90.0, 170.0)):
        """Curvatura (1/m, sinal do sim: + = curva a direita) a `dists` m.

        Retorna lista com None onde o mapa nao alcanca.
        """
        chain = self._walk(idx, heading)
        if len(chain) < 3:
            return [None] * len(dists)
        si = self.s[chain[0]]
        out, target = [], 0
        arcs = [self.s[k] - si for k in chain]
        # curvature Menger assinada em cada ponto interno da cadeia
        ks = [0.0] * len(chain)
        for a in range(1, len(chain) - 1):
            A = (self.x[chain[a - 1]], self.y[chain[a - 1]])
            B = (self.x[chain[a]], self.y[chain[a]])
            C = (self.x[chain[a + 1]], self.y[chain[a + 1]])
            u = (B[0] - A[0], B[1] - A[1])
            v = (C[0] - B[0], C[1] - B[1])
            nu, nv = math.hypot(*u), math.hypot(*v)
            if nu < 1e-6 or nv < 1e-6:
                continue
            cross = u[0] * v[1] - u[1] * v[0]
            ks[a] = 2.0 * cross / (nu * nv * math.hypot(u[0] + v[0], u[1] + v[1]))
        for d in dists:
            # ponto da cadeia mais proximo da arclength alvo
            kbest, dbest = None, None
            for a, arc in enumerate(arcs):
                if a == 0:
                    continue
                dd = abs(arc - d)
                if dbest is None or dd < dbest:
                    kbest, dbest = a, dd
            if dbest is None or arcs[-1] < d * 0.98:
                out.append(None)      # mapa nao alcanca tao longe
                continue
            out.append(ks[max(1, min(len(chain) - 2, kbest))])
        return out

    def coverage(self, idx, heading, dists=(8.0, 18.0, 40.0, 90.0, 170.0)):
        cs = self.curvatures_ahead(idx, heading, dists)
        return sum(1 for c in cs if c is not None)

    # ------------------------------------------------------------------ #
    # persistencia / estatisticas
    # ------------------------------------------------------------------ #
    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "ets2ai-roadmap,v1",
            "frame": self.frame.as_dict(),
            "x": [round(v, 3) for v in self.x],
            "y": [round(v, 3) for v in self.y],
            "h": [round(v, 5) for v in self.h],
            "s": [round(v, 2) for v in self.s],
            "pass": list(self.pass_id),
            "vref": [round(v, 2) for v in self.vref],
            "hits": list(self.hits),
            "_pass": self._pass,
        }
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def load(path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        assert d["format"] == "ets2ai-roadmap,v1"
        m = RoadMap(Frame.from_dict(d["frame"]))
        m.x = list(d["x"]); m.y = list(d["y"]); m.h = list(d["h"])
        m.s = list(d["s"]); m.pass_id = list(d["pass"])
        m.vref = list(d["vref"]); m.hits = list(d["hits"])
        m._pass = int(d["_pass"])
        for i in range(len(m.x)):
            m._index_add(i)
        return m

    def stats(self):
        per_pass = {}
        for i, p in enumerate(self.pass_id):
            per_pass[p] = max(per_pass.get(p, 0.0), self.s[i])
        km = sum(per_pass.values()) / 1000.0
        return {"pontos": len(self.x), "passadas": len(per_pass),
                "km_mapeados": round(km, 2),
                "frame_travado": self.frame.locked,
                "z_flip": self.frame.z_flip}
