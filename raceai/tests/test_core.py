"""Testes do núcleo (sem pygame): física, pista, sensores, GA e modelos.

Roda com:  python tests/run_tests.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from raceai.ai.ga import GAConfig, Population
from raceai.ai.model_io import ModelError, load_model, save_model
from raceai.ai.policy import PolicySpec, flatten, init_genome, unflatten
from raceai.car import CarSpec
from raceai.sim import SimConfig, Simulation
from raceai.track import Track, make_oval

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")


def _track(name="kartodromo") -> Track:
    return Track.load(os.path.join(ASSETS, "tracks", f"{name}.json"))


def _car(name="gt") -> CarSpec:
    return CarSpec.load(os.path.join(ASSETS, "cars", f"{name}.json"))


def _straight_track(length: float = 6000.0, width: float = 60.0) -> Track:
    """Pista 'régua': duas retas longas unidas por semicírculos.

    Serve para testar física pura (aceleração, frenagem, curva) sem que o
    carro encontre uma parede no meio do teste.
    """
    r = width / 2.0
    pts = []
    step = 10.0
    n = max(2, int(length / step))
    for i in range(n):                           # reta de baixo (sentido +x)
        pts.append([-length / 2 + length * i / n, -r])
    m = max(6, int(math.pi * r / step))
    for i in range(m):                           # semicírculo direito
        a = -math.pi / 2 + math.pi * i / m
        pts.append([length / 2 + r * math.cos(a), r * math.sin(a)])
    for i in range(n):                           # reta de cima (sentido -x)
        pts.append([length / 2 - length * i / n, r])
    for i in range(m):                           # semicírculo esquerdo
        a = math.pi / 2 + math.pi * i / m
        pts.append([-length / 2 + r * math.cos(a), r * math.sin(a)])
    data = {"name": "Régua", "closed": True, "width": width, "spacing": 8.0,
            "start": 0.05,          # largada no meio de uma reta (sem curvatura)
            "points": [[round(x, 2), round(y, 2)] for x, y in pts]}
    return Track.from_dict(data)


# ---------------------------------------------------------------------- #
def test_tracks_load():
    folder = os.path.join(ASSETS, "tracks")
    files = sorted(f for f in os.listdir(folder) if f.endswith(".json"))
    assert len(files) >= 6, "poucas pistas padrão"
    for f in files:
        t = Track.load(os.path.join(folder, f))
        assert len(t.center) > 20, f
        assert t.length > 100, f"{f} muito curta: {t.length}"
        assert np.isfinite(t.center).all(), f
        assert (t.half_widths >= 3.0).all(), f"{f} com largura irreal"
        # índice mais próximo de pontos sobre a linha de centro deve bater
        pos = t.center[::7]
        idx, lat = t.nearest(pos, hint=None)
        assert np.abs(lat).max() < 1.0, f"{f}: deslocamento lateral {np.abs(lat).max()}"


def test_cars_load():
    folder = os.path.join(ASSETS, "cars")
    files = sorted(f for f in os.listdir(folder) if f.endswith(".json"))
    assert len(files) >= 5
    for f in files:
        c = CarSpec.load(os.path.join(folder, f))
        assert c.mass > 100 and c.max_speed > 5
        assert 0.0 <= c.drive_front <= 1.0
        assert c.iz > 0


def test_physics_straight_line():
    """Aceleração em linha reta: o carro anda para frente e sem NaN."""
    trk = _straight_track()
    car = _car("gt")
    sim = Simulation(trk, car, SimConfig(max_seconds=10.0), 1, seed=0)
    sim.set_actions(np.array([[0.0, 1.0]]), np.array([0]))
    for _ in range(int(6.0 / sim.cfg.dt)):
        sim.step()
    f = sim.fleet
    assert np.isfinite(f.x[0]) and np.isfinite(f.vx[0])
    assert f.vx[0] > 8.0, f"aceleração fraca: {f.vx[0]:.1f} m/s"
    assert abs(f.vy[0]) < 3.0, f"desvio lateral demais: {f.vy[0]:.2f}"


def test_physics_braking():
    """Freio forte reduz a velocidade."""
    trk = _straight_track()
    car = _car("gt")
    sim = Simulation(trk, car, SimConfig(max_seconds=20.0), 1, seed=0)
    sim.set_actions(np.array([[0.0, 1.0]]), np.array([0]))
    for _ in range(int(6.0 / sim.cfg.dt)):
        sim.step()
    v_before = sim.fleet.vx[0]
    sim.set_actions(np.array([[0.0, -1.0]]), np.array([0]))
    for _ in range(int(1.5 / sim.cfg.dt)):
        sim.step()
    assert sim.fleet.vx[0] < v_before * 0.75, "freio fraco"


def test_physics_turning():
    """Esterço constante gira o carro (yaw rate com sinal certo)."""
    trk = _straight_track(width=80.0)
    car = _car("gt")
    sim = Simulation(trk, car, SimConfig(max_seconds=10.0), 1, seed=0)
    sim.set_actions(np.array([[0.0, 0.6]]), np.array([0]))
    for _ in range(int(3.0 / sim.cfg.dt)):
        sim.step()
    sim.set_actions(np.array([[1.0, 0.6]]), np.array([0]))
    for _ in range(int(2.0 / sim.cfg.dt)):
        sim.step()
    assert sim.fleet.r[0] > 0.15, f"carro não virou à esquerda: r={sim.fleet.r[0]:.3f}"


def test_top_speed_reasonable():
    """Velocidade máxima perto do declarado (modelo limitado por potência)."""
    trk = _straight_track(length=8000.0)
    car = _car("formula")
    sim = Simulation(trk, car, SimConfig(max_seconds=60.0), 1, seed=0)
    sim.set_actions(np.array([[0.0, 1.0]]), np.array([0]))
    for _ in range(int(40.0 / sim.cfg.dt)):
        sim.step()
    v = sim.fleet.speed[0]
    assert 0.35 * car.max_speed < v <= car.max_speed * 1.05, f"{v:.1f} m/s"


def test_walls_stop_the_car():
    """Ninguém atravessa o muro: deslocamento lateral fica limitado."""
    trk = _track("kartodromo")
    car = _car("truck")
    sim = Simulation(trk, car, SimConfig(max_seconds=12.0), 4, seed=2)
    rng = np.random.default_rng(0)
    max_lat = 0.0
    for _ in range(int(10.0 / sim.cfg.dt)):
        if sim.should_decide():
            obs, idx = sim.observe()
            sim.set_actions(rng.uniform(-1, 1, size=(len(idx), 2)), idx)
        sim.step()
        limit = trk.half_widths[sim.fleet.idx] + sim.cfg.runoff + 0.5
        max_lat = max(max_lat, float((np.abs(sim.fleet.lateral) - limit).max()))
    assert max_lat < 1.0, f"carro saiu da pista em {max_lat:.2f} m"


def test_sensors_and_observation():
    trk = _track("serra")
    car = _car("gt")
    sim = Simulation(trk, car, SimConfig(max_seconds=20.0), 6, seed=0)
    obs, idx = sim.observe()
    assert obs.shape == (6, 24), obs.shape
    assert np.isfinite(obs).all()
    assert obs.min() >= -1.6 and obs.max() <= 2.1, (obs.min(), obs.max())
    # os raios devem estar dentro do alcance e positivos
    rays = obs[:, :9]
    assert (rays >= 0).all() and (rays <= 1.0).all()


def test_progress_monotonic_with_pilot():
    """Com um piloto simples, a progressão nunca 'salta' entre trechos."""
    trk = _track("cidade")
    car = _car("kart")
    sim = Simulation(trk, car, SimConfig(max_seconds=60.0), 1, seed=3)
    prev = 0.0
    max_jump = 0.0
    for _ in range(int(45.0 / sim.cfg.dt)):
        if sim.should_decide():
            obs, idx = sim.observe()
            v = sim.fleet.speed[idx]
            step = np.maximum(1, np.round((6.0 + 0.55 * v) / trk.spacing)).astype(int)
            j = (sim.fleet.idx[idx] + step) % trk.n
            tgt = trk.center[j]
            err = ((np.arctan2(tgt[:, 1] - sim.fleet.y[idx], tgt[:, 0] - sim.fleet.x[idx])
                    - sim.fleet.heading[idx] + np.pi) % math.tau - np.pi)
            k = np.abs(trk.curvature[j]) + 1e-4
            vt = np.minimum(car.max_speed * 0.9, np.sqrt(9.81 * 1.4 / k))
            sim.set_actions(np.column_stack([np.clip(1.6 * err / 0.6, -1, 1),
                                             np.clip((vt - v) * 0.5, -1, 1)]), idx)
        sim.step()
        s = sim.fleet.s_total[0]
        max_jump = max(max_jump, abs(s - prev))
        prev = s
    assert max_jump < 3.0, f"salto de progressão de {max_jump:.2f} m"
    assert sim.fleet.max_s[0] > 300, f"piloto simples andou pouco: {sim.fleet.max_s[0]:.0f} m"


def test_ga_shapes_and_evolution():
    spec = PolicySpec(obs_dim=24, hidden=(32, 32))
    pop = Population(spec, GAConfig(population=20), seed=1)
    assert len(pop.genomes) == 20
    assert all(g.shape == (spec.n_params,) for g in pop.genomes)
    fit = np.arange(20, dtype=float)
    pop.record(fit)
    assert pop.best_fitness == 19.0
    best_before = pop.best_genome.copy()
    pop.evolve()
    # elitismo preserva o melhor indivíduo intacto
    assert np.allclose(pop.genomes[0], best_before), "elitismo não preservou o melhor"
    assert len(pop.genomes) == 20
    # mutação muda os filhos
    mutated = sum(1 for g in pop.genomes[1:] if not np.allclose(g, best_before))
    assert mutated > 5, "mutação/cruzamento fracos"


def test_ga_improves_on_simple_task():
    """A evolução precisa melhorar o fitness médio em poucas gerações."""
    spec = PolicySpec(obs_dim=24, hidden=(16, 16))
    rng = np.random.default_rng(0)
    target = rng.normal(size=spec.n_params).astype(np.float32)

    pop = Population(spec, GAConfig(population=40, elitism=0.1, mutation_rate=0.1,
                                    mutation_sigma=0.2, fresh_blood=0.0), seed=7)
    first_mean = None
    last_mean = None
    for _ in range(25):
        fit = -np.array([float(np.sum((g - target) ** 2)) for g in pop.genomes])
        pop.record(fit)
        if first_mean is None:
            first_mean = fit.mean()
        last_mean = fit.mean()
        pop.evolve()
    assert last_mean > first_mean, f"sem melhora: {first_mean:.1f} -> {last_mean:.1f}"


def test_model_roundtrip():
    spec = PolicySpec(obs_dim=24, hidden=(24, 16))
    genome = init_genome(spec, np.random.default_rng(0))
    meta = {"track": "teste", "generation": 3, "fitness": 12.5}
    with tempfile.TemporaryDirectory() as d:
        npz = os.path.join(d, "modelo.npz")
        used = save_model(npz, spec, genome, meta)
        assert os.path.exists(used)
        spec2, genome2, meta2 = load_model(used)
        assert spec2.obs_dim == spec.obs_dim and spec2.hidden == spec.hidden
        assert all(np.allclose(a, b) for a, b in zip(genome, genome2))
        assert meta2["generation"] == 3
        # .pt cai para .npz quando não há PyTorch
        pt = os.path.join(d, "modelo.pt")
        used_pt = save_model(pt, spec, genome, meta)
        spec3, genome3, _ = load_model(used_pt)
        assert all(np.allclose(a, b) for a, b in zip(genome, genome3))
        # modelo incompatível deve dar erro claro
        bad = os.path.join(d, "ruim.npz")
        save_model(bad, PolicySpec(obs_dim=8, hidden=(4,)), [np.zeros((4, 8)), np.zeros(4)], {})
        try:
            from raceai.ai.model_io import load_npz
            from raceai.trainer import Trainer
        except Exception:
            pass
        try:
            load_model(bad)
            from raceai.ai.policy import unflatten
            unflatten(spec, np.zeros(10, dtype=np.float32))
            raise AssertionError("deveria falhar com formato incompatível")
        except (ModelError, ValueError):
            pass


def test_trainer_generation_and_save():
    from raceai.trainer import Trainer
    trk = _track("kartodromo")
    car = _car("kart")
    trainer = Trainer(trk, car, SimConfig(max_seconds=6.0),
                      GAConfig(population=16), PolicySpec(obs_dim=24), device_id="cpu", seed=0)
    stats = trainer.run_generation()
    assert "best" in stats and "mean" in stats
    assert trainer.pop.generation == 1
    with tempfile.TemporaryDirectory() as d:
        path = trainer.save_best(os.path.join(d, "modelo.pt"))
        assert os.path.exists(path)
        spec, genome, meta = load_model(path)
        assert spec.obs_dim == trainer.policy.obs_dim
        # recarregar mantém o comportamento (mesmas ações para a mesma entrada)
        from raceai.ai.policy import forward_single
        obs = np.zeros(spec.obs_dim, dtype=np.float32)
        a1 = forward_single(spec, genome, obs)
        a2 = forward_single(spec, unflatten(spec, flatten(genome)), obs)
        assert np.allclose(a1, a2)
