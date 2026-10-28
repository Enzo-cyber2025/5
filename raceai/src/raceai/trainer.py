"""Treinador: junta simulação + população + backend de inferência.

Usado tanto pelo jogo (que chama `step()` a cada frame e desenha) quanto
pelo treinador de linha de comando (`train_headless.py`), garantindo que os
dois evoluam exatamente com a mesma física.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import numpy as np

from .ai.backend import NumpyBackend, TorchBackend, create_backend, resolve_device
from .ai.ga import GAConfig, Population
from .ai.model_io import ModelError, describe, load_model, save_model
from .ai.policy import PolicySpec
from .car import CarSpec
from .sim import SimConfig, Simulation
from .track import Track


@dataclass
class TrainerState:
    generation: int = 0
    steps: int = 0
    sim_seconds: float = 0.0
    inference_ms: float = 0.0
    steps_per_second: float = 0.0
    device: str = "cpu"
    device_desc: str = ""
    last_stats: dict = field(default_factory=dict)


class Trainer:
    """Avalia uma geração por vez e faz a evolução genética."""

    def __init__(self, track: Track, car: CarSpec, sim_cfg: SimConfig | None = None,
                 ga_cfg: GAConfig | None = None, policy: PolicySpec | None = None,
                 device_id: str = "auto", seed: int = 0):
        self.track = track
        self.car = car
        self.sim_cfg = sim_cfg or SimConfig()
        self.ga_cfg = ga_cfg or GAConfig()
        self.seed = seed
        self.policy = policy or PolicySpec(obs_dim=24)
        self.device_id, dev_desc = resolve_device(device_id)
        self.sim = Simulation(track, car, self.sim_cfg, self.ga_cfg.population, seed=seed)
        # a dimensão de observação depende do número de raios configurado
        self.policy = PolicySpec(obs_dim=self.sim.obs_dim, hidden=self.policy.hidden,
                                 act_dim=self.policy.act_dim)
        self.pop = Population(self.policy, self.ga_cfg, seed=seed)
        self.backend = create_backend(self.policy, self.ga_cfg.population, self.device_id)
        self.backend.set_population(self.pop.as_layers())
        self.backend.warmup(self.policy.obs_dim)
        self.state = TrainerState(device=self.device_id,
                                  device_desc=getattr(self.backend, "device_desc", ""))
        self.manual_control = False
        self.manual_action = np.zeros(2, dtype=np.float32)
        self.autopilot = None                  # piloto clássico (opcional)
        self.use_autopilot_when_idle = False
        self.excluded = np.zeros(self.ga_cfg.population, dtype=bool)
        self._t0 = time.perf_counter()
        self._steps_mark = 0
        self.generations_enabled = True
        self.last_gen_stats: dict = {}

    # ------------------------------------------------------------------ #
    # Configuração dinâmica (chamada pela UI)
    # ------------------------------------------------------------------ #
    def set_track(self, track: Track):
        self.track = track
        self.sim.track = track
        self.restart()

    def set_car(self, car: CarSpec):
        self.car = car
        self.sim.spec = car
        if self.autopilot is not None:
            self.autopilot.update(car=car)
        self.sim.reset()

    def enable_autopilot(self, enabled: bool = True, **kwargs):
        """Liga o piloto clássico (usado quando não há modelo carregado)."""
        from .autopilot import Autopilot
        if enabled:
            if self.autopilot is None:
                self.autopilot = Autopilot(self.track, self.car, **kwargs)
            else:
                self.autopilot.update(track=self.track, car=self.car)
        self.use_autopilot_when_idle = bool(enabled)

    def set_population_size(self, n: int):
        n = max(2, int(n))
        if n == self.ga_cfg.population and self.sim.n == n:
            return
        self.ga_cfg.population = n
        self.pop.resize(n)
        self.sim.reset(n_agents=n)
        self.backend = create_backend(self.policy, n, self.device_id)
        self.backend.set_population(self.pop.as_layers())
        self.excluded = np.zeros(n, dtype=bool)
        self.state.generation = self.pop.generation

    def set_device(self, device_id: str):
        device_id, _ = resolve_device(device_id)
        if device_id == self.device_id:
            return
        self.device_id = device_id
        self.backend = create_backend(self.policy, self.ga_cfg.population, device_id)
        self.backend.set_population(self.pop.as_layers())
        self.backend.warmup(self.policy.obs_dim)
        self.state.device = device_id
        self.state.device_desc = getattr(self.backend, "device_desc", "")

    def set_ga_params(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self.ga_cfg, k):
                setattr(self.ga_cfg, k, v)

    def set_sim_params(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self.sim_cfg, k):
                setattr(self.sim_cfg, k, v)
        self.sim.max_steps = int(self.sim_cfg.max_seconds / self.sim_cfg.dt)

    def restart(self, fresh: bool = False):
        if fresh:
            self.pop.random_population()
        self.sim.reset()
        self.backend.set_population(self.pop.as_layers())
        self.state.steps = 0
        self.state.sim_seconds = 0.0

    def reset_training(self):
        self.pop = Population(self.policy, self.ga_cfg, seed=self.seed)
        self.backend.set_population(self.pop.as_layers())
        self.restart()
        self.state.generation = 0
        self.last_gen_stats = {}

    # ------------------------------------------------------------------ #
    # Modelos
    # ------------------------------------------------------------------ #
    def load_model(self, path: str, seed_population: bool = True) -> dict:
        spec, genome, meta = load_model(path)
        if spec.obs_dim != self.policy.obs_dim:
            raise ModelError(
                f"modelo esperava {spec.obs_dim} sensores, a configuração atual usa "
                f"{self.policy.obs_dim} (número de raios/observações diferente)")
        flat = np.concatenate([np.asarray(g, dtype=np.float32).ravel() for g in genome])
        if seed_population:
            self.pop.seed_from(flat)
            self.backend.set_population(self.pop.as_layers())
            self.sim.reset()
        else:
            self.pop.genomes[0] = flat
            self.backend.set_population(self.pop.as_layers())
            self.sim.reset()
        self.loaded_meta = meta
        self.loaded_genome = flat
        return meta

    def best_model_path_info(self) -> tuple[np.ndarray, dict]:
        genome = self.pop.best_genome
        if genome is None:
            genome = self.pop.genomes[0]
        meta = {
            "track": self.track.name,
            "car": self.car.name,
            "generation": self.pop.generation,
            "fitness": float(self.pop.best_fitness),
            "device": self.state.device_desc or self.state.device,
            "obs_dim": self.policy.obs_dim,
            "population": self.ga_cfg.population,
        }
        return genome, meta

    def save_best(self, path: str) -> str:
        """Salva o melhor indivíduo. Retorna o caminho realmente usado."""
        from .ai.policy import unflatten
        genome, meta = self.best_model_path_info()
        return save_model(path, self.policy, unflatten(self.policy, genome), meta)

    # ------------------------------------------------------------------ #
    # Loop
    # ------------------------------------------------------------------ #
    def step(self, n_steps: int = 1):
        sim = self.sim
        for _ in range(n_steps):
            if sim.should_decide():
                obs, rows = sim.observe()
                if len(rows):
                    ids = sim.agent_ids(rows)          # quem é quem na população
                    if self.use_autopilot_when_idle and self.autopilot is not None:
                        actions = self.autopilot.actions(sim, rows)
                    else:
                        actions = self.backend.predict(obs, ids)
                    if self.manual_control:
                        mine = np.flatnonzero(ids == self.manual_agent)
                        if len(mine):
                            actions[mine[0]] = self.manual_action
                    sim.set_actions(actions, rows)
            sim.step()
        self.state.steps = sim.step_count
        self.state.sim_seconds = sim.step_count * sim.cfg.dt
        self.state.inference_ms = getattr(self.backend, "last_ms", 0.0)
        now = time.perf_counter()
        elapsed = now - self._t0
        if elapsed >= 1.0:
            self.state.steps_per_second = (sim.step_count - self._steps_mark) / elapsed
            self._t0 = now
            self._steps_mark = sim.step_count

    @property
    def manual_agent(self) -> int:
        return 0

    def generation_done(self) -> bool:
        return self.sim.all_dead() or self.sim.step_count >= self.sim.max_steps

    def finish_generation(self, evolve: bool | None = None) -> dict:
        """Fecha a geração, registra fitness e (opcionalmente) evolui."""
        sim = self.sim
        fit = sim.fitness_by_agent()          # volta para a ordem da população
        if self.manual_control and self.excluded.sum() < len(fit):
            # o carro pilotado por humano não entra na seleção
            fit[self.excluded] = fit[~self.excluded].min() if (~self.excluded).any() else fit.min()
        self.pop.record(fit)
        stats = dict(self.pop.stats())
        stats.update(sim.stats())
        stats["death_reasons"] = _reason_counts(sim.fleet.death_reason)
        self.last_gen_stats = stats
        self.state.generation = self.pop.generation
        do_evolve = self.generations_enabled if evolve is None else evolve
        if do_evolve:
            self.pop.evolve()
            self.backend.set_population(self.pop.as_layers())
            self.state.generation = self.pop.generation
        self.sim.reset()
        self.state.steps = 0
        return stats

    def run_generation(self, callback=None, steps_per_call: int = 240) -> dict:
        """Roda uma geração inteira (modo headless/linha de comando)."""
        while not self.generation_done():
            self.step(steps_per_call)
            if callback:
                callback(self)
        return self.finish_generation()

    def run(self, generations: int, callback=None, log=None, save_every: int = 0,
            out_path: str | None = None) -> dict:
        t0 = time.perf_counter()
        for g in range(generations):
            stats = self.run_generation(callback)
            if log is not None:
                log.append(stats)
            if save_every and out_path and (self.pop.generation % save_every == 0):
                self.save_best(out_path)
        if out_path:
            self.save_best(out_path)
        return {"seconds": time.perf_counter() - t0, "generations": self.pop.generation}


def _reason_counts(reasons) -> dict:
    out = {}
    for r in reasons:
        if r:
            out[r] = out.get(r, 0) + 1
    return out
