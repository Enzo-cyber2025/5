"""Núcleo de simulação: frota de carros, sensores, colisão e fitness.

Este módulo é **headless** (não importa pygame) para que o treinador de
linha de comando e o jogo usem exatamente a mesma física.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .car import CarBatch, CarSpec, physics_step
from .track import Track

OBS_RAYS_DEFAULT = 9
OBS_EXTRA = 15              # campos além dos raios (ver build_observation)


@dataclass
class SimConfig:
    dt: float = 1.0 / 120.0
    decision_interval: int = 4        # passos de física entre decisões da rede (~30 Hz)
    n_rays: int = OBS_RAYS_DEFAULT
    ray_range: float = 70.0
    fov_deg: float = 140.0
    max_seconds: float = 60.0
    target_laps: int = 0              # 0 = ilimitado
    grass_grip: float = 0.62
    grass_roll: float = 4.0
    runoff: float = 3.5               # faixa de escape antes do muro (m)
    stall_seconds: float = 2.0
    wrong_way_seconds: float = 2.5    # tempo contra o sentido da pista antes de desistir
    max_crashes: int = 40
    time_penalty: float = 0.08        # por segundo vivo
    offtrack_penalty: float = 1.2     # por segundo fora da pista
    crash_penalty: float = 4.0        # por batida (valores maiores deixam a população medrosa)
    finish_bonus_per_second: float = 40.0
    spawn_rows: int = 0               # 0 = automático


class Fleet:
    """Estado de todos os carros da frota (arrays numpy)."""

    def __init__(self, n: int):
        self.n = n
        self.agent_id = np.arange(n, dtype=int)   # posição original na população
        self.x = np.zeros(n)
        self.y = np.zeros(n)
        self.heading = np.zeros(n)
        self.vx = np.zeros(n)
        self.vy = np.zeros(n)
        self.r = np.zeros(n)
        self.steer = np.zeros(n)
        self.steer_cmd = np.zeros(n)
        self.throttle = np.zeros(n)
        self.brake = np.zeros(n)
        self.reverse_cmd = np.ones(n)          # freio com carro parado = ré
        self.alive = np.ones(n, dtype=bool)
        self.frozen = np.zeros(n, dtype=bool)
        self.finished = np.zeros(n, dtype=bool)
        self.idx = np.zeros(n, dtype=int)
        self.s_prev = np.zeros(n)
        self.s_total = np.zeros(n)
        self.max_s = np.zeros(n)
        self.laps = np.zeros(n, dtype=int)
        self.lap_count = np.zeros(n, dtype=int)
        self.lap_start = np.zeros(n)
        self.last_lap = np.zeros(n)
        self.best_lap = np.full(n, np.inf)
        self.time = np.zeros(n)
        self.offtrack_time = np.zeros(n)
        self.crashes = np.zeros(n, dtype=int)
        self.crash_cd = np.zeros(n)
        self.stall_time = np.zeros(n)
        self.wrong_way_time = np.zeros(n)
        self.death_reason = np.array([""] * n, dtype=object)
        self.fitness = np.zeros(n)
        self.surface_grip = np.ones(n)
        self.surface_roll = np.ones(n)
        self.lateral = np.zeros(n)
        # saídas da física
        self.slip_f = np.zeros(n)
        self.slip_r = np.zeros(n)
        self.grip_use = np.zeros(n)
        self.ax = np.zeros(n)
        self.ay = np.zeros(n)
        self.speed = np.zeros(n)
        # última ação aplicada (vai na observação)
        self.last_steer = np.zeros(n)
        self.last_drive = np.zeros(n)

    def permute(self, perm: np.ndarray):
        """Reordena todas as linhas (usado para compactar os vivos no início)."""
        for name, arr in list(self.__dict__.items()):
            if isinstance(arr, np.ndarray) and arr.shape and arr.shape[0] == self.n:
                self.__dict__[name] = arr[perm]


class Simulation:
    """Avança a frota inteira em passos fixos e calcula fitness."""

    def __init__(self, track: Track, spec: CarSpec, config: SimConfig | None = None,
                 n_agents: int = 1, seed: int = 0, specs: list | None = None):
        self.track = track
        # `specs` permite um carro por linha (corrida com carros diferentes);
        # sem ele, a frota inteira usa o mesmo carro (treino/padrão).
        self.specs: list = [spec] * max(1, int(n_agents)) if not specs else list(specs)
        if len(self.specs) < n_agents:
            self.specs = (self.specs * (n_agents // max(1, len(self.specs)) + 1))[:n_agents]
        self.specs = self.specs[:max(1, int(n_agents))]
        self.batch = CarBatch(self.specs)
        self.cfg = config or SimConfig()
        self.rng = np.random.default_rng(seed)
        self.fleet = Fleet(n_agents)
        self.step_count = 0
        self.obs_dim = self.cfg.n_rays + OBS_EXTRA
        self.max_steps = int(self.cfg.max_seconds / self.cfg.dt)
        self.pending_actions = np.zeros((n_agents, 2), dtype=np.float32)
        self.n_active = n_agents
        self._compact_interval = 30
        self.reset()
        self._history = []

    # ------------------------------------------------------------------ #
    @property
    def spec(self) -> CarSpec:
        """Carro da primeira linha (compatibilidade: HUD, sensores)."""
        return self.specs[0]

    def set_car(self, spec: CarSpec):
        """Troca o carro de toda a frota (modo treino: todos iguais)."""
        self.set_specs([spec] * self.fleet.n)

    def set_specs(self, specs: list):
        """Define um carro por linha da frota."""
        n = self.fleet.n
        self.specs = list(specs)[:n]
        if len(self.specs) < n:
            self.specs = (self.specs * (n // max(1, len(self.specs)) + 1))[:n]
        self.batch = CarBatch(self.specs)

    @property
    def n(self) -> int:
        return self.fleet.n

    def should_decide(self) -> bool:
        return (self.step_count % max(1, self.cfg.decision_interval)) == 0

    def active_indices(self) -> np.ndarray:
        a = self.fleet.alive[:self.n_active] & ~self.fleet.frozen[:self.n_active]
        return np.flatnonzero(a)

    def _maybe_compact(self):
        """Manda os agentes mortos para o fim: menos contas por passo."""
        n = self.n_active
        if n <= 1:
            return
        alive = self.fleet.alive[:n]
        if alive.all():
            return
        if alive.mean() > 0.75:
            return
        idx = np.flatnonzero(alive)
        if len(idx) == 0:
            self.n_active = 0
            return
        perm = np.concatenate([idx, np.setdiff1d(np.arange(self.fleet.n), idx, assume_unique=False)])
        self.fleet.permute(perm)
        self.batch.permute(perm)          # cada linha leva o seu carro junto
        self.n_active = len(idx)

    def reset(self, n_agents: int | None = None, rotation: int = 0):
        if n_agents is not None and n_agents != self.fleet.n:
            self.fleet = Fleet(n_agents)
            self.pending_actions = np.zeros((n_agents, 2), dtype=np.float32)
            self.set_specs(self.specs) if self.specs else None
        f = self.fleet
        trk = self.track
        n = f.n
        f.__init__(n)
        self.step_count = 0
        self.n_active = n

        per_row = max(1, int((trk.half_widths[trk.start_index] * 2 - 3.0) // 3.2))
        rows = self.cfg.spawn_rows or math.ceil(n / per_row)
        for k in range(n):
            # a posição no grid gira a cada geração: nenhum indivíduo fica
            # sempre com o mesmo lugar (bom ou ruim) na largada
            slot = (k + rotation) % n
            row = slot // per_row
            col = slot % per_row
            back = int(round((6.0 + row * 9.0) / trk.spacing))
            i = (trk.start_index - back) % trk.n
            half = trk.half_widths[i]
            lat = np.linspace(-(half - 1.6), (half - 1.6), per_row)[col] if per_row > 1 else 0.0
            f.x[k], f.y[k] = trk.center[i] + trk.normals[i] * lat
            f.heading[k] = trk.heading[i]
            f.idx[k] = i
            f.s_prev[k] = 0.0
        self._sync_track_state()

    def _sync_track_state(self, n: int | None = None):
        """Recalcula índice, deslocamento lateral e superfície dos agentes ativos."""
        f = self.fleet
        trk = self.track
        sl = slice(0, n) if n is not None else slice(None)
        pos = np.stack([f.x[sl], f.y[sl]], axis=1)
        idx, lateral = trk.nearest(pos, hint=f.idx[sl], window=48, guard=25.0)
        f.idx[sl] = idx
        f.lateral[sl] = lateral
        half = trk.half_widths[idx]
        on_track = np.abs(lateral) <= half
        grass = ~on_track
        f.surface_grip[sl] = np.where(on_track, trk.grip[idx], trk.grip[idx] * self.cfg.grass_grip)
        f.surface_roll[sl] = np.where(grass, self.cfg.grass_roll, 1.0)

    # ------------------------------------------------------------------ #
    def build_observation(self, indices: np.ndarray) -> np.ndarray:
        """Monta o vetor de observação (B, obs_dim) para os agentes vivos."""
        f = self.fleet
        trk = self.track
        cfg = self.cfg
        pos = np.stack([f.x[indices], f.y[indices]], axis=1)
        heading = f.heading[indices]
        idx = f.idx[indices]

        rays = trk.cast_rays(pos, heading, idx, n_rays=cfg.n_rays,
                             max_range=cfg.ray_range, fov=math.radians(cfg.fov_deg))
        rays_n = np.clip(rays / cfg.ray_range, 0.0, 1.0)

        max_speed = np.maximum(self.batch.max_speed[indices], 1e-6)
        steer_norm = np.maximum(self.batch.max_steer[indices], 1e-6)
        half = np.maximum(trk.half_widths[idx], 1e-6)
        heading_err = ((heading - trk.heading[idx] + np.pi) % (2 * np.pi) - np.pi) / np.pi

        la_d, la_k = trk.lookahead(idx, np.array([15.0, 30.0, 50.0, 80.0]))
        la_n = np.clip(la_d / 1.2, -1.0, 1.0)
        curv_n = np.clip(la_k * 40.0, -1.0, 1.0)

        cols = [
            rays_n,
            (f.speed[indices] / max_speed)[:, None],
            (f.vx[indices] / max_speed)[:, None],
            (f.vy[indices] / 12.0)[:, None],
            (f.r[indices] / 3.0)[:, None],
            (f.steer[indices] / steer_norm)[:, None],
            np.clip(f.lateral[indices] / half, -1.5, 1.5)[:, None] / 1.5,
            heading_err[:, None],
            la_n,
            np.clip(f.surface_grip[indices], 0.0, 2.0)[:, None],
            np.clip(f.grip_use[indices], 0.0, 1.5)[:, None],
            f.last_steer[indices][:, None],
            f.last_drive[indices][:, None],
        ]
        obs = np.concatenate([np.atleast_2d(c) for c in cols], axis=1).astype(np.float32)
        return obs

    def observe(self) -> tuple[np.ndarray, np.ndarray]:
        """Retorna (observações, linhas ativas).

        As linhas podem ter sido compactadas — use `agent_ids(rows)` para
        saber qual indivíduo da população está em cada linha.
        """
        idx = self.active_indices()
        if len(idx) == 0:
            return np.zeros((0, self.obs_dim), dtype=np.float32), idx
        return self.build_observation(idx), idx

    def agent_ids(self, rows: np.ndarray) -> np.ndarray:
        """Índices na população correspondentes a estas linhas da frota."""
        return self.fleet.agent_id[rows]

    def fitness_by_agent(self) -> np.ndarray:
        """Fitness reordenado na ordem da população (desfaz a compactação)."""
        out = np.zeros(self.fleet.n, dtype=np.float64)
        out[self.fleet.agent_id] = self.fleet.fitness
        return out

    def set_actions(self, actions: np.ndarray, indices: np.ndarray):
        """actions: (B,2) com [steer, drive] em [-1,1]."""
        if len(indices) == 0:
            return
        a = np.clip(np.asarray(actions, dtype=np.float64), -1.0, 1.0)
        f = self.fleet
        f.steer_cmd[indices] = a[:, 0]
        drive = a[:, 1]
        f.throttle[indices] = np.clip(drive, 0.0, 1.0)
        f.brake[indices] = np.clip(-drive, 0.0, 1.0)
        f.last_steer[indices] = a[:, 0]
        f.last_drive[indices] = drive

    # ------------------------------------------------------------------ #
    def step(self):
        f = self.fleet
        cfg = self.cfg
        dt = cfg.dt
        n = self.n_active

        physics_step(self.batch, f, f.surface_grip, f.surface_roll, dt, n)
        self._sync_track_state(n)
        self._handle_walls(n)

        alive = f.alive
        dt_alive = dt * alive
        f.time += dt_alive

        # progressão ao longo do arco (com tratamento da volta)
        s = np.zeros(f.n)
        rel = np.stack([f.x - self.track.center[f.idx, 0], f.y - self.track.center[f.idx, 1]], axis=1)
        tang = self.track.tangents[f.idx]
        along = rel[:, 0] * tang[:, 0] + rel[:, 1] * tang[:, 1]
        s = self.track.arc[f.idx] + np.clip(along, -self.track.spacing, self.track.spacing)
        ds = s - f.s_prev
        half_len = self.track.length * 0.5
        ds = np.where(ds > half_len, ds - self.track.length, ds)
        ds = np.where(ds < -half_len, ds + self.track.length, ds)
        # nenhum carro anda mais do que alguns metros por passo: corta saltos.
        # o fator 3x é de propósito: na linha de dentro de uma curva fechada o
        # progresso na linha de centro avança mais rápido que o carro (legítimo)
        max_ds = np.maximum(f.speed * dt * 3.0 + 1.0, 2.0)
        ds = np.clip(ds, -max_ds, max_ds)
        ds = np.where(alive, ds, 0.0)
        f.s_total += ds
        f.s_prev = s
        f.max_s = np.maximum(f.max_s, f.s_total)
        f.laps = np.floor(f.s_total / max(self.track.length, 1e-6)).astype(int)
        done = alive & (f.laps > f.lap_count)
        if done.any():
            rows = np.flatnonzero(done)
            lt = f.time[rows] - f.lap_start[rows]
            f.last_lap[rows] = lt
            better = lt < f.best_lap[rows]
            if better.any():
                f.best_lap[rows[better]] = lt[better]
            f.lap_count[rows] = f.laps[rows]
            f.lap_start[rows] = f.time[rows]
        f.offtrack_time += dt * (alive & (np.abs(f.lateral) > self.track.half_widths[f.idx]))
        f.crash_cd = np.maximum(f.crash_cd - dt, 0.0)

        # sentido da pista: produto interno entre a direção do carro e a tangente
        tang = self.track.tangents[f.idx]
        hx = np.cos(f.heading)
        hy = np.sin(f.heading)
        aligned = hx * tang[:, 0] + hy * tang[:, 1]
        wrong = (aligned < -0.15) & (f.speed > 2.0) & alive
        f.wrong_way_time = np.where(wrong, f.wrong_way_time + dt, 0.0)

        # término por parada prolongada, marcha a ré ou conclusão
        slow = (f.speed < 1.2) & alive
        f.stall_time = np.where(slow, f.stall_time + dt, 0.0)
        stalled = f.stall_time > cfg.stall_seconds
        backwards = f.s_total < (f.max_s - 30.0)
        wrong_way = f.wrong_way_time > cfg.wrong_way_seconds
        timed_out = f.time >= cfg.max_seconds
        finished_laps = (cfg.target_laps > 0) & (f.laps >= cfg.target_laps)
        too_many_crashes = f.crashes >= cfg.max_crashes
        dead = alive & (stalled | backwards | wrong_way | timed_out | finished_laps
                        | too_many_crashes)
        f.finished |= finished_laps
        for mask, reason in ((stalled, "parado"), (backwards, "voltou"),
                             (wrong_way, "contra-mão"), (timed_out, "tempo"),
                             (finished_laps, "concluiu"), (too_many_crashes, "batidas")):
            hit = dead & mask & (f.death_reason == "")
            if hit.any():
                f.death_reason[hit] = reason
        f.alive = alive & ~dead

        self.step_count += 1
        if self.step_count % self._compact_interval == 0:
            self._maybe_compact()
        self._update_fitness()

    def _handle_walls(self, n: int | None = None):
        f = self.fleet
        trk = self.track
        cfg = self.cfg
        sl = slice(0, n) if n is not None else slice(None)
        lat = f.lateral[sl]
        idx_all = f.idx[sl]
        half = trk.half_widths[idx_all]                 # (A,)
        over = (np.abs(lat) > half + cfg.runoff) & f.alive[sl]
        if not over.any():
            return
        rows = np.flatnonzero(over)
        sign = np.sign(lat[over])
        idx = idx_all[over]
        limit = (half + cfg.runoff)[over]
        # reposiciona na parede
        pos = trk.center[idx] + trk.normals[idx] * (sign * limit)[:, None]
        f.x[rows] = pos[:, 0]
        f.y[rows] = pos[:, 1]

        tang = trk.tangents[idx]
        nrm = trk.normals[idx]
        # velocidade em referencial da pista -> reflete a componente normal
        wvx = f.vx[rows] * np.cos(f.heading[rows]) - f.vy[rows] * np.sin(f.heading[rows])
        wvy = f.vx[rows] * np.sin(f.heading[rows]) + f.vy[rows] * np.cos(f.heading[rows])
        v_t = wvx * tang[:, 0] + wvy * tang[:, 1]
        v_n = wvx * nrm[:, 0] + wvy * nrm[:, 1]
        speed = np.sqrt(v_t * v_t + v_n * v_n) + 1e-6
        v_n_out = np.where(np.sign(v_n) == sign, v_n, 0.0)     # só componente "para fora"
        v_n2 = v_n - 1.25 * v_n_out                            # restituição 0.25
        # raspão (quase paralelo) quase não tira velocidade; batida frontal, muito
        impact = np.clip(np.abs(v_n_out) / speed, 0.0, 1.0)
        v_t2 = v_t * (1.0 - 0.45 * impact)
        wvx2 = tang[:, 0] * v_t2 + nrm[:, 0] * v_n2
        wvy2 = tang[:, 1] * v_t2 + nrm[:, 1] * v_n2
        cos_h = np.cos(f.heading[rows])
        sin_h = np.sin(f.heading[rows])
        f.vx[rows] = wvx2 * cos_h + wvy2 * sin_h
        f.vy[rows] = -wvx2 * sin_h + wvy2 * cos_h
        f.r[rows] *= 0.55
        counted = f.crash_cd[rows] <= 0.0
        f.crashes[rows] += counted.astype(int)
        f.crash_cd[rows] = np.where(counted, 0.4, f.crash_cd[rows])

    def _update_fitness(self):
        f = self.fleet
        cfg = self.cfg
        fit = (f.max_s
               - cfg.time_penalty * f.time
               - cfg.offtrack_penalty * f.offtrack_time
               - cfg.crash_penalty * f.crashes)
        bonus = np.where(f.finished,
                         cfg.finish_bonus_per_second * np.maximum(cfg.max_seconds - f.time, 0.0), 0.0)
        f.fitness = fit + bonus

    # ------------------------------------------------------------------ #
    def all_dead(self) -> bool:
        return self.n_active == 0 or not bool(self.fleet.alive[:self.n_active].any())

    def stats(self) -> dict:
        f = self.fleet
        alive = int(f.alive.sum())
        return {
            "step": self.step_count,
            "time": self.step_count * self.cfg.dt,
            "alive": alive,
            "best": float(f.fitness.max()) if f.n else 0.0,
            "mean": float(f.fitness.mean()) if f.n else 0.0,
            "best_lap": float(np.floor(f.max_s.max() / max(self.track.length, 1e-6))),
            "distance": float(f.max_s.max()),
            "crashes": float(f.crashes.mean()),
            "avg_speed": float(f.speed[f.alive].mean()) if alive else 0.0,
        }

    def best_index(self) -> int:
        return int(np.argmax(self.fleet.fitness))
