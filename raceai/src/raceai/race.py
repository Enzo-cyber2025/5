"""Modo **corrida**: vários carros (e vários modelos) correndo ao mesmo tempo.

Cada competidor do grid tem o seu carro e o seu piloto:

  * ``humano``  — você, no teclado (só um por corrida);
  * ``auto``    — piloto automático clássico (perseguição pura);
  * ``modelo``  — uma rede `.pt`/`.npz` carregada (cada um com os seus pesos).

Todos dividem a mesma simulação (`Simulation` com um carro por linha), então
há grid, disputa de posição, volta mais rápida e classificação final.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import numpy as np

from .ai.backend import create_backend
from .ai.model_io import ModelError, load_model
from .ai.policy import PolicySpec, unflatten
from .autopilot import Autopilot
from .car import CarSpec
from .sim import SimConfig, Simulation

HUMANO = "humano"
AUTO = "auto"
MODELO = "modelo"

KIND_LABEL = {HUMANO: "Você", AUTO: "Piloto automático", MODELO: "Modelo"}

# limites usados só na corrida: aqui ninguém é eliminado por ficar parado
RACE_CFG = dict(stall_seconds=90.0, max_crashes=100_000, wrong_way_seconds=1.0e9)


@dataclass
class Competitor:
    """Um carro no grid."""

    name: str
    car: CarSpec
    kind: str = AUTO
    model_path: str = ""
    genome: np.ndarray | None = None
    meta: dict = field(default_factory=dict)

    @property
    def driver(self) -> str:
        if self.kind == MODELO:
            return os.path.splitext(os.path.basename(self.model_path))[0] or "modelo"
        return KIND_LABEL.get(self.kind, self.kind)

    def car_name(self) -> str:
        return getattr(self.car, "name", "carro")

    def describe(self) -> str:
        return f"{self.name} · {self.car_name()} · {self.driver}"


class Race:
    """Prepara o grid e corre."""

    def __init__(self, track, policy: PolicySpec | None = None, device: str = "auto",
                 seed: int = 0, sim_cfg: SimConfig | None = None):
        self.track = track
        self.policy = policy or PolicySpec()
        self.device = device
        self.seed = seed
        self.sim_cfg = sim_cfg
        self.entries: list[Competitor] = []
        self.sim: Simulation | None = None
        self.backend = None
        self.autopilots: dict[str, Autopilot] = {}
        self.model_index: dict[int, int] = {}      # competidor -> linha no backend
        self.human_rows: list[int] = []
        self.human_action = np.zeros(2, dtype=np.float32)

        self.state = "setup"          # setup | countdown | running | finished
        self.countdown = 3.0
        self.laps_target = 3
        self.time_limit = 0.0         # 0 = só conta voltas
        self.elapsed = 0.0
        self.results: list[dict] = []
        self.focus = 0
        self.finished_at: dict[int, float] = {}
        self.leader_finished_at: float | None = None
        self.finish_grace = 20.0       # espera dos retardatários após o líder
        self._t0 = 0.0

    # ------------------------------------------------------------------ #
    # Grid
    # ------------------------------------------------------------------ #
    def add(self, competitor: Competitor):
        self.entries.append(competitor)

    def remove(self, index: int):
        if 0 <= index < len(self.entries):
            self.entries.pop(index)

    def clear(self):
        self.entries = []

    def add_human(self, car: CarSpec, name: str = "Você"):
        if any(e.kind == HUMANO for e in self.entries):
            return False
        self.add(Competitor(name=name, car=car, kind=HUMANO))
        return True

    def add_autopilot(self, car: CarSpec, name: str | None = None):
        n = sum(1 for e in self.entries if e.kind == AUTO) + 1
        self.add(Competitor(name=name or f"Piloto {n}", car=car, kind=AUTO))

    def add_model(self, car: CarSpec, path: str, name: str | None = None) -> bool:
        """Carrega um .pt/.npz e coloca esse piloto no grid."""
        try:
            spec, genome, meta = load_model(path)
        except (ModelError, FileNotFoundError, OSError):
            return False
        flat = np.concatenate([np.asarray(w, dtype=np.float32).ravel() for w in genome]) \
            if isinstance(genome, list) else np.asarray(genome, dtype=np.float32)
        nome = name or os.path.splitext(os.path.basename(path))[0]
        self.add(Competitor(name=nome, car=car, kind=MODELO, model_path=path,
                            genome=flat, meta=meta))
        return True

    def default_grid(self, cars: list[CarSpec], models: list[str] | None = None):
        """Grid pronto para usar: você + pilotos automáticos + modelos."""
        self.clear()
        if not cars:
            return
        self.add_human(cars[0])
        for path in (models or [])[:6]:
            car = cars[min(1, len(cars) - 1)]
            self.add_model(car, path)
        n_auto = max(1, min(3, len(cars)))
        for k in range(n_auto):
            self.add_autopilot(cars[min(k + 1, len(cars) - 1)])

    # ------------------------------------------------------------------ #
    # Corrida
    # ------------------------------------------------------------------ #
    def build(self, laps: int | None = None, time_limit: float = 0.0) -> bool:
        """Monta a simulação com um carro por linha. False se o grid estiver vazio."""
        if not self.entries:
            return False
        if laps is not None:
            self.laps_target = max(1, int(laps))
        self.time_limit = float(time_limit or 0.0)

        specs = [e.car for e in self.entries]
        base = self.sim_cfg or SimConfig()
        cfg = SimConfig(**{**base.__dict__, **RACE_CFG})
        cfg.max_seconds = 1.0e6                   # a corrida termina por volta/tempo
        self.sim = Simulation(self.track, specs[0], cfg, len(specs), seed=self.seed,
                              specs=specs)
        self.sim.reset()

        # pilotos automáticos: um por carro (o autopilot usa os limites do carro)
        self.autopilots = {}
        for entry in self.entries:
            if entry.kind == AUTO:
                self.autopilots.setdefault(entry.car.id,
                                           Autopilot(self.track, entry.car))

        # modelos: um "banco" de redes, uma por competidor
        self.model_index = {}
        layers = []
        for i, entry in enumerate(self.entries):
            if entry.kind == MODELO and entry.genome is not None:
                self.model_index[i] = len(layers)
                layers.append(unflatten(self.policy, entry.genome))
        self.backend = None
        if layers:
            self.backend = create_backend(self.policy, len(layers), self.device)
            self.backend.set_population(layers)

        self.human_rows = [i for i, e in enumerate(self.entries) if e.kind == HUMANO]
        self.state = "countdown"
        self.countdown = 3.0
        self.elapsed = 0.0
        self.results = []
        self.finished_at = {}
        self.leader_finished_at = None
        self.focus = self.human_rows[0] if self.human_rows else 0
        self._t0 = time.perf_counter()
        self.sim.fleet.frozen[:] = True           # preso no grid até a largada
        return True

    def start(self, laps: int | None = None, time_limit: float = 0.0) -> bool:
        ok = self.build(laps, time_limit)
        return ok

    def restart(self):
        self.build(self.laps_target, self.time_limit)

    # ------------------------------------------------------------------ #
    @property
    def running(self) -> bool:
        return self.state in ("countdown", "running")

    def step(self, n_steps: int = 1):
        sim = self.sim
        if sim is None or self.state == "finished":
            return
        for _ in range(n_steps):
            if self.state == "countdown":
                self.countdown -= sim.cfg.dt
                if self.countdown <= 0.0:
                    self.state = "running"
                    sim.fleet.frozen[:] = False
                continue
            if self.state != "running":
                return
            if sim.should_decide():
                self._decide()
            sim.step()
            self.elapsed += sim.cfg.dt
            self._check_finish()

    def _decide(self):
        sim = self.sim
        rows = sim.active_indices()
        if len(rows) == 0:
            return
        ids = sim.agent_ids(rows)
        actions = np.zeros((len(rows), 2), dtype=np.float32)

        # 1) modelos (todos de uma vez, em batch)
        if self.backend is not None and self.model_index:
            sel = np.array([i for i, ag in enumerate(ids) if ag in self.model_index], dtype=int)
            if len(sel):
                obs = sim.build_observation(rows[sel])
                gidx = np.array([self.model_index[int(ag)] for ag in ids[sel]], dtype=int)
                actions[sel] = self.backend.predict(obs, gidx)

        # 2) piloto automático (agrupado por carro)
        for car_id, pilot in self.autopilots.items():
            sel = np.array([i for i, ag in enumerate(ids)
                            if self.entries[int(ag)].kind == AUTO
                            and self.entries[int(ag)].car.id == car_id], dtype=int)
            if len(sel):
                actions[sel] = pilot.actions(sim, rows[sel])

        # 3) humano
        if self.human_rows:
            sel = np.array([i for i, ag in enumerate(ids) if int(ag) in self.human_rows],
                           dtype=int)
            if len(sel):
                actions[sel] = self.human_action

        sim.set_actions(actions, rows)

    def _check_finish(self):
        """Marca quem completou as voltas e encerra a corrida quando der."""
        sim = self.sim
        f = sim.fleet
        for i in range(len(self.entries)):
            if i in self.finished_at:
                continue
            if not f.alive[i]:
                self.finished_at[i] = -1.0        # -1 = abandonou
            elif f.lap_count[i] >= self.laps_target:
                self.finished_at[i] = self.elapsed
                if self.leader_finished_at is None:
                    self.leader_finished_at = self.elapsed
        if self.time_limit and self.elapsed >= self.time_limit:
            self.finish()
            return
        vivos = [i for i in range(len(self.entries)) if f.alive[i]]
        if not vivos or all(i in self.finished_at for i in vivos):
            self.finish()
            return
        # o líder já ganhou: dá um tempo para os outros cruzarem e encerra
        if self.leader_finished_at is not None and \
                self.elapsed - self.leader_finished_at >= self.finish_grace:
            self.finish()

    def finish(self):
        if self.state == "finished":
            return
        self.state = "finished"
        self.results = self.standings()

    # ------------------------------------------------------------------ #
    # Classificação
    # ------------------------------------------------------------------ #
    def standings(self) -> list[dict]:
        """Ordem de prova: quem completou (por tempo) e depois por progresso."""
        if self.sim is None or not self.entries:
            return []
        f = self.sim.fleet
        rows = []
        for i, entry in enumerate(self.entries):
            finished = self.finished_at.get(i)
            dnf = (finished is not None and finished < 0) or not f.alive[i]
            rows.append({
                "pos": 0,
                "idx": i,
                "nome": entry.name,
                "carro": entry.car_name(),
                "piloto": entry.driver,
                "voltas": int(f.lap_count[i]),
                "progresso": float(f.s_total[i]),
                "melhor_volta": float(f.best_lap[i]) if np.isfinite(f.best_lap[i]) else None,
                "ultima_volta": float(f.last_lap[i]) if f.last_lap[i] > 0 else None,
                "velocidade": float(f.speed[i]),
                "batidas": int(f.crashes[i]),
                "tempo": float(finished) if finished and finished > 0 else None,
                "abandonou": bool(dnf),
                "vivo": bool(f.alive[i]),
                "foi_humano": entry.kind == HUMANO,
            })
        # concluídos primeiro (menor tempo), depois por volta/progresso
        rows.sort(key=lambda r: (
            0 if r["tempo"] is not None else (2 if r["abandonou"] else 1),
            r["tempo"] if r["tempo"] is not None else 1e9,
            -r["voltas"], -r["progresso"]))
        for k, r in enumerate(rows):
            r["pos"] = k + 1
        return rows

    def leader(self) -> dict | None:
        st = self.standings()
        return st[0] if st else None

    def focus_name(self) -> str:
        if not self.entries or self.sim is None:
            return ""
        i = int(self.focus)
        if i >= len(self.entries):
            return ""
        return self.entries[i].name

    def cycle_focus(self, direction: int = 1):
        if not self.entries:
            return
        self.focus = (self.focus + direction) % len(self.entries)

    def set_human_action(self, action):
        self.human_action = np.asarray(action, dtype=np.float32)

    # ------------------------------------------------------------------ #
    def hud_lines(self) -> list[str]:
        """Linhas do painel de corrida (tempo, voltas, líder)."""
        if self.sim is None:
            return ["grid vazio"]
        st = self.standings()
        out = [f"voltas {self.laps_target} · tempo {self.elapsed:6.1f}s"]
        if self.state == "countdown":
            out.append(f"largada em {max(0.0, self.countdown):.1f}s")
        elif self.state == "finished":
            out.append("corrida encerrada")
        for r in st[:4]:
            volta = f"{r['voltas']}/{self.laps_target}"
            if r["tempo"]:
                extra = f"{r['tempo']:.1f}s"
            elif r["abandonou"]:
                extra = "fora"
            else:
                extra = f"{r['velocidade'] * 3.6:3.0f} km/h"
            out.append(f"{r['pos']}º {r['nome'][:12]:<12} {volta:<5} {extra}")
        return out


def load_model_genome(path: str) -> tuple[np.ndarray | None, dict]:
    """Atalho: devolve (genome achatado, meta) de um .pt/.npz."""
    spec, genome, meta = load_model(path)
    flat = np.concatenate([np.asarray(w, dtype=np.float32).ravel() for w in genome]) \
        if isinstance(genome, list) else np.asarray(genome, dtype=np.float32)
    return flat, meta
