#!/usr/bin/env python3
"""RaceAI 2D — ponto de entrada do jogo.

Uso
---
python main.py                       # abre o jogo (menu)
python main.py --mode train          # já começa treinando
python main.py --model modelos/x.pt  # já começa dirigindo com o modelo
python main.py --selftest            # testa tudo sem abrir janela (para CI)
python main.py --headless-train 100  # treina 100 gerações sem janela
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

VERSION = "1.0.0"

# Windows com saída redirecionada usa cp1252 e quebra em acentos/ setas.
try:                                    # pragma: no cover
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="RaceAI 2D", add_help=True)
    p.add_argument("--mode", default="menu", choices=["menu", "manual", "ia", "train"])
    p.add_argument("--model", default="", help="modelo .pt/.npz para carregar ao iniciar")
    p.add_argument("--track", default="", help="pista inicial")
    p.add_argument("--car", default="", help="carro inicial")
    p.add_argument("--pop", type=int, default=0, help="tamanho da população inicial")
    p.add_argument("--device", default="", help="auto | cpu | torch-cpu | dml | cuda")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--selftest", action="store_true",
                   help="roda verificações internas sem janela e sai")
    p.add_argument("--headless-train", type=int, default=0, metavar="GERAÇÕES",
                   help="treina N gerações sem abrir janela e salva o modelo")
    p.add_argument("--generations", type=int, default=0, dest="headless_generations",
                   help="atalho para --headless-train")
    p.add_argument("--out", default=os.path.join("modelos", "modelo.pt"))
    p.add_argument("--bench", action="store_true", help="mede o desempenho dos backends e sai")
    p.add_argument("--bench-agents", type=int, default=120)
    p.add_argument("--bench-seconds", type=float, default=3.0)
    p.add_argument("--version", action="store_true")
    return p.parse_args(argv)


def bench(agents: int = 120, seconds: float = 3.0, track_name: str = "kartodromo",
          car_name: str = "gt") -> int:
    """Compara os backends disponíveis (CPU numpy, torch CPU, DirectML...)."""
    import time

    import numpy as np

    from raceai import mods
    from raceai.ai.backend import create_backend, list_devices
    from raceai.ai.ga import GAConfig
    from raceai.ai.policy import PolicySpec, flatten, init_genome, unflatten
    from raceai.car import CarSpec
    from raceai.sim import SimConfig
    from raceai.track import Track
    from raceai.trainer import Trainer

    spec = PolicySpec(obs_dim=9 + 15)
    rng = np.random.default_rng(0)
    genomes = [unflatten(spec, flatten(init_genome(spec, rng))) for _ in range(agents)]
    obs = (rng.random((agents, spec.obs_dim)).astype(np.float32) * 2 - 1)
    idx = np.arange(agents)

    track = None
    for it in mods.load_tracks():
        if it.obj is not None and it.name == track_name:
            track = it.obj
    if track is None:
        items = [i.obj for i in mods.load_tracks() if i.obj]
        track = items[0]
    car = CarSpec.load(os.path.join(mods.assets_dir(), "cars", f"{car_name}.json"))

    print(f"Benchmark — {agents} agentes · rede {spec.obs_dim}->"
          f"{list(spec.hidden)}->{spec.act_dim} ({spec.n_params} pesos)")
    print(f"{'backend':<10} {'inferência':>12} {'simulação':>12} {'x tempo real':>13}  descrição")
    print("-" * 78)
    best = None
    for dev, desc in list_devices():
        if "indisponível" in desc or "indisponible" in desc:
            print(f"{dev:<10} {'—':>12} {'—':>12} {'—':>13}  {desc}")
            continue
        try:
            backend = create_backend(spec, agents, dev)
        except Exception as exc:
            print(f"{dev:<10} {'falhou':>12} {'':>12} {'':>13}  {exc}")
            continue
        backend.set_population(genomes)
        backend.warmup(spec.obs_dim)
        count = 0
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            backend.predict(obs, idx)
            count += 1
        infer_ms = (time.perf_counter() - t0) / max(count, 1) * 1000.0

        trainer = Trainer(track, car, SimConfig(max_seconds=8.0),
                          GAConfig(population=agents), spec, device_id=dev, seed=0)
        t0 = time.perf_counter()
        trainer.step(600)
        el = time.perf_counter() - t0
        sps = 600 / max(el, 1e-6)
        realtime = sps * trainer.sim.cfg.dt
        print(f"{dev:<10} {infer_ms:9.3f} ms {sps:9.0f}/s {realtime:11.1f}x  "
              f"{getattr(backend, 'device_desc', desc)}")
        if best is None or sps > best[1]:
            best = (dev, sps)
    print("-" * 78)
    if best:
        print(f"mais rápido nesta máquina: {best[0]} ({best[1]:.0f} passos/s). "
              f"No jogo, escolha em Configurações ou use --device {best[0]}")
    print("Dica: lotes pequenos (poucos agentes) às vezes são mais rápidos em CPU — "
          "a GPU brilha com populações grandes.")
    return 0


def resolve_asset(kind: str, name: str):
    """Aceita nome simples ('kartodromo') ou caminho de arquivo."""
    from raceai import mods
    if not name:
        return None
    if os.path.isfile(name):
        return name
    for folder in (os.path.join(mods.assets_dir(), kind), os.path.join(mods.mods_dir(), kind)):
        for ext in (".json", ""):
            p = os.path.join(folder, name + ext)
            if os.path.isfile(p):
                return p
    return None


def selftest() -> int:
    """Verificações internas (usado pelo CI para validar o executável)."""
    import numpy as np

    from raceai import mods
    from raceai.ai.backend import list_devices, resolve_device
    from raceai.ai.ga import GAConfig
    from raceai.ai.model_io import load_model, save_model
    from raceai.ai.policy import PolicySpec, flatten, init_genome, unflatten
    from raceai.car import CarSpec
    from raceai.sim import SimConfig, Simulation
    from raceai.track import Track
    from raceai.trainer import Trainer

    print(f"RaceAI 2D {VERSION} — autoteste")
    print(f"python {sys.version.split()[0]} · numpy {np.__version__} · plataforma {sys.platform}")

    tracks = mods.load_tracks()
    cars = mods.load_cars()
    print(f"pistas carregadas: {len(tracks)} · carros: {len(cars)}")
    for t in tracks:
        if t.error:
            print(f"  ERRO pista {t.name}: {t.error}")
    for c in cars:
        if c.error:
            print(f"  ERRO carro {c.name}: {c.error}")
    if not tracks or not cars:
        print("FALHA: nenhuma pista/carro válido")
        return 1

    dev, desc = resolve_device(os.environ.get("RACEAI_DEVICE", "auto"))
    print(f"backend escolhido: {dev} — {desc}")
    print("dispositivos:", ", ".join(f"{k}={v}" for k, v in list_devices()))

    track = tracks[0].obj
    car = cars[0].obj
    cfg = SimConfig(max_seconds=8.0)
    sim = Simulation(track, car, cfg, 8, seed=1)
    steps = 0
    while not sim.all_dead() and steps < int(8.0 / cfg.dt):
        if sim.should_decide():
            obs, idx = sim.observe()
            sim.set_actions(np.zeros((len(idx), 2), dtype=np.float32), idx)
        sim.step()
        steps += 1
    print(f"física: {steps} passos, distância máxima {sim.fleet.max_s.max():.1f} m, "
          f"sem NaN: {not np.isnan(sim.fleet.x).any()}")

    # evolução + salvamento
    trainer = Trainer(track, car, SimConfig(max_seconds=6.0),
                      GAConfig(population=12), PolicySpec(obs_dim=24), device_id=dev, seed=0)
    t0 = time.perf_counter()
    stats = trainer.run_generation()
    print(f"geração 0 em {time.perf_counter() - t0:.2f}s · melhor {stats['best']:.1f} · "
          f"inferência {trainer.state.inference_ms:.2f} ms")
    tmpdir = os.path.join(mods.base_dir(), "_selftest")
    os.makedirs(tmpdir, exist_ok=True)
    path = trainer.save_best(os.path.join(tmpdir, "modelo.pt"))
    spec, genome, meta = load_model(path)
    print(f"modelo salvo/carregado: {os.path.basename(path)} · "
          f"camadas {[g.shape for g in genome]}")
    os.remove(path)
    try:
        os.rmdir(tmpdir)
    except OSError:
        pass
    print("AUTOTESTE OK")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.version:
        print(f"RaceAI 2D {VERSION}")
        return 0
    if args.selftest:
        return selftest()
    if args.bench:
        return bench(args.bench_agents, args.bench_seconds,
                     args.track or "kartodromo", args.car or "gt")

    generations = args.headless_train or args.headless_generations
    if generations:
        sys.argv = [sys.argv[0], "--generations", str(generations),
                    "--out", args.out]
        if args.track:
            sys.argv += ["--track", args.track]
        if args.car:
            sys.argv += ["--car", args.car]
        if args.pop:
            sys.argv += ["--pop", str(args.pop)]
        if args.device:
            sys.argv += ["--device", args.device]
        import train_headless
        return train_headless.main(sys.argv[1:])

    from raceai.app import App
    app = App(width=args.width, height=args.height, start_mode=args.mode,
              model_path=args.model, fullscreen=args.fullscreen)
    if args.track:
        found = resolve_asset("tracks", args.track)
        if found:
            app.settings["track"] = os.path.splitext(os.path.basename(found))[0]
    if args.car:
        found = resolve_asset("cars", args.car)
        if found:
            app.settings["car"] = os.path.splitext(os.path.basename(found))[0]
    if args.pop:
        app.settings["population"] = args.pop
    if args.device:
        app.settings["device"] = args.device
    if any([args.track, args.car, args.pop, args.device]):
        app.reload_mods()
        app.build_trainer()
    app.run()
    return 0


def _log_crash(exc: BaseException) -> None:
    """Registra erros fatais em arquivo (o executável de janela não mostra console)."""
    import traceback

    try:
        folder = os.path.dirname(os.path.abspath(__file__))
        if getattr(sys, "frozen", False):
            folder = os.path.dirname(sys.executable)
        with open(os.path.join(folder, "raceai_erro.log"), "w", encoding="utf-8") as f:
            f.write("RaceAI 2D — relatório de erro\n")
            f.write(f"versão {VERSION} · python {sys.version}\n\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
        print(f"erro registrado em {os.path.join(folder, 'raceai_erro.log')}")
    except Exception:
        pass
    traceback.print_exception(type(exc), exc, exc.__traceback__)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:      # noqa: BLE001 - queremos registrar tudo
        _log_crash(exc)
        raise SystemExit(1)
