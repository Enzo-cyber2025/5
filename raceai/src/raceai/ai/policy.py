"""Política (rede neural) e representação de genoma para evolução.

Topologia padrão: MLP  obs -> [64, 64] -> 2  com tanh.
Saída: [esterço, acelerador] em [-1, 1] (acelerador negativo = freio).

O genoma é a lista de matrizes/vetores de pesos; para a evolução ele é
achatado num vetor float32, e mutação/crossover operam nesse vetor.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np


@dataclass
class PolicySpec:
    obs_dim: int = 24
    hidden: tuple = (64, 64)
    act_dim: int = 2
    activation: str = "tanh"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["hidden"] = list(self.hidden)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PolicySpec":
        if not d:
            return cls()
        hidden = d.get("hidden", (64, 64))
        return cls(obs_dim=int(d.get("obs_dim", 24)),
                   hidden=tuple(int(h) for h in hidden),
                   act_dim=int(d.get("act_dim", 2)),
                   activation=str(d.get("activation", "tanh")))

    @property
    def shapes(self) -> list[tuple[int, ...]]:
        dims = [self.obs_dim, *self.hidden, self.act_dim]
        out = []
        for i in range(len(dims) - 1):
            out.append((dims[i + 1], dims[i]))   # peso (out, in)
            out.append((dims[i + 1],))           # bias
        return out

    @property
    def n_params(self) -> int:
        return int(sum(int(np.prod(s)) for s in self.shapes))


def init_genome(spec: PolicySpec, rng: np.random.Generator,
                scale: float = 0.9) -> list[np.ndarray]:
    """Inicialização Xavier/uniforme — saída pequena para não sair derrapando."""
    genome = []
    dims = [spec.obs_dim, *spec.hidden, spec.act_dim]
    for i in range(len(dims) - 1):
        fan_in, fan_out = dims[i], dims[i + 1]
        lim = scale * np.sqrt(6.0 / (fan_in + fan_out))
        W = rng.uniform(-lim, lim, size=(fan_out, fan_in)).astype(np.float32)
        b = np.zeros(fan_out, dtype=np.float32)
        genome.append(W)
        genome.append(b)
    return genome


def flatten(genome: list[np.ndarray]) -> np.ndarray:
    return np.concatenate([np.asarray(g, dtype=np.float32).ravel() for g in genome])


def unflatten(spec: PolicySpec, vec: np.ndarray) -> list[np.ndarray]:
    vec = np.asarray(vec, dtype=np.float32)
    out = []
    pos = 0
    for shape in spec.shapes:
        size = int(np.prod(shape))
        out.append(vec[pos:pos + size].reshape(shape).copy())
        pos += size
    if pos != len(vec):
        raise ValueError(f"genoma com {len(vec)} valores, esperado {pos}")
    return out


def genome_to_layers(spec: PolicySpec, genome: list[np.ndarray]) -> list[tuple[np.ndarray, np.ndarray]]:
    return [(genome[i], genome[i + 1]) for i in range(0, len(genome), 2)]


def forward_single(spec: PolicySpec, genome: list[np.ndarray], obs: np.ndarray) -> np.ndarray:
    """Inferência de um indivíduo (usada em testes e no modo 'dirigir com modelo')."""
    x = np.asarray(obs, dtype=np.float32)
    layers = genome_to_layers(spec, genome)
    for i, (W, b) in enumerate(layers):
        x = x @ W.T + b
        if i < len(layers) - 1 or True:
            x = np.tanh(x)
    return x
