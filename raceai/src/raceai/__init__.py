"""RaceAI 2D — jogo de corrida 2D para treinar IA por gerações.

O núcleo (mathutil, track, car, sim, autopilot, trainer, ai) não depende de
pygame: o mesmo código roda no jogo com janela e no treinador headless.
"""
__version__ = "1.0.0"

from . import (  # noqa: F401  (imports preguiçosos: pygame só entra se usado)
    autopilot,
    car,
    mathutil,
    sim,
    track,
    trainer,
)
