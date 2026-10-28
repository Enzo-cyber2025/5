#!/usr/bin/env python3
"""Treinador de linha de comando (sem janela) — muito mais rápido que o jogo.

Exemplos
--------
# treinar no kartódromo com 150 indivíduos por 200 gerações
python train_headless.py --track kartodromo --car gt --pop 150 --generations 200 ^
       --device dml --out modelos/gt_kart.pt

# continuar de um modelo já treinado
python train_headless.py --track kartodromo --car gt --init modelos/gt_kart.pt --generations 100

# só avaliar um modelo (sem evoluir) e ver o que ele faz
python train_headless.py --track serra --car gt --load modelos/gt_kart.pt --eval

# ver os backends disponíveis
python train_headless.py --list-devices
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import numpy as np

from raceai.ai.backend import list_devices, resolve_device
from raceai.ai.ga import GAConfig
from raceai.ai.model_io import ModelError, describe, load_model, save_model
from raceai.ai.policy import PolicySpec, unflatten
from raceai.car import CarSpec
from raceai.sim import SimConfig, Simulation
from raceai.track import Track
from raceai.trainer import Trainer

HERE = os.path.dirname(os.path.abspath(__file__))

# Windows com saída redirecionada usa cp1252 e quebra em acentos/ setas.
try:                                    # pragma: no cover
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ASSETS = os.path.join(HERE, "assets")


def asset_dirs():
    return [ASSETS, os.path.join(HERE, "mods")]


def find_asset(kind: str, name: str) -> str:
    """Procura pista/carro por nome ou caminho."""
    if os.path.isfile(name):
        return name
    for base in asset_dirs():
        p = os.path.join(base, kind, f"{name}.json")
        if os.path.isfile(p):
            return p
        p2 = os.path.join(base, kind, name)
        if os.path.isfile(p2):
            return p2
    raise FileNotFoundError(f"{kind} '{name}' não encontrado em {asset_dirs()}")


def list_assets(kind: str):
    out = []
    for base in asset_dirs():
        d = os.path.join(base, kind)
        if os.path.isdir(d):
            out += [os.path.splitext(f)[0] for f in sorted(os.listdir(d))
                    if f.lower().endswith(".json")]
    return sorted(set(out))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Treinador headless RaceAI",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--track", default="kartodromo", help="nome do arquivo em assets/tracks")
    p.add_argument("--car", default="gt", help="nome do arquivo em assets/cars")
    p.add_argument("--generations", type=int, default=100)
    p.add_argument("--pop", type=int, default=120, help="tamanho da população")
    p.add_argument("--device", default="auto", help="auto | cpu | torch-cpu | dml | cuda")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=os.path.join("modelos", "modelo.pt"))
    p.add_argument("--init", default="", help="modelo .pt/.npz para continuar o treino")
    p.add_argument("--load", default="", help="modelo para apenas avaliar (com --eval)")
    p.add_argument("--eval", action="store_true", help="apenas avalia, sem evoluir")
    p.add_argument("--eval-agents", type=int, default=1)
    p.add_argument("--max-seconds", type=float, default=45.0, help="duração de cada geração")
    p.add_argument("--target-laps", type=int, default=0)
    p.add_argument("--dt", type=float, default=1 / 120.0)
    p.add_argument("--decision-interval", type=int, default=4,
                   help="passos de física entre decisões da rede")
    p.add_argument("--rays", type=int, default=9)
    p.add_argument("--ray-range", type=float, default=70.0)
    p.add_argument("--hidden", default="64,64", help="camadas ocultas, ex: 64,64")
    p.add_argument("--elitism", type=float, default=0.10)
    p.add_argument("--tournament", type=int, default=3)
    p.add_argument("--crossover", default="blend", choices=["blend", "uniform"])
    p.add_argument("--crossover-rate", type=float, default=0.90)
    p.add_argument("--mut-rate", type=float, default=0.08)
    p.add_argument("--mut-sigma", type=float, default=0.25)
    p.add_argument("--sigma-decay", type=float, default=0.995)
    p.add_argument("--fresh-blood", type=float, default=0.04)
    p.add_argument("--save-every", type=int, default=0)
    p.add_argument("--export-onnx", default="", help="também exporta para ONNX neste caminho")
    p.add_argument("--csv", default="", help="salva o histórico em CSV")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--list-assets", action="store_true")
    p.add_argument("--threads", type=int, default=0, help="limite de threads do PyTorch")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.list_devices:
        print("Backends disponíveis:")
        for key, desc in list_devices():
            print(f"  {key:10s} {desc}")
        return 0
    if args.list_assets:
        print("pistas:", ", ".join(list_assets("tracks")))
        print("carros:", ", ".join(list_assets("cars")))
        return 0

    if args.threads > 0:
        os.environ.setdefault("OMP_NUM_THREADS", str(args.threads))
        try:
            import torch
            torch.set_num_threads(args.threads)
        except Exception:
            pass

    dev_id, dev_desc = resolve_device(args.device)
    if not args.quiet:
        print(f"[device] {dev_id} — {dev_desc or {k: v for k, v in list_devices()}.get(dev_id, '')}")

    track = Track.load(find_asset("tracks", args.track))
    car = CarSpec.load(find_asset("cars", args.car))
    hidden = tuple(int(h) for h in args.hidden.split(",") if h.strip())

    sim_cfg = SimConfig(max_seconds=args.max_seconds, target_laps=args.target_laps,
                        dt=args.dt, decision_interval=args.decision_interval,
                        n_rays=args.rays, ray_range=args.ray_range)
    ga_cfg = GAConfig(population=args.pop, elitism=args.elitism, tournament=args.tournament,
                      crossover=args.crossover, crossover_rate=args.crossover_rate,
                      mutation_rate=args.mut_rate, mutation_sigma=args.mut_sigma,
                      sigma_decay=args.sigma_decay, fresh_blood=args.fresh_blood)

    # modo avaliação pura
    if args.eval or args.load:
        if not args.load:
            print("erro: --eval precisa de --load modelo", file=sys.stderr)
            return 2
        spec, genome, meta = load_model(args.load)
        policy = PolicySpec(obs_dim=spec.obs_dim, hidden=spec.hidden, act_dim=spec.act_dim)
        sim = Simulation(track, car, sim_cfg, args.eval_agents, seed=args.seed)
        from raceai.ai.backend import create_backend
        backend = create_backend(policy, args.eval_agents, dev_id)
        backend.set_population([genome] * args.eval_agents)
        steps = int(args.max_seconds / sim_cfg.dt)
        t0 = time.perf_counter()
        while not sim.all_dead() and sim.step_count < steps:
            if sim.should_decide():
                obs, idx = sim.observe()
                sim.set_actions(backend.predict(obs, idx), idx)
            sim.step()
        f = sim.fleet
        laps = f.max_s[0] / track.length
        print(f"modelo: {os.path.basename(args.load)} ({describe(meta)})")
        print(f"pista {track.name} · carro {car.name}")
        print(f"distância {f.max_s[0]:.0f} m · voltas {laps:.2f} · "
              f"velocidade média {f.max_s[0] / max(f.time[0], 1e-3):.1f} m/s · "
              f"batidas {int(f.crashes[0])} · tempo {f.time[0]:.1f} s · "
              f"motivo: {f.death_reason[0] or 'vivo'}")
        print(f"avaliação em {time.perf_counter() - t0:.1f} s "
              f"({sim.step_count * sim_cfg.dt / (time.perf_counter() - t0):.1f}x tempo real)")
        return 0

    policy = PolicySpec(obs_dim=args.rays + 15, hidden=hidden)
    trainer = Trainer(track, car, sim_cfg, ga_cfg, policy, device_id=dev_id, seed=args.seed)
    if not args.quiet:
        print(f"pista: {track.name} ({track.length:.0f} m) · carro: {car.name}")
        print(f"população {ga_cfg.population} · genes por indivíduo {policy.n_params} · "
              f"observações {trainer.policy.obs_dim}")
        print(f"backend: {trainer.state.device_desc}")
        if args.init:
            try:
                meta = trainer.load_model(args.init)
                print(f"continuando de {args.init} ({describe(meta)})")
            except ModelError as exc:
                print(f"erro: {exc}", file=sys.stderr)
                return 2

    log = []
    t_start = time.perf_counter()
    gen_times = []

    for g in range(args.generations):
        t0 = time.perf_counter()
        stats = trainer.run_generation()
        gen_times.append(time.perf_counter() - t0)
        log.append(stats)
        if not args.quiet and (g % 1 == 0 or g == args.generations - 1):
            sps = trainer.state.steps_per_second
            print(f"ger {stats.get('generation', g):4d} | melhor {stats['best']:9.1f} | "
                  f"média {stats['mean']:8.1f} | pior {stats['worst']:8.1f} | "
                  f"sigma {stats['sigma']:.3f} | inf {trainer.state.inference_ms:5.2f} ms | "
                  f"{sps:7.0f} passos/s | {gen_times[-1]:5.1f} s")
        if args.save_every and trainer.pop.generation % args.save_every == 0:
            trainer.save_best(args.out)
            if not args.quiet:
                print(f"  -> salvo {args.out}")

    trainer.save_best(args.out)
    total = time.perf_counter() - t_start
    best = trainer.pop.best_fitness
    print("-" * 70)
    print(f"FIM · {args.generations} gerações em {total:.1f} s "
          f"({total / max(args.generations, 1):.2f} s/geração)")
    print(f"melhor fitness {best:.1f} (geração {trainer.pop.best_generation})")
    genome, meta = trainer.best_model_path_info()
    print(f"modelo salvo em {os.path.abspath(args.out)}  [{describe(meta)}]")

    if args.export_onnx:
        try:
            save_model(args.export_onnx, trainer.policy,
                       unflatten(trainer.policy, genome), meta)
            print(f"ONNX exportado em {args.export_onnx}")
        except Exception as exc:
            print(f"falha ao exportar ONNX: {exc}", file=sys.stderr)

    if args.csv:
        os.makedirs(os.path.dirname(os.path.abspath(args.csv)), exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["generation", "best", "mean", "worst", "std", "sigma",
                        "distance", "alive", "crashes", "steps_per_second"])
            for row in log:
                w.writerow([row.get("generation"), round(row.get("best", 0), 2),
                            round(row.get("mean", 0), 2), round(row.get("worst", 0), 2),
                            round(row.get("std", 0), 2), round(row.get("sigma", 0), 4),
                            round(row.get("distance", 0), 1), row.get("alive"),
                            round(row.get("crashes", 0), 2),
                            round(trainer.state.steps_per_second, 1)])
        print(f"histórico em {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
