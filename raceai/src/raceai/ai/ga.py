"""Algoritmo genético: seleção, cruzamento, mutação e elitismo.

Projeto pensado para neuroevolução de políticas pequenas:
  * elitismo mantém os melhores intactos (passam os pesos adiante);
  * torneio escolhe os pais;
  * cruzamento aritmético/uniforme mistura os pesos;
  * mutação gaussiana por gene, com sigma adaptativo (encolhe com o tempo e
    dispara quando a evolução estagna).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from .policy import PolicySpec, flatten, init_genome, unflatten


@dataclass
class GAConfig:
    population: int = 120
    elitism: float = 0.10           # fração dos melhores preservada sem alteração
    tournament: int = 3
    crossover: str = "blend"        # blend | uniform
    crossover_rate: float = 0.90
    mutation_rate: float = 0.08     # probabilidade por gene
    mutation_sigma: float = 0.25    # desvio padrão do ruído
    sigma_decay: float = 0.995      # multiplicado por geração
    sigma_min: float = 0.03
    fresh_blood: float = 0.04       # fração de indivíduos novos por geração
    stagnation_limit: int = 15      # gerações sem melhora -> aumenta mutação
    reset_mutation_chance: float = 0.01   # genes reiniciados do zero

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GAConfig":
        valid = {k: v for k, v in (d or {}).items() if k in cls().__dict__}
        return cls(**valid)


class Population:
    """População de genomas + histórico da evolução."""

    def __init__(self, spec: PolicySpec, cfg: GAConfig | None = None,
                 rng: np.random.Generator | None = None, seed: int = 0):
        self.spec = spec
        self.cfg = cfg or GAConfig()
        self.rng = rng or np.random.default_rng(seed)
        self.generation = 0
        self.genomes: list[np.ndarray] = []
        self.fitness = np.zeros(0)
        self.history: list[dict] = []
        self.best_fitness = -np.inf
        self.best_genome: np.ndarray | None = None
        self.best_generation = 0
        self.stagnation = 0
        self.sigma = float(self.cfg.mutation_sigma)
        self.random_population()

    # ------------------------------------------------------------------ #
    def random_population(self):
        n = max(2, int(self.cfg.population))
        self.genomes = [flatten(init_genome(self.spec, self.rng)) for _ in range(n)]
        self.fitness = np.zeros(n, dtype=np.float64)
        self.generation = 0
        self.best_fitness = -np.inf
        self.best_genome = None
        self.stagnation = 0
        self.sigma = float(self.cfg.mutation_sigma)
        self.history = []

    def resize(self, n: int):
        n = max(2, int(n))
        self.cfg.population = n
        if self.best_genome is not None and len(self.genomes):
            base = self.best_genome
            self.genomes = [self._mutate(base.copy(), boost=1.0) for _ in range(n)]
            self.genomes[0] = base.copy()
        else:
            self.random_population()
            return
        self.fitness = np.zeros(n, dtype=np.float64)

    def seed_from(self, genome: np.ndarray, keep_elite: bool = True):
        """Reinicia a população a partir de um modelo carregado (ajuste fino)."""
        n = max(2, int(self.cfg.population))
        self.genomes = [self._mutate(np.asarray(genome, dtype=np.float32).copy(), boost=1.0)
                        for _ in range(n)]
        self.genomes[0] = np.asarray(genome, dtype=np.float32).copy()
        self.fitness = np.zeros(n, dtype=np.float64)
        self.generation = 0
        self.best_fitness = -np.inf
        self.best_genome = np.asarray(genome, dtype=np.float32).copy()
        self.sigma = float(self.cfg.mutation_sigma) * 0.6
        self.stagnation = 0
        if not keep_elite:
            self.history = []

    # ------------------------------------------------------------------ #
    def as_layers(self) -> list[list[np.ndarray]]:
        return [unflatten(self.spec, g) for g in self.genomes]

    def best_index(self) -> int:
        return int(np.argmax(self.fitness))

    def record(self, fitness: np.ndarray):
        """Recebe o fitness avaliado da geração atual."""
        fit = np.asarray(fitness, dtype=np.float64)
        self.fitness = fit
        best_i = int(np.argmax(fit))
        if fit[best_i] > self.best_fitness:
            self.best_fitness = float(fit[best_i])
            self.best_genome = self.genomes[best_i].copy()
            self.best_generation = self.generation
            self.stagnation = 0
        else:
            self.stagnation += 1
        self.history.append({
            "generation": self.generation,
            "best": float(fit[best_i]),
            "mean": float(fit.mean()),
            "std": float(fit.std()),
            "worst": float(fit.min()),
            "sigma": float(self.sigma),
            "diversity": float(np.mean([g.std() for g in self.genomes])) if self.genomes else 0.0,
            "best_ever": float(self.best_fitness),
        })

    # ------------------------------------------------------------------ #
    def _tournament(self) -> int:
        k = max(2, int(self.cfg.tournament))
        cand = self.rng.integers(0, len(self.genomes), size=k)
        return int(cand[np.argmax(self.fitness[cand])])

    def _crossover(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        if self.rng.random() > self.cfg.crossover_rate:
            return a.copy()
        if self.cfg.crossover == "uniform":
            mask = self.rng.random(a.shape[0]) < 0.5
            child = a.copy()
            child[mask] = b[mask]
            return child
        # blend: mistura linear por gene
        alpha = self.rng.random(a.shape[0]).astype(np.float32)
        return (a * alpha + b * (1.0 - alpha)).astype(np.float32)

    def _mutate(self, genome: np.ndarray, boost: float = 1.0) -> np.ndarray:
        sigma = self.sigma * boost
        g = genome.copy()
        rate = float(np.clip(self.cfg.mutation_rate, 0.0, 1.0))
        mask = self.rng.random(g.shape[0]) < rate
        if mask.any():
            g[mask] += (self.rng.normal(0.0, sigma, size=int(mask.sum()))
                        .astype(np.float32))
        if self.cfg.reset_mutation_chance > 0:
            rmask = self.rng.random(g.shape[0]) < self.cfg.reset_mutation_chance
            if rmask.any():
                g[rmask] = (self.rng.normal(0.0, 0.5, size=int(rmask.sum()))
                            .astype(np.float32))
        np.clip(g, -8.0, 8.0, out=g)
        return g

    # ------------------------------------------------------------------ #
    def evolve(self) -> list[np.ndarray]:
        """Gera a próxima geração. Devolve a lista de genomas (achatados)."""
        cfg = self.cfg
        n = max(2, int(cfg.population))
        order = np.argsort(-self.fitness)
        n_elite = max(1, int(round(n * float(np.clip(cfg.elitism, 0.0, 0.6)))))
        n_fresh = int(round(n * float(np.clip(cfg.fresh_blood, 0.0, 0.5))))

        new: list[np.ndarray] = []
        # 1) campeão: o melhor de todos os tempos nunca se perde
        if self.best_genome is not None:
            new.append(np.asarray(self.best_genome, dtype=np.float32).copy())
        # 2) elitismo: os melhores da geração passam com os pesos intactos
        for i in order[:n_elite]:
            new.append(self.genomes[int(i)].copy())
        # 2) sangue novo para manter diversidade
        for _ in range(n_fresh):
            new.append(flatten(init_genome(self.spec, self.rng)))
        # 3) reprodução com cruzamento + mutação
        while len(new) < n:
            pa = self.genomes[self._tournament()]
            pb = self.genomes[self._tournament()]
            child = self._crossover(pa, pb)
            new.append(self._mutate(child))
        self.genomes = new[:n]
        self.fitness = np.zeros(len(self.genomes), dtype=np.float64)
        self.generation += 1

        # 4) sigma adaptativo
        if self.stagnation >= max(1, int(cfg.stagnation_limit)):
            self.sigma = min(0.45, self.sigma * 1.5)
            self.stagnation = 0
        else:
            self.sigma = max(cfg.sigma_min, self.sigma * float(cfg.sigma_decay))
        return self.genomes

    # ------------------------------------------------------------------ #
    def stats(self) -> dict:
        if not self.history:
            return {}
        h = self.history[-1]
        return {
            "generation": self.generation,
            "best": h["best"],
            "mean": h["mean"],
            "std": h["std"],
            "worst": h["worst"],
            "diversity": h["diversity"],
            "sigma": self.sigma,
            "best_ever": self.best_fitness,
            "best_generation": self.best_generation,
            "stagnation": self.stagnation,
        }
