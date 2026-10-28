"""Piloto automático clássico (perseguição pura + controle de velocidade).

Serve para três coisas:
  * modo "Assistir IA" funcionar mesmo sem nenhum modelo carregado;
  * comparar a rede treinada com uma referência determinística;
  * validar pistas novas (se o piloto clássico não consegue, a pista é difícil).

Não evolui, não tem pesos: é geometria + física simples.
"""
from __future__ import annotations

import math

import numpy as np

G = 9.81


class Autopilot:
    """Perseguição pura: mira um ponto à frente na linha de centro."""

    def __init__(self, track, car, lookahead: float = 6.0, lookahead_k: float = 0.55,
                 gain: float = 1.6, grip: float = 1.4, aggression: float = 1.0,
                 brake_margin: float = 1.0):
        self.track = track
        self.car = car
        self.lookahead = lookahead
        self.lookahead_k = lookahead_k
        self.gain = gain
        self.grip = grip
        self.aggression = aggression
        self.brake_margin = brake_margin

    def update(self, track=None, car=None):
        if track is not None:
            self.track = track
        if car is not None:
            self.car = car

    def actions(self, sim, indices: np.ndarray) -> np.ndarray:
        """Ações [esterço, acelerador] para os agentes em `indices`."""
        if len(indices) == 0:
            return np.zeros((0, 2), dtype=np.float32)
        trk = self.track
        f = sim.fleet
        v = f.speed[indices]
        idx = f.idx[indices]

        # ponto alvo à frente proporcional à velocidade
        ld = self.lookahead + self.lookahead_k * v
        step = np.maximum(1, np.round(ld / max(trk.spacing, 1e-6)).astype(int))
        j = (idx + step) % trk.n
        tgt = trk.center[j]
        err = ((np.arctan2(tgt[:, 1] - f.y[indices], tgt[:, 0] - f.x[indices])
                - f.heading[indices] + np.pi) % (2 * np.pi) - np.pi)
        steer = np.clip(self.gain * err / max(self.car.max_steer, 1e-6), -1.0, 1.0)

        # velocidade alvo: curvatura à frente limitada pela aderência
        k = np.abs(trk.curvature[j])
        far = np.maximum(1, np.round(35.0 / max(trk.spacing, 1e-6)).astype(int))
        k2 = np.abs(trk.curvature[(idx + far) % trk.n])
        k = np.maximum(k, k2 * 0.85)
        v_target = np.sqrt(G * self.grip * self.aggression / np.maximum(k, 1e-5))
        v_target = np.minimum(v_target, self.car.max_speed * 0.95)

        # frenagem antecipada: precisa reduzir antes da curva
        need = np.sqrt(np.maximum(v_target ** 2 + 2 * self.car.brake_force /
                                  max(self.car.mass, 1.0) * 35.0 * self.brake_margin, 0.0))
        drive = np.clip((v_target - v) * 0.55, -1.0, 1.0)
        drive = np.where(v > need, np.clip((v_target - v) * 0.9, -1.0, 0.0), drive)
        return np.column_stack([steer, drive]).astype(np.float32)

    def describe(self) -> str:
        return (f"piloto clássico: olhar {self.lookahead:.0f}+{self.lookahead_k:.2f}·v m, "
                f"ganho {self.gain:.2f}, aderência assumida {self.grip:.2f}")
